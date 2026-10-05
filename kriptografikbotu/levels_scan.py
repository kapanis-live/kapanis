"""Level scan: every 30 minutes, what did the last CLOSED candle do at its support / resistance zones?

Markets: the most traded coins (1h candle, zones from 4h + 1d pivots), BIST (1h candle, zones from daily pivots,
only on trading days) and the US watch list (daily candle, zones from daily pivots).
Events, all from closes (a wick alone is never an event):
  KIRILIM        the candle closed above a resistance zone the previous candle closed under
  DESTEK_KIRILDI the candle closed under a support zone the previous candle closed over
  DESTEKTE       the candle's low reached a support zone and it closed inside or above it (first touch)
  DIRENCTE       the candle's high reached a resistance zone and it closed inside or under it (first touch)

This is information, not a buy suggestion. The history tests say so (config.BUY_SIGNALS, research/README.md): the
breakout rule lost 0.21R per trade, resistance zones turned the price no more often than random levels, and no stop
distance made the breakout entry profitable. Every digest carries that note. One event per asset per candle.
Only zones with at least MIN_TOUCHES pivots count.
"""
import asyncio
import logging

import httpx

import alerts_store
import bist
import config
import market
import universe
import us
import watchlist

log = logging.getLogger(__name__)

STATE = config.DATA_DIR / "seviye_tarama.json"
KEY = "seviye_tarama"
CRYPTO_LIMIT = 60
PARALLEL = 4
ROWS_PER_MARKET = 8
MIN_TOUCHES = 2            # a level the price turned at once is not a level yet
ORDER = {"KIRILIM": 0, "DESTEK_KIRILDI": 1, "DESTEKTE": 2, "DIRENCTE": 3}
LABEL = {"KIRILIM": "🟢 direnç kırıldı", "DESTEK_KIRILDI": "🔴 destek kırıldı", "DESTEKTE": "🛟 destekte tutundu",
         "DIRENCTE": "🧱 dirence takıldı"}
NOTE = ("ℹ️ Bilgi amaçlı, AL/SAT önerisi değil. Geçmiş testte kırılım girişi işlem başına ortalama −0,21R "
        "kaybettirdi; direnç bölgeleri fiyatı rastgele seviyeden daha sık döndürmedi. Kapat: /seviye kapat")


def enabled() -> bool:
    return alerts_store.load_settings().get(KEY, True)


def set_enabled(on: bool):
    s = alerts_store.load_settings()
    s[KEY] = on
    alerts_store.save_settings(s)


def detect(prev, last, zones: dict) -> dict | None:
    """The strongest event of one closed candle. zones: market.sr_zones() computed around the PREVIOUS close, so a
    zone the candle crossed is still on its old side. Pure."""
    res = [z for z in zones.get("direncler") or [] if z["dokunma"] >= MIN_TOUCHES]
    sup = [z for z in zones.get("destekler") or [] if z["dokunma"] >= MIN_TOUCHES]
    vol = bool(last.vol_avg20 == last.vol_avg20 and last.vol_avg20 and last.volume > last.vol_avg20)

    def event(kind, z, nxt):
        return {"tur": kind, "alt": z["alt"], "ust": z["ust"], "dokunma": z["dokunma"], "hacim": vol,
                "sonraki": None if nxt is None else nxt["orta"]}
    broken = [z for z in res if prev.close <= z["ust"] < last.close]
    if broken:
        z = broken[-1]                                           # the highest zone the close cleared
        above = [x for x in res if x["alt"] > last.close]
        return event("KIRILIM", z, above[0] if above else None)
    lost = [z for z in sup if prev.close >= z["alt"] > last.close]
    if lost:
        z = lost[-1]                                             # the lowest zone the close lost
        below = [x for x in sup if x["ust"] < last.close]
        return event("DESTEK_KIRILDI", z, below[0] if below else None)
    for z in sup:
        if last.low <= z["ust"] and last.close >= z["alt"] and prev.low > z["ust"]:
            return event("DESTEKTE", z, res[0] if res else None)
    for z in res:
        if last.high >= z["alt"] and last.close <= z["ust"] and prev.high < z["alt"]:
            return event("DIRENCTE", z, sup[0] if sup else None)
    return None


def _row(mkt: str, code: str, bar, htf, daily, tf: str) -> dict | None:
    if len(bar) < 30 or htf is None or len(htf) < 20:
        return None
    prev, last = bar.iloc[-2], bar.iloc[-1]
    atr = float(htf.atr14.iloc[-1]) if "atr14" in htf else None
    ev = detect(prev, last, market.sr_zones(htf, daily, float(prev.close), atr, top=3))
    if not ev:
        return None
    return {"piyasa": mkt, "kod": code, "tf": tf, "mum": int(last.open_time), "kapanis": float(last.close), **ev}


async def _crypto(client) -> list:
    try:
        import danisman   # the advisor's universe: real spot coins by volume, without the coins Midas does not offer
        pairs = await danisman.universe(client, CRYPTO_LIMIT)
    except Exception as e:
        log.warning("Level scan: advisor universe failed (%s), using the watch list", e)
        pairs = [(c, config.QUOTE) for c in config.WATCHLIST]

    async def one(coin, quote):
        sym = coin + quote
        h1 = market.add_indicators(await market.fetch_klines(client, sym, "1h", limit=120))
        h4 = market.add_indicators(await market.fetch_klines(client, sym, "4h"))
        d1 = market.add_indicators(await market.fetch_klines(client, sym, "1d"))
        return _row("KRIPTO", coin, h1, h4, d1, "1s")
    return [(c, one(c, q)) for c, q in pairs]


async def _bist(client) -> list:
    if not bist.trading_day():
        return []

    async def one(code):
        sym = bist.yahoo_symbol(code)
        h1 = market.add_indicators(await bist.fetch(client, sym, "1h"))
        d1 = market.add_indicators(await bist.fetch(client, sym, "1d"))
        return _row("BIST", code, h1, d1, None, "1s")
    return [(c, one(c)) for c in universe.bist_names()]


async def _us(client) -> list:
    async def one(code):
        d1 = market.add_indicators(await us.fetch(client, code, "1d", bulk=True))
        return _row("ABD", code, d1, d1, None, "1g")
    return [(c, one(c)) for c in watchlist.load().get("ABD", [])]


async def scan(remember: bool = True) -> dict:
    """{"olaylar": new events, "taranan": {market: n}, "hata": n}. remember=False: show everything, mark nothing."""
    seen = alerts_store._load(STATE, {})
    slots = asyncio.Semaphore(PARALLEL)
    events, counts, failed = [], {}, 0

    async def guarded(coro):
        async with slots:
            try:
                return await coro
            except Exception as e:
                log.info("Level scan: %s", str(e)[:120])
                return e
    async with httpx.AsyncClient() as client:
        for mkt, build in (("KRIPTO", _crypto), ("BIST", _bist), ("ABD", _us)):
            jobs = await build(client)
            counts[mkt] = len(jobs)
            for (code, _), got in zip(jobs, await asyncio.gather(*[guarded(c) for _, c in jobs])):
                if isinstance(got, Exception):
                    failed += 1
                elif got and seen.get(f"{mkt}:{code}") != got["mum"]:
                    events.append(got)
                    if remember:
                        seen[f"{mkt}:{code}"] = got["mum"]
    if remember:
        alerts_store._save(STATE, seen)
    return {"olaylar": events, "taranan": counts, "hata": failed}


def _g(x) -> str:
    return "—" if x is None else f"{x:.6g}"


def text(res: dict, empty: bool = False) -> str | None:
    """The digest; None when there is nothing new (unless empty=True, for the command)."""
    ev = res["olaylar"]
    n = res["taranan"]
    head = (f"📍 SEVİYE TARAMASI {alerts_store.now_tr().strftime('%H:%M')} · {n.get('KRIPTO', 0)} coin, "
            f"{n.get('BIST', 0)} BIST, {n.get('ABD', 0)} ABD · kapanan mumlar")
    if not ev:
        return head + "\nYeni seviye olayı yok." if empty else None
    lines = [head]
    for mkt, title in (("KRIPTO", "🪙 Kripto (1 saatlik mum)"), ("BIST", "🇹🇷 BIST (1 saatlik mum, ~15 dk gecikmeli)"),
                       ("ABD", "🇺🇸 ABD (günlük mum)")):
        rows = sorted((e for e in ev if e["piyasa"] == mkt), key=lambda e: (ORDER[e["tur"]], not e["hacim"], -e["dokunma"]))
        if not rows:
            continue
        lines += ["", title]
        for e in rows[:ROWS_PER_MARKET]:
            nxt = "" if e["sonraki"] is None else f" · sıradaki seviye {_g(e['sonraki'])}"
            lines.append(f"{e['kod']} {_g(e['kapanis'])} — {LABEL[e['tur']]} {_g(e['alt'])}–{_g(e['ust'])} "
                         f"({e['dokunma']} dokunma{', hacimli' if e['hacim'] else ''}){nxt}")
        if len(rows) > ROWS_PER_MARKET:
            lines.append(f"+{len(rows) - ROWS_PER_MARKET} olay daha")
    if res["hata"]:
        lines += ["", f"({res['hata']} varlığın verisi alınamadı)"]
    return "\n".join(lines + ["", NOTE])

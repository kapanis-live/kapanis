"""Takip listesi (watchlist): the user's own list per market. Nothing here is analyzed automatically by the AI;
every 30 minutes the bot only ASKS whether to look, and the user picks one, several or a whole market.

Quick status is code-only (no AI, no cost): price, daily and weekly change, trend vs SMA50/200, RSI,
nearest support/resistance zone. The web panel gets the same rows (refreshed at most every 30 minutes).
"""
import asyncio
import json
import logging
import re
import time

import httpx

import alerts_store
import bist
import config
import market
import us
import watch_cards

log = logging.getLogger(__name__)

MARKETS = {"KRIPTO": "🪙 Kripto", "BIST": "🇹🇷 BIST", "ABD": "🇺🇸 ABD"}
DEFAULT = {
    "KRIPTO": "BTC SOL ETH AVAX LINK XRP ARB AAVE HYPE ONDO NEAR UNI BCH SHIB PEPE DOGE".split(),
    "BIST": ("KTLEV ASTOR EUPWR YEOTK AKBNK BIMAS KCHOL THYAO EREGL ENJSA ISCTR MPARK CIMSA CCOLA ENKAI GARAN TOASO TTKOM "
             "FROTO TCELL PGSUS CWENE SAHOL GESAN ARDYZ ATATP MIATK KARTN AYGAZ KORDS TUPRS ASELS ULKER AKSA SASA").split(),
    "ABD": ("NVDA MSFT GOOGL AMZN META AVGO AMD TSM MU ASML ORCL PLTR CEG VST GEV ETN XOM CVX JPM GS V MA COST WMT HD MCD "
            "LLY ABBV ISRG CAT RTX LMT UNP TMUS UBER NEE UNH PG KO PEP FCX LIN DLR O ANET LRCX KLAC PANW CRWD HON DE SHY BIL").split(),
}
CACHE = config.DATA_DIR / "takip_durum.json"
PANEL_TTL = 1800


def load() -> dict[str, list[str]]:
    s = alerts_store.load_settings()
    if "takip_listesi" not in s:
        s["takip_listesi"] = DEFAULT
        alerts_store.save_settings(s)
    return s["takip_listesi"]


def save(lists: dict[str, list[str]]):
    s = alerts_store.load_settings()
    s["takip_listesi"] = lists
    alerts_store.save_settings(s)


def add(mkt: str, codes: list[str]) -> list[str]:
    lists = load()
    new = [c for c in codes if c not in lists[mkt]]
    lists[mkt] = lists[mkt] + new
    save(lists)
    return new


def remove(codes: list[str]) -> list[str]:
    lists = load()
    gone = []
    for mkt in lists:
        for c in codes:
            if c in lists[mkt]:
                lists[mkt].remove(c)
                gone.append(c)
    save(lists)
    return gone


def settings() -> dict:
    return alerts_store.load_settings().get("takip_sor", {"aktif": True, "aralik_dk": 30})


def set_settings(**kw):
    s = alerts_store.load_settings()
    s["takip_sor"] = {**settings(), **kw}
    alerts_store.save_settings(s)


def _nan(x) -> bool:
    return x is None or x != x


def _row(code: str, price: float, prev: float | None, d, bench_6m: float | None = None) -> dict:
    """Quick status from daily bars (d with market.add_indicators). bench_6m: the benchmark's 6-month return (%),
    for the strength column. Pure."""
    last = d.iloc[-1]
    atr = float(last.atr14) if not _nan(last.atr14) else price * 0.03
    zones = market.sr_zones(d, None, price, atr, top=1)
    sup = zones["destekler"][0] if zones["destekler"] else None
    res = zones["direncler"][0] if zones["direncler"] else None
    closed_price = float(last.close)
    closed_zones = market.sr_zones(d, None, closed_price, atr, top=1)
    closed_sup = closed_zones["destekler"][0] if closed_zones["destekler"] else None
    s50, s200 = last.sma50, last.sma200
    if not _nan(s50) and not _nan(s200):
        trend = "↗ güçlü" if price > s50 > s200 else "↘ zayıf" if price < s50 < s200 else "→ karışık"
    else:
        trend = "↗" if not _nan(s50) and price > s50 else "↘" if not _nan(s50) else "az veri"
    week = float(d.close.iloc[-6]) if len(d) > 6 else None
    vol_avg = float(last.vol_avg20) if "vol_avg20" in d and not _nan(last.vol_avg20) else None
    vol_x = round(float(last.volume) / vol_avg, 2) if vol_avg else None  # last closed day vs its 20-day average
    own_6m = watch_cards.six_month_return(d.close)
    rel = round(own_6m - bench_6m, 1) if own_6m is not None and bench_6m is not None else None
    return {"kod": code, "fiyat": price, "gun_yuzde": round((price / prev - 1) * 100, 2) if prev else None,
            "kapanis_fiyat": closed_price, "kapanis_destek": closed_sup["orta"] if closed_sup else None,
            "kapanis_destek_yuzde": closed_sup["uzaklik_yuzde"] if closed_sup else None,
            "hafta_yuzde": round((price / week - 1) * 100, 2) if week else None, "trend": trend,
            "rsi": round(float(last.rsi14)) if not _nan(last.rsi14) else None,
            "destek": sup["orta"] if sup else None, "destek_yuzde": sup["uzaklik_yuzde"] if sup else None,
            "direnc": res["orta"] if res else None, "direnc_yuzde": res["uzaklik_yuzde"] if res else None,
            "hacim_kat": vol_x, "getiri_6a": None if own_6m is None else round(own_6m, 1),
            "guc_6a": rel, "guc": watch_cards.strength(rel)}


async def rows(mkt: str, codes: list[str]) -> list[dict]:
    """Quick status for some codes of one market (concurrent, Tiingo never used: this is a bulk read)."""
    out: dict[str, dict] = {}
    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient() as client:
        tick24 = {}
        if mkt == "KRIPTO":
            syms = [c + config.QUOTE for c in codes]
            r = await client.get(f"{market.BINANCE_BASES[0]}/api/v3/ticker/24hr",
                                 params={"symbols": json.dumps(syms, separators=(",", ":"))}, timeout=20)
            r.raise_for_status()
            tick24 = {x["symbol"]: x for x in r.json()}
        try:    # the benchmark each row is measured against: BTC, BIST 100, S&P 500
            if mkt == "KRIPTO":
                bd = await market.fetch_klines(client, "BTC" + config.QUOTE, "1d", limit=250)
            elif mkt == "BIST":
                bd = await bist.fetch(client, bist.INDEX, "1d")
            else:
                bd = await us.fetch(client, "SPY", "1d", bulk=True)
            bench = watch_cards.six_month_return(bd.close)
        except Exception as e:
            log.warning("Watchlist benchmark %s failed: %s", mkt, e)
            bench = None

        async def one(code):
            async with sem:
                try:
                    if mkt == "KRIPTO":
                        t = tick24[code + config.QUOTE]
                        d = market.add_indicators(await market.fetch_klines(client, code + config.QUOTE, "1d", limit=250))
                        price = float(t["lastPrice"])
                        out[code] = _row(code, price, price / (1 + float(t["priceChangePercent"]) / 100), d,
                                         None if code == "BTC" else bench)      # BTC is the benchmark itself
                    elif mkt == "BIST":
                        q = await bist.day_quote(client, code)
                        d = market.add_indicators(await bist.fetch(client, code, "1d"))
                        out[code] = _row(code, q["fiyat"], q["onceki_kapanis"], d, bench)
                    else:
                        d = market.add_indicators(await us.fetch(client, code, "1d", bulk=True))
                        price = float(d.close.iloc[-1])
                        r = await client.get(us.YAHOO + code, params={"interval": "1d", "range": "5d"}, headers=us.HEADERS, timeout=15)
                        live = r.json()["chart"]["result"][0]["meta"].get("regularMarketPrice")
                        if live:
                            price = float(live)
                        prev = float(d.close.iloc[-2]) if abs(price / float(d.close.iloc[-1]) - 1) < 1e-5 else float(d.close.iloc[-1])
                        out[code] = _row(code, price, prev, d, bench)
                except Exception as e:
                    out[code] = {"kod": code, "hata": str(e)[:60]}
        await asyncio.gather(*(one(c) for c in codes))
    return [out[c] for c in codes if c in out]


MAX_ACCOUNT_CODES = 30
_ACCOUNT_CODE = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,9}$")


def clean_lists(raw) -> dict[str, list[str]]:
    """The lists a site account sent with its command: known markets, plain codes, no repeats, a bounded total. Pure."""
    out: dict[str, list[str]] = {m: [] for m in MARKETS}
    left = MAX_ACCOUNT_CODES
    for mkt in MARKETS:
        codes = raw.get(mkt) if isinstance(raw, dict) else None
        for c in codes if isinstance(codes, list) else []:
            c = str(c).strip().upper()
            if left and _ACCOUNT_CODE.match(c) and c not in out[mkt]:
                out[mkt].append(c)
                left -= 1
    return out


async def account_rows(raw_lists, meta: dict) -> dict | None:
    """The quick status of one site account's watchlist (the same rows the owner's list has), stored under its id.

    Earnings days and fundamental scores are filled only for stocks the bot already keeps them for: no extra requests."""
    uid = meta.get("user_id")
    if not uid:
        return None
    markets: dict[str, list[dict]] = {}
    for mkt, codes in clean_lists(raw_lists).items():
        if not codes:
            markets[mkt] = []
            continue
        try:
            markets[mkt] = await rows(mkt, codes)
        except Exception as e:      # one unknown crypto code fails the whole bulk price request: ask one by one
            log.warning("Account watchlist %s failed in bulk (%s); asking one by one", mkt, e)
            got = []
            for c in codes:
                try:
                    got += await rows(mkt, [c])
                except Exception as e2:
                    got.append({"kod": c, "hata": str(e2)[:60]})
            markets[mkt] = got
    import features
    watch_cards.enrich(markets, features.calendar_for_panel(120), watch_cards.load_scores().get("puanlar") or {},
                       alerts_store.now_tr().date())
    return {"id": f"takip:{uid}", "tur": "takip", "user_id": uid, "zaman": alerts_store.now_tr().isoformat(timespec="seconds"),
            "piyasalar": markets}


def _p(x) -> str:
    if x is None:
        return "—"
    if abs(x) < 0.01:
        return f"{x:.10f}".rstrip("0").rstrip(".")
    return f"{x:,.4f}".rstrip("0").rstrip(".") if abs(x) < 1 else f"{x:,.2f}".rstrip("0").rstrip(".")


def text(mkt: str, rs: list[dict]) -> str:
    unit = {"KRIPTO": "$", "BIST": "₺", "ABD": "$"}[mkt]
    lines = [f"{MARKETS[mkt]} — takip listesi ({len(rs)})" + (" · BIST ~15 dk gecikmeli" if mkt == "BIST" else "")]
    ups = sum(1 for r in rs if (r.get("gun_yuzde") or 0) > 0)
    for r in rs:
        if "hata" in r:
            lines.append(f"⚪ {r['kod']}: veri alınamadı")
            continue
        g, wk = r["gun_yuzde"], r["hafta_yuzde"]
        icon = "🟢" if g and g > 0 else "🔴" if g and g < 0 else "⚪"
        lines.append(f"{icon} {r['kod']} {_p(r['fiyat'])}{unit} " + (f"%{g:+.2f}" if g is not None else "%—")
                     + (f" · hafta %{wk:+.1f}" if wk is not None else "") + f" · {r['trend']}"
                     + (f" · RSI {r['rsi']}" if r["rsi"] is not None else "")
                     + (f" · güç {r['guc']}" if r.get("guc") in ("GÜÇLÜ", "ZAYIF") else "")
                     + (f" · bilanço {r['bilanco_gun']}g" + (" ⚠️" if r.get("bilanco_risk") == "YÜKSEK" else "")
                        if r.get("bilanco_gun") is not None and r["bilanco_gun"] <= 14 else "")
                     + (f" · puan {r['puan']}" if r.get("puan") is not None else "")
                     + (f" · destek {_p(r['destek'])} ({r['destek_yuzde']:+.1f}%)" if r.get("destek") else "")
                     + (f" · direnç {_p(r['direnc'])} ({r['direnc_yuzde']:+.1f}%)" if r.get("direnc") else ""))
    lines.append(f"\n{ups}/{len(rs)} yükselişte. Gün: " + ("24 saatlik değişim" if mkt == "KRIPTO" else
                                                            "son seans (hafta sonu/kapalıyken son kapanış günü)"))
    return "\n".join(lines)


async def panel_rows() -> dict:
    """All lists for the web panel, cached for 30 minutes so the panel never hammers the data sources."""
    try:
        cached = json.loads(CACHE.read_text(encoding="utf-8"))
        if cached.get("surum") == 3 and time.time() - cached["zaman"] < PANEL_TTL:
            return cached
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    lists = load()
    out = {"zaman": time.time(), "surum": 3, "piyasalar": {}}
    for mkt, codes in lists.items():
        try:
            out["piyasalar"][mkt] = await rows(mkt, codes)
        except Exception as e:
            log.warning("Watchlist panel rows %s failed: %s", mkt, e)
            out["piyasalar"][mkt] = []
    import features     # earnings days and fundamental scores come from what the bot already keeps: no extra requests
    watch_cards.enrich(out["piyasalar"], features.calendar_for_panel(120), watch_cards.load_scores().get("puanlar") or {},
                       alerts_store.now_tr().date())
    CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out

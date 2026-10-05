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


def _row(mkt: str, code: str, bar, htf, daily, tf: str, btc_up: bool | None = None) -> dict | None:
    if len(bar) < 30 or htf is None or len(htf) < 20:
        return None
    prev, last = bar.iloc[-2], bar.iloc[-1]
    atr = float(htf.atr14.iloc[-1]) if "atr14" in htf else None
    ev = detect(prev, last, market.sr_zones(htf, daily, float(prev.close), atr, top=3))
    if not ev:
        return None
    bar_atr = float(last.atr14) if last.atr14 == last.atr14 else None
    row = {"piyasa": mkt, "kod": code, "tf": tf, "mum": int(last.open_time), "kapanis": float(last.close),
           "atr": atr if atr and atr == atr else None, "atr_mum": bar_atr, **ev}
    if btc_up is not None:   # the checklist of research/score_lab.py, measured only for coins on 1h candles
        top = htf.iloc[-1]
        row["sartlar"] = {"mum": bool(last.close - last.low >= 0.7 * max(last.high - last.low, 1e-12)),
                          "ana_trend": bool(top.sma200 == top.sma200 and top.close > top.sma200),
                          "ivme": bool(last.close > last.sma20 and last.close > last.sma50), "btc": btc_up}
    return row


async def _crypto(client) -> list:
    try:
        import danisman   # the advisor's universe: real spot coins by volume, without the coins Midas does not offer
        pairs = await danisman.universe(client, CRYPTO_LIMIT)
    except Exception as e:
        log.warning("Level scan: advisor universe failed (%s), using the watch list", e)
        pairs = [(c, config.QUOTE) for c in config.WATCHLIST]

    b = market.add_indicators(await market.fetch_klines(client, "BTC" + config.QUOTE, "1h", limit=120)).iloc[-1]
    btc_up = bool(b.close > b.sma50)

    async def one(coin, quote):
        sym = coin + quote
        h1 = market.add_indicators(await market.fetch_klines(client, sym, "1h", limit=120))
        h4 = market.add_indicators(await market.fetch_klines(client, sym, "4h"))
        d1 = market.add_indicators(await market.fetch_klines(client, sym, "1d"))
        return _row("KRIPTO", coin, h1, h4, d1, "1s", btc_up)
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


# ---------------- the long setups among the events, checked by code and shown as information ----------------
VERDICT = "BİLGİ"       # never AL: no level rule has paid in a history test; a rule that passes one may earn the word
SIGNALS_PER_SCAN = 6
STRETCH_ATR = 1.5      # a close further than this many candle ATRs past the zone is chasing
STOP_PAD_ATR = 0.25    # the stop sits this far (zone timeframe ATR) under the zone
KEEP_DAYS = 7          # records with a failed rule older than this are dropped from the decision log
EVIDENCE = ("Bilgi amaçlı, AL önerisi değil: seviye kuralları geçmiş testte kazandırmadı (kırılım −0,13R, kırılım sonrası "
            "dönüş −0,04R, destekte alım −0,03R). Sonuçlar kural karnesinde canlı tutulur (/karne). Bot işlem yapmaz.")


# research/score_lab.py, development period (2023-01..2024-09; the two later years agree within a few points):
# points out of seven -> (% of setups that closed with a profit, mean net R). Measured on coins, 1h candles, with this
# module's stop and target. The numbers FALL as the points rise: on an hourly candle "everything looks strong" is late.
HISTORY = {"KIRILIM": ((2, 59, -0.09), (3, 57, -0.19), (4, 54, -0.26), (5, 53, -0.27), (7, 45, -0.26)),
           "DESTEKTE": ((2, 54, +0.03), (3, 52, +0.01), (4, 50, -0.15), (5, 46, -0.31), (7, 46, -0.01))}
CHECKS = ("hacim", "güçlü kapanış", "4s trend", "1s ivme", "BTC", "R/R ≥ 1,5", "geniş stop")


def measured(e: dict, rr: float, stop: float) -> dict | None:
    """{puan, var, isabet, R} for a coin setup: its points on the seven-condition checklist and what setups with
    those points did in the history test. None where it was not measured (stocks, daily candles)."""
    c = e.get("sartlar")
    if not c or e["tur"] not in HISTORY or not e.get("atr_mum"):
        return None
    flags = (e["hacim"], c["mum"], c["ana_trend"], c["ivme"], c["btc"], rr >= 1.5, e["kapanis"] - stop >= 1.5 * e["atr_mum"])
    pts = sum(flags)
    _, hit, r = next(g for g in HISTORY[e["tur"]] if pts <= g[0])
    return {"puan": pts, "var": [n for n, f in zip(CHECKS, flags) if f], "isabet": hit, "R": r}


def plan(e: dict, min_rr: float) -> dict | None:
    """Stop, target, R/R and the rule-by-rule check of a long setup (KIRILIM, DESTEKTE); None for the other events.
    gecti = every rule below passes. That is a description of the setup, not a suggestion. Pure."""
    if e["tur"] not in ("KIRILIM", "DESTEKTE") or not e.get("atr"):
        return None
    close, atr = e["kapanis"], e["atr"]
    stop = e["alt"] - STOP_PAD_ATR * atr
    target = e["sonraki"] if e["sonraki"] and e["sonraki"] > close else close + 2 * atr
    if not close > stop:
        return None
    rr = (target - close) / (close - stop)
    stretch = (close - e["ust"]) / e["atr_mum"] if e.get("atr_mum") else None
    rules = [
        {"kural": "kapanış teyidi", "durum": "gecti",
         "detay": ("kapanış bölgenin üstünde" if e["tur"] == "KIRILIM" else "fitil bölgeye değdi, kapanış bölgenin içinde/üstünde")
                  + f" ({e['alt']:.6g}–{e['ust']:.6g}, {e['dokunma']} dokunma)"},
        {"kural": "hacim", "durum": "gecti" if e["hacim"] else "kaldi",
         "detay": "mum hacmi 20 mum ortalamasının " + ("üstünde" if e["hacim"] else "altında")},
        {"kural": "R/R", "durum": "gecti" if rr >= min_rr else "kaldi",
         "detay": f"R/R {rr:.2f}, eşik {min_rr:g} (hedef " + ("sıradaki seviye" if e["sonraki"] and e["sonraki"] > close else "2 ATR") + ")"},
    ]
    if e["tur"] == "KIRILIM" and stretch is not None:
        rules.append({"kural": "kovalama", "durum": "gecti" if stretch <= STRETCH_ATR else "kaldi",
                      "detay": f"kapanış bölgenin {stretch:.1f} ATR üstünde, sınır {STRETCH_ATR:g}"})
    failed = [r["kural"] for r in rules if r["durum"] == "kaldi"]
    return {"iptal": round(stop, 8), "hedef": round(target, 8), "rr": round(rr, 2), "kurallar": rules, "kalan": failed,
            "gecti": not failed, "olcum": measured(e, rr, stop)}


def _ids(e: dict) -> tuple[str, str]:
    if e["piyasa"] == "BIST":
        return bist.yahoo_symbol(e["kod"]), bist.yahoo_symbol(e["kod"])
    if e["piyasa"] == "ABD":
        return us.key(e["kod"]), us.key(e["kod"])
    return f"{e['kod']}/{config.QUOTE}", e["kod"] + config.QUOTE


def record(events: list[dict]) -> list[dict]:
    """Write the scan's long setups to the decision log (the site's Signals page) as information: no Aldım / Pas,
    no size. Setups whose rules all pass first; at most SIGNALS_PER_SCAN. Their outcomes are still followed, so the
    rule report (/karne) shows what these rules do live. Returns the logged records."""
    import positions
    cand = []
    for e in events:
        min_rr = {"BIST": config.BIST_MIN_RR, "ABD": config.US_MIN_RR}.get(e["piyasa"], config.MIN_RR_RISK_OFF)
        p = plan(e, min_rr)
        if p:
            cand.append((e, p))
    cand.sort(key=lambda x: (not x[1]["gecti"], -x[0]["dokunma"], -x[1]["rr"]))
    out = []
    for e, p in cand[:SIGNALS_PER_SCAN]:
        pair, symbol = _ids(e)
        ok = p["gecti"]
        unit = "TL" if e["piyasa"] == "BIST" else "USD"
        head = (f"📍 {e['kod']} ({'1 saatlik' if e['tf'] == '1s' else 'günlük'} mum): {LABEL[e['tur']]} "
                f"{_g(e['alt'])}–{_g(e['ust'])} — " + ("kuralların hepsi geçti" if ok else "eksik: " + ", ".join(p["kalan"])))
        m = p["olcum"]
        past = ("📊 Geçmiş ölçüm yok: bu tablo yalnız coinlerde, 1 saatlik mumda ölçüldü." if not m else
                f"📊 Geçmiş ölçüm: 7 şarttan {m['puan']}'i var ({', '.join(m['var']) or 'hiçbiri'}). Bu puandaki kurulumların "
                f"%{m['isabet']}'i kârla kapandı, ortalama {m['R']:+.2f}R (35.000 olay, 2023-2026). "
                "Not: şart sayısı arttıkça geçmiş sonuç kötüleşti, iyileşmedi.")
        if m:
            head += f" · geçmişte %{m['isabet']} kârla kapandı (ort. {m['R']:+.2f}R)"
        lines = [head, f"Kapanış {_g(e['kapanis'])} {unit} | iptal {_g(p['iptal'])} | hedef {_g(p['hedef'])} | R/R {p['rr']:.2f}", "",
                 *[f"{'✅' if r['durum'] == 'gecti' else '❌'} {r['kural']}: {r['detay']}" for r in p["kurallar"]], "", past, "", EVIDENCE]
        out.append(positions.log_decision({
            "pair": pair, "symbol": symbol, "timeframe": "1h" if e["tf"] == "1s" else "1d", "yon": "ABOVE", "alarm_id": 0,
            "piyasa": e["piyasa"], "kaynak": "seviye", "kapanis": e["kapanis"], "mum_ms": e["mum"], "iptal": p["iptal"],
            "hedef": p["hedef"], "karar": VERDICT,
            "analiz": "\n".join(lines), "uyarilar": [f"{r['kural']}: {r['detay']}" for r in p["kurallar"] if r["durum"] == "kaldi"],
            "kapi": {"ok": ok, "rr": p["rr"], "kurallar": p["kurallar"], "kalan": p["kalan"], "risk_off": True,
                     "hacim_ok": e["hacim"], "olcum": m}}))
    prune()
    return out


def prune():
    """Drop this scan's old records that had a failed rule; the ones whose rules all passed stay for the rule report."""
    import positions
    from datetime import datetime, timedelta
    cut = alerts_store.now_tr() - timedelta(days=KEEP_DAYS)
    items = positions.load_decisions()
    for d in items:        # records an earlier version logged as AL / PAS: they were never tested buy signals
        if d.get("kaynak") == "seviye" and d["karar"] != VERDICT and not d.get("aksiyon"):
            d["karar"] = VERDICT
            d.pop("kademe_usd", None)
    keep = [d for d in items if not (d.get("kaynak") == "seviye" and not (d.get("kapi") or {}).get("ok") and not d.get("aksiyon")
                                     and datetime.fromisoformat(d["zaman"]) < cut)]
    if keep != positions.load_decisions():
        alerts_store._save(config.DECISIONS_FILE, keep)


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

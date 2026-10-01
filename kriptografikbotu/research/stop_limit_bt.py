"""History test of the order-planning layer (stop_limit.py). Writes stop_limit_results.json; touches nothing else.

Same standard as engine.py (daily bars, universes with dead coins, costs, random twins with the same time in the
market, buy & hold, last 365 days locked) with two differences this layer needs:
- three periods: DEVELOPMENT (everything before the last 730 days) is where parameters are chosen, VALIDATION (the
  365 days before the locked year) only confirms the choice, LOCKED (last 365 days) is scored once at the end;
- intraday fills, because a stop-limit order does not wait for the close (see simulate()).

Order life: the plan is computed at the close of day j from data up to j and is the working order for day j+1.
Fill on day j+1: open above the limit -> filled at the limit only if the day's low came back to it, else missed;
open between trigger and limit -> the open (+ slippage, never above the limit); otherwise the trigger (+ slippage).
Stops are touch orders: a gap through the stop exits at the open; a low under the stop on the ENTRY day counts as a
stop-out (the bar does not say which came first, so the worse case is assumed).
Cost per side: engine.COST (crypto 0.1 %, BIST 0.2 %); slippage on every stop fill: crypto 0.05 %, BIST 0.10 %.

    python research/stop_limit_bt.py
"""
import asyncio
import json
import pathlib
import random
import sys
import time
from dataclasses import asdict, replace
from types import SimpleNamespace

import httpx
import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import engine  # noqa: E402
import regime  # noqa: E402
import stop_limit as sl  # noqa: E402
import strategies  # noqa: E402

SLIP = {"KRIPTO": 0.0005, "BIST": 0.0010}
START = max(engine.WARMUP, sl.LOOKBACK)
VALIDATION_DAYS = 365
MIN_TRADES = 100      # a variant with fewer development trades cannot be chosen
MARGIN = 0.5          # a variant replaces the default only if it is this many %/yr better in development
SEED = 11


# ---------------- data ----------------
async def load_named(market: str):
    """{name: raw OHLCV frame}, labelled benchmark frame, raw benchmark frame."""
    raw = {}
    async with httpx.AsyncClient() as client:
        if market == "KRIPTO":
            for coin in engine.CRYPTO:
                try:
                    df = await engine.crypto_daily(client, coin)
                    if len(df) > engine.WARMUP + 120:
                        raw[coin] = df
                except Exception:
                    pass
            bench_raw = raw["BTC"]
        else:
            for s in engine.BIST:
                raw[s] = await engine.yahoo_daily(client, f"{s}.IS")
            bench_raw = await engine.yahoo_daily(client, "XU100.IS")
    return raw, regime.label(engine.indicators(bench_raw.copy())), bench_raw


def precompute(b) -> SimpleNamespace:
    """Everything that does not depend on the order parameters, for every bar (levels known at that bar's close)."""
    n = b.n
    P = SimpleNamespace(res=np.full(n, np.nan), tch=np.zeros(n, dtype=int), swing=np.full(n, np.nan),
                        score=np.full(n, -99), cl_lvl=np.full((n, sl.MAX_CLUSTERS), np.nan),
                        cl_tch=np.zeros((n, sl.MAX_CLUSTERS), dtype=int),
                        trail_regime=np.array([sum(sl.trail_band(r)) / 2 for r in b.regime]))
    for i in range(START, n):
        cl = sl.clusters_at(b, i)
        m = sl.main_resistance(cl)
        if m is None:
            continue
        for k, (lvl, t, _) in enumerate(cl):
            P.cl_lvl[i, k], P.cl_tch[i, k] = lvl, t
        P.res[i], P.tch[i], last = cl[m]
        P.swing[i] = sl.swing_low_at(b, i)
        P.score[i] = sl.score_at(b, i, P.res[i], last, detail=False)[0]
    return P


# ---------------- simulation ----------------
def simulate(b, P, p: sl.Params, market: str, cost: float | None = None, slip: float | None = None) -> dict:
    """One asset, one parameter set -> trades, daily strategy returns, days in the market, fill statistics."""
    cost = engine.COST[market] if cost is None else cost
    slip = SLIP[market] if slip is None else slip
    n, o, h, l, c, atr = b.n, b.o, b.h, b.l, b.c, b.atr
    dret, held, trades = np.zeros(n), np.zeros(n), []
    st = {"aday": 0, "stop_seviyesi_yok": 0, "risk_cok_buyuk": 0, "rr_yetersiz": 0, "emir": 0, "bosluk_kacti": 0,
          "bosluk_limitten_doldu": 0, "doldu": 0}
    ok = np.isfinite(P.res) & (P.score >= p.min_score) & (b.regime != "PANIK")
    if p.require_two_touches:
        ok &= P.tch >= 2
    limit_order = p.entry_mode == "stop_limit"
    if limit_order:
        trig, lim = sl.entry_order(P.res, atr, p)
        cand = np.flatnonzero(ok[:-1] & (h[1:] >= trig[:-1]))
    else:
        cand = np.flatnonzero(ok[:-1] & (c[1:] > P.res[:-1]))
    tm = P.trail_regime if p.trail == "rejim" else np.full(n, float(p.trail))
    free = 0
    for j in cand:
        if j < free:
            continue
        e = j + 1
        ref = j if limit_order else e            # the bar whose close the levels come from
        plan_entry = trig[j] if limit_order else c[e]
        st["aday"] += 1
        s = sl.stop_level(plan_entry, atr[ref], P.swing[ref], b.sma20[ref], b.sma50[ref], p)
        if s is None:
            st["stop_seviyesi_yok"] += 1
            continue
        stop = s[0]
        if not 0 < plan_entry - stop <= p.max_risk_pct * plan_entry:
            st["risk_cok_buyuk"] += 1
            continue
        cl = [(P.cl_lvl[ref, k], P.cl_tch[ref, k], 0) for k in range(sl.MAX_CLUSTERS) if P.cl_lvl[ref, k] == P.cl_lvl[ref, k]]
        tp1, _, rr1, _, technical = sl.targets(plan_entry, stop, cl, lim[j] if limit_order else c[e])
        if rr1 is not None and rr1 < p.min_rr:
            st["rr_yetersiz"] += 1
            continue
        st["emir"] += 1
        if not limit_order:
            fill = c[e]
        elif o[e] > lim[j]:
            if l[e] > lim[j]:
                st["bosluk_kacti"] += 1
                continue
            fill = lim[j]
            st["bosluk_limitten_doldu"] += 1
        else:
            fill = min(max(o[e], trig[j]) * (1 + slip), lim[j])
        st["doldu"] += 1
        buy = fill * (1 + cost)
        w, S, hh, took, x, net = 1.0, stop, h[e], False, None, 0.0

        def close_out(k, px, weight, prev):
            nonlocal net
            net += weight * (px * (1 - cost) / buy - 1)
            dret[k] += weight * (px * (1 - cost) / prev - 1)

        if limit_order and l[e] <= S:           # stopped on the entry day (worst case assumed)
            close_out(e, min(S, fill) * (1 - slip), 1.0, buy)
            x = e
        else:
            dret[e] += c[e] / buy - 1
            held[e] = 1
            S = max(S, hh - tm[e] * atr[e])
            k = e + 1
            while k < n:
                if o[k] <= S:
                    close_out(k, o[k] * (1 - slip), w, c[k - 1])
                elif l[k] <= S:
                    close_out(k, S * (1 - slip), w, c[k - 1])
                else:
                    if p.tp_mode == "yarim" and not took and h[k] >= tp1:
                        close_out(k, max(tp1, o[k]), 0.5, c[k - 1])   # resting limit sell: no slippage
                        w, took = 0.5, True
                    dret[k] += w * (c[k] / c[k - 1] - 1)
                    held[k] = 1
                    hh = max(hh, h[k])
                    S = max(S, hh - tm[k] * atr[k])
                    k += 1
                    continue
                x = k
                break
            if x is None:                        # data ended while holding: valued at the last close, cost charged
                x = n - 1
                net += w * (c[x] * (1 - cost) / buy - 1)
                dret[x] -= w * cost
        trades.append({"e": e, "x": x, "gun": x - e, "r": net, "R": net * buy / (fill - stop), "rejim": b.regime[j],
                       "skor": int(P.score[ref]), "temas": int(P.tch[ref]), "ayni_gun_stop": x == e,
                       "direnc_altinda_kapandi": bool(limit_order and c[e] < P.res[j]), "teknik_hedef": technical})
        free = x
    return {"trades": trades, "dret": dret, "held": held, "st": st}


# ---------------- scoring ----------------
def periods(last_day) -> dict:
    lock = np.datetime64(last_day - pd.Timedelta(days=engine.HOLDOUT_DAYS))
    val = np.datetime64(last_day - pd.Timedelta(days=engine.HOLDOUT_DAYS + VALIDATION_DAYS))
    return {"gelistirme": (None, val), "validation": (val, lock), "kilitli_son_12_ay": (lock, None)}


def _mask(day, lo, hi):
    m = np.ones(len(day), dtype=bool)
    m[:START] = False
    if lo is not None:
        m &= day >= lo
    if hi is not None:
        m &= day < hi
    return m


def _med(xs, pct=True):
    xs = [x for x in xs if x is not None]
    return round(float(np.median(xs)) * (100 if pct else 1), 1) if xs else None


def trade_stats(ts: list[dict]) -> dict:
    if not ts:
        return {"islem": 0}
    r, R = np.array([t["r"] for t in ts]), np.array([t["R"] for t in ts])
    boot = np.random.default_rng(SEED).choice(R, size=(2000, len(R))).mean(axis=1)
    gains, losses = r[r > 0].sum(), -r[r <= 0].sum()
    return {"islem": len(ts), "isabet_%": round(float((r > 0).mean()) * 100, 1), "ort_R": round(float(R.mean()), 3),
            "ort_R_%95": [round(float(np.percentile(boot, 2.5)), 3), round(float(np.percentile(boot, 97.5)), 3)],
            "ort_net_%": round(float(r.mean()) * 100, 2),
            "kar_faktoru": round(float(gains / losses), 2) if losses > 0 else None,
            "ort_gun": round(float(np.mean([t["gun"] for t in ts])), 1),
            "giris_gunu_stop_%": round(float(np.mean([t["ayni_gun_stop"] for t in ts])) * 100, 1),
            "giris_gunu_direnc_altinda_kapanis_%": round(float(np.mean([t["direnc_altinda_kapandi"] for t in ts])) * 100, 1)}


def summarize(runs: list[dict], market: str, spans: dict, twins: bool, cost: float | None = None) -> dict:
    """Per period: median yearly result per asset, buy & hold, random twins (same exposure and holding length),
    drawdown, time in the market, and the trades that were ENTERED in the period."""
    cost = engine.COST[market] if cost is None else cost
    dpy, rng, out = engine.DPY[market], random.Random(SEED), {}
    for tag, (lo, hi) in spans.items():
        rows, ts = {k: [] for k in ("kural", "al_tut", "rastgele", "yuzdelik", "dusus", "piyasada")}, []
        for run in runs:
            b = run["b"]
            m = _mask(b.day, lo, hi)
            ts += [t for t in run["trades"] if m[t["e"]]]
            days = int(m.sum())
            if days <= 60:
                continue
            eq = np.concatenate([[1.0], np.cumprod(1 + run["dret"][m])])
            y = engine.yearly(eq, days, dpy)
            if y is None:
                continue
            close, pos = b.c[m], run["held"][m]
            rows["kural"].append(y)
            rows["al_tut"].append(engine.yearly(engine.equity(close, np.ones(days), cost)[0], days, dpy))
            rows["dusus"].append(float((eq / np.maximum.accumulate(eq) - 1).min()))
            rows["piyasada"].append(float(pos.mean()))
            if twins:
                exp = float(pos.mean())
                lens = np.diff(np.flatnonzero(np.diff(np.concatenate([[0], pos, [0]]))))
                avg_len = float(np.mean(lens[::2])) if exp > 0 and len(lens) else 1.0
                tw = [t for t in (engine.yearly(engine.equity(close, engine.random_twin(days, exp, avg_len, rng), cost)[0],
                                                days, dpy) for _ in range(engine.RANDOM_DRAWS)) if t is not None]
                rows["rastgele"].append(float(np.median(tw)) if tw else None)
                rows["yuzdelik"].append(float(np.mean([y > t for t in tw])) if tw else None)
        pct = [x for x in rows["yuzdelik"] if x is not None]
        out[tag] = {"varlik": len(rows["kural"]), "kural_yillik_%": _med(rows["kural"]), "al_tut_%": _med(rows["al_tut"]),
                    "rastgele_%": _med(rows["rastgele"]) if twins else None,
                    "rastgeleyi_gecen_varlik_%": round(float(np.mean(pct)) * 100) if pct else None,
                    "en_buyuk_dusus_%": _med(rows["dusus"]), "piyasada_%": _med(rows["piyasada"]), "islemler": trade_stats(ts)}
    return out


def run_market(data: list, market: str, p: sl.Params, spans: dict, twins: bool = False, **kw) -> tuple[dict, list]:
    runs = [{"b": b, **simulate(b, P, p, market, **kw)} for _, b, P in data]
    fills: dict = {}
    for r in runs:
        for k, v in r["st"].items():
            fills[k] = fills.get(k, 0) + v
    res = summarize(runs, market, spans, twins, kw.get("cost"))
    res["emir_istatistigi_tum_donem"] = fills
    return res, runs


def passes(t: dict, share: int) -> bool:
    return (t.get("kural_yillik_%") is not None and t.get("rastgele_%") is not None
            and t["kural_yillik_%"] > t["rastgele_%"] and (t.get("rastgeleyi_gecen_varlik_%") or 0) >= share)


# ---------------- parameter search (development period only) ----------------
def grid(default: sl.Params) -> dict:
    g = _grid()
    for rows in g.values():   # the market's own default is always one of the variants
        keys = rows[0][1].keys()
        if not any(all(getattr(default, k) == v for k, v in ch.items()) for _, ch in rows):
            rows.append(("varsayılan", {k: getattr(default, k) for k in keys}))
    return g


def _grid() -> dict:
    return {
        "giris_tamponu": [(f"%{a * 100:g} / {k:g} ATR", {"pct_buffer": a, "atr_buffer": k})
                          for a in (0.0, 0.0010, 0.0015, 0.0025, 0.0040) for k in (0.0, 0.05, 0.10, 0.20)],
        "stop": [(m, {"stop_mode": m}) for m in ("atr1", "atr1.5", "atr2", "swing", "swing_tampon", "kombine")],
        "iz_suren_stop": [(f"{t} ATR" if t != "rejim" else "rejime göre", {"trail": t}) for t in (1.5, 2.0, 2.5, 3.0, "rejim")],
        "min_rr": [(f"{r:g}" if r else "yok", {"min_rr": r}) for r in (0.0, 1.0, 1.5, 2.0, 2.5)],
        "min_skor": [("yok" if s < 0 else f">= {s}", {"min_score": s}) for s in (-99, 4, 7)],
        "temas": [("tek temas da olur", {"require_two_touches": False}), ("en az 2 temas", {"require_two_touches": True})],
        "kar_al": [("yalnız iz süren stop", {"tp_mode": "iz"}), ("TP1'de yarısı", {"tp_mode": "yarim"})],
    }


def search(data: list, market: str, default: sl.Params, spans: dict) -> tuple[sl.Params, dict, dict]:
    """One pass, one dimension at a time, carrying each choice forward. Only the development period is scored.
    The default stays unless a variant is MARGIN %/yr better (median per asset) with at least MIN_TRADES trades."""
    dev = {"gelistirme": spans["gelistirme"]}
    current, table, chosen = default, {}, {}
    for dim, variants in grid(default).items():
        rows = []
        for label, change in variants:
            res, _ = run_market(data, market, replace(current, **change), dev)
            d = res["gelistirme"]
            rows.append({"etiket": label, "degisiklik": change, "varsayilan": all(getattr(default, k) == v for k, v in change.items()),
                         "kural_yillik_%": d["kural_yillik_%"], "piyasada_%": d["piyasada_%"],
                         "en_buyuk_dusus_%": d["en_buyuk_dusus_%"], **d["islemler"]})
        base = next(r for r in rows if r["varsayilan"])
        ok = [r for r in rows if r.get("islem", 0) >= MIN_TRADES and r["kural_yillik_%"] is not None]
        best = max(ok, key=lambda r: r["kural_yillik_%"]) if ok else base
        pick = best if base["kural_yillik_%"] is None or best["kural_yillik_%"] >= base["kural_yillik_%"] + MARGIN else base
        current = replace(current, **pick["degisiklik"])
        table[dim], chosen[dim] = rows, pick["etiket"]
        print(f"  {market} {dim}: seçilen {pick['etiket']} ({pick['kural_yillik_%']} %/yıl, ort {pick.get('ort_R')}R, "
              f"{pick.get('islem')} işlem) | varsayılan {base['etiket']} ({base['kural_yillik_%']} %/yıl)", flush=True)
    return current, table, chosen


# ---------------- checks ----------------
def lookahead_check(raw: dict, bench_raw: pd.DataFrame, data: list, market: str, p: sl.Params, samples: int = 40) -> dict:
    """1) Levels: rebuild everything from data cut at a random bar (asset AND benchmark) and compare with the values the
    test used for that bar. 2) Trades: cut the data, rerun, and compare every trade that ended before the cut."""
    rng, bad, checked = random.Random(SEED), [], 0
    names = [n for n, _, _ in data]
    lookup = {n: (b, P) for n, b, P in data}
    for _ in range(samples):
        name = rng.choice(names)
        b, P = lookup[name]
        i = rng.randrange(START, b.n)
        cut_day = pd.Timestamp(b.day[i])
        braw = bench_raw[pd.to_datetime(bench_raw.t, unit="ms").dt.normalize() <= cut_day].copy()
        bench_cut = regime.label(engine.indicators(braw))
        bc = sl.prepare(raw[name].iloc[:i + 1], bench_cut)
        cl = sl.clusters_at(bc, i)
        m = sl.main_resistance(cl)
        got = (np.nan, 0, np.nan, -99) if m is None else (
            cl[m][0], cl[m][1], sl.swing_low_at(bc, i), sl.score_at(bc, i, cl[m][0], cl[m][2], detail=False)[0])
        want = (P.res[i], int(P.tch[i]), P.swing[i], int(P.score[i]))
        checked += 1
        if not all((a != a and w != w) or abs(a - w) <= 1e-9 * max(1.0, abs(w)) for a, w in zip(got, want)):
            bad.append({"varlik": name, "bar": i, "kesik": [float(x) for x in got], "tam": [float(x) for x in want]})
    trades_checked, trade_bad = 0, 0
    for name in rng.sample(names, min(8, len(names))):
        b, P = lookup[name]
        cut = rng.randrange(START + 200, b.n) if b.n > START + 201 else b.n
        full = [t for t in simulate(b, P, p, market)["trades"] if t["x"] < cut - 1]
        bench = regime.label(engine.indicators(bench_raw.copy()))
        bc = sl.prepare(raw[name].iloc[:cut], bench)
        part = [t for t in simulate(bc, precompute(bc), p, market)["trades"] if t["x"] < cut - 1]
        trades_checked += len(full)
        trade_bad += len(full) != len(part) or any(a["e"] != z["e"] or a["x"] != z["x"] or abs(a["r"] - z["r"]) > 1e-9
                                                    for a, z in zip(full, part))
    return {"seviye_kontrolu": checked, "seviye_farki": len(bad), "ornek_farklar": bad[:5],
            "islem_kontrolu": trades_checked, "islem_farki_olan_varlik": int(trade_bad), "gecti": not bad and not trade_bad}


def cost_check(data: list, market: str, p: sl.Params, spans: dict) -> dict:
    """The same trades with no cost, the standard cost and double cost: the result must fall as the cost rises."""
    dev, out = {"gelistirme": spans["gelistirme"]}, {}
    c0, s0 = engine.COST[market], SLIP[market]
    for label, mult in (("maliyetsiz", 0.0), ("standart", 1.0), ("iki_kat", 2.0)):
        d = run_market(data, market, p, dev, cost=c0 * mult, slip=s0 * mult)[0]["gelistirme"]
        out[label] = {"komisyon_%": c0 * mult * 100, "kayma_%": s0 * mult * 100, "kural_yillik_%": d["kural_yillik_%"],
                      "ort_R": d["islemler"].get("ort_R"), "ort_net_%": d["islemler"].get("ort_net_%"),
                      "islem": d["islemler"].get("islem")}
    a, s, z = (out[k]["ort_net_%"] for k in ("maliyetsiz", "standart", "iki_kat"))
    out["gecti"] = None not in (a, s, z) and a > s > z
    return out


# ---------------- main ----------------
def study(market: str) -> dict:
    t0 = time.time()
    raw, bench, bench_raw = asyncio.run(load_named(market))
    data = []
    for name, df in raw.items():
        b = sl.prepare(df, bench)
        if b.n > START + 120:
            data.append((name, b, precompute(b)))
    last_day = pd.Timestamp(max(b.day[-1] for _, b, _ in data))
    spans = periods(last_day)
    default = sl.DEFAULTS[market]
    print(f"{market}: {len(data)} varlık, son gün {last_day.date()}, hazırlık {time.time() - t0:.0f} sn", flush=True)

    chosen, table, picks = search(data, market, default, spans)

    # score buckets (development, default orders, no score filter): does the score separate good breakouts?
    _, runs = run_market(data, market, replace(default, min_score=-99), {"gelistirme": spans["gelistirme"]})
    dev_mask = {id(r["b"]): _mask(r["b"].day, *spans["gelistirme"]) for r in runs}
    buckets = {"0-3": [], "4-6": [], "7+": []}
    for r in runs:
        for t in r["trades"]:
            if dev_mask[id(r["b"])][t["e"]]:
                buckets["0-3" if t["skor"] <= 3 else "4-6" if t["skor"] <= 6 else "7+"].append(t)

    # final scoring: every period, with random twins; the locked year is read here for the first time
    years = {str(y): (np.datetime64(f"{y}-01-01"), np.datetime64(f"{y + 1}-01-01"))
             for y in range(2017, last_day.year + 1)}
    dev_end = spans["gelistirme"][1]
    folds = {y: (lo, min(hi, dev_end)) for y, (lo, hi) in years.items() if lo < dev_end}
    final = {}
    for label, prm in (("varsayilan", default), ("secilen", chosen), ("secilen_kapanista_giris", replace(chosen, entry_mode="kapanis"))):
        res, _ = run_market(data, market, prm, spans, twins=True)
        res["yillar_gelistirme"] = {k: v for k, v in run_market(data, market, prm, folds, twins=True)[0].items()
                                    if k in folds and v["varlik"]}
        final[label] = res
        print(f"  {market} {label}: " + " | ".join(
            f"{k} kural {res[k]['kural_yillik_%']} rastgele {res[k]['rastgele_%']} al-tut {res[k]['al_tut_%']} "
            f"(%{res[k]['rastgeleyi_gecen_varlik_%']}) ort {res[k]['islemler'].get('ort_R')}R n={res[k]['islemler'].get('islem')}"
            for k in spans), flush=True)

    s = final["secilen"]
    dev_ok, val_ok, lock_ok = passes(s["gelistirme"], 60), passes(s["validation"], 55), passes(s["kilitli_son_12_ay"], 55)
    verdict = "PRODUCTION" if dev_ok and val_ok and lock_ok else "RESEARCH" if dev_ok else "REJECTED"

    # reference: the existing close-based trend rule on the same data, engine standard (nothing is written)
    frames = [engine.attach_benchmark(engine.indicators(df.copy()), bench) for df in raw.values() if len(df) > START + 120]
    ref = engine.evaluate(frames, strategies.trend_donchian, market)

    return {"varlik": len(data), "son_gun": str(last_day.date()),
            "donemler": {k: [None if lo is None else str(lo)[:10], None if hi is None else str(hi)[:10]]
                         for k, (lo, hi) in spans.items()},
            "varsayilan_parametreler": asdict(default), "secilen_parametreler": asdict(chosen), "secim": picks,
            "izgara_gelistirme": table,
            "skor_kovalari_gelistirme": {k: trade_stats(v) for k, v in buckets.items()},
            "sonuc": final, "karar": verdict,
            "karar_ayrinti": {"gelistirme_gecti": dev_ok, "validation_gecti": val_ok, "kilitli_gecti": lock_ok},
            "referans_trend_takibi_kapanis": {"karar": ref["karar"], "gelistirme": ref["donemler"].get("gelistirme"),
                                              "kilitli_son_12_ay": ref["donemler"].get("kilitli_son_12_ay")},
            "kontroller": {"ileriye_bakma": lookahead_check(raw, bench_raw, data, market, chosen),
                           "maliyet": cost_check(data, market, chosen, spans)},
            "sure_sn": round(time.time() - t0)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    out = {"olusturma": time.strftime("%Y-%m-%d %H:%M"),
           "standart": {"mum": "günlük", "komisyon_tek_yon_%": {k: v * 100 for k, v in engine.COST.items()},
                        "kayma_stop_emirlerinde_%": {k: v * 100 for k, v in SLIP.items()},
                        "secim_kurali": f"yalnız geliştirme dönemi; varsayılan, bir seçenek ortanca yıllık getiride en az "
                                        f"{MARGIN} puan iyi ve en az {MIN_TRADES} işlemli değilse değişmez",
                        "karar_kurali": "PRODUCTION: geliştirme (>= %60 varlık), validation ve kilitli yıl (>= %55) "
                                        "dönemlerinin üçünde de rastgele ikizini geçer; RESEARCH: yalnız geliştirme; yoksa REJECTED",
                        "abd": "test edilmedi (araştırma evreninde ABD hissesi yok); parametreler BIST ile aynı"}}
    for mkt in ("KRIPTO", "BIST"):
        out[mkt] = study(mkt)
        print(f"{mkt}: {out[mkt]['karar']} ({out[mkt]['sure_sn']} sn)", flush=True)
    (HERE / "stop_limit_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

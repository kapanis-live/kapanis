"""The retest after a breakout was the only level event that differed from random (levels_lab.py). Does a filter make
it pay, and does that survive data nobody looked at? Writes retest_lab_results.json; touches nothing else.

Event (pivot levels, 1h closes): a close above a zone the previous candle closed under, then within 48 hours the
first candle whose low is back at the zone and that closes above it. Long at that close. Outcome as in levels_lab:
a 1 ATR(4h) race over 48 hourly closes, net of 0.1 % per side. One event per coin per 24 hours.

Filters, fixed before any result was seen (8 combinations):
  BTC     BTC's 1h close is above its 200-hour average at the entry
  TREND   the coin's 1h close is above its own 200-hour average at the entry
  HACIM   the breakout candle's volume was above 1.5 x its 20-hour average

Periods
  gelistirme  2023-01-01 .. 2024-09-27   the combination is CHOSEN here: highest daily mean R with >= 1000 events
  validation  2024-09-27 .. 2025-09-27   seen once before (levels_lab.py printed the unfiltered retest there)
  taze        2025-09-27 .. today        downloaded for this run; no rule was ever tuned or scored on it

Verdict for the chosen combination: GECTI only if the daily mean R's 95 % range is above zero in development AND the
mean is above zero and above the random-zone twin in validation AND in the fresh year. Otherwise KALDI.

    python research/retest_lab.py
"""
import asyncio
import itertools
import json
import pathlib
import random
import sys
import time

import httpx
import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import levels_lab as ll  # noqa: E402

FRESH = HERE / "kl" / "fresh_15m"
LOCK = pd.Timestamp("2025-09-27", tz="UTC").value // 10**6
FILTERS = ("BTC", "TREND", "HACIM")
PERIODS = ("gelistirme", "validation", "taze")


async def fresh_15m(client, sym: str, gate: asyncio.Semaphore) -> pd.DataFrame | None:
    f = FRESH / f"{sym}_15m_from_2025-09-27.pkl"
    if f.exists():
        return pd.read_pickle(f)
    rows, t, end = [], LOCK, int(time.time() * 1000) // 900_000 * 900_000
    async with gate:
        while t < end:
            r = await client.get("https://data-api.binance.vision/api/v3/klines",
                                 params={"symbol": sym, "interval": "15m", "startTime": t, "limit": 1000}, timeout=30)
            if r.status_code == 400:
                break                                         # delisted since
            r.raise_for_status()
            d = r.json()
            if not d:
                break
            rows += d
            t = d[-1][0] + 900_000
            if len(d) < 1000:
                break
    df = pd.DataFrame({"t": [int(x[0]) for x in rows], "o": [float(x[1]) for x in rows], "h": [float(x[2]) for x in rows],
                       "l": [float(x[3]) for x in rows], "c": [float(x[4]) for x in rows], "v": [float(x[5]) for x in rows]})
    df = df[df.t + 900_000 <= end].reset_index(drop=True)
    df.to_pickle(f)
    return df


async def load_all() -> dict[str, pd.DataFrame]:
    FRESH.mkdir(parents=True, exist_ok=True)
    files = sorted(ll.CACHE.glob("*USDT_15m_*.pkl"))
    gate = asyncio.Semaphore(6)
    async with httpx.AsyncClient() as client:
        new = await asyncio.gather(*[fresh_15m(client, f.name.split("_")[0], gate) for f in files], return_exceptions=True)
    out = {}
    for f, extra in zip(files, new):
        old = pd.read_pickle(f)
        if isinstance(extra, pd.DataFrame) and len(extra):
            old = pd.concat([old[old.t < LOCK], extra[["t", "o", "h", "l", "c", "v"]]], ignore_index=True)
        out[f.name.split("_")[0]] = old.drop_duplicates("t").sort_values("t").reset_index(drop=True)
    return out


def period_of(t: int) -> str:
    return "gelistirme" if t < ll.VALIDATION else "validation" if t < LOCK else "taze"


def run_coin(raw: pd.DataFrame, btc_up: pd.Series, rng: random.Random, acc: dict):
    h1, h4, d1 = ll.resample(raw, ll.H1), ll.resample(raw, ll.H4), ll.resample(raw, ll.D1)
    if len(h1) < 2000 or len(d1) < 80:
        return
    a4 = ll.atr14(h4)
    p4, p1 = ll.pivots(h4, 3, ll.H4, a4), ll.pivots(d1, 2, ll.D1)
    T, H, L, C, V = h1.t.values, h1.h.values, h1.l.values, h1.c.values, h1.v.values
    trend = (h1.c > h1.c.rolling(200).mean()).values
    busy = (h1.v > 1.5 * h1.v.rolling(20).mean().shift()).values
    btc = btc_up.reindex(T).fillna(False).values
    last = {"SEVIYE": -10**9, "RASTGELE": -10**9}
    first_day = max(ll.START, int(T[0] // ll.D1 + 61) * ll.D1)
    for day in range(first_day, int(T[-1]), ll.D1):
        j0, j1 = int(np.searchsorted(T, day)), int(np.searchsorted(T, day + ll.D1))
        i4 = int(np.searchsorted(h4.t.values, day)) - 1
        w0 = int(np.searchsorted(T, day - 60 * ll.D1))
        if j0 < 2 or j1 <= j0 or i4 < 20 or not a4[i4] > 0 or j0 - w0 < 500:
            continue
        price, atr = float(C[j0 - 1]), float(a4[i4])
        zones = ll.pivot_zones(p4, p1, day, price, max(atr * 0.35, price * 0.0015))
        lo60, hi60 = float(L[w0:j0].min()), float(H[w0:j0].max())
        twin = []
        for alt, ust in zones:
            mid = rng.uniform(lo60, hi60)
            twin.append((mid - (ust - alt) / 2, mid + (ust - alt) / 2))
        for who, zs in (("SEVIYE", zones), ("RASTGELE", twin)):
            for kind, j, _alt, ust in sorted(ll.events_of(zs, j0, j1, H, L, C), key=lambda e: e[1]):
                if kind != "KIRILIM":
                    continue
                k = ll.retest(j, ust, L, C)
                if k is None or k - last[who] < 24:
                    continue
                r = ll.race(k, atr, C, True)
                if r is None:
                    continue
                last[who] = k
                flags = {"BTC": bool(btc[k]), "TREND": bool(trend[k]), "HACIM": bool(busy[j])}
                acc.setdefault((who, period_of(int(T[k]))), []).append((int(T[k] // ll.D1), r, flags))


def table(rows: list[tuple], need: tuple) -> dict | None:
    rows = [x for x in rows if all(x[2][f] for f in need)]
    return ll.summarize([(d, r) for d, r, _ in rows]) if len(rows) >= 30 else None


def main() -> dict:
    data = asyncio.run(load_all())
    b1 = ll.resample(data["BTCUSDT"], ll.H1)
    btc_up = pd.Series((b1.c > b1.c.rolling(200).mean()).values, index=b1.t.values)
    rng, acc = random.Random(11), {}
    for n, (coin, raw) in enumerate(data.items(), 1):
        run_coin(raw, btc_up, rng, acc)
        print(f"{n}/{len(data)} {coin}", flush=True)
    out = {"veri": {"coin": len(data), "taze_son": str(pd.to_datetime(max(d.t.iloc[-1] for d in data.values() if len(d)), unit="ms"))},
           "kombinasyonlar": {}}
    for n in range(len(FILTERS) + 1):
        for need in itertools.combinations(FILTERS, n):
            name = " + ".join(need) or "filtresiz"
            out["kombinasyonlar"][name] = {p: {"seviye": table(acc.get(("SEVIYE", p), []), need),
                                               "rastgele": table(acc.get(("RASTGELE", p), []), need)} for p in PERIODS}
    ok = {k: v for k, v in out["kombinasyonlar"].items() if v["gelistirme"]["seviye"] and v["gelistirme"]["seviye"]["olay"] >= 1000}
    chosen = max(ok, key=lambda k: ok[k]["gelistirme"]["seviye"]["gunluk_ort_R"])
    c = out["kombinasyonlar"][chosen]

    def beats(p):
        s, t = c[p]["seviye"], c[p]["rastgele"]
        return bool(s and s["gunluk_ort_R"] > 0 and (t is None or s["gunluk_ort_R"] > t["gunluk_ort_R"]))
    steps = {"gelistirme_%95_sifirin_ustunde": c["gelistirme"]["seviye"]["gunluk_%95"][0] > 0,
             "validation_sifirin_ve_rastgelenin_ustunde": beats("validation"), "taze_sifirin_ve_rastgelenin_ustunde": beats("taze")}
    out["secilen"] = chosen
    out["adimlar"] = steps
    out["karar"] = "GECTI" if all(steps.values()) else "KALDI"
    return out


if __name__ == "__main__":
    res = main()
    (HERE / "retest_lab_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("veri", res["veri"])
    for name, periods in res["kombinasyonlar"].items():
        print(name)
        for p, c in periods.items():
            s, t = c["seviye"], c["rastgele"]
            if s:
                print(f"   {p:11s} n={s['olay']:6d} gun={s['gun']:4d} isabet %{s['yon_isabeti_%']:5} R {s['gunluk_ort_R']:+.3f} {s['gunluk_%95']}"
                      + (f" | rastgele n={t['olay']:5d} R {t['gunluk_ort_R']:+.3f}" if t else " | rastgele: az olay"), flush=True)
    print("SECILEN:", res["secilen"], res["adimlar"], "=>", res["karar"])

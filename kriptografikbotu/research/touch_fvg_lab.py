"""Two claims from an outside review, measured. Writes touch_fvg_results.json; touches nothing else.

A) "The more often a level was touched, the weaker it is."
   Pivot levels as the bot draws them (levels_lab.pivot method), split by the number of pivots in the zone:
   2, 3-4, 5 or more. Events on a 1h close: TUTUNMA (held at the zone, long), KIRILIM (closed above it, long),
   TAKILMA (stopped under it, down), DUSUS (closed under it, down). If the claim holds, holds and rejections get
   worse and breaks get better as the touch count grows.

B) "A fair value gap pulls the price back and is a good place to buy."
   Bullish gap on 1h candles: low[i] > high[i-2], at least 0.25 ATR(1h) wide; the zone is high[i-2]..low[i].
   MIKNATIS: does the price come back to the zone's top within 48 hours more often than it reaches the level the
             same distance ABOVE the close of candle i?
   GIRIS:    the first candle within 48 hours whose low is back in the zone and that closes at or above its bottom;
             long at that close. Twin: the same zone geometry (distance and width in ATR) under a random candle of
             the same coin that formed no gap.

Outcome for every entry: the levels_lab race (1 ATR(4h) up or down within 48 hourly closes, net of 0.1 % per side),
daily means as the sample. Periods: development, validation, and the year after 2025-09-27 (already used once, for
the retest check; these two questions were never asked of it before).

    python research/touch_fvg_lab.py
"""
import asyncio
import json
import pathlib
import random
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import levels_lab as ll  # noqa: E402
import market  # noqa: E402
import retest_lab as rl  # noqa: E402

BUCKETS = ((2, 2, "2 dokunma"), (3, 4, "3-4 dokunma"), (5, 99, "5+ dokunma"))
GAP_MIN_ATR = 0.25


def touch_zones(p4, p1, day: int, price: float, band: float) -> list[tuple]:
    """levels_lab.pivot_zones, but keeping the touch count: (alt, ust, dokunma)."""
    m4 = (p4["known"] <= day) & (p4["t"] >= day - 300 * ll.H4)
    m1 = (p1["known"] <= day) & (p1["t"] >= day - 300 * ll.D1)
    pts = []
    for p, m, w in ((p4, m4, 1.0), (p1, m1, 1.5)):
        for col, flag in (("h", "hi"), ("l", "lo")):
            pts += [{"price": float(x), "volume": float(v) * w} for x, v in zip(p[col][m & p[flag]], p["v"][m & p[flag]])]
    z = [x for x in market._cluster(pts, band) if x["dokunma"] >= 2]
    under = sorted((x for x in z if x["orta"] < price), key=lambda x: -x["orta"])[:3]
    over = sorted((x for x in z if x["orta"] >= price), key=lambda x: x["orta"])[:3]
    return [(x["alt"], x["ust"], x["dokunma"]) for x in under + over]


def run_coin(raw, rng: random.Random, acc: dict):
    h1, h4, d1 = ll.resample(raw, ll.H1), ll.resample(raw, ll.H4), ll.resample(raw, ll.D1)
    if len(h1) < 2000 or len(d1) < 80:
        return
    a4, a1 = ll.atr14(h4), ll.atr14(h1)
    p4, p1 = ll.pivots(h4, 3, ll.H4, a4), ll.pivots(d1, 2, ll.D1)
    T, H, L, C = h1.t.values, h1.h.values, h1.l.values, h1.c.values
    t4 = h4.t.values
    last: dict = {}

    def add(key, j, atr, long=True):
        if j - last.get(key, -10**9) < 24:
            return
        r = ll.race(j, atr, C, long)
        if r is None:
            return
        last[key] = j
        acc.setdefault((*key, rl.period_of(int(T[j]))), []).append((int(T[j] // ll.D1), r))

    # A) touch count
    first_day = max(ll.START, int(T[0] // ll.D1 + 61) * ll.D1)
    for day in range(first_day, int(T[-1]), ll.D1):
        j0, j1 = int(np.searchsorted(T, day)), int(np.searchsorted(T, day + ll.D1))
        i4 = int(np.searchsorted(t4, day)) - 1
        w0 = int(np.searchsorted(T, day - 60 * ll.D1))
        if j0 < 2 or j1 <= j0 or i4 < 20 or not a4[i4] > 0 or j0 - w0 < 500:
            continue
        price, atr = float(C[j0 - 1]), float(a4[i4])
        zones = touch_zones(p4, p1, day, price, max(atr * 0.35, price * 0.0015))
        for lo, hi, name in BUCKETS:
            zs = [(a, u) for a, u, n in zones if lo <= n <= hi]
            for kind, j, _a, _u in sorted(ll.events_of(zs, j0, j1, H, L, C), key=lambda e: e[1]):
                add(("DOKUNMA", name, kind), j, atr, kind in ll.LONG)

    # B) fair value gaps
    n = len(T)
    start = int(np.searchsorted(T, ll.START))
    gap = np.zeros(n, dtype=bool)
    gap[2:] = (L[2:] > H[:-2]) & ((L[2:] - H[:-2]) >= GAP_MIN_ATR * a1[2:])
    twins: list[tuple] = []
    plain = np.flatnonzero(~gap[start:n - 2 * ll.HORIZON - 2]) + start
    for i in np.flatnonzero(gap):
        if i < start or i + 2 * ll.HORIZON + 2 > n:
            continue
        i4 = int(np.searchsorted(t4, T[i])) - 1
        if i4 < 20 or not a4[i4] > 0 or not a1[i] > 0:
            continue
        top, bottom, close = float(L[i]), float(H[i - 2]), float(C[i])
        dist = close - top
        seg_l, seg_h = L[i + 1:i + 1 + ll.HORIZON], H[i + 1:i + 1 + ll.HORIZON]
        period = rl.period_of(int(T[i]))
        acc.setdefault(("FVG", "MIKNATIS", "asagi_bosluga", period), []).append((int(T[i] // ll.D1), float((seg_l <= top).any())))
        acc.setdefault(("FVG", "MIKNATIS", "yukari_ayni_mesafe", period), []).append((int(T[i] // ll.D1), float((seg_h >= close + dist).any())))
        back = seg_l <= top
        if back.any():
            k = i + 1 + int(back.argmax())
            if C[k] >= bottom:
                add(("FVG", "GIRIS", "bosluk"), k, float(a4[i4]))
        if len(plain):                                      # the twin: the same geometry under a candle with no gap
            q = int(plain[rng.randrange(len(plain))])
            q4 = int(np.searchsorted(t4, T[q])) - 1
            if q4 >= 20 and a4[q4] > 0 and a1[q] > 0:
                scale = a1[q] / a1[i]
                ttop = C[q] - dist * scale
                tbot = ttop - (top - bottom) * scale
                tb = L[q + 1:q + 1 + ll.HORIZON] <= ttop
                if tb.any():
                    k = q + 1 + int(tb.argmax())
                    if C[k] >= tbot:
                        twins.append((k, float(a4[q4])))
    for k, atr in sorted(twins):          # random candles come in no order; the 24-hour spacing needs time order
        add(("FVG", "GIRIS", "ikiz"), k, atr)


def rate(rows: list[tuple]) -> dict:
    v = np.array([x[1] for x in rows])
    return {"olay": len(v), "oran_%": round(float(v.mean()) * 100, 1)}


def main() -> dict:
    data = asyncio.run(rl.load_all())
    rng, acc = random.Random(11), {}
    for n, (coin, raw) in enumerate(data.items(), 1):
        if len(raw):
            run_coin(raw, rng, acc)
        print(f"{n}/{len(data)} {coin}", flush=True)
    out = {"dokunma": {}, "fvg_miknatis": {}, "fvg_giris": {}}
    for (a, b, c, period), rows in sorted(acc.items()):
        if a == "DOKUNMA":
            out["dokunma"].setdefault(c, {}).setdefault(b, {})[period] = ll.summarize(rows)
        elif b == "MIKNATIS":
            out["fvg_miknatis"].setdefault(c, {})[period] = rate(rows)
        else:
            out["fvg_giris"].setdefault(c, {})[period] = ll.summarize(rows)
    return out


if __name__ == "__main__":
    res = main()
    (HERE / "touch_fvg_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for kind, buckets in res["dokunma"].items():
        print(kind)
        for name, periods in buckets.items():
            print("   ", name, " | ".join(f"{p}: n={s['olay']} isabet %{s['yon_isabeti_%']} R {s['gunluk_ort_R']:+.3f}" for p, s in periods.items()))
    for name, periods in res["fvg_miknatis"].items():
        print("MIKNATIS", name, " | ".join(f"{p}: n={s['olay']} %{s['oran_%']}" for p, s in periods.items()))
    for name, periods in res["fvg_giris"].items():
        print("GIRIS", name, " | ".join(f"{p}: n={s['olay']} isabet %{s['yon_isabeti_%']} R {s['gunluk_ort_R']:+.3f} {s['gunluk_%95']}" for p, s in periods.items()))

"""Does a confluence score separate good level setups from bad ones? Writes score_lab_results.json; nothing else.

An outside review proposed a seven-point checklist as a "confidence rate". Here the checklist is computed by code on
every past long level event and the outcome is compared across scores. If the score means anything, results must
improve as it rises, and the top group must be above zero.

Events (pivot levels, 1h closes, 77 coins): KIRILIM (close above a zone the previous candle closed under) and
TUTUNMA (low reached the zone from above, close inside or over it). The plan is the level scan's own:
stop = zone bottom - 0.25 ATR(4h), target = the next zone above the close, else close + 2 ATR(4h).

The seven conditions, one point each (the review's weights of 15/15/15/15/15/15/10 are ignored: untested numbers)
  1 HACIM     the candle's volume is above its 20-candle average
  2 MUM       the close is in the top 30 % of the candle's range
  3 ANA_TREND the last closed 4h candle is above its 200-candle average
  4 IVME      the 1h close is above its 20- and 50-candle averages
  5 BTC       BTC's 1h close is above its 50-candle average      (macro events are not in the data: left out)
  6 RR        reward / risk of the plan is at least 1.5
  7 STOP      the stop is at least 1.5 ATR(1h) under the entry

Outcome of the plan, by 1h closes over the next 96 hours: a close at or over the target, a close at or under the
stop, else the last close; R = (exit - entry) / (entry - stop), net of 0.1 % per side. One event per coin per 24 h.
Daily means are the sample. Rule fixed in advance: the checklist is USEFUL only if the top group (6-7 points) has a
95 % range above zero in development AND a mean above zero in validation and in the fresh year.

    python research/score_lab.py
"""
import asyncio
import json
import pathlib
import sys

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import levels_lab as ll  # noqa: E402
import retest_lab as rl  # noqa: E402
import touch_fvg_lab as tf  # noqa: E402

HOLD = 96
GROUPS = ((0, 2, "0-2 puan"), (3, 3, "3 puan"), (4, 4, "4 puan"), (5, 5, "5 puan"), (6, 7, "6-7 puan"))
NAMES = ("HACIM", "MUM", "ANA_TREND", "IVME", "BTC", "RR", "STOP")


def outcome(j: int, stop: float, target: float, C) -> float | None:
    if j + 1 + HOLD > len(C):
        return None
    entry, seg = C[j], C[j + 1:j + 1 + HOLD]
    hit = (seg >= target) | (seg <= stop)
    exit_ = seg[int(hit.argmax())] if hit.any() else seg[-1]
    risk = entry - stop
    return (exit_ - entry) / risk - 2 * ll.COST * entry / risk


def run_coin(raw, btc_up: pd.Series, acc: dict):
    h1, h4, d1 = ll.resample(raw, ll.H1), ll.resample(raw, ll.H4), ll.resample(raw, ll.D1)
    if len(h1) < 2000 or len(d1) < 80:
        return
    a4, a1 = ll.atr14(h4), ll.atr14(h1)
    p4, p1 = ll.pivots(h4, 3, ll.H4, a4), ll.pivots(d1, 2, ll.D1)
    T, H, L, C, V = h1.t.values, h1.h.values, h1.l.values, h1.c.values, h1.v.values
    t4 = h4.t.values
    vol_ok = (h1.v > h1.v.rolling(20).mean().shift()).values
    strong = ((C - L) >= 0.7 * np.maximum(H - L, 1e-12))
    mom = ((h1.c > h1.c.rolling(20).mean()) & (h1.c > h1.c.rolling(50).mean())).values
    main = (h4.c > h4.c.rolling(200).mean()).values
    btc = btc_up.reindex(T).fillna(False).values
    last = -10**9
    first_day = max(ll.START, int(T[0] // ll.D1 + 61) * ll.D1)
    for day in range(first_day, int(T[-1]), ll.D1):
        j0, j1 = int(np.searchsorted(T, day)), int(np.searchsorted(T, day + ll.D1))
        i4 = int(np.searchsorted(t4, day)) - 1
        w0 = int(np.searchsorted(T, day - 60 * ll.D1))
        if j0 < 2 or j1 <= j0 or i4 < 20 or not a4[i4] > 0 or j0 - w0 < 500:
            continue
        price, atr = float(C[j0 - 1]), float(a4[i4])
        zones = tf.touch_zones(p4, p1, day, price, max(atr * 0.35, price * 0.0015))
        flat = [(a, u) for a, u, _ in zones]
        for kind, j, alt, ust in sorted(ll.events_of(flat, j0, j1, H, L, C), key=lambda e: e[1]):
            if kind not in ("KIRILIM", "TUTUNMA") or j - last < 24 or not a1[j] > 0:
                continue
            close = float(C[j])
            stop = alt - 0.25 * atr
            if not close > stop:
                continue
            above = [a for a, u in flat if (a + u) / 2 > close and a > ust]
            target = (min(above) + 0.0) if above else close + 2 * atr
            if not target > close:
                target = close + 2 * atr
            r = outcome(j, stop, target, C)
            if r is None:
                continue
            last = j
            k4 = int(np.searchsorted(t4, T[j], side="right")) - 2          # the last 4h candle closed before this hour ends
            flags = (bool(vol_ok[j]), bool(strong[j]), bool(k4 >= 0 and main[k4]), bool(mom[j]), bool(btc[j]),
                     (target - close) / (close - stop) >= 1.5, (close - stop) >= 1.5 * a1[j])
            acc.setdefault((kind, rl.period_of(int(T[j]))), []).append((int(T[j] // ll.D1), r, flags))


def main() -> dict:
    data = asyncio.run(rl.load_all())
    b1 = ll.resample(data["BTCUSDT"], ll.H1)
    btc_up = pd.Series((b1.c > b1.c.rolling(50).mean()).values, index=b1.t.values)
    acc: dict = {}
    for n, (coin, raw) in enumerate(data.items(), 1):
        if len(raw):
            run_coin(raw, btc_up, acc)
        print(f"{n}/{len(data)} {coin}", flush=True)
    out = {"puan": {}, "sart": {}}
    for kind in ("KIRILIM", "TUTUNMA", "HEPSI"):
        for period in rl.PERIODS:
            rows = [x for (k, p), v in acc.items() if p == period and kind in (k, "HEPSI") for x in v]
            for lo, hi, name in GROUPS:
                sel = [(d, r) for d, r, f in rows if lo <= sum(f) <= hi]
                out["puan"].setdefault(kind, {}).setdefault(name, {})[period] = ll.summarize(sel) if len(sel) >= 30 else None
            if kind == "HEPSI":
                for i, cond in enumerate(NAMES):
                    yes, no = [(d, r) for d, r, f in rows if f[i]], [(d, r) for d, r, f in rows if not f[i]]
                    out["sart"].setdefault(cond, {})[period] = {
                        "var": ll.summarize(yes) if len(yes) >= 30 else None, "yok": ll.summarize(no) if len(no) >= 30 else None}
    top = out["puan"]["HEPSI"]["6-7 puan"]
    steps = {"gelistirme_%95_sifirin_ustunde": bool(top["gelistirme"] and top["gelistirme"]["gunluk_%95"][0] > 0),
             "validation_sifirin_ustunde": bool(top["validation"] and top["validation"]["gunluk_ort_R"] > 0),
             "taze_sifirin_ustunde": bool(top["taze"] and top["taze"]["gunluk_ort_R"] > 0)}
    out["adimlar"], out["karar"] = steps, "ISE_YARAR" if all(steps.values()) else "ISE_YARAMAZ"
    return out


if __name__ == "__main__":
    res = main()
    (HERE / "score_lab_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    fmt = lambda s: "az olay" if not s else f"n={s['olay']} isabet %{s['yon_isabeti_%']} R {s['gunluk_ort_R']:+.3f} {s['gunluk_%95']}"
    for kind, groups in res["puan"].items():
        print(kind)
        for name, periods in groups.items():
            print(f"   {name:9s}", " | ".join(f"{p}: {fmt(s)}" for p, s in periods.items()), flush=True)
    print("SARTLAR (var / yok, gunluk ort R)")
    for cond, periods in res["sart"].items():
        print(f"   {cond:10s}", " | ".join(f"{p}: {c['var']['gunluk_ort_R'] if c['var'] else '-'} / {c['yok']['gunluk_ort_R'] if c['yok'] else '-'}"
                                          for p, c in periods.items()))
    print("KARAR:", res["adimlar"], "=>", res["karar"])

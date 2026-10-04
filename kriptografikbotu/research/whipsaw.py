"""How wide must a stop be before normal noise stops hitting it? Writes whipsaw_results.json; touches nothing else.

Data: the Strategy Lab v3 cache (closed 15m candles, crypto universe with dead coins, 2023-01-01 .. 2025-09-27).
Entries, at a 15m close:  KIRILIM = the close is above the high of the previous 20 candles;
                          RASTGELE = a fixed grid (every 96th candle), no setup at all.
At most one entry per coin per 24 hours, so the trades do not overlap.
For each stop distance k x ATR(14, 15m) below the entry, over the next 24 hours (96 candles):
  touch stop (broker, Midas): the first low at or under the stop        close stop (the bot): the first close under it
  whipsaw: the stop was hit and within the 24 hours after it a candle closed back above the entry
  race: +1R (entry + k ATR, by the high) against the touch stop; both in one candle counts as the stop; neither in
        24 hours is marked to the last close. Net of 0.1 % per side.
Periods: development (before 2024-09-27) and validation (the year after); nothing is chosen on validation.

    python research/whipsaw.py
"""
import json
import pathlib

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
CACHE = HERE / "kl" / "strategy_lab_v3"
START = pd.Timestamp("2023-01-01", tz="UTC").value // 10**6
VALIDATION = pd.Timestamp("2024-09-27", tz="UTC").value // 10**6
H = 96                     # 24 hours of 15m candles
KS = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0)
COST = 0.001


def atr14(df: pd.DataFrame) -> np.ndarray:
    c = df.c.shift()
    tr = pd.concat([df.h - df.l, (df.h - c).abs(), (df.l - c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / 14, adjust=False).mean().values


def entries(df: pd.DataFrame) -> dict[str, np.ndarray]:
    brk = (df.c > df.h.rolling(20).max().shift()).values
    out = {"KIRILIM": [], "RASTGELE": list(range(100, len(df), H))}
    last = -H
    for i in np.flatnonzero(brk):
        if i - last >= H:
            out["KIRILIM"].append(i)
            last = i
    return {k: np.array(v, dtype=int) for k, v in out.items()}


def first(mask: np.ndarray) -> int | None:
    i = int(mask.argmax())
    return i if mask[i] else None


def measure(o: dict, k: float) -> dict:
    """One entry, one stop distance. o: entry, atr and the next 2H lows / highs / closes."""
    stop, target = o["entry"] - k * o["atr"], o["entry"] + k * o["atr"]
    lo, hi, cl = o["l"], o["h"], o["c"]
    t, c, up = first(lo[:H] <= stop), first(cl[:H] < stop), first(hi[:H] >= target)
    r = (cl[H - 1] - o["entry"]) / (k * o["atr"]) if t is None and up is None else -1.0 if up is None or (t is not None and t <= up) else 1.0
    return {"touch": t is not None, "touch_whip": t is not None and bool((cl[t + 1:t + 1 + H] > o["entry"]).any()),
            "close": c is not None, "close_whip": c is not None and bool((cl[c + 1:c + 1 + H] > o["entry"]).any()),
            "win": r == 1.0, "r": r - 2 * COST * o["entry"] / (k * o["atr"])}


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    t, c = sum(x["touch"] for x in rows), sum(x["close"] for x in rows)
    return {"giris": n, "dokunma_stop_%": round(t / n * 100, 1),
            "dokunma_whipsaw_%": round(sum(x["touch_whip"] for x in rows) / t * 100, 1) if t else None,
            "kapanis_stop_%": round(c / n * 100, 1),
            "kapanis_whipsaw_%": round(sum(x["close_whip"] for x in rows) / c * 100, 1) if c else None,
            "once_+1R_%": round(float(sum(x["win"] for x in rows)) / n * 100, 1),
            "ort_net_R": round(float(np.mean([x["r"] for x in rows])), 3)}


def run() -> dict:
    acc: dict = {}
    files = sorted(CACHE.glob("*USDT_15m_*.pkl"))
    for f in files:
        df = pd.read_pickle(f)
        a, t = atr14(df), df.t.values
        lo, hi, cl = df.l.values, df.h.values, df.c.values
        for kind, idx in entries(df).items():
            for i in idx:
                if t[i] < START or i + 1 + 2 * H > len(df) or not a[i] > 0:
                    continue
                o = {"entry": cl[i], "atr": a[i], "l": lo[i + 1:i + 1 + 2 * H], "h": hi[i + 1:i + 1 + 2 * H], "c": cl[i + 1:i + 1 + 2 * H]}
                period = "gelistirme" if t[i] < VALIDATION else "validation"
                for k in KS:
                    acc.setdefault((kind, period, k), []).append(measure(o, k))
    out = {"veri": {"coin": len(files), "mum": "15m", "ufuk_saat": 24, "maliyet_tek_yon_%": COST * 100,
                    "gelistirme": "2023-01-01 .. 2024-09-27", "validation": "2024-09-27 .. 2025-09-27"}, "sonuc": {}}
    for (kind, period, k), rows in sorted(acc.items()):
        out["sonuc"].setdefault(kind, {}).setdefault(period, {})[f"{k:g}"] = summarize(rows)
    return out


if __name__ == "__main__":
    res = run()
    (HERE / "whipsaw_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for kind, periods in res["sonuc"].items():
        for period, table in periods.items():
            print(kind, period)
            for k, row in table.items():
                print(f"  {k:>4} ATR  {row}", flush=True)

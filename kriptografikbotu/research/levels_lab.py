"""Do better-drawn support / resistance levels predict anything? Writes levels_lab_results.json; touches nothing else.

Data: the Strategy Lab v3 cache (closed 15m candles, 78 coins with dead ones, 2022-11 .. 2025-09-27), resampled to
1h (decision candle), 4h and 1d. Levels are redrawn once a day at 00:00 UTC from data closed before that moment.

Level methods
  PIVOT      what the bot draws today: 4h pivots (3 left, 3 right, last 300 candles) + daily pivots (2/2, x1.5),
             clustered within 0.35 ATR(4h); zones with at least 2 touches; the 3 nearest under and over the price
  HACIM      volume profile of the last 60 days of 1h candles: the busiest price nodes, 3 under and 3 over the price
  TEPKI      only 4h pivots of the last 60 days after which the price moved at least 2 ATR away within 10 candles
  each with a RASTGELE twin: the same number of zones with the same widths at random prices inside the 60-day range

Events on a 1h close
  TUTUNMA    low reached the zone from above, close inside or above it        (long)
  KIRILIM    close above a zone the previous candle closed under              (long)
  RETEST     after a KIRILIM, the first return to the zone within 48 h that closes back above it   (long)
  TAKILMA    high reached the zone from below, close inside or under it       (direction: down)
  DUSUS      close under a zone the previous candle closed over               (direction: down)

Outcome: a race over the next 48 hourly closes between entry + 1 ATR(4h) and entry - 1 ATR(4h); neither = marked to
the last close. R is in the event's direction, net of 0.1 % per side. One event per coin, method and kind per 24 h.
Periods: development (2023-01-01 .. 2024-09-27) and validation (.. 2025-09-27). A method passes only if the event's
mean net R is above zero AND above its random twin's in both periods, judged on daily means (days are the sample,
because coins move together).

    python research/levels_lab.py
"""
import json
import pathlib
import random
import sys

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import market  # noqa: E402

CACHE = HERE / "kl" / "strategy_lab_v3"
H1, H4, D1 = 3_600_000, 14_400_000, 86_400_000
START = pd.Timestamp("2023-01-01", tz="UTC").value // 10**6
VALIDATION = pd.Timestamp("2024-09-27", tz="UTC").value // 10**6
HORIZON = 48
COST = 0.001
LONG = ("TUTUNMA", "KIRILIM", "RETEST")
KINDS = LONG + ("TAKILMA", "DUSUS")
METHODS = ("PIVOT", "HACIM", "TEPKI")


def resample(df: pd.DataFrame, ms: int) -> pd.DataFrame:
    g = df.t // ms
    out = df.groupby(g).agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"), v=("v", "sum"), n=("t", "size"))
    out["t"] = out.index * ms
    return out[out.n == ms // 900_000].reset_index(drop=True)      # complete candles only


def atr14(df: pd.DataFrame) -> np.ndarray:
    c = df.c.shift()
    tr = pd.concat([df.h - df.l, (df.h - c).abs(), (df.l - c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().values


def pivots(df: pd.DataFrame, k: int, ms: int, atr=None) -> dict:
    """Swing highs / lows with the time they become known (k candles later). With atr: also whether the price then
    moved 2 ATR away within 10 candles, known 10 candles later."""
    h, l = df.h, df.l
    hi = (h == h.rolling(2 * k + 1, center=True).max()).values
    lo = (l == l.rolling(2 * k + 1, center=True).min()).values
    out = {"t": df.t.values, "hi": hi, "lo": lo, "h": h.values, "l": l.values, "v": df.v.values,
           "known": df.t.values + (k + 1) * ms}
    if atr is not None:
        fut_lo = l[::-1].rolling(10).min()[::-1].shift(-1).values
        fut_hi = h[::-1].rolling(10).max()[::-1].shift(-1).values
        out["hi_react"] = hi & (fut_lo <= h.values - 2 * atr)
        out["lo_react"] = lo & (fut_hi >= l.values + 2 * atr)
        out["react_known"] = df.t.values + 11 * ms
    return out


def nearest(zones: list[dict], price: float, min_touch: int) -> list[tuple]:
    z = [x for x in zones if x["dokunma"] >= min_touch]
    under = sorted((x for x in z if x["orta"] < price), key=lambda x: -x["orta"])[:3]
    over = sorted((x for x in z if x["orta"] >= price), key=lambda x: x["orta"])[:3]
    return [(x["alt"], x["ust"]) for x in under + over]


def pivot_zones(p4, p1, day: int, price: float, band: float) -> list[tuple]:
    m4 = (p4["known"] <= day) & (p4["t"] >= day - 300 * H4)
    m1 = (p1["known"] <= day) & (p1["t"] >= day - 300 * D1)
    pts = ([{"price": float(x), "volume": float(v)} for x, v in zip(p4["h"][m4 & p4["hi"]], p4["v"][m4 & p4["hi"]])]
           + [{"price": float(x), "volume": float(v)} for x, v in zip(p4["l"][m4 & p4["lo"]], p4["v"][m4 & p4["lo"]])]
           + [{"price": float(x), "volume": float(v) * 1.5} for x, v in zip(p1["h"][m1 & p1["hi"]], p1["v"][m1 & p1["hi"]])]
           + [{"price": float(x), "volume": float(v) * 1.5} for x, v in zip(p1["l"][m1 & p1["lo"]], p1["v"][m1 & p1["lo"]])])
    return nearest(market._cluster(pts, band), price, 2)


def reaction_zones(p4, day: int, price: float, band: float) -> list[tuple]:
    m = (p4["react_known"] <= day) & (p4["t"] >= day - 60 * D1)
    pts = ([{"price": float(x), "volume": float(v)} for x, v in zip(p4["h"][m & p4["hi_react"]], p4["v"][m & p4["hi_react"]])]
           + [{"price": float(x), "volume": float(v)} for x, v in zip(p4["l"][m & p4["lo_react"]], p4["v"][m & p4["lo_react"]])])
    return nearest(market._cluster(pts, band), price, 1)


def volume_zones(typical: np.ndarray, vol: np.ndarray, price: float, band: float) -> list[tuple]:
    lo, hi = typical.min(), typical.max()
    bins = int(min(max((hi - lo) / band, 10), 400))
    prof, edges = np.histogram(typical, bins=bins, range=(lo, hi), weights=vol)
    smooth = np.convolve(prof, np.ones(3) / 3, mode="same")
    peak = np.flatnonzero((smooth[1:-1] > smooth[:-2]) & (smooth[1:-1] >= smooth[2:])) + 1
    nodes = [{"orta": (edges[i] + edges[i + 1]) / 2, "alt": edges[i], "ust": edges[i + 1], "dokunma": 1, "w": smooth[i]} for i in peak]
    nodes = sorted(nodes, key=lambda x: -x["w"])[:12]                       # the busiest nodes, then the nearest of them
    return nearest(nodes, price, 1)


def events_of(zones: list[tuple], j0: int, j1: int, H, L, C) -> list[tuple]:
    """(kind, bar index, alt, ust) for the hourly candles j0..j1-1."""
    if not zones or j1 <= j0:
        return []
    alt = np.array([z[0] for z in zones])[:, None]
    ust = np.array([z[1] for z in zones])[:, None]
    j = np.arange(j0, j1)
    h, l, c, ph, pl, pc = H[j], L[j], C[j], H[j - 1], L[j - 1], C[j - 1]
    found = []
    for kind, mask in (("TUTUNMA", (pl > ust) & (l <= ust) & (c >= alt)), ("KIRILIM", (pc <= ust) & (c > ust)),
                       ("TAKILMA", (ph < alt) & (h >= alt) & (c <= ust)), ("DUSUS", (pc >= alt) & (c < alt))):
        for zi, bi in zip(*np.nonzero(mask)):
            found.append((kind, int(j[bi]), float(alt[zi, 0]), float(ust[zi, 0])))
    return found


def retest(j: int, ust: float, L, C) -> int | None:
    """After a breakout at candle j: the first later candle (within HORIZON) whose low is back at the zone; an event
    only if that candle closes above the zone."""
    seg = L[j + 2:j + 1 + HORIZON] <= ust
    if not seg.any():
        return None
    k = j + 2 + int(seg.argmax())
    return k if C[k] >= ust else None


def race(j: int, atr: float, C, long: bool) -> float | None:
    if j + 1 + HORIZON > len(C) or not atr > 0:
        return None
    seg, entry = C[j + 1:j + 1 + HORIZON], C[j]
    up, dn = seg >= entry + atr, seg <= entry - atr
    iu = int(up.argmax()) if up.any() else HORIZON
    idn = int(dn.argmax()) if dn.any() else HORIZON
    r = (seg[-1] - entry) / atr if iu == idn else 1.0 if iu < idn else -1.0
    return (r if long else -r) - 2 * COST * entry / atr


def run_coin(path: pathlib.Path, rng: random.Random, acc: dict):
    raw = pd.read_pickle(path)
    h1, h4, d1 = resample(raw, H1), resample(raw, H4), resample(raw, D1)
    if len(h1) < 2000 or len(d1) < 80:
        return
    a4 = atr14(h4)
    p4, p1 = pivots(h4, 3, H4, a4), pivots(d1, 2, D1)
    T, H, L, C, V = h1.t.values, h1.h.values, h1.l.values, h1.c.values, h1.v.values
    typical = (H + L + C) / 3
    last_seen: dict = {}

    def record(method, kind, j, atr):
        key = (method, kind)
        if j - last_seen.get(key, -10**9) < 24:
            return
        r = race(j, atr, C, kind in LONG)
        if r is None:
            return
        last_seen[key] = j
        period = "gelistirme" if T[j] < VALIDATION else "validation"
        acc.setdefault((method, kind, period), []).append((int(T[j] // D1), r))

    first_day = max(START, int(T[0] // D1 + 61) * D1)
    for day in range(first_day, int(T[-1]), D1):
        j0, j1 = int(np.searchsorted(T, day)), int(np.searchsorted(T, day + D1))
        i4 = int(np.searchsorted(h4.t.values, day)) - 1
        if j0 < 2 or j1 <= j0 or i4 < 20 or not a4[i4] > 0:
            continue
        price, atr = float(C[j0 - 1]), float(a4[i4])
        band = max(atr * 0.35, price * 0.0015)
        w0 = int(np.searchsorted(T, day - 60 * D1))
        if j0 - w0 < 500:                 # a trading gap inside the 60 days (relisted ticker): no levels for that day
            continue
        lo60, hi60 = float(L[w0:j0].min()), float(H[w0:j0].max())
        sets = {"PIVOT": pivot_zones(p4, p1, day, price, band), "TEPKI": reaction_zones(p4, day, price, band),
                "HACIM": volume_zones(typical[w0:j0], V[w0:j0], price, band)}
        for method, zones in list(sets.items()):
            twin = []
            for alt, ust in zones:
                mid = rng.uniform(lo60, hi60)
                twin.append((mid - (ust - alt) / 2, mid + (ust - alt) / 2))
            sets[method + "_RASTGELE"] = twin
        for method, zones in sets.items():
            for kind, j, alt, ust in sorted(events_of(zones, j0, j1, H, L, C), key=lambda e: e[1]):
                record(method, kind, j, atr)
                if kind == "KIRILIM":
                    k = retest(j, ust, L, C)
                    if k is not None:
                        record(method, "RETEST", k, atr)


def summarize(rows: list[tuple]) -> dict:
    r = np.array([x[1] for x in rows])
    daily = pd.Series(r).groupby([x[0] for x in rows]).mean()
    se = float(daily.std(ddof=1) / np.sqrt(len(daily))) if len(daily) > 1 else float("nan")
    return {"olay": len(r), "gun": len(daily), "yon_isabeti_%": round(float((r > 0).mean()) * 100, 1),
            "ort_net_R": round(float(r.mean()), 3), "gunluk_ort_R": round(float(daily.mean()), 3),
            "gunluk_%95": [round(float(daily.mean() - 1.96 * se), 3), round(float(daily.mean() + 1.96 * se), 3)]}


def main() -> dict:
    rng, acc = random.Random(11), {}
    files = sorted(CACHE.glob("*USDT_15m_*.pkl"))
    for n, f in enumerate(files, 1):
        run_coin(f, rng, acc)
        print(f"{n}/{len(files)} {f.name.split('_')[0]}", flush=True)
    out = {"veri": {"coin": len(files), "karar_mumu": "1h", "ufuk_saat": HORIZON, "bariyer": "1 ATR(4h)",
                    "maliyet_tek_yon_%": COST * 100}, "sonuc": {}, "karar": {}}
    for method in METHODS:
        for kind in KINDS:
            cell = {}
            for period in ("gelistirme", "validation"):
                real, twin = acc.get((method, kind, period)), acc.get((method + "_RASTGELE", kind, period))
                cell[period] = {"seviye": summarize(real) if real else None, "rastgele": summarize(twin) if twin else None}
            ok = all(c["seviye"] and c["rastgele"] and c["seviye"]["olay"] >= 300 and c["seviye"]["gunluk_%95"][0] > 0
                     and c["seviye"]["gunluk_ort_R"] > c["rastgele"]["gunluk_ort_R"] for c in cell.values())
            out["sonuc"][f"{method} · {kind}"] = cell
            out["karar"][f"{method} · {kind}"] = "GECTI" if ok else "KALDI"
    return out


if __name__ == "__main__":
    res = main()
    (HERE / "levels_lab_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, cell in res["sonuc"].items():
        print(name, res["karar"][name])
        for period, c in cell.items():
            s, t = c["seviye"], c["rastgele"]
            if s and t:
                print(f"   {period:11s} seviye n={s['olay']:6d} isabet %{s['yon_isabeti_%']:5} R {s['gunluk_ort_R']:+.3f} {s['gunluk_%95']}"
                      f" | rastgele n={t['olay']:6d} isabet %{t['yon_isabeti_%']:5} R {t['gunluk_ort_R']:+.3f}", flush=True)

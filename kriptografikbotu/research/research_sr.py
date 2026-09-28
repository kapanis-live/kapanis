"""Does the bot's edge exist on history? Two tests on Binance data, same code as the live bot.

A) Resistance zones (market.sr_zones on 300×4h + 300×1d): when price first touches the nearest resistance,
   how often does it reject (4h close ≥1 ATR below the zone) before breaking (4h close ≥1 ATR above)?
   Control: an imaginary zone of the same width at the same distance but shifted randomly ±30-70%.
B) The scanner's AL rule (15m close breaks the zone's top with volume > MA20 and close > SMA50, not stretched,
   stop = zone bottom − 0.25 ATR4h, target = next resistance or +2 ATR4h, R/R ≥ 1): net R per trade after
   0.1% cost per side, close-based exits. Control: the same stop/target distances from random 15m closes.
Run: python research_sr.py   (caches klines in ./kl/)
"""
import asyncio
import json
import pathlib
import random
import sys
import time

import httpx
import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import market  # noqa: E402

COINS = ["BTC", "ETH", "SOL", "XRP", "LINK", "AVAX", "NEAR", "AAVE", "UNI", "BCH", "ADA", "DOGE", "LTC", "DOT", "ATOM"]
DAYS = 540
CACHE = pathlib.Path("kl")
CACHE.mkdir(exist_ok=True)
TF_MS = {"15m": 900_000, "4h": 14_400_000, "1d": 86_400_000}
COST = 0.1


async def klines(client, sym, tf, start_ms, end_ms):
    f = CACHE / f"{sym}_{tf}_{DAYS}.pkl"
    if f.exists():
        return pd.read_pickle(f)
    rows, t = [], start_ms
    while t < end_ms:
        r = await client.get("https://data-api.binance.vision/api/v3/klines",
                             params={"symbol": sym, "interval": tf, "startTime": t, "limit": 1000}, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        rows += data
        t = data[-1][0] + TF_MS[tf]
        if len(data) < 1000:
            break
    df = pd.DataFrame([[int(x[0]), *map(float, x[1:6])] for x in rows], columns=["open_time", "open", "high", "low", "close", "volume"])
    df = df[df.open_time + TF_MS[tf] <= end_ms].reset_index(drop=True)
    df.to_pickle(f)
    return df


def zones_at(d4, d1, i4, price, atr):
    """Live-equivalent zones using only candles closed before 4h index i4."""
    w4 = d4.iloc[max(0, i4 - 300):i4]
    cut = d4.open_time.iloc[i4 - 1] + TF_MS["4h"]
    w1 = d1[d1.open_time + TF_MS["1d"] <= cut].tail(300)
    return market.sr_zones(w4, w1, price, atr, top=2)


def test_a(d4, d1, rng):
    real, ctrl = [], []
    for i in range(320, len(d4) - 60, 6):  # once a day
        price, atr = float(d4.close.iloc[i - 1]), float(d4.atr14.iloc[i - 1])
        if not atr or atr != atr:
            continue
        z = zones_at(d4, d1, i, price, atr)
        if not z["direncler"]:
            continue
        zr = z["direncler"][0]
        if zr["alt"] <= price:
            continue
        dist = zr["orta"] - price
        width = zr["ust"] - zr["alt"]
        shift = dist * rng.uniform(0.3, 0.7) * rng.choice([-1, 1])
        fake = {"alt": zr["alt"] + shift, "ust": zr["ust"] + shift}
        if fake["alt"] <= price:
            fake = {"alt": zr["alt"] + abs(shift), "ust": zr["ust"] + abs(shift)}
        for zone, bucket in ((zr, real), (fake, ctrl)):
            after = d4.iloc[i:i + 60]
            touch = next((k for k in range(len(after)) if after.high.iloc[k] >= zone["alt"]), None)
            if touch is None:
                continue
            res = None
            for k in range(touch, len(after)):
                c = after.close.iloc[k]
                if c <= zone["alt"] - atr:
                    res = "red"
                    break
                if c >= zone["ust"] + atr:
                    res = "kirilim"
                    break
            if res:
                bucket.append(res)
        _ = width
    return real, ctrl


def test_b(d15, d4, d1, rng):
    trades, ctrl = [], []
    d15 = market.add_indicators(d15.copy())
    zone_cache = {}
    last_signal = -10**9
    for j in range(260, len(d15) - 1):
        last, prev = d15.iloc[j], d15.iloc[j - 1]
        t_close = last.open_time + TF_MS["15m"]
        i4 = int(np.searchsorted(d4.open_time.values + TF_MS["4h"], t_close, side="right"))
        if i4 < 320:
            continue
        key = i4
        if key not in zone_cache:
            atr4 = float(d4.atr14.iloc[i4 - 1])
            zone_cache.clear()
            zone_cache[key] = (atr4, zones_at(d4, d1, i4, float(prev.close), atr4) if atr4 == atr4 else None)
        atr4, z = zone_cache[key]
        if not z or not z["direncler"]:
            continue
        # zones are relative to prev.close in live; recompute cheaply only when the level is near
        zone = z["direncler"][0]
        level = zone["ust"]
        if not (prev.close <= level < last.close):
            continue
        if not (last.vol_avg20 == last.vol_avg20 and last.volume > last.vol_avg20):
            continue
        if not (last.sma50 == last.sma50 and last.close > last.sma50):
            continue
        if last.atr14 == last.atr14 and last.close - level > 1.5 * last.atr14:
            continue
        if t_close - last_signal < 4 * 3600 * 1000:
            continue
        stop = zone["alt"] - 0.25 * atr4
        nxt = z["direncler"][1] if len(z["direncler"]) > 1 else None
        target = nxt["orta"] if nxt else level + 2 * atr4
        entry = float(last.close)
        if entry <= stop or (target - entry) / (entry - stop) < 1.0:
            continue
        last_signal = t_close
        after = d15.iloc[j + 1:j + 1 + 2000]
        for e, bucket in ((entry, trades), (None, ctrl)):
            if e is None:  # control: random close, same % distances
                k = rng.randrange(260, len(d15) - 2001)
                e2 = float(d15.close.iloc[k])
                s2, t2 = e2 * stop / entry, e2 * target / entry
                a2 = d15.iloc[k + 1:k + 2001]
                o = backtest_outcome(a2, e2, s2, t2)
                e_ = e2
                s_ = s2
            else:
                o = backtest_outcome(after, entry, stop, target)
                e_, s_ = entry, stop
            if o is None:
                continue
            c = COST / 100
            net = (o[1] * (1 - c) - e_ * (1 + c)) / (e_ - s_)
            bucket.append({"sonuc": o[0], "R": net})
    return trades, ctrl


def backtest_outcome(after, entry, stop, target):
    for c in after.close.values:
        if c < stop:
            return ("stop", c)
        if c >= target:
            return ("hedef", c)
    return None  # unresolved in 2000 candles: skipped


def summary(rows):
    if not rows:
        return {"n": 0}
    rs = np.array([r["R"] for r in rows])
    se = rs.std(ddof=1) / np.sqrt(len(rs)) if len(rs) > 1 else float("nan")
    return {"n": len(rs), "isabet": round(float(np.mean([r["sonuc"] == "hedef" for r in rows])) * 100, 1),
            "ort_R": round(float(rs.mean()), 3), "ort_R_95alt": round(float(rs.mean() - 1.96 * se), 3),
            "ort_R_95ust": round(float(rs.mean() + 1.96 * se), 3)}


async def main():
    rng = random.Random(7)
    end = int(time.time() * 1000)
    start = end - DAYS * 86_400_000
    A_real, A_ctrl, B, B_ctrl = [], [], [], []
    async with httpx.AsyncClient() as client:
        for coin in COINS:
            sym = coin + "USDT"
            try:
                d1 = await klines(client, sym, "1d", start - 320 * 86_400_000, end)
                d4 = market.add_indicators(await klines(client, sym, "4h", start - 60 * 86_400_000, end))
                d15 = await klines(client, sym, "15m", end - 365 * 86_400_000, end)
            except Exception as e:
                print(coin, "veri yok", e)
                continue
            a, ac = test_a(d4, d1, rng)
            b, bc = test_b(d15, d4, d1, rng)
            A_real += a
            A_ctrl += ac
            B += b
            B_ctrl += bc
            print(coin, "A", len(a), "B", len(b), flush=True)
    out = {
        "A_direnc_red_orani": {"gercek_bolge": {"n": len(A_real), "red_yuzde": round(A_real.count("red") / max(len(A_real), 1) * 100, 1)},
                               "rastgele_bolge": {"n": len(A_ctrl), "red_yuzde": round(A_ctrl.count("red") / max(len(A_ctrl), 1) * 100, 1)}},
        "B_kirilim_AL": {"kural": summary(B), "rastgele_giris_ayni_mesafe": summary(B_ctrl)},
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    pathlib.Path("research_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


asyncio.run(main())

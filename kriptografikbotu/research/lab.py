"""Strategy lab: textbook long-only rules on daily closes, costs included, split into two halves.

Markets: 15 large crypto (Binance, since 2019) and 40 liquid BIST stocks (Yahoo, 10 years).
Each rule decides on a CLOSE and trades at that close (same as the bot's close rule), cost per side:
crypto 0.1 %, BIST 0.2 %. Result per rule: yearly return, max drawdown, time in market, trades, and
the same numbers for buy & hold. Parameters are the standard textbook ones (not tuned), and every number
is reported for the first and second half separately: a rule has to hold up in both.
Known bias: today's BIST list (delisted losers are missing) flatters buy & hold and every long rule alike.
"""
import asyncio
import json
import pathlib
import time

import httpx
import numpy as np
import pandas as pd

CRYPTO = ["BTC", "ETH", "SOL", "XRP", "LINK", "AVAX", "NEAR", "AAVE", "UNI", "BCH", "ADA", "DOGE", "LTC", "DOT", "ATOM"]
BIST = ["THYAO", "GARAN", "AKBNK", "ISCTR", "YKBNK", "KCHOL", "SAHOL", "EREGL", "KRDMD", "TUPRS", "PETKM", "SISE",
        "ASELS", "BIMAS", "MGROS", "TCELL", "TTKOM", "FROTO", "TOASO", "ARCLK", "VESTL", "PGSUS", "TAVHL", "ENKAI",
        "EKGYO", "SASA", "HEKTS", "GUBRF", "AKSEN", "ULKER", "AEFES", "CCOLA", "DOHOL", "ALARK", "TKFEN", "OTKAR",
        "VAKBN", "HALKB", "TSKB", "SOKM"]
CACHE = pathlib.Path("kl")
CACHE.mkdir(exist_ok=True)
COST = {"KRIPTO": 0.001, "BIST": 0.002}


async def crypto_daily(client, coin):
    f = CACHE / f"{coin}USDT_1d_full.pkl"
    if f.exists():
        return pd.read_pickle(f)
    rows, t = [], int(pd.Timestamp("2019-01-01", tz="UTC").timestamp() * 1000)
    while True:
        r = await client.get("https://data-api.binance.vision/api/v3/klines",
                             params={"symbol": coin + "USDT", "interval": "1d", "startTime": t, "limit": 1000}, timeout=30)
        r.raise_for_status()
        d = r.json()
        if not d:
            break
        rows += d
        t = d[-1][0] + 86_400_000
        if len(d) < 1000:
            break
    df = pd.DataFrame({"t": [int(x[0]) for x in rows], "o": [float(x[1]) for x in rows], "h": [float(x[2]) for x in rows],
                       "l": [float(x[3]) for x in rows], "c": [float(x[4]) for x in rows]})
    df = df[df.t + 86_400_000 <= time.time() * 1000].reset_index(drop=True)
    df.to_pickle(f)
    return df


async def bist_daily(client, code):
    f = CACHE / f"{code}_IS_1d_10y.pkl"
    if f.exists():
        return pd.read_pickle(f)
    r = await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.IS",
                         params={"interval": "1d", "range": "10y"}, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    df = pd.DataFrame({"t": [x * 1000 for x in res["timestamp"]], "o": q["open"], "h": q["high"], "l": q["low"], "c": q["close"]})
    if adj:  # splits and dividends (bedelsiz) otherwise look like crashes
        ratio = pd.Series(adj) / df.c
        for k in ("o", "h", "l", "c"):
            df[k] = df[k] * ratio
    df = df.dropna().reset_index(drop=True)
    df = df.iloc[:-1]  # today's candle may still be forming
    df.to_pickle(f)
    return df


def ind(df):
    c = df.c
    df["sma5"], df["sma50"], df["sma200"] = c.rolling(5).mean(), c.rolling(50).mean(), c.rolling(200).mean()
    d = c.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    df["rsi2"] = 100 - 100 / (1 + up.ewm(alpha=1 / 2, adjust=False).mean() / dn.ewm(alpha=1 / 2, adjust=False).mean())
    df["hi20"], df["lo10"] = df.h.rolling(20).max().shift(1), df.l.rolling(10).min().shift(1)
    df["ret90"] = c / c.shift(90) - 1
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    df["bb_lo"] = mid - 2 * sd
    df["bb_mid"] = mid
    rng = df.h - df.l
    df["nr7"] = rng == rng.rolling(7).min()
    tr = pd.concat([df.h - df.l, (df.h - c.shift()).abs(), (df.l - c.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    return df


# Each rule: position (0/1) for tomorrow, decided from today's close. State machine where exits differ from entries.
def rule_positions(df, name):
    n = len(df)
    pos = np.zeros(n)
    hold, entry_i, entry_p = 0, 0, 0.0
    for i in range(201, n):
        r = df.iloc[i]
        if name == "sma200":
            hold = int(r.c > r.sma200)
        elif name == "altin_kesisim":
            hold = int(r.sma50 > r.sma200)
        elif name == "donchian_20_10":
            if not hold and r.c > r.hi20:
                hold = 1
            elif hold and r.c < r.lo10:
                hold = 0
        elif name == "rsi2_trend":  # Connors: buy deep short-term dips in a long-term uptrend
            if not hold and r.c > r.sma200 and r.rsi2 < 10:
                hold = 1
            elif hold and r.c > r.sma5:
                hold = 0
        elif name == "bollinger_trend":
            if not hold and r.c > r.sma200 and r.c < r.bb_lo:
                hold = 1
            elif hold and r.c > r.bb_mid:
                hold = 0
        elif name == "nr7_kirilim":
            if not hold and df.nr7.iloc[i - 1] and r.c > df.h.iloc[i - 1] and r.c > r.sma200:
                hold, entry_i, entry_p = 1, i, r.c
            elif hold and (i - entry_i >= 5 or r.c < entry_p - df.atr.iloc[entry_i]):
                hold = 0
        elif name == "donchian_20_10_trend":
            if not hold and r.c > r.hi20 and r.c > r.sma200:
                hold = 1
            elif hold and r.c < r.lo10:
                hold = 0
        pos[i] = hold
    return pos


RULES = ["sma200", "altin_kesisim", "donchian_20_10", "donchian_20_10_trend", "rsi2_trend", "bollinger_trend", "nr7_kirilim"]


def equity(df, pos, cost):
    ret = df.c.pct_change().fillna(0).values
    held = np.concatenate([[0], pos[:-1]])  # decided at yesterday's close
    trades = np.abs(np.diff(np.concatenate([[0], held])))
    return np.cumprod(1 + held * ret - trades * cost), held, trades


def stats(eq, held, trades, years):
    if years <= 0 or len(eq) < 2:
        return None
    total = eq[-1] / eq[0]
    peak = np.maximum.accumulate(eq)
    return {"yillik_%": round((total ** (1 / years) - 1) * 100, 1), "max_dusus_%": round((eq / peak - 1).min() * 100, 1),
            "piyasada_%": round(held.mean() * 100), "islem": int(trades.sum() // 2)}


def portfolio(frames, market, rule):
    """Equal-weight across assets, per half; each asset's curve starts after its 201st day."""
    out = {}
    for half in (0, 1):
        curves, bh = [], []
        for df in frames:
            d = df.iloc[201:].reset_index(drop=True)
            cut = len(d) // 2
            part = d.iloc[:cut] if half == 0 else d.iloc[cut:]
            if len(part) < 120:
                continue
            p = rule_positions(df, rule)[201:][:cut] if half == 0 else rule_positions(df, rule)[201:][cut:]
            eq, held, tr = equity(part.reset_index(drop=True), p, COST[market])
            ones = np.ones(len(part))
            eqb, hb, tb = equity(part.reset_index(drop=True), ones, COST[market])
            years = len(part) / (365 if market == "KRIPTO" else 250)
            curves.append(stats(eq, held, tr, years))
            bh.append(stats(eqb, hb, tb, years))
        med = lambda rows, k: round(float(np.median([r[k] for r in rows if r])), 1)
        out[f"{'1' if half == 0 else '2'}. yarı"] = {
            "kural": {k: med(curves, k) for k in ("yillik_%", "max_dusus_%", "piyasada_%", "islem")},
            "al_tut": {k: med(bh, k) for k in ("yillik_%", "max_dusus_%")},
            "kural_al_tutu_gecen_varlik": f"{sum(1 for a, b in zip(curves, bh) if a and b and a['yillik_%'] > b['yillik_%'])}/{len(curves)}"}
    return out


async def main():
    frames = {"KRIPTO": [], "BIST": []}
    async with httpx.AsyncClient() as client:
        for c in CRYPTO:
            try:
                frames["KRIPTO"].append(ind(await crypto_daily(client, c)))
            except Exception as e:
                print("kripto", c, e)
        for b in BIST:
            try:
                frames["BIST"].append(ind(await bist_daily(client, b)))
            except Exception as e:
                print("bist", b, e)
    print({k: len(v) for k, v in frames.items()}, flush=True)
    result = {}
    for market, fs in frames.items():
        for rule in RULES:
            result[f"{market} {rule}"] = portfolio(fs, market, rule)
            print(market, rule, json.dumps(result[f"{market} {rule}"], ensure_ascii=False), flush=True)
    pathlib.Path("lab_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())

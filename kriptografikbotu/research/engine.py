"""Strategy research engine: every candidate is tested the same way before it can reach users.

Standard (all of it, for every strategy):
- long-only, decided on a daily CLOSE, traded at that close; cost per side: crypto 0.1 %, BIST 0.2 %
- universes include assets that later collapsed or were delisted (crypto); BIST is today's list (known bias)
- the LAST 365 DAYS ARE A LOCKED HOLDOUT: no rule, parameter or filter may be chosen by looking at it;
  it is scored once, at the end, and reported separately
- the development period is cut into yearly folds (walk-forward style reporting): a rule must hold up in most folds
- comparison per asset: buy & hold, and random timing with the SAME time in the market and the same average holding
  length (RANDOM_DRAWS draws, the rule's result is placed as a percentile of that distribution)
- per-trade statistics: count, hit rate, average net return, profit factor
- every trade records the benchmark's market regime at entry (regime.py), for the regime study
Verdict: PRODUCTION only if, over the whole development period AND again in the locked holdout, the rule's median
result beats its random twin's and it beats its own twin on most assets (>= 60 % dev, >= 55 % holdout);
RESEARCH if only the development period passes; REJECTED otherwise. Yearly folds are reported for stability.
"""
import asyncio
import pathlib
import random
import time

import httpx
import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
CACHE = HERE / "kl"
CACHE.mkdir(exist_ok=True)
COST = {"KRIPTO": 0.001, "BIST": 0.002}
DPY = {"KRIPTO": 365, "BIST": 250}
HOLDOUT_DAYS = 365
RANDOM_DRAWS = 20
WARMUP = 210

CRYPTO = ("BTC ETH BNB SOL XRP DOGE ADA TRX AVAX LINK DOT BCH LTC NEAR UNI ATOM ETC FIL ICP HBAR XLM VET ALGO AAVE "
          "MKR SAND MANA AXS CHZ ENJ GRT CRV COMP SNX SUSHI YFI 1INCH ZEC DASH XMR EOS NEO WAVES QTUM ZIL ONT IOTA "
          "KSM EGLD THETA FTM RUNE KAVA CELO ICX OMG BAT ZRX LRC STORJ ANKR SKL OCEAN BAND REN KNC "
          "LUNA FTT SRM ANC MIR NANO STRAX LINA REEF MDX BZRX").split()
BIST = ["THYAO", "GARAN", "AKBNK", "ISCTR", "YKBNK", "KCHOL", "SAHOL", "EREGL", "KRDMD", "TUPRS", "PETKM", "SISE",
        "ASELS", "BIMAS", "MGROS", "TCELL", "TTKOM", "FROTO", "TOASO", "ARCLK", "VESTL", "PGSUS", "TAVHL", "ENKAI",
        "EKGYO", "SASA", "HEKTS", "GUBRF", "AKSEN", "ULKER", "AEFES", "CCOLA", "DOHOL", "ALARK", "TKFEN", "OTKAR",
        "VAKBN", "HALKB", "TSKB", "SOKM"]


# ---------------- data ----------------
async def crypto_daily(client, coin: str) -> pd.DataFrame:
    f = CACHE / f"{coin}USDT_1d_ohlcv.pkl"
    if f.exists():
        return pd.read_pickle(f)
    rows, t = [], int(pd.Timestamp("2018-01-01", tz="UTC").timestamp() * 1000)
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
                       "l": [float(x[3]) for x in rows], "c": [float(x[4]) for x in rows], "v": [float(x[7]) for x in rows]})
    df = df[df.t + 86_400_000 <= time.time() * 1000].reset_index(drop=True)
    df.to_pickle(f)
    return df


async def yahoo_daily(client, symbol: str) -> pd.DataFrame:
    f = CACHE / f"{symbol.replace('^', '_')}_1d_10y_ohlcv.pkl"
    if f.exists():
        return pd.read_pickle(f)
    r = await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                         params={"interval": "1d", "range": "10y"}, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    df = pd.DataFrame({"t": [x * 1000 for x in res["timestamp"]], "o": q["open"], "h": q["high"], "l": q["low"],
                       "c": q["close"], "v": q["volume"]})
    if adj:  # splits / bonus shares would otherwise look like crashes
        ratio = pd.Series(adj) / df.c
        for k in ("o", "h", "l", "c"):
            df[k] = df[k] * ratio
    df = df.dropna().reset_index(drop=True).iloc[:-1]  # today's candle may still be forming
    df.to_pickle(f)
    return df


def split_gaps(df: pd.DataFrame, max_days: int = 3) -> list[pd.DataFrame]:
    """A ticker that stops trading and comes back is a different asset (LUNA relaunch, FTT relisting, STRAX swap):
    one frame across the gap would book the price jump as a trade."""
    cuts = [0] + list(np.flatnonzero(df.t.diff().values > max_days * 86_400_000)) + [len(df)]
    return [df.iloc[a:b].reset_index(drop=True) for a, b in zip(cuts, cuts[1:])]


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l = df.c, df.h, df.l
    for n in (5, 20, 50, 200):
        df[f"sma{n}"] = c.rolling(n).mean()
    df["ema20"] = c.ewm(span=20, adjust=False).mean()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df["atr_pct"] = df.atr / c
    df["atr_rank"] = df.atr_pct.rolling(100).rank(pct=True)
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    df["bb_lo"], df["bb_hi"] = mid - 2 * sd, mid + 2 * sd
    df["bbw"] = (4 * sd) / mid
    df["bbw_rank"] = df.bbw.rolling(100).rank(pct=True)
    d = c.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    df["rsi2"] = 100 - 100 / (1 + up.ewm(alpha=1 / 2, adjust=False).mean() / dn.ewm(alpha=1 / 2, adjust=False).mean())
    df["hi20"], df["lo10"] = h.rolling(20).max().shift(1), l.rolling(10).min().shift(1)
    df["vol_ma20"] = df.v.rolling(20).mean()
    # ADX(14)
    upm, dnm = h.diff(), -l.diff()
    plus = np.where((upm > dnm) & (upm > 0), upm, 0.0)
    minus = np.where((dnm > upm) & (dnm > 0), dnm, 0.0)
    atr14 = tr.ewm(alpha=1 / 14, adjust=False).mean()
    pdi = 100 * pd.Series(plus, index=df.index).ewm(alpha=1 / 14, adjust=False).mean() / atr14
    mdi = 100 * pd.Series(minus, index=df.index).ewm(alpha=1 / 14, adjust=False).mean() / atr14
    df["adx"] = (100 * (pdi - mdi).abs() / (pdi + mdi)).ewm(alpha=1 / 14, adjust=False).mean()
    df["ret63"] = c / c.shift(63) - 1
    df["day"] = pd.to_datetime(df.t, unit="ms").dt.normalize()
    return df


def attach_benchmark(df: pd.DataFrame, bench: pd.DataFrame) -> pd.DataFrame:
    b = bench.set_index("day")
    df["bench_ret63"] = df.day.map(b.ret63)
    df["regime"] = df.day.map(b.regime) if "regime" in b else "?"
    return df


# ---------------- evaluation ----------------
def equity(close: np.ndarray, pos: np.ndarray, cost: float):
    ret = np.concatenate([[0.0], close[1:] / close[:-1] - 1])
    held = np.concatenate([[0.0], pos[:-1]])       # decided at yesterday's close
    trades = np.abs(np.diff(np.concatenate([[0.0], held])))
    return np.cumprod(1 + held * ret - trades * cost), held


def trade_list(close: np.ndarray, pos: np.ndarray, cost: float, regimes=None) -> list[dict]:
    out, entry, i0 = [], None, None
    for i in range(1, len(pos)):
        if pos[i - 1] and entry is None:
            entry, i0 = close[i - 1], i - 1
        if entry is not None and not pos[i - 1] and i - 1 > i0:
            ex = close[i - 1]
            out.append({"r": (ex * (1 - cost)) / (entry * (1 + cost)) - 1, "gun": i - 1 - i0,
                        "rejim": None if regimes is None else regimes[i0]})
            entry = None
    return out


def random_twin(n: int, exposure: float, avg_len: float, rng: random.Random) -> np.ndarray:
    pos, hold = np.zeros(n), 0
    p_exit = 1 / max(avg_len, 1)
    p_enter = min(1.0, p_exit * exposure / max(1 - exposure, 1e-9))
    for i in range(n):
        hold = (rng.random() > p_exit) if hold else (rng.random() < p_enter)
        pos[i] = hold
    return pos


def yearly(eq: np.ndarray, days: int, dpy: int) -> float | None:
    if days < 60 or eq[-1] <= 0:
        return None
    return (eq[-1] / eq[0]) ** (dpy / days) - 1


def anomaly(r: np.ndarray) -> dict:
    """A result too good to be a strategy is usually a data fault (a relisted ticker, a missed split): say so."""
    why = []
    if len(r) and float(r.max()) > 10:
        why.append(f"tek işlem +%{float(r.max()) * 100:.0f}")
    if len(r) >= 30 and float(r[r > 0].sum()) > 20 * float(-r[r <= 0].sum()) > 0:
        why.append("kâr faktörü 20'nin üstünde")
    return {"anomali": "METRIC_ANOMALY: " + ", ".join(why) + " — veriyi kontrol et"} if why else {}


def evaluate(frames: list[pd.DataFrame], strategy, market: str, seed: int = 11) -> dict:
    """Run one strategy over one universe with the full standard."""
    rng = random.Random(seed)
    cost, dpy = COST[market], DPY[market]
    last_day = max(f.day.iloc[-1] for f in frames)
    holdout_start = last_day - pd.Timedelta(days=HOLDOUT_DAYS)
    folds: dict[str, dict[str, list]] = {}
    trades_dev, trades_hold = [], []

    def score(tag, d, p):
        close = d.c.values
        eq, held = equity(close, p, cost)
        y = yearly(eq, len(d), dpy)
        if y is None:
            return
        bh = yearly(equity(close, np.ones(len(d)), cost)[0], len(d), dpy)
        exp = p.mean()
        runs = np.diff(np.flatnonzero(np.diff(np.concatenate([[0], p, [0]]))))
        avg_len = float(np.mean(runs[::2])) if exp > 0 and len(runs) else 1.0
        twins = []
        for _ in range(RANDOM_DRAWS):
            rp = random_twin(len(d), exp, avg_len, rng)
            ry = yearly(equity(close, rp, cost)[0], len(d), dpy)
            if ry is not None:
                twins.append(ry)
        pct = float(np.mean([y > t for t in twins])) if twins else None
        peak = np.maximum.accumulate(eq)
        folds.setdefault(tag, {"kural": [], "al_tut": [], "rastgele_ortanca": [], "yuzdelik": [], "dusus": [], "piyasada": []})
        f = folds[tag]
        f["kural"].append(y)
        f["al_tut"].append(bh)
        f["rastgele_ortanca"].append(float(np.median(twins)) if twins else None)
        f["yuzdelik"].append(pct)
        f["dusus"].append(float((eq / peak - 1).min()))
        f["piyasada"].append(exp)

    for df in frames:
        pos = strategy(df)
        pos[:WARMUP] = 0
        d = df.iloc[WARMUP:].reset_index(drop=True)
        p = pos[WARMUP:]
        dev = (d.day < holdout_start).values
        if dev.sum() > 60:
            dd, pp = d[dev].reset_index(drop=True), p[dev]
            trades_dev += trade_list(dd.c.values, pp, cost, dd.regime.values)
            for year in sorted(dd.day.dt.year.unique()):
                m = (dd.day.dt.year == year).values
                if m.sum() > 60:
                    score(str(year), dd[m].reset_index(drop=True), pp[m])
            score("gelistirme", dd, pp)
        if (~dev).sum() > 60:
            dh, ph = d[~dev].reset_index(drop=True), p[~dev]
            trades_hold += trade_list(dh.c.values, ph, cost, dh.regime.values)
            score("kilitli_son_12_ay", dh, ph)

    def med(xs):
        xs = [x for x in xs if x is not None]
        return round(float(np.median(xs)) * 100, 1) if xs else None

    table = {tag: {"varlik": len(v["kural"]), "kural_yillik_%": med(v["kural"]), "al_tut_%": med(v["al_tut"]),
                   "rastgele_%": med(v["rastgele_ortanca"]),
                   "rastgeleyi_gecen_varlik_%": round(np.mean([x for x in v["yuzdelik"] if x is not None]) * 100) if v["yuzdelik"] else None,
                   "en_buyuk_dusus_%": med(v["dusus"]), "piyasada_%": med(v["piyasada"])} for tag, v in folds.items()}

    def tstats(ts):
        if not ts:
            return {"islem": 0}
        r = np.array([t["r"] for t in ts])
        gains, losses = r[r > 0].sum(), -r[r <= 0].sum()
        return {"islem": len(r), "isabet_%": round(float((r > 0).mean()) * 100, 1), "ort_net_%": round(float(r.mean()) * 100, 2),
                "kar_faktoru": round(float(gains / losses), 2) if losses > 0 else None,
                "ort_gun": round(float(np.mean([t["gun"] for t in ts])), 1), **anomaly(r)}

    by_regime = {}
    for t in trades_dev:
        by_regime.setdefault(t["rejim"] if isinstance(t["rejim"], str) else "?", []).append(t)
    years = [k for k in table if k.isdigit()]
    # a year where the rule never traded ties with its random twin (both 0): not counted as a win or a loss
    decided = [k for k in years if table[k]["kural_yillik_%"] is not None and table[k]["rastgele_%"] is not None
               and table[k]["piyasada_%"] and table[k]["piyasada_%"] >= 5]
    beat = [k for k in decided if table[k]["kural_yillik_%"] > table[k]["rastgele_%"]]
    dev, hold = table.get("gelistirme", {}), table.get("kilitli_son_12_ay", {})

    def wins(t, share):
        return (t.get("kural_yillik_%") is not None and t.get("rastgele_%") is not None
                and t["kural_yillik_%"] > t["rastgele_%"] and (t.get("rastgeleyi_gecen_varlik_%") or 0) >= share)
    dev_ok, hold_ok = wins(dev, 60), wins(hold, 55)
    verdict = "PRODUCTION" if dev_ok and hold_ok else "RESEARCH" if dev_ok else "REJECTED"
    years = decided
    return {"karar": verdict, "rastgeleyi_gecen_yil": f"{len(beat)}/{len(years)}", "kilitli_donem_gecti": hold_ok,
            "donemler": table, "islemler_gelistirme": tstats(trades_dev), "islemler_kilitli": tstats(trades_hold),
            "rejime_gore": {k: tstats(v) for k, v in sorted(by_regime.items())}}


async def load(market: str) -> tuple[list[pd.DataFrame], pd.DataFrame]:
    import regime
    async with httpx.AsyncClient() as client:
        if market == "KRIPTO":
            frames = []
            for coin in CRYPTO:
                try:
                    for part in split_gaps(await crypto_daily(client, coin)):
                        if len(part) > WARMUP + 120:
                            frames.append(indicators(part))
                except Exception:
                    pass
            bench = next(f for f in frames if f.c.iloc[0] > 1000)  # BTC is the first coin
        else:
            frames = [indicators(await yahoo_daily(client, f"{s}.IS")) for s in BIST]
            bench = indicators(await yahoo_daily(client, "XU100.IS"))
    bench = regime.label(bench)
    frames = [attach_benchmark(f, bench) for f in frames]
    return frames, bench


def run_all(strategies: dict, markets=("KRIPTO", "BIST")) -> dict:
    out = {}
    for market in markets:
        frames, _ = asyncio.run(load(market))
        for name, fn in strategies.items():
            out[f"{market} · {name}"] = evaluate(frames, fn, market)
    return out

"""Research-only intraday lab. No advisor imports, orders, promotion, or holdout scoring.

Run: python research/strategy_lab_v3.py
The frozen lock starts 2025-09-27 (existing v2 cache's last day minus 365 days).
All signals use completed bars; every fill uses the following bar's OPEN.
Parameters are specified before the first run and are never fitted to validation.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

import httpx
import numpy as np
import pandas as pd

if __package__:
    from .engine import CRYPTO
else:
    from engine import CRYPTO

HERE = Path(__file__).resolve().parent
CACHE = HERE / "kl" / "strategy_lab_v3"
RESULTS = HERE / "strategy_lab_v3_results.json"
LOCK = pd.Timestamp("2025-09-27", tz="UTC")
VALIDATION = LOCK - pd.Timedelta(days=365)
START = pd.Timestamp("2023-01-01", tz="UTC")
RAW_START = START - pd.Timedelta(days=61)
DAY_MS = 86_400_000
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
REGIMES = ("TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOL", "PANIC")
STRATEGIES = ("breakout_retest_continuation", "liquidity_sweep_reclaim",
              "failed_breakout_reclaim", "vwap_reclaim", "relative_strength_rotation",
              "compression_expansion_v2")
FEE = 0.001
SLIPPAGE = 0.0005
PARAMETERS = {
    "lookback": 20, "atr_period": 14, "volume_multiple": 1.2,
    "breakout_atr_buffer": 0.1, "retest_atr_tolerance": 0.25,
    "setup_expiry_bars": 10, "minimum_stop_atr": 1.0,
    "target_R": 2.0, "maximum_hold_bars": 48,
    "squeeze_rank": 0.2, "squeeze_memory_bars": 5,
    "rotation_momentum_bars": 63, "rotation_every_bars": 24, "rotation_top_n": 3,
    "false_breakout_window_bars": 3,
}


def ms(ts):
    return int(pd.Timestamp(ts).timestamp() * 1000)


def iso(value):
    return pd.to_datetime(int(value), unit="ms", utc=True).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_hashes():
    # Includes both advisor implementations, their rules, and previous research results.
    files = list(HERE.parent.glob("*.py")) + list(HERE.glob("*.py"))
    files += [HERE / "results_v2.json", HERE / "stop_limit_results.json"]
    return {str(p.relative_to(HERE.parent)): digest(p) for p in sorted(files)
            if p.exists() and p.name not in ("strategy_lab_v3.py", "test_strategy_lab_v3.py")}


def closed_only(df, step, start=RAW_START, end=LOCK):
    """Clip BEFORE indicators, ranking, resampling, or evaluation."""
    out = df[(df.t >= ms(start)) & (df.t + step <= ms(end))].copy()
    if out.t.duplicated().any():
        raise ValueError("Duplicate candle timestamps")
    out = out.sort_values("t").reset_index(drop=True)
    if not out.empty:
        values = out[["o", "h", "l", "c", "v"]].to_numpy()
        if not np.isfinite(values).all() or (values[:, :4] <= 0).any() or (out.v < 0).any():
            raise ValueError("Invalid OHLCV values")
        if ((out.h < out[["o", "c", "l"]].max(axis=1)) |
                (out.l > out[["o", "c", "h"]].min(axis=1))).any():
            raise ValueError("Inconsistent OHLC values")
        if (out.t % step != 0).any():
            raise ValueError("Candle timestamp is not aligned to UTC interval")
    return out


def parse_archive(payload):
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        names = [name for name in z.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("Expected one candle CSV per archive")
        raw = pd.read_csv(z.open(names[0]), header=None, usecols=range(6))
    raw.columns = ["t", "o", "h", "l", "c", "v"]
    raw = raw.apply(pd.to_numeric, errors="raise")
    # Binance spot archives switched to microseconds on 2025-01-01.
    raw["t"] = np.where(raw.t >= 10**14, raw.t // 1000, raw.t).astype("int64")
    return raw


async def get(client, url, params=None):
    for attempt in range(4):
        try:
            response = await client.get(url, params=params)
            if response.status_code == 404:
                return None
            if response.status_code in (418, 429, 500, 502, 503, 504):
                if attempt == 3:
                    response.raise_for_status()
                await asyncio.sleep(min(30, 2 ** (attempt + 1)))
                continue
            response.raise_for_status()
            return response
        except (httpx.TimeoutException, httpx.NetworkError):
            if attempt == 3:
                raise
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError("HTTP retries exhausted")


async def api_range(client, coin, tf, start, end):
    """Bound every request to pre-lock candles; never request current klines."""
    step = DAY_MS if tf == "1d" else TF_MS[tf]
    rows, cursor = [], ms(start)
    while cursor + step <= ms(end):
        response = await get(client, "https://data-api.binance.vision/api/v3/klines",
                             {"symbol": coin + "USDT", "interval": tf, "startTime": cursor,
                              "endTime": ms(end) - 1, "limit": 1000})
        data = response.json()
        if not data:
            break
        rows.extend([[int(x[0]), *map(float, x[1:6])] for x in data])
        next_cursor = int(data[-1][0]) + step
        if next_cursor <= cursor:
            raise ValueError("Non-advancing API candle cursor")
        cursor = next_cursor
    return closed_only(pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v"]),
                       step, start, end)


async def download_coin(client, coin):
    path = CACHE / f"{coin}USDT_15m_{RAW_START.date()}_{LOCK.date()}.pkl"
    if path.exists():
        frame = pd.read_pickle(path)
        provenance = frame.attrs.get("provenance", {})
        if not provenance:
            raise ValueError(f"Cache lacks provenance: {path.name}")
        return closed_only(frame, TF_MS["15m"]), {**provenance, "cache_sha256": digest(path)}
    parts, missing, archives = [], [], []
    month = RAW_START.normalize().replace(day=1)
    # Fetch only complete months ending BEFORE the holdout. Never download its mixed month.
    while month + pd.offsets.MonthBegin(1) <= LOCK:
        stamp = month.strftime("%Y-%m")
        url = f"https://data.binance.vision/data/spot/monthly/klines/{coin}USDT/15m/{coin}USDT-15m-{stamp}.zip"
        response = await get(client, url)
        if response is None:
            missing.append(stamp)
        else:
            parts.append(parse_archive(response.content))
            archives.append({"month": stamp, "sha256": hashlib.sha256(response.content).hexdigest()})
        month += pd.offsets.MonthBegin(1)
    # A delisted symbol has no last full month; do not query its nonexistent current symbol.
    if archives and archives[-1]["month"] == (month - pd.offsets.MonthBegin(1)).strftime("%Y-%m"):
        tail = await api_range(client, coin, "15m", month, LOCK)
        parts.append(tail)
    frame = closed_only(pd.concat(parts, ignore_index=True), TF_MS["15m"]) if parts else pd.DataFrame(
        columns=["t", "o", "h", "l", "c", "v"])
    provenance = {"symbol": coin + "USDT", "source": "Binance spot public archive + bounded REST tail",
                  "missing_archive_months": missing, "archives": archives,
                  "rest_tail_start": month.isoformat(), "rest_end_exclusive": LOCK.isoformat()}
    frame.attrs["provenance"] = provenance
    frame.to_pickle(path)
    return frame, {**provenance, "cache_sha256": digest(path)}


async def load_data(coins):
    CACHE.mkdir(parents=True, exist_ok=True)
    frames, coverage, semaphore = {}, {}, asyncio.Semaphore(6)
    async with httpx.AsyncClient(timeout=45, limits=httpx.Limits(max_connections=8)) as client:
        daily_path = CACHE / f"BTCUSDT_1d_2022-01-01_{LOCK.date()}.pkl"
        if daily_path.exists():
            daily = closed_only(pd.read_pickle(daily_path), DAY_MS, pd.Timestamp("2022-01-01", tz="UTC"))
        else:
            daily = await api_range(client, "BTC", "1d", pd.Timestamp("2022-01-01", tz="UTC"), LOCK)
            daily.to_pickle(daily_path)

        async def one(coin):
            async with semaphore:
                try:
                    frame, meta = await download_coin(client, coin)
                    frames[coin] = frame
                    coverage[coin] = meta
                    print(f"DATA {coin}: {len(frame)} pre-lock 15m bars", flush=True)
                except Exception as exc:
                    coverage[coin] = {"symbol": coin + "USDT", "error": str(exc)}
                    print(f"DATA {coin}: ERROR {exc}", flush=True)

        await asyncio.gather(*(one(coin) for coin in coins))
    if not len(daily) or "BTC" not in frames or frames["BTC"].empty:
        raise ValueError("BTC benchmark data is unavailable")
    return frames, daily, coverage, digest(daily_path)


def resample(df, tf):
    step = TF_MS[tf]
    if tf == "15m":
        out = df.copy()
    else:
        grouped = df.groupby(df.t // step * step)
        out = grouped.agg(o=("o", "first"), h=("h", "max"), l=("l", "min"),
                          c=("c", "last"), v=("v", "sum"), count=("t", "size"))
        out = out[out["count"] == step // TF_MS["15m"]].drop(columns="count")
        out.index.name = "t"
        out = out.reset_index()
    return closed_only(out, step)


def features(df, step, daily_btc=None):
    d = df.copy()
    c, h, l = d.c, d.h, d.l
    for length in (20, 50, 200):
        d[f"sma{length}"] = c.rolling(length).mean()
    d["ema20"] = c.ewm(span=20, adjust=False).mean()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    atr_pct = d.atr / c
    d["atr_rank"] = atr_pct.rolling(100).rank(pct=True)
    d["bbw"] = 4 * c.rolling(20).std() / d.sma20
    d["bbw_rank"] = d.bbw.rolling(100).rank(pct=True)
    d["hi20"] = h.rolling(20).max().shift(1)
    d["lo20"] = l.rolling(20).min().shift(1)
    d["vma20"] = d.v.rolling(20).mean().shift(1)
    d["ret63"] = c / c.shift(63) - 1
    up, down = h.diff(), -l.diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0), index=d.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0), index=d.index)
    pdi = plus.ewm(alpha=1 / 14, adjust=False).mean() / d.atr
    mdi = minus.ewm(alpha=1 / 14, adjust=False).mean() / d.atr
    d["adx"] = (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)).ewm(alpha=1 / 14, adjust=False).mean()
    r20 = c / c.shift(20) - 1
    ready = d[["sma200", "atr_rank", "adx"]].notna().all(axis=1)
    d["regime"] = np.select(
        [~ready, (r20 <= -0.15) | ((d.atr_rank >= 0.9) & (c < d.sma50)),
         d.atr_rank >= 0.8, (c > d.sma200) & (d.sma50 > d.sma200) & (d.adx >= 20),
         (c < d.sma200) & (d.sma50 < d.sma200)],
        ["UNKNOWN", "PANIC", "HIGH_VOL", "TREND_UP", "TREND_DOWN"], default="RANGE")
    session = d.t // DAY_MS
    pv = ((h + l + c) / 3 * d.v).groupby(session).cumsum()
    d["vwap"] = pv / d.v.groupby(session).cumsum().replace(0, np.nan)
    d["session"] = session
    if daily_btc is not None:
        bench = daily_btc[["t", "regime"]].copy()
        bench["known_at"] = bench.t + DAY_MS
        d["decision_ms"] = d.t + step
        aligned = pd.merge_asof(d[["decision_ms"]], bench[["known_at", "regime"]],
                                left_on="decision_ms", right_on="known_at", direction="backward")
        d["btc_regime"] = aligned.regime.fillna("UNKNOWN").to_numpy()
        d["btc_known_at_ms"] = aligned.known_at.to_numpy()
    return d


def signals(d, name):
    """Return causal entry plans. Exits are specified by the common simulator."""
    n = len(d)
    enter, stop, level = np.zeros(n, bool), np.full(n, np.nan), np.full(n, np.nan)
    a = {k: d[k].to_numpy() for k in ("c", "o", "h", "l", "atr", "hi20", "lo20", "v", "vma20",
                                     "ema20", "sma50", "sma200", "vwap", "session")}
    c, atr = a["c"], a["atr"]
    squeeze = ((d.bbw_rank <= 0.2) & (d.atr_rank <= 0.2)).to_numpy()
    setup_level, setup_i, failed, low = np.nan, -100, False, np.nan
    for i in range(200, n):
        if not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        liquid = a["v"][i] >= 1.2 * a["vma20"][i]
        trend = c[i] > a["sma200"][i] and a["sma50"][i] > a["sma200"][i]
        breakout = c[i] > a["hi20"][i] + 0.1 * atr[i] and c[i - 1] <= a["hi20"][i]
        candidate, invalid, reference = False, np.nan, np.nan
        if name == "breakout_retest_continuation":
            if i - setup_i > 10 or (np.isfinite(setup_level) and c[i] < setup_level - atr[i]):
                setup_level = np.nan
            if np.isfinite(setup_level) and i > setup_i:
                candidate = a["l"][i] <= setup_level + 0.25 * atr[i] and c[i] > setup_level and c[i] > c[i - 1] and trend
                invalid, reference = min(a["l"][i], setup_level) - 0.25 * atr[i], setup_level
            if candidate:
                setup_level = np.nan
            elif breakout and liquid and trend and not np.isfinite(setup_level):
                setup_level, setup_i = a["hi20"][i], i
        elif name == "liquidity_sweep_reclaim":
            reference = a["lo20"][i]
            candidate = a["l"][i] < reference - 0.1 * atr[i] and c[i] > reference and c[i] > a["o"][i] and liquid
            invalid = a["l"][i] - 0.25 * atr[i]
        elif name == "failed_breakout_reclaim":
            if i - setup_i > 10:
                setup_level, failed = np.nan, False
            if np.isfinite(setup_level) and i > setup_i:
                low = min(low, a["l"][i])
                if c[i] < setup_level:
                    failed = True
                candidate = failed and c[i] > setup_level + 0.1 * atr[i] and c[i] > a["o"][i] and liquid
                invalid, reference = low - 0.25 * atr[i], setup_level
            if candidate:
                setup_level, failed = np.nan, False
            elif breakout and liquid and not np.isfinite(setup_level):
                setup_level, setup_i, low = a["hi20"][i], i, a["l"][i]
        elif name == "vwap_reclaim":
            candidate = (a["session"][i] == a["session"][i - 1] and c[i - 1] <= a["vwap"][i - 1]
                         and c[i] > a["vwap"][i] and c[i] > a["ema20"][i] and liquid)
            invalid = min(a["l"][i], a["vwap"][i]) - 0.5 * atr[i]
        elif name == "compression_expansion_v2":
            candidate = squeeze[max(0, i - 5):i].any() and breakout and liquid and trend
            reference = a["hi20"][i]
            invalid = min(a["l"][i], reference) - 0.25 * atr[i]
        else:
            raise ValueError(f"Unknown independent strategy: {name}")
        if candidate and np.isfinite(invalid):
            enter[i] = True
            stop[i] = min(invalid, c[i] - atr[i])
            # A common close-back-below-level definition is only meaningful for breakout entries.
            if name in ("breakout_retest_continuation", "failed_breakout_reclaim", "compression_expansion_v2"):
                level[i] = reference
    return {"enter": enter, "stop": stop, "level": level}


def new_trade(coin, signal, entry_ms, entry_fill, stop, level, regime, btc_regime):
    return {"symbol": coin + "USDT", "signal_close_ms": int(signal), "entry_ms": int(entry_ms),
            "entry_fill": float(entry_fill), "initial_stop": float(stop),
            "initial_risk_per_unit": float(entry_fill - stop), "level": float(level),
            "regime": str(regime), "btc_regime": str(btc_regime),
            "max_price": float(entry_fill), "min_price": float(entry_fill),
            "closed_bars": 0, "false_breakout": False}


def observe(trade, high, low, close):
    trade["max_price"] = max(trade["max_price"], float(high))
    trade["min_price"] = min(trade["min_price"], float(low))
    trade["closed_bars"] += 1
    if trade["closed_bars"] <= 3 and np.isfinite(trade["level"]) and close < trade["level"]:
        trade["false_breakout"] = True


def finish_trade(trade, exit_ms, raw_exit, reason, qty=1.0):
    fill = raw_exit * (1 - SLIPPAGE)
    risk = trade["initial_risk_per_unit"]
    net = fill * (1 - FEE) - trade["entry_fill"] * (1 + FEE)
    max_price, min_price = max(trade["max_price"], raw_exit), min(trade["min_price"], raw_exit)
    return {**{k: v for k, v in trade.items() if k not in ("max_price", "min_price", "level")},
            "exit_ms": int(exit_ms), "exit_fill": float(fill), "exit_reason": reason,
            "net_R": float(net / risk), "net_profit": float(qty * net),
            "net_return": float(net / (trade["entry_fill"] * (1 + FEE))),
            "MFE_R": float(max(0, max_price - trade["entry_fill"]) / risk),
            "MAE_R": float(max(0, trade["entry_fill"] - min_price) / risk),
            "hold_hours": (exit_ms - trade["entry_ms"]) / 3_600_000,
            "false_breakout_observed": bool(np.isfinite(trade["level"]) and
                                            (trade["closed_bars"] >= 3 or trade["false_breakout"]))}


def exit_reason(trade, close):
    if close <= trade["initial_stop"]:
        return "close_stop"
    if close >= trade["entry_fill"] + 2 * trade["initial_risk_per_unit"]:
        return "close_target"
    if trade["closed_bars"] >= 48:
        return "time_exit"
    return None


def empty_path(grid):
    return {"grid": grid, "equity": np.ones(len(grid)), "exposure": np.zeros(len(grid)), "trades": [],
            "regime_pnl": {r: np.zeros(len(grid)) for r in (*REGIMES, "UNKNOWN")},
            "btc_pnl": {r: np.zeros(len(grid)) for r in (*REGIMES, "UNKNOWN")},
            "regime_exposure": {r: np.zeros(len(grid)) for r in (*REGIMES, "UNKNOWN")},
            "btc_exposure": {r: np.zeros(len(grid)) for r in (*REGIMES, "UNKNOWN")}}


def simulate_asset(d, plan, coin, step, start, end):
    """One unlevered cash sleeve, reset flat at each evaluation period."""
    grid = np.arange(ms(start), ms(end), step, dtype=np.int64)
    out = empty_path(grid)
    selected = np.flatnonzero((d.t.to_numpy() >= ms(start)) & (d.t.to_numpy() + step <= ms(end)))
    if len(selected) < 2:
        return out
    a = {k: d[k].to_numpy() for k in ("t", "o", "h", "l", "c", "regime", "btc_regime")}
    cash, qty, trade, value = 1.0, 0.0, None, 1.0
    for i in selected:
        g = int((a["t"][i] - ms(start)) // step)
        before = value
        attribution = trade
        terminal = i == selected[-1]
        reason = exit_reason(trade, a["c"][i - 1]) if trade else None
        if trade and terminal:
            reason = "period_end" if a["t"][i] + step == ms(end) else "data_end"
        elif trade and a["t"][i] - a["t"][i - 1] != step:
            reason = "data_gap"
        if trade and reason:
            closed = finish_trade(trade, int(a["t"][i]), a["o"][i], reason, qty)
            cash = qty * closed["exit_fill"] * (1 - FEE)
            out["trades"].append(closed)
            qty, trade = 0.0, None
        # Do not exit and re-enter on the same open; no decisions from execution-bar OHLC.
        elif (trade is None and not terminal and i > 0 and a["t"][i - 1] >= ms(start)
              and a["t"][i] - a["t"][i - 1] == step and plan["enter"][i - 1]):
            fill, stop = a["o"][i] * (1 + SLIPPAGE), plan["stop"][i - 1]
            if a["o"][i] > stop and fill > stop > 0:
                trade = new_trade(coin, a["t"][i - 1] + step, a["t"][i], fill, stop,
                                  plan["level"][i - 1], a["regime"][i - 1], a["btc_regime"][i - 1])
                attribution = trade
                qty, cash = cash / (fill * (1 + FEE)), 0.0
        if trade:
            observe(trade, a["h"][i], a["l"][i], a["c"][i])
        value = cash + qty * a["c"][i]
        out["equity"][g] = value
        if attribution:
            out["regime_pnl"][attribution["regime"]][g] += value - before
            out["btc_pnl"][attribution["btc_regime"]][g] += value - before
        if trade:
            out["exposure"][g] = 1.0
            out["regime_exposure"][trade["regime"]][g] = 1.0
            out["btc_exposure"][trade["btc_regime"]][g] = 1.0
    # Forward-fill equity across listing/delisting dates and missing data; never invent price candles.
    observed = (d.t.to_numpy()[selected] - ms(start)) // step
    sparse = pd.Series(out["equity"][observed], index=observed)
    out["equity"] = sparse.reindex(np.arange(len(grid))).ffill().fillna(1.0).to_numpy()
    for vector in [out["exposure"], *out["regime_exposure"].values(), *out["btc_exposure"].values()]:
        vector[:] = pd.Series(vector[observed], index=observed).reindex(np.arange(len(grid))).ffill().fillna(0).to_numpy()
    return out


def combine_sleeves(paths, universe_size, grid):
    """Fixed equal initial capital. Missing/unlisted assets keep their sleeve in cash."""
    out = empty_path(grid)
    for path in paths:
        out["equity"] += (path["equity"] - 1) / universe_size
        out["exposure"] += path["exposure"] / universe_size
        out["trades"].extend({**t, "net_profit": t["net_profit"] / universe_size} for t in path["trades"])
        for kind in ("regime_pnl", "btc_pnl", "regime_exposure", "btc_exposure"):
            for regime in out[kind]:
                out[kind][regime] += path[kind][regime] / universe_size
    return out


def simulate_rotation(frames, step, start, end):
    """Actual top-three portfolio. Sell then buy on next open; idle slots remain cash.

    At each 24-bar rebalance, rank positive 63-bar excess return vs BTC among assets
    above SMA200. Retained positions are not resized; each new position uses at most
    one third of current equity. No leverage or hypothetical constant-weight returns.
    """
    grid = np.arange(ms(start), ms(end), step, dtype=np.int64)
    out = empty_path(grid)
    coins = sorted(frames)
    columns = ("o", "h", "l", "c", "atr", "ret63", "sma200")
    arrays = {column: np.full((len(grid), len(coins)), np.nan) for column in columns}
    labels = {column: np.full((len(grid), len(coins)), "UNKNOWN", dtype=object)
              for column in ("regime", "btc_regime")}
    last = {}
    for k, coin in enumerate(coins):
        d = frames[coin]
        mask = (d.t >= ms(start)) & (d.t + step <= ms(end))
        indices = ((d.t[mask].to_numpy() - ms(start)) // step).astype(int)
        if not len(indices):
            continue
        last[k] = int(indices[-1])
        for column in columns:
            arrays[column][indices, k] = d.loc[mask, column].to_numpy()
        for column in labels:
            labels[column][indices, k] = d.loc[mask, column].to_numpy()
    btc_index = coins.index("BTC")
    cash, positions, pending, targets = 1.0, {}, {}, []
    for g, timestamp in enumerate(grid):
        terminal = g == len(grid) - 1
        # All pending instructions were made using the previous completed candle.
        exited = set()
        for k in list(positions):
            pos = positions[k]
            reason = pending.get(k)
            if terminal or g == last.get(k):
                reason = "period_end" if terminal else "data_end"
            if reason and np.isfinite(arrays["o"][g, k]):
                trade = finish_trade(pos["trade"], int(timestamp), arrays["o"][g, k], reason, pos["qty"])
                proceeds = pos["qty"] * trade["exit_fill"] * (1 - FEE)
                delta = proceeds - pos["qty"] * pos["mark"]
                out["regime_pnl"][trade["regime"]][g] += delta
                out["btc_pnl"][trade["btc_regime"]][g] += delta
                cash += proceeds
                out["trades"].append(trade)
                del positions[k]
                exited.add(k)
        pending = {}
        equity_open = cash + sum(p["qty"] * (arrays["o"][g, k] if np.isfinite(arrays["o"][g, k]) else p["mark"])
                                 for k, p in positions.items())
        if not terminal and g > 0:
            for k in targets:
                if k in positions or k in exited or g == last.get(k) or cash <= 0:
                    continue
                opening, previous = arrays["o"][g, k], arrays["c"][g - 1, k]
                stop = previous - 2 * arrays["atr"][g - 1, k]
                if not np.isfinite(opening + stop) or not opening > stop > 0:
                    continue
                fill = opening * (1 + SLIPPAGE)
                budget = min(cash, equity_open / 3)
                qty = budget / (fill * (1 + FEE))
                trade = new_trade(coins[k], timestamp, timestamp, fill, stop, np.nan,
                                  labels["regime"][g - 1, k], labels["btc_regime"][g - 1, k])
                cash -= budget
                positions[k] = {"qty": qty, "trade": trade, "mark": opening, "entry_budget": budget}
        targets = []
        for k, pos in positions.items():
            close = arrays["c"][g, k]
            if not np.isfinite(close):
                pending[k] = "data_gap"
                continue
            trade = pos["trade"]
            observe(trade, arrays["h"][g, k], arrays["l"][g, k], close)
            delta = pos["qty"] * (close - pos["mark"])
            if "entry_budget" in pos:
                delta += pos["qty"] * pos["mark"] - pos.pop("entry_budget")
            out["regime_pnl"][trade["regime"]][g] += delta
            out["btc_pnl"][trade["btc_regime"]][g] += delta
            pos["mark"] = close
            reason = exit_reason(trade, close)
            if reason:
                pending[k] = reason
        value = cash + sum(p["qty"] * p["mark"] for p in positions.values())
        out["equity"][g] = value
        for pos in positions.values():
            weight = pos["qty"] * pos["mark"] / value if value > 0 else 0
            out["exposure"][g] += weight
            out["regime_exposure"][pos["trade"]["regime"]][g] += weight
            out["btc_exposure"][pos["trade"]["btc_regime"]][g] += weight
        if timestamp // step % 24 == 0 and not terminal:
            excess = arrays["ret63"][g] - arrays["ret63"][g, btc_index]
            eligible = np.flatnonzero((excess > 0) & (arrays["ret63"][g] > 0) &
                                      (arrays["c"][g] > arrays["sma200"][g]))
            targets = sorted(eligible, key=lambda k: (-excess[k], coins[k]))[:3]
            for k in positions:
                if k not in targets:
                    pending[k] = "rotation_out"
    if positions:
        raise ValueError("Rotation has unliquidated positions; data coverage cannot support next-bar exit")
    return out


def finite(value):
    return round(float(value), 10) if value is not None and np.isfinite(value) else None


def metrics(trades, equity, grid, exposure, step):
    r = np.array([t["net_R"] for t in trades])
    profit = np.array([t["net_profit"] for t in trades])
    gains, losses = profit[profit > 0].sum(), -profit[profit < 0].sum()
    complete = [t for t in trades if t["false_breakout_observed"]]
    e = np.concatenate([[1.0], np.asarray(equity)])
    peak = np.maximum.accumulate(e)
    years = len(grid) * step / (365.25 * DAY_MS)
    daily = pd.Series(equity, index=pd.to_datetime(grid + step, unit="ms", utc=True))
    # Right-edge daily marks: midnight is the previous day's closing mark.
    daily.index -= pd.Timedelta(milliseconds=1)
    marks = daily.resample("1D").last().to_numpy()
    returns = np.diff(np.concatenate([[1.0], marks])) / np.concatenate([[1.0], marks])[:-1]
    stdev = returns.std(ddof=1) if len(returns) > 1 else 0.0
    downside = np.sqrt(np.mean(np.minimum(returns, 0) ** 2)) if len(returns) else 0.0
    return {
        "trade_count": len(trades), "win_rate": finite((r > 0).mean()) if len(r) else None,
        "mean_R": finite(r.mean()) if len(r) else None, "median_R": finite(np.median(r)) if len(r) else None,
        "profit_factor": finite(gains / losses) if losses > 0 else None,
        "profit_factor_status": "finite" if losses > 0 else "no_losses" if len(r) else "no_trades",
        "CAGR": finite(e[-1] ** (1 / years) - 1) if years > 0 and e[-1] > 0 else None,
        "max_drawdown": finite(max(0, -(e / peak - 1).min())),
        "Sharpe": finite(returns.mean() / stdev * math.sqrt(365.25)) if stdev > 0 else None,
        "Sortino": finite(returns.mean() / downside * math.sqrt(365.25)) if downside > 0 else None,
        "exposure": finite(np.mean(exposure)),
        "MFE": finite(np.mean([t["MFE_R"] for t in trades])) if trades else None,
        "MAE": finite(np.mean([t["MAE_R"] for t in trades])) if trades else None,
        "false_breakout_rate": finite(np.mean([t["false_breakout"] for t in complete])) if complete else None,
        "false_breakout_sample_count": len(complete),
        "average_hold_time": finite(np.mean([t["hold_hours"] for t in trades])) if trades else None,
        "net_total_return": finite(e[-1] - 1),
        "boundary_exit_count": sum(t["exit_reason"] in ("period_end", "data_end") for t in trades),
        "data_gap_exit_count": sum(t["exit_reason"] == "data_gap" for t in trades),
    }


def summarize(path, step):
    equity, trades, grid = path["equity"], path["trades"], path["grid"]
    for kind in ("regime_pnl", "btc_pnl"):
        attributed = sum(path[kind].values())
        if not np.allclose(1 + np.cumsum(attributed), equity, rtol=1e-8, atol=1e-8):
            raise ValueError(f"{kind} attribution does not reconcile to portfolio equity")
    result = {"metrics": metrics(trades, equity, grid, path["exposure"], step)}
    for key, label, pnl_key, exposure_key in (
            ("by_regime", "regime", "regime_pnl", "regime_exposure"),
            ("by_btc_regime", "btc_regime", "btc_pnl", "btc_exposure")):
        result[key] = {}
        for regime in (*REGIMES, "UNKNOWN"):
            ts = [t for t in trades if t[label] == regime]
            subequity = 1 + np.cumsum(path[pnl_key][regime])
            result[key][regime] = metrics(ts, subequity, grid, path[exposure_key][regime], step)
    result["by_asset"] = {
        symbol: {"trade_count": len(ts), "mean_R": finite(np.mean([t["net_R"] for t in ts])),
                 "win_rate": finite(np.mean([t["net_R"] > 0 for t in ts]))}
        for symbol in sorted({t["symbol"] for t in trades})
        for ts in [[t for t in trades if t["symbol"] == symbol]]}
    result["execution_audit"] = {
        "fills_before_signal_close": sum(t["entry_ms"] < t["signal_close_ms"] for t in trades),
        "entry_not_at_next_open": sum(t["entry_ms"] != t["signal_close_ms"] for t in trades),
        "cross_period_trades": int(sum(t["entry_ms"] < grid[0] or t["exit_ms"] >= grid[-1] + step for t in trades)),
        "holdout_trades": sum(t["entry_ms"] >= ms(LOCK) or t["exit_ms"] >= ms(LOCK) for t in trades),
        "last_entry_ms": max((t["entry_ms"] for t in trades), default=None),
        "last_exit_ms": max((t["exit_ms"] for t in trades), default=None),
    }
    # Small audit sample; all aggregate calculations above use the complete trade population.
    result["trade_samples"] = trades[:3] + (trades[-3:] if len(trades) > 3 else [])
    return result


def evaluate(frames, daily, coins):
    output, btc = {}, features(daily, DAY_MS)
    periods = {"development": (START, VALIDATION), "validation": (VALIDATION, LOCK)}
    for tf, step in TF_MS.items():
        prepared = {coin: features(resample(d, tf), step, btc) for coin, d in frames.items() if len(d)}
        for name in STRATEGIES:
            output.setdefault(name, {"status": "RESEARCH_ONLY", "automatic_production_eligible": False,
                                     "timeframes": {}})
            plans = {coin: signals(d, name) for coin, d in prepared.items()} if name != "relative_strength_rotation" else {}
            reports = {}
            for period, (start, end) in periods.items():
                if name == "relative_strength_rotation":
                    path = simulate_rotation(prepared, step, start, end)
                else:
                    grid = np.arange(ms(start), ms(end), step, dtype=np.int64)
                    paths = (simulate_asset(d, plans[coin], coin, step, start, end) for coin, d in prepared.items())
                    path = combine_sleeves(paths, len(coins), grid)
                reports[period] = summarize(path, step)
            output[name]["timeframes"][tf] = reports
            print(f"SCORED {name} {tf}: dev={reports['development']['metrics']['trade_count']} "
                  f"val={reports['validation']['metrics']['trade_count']}", flush=True)
    return output, btc


def run(coins):
    before = protected_hashes()
    frames, daily, coverage, daily_hash = asyncio.run(load_data(coins))
    output, btc = evaluate(frames, daily, coins)
    for coin, d in frames.items():
        coverage[coin]["bars_15m"] = len(d)
        coverage[coin]["first_open"] = iso(d.t.iloc[0]) if len(d) else None
        coverage[coin]["last_close"] = iso(d.t.iloc[-1] + TF_MS["15m"]) if len(d) else None
        coverage[coin]["missing_intervals_within_observed_history"] = int(
            ((d.t.diff().dropna() / TF_MS["15m"]) - 1).clip(lower=0).sum()) if len(d) else 0
    after = protected_hashes()
    if before != after:
        raise ValueError("Protected source or prior results changed during research")
    report = {
        "schema_version": 3, "status": "RESEARCH_ONLY", "production_integration": False,
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "code_sha256": digest(Path(__file__)), "parameters": PARAMETERS,
        "periods": {"development": {"start": START.isoformat(), "end_exclusive": VALIDATION.isoformat()},
                    "validation": {"start": VALIDATION.isoformat(), "end_exclusive": LOCK.isoformat()},
                    "locked_holdout": {"start": LOCK.isoformat(), "status": "NOT_LOADED_NOT_SCORED"}},
        "methodology": {
            "market": "Binance spot USDT; long only; no leverage",
            "universe_source": "Frozen existing research.engine.CRYPTO, including failed/delisted symbols",
            "parameters_selected_on": "Predeclared before scoring; no optimization on development or validation",
            "execution": "Signal on completed bar; buy/sell at the next available bar open",
            "fees_per_side": FEE, "slippage_per_side": SLIPPAGE,
            "stops_and_targets": "Close-confirmed thresholds; next-open exits; gaps can lose more than 1R",
            "period_boundaries": "Flat initial portfolios; terminal bar reserved for next-open liquidation; no cross-period trades",
            "early_data_ends": "Liquidate at final observed open; flagged data_end; unknown delisting losses are not reconstructed",
            "allocation": "Five independent strategies: fixed equal-capital asset sleeves, idle sleeves cash. "
                          "Rotation: actual pooled top-3 portfolio, new allocation <= equity/3; retained holdings not resized",
            "local_regime": "Each asset's completed timeframe bar: SMA50/200, ADX14, ATR percentile100, return20; "
                            "PANIC > HIGH_VOL > TREND_UP > TREND_DOWN > RANGE",
            "btc_regime": "Same regime rules on BTC daily bars; as-of join only after the daily bar has closed",
            "regime_returns": "P&L attributed to regime at entry signal; full calendar denominator; not a tradable regime filter",
            "CAGR": "Compounded marked portfolio equity; 365.25-day year; decimal fraction",
            "max_drawdown": "Positive fraction; candle-close marks including initial cash (intrabar losses may be larger)",
            "Sharpe_Sortino": "UTC daily portfolio returns, sqrt(365.25), zero risk-free rate; downside RMS includes zero/up days",
            "R": "Net P&L per unit / (slippage-adjusted entry fill - initial stop); both fees included in numerator",
            "profit_factor": "Sum positive net monetary P&L / absolute sum negative net monetary P&L",
            "MFE_MAE": "Mean favorable/adverse excursion in initial R; completed holding-bar highs/lows plus exit open; excludes exit-bar extremes",
            "false_breakout_rate": "Closed price below fixed breakout level within first 3 held bars; "
                                   "only breakout/retest, failed-breakout/reclaim and compression entries; short unresolved windows censored",
            "average_hold_time": "Hours from entry open to exit open",
            "exposure": "Equal-sleeve time exposure for independent strategies; invested equity fraction for rotation",
            "null_metrics": "Undefined ratios/no trades/not applicable are JSON null, never NaN or Infinity",
        },
        "limitations": [
            "Inherited universe is not a point-in-time exchange universe; inclusion of delisted coins reduces but does not eliminate selection bias.",
            "Unavailable symbols and unlisted history stay cash; coverage is reported explicitly.",
            "Early data-end liquidation uses the observed endpoint; actual delisting liquidation may be worse.",
            "No order-book capacity model; fixed slippage is a scenario, not measured execution quality.",
            "No parameter search, significance claim, random-entry baseline or production verdict in this first research pass.",
            "Sparse regime cells and multiple candidate/timeframe comparisons require independent follow-up before any deployment decision.",
        ],
        "data": {"planned_universe": coins, "loaded_assets": len(frames),
                 "assets_with_bars": sum(bool(len(d)) for d in frames.values()), "coverage": coverage,
                 "btc_daily_sha256": daily_hash,
                 "btc_regime_bar_counts": {p: btc.loc[(btc.t + DAY_MS > ms(a)) & (btc.t + DAY_MS <= ms(b)), "regime"].value_counts().to_dict()
                                            for p, (a, b) in {"development": (START, VALIDATION), "validation": (VALIDATION, LOCK)}.items()}},
        "integrity": {"advisor_and_prior_research_unchanged": True, "protected_file_sha256": before,
                      "maximum_allowed_data_close_ms": ms(LOCK), "locked_holdout_scored": False},
        "strategies": output,
    }
    temporary = RESULTS.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(RESULTS)
    print(f"RESULT {RESULTS}", flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()
    if args.download_only:
        asyncio.run(load_data(CRYPTO))
    else:
        run(CRYPTO)

"""Close-only backtests and outcome evaluation.

Same rules as live alerts: only candle CLOSES count, for entry, stop and target alike.
"""
import time

import httpx
import pandas as pd

import config
import market

TF_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
         "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "6h": 21_600_000, "8h": 28_800_000,
         "12h": 43_200_000, "1d": 86_400_000, "3d": 259_200_000, "1w": 604_800_000}
MAX_CANDLES = 40_000  # keeps a backtest to ~40 REST calls


def outcome(after: pd.DataFrame, direction: str, entry: float, stop: float | None,
            target: float | None, max_candles: int = 500) -> dict:
    """Walk forward from the candle after entry. First close beyond stop or target wins."""
    long = direction == "ABOVE"
    risk = abs(entry - stop) if stop is not None else None
    for i, row in enumerate(after.head(max_candles).itertuples(), start=1):
        c = row.close
        if stop is not None and (c < stop if long else c > stop):
            return {"sonuc": "stop", "cikis": c, "mum": i, "R": _r(entry, c, risk, long)}
        if target is not None and (c >= target if long else c <= target):
            return {"sonuc": "hedef", "cikis": c, "mum": i, "R": _r(entry, c, risk, long)}
    last = after.head(max_candles)
    if last.empty:
        return {"sonuc": "veri yok", "cikis": None, "mum": 0, "R": None}
    c = last.close.iloc[-1]
    return {"sonuc": "açık", "cikis": c, "mum": len(last), "R": _r(entry, c, risk, long)}


def _r(entry, exit_, risk, long):
    if not risk:
        return None
    return round(((exit_ - entry) if long else (entry - exit_)) / risk, 2)


def net_r(entry, exit_, stop, long, cost_pct):
    """R after costs: each side pays fee + slippage (cost_pct, percent of price).
    Risk stays the planned entry-to-stop distance, so costs show up as lost R."""
    if stop is None or exit_ is None or entry == stop:
        return None
    c = cost_pct / 100
    if long:
        pnl = exit_ * (1 - c) - entry * (1 + c)
    else:
        pnl = entry * (1 - c) - exit_ * (1 + c)
    return round(pnl / abs(entry - stop), 2)


async def run(pair_symbol: str, direction: str, trigger: float, tf: str, days: int,
              stop: float | None, target: float | None,
              fee_pct: float | None = None, slippage_pct: float | None = None,
              market_name: str = "KRIPTO") -> dict:
    fee = config.BACKTEST_FEE_PCT if fee_pct is None else fee_pct
    slip = config.BACKTEST_SLIPPAGE_PCT if slippage_pct is None else slippage_pct
    start = int(time.time() * 1000) - days * 86_400_000
    if days * 86_400_000 / TF_MS[tf] > MAX_CANDLES:
        start = int(time.time() * 1000) - MAX_CANDLES * TF_MS[tf]
    async with httpx.AsyncClient() as client:
        if market_name == "BIST":
            import bist
            df = await bist.fetch(client, pair_symbol, tf)
            df = df[df.open_time >= start].reset_index(drop=True)
        else:
            df = await market.fetch_range(client, pair_symbol, tf, start)
        df = market.add_indicators(df)
    if len(df) < 30:
        return {"hata": "yeterli mum yok"}

    long = direction == "ABOVE"
    atr_default = stop is None or target is None
    trades = []
    i = 1
    while i < len(df):
        prev, cur = df.iloc[i - 1], df.iloc[i]
        crossed = prev.close <= trigger < cur.close if long else prev.close >= trigger > cur.close
        if not crossed:
            i += 1
            continue
        atr = cur.atr14 if cur.atr14 == cur.atr14 else None
        s = stop if stop is not None else (atr and (cur.close - 1.5 * atr if long else cur.close + 1.5 * atr))
        t = target if target is not None else (atr and (cur.close + 2 * atr if long else cur.close - 2 * atr))
        if market_name == "BIST" and t is not None and cur.close >= t:
            i += 1  # a gap already beyond the target is not a usable entry
            continue
        res = outcome(df.iloc[i + 1:], direction, cur.close, s, t)
        vol_ok = cur.vol_avg20 == cur.vol_avg20 and cur.volume > cur.vol_avg20
        trades.append({"zaman": market._ts(cur.open_time), "giris": cur.close, "hacim_teyitli": bool(vol_ok), **res,
                       "R_net": net_r(cur.close, res["cikis"], s, long, fee + slip)})
        i += max(res["mum"], 1) + 1  # no overlapping trades

    def stats(ts):
        closed = [t for t in ts if t["sonuc"] in ("hedef", "stop")]
        rs = [t["R"] for t in closed if t["R"] is not None]
        nets = [t["R_net"] for t in closed if t.get("R_net") is not None]
        return {"islem": len(ts), "hedef": sum(t["sonuc"] == "hedef" for t in ts),
                "ort_R_net": round(sum(nets) / len(nets), 2) if nets else None,
                "toplam_R_net": round(sum(nets), 2) if nets else None,
                "stop": sum(t["sonuc"] == "stop" for t in ts), "acik": sum(t["sonuc"] == "açık" for t in ts),
                "isabet_yuzde": round(sum(t["sonuc"] == "hedef" for t in closed) / len(closed) * 100) if closed else None,
                "ort_R": round(sum(rs) / len(rs), 2) if rs else None,
                "toplam_R": round(sum(rs), 2) if rs else None}

    return {"donem": f"{market._ts(df.open_time.iloc[0])} → {market._ts(df.open_time.iloc[-1])} UTC",
            "mum_sayisi": len(df), "atr_varsayilan": atr_default,
            "maliyet": {"komisyon_yuzde": fee, "kayma_yuzde": slip},
            "tum": stats(trades), "hacim_teyitli": stats([t for t in trades if t["hacim_teyitli"]]),
            "hacimsiz": stats([t for t in trades if not t["hacim_teyitli"]]),
            "son_islemler": trades[-5:],
            "islemler": [{**t, "giris": float(t["giris"]), "cikis": None if t["cikis"] is None else float(t["cikis"]),
                          "R": None if t["R"] is None else float(t["R"]),
                          "R_net": None if t.get("R_net") is None else float(t["R_net"])} for t in trades]}


async def evaluate_decision(d: dict) -> dict:
    """What happened after a logged alert decision, judged by closes on the alert's timeframe."""
    long = d["yon"] == "ABOVE"
    async with httpx.AsyncClient() as client:
        if d.get("piyasa") == "BIST":
            import bist
            df = await bist.fetch(client, d["symbol"], "1h")
            df = df[df.open_time > d["mum_ms"]]
        else:
            df = await market.fetch_range(client, d["symbol"], d["timeframe"], d["mum_ms"] + TF_MS[d["timeframe"]])
    return outcome(df, "ABOVE" if long else "BELOW", d["kapanis"], d.get("iptal"), d.get("hedef"))

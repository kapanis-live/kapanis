"""MarketSnapshot: the one frozen picture of a coin that the planners and the three AI analysts all read.

    build(data, ...)  ->  MarketSnapshot(raw JSON, hash)

Everything that needs candle arrays is computed here, once: indicators, confirmed swings, zones, the breakout /
retest / reclaim facts, the BTC regime, the portfolio's exposure. The planners are pure functions of the dict that
comes out, so the same snapshot always gives the same order plan, whatever the AI analysts write.

Closed candles only. The open 15m candle gives `current_price` (and the no-chase distance, which is a guard, not a
confirmation); it never confirms a breakout, a retest, a swing, a trend or a touch. The indicator, swing, trend and
breakout-state code is the first advisor's (danisman.py), unchanged.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_FLOOR, Decimal

import numpy as np

import danisman as d

from . import config as cfg

TREND = {"STRONG_UPTREND": "STRONG_UP", "UPTREND": "UP", "RANGE": "RANGE", "DOWNTREND": "DOWN",
         "STRONG_DOWNTREND": "STRONG_DOWN", "INSUFFICIENT_HISTORY": "INSUFFICIENT_HISTORY"}
UPS, DOWNS = ("UP", "STRONG_UP"), ("DOWN", "STRONG_DOWN")
VOLATILE = ("generated_at", "data_age_seconds")     # not part of the hash: they change with the clock, not the market
AI_CANDLES = {"15m": "AI_CANDLES_15M", "1h": "AI_CANDLES_1H", "4h": "AI_CANDLES_4H", "1d": "AI_CANDLES_1D"}


@dataclass(frozen=True)
class MarketSnapshot:
    """Immutable: the canonical JSON text and its hash. data() hands out a fresh copy every time."""
    raw: str
    hash: str

    def data(self) -> dict:
        return json.loads(self.raw)


def freeze(snapshot: dict) -> MarketSnapshot:
    body = {k: v for k, v in snapshot.items() if k not in VOLATILE}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:16]
    return MarketSnapshot(json.dumps({**snapshot, "snapshot_hash": digest}, sort_keys=True, default=str), digest)


# ---------------- ticks ----------------
def floor_tick(x: float, tick: float) -> float:
    q = Decimal(str(tick))
    return float((Decimal(repr(float(x))) / q).to_integral_value(rounding=ROUND_FLOOR) * q)


def next_tick(x: float, tick: float) -> float:
    """The first tick strictly above x."""
    q = Decimal(str(tick))
    return float(((Decimal(repr(float(x))) / q).to_integral_value(rounding=ROUND_FLOOR) + 1) * q)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _n(x, nd: int | None = None):
    return d._n(x, nd)


# ---------------- zones ----------------
def zones(views: dict, price: float, now_ms: int) -> tuple[list[dict], list[dict], list[dict]]:
    """(supports, resistances, 15m-only zones), nearest first.

    A zone is a cluster of CONFIRMED swing points of the 1h and 4h candles that lie within ZONE_CLUSTER_ATR1H x the 1h
    ATR of the cluster's first level. A 15m swing never makes a main zone; inside one it is another touch. 15m swings
    outside every main zone are clustered on their own (by the 15m ATR) and reported as minor zones: the 1h zones
    come first in every decision. The dicts keep the keys the first advisor's breakout code expects."""
    atr = float(views["1h"].atr[-1])
    pts: dict[tuple, dict] = {}
    for tf in ("4h", "1h"):
        for p in d.swing_points(views[tf]) if tf in views else []:
            q = pts.get((p["kind"], p["price"]))
            if q:
                q["tf"] |= p["tf"]
                q["known"] = min(q["known"], p["known"])
            else:
                pts[(p["kind"], p["price"])] = p

    def cluster(points, tol):
        groups, base = [], None
        for p in sorted(points, key=lambda x: x["price"]):
            if base is None or p["price"] - base > tol:
                groups.append([p])
                base = p["price"]
            else:
                groups[-1].append(p)
        return groups

    def level(g, tf_step):
        lo, hi = g[0]["price"], g[-1]["price"]
        tfs = set().union(*[p["tf"] for p in g])
        vols = [p["vol"] for p in g if p["vol"] == p["vol"]]
        last = max(p["t"] for p in g)
        is_res = hi >= price          # inside the zone counts as resistance: it has to be closed above
        highs = sum(p["kind"] == "H" for p in g)
        return {"price": hi if is_res else lo, "zone": [lo, hi], "touch_count": len(g),
                "age_bars": round((now_ms - last) / tf_step), "last_touch_ms": int(last),
                "distance_pct": round((max(lo, price) if is_res else hi) / price * 100 - 100, 2),
                "strength": {"touch_count": len(g), "volume_on_reactions": round(float(np.mean(vols)), 2) if vols else None,
                             "hours_since_last_touch": round((now_ms - last) / d.TFS["1h"], 1),
                             "timeframe": sorted(tfs, key=list(d.TFS).index)},
                "highs": highs, "lows": len(g) - highs, "known": min(p["known"] for p in g), "is_resistance": is_res}

    minor_pts = [p for p in d.swing_points(views["15m"]) if (p["kind"], p["price"]) not in pts]
    sup, res = [], []
    for g in cluster(pts.values(), cfg.ZONE_CLUSTER_ATR1H * atr):
        lo, hi = g[0]["price"], g[-1]["price"]
        g = g + [p for p in minor_pts if lo <= p["price"] <= hi]
        lvl = level(g, d.TFS["1h"])
        (res if lvl["is_resistance"] else sup).append(lvl)
    main = [x["zone"] for x in sup + res]
    loose = [p for p in minor_pts if not any(z[0] <= p["price"] <= z[1] for z in main)]
    minor = [level(g, d.TFS["15m"]) for g in cluster(loose, cfg.ZONE_CLUSTER_ATR1H * float(views["15m"].atr[-1]))]
    minor.sort(key=lambda x: abs(x["price"] - price))
    return sup[::-1], res, minor


def public_zone(lvl: dict) -> dict:
    """A zone as the snapshot shows it."""
    kind = "swing_high" if lvl["lows"] == 0 else "swing_low" if lvl["highs"] == 0 else "swing_high+swing_low"
    return {"low": _n(lvl["zone"][0]), "high": _n(lvl["zone"][1]), "touch_count": lvl["touch_count"],
            "last_touch_timestamp": _iso(lvl["last_touch_ms"]), "timeframe": lvl["strength"]["timeframe"],
            "strength": lvl["strength"], "source": kind, "distance_pct": lvl["distance_pct"],
            "swing_highs": lvl["highs"], "swing_lows": lvl["lows"]}


# ---------------- structure ----------------
def structure(views: dict, sup: list[dict], res: list[dict], live15: dict | None, price: float) -> dict:
    """What the price has done at its levels, from closed 15m (and 1h) candles: breakout, failure, reclaim, retest."""
    b15, b1 = views["15m"], views["1h"]
    i, c, h, lw = b15.n - 1, b15.c, b15.h, b15.l
    step = d.TFS["15m"]
    atr15, atr1h = float(b15.atr[-1]), float(b1.atr[-1])
    bo = d.find_breakout(b15, sup, res, atr1h, live15)
    status = bo["status"]
    out = {"breakout_status": status, "confirmed_breakout": status == "CONFIRMED",
           "failed_breakout": status in ("FAILED_BREAKOUT", "RECLAIM_TESTING"), "reclaim": None, "retest": None,
           "broken_resistance": None, "retest_zone": None, "control_level": _n(bo.get("level")),
           "distance_from_control_level_atr": None if bo.get("level") is None else _n((price - bo["level"]) / atr15, 2),
           "breakout": {k: v for k, v in bo.items() if k not in ("status",)}, "open_candle_above": bool(bo.get("open_candle_above"))}
    if status == "CONFIRMED":
        zone_lo, top = bo["zone"]
        lvl = next(x for x in sup if x["zone"] == bo["zone"])
        t0 = i - bo["bars_ago"]
        start = max(int(np.searchsorted(b15.t, lvl["known"])), i - d.RETEST_WINDOW, 1)
        ups = [t for t in range(start, i + 1) if c[t - 1] <= top < c[t]]
        downs = [t for t in range(start, i + 1) if c[t - 1] > top >= c[t]]
        out["broken_resistance"] = _n(top)
        if len(ups) >= 2 and downs:
            # closed above, fell back under, closed above again: the last close above is a reclaim, not a first breakout
            held = i - t0
            out["reclaim"] = {"level": _n(top), "failed_at": _iso(int(b15.t[downs[-1]]) + step),
                              "reclaim_candle_time": _iso(int(b15.t[t0]) + step), "held_bars": int(held),
                              "confirmed": bool(held >= cfg.RECLAIM_HOLD_BARS),
                              "hold_high": _n(float(h[t0:i + 1].max())), "hold_low": _n(float(lw[t0:i + 1].min()))}
        zone_hi = top + cfg.RETEST_ZONE_ATR1H * atr1h
        away = next((t for t in range(t0, i + 1) if c[t] > zone_hi), None)
        back = None if away is None else next((t for t in range(away + 1, i + 1) if lw[t] <= zone_hi), None)
        conf = None if back is None else next((t for t in range(i, back - 1, -1) if lw[t] <= zone_hi and c[t] > top), None)
        out["retest_zone"] = [_n(zone_lo), _n(zone_hi)]
        out["retest"] = {
            "broken_resistance": _n(top), "zone_low": _n(zone_lo), "zone_high": _n(zone_hi),
            "breakout_candle_time": _iso(int(b15.t[t0]) + step), "moved_away": away is not None,
            "entered_zone": back is not None, "in_zone_now": bool(lw[i] <= zone_hi),
            "distance_atr15": _n(max(price - zone_hi, 0.0) / atr15, 2),
            "structure_low": None if back is None else _n(float(lw[back:i + 1].min())),
            "confirmation": None if conf is None else {
                "time": _iso(int(b15.t[conf]) + step), "closed": True, "bars_ago": int(i - conf), "high": _n(float(h[conf])),
                "low": _n(float(lw[conf])), "close": _n(float(c[conf]))}}
    # a support that the 1h candles closed under a short while ago (position protection reads this)
    c1, t1 = b1.c, b1.t
    j = b1.n - 1
    lost = None
    for lvl in res:
        if not lvl["lows"] or lvl["touch_count"] < cfg.MAJOR_SUPPORT_MIN_TOUCHES:
            continue                     # a single reaction is not a "major" support
        lo = lvl["zone"][0]
        k = next((k for k in range(j, max(j - cfg.SUPPORT_LOST_BARS, 0), -1)
                  if c1[k - 1] >= lo > c1[k] and lvl["known"] <= t1[k]), None)
        if k is not None and c1[j] < lo:
            lost = {"low": _n(lo), "high": _n(lvl["zone"][1]), "bars_ago": int(j - k),
                    "closed_below_at": _iso(int(t1[k]) + d.TFS["1h"]), "touch_count": lvl["touch_count"]}
            break
    out["lost_support"] = lost
    # the last closed 15m candle: did it reach the nearest resistance and get turned back?
    rng = h[i] - lw[i]
    wick = (h[i] - max(b15.o[i], c[i])) / rng if rng > 0 else 0.0
    out["rejection"] = bool(res and h[i] >= res[0]["zone"][0] and c[i] < res[0]["zone"][0] and wick >= cfg.REJECTION_WICK_RATIO)
    lows = d.confirmed_swings(b15, "L")
    out["higher_low_15m"] = None
    if len(lows) >= 2 and lw[lows[-2]] < lw[lows[-1]] < c[i]:       # a higher low that the price is still above
        out["higher_low_15m"] = {"price": _n(float(lw[lows[-1]])), "time": _iso(int(b15.t[lows[-1]]) + step),
                                 "previous": _n(float(lw[lows[-2]]))}
    swing = d.sl.swing_low_at(b1, j)
    out["swing_low_1h"] = None if swing != swing else _n(swing)
    return out


# ---------------- BTC regime ----------------
def btc_regime(data: dict, asof: int) -> dict:
    """BTC's 15m / 1h / 4h trend, shared by every altcoin report. RISK_OFF (1h and 4h both in a strong downtrend)
    blocks new altcoin longs; CAUTION (either one falling) is a warning; a range is neutral."""
    views = {}
    for tf in ("15m", "1h", "4h"):
        closed = d.split(data["btc"][tf], tf, asof)[0]
        if len(closed) >= d.TREND_BARS:
            views[tf] = d.view(closed, tf)
    trend = {tf: TREND[d.trend_state(views[tf])["state"]] if tf in views else "INSUFFICIENT_HISTORY" for tf in ("15m", "1h", "4h")}
    h1, h4, m15 = trend["1h"], trend["4h"], trend["15m"]
    regime = ("RISK_OFF" if h1 == "STRONG_DOWN" and h4 == "STRONG_DOWN" else
              "CAUTION" if h1 in DOWNS or h4 in DOWNS else "RISK_ON" if h1 in UPS and h4 in UPS else "NEUTRAL")
    b1 = views.get("1h")
    return {"trend_15m": m15, "trend_1h": h1, "trend_4h": h4, "regime": regime,
            # the first advisor's own rule, kept for comparison with its paper records
            "v1_market_risk": bool(h1 == "STRONG_DOWN" or (h1 in DOWNS and m15 in DOWNS)),
            "rsi_1h": None if b1 is None else _n(b1.rsi[-1], 1),
            "atr_pct_1h": None if b1 is None else _n(b1.atr[-1] / b1.c[-1] * 100, 2),
            "atr_percentile_1h": None if b1 is None else _n(b1.atr_rank[-1] * 100, 0)}


# ---------------- portfolio ----------------
def portfolio_facts(symbol: str, price: float, portfolio: dict | None, corr: dict) -> dict:
    """The portfolio as the risk rules see it. portfolio: {"value", "cash", "total_known", "holdings": [{"symbol",
    "value", "quantity", "entry_price", "initial_stop", "stop", "opened_at"}]}; value None = unknown. total_known:
    `value` covers every market and the cash, so the share of crypto in it means something."""
    p = portfolio or {}
    value = p.get("value")
    held = [x for x in p.get("holdings") or [] if x.get("symbol")]
    mine = next((x for x in held if x["symbol"].upper() == symbol), None)
    out = {"portfolio_value": _n(value), "available_cash": _n(p.get("cash")), "total_known": bool(p.get("total_known")),
           "holding_exists": mine is not None, "position_value": None, "entry_price": None, "quantity": None,
           "unrealized_pnl": None, "unrealized_pnl_pct": None, "position_R": None, "initial_stop": None, "current_stop": None,
           "initial_stop_source": None,
           "opened_at": None, "asset_class": d.coin_class(symbol), "correlations": corr,
           "correlation_group": sorted(k for k, v in corr.items() if v >= cfg.HIGH_CORRELATION),
           "positions": len(held), "holdings": []}
    if mine:
        qty, entry = mine.get("quantity"), mine.get("entry_price")
        pos_value = qty * price if qty else mine.get("value")
        out.update(position_value=_n(pos_value), entry_price=_n(entry), quantity=_n(qty), opened_at=mine.get("opened_at"),
                   initial_stop=_n(mine.get("initial_stop")), current_stop=_n(mine.get("stop")),
                   initial_stop_source=mine.get("initial_stop_source"))
        if qty and entry:
            out.update(unrealized_pnl=_n(qty * (price - entry)), unrealized_pnl_pct=_n((price / entry - 1) * 100, 2))
            if mine.get("initial_stop") and entry > mine["initial_stop"]:
                out["position_R"] = _n((price - entry) / (entry - mine["initial_stop"]), 2)
    values = {x["symbol"].upper(): float(x.get("value") or 0.0) for x in held}
    if mine and out["position_value"]:
        values[symbol] = out["position_value"]
    out["holdings"] = [{"symbol": s, "value": _n(v, 2), "asset_class": d.coin_class(s)} for s, v in values.items()]
    crypto = sum(values.values())

    def share(v):
        return None if not value else _n(v / value * 100, 2)

    def by_class(cls):
        return sum(v for s, v in values.items() if d.coin_class(s) == cls)

    out.update(crypto_value=_n(crypto, 2), portfolio_crypto_exposure=share(crypto),
               portfolio_alt_exposure=share(by_class("ALT")), portfolio_meme_exposure=share(by_class("MEME")),
               portfolio_correlated_exposure=share(sum(values.get(s, 0.0) for s in out["correlation_group"])))
    return out


# ---------------- the snapshot ----------------
def build(data: dict, portfolio: dict | None = None, macro: dict | None = None, asof_ms: int | None = None,
          now_ms: int | None = None, v1_reference: dict | None = None) -> MarketSnapshot:
    """data = danisman.fetch(...) plus data["filters"] (tick_size, step_size, min_qty, min_notional). Pure when
    asof_ms is given (a replay: no open candle, no staleness). Raises ValueError when 15m or 1h history is too short."""
    live_mode = asof_ms is None
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    asof = now if live_mode else int(asof_ms)
    symbol, pair, quote = data["symbol"], data["pair"], data["quote"]
    views, counts, live15 = {}, {}, None
    for tf in d.TFS:
        closed, live = d.split(data["frames"][tf], tf, asof)
        counts[tf] = len(closed)
        if len(closed) < d.NEED_BARS[tf]:
            raise ValueError(f"{pair} {tf}: {len(closed)} kapanmış mum var, en az {d.NEED_BARS[tf]} gerekli (parite çok yeni)")
        if len(closed) >= d.TREND_BARS:
            views[tf] = d.view(closed, tf)
        if tf == "15m":
            live15 = live if live_mode else None
    b15 = views["15m"]
    close15 = float(b15.c[-1])
    price = float(live15["c"]) if live15 else close15
    market_ms = int(b15.t[-1]) + d.TFS["15m"]
    age = max(0, (now - market_ms) // 1000) if live_mode else 0
    sup, res, minor = zones(views, close15, asof)
    frames = {}
    for tf in d.TFS:
        if tf not in views:
            frames[tf] = {"bars": counts[tf], "trend": "INSUFFICIENT_HISTORY", "trend_evidence": [], "indicators": None,
                          "swing_highs": [], "swing_lows": [], "candles": []}
            continue
        b = views[tf]
        tr = d.trend_state(b)

        def swings(kind, arr):
            return [[_n(float(arr[k])), _iso(int(b.t[k]) + d.TFS[tf])] for k in d.confirmed_swings(b, kind)[-4:]]

        tail = slice(max(0, b.n - getattr(cfg, AI_CANDLES[tf])), b.n)
        frames[tf] = {"bars": counts[tf], "trend": TREND[tr["state"]], "trend_evidence": tr["reasons"],
                      "indicators": d.snapshot(b), "swing_highs": swings("H", b.h), "swing_lows": swings("L", b.l),
                      # [close time, open, high, low, close, quote volume], closed candles only
                      "candles": [[_iso(int(t) + d.TFS[tf]), float(o), float(hh), float(ll), float(cc), round(float(v), 2)]
                                  for t, o, hh, ll, cc, v in zip(b.t[tail], b.o[tail], b.h[tail], b.l[tail], b.c[tail], b.v[tail])]}
    corr = d.correlations(data["frames"]["1h"], data.get("others") or {}, asof)
    st = structure(views, sup, res, live15, price)
    filters = data.get("filters")
    snapshot = {
        "symbol": symbol, "pair": pair, "base_asset": symbol, "quote_asset": quote,
        "market_timestamp": _iso(market_ms), "market_timestamp_ms": market_ms, "generated_at": _iso(now),
        "data_age_seconds": int(age), "live": live_mode,
        "stale": bool(live_mode and age > cfg.MAX_DATA_AGE_SECONDS),
        "current_price": price, "last_closed_15m": close15,
        "price_source": "open 15m candle (display and no-chase only)" if live15 else "last closed 15m candle",
        "timeframes": frames,
        "structure": {"trend_15m": frames["15m"]["trend"], "trend_1h": frames["1h"]["trend"],
                      "trend_4h": frames["4h"]["trend"], "trend_1d": frames["1d"]["trend"],
                      "supports": [public_zone(x) for x in sup[:cfg.ZONES_KEPT]],
                      "resistances": [public_zone(x) for x in res[:cfg.ZONES_KEPT]],
                      "minor_zones_15m": [public_zone(x) for x in minor[:cfg.ZONES_KEPT]],
                      "nearest_support": public_zone(sup[0]) if sup else None,
                      "nearest_resistance": public_zone(res[0]) if res else None, **st},
        "insufficient_history": [tf for tf in d.TFS if tf not in views],
        "btc": btc_regime(data, asof) | {"applies": symbol != "BTC"},
        "portfolio": portfolio_facts(symbol, price, portfolio, corr),
        "macro": macro or {"macro_status": "NOT_REQUESTED"},
        # what the first advisor (Telegram /danis) says about the same candles: a cross-check, and its pullback zone
        "v1_reference": v1_reference,
        "execution": None if not filters else {
            "tick_size": filters["tick_size"], "step_size": filters.get("step_size"), "min_qty": filters.get("min_qty"),
            "min_notional": filters.get("min_notional"), "quote_currency": quote},
    }
    return freeze(_clean(snapshot))


def _clean(x):
    """JSON-safe: numpy numbers to Python ones, NaN / inf to None."""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return None if x != x or math.isinf(x) else float(x)
    return x

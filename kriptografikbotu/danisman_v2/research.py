"""Paper research for V2: what a plan would have done, which exit style would have suited it, how often a stop was a
whipsaw. It measures; it never changes a rule. Thresholds are not tuned from these numbers without a real sample.

    paper_row()        one V2 run as a record for the first advisor's paper log (danisman_paper: same store, same
                       duplicate rule, same LIVE / REPLAY / TEST origins; its tracker fills the 1h / 4h / 24h outcome)
    simulate()         the same entry under four exit styles, and the whipsaw facts of every stop
    update_outcomes()  fill outcome["v2"] for records whose research horizon has passed
    stats()            per exit style: expectancy, win rate, drawdown, whipsaw rate ... INCONCLUSIVE below MIN_SAMPLE

Exit styles compared (the entry and the first stop are the plan's own in all four):
    A  structural stop + structural target        B  structural stop + 2.5R target
    C  structural stop, no target, 3 ATR(1h) trail D  structural stop, no target, trail under confirmed 15m higher lows
A candle that holds both the stop and the target counts as the stop (conservative).
"""
from __future__ import annotations

import hashlib
import logging
import os
import statistics
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import danisman as d

from . import config as cfg

log = logging.getLogger(__name__)
M15, H1 = 900_000, 3_600_000
WARMUP_MS = 3 * 86_400_000           # candles before the record, so that ATR at the stop has a history
SWING_K = 3
VARIANTS = {"A": "yapısal stop + yapısal hedef", "B": "yapısal stop + 2,5R hedef",
            "C": "yapısal stop + 3 ATR iz süren", "D": "yapısal stop + teyitli yükselen dip"}
CLASS_OF = {"BUY_SETUP": "READY_TO_WATCH"}      # the paper log's class names; every other status keeps its own name
BUCKETS = ((0, 1.25), (1.25, 1.5), (1.5, 1.75), (1.75, 2.0), (2.0, 99.0))


def ruleset_hash() -> str:
    return cfg.ruleset_hash(d.ruleset())


def setup_id(s: dict, engine: dict) -> tuple[str, str]:
    """(id, key): the same setup seen again keeps its id; a new level or a new confirming candle makes a new one."""
    st, day = s["structure"], s["market_timestamp"][:10]
    level = st.get("broken_resistance") or st.get("control_level") or (st.get("nearest_resistance") or {}).get("high")
    anchor = day
    if st.get("retest") and engine["setup"] in ("BREAKOUT", "RETEST", "RECLAIM"):
        conf = st["retest"].get("confirmation")
        anchor = (conf["time"] if engine["setup"] == "RETEST" and conf else st["retest"]["breakout_candle_time"])
    under = engine.get("underlying_status") or engine["status"]
    parts = ["v2", s["symbol"], engine["setup"], under, "-" if level is None else f"{level:.6g}", anchor]
    if engine["status"] == "BLOCKED_SETUP":
        parts += ["BLOCKED", engine["blocks"][0]["code"]]
    if engine["setup"] == "NONE":
        parts = ["v2", s["symbol"], engine["status"], day]
    key = "|".join(parts)
    return hashlib.sha1(key.encode()).hexdigest()[:16], key


def paper_row(s: dict, engine: dict, consensus: dict | None, source: str, origin: str | None = None) -> dict:
    """A V2 run as a paper-log record. The field names the tracker reads are the first advisor's."""
    plan = engine["plan"] or engine["withheld_plan"] or {}
    sid, key = setup_id(s, engine)
    st = s["structure"]
    i15, i1 = s["timeframes"]["15m"]["indicators"] or {}, s["timeframes"]["1h"]["indicators"] or {}
    status = engine["status"]
    forced = (os.getenv("ADVISOR_DATA_ORIGIN") or "").upper()
    structural_tp = plan.get("take_profit_reference") if plan.get("take_profit_source") == "STRUCTURAL_RESISTANCE" else None
    return {
        "engine": "v2", "symbol": s["symbol"], "pair": s["pair"], "setup_id": sid, "setup_key": key,
        "setup_class": CLASS_OF.get(status, status), "underlying_setup": engine.get("underlying_status"),
        "blocked_reason": engine["blocks"][0]["code"] if status == "BLOCKED_SETUP" else None,
        "close_ms": s["market_timestamp_ms"], "timestamp": s["market_timestamp"],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "market_timestamp": s["market_timestamp"], "market_timestamp_ms": s["market_timestamp_ms"],
        "data_origin": origin if origin in d.ORIGINS else forced if forced in d.ORIGINS else "LIVE" if s.get("live") else "REPLAY",
        "source": source, "advisor_version": cfg.ADVISOR_VERSION, "ruleset_hash": ruleset_hash(), **d.code_version(),
        "snapshot_hash": s.get("snapshot_hash"),
        "decision": status, "entry_type": None if engine["setup"] == "NONE" else engine["setup"], "group": engine["group"],
        "actionable": bool(engine["actionable"]), "breakout_status": st["breakout_status"],
        "price": s["last_closed_15m"], "live_price": s["current_price"],
        "trend_1h": st["trend_1h"], "trend_4h": st["trend_4h"],
        "level": st.get("broken_resistance") or st.get("control_level"),
        "plan_type": plan.get("type"), "plan_kind": plan.get("kind"), "entry": plan.get("trigger"),
        "trigger": plan.get("trigger"), "limit": plan.get("limit"), "stop": plan.get("technical_stop"),
        "invalidation": plan.get("technical_invalidation"), "resistance_1": structural_tp,
        "risk_per_unit": plan.get("risk_per_unit"), "retest_zone": plan.get("retest_zone"),
        "retest_confirmation_price": plan.get("confirmation_price"), "pullback_zone": None,
        "take_profit": plan.get("take_profit_reference"), "take_profit_source": plan.get("take_profit_source"),
        "stop_source": plan.get("stop_source"), "stop_distance_atr15": plan.get("stop_distance_atr15"),
        "atr_15m": i15.get("atr14"), "atr_1h": i1.get("atr14"), "volume_ratio": i15.get("volume_ratio"),
        "rsi_1h": i1.get("rsi14"), "rsi_15m": i15.get("rsi14"),
        "btc_regime": {k: s["btc"].get(k) for k in ("trend_15m", "trend_1h", "trend_4h", "regime")},
        "macro_status": (s.get("macro") or {}).get("macro_status"),
        "warnings": [w["code"] for w in engine["warnings"]], "blocks": [b["code"] for b in engine["blocks"]],
        "waits": [w["code"] for w in engine["waits"]],
        "consensus": None if not consensus else consensus["consensus"], "plan_released": bool(consensus and consensus["plan_released"]),
        "verdicts": None if not consensus else {k: consensus[f"{k}_verdict"] for k in ("technical", "risk", "regime")},
        "reason_code": (engine["blocks"] + engine["waits"])[0]["code"] if (engine["blocks"] or engine["waits"]) else None,
        "outcome_due_ms": {h: s["market_timestamp_ms"] + ms for h, ms in d.PAPER_HORIZONS.items()},
        "outcome": {}, "outcome_done": []}


def log_runs(rows: list[dict]) -> int:
    """Store the records (the store skips duplicates). A failure here never breaks a run."""
    try:
        import danisman_paper
        return danisman_paper.log(rows)
    except Exception as e:
        log.warning("Advisor V2 paper log failed: %s", e)
        return 0


# ---------------- simulation ----------------
def _atr(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    prev = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    return pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().values


def _whipsaw(w: pd.DataFrame, e: int, stopped: float, invalidation: float | None, atr15: np.ndarray, atr1h_at) -> dict:
    """The facts of one stop: w is the 15m window, e the candle that touched the stop."""
    t, h, c = w.t.values, w.h.values, w.c.values
    after = slice(e + 1, e + 1 + cfg.WHIPSAW_BARS)
    back = next((j for j in range(e + 1, min(e + 1 + cfg.WHIPSAW_BARS, len(w))) if c[j] > stopped), None)
    upto = e + 1 + cfg.WHIPSAW_BARS if back is None else back + 1
    broken = bool(invalidation is not None and (c[e:upto] < invalidation).any())
    complete = len(w) >= e + 1 + cfg.WHIPSAW_BARS
    return {"stop_timestamp": d._iso(int(t[e]) + M15), "stop_price": float(stopped),
            "ATR15_at_stop": float(atr15[e]), "ATR1h_at_stop": atr1h_at(int(t[e])),
            "time_to_reclaim": None if back is None else int((back - e) * 15),
            "max_price_1h_after_stop": float(h[after].max()) if len(h[after]) else None,
            "max_price_4h_after_stop": float(h[e + 1:e + 17].max()) if len(h[e + 1:e + 17]) else None,
            "technical_invalidation_broken": broken,
            # undecided until the candles after the stop have closed
            "whipsaw_exit": (bool(back is not None and not broken) if complete or back is not None else None)}


def simulate(row: dict, bars: pd.DataFrame) -> dict:
    """The record's plan under the four exit styles. bars: 15m candles (t, o, h, l, c) from WARMUP_MS before the
    record's close to the end of the research horizon. Only candles after the record's close can fill or end a trade."""
    import danisman_paper as dp
    bars = bars.sort_values("t").reset_index(drop=True)
    atr_all = _atr(bars.h.values, bars.l.values, bars.c.values)
    hours = bars.groupby(bars.t // H1 * H1).agg(h=("h", "max"), l=("l", "min"), c=("c", "last"))
    atr_h = pd.Series(_atr(hours.h.values, hours.l.values, hours.c.values), index=hours.index)

    def atr1h_at(ms: int):
        done = atr_h[atr_h.index + H1 <= ms]         # the last 1h candle that had closed by then
        return float(done.iloc[-1]) if len(done) else None

    first = int(np.searchsorted(bars.t.values, row["close_ms"]))
    w = bars.iloc[first:].reset_index(drop=True)
    atr15 = atr_all[first:]
    if not len(w) or not row.get("plan_type") or row.get("stop") is None:
        return {"triggered": None}
    base, start = dp.plan_outcome(row, w)
    if not base["triggered"] or start is None or start >= len(w):
        return {"triggered": bool(base["triggered"]), "fill_price": base["fill_price"]}
    fill, stop0 = float(base["fill_price"]), float(row["stop"])
    risk = fill - stop0
    if risk <= 0:
        return {"triggered": True, "fill_price": fill, "error": "stop girişin üstünde"}
    t, h, l, c = w.t.values, w.h.values, w.l.values, w.c.values
    a15, a1 = row.get("atr_15m") or float(atr15[start]), row.get("atr_1h") or atr1h_at(int(t[start])) or 0.0
    inval = row.get("invalidation")

    def run(target: float | None, trail: str | None) -> dict:
        stop, hi, lo, last_low, top = stop0, fill, fill, stop0, fill
        for i in range(start, len(w)):
            lo = min(lo, l[i])
            if l[i] <= stop:                                    # the stop first, whatever else the candle holds
                why = "STOP" if stop == stop0 else "TRAIL"
                return {"result_r": round((stop - fill) / risk, 2), "exit": why, "exit_candle": i, "stop_at_exit": float(stop),
                        "bars_held": i - start + 1, "mfe_r": round((hi - fill) / risk, 2), "mae_r": round((lo - fill) / risk, 2)}
            hi = max(hi, h[i])
            if target is not None and h[i] >= target:
                return {"result_r": round((target - fill) / risk, 2), "exit": "TP", "exit_candle": i, "stop_at_exit": float(stop),
                        "bars_held": i - start + 1, "mfe_r": round((hi - fill) / risk, 2), "mae_r": round((lo - fill) / risk, 2)}
            if trail == "ATR":                                  # from the next candle on
                top = max(top, h[i])
                stop = max(stop, top - cfg.TRAIL_REFERENCE_ATR1H * a1)
            elif trail == "HIGHER_LOW":
                j = i - SWING_K                                 # a swing low is known SWING_K candles after it formed
                if j - SWING_K >= start and l[j] == l[j - SWING_K:j + SWING_K + 1].min() and l[j] > last_low:
                    last_low = l[j]
                    stop = max(stop, l[j] - cfg.HIGHER_LOW_ATR15_BUFFER * a15)
        return {"result_r": round(float((c[-1] - fill) / risk), 2), "exit": "OPEN_AT_HORIZON", "exit_candle": None,
                "stop_at_exit": float(stop), "bars_held": len(w) - start, "mfe_r": round((hi - fill) / risk, 2),
                "mae_r": round((lo - fill) / risk, 2)}

    structural = row.get("take_profit") if row.get("take_profit_source") == "STRUCTURAL_RESISTANCE" else None
    runs = {"A": run(structural, None) if structural else None, "B": run(fill + cfg.FALLBACK_TP_R * risk, None),
            "C": run(None, "ATR"), "D": run(None, "HIGHER_LOW")}
    for v in runs.values():
        if v and v["exit"] in ("STOP", "TRAIL"):
            v["whipsaw"] = _whipsaw(w, v["exit_candle"], v["stop_at_exit"], inval if v["exit"] == "STOP" else None, atr15, atr1h_at)
            v["whipsaw"].update(initial_entry=fill, R_at_stop=v["result_r"])
        if v:
            v["left_on_table_r"] = round(v["mfe_r"] - v["result_r"], 2)
            v["hold_hours"] = round(v["bars_held"] * 0.25, 2)
            v["exit_ms"] = None if v["exit_candle"] is None else int(t[v["exit_candle"]]) + M15
    return {"triggered": True, "fill_price": fill, "fill_ms": int(t[start]), "initial_stop": stop0, "risk_per_unit": risk,
            "stop_distance_atr15": round(risk / a15, 2) if a15 else None, "stop_source": row.get("stop_source"),
            "virtual": row.get("setup_class") == "BLOCKED_SETUP" or not row.get("actionable"), "variants": runs}


async def update_outcomes(store=None, now_ms: int | None = None, candles=None) -> dict:
    """Fill outcome["v2"] for V2 records whose research horizon has passed. candles: async (pair, start_ms, end_ms) ->
    15m frame, instead of the network. Only the "outcome" of a record is written, as the first tracker does."""
    import danisman_paper as dp
    import httpx
    st = store or dp.store()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    horizon = cfg.RESEARCH_HORIZON_HOURS * H1
    rows = [r for r in st.all() if r.get("engine") == "v2" and r.get("plan_type") and r.get("stop") is not None
            and r.get("data_origin") in dp.TRACKED and "v2" not in (r.get("outcome") or {}) and now >= r["close_ms"] + horizon + M15]
    by_pair: dict[str, list[dict]] = {}
    for r in rows:
        by_pair.setdefault(r["pair"], []).append(r)
    done, client = 0, None
    try:
        if by_pair and candles is None:
            client = httpx.AsyncClient()

            async def candles(pair, start, end):
                return await dp._klines(client, pair, "15m", start, end, M15)
        for pair, group in by_pair.items():
            for r in group:
                try:
                    bars = await candles(pair, r["close_ms"] - WARMUP_MS, r["close_ms"] + horizon)
                    bars = bars[bars.t + M15 <= now]
                    if not len(bars):
                        continue
                    st.update(dp.key(r), {**(r.get("outcome") or {}), "v2": simulate(r, bars)}, r.get("outcome_done") or [])
                    done += 1
                except Exception as e:
                    log.warning("Advisor V2 research: %s failed: %s", pair, e)
    finally:
        if client is not None:
            await client.aclose()
        st.flush()
    return {"pending": len(rows), "updated": done}


# ---------------- statistics ----------------
def _metrics(trades: list[dict]) -> dict:
    """trades: one exit style's finished paper trades, each {"result_r", "exit", "mfe_r", "mae_r", ...}, in time order."""
    n = len(trades)
    if not n:
        return {"sample_size": 0, "verdict": "INCONCLUSIVE"}
    rs = [x["result_r"] for x in trades]
    wins, losses = [r for r in rs if r > 0], [r for r in rs if r <= 0]
    equity = np.concatenate([[0.0], np.cumsum(rs)])      # in R, from a flat start
    stops = [x for x in trades if x["exit"] in ("STOP", "TRAIL")]
    judged = [x["whipsaw"]["whipsaw_exit"] for x in stops if x.get("whipsaw") and x["whipsaw"]["whipsaw_exit"] is not None]
    mean = lambda xs: round(statistics.fmean(xs), 2) if xs else None
    return {"sample_size": n, "verdict": "MEASURED" if n >= cfg.MIN_SAMPLE else "INCONCLUSIVE",
            "expectancy_R": mean(rs), "win_rate": round(len(wins) / n * 100, 1), "avg_win_R": mean(wins), "avg_loss_R": mean(losses),
            "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
            "max_drawdown_R": round(float((np.maximum.accumulate(equity) - equity).max()), 2),
            "stop_rate": round(len(stops) / n * 100, 1), "TP_rate": round(sum(x["exit"] == "TP" for x in trades) / n * 100, 1),
            "whipsaw_rate": round(sum(judged) / len(judged) * 100, 1) if judged else None, "whipsaw_sample": len(judged),
            "MFE": mean([x["mfe_r"] for x in trades]), "MAE": mean([x["mae_r"] for x in trades]),
            "MFE_left_on_table": mean([x["left_on_table_r"] for x in trades]),
            "avg_holding_time_hours": mean([x["hold_hours"] for x in trades])}


def stats(rows: list[dict], origin: str = "LIVE", only_ruleset: str | None = None, include_virtual: bool = False) -> dict:
    """The exit-style comparison and the whipsaw report. A setup seen on several runs counts once (its first record).
    origin: LIVE (default), REPLAY, TEST or ALL. only_ruleset: one ruleset hash (None = every V2 version).
    include_virtual: also count plans that were never offered (blocked, reclaim watch)."""
    origin = origin.upper()
    v2 = [r for r in rows if r.get("engine") == "v2"]
    kept = [r for r in v2 if (origin == "ALL" or r.get("data_origin") == origin) and (only_ruleset is None or r.get("ruleset_hash") == only_ruleset)]
    first: dict[str, dict] = {}
    for r in sorted(kept, key=lambda x: x["close_ms"]):
        first.setdefault(r["setup_id"], r)
    sims = [(r, r["outcome"]["v2"]) for r in first.values() if (r.get("outcome") or {}).get("v2")]
    entered = [(r, o) for r, o in sims if o.get("variants") and (include_virtual or not o.get("virtual"))]
    out = {"origin": origin, "ruleset_hash": only_ruleset, "records": len(kept), "setups": len(first),
           "excluded": len(v2) - len(kept), "simulated": len(sims), "entered": len(entered), "min_sample": cfg.MIN_SAMPLE,
           "by_status": {}, "variants": {}, "whipsaw": {}}
    for r in first.values():
        out["by_status"][r["decision"]] = out["by_status"].get(r["decision"], 0) + 1
    for name, label in VARIANTS.items():
        trades = [o["variants"][name] for _, o in entered if o["variants"].get(name)]
        out["variants"][name] = {"label": label, **_metrics(trades)}
    # whipsaw: by how far the first stop sat from the entry, and by what the stop rested on (style B: no trailing)
    stopped = [(o["stop_distance_atr15"], o.get("stop_source"), o["variants"]["B"]["whipsaw"]["whipsaw_exit"])
               for _, o in entered if o["variants"]["B"]["exit"] == "STOP" and o["variants"]["B"]["whipsaw"]["whipsaw_exit"] is not None]
    rate = lambda xs: {"stops": len(xs), "whipsaw_rate": round(sum(xs) / len(xs) * 100, 1) if xs else None,
                       "verdict": "MEASURED" if len(xs) >= cfg.MIN_SAMPLE else "INCONCLUSIVE"}
    out["whipsaw"] = {
        "all": rate([w for _, _, w in stopped]),
        "by_stop_distance_atr15": {
            f"{lo:g}-{hi:g}" if hi < 99 else f"{lo:g}+": rate([w for dist, _, w in stopped if dist is not None and lo <= dist < hi])
            for lo, hi in BUCKETS},
        "by_stop_source": {src: rate([w for _, s, w in stopped if (s or "?") == src]) for src in sorted({s or "?" for _, s, _ in stopped})},
        "note": "MIN_STOP_ATR15 yeterli örnek olmadan değiştirilmez; bu tablo yalnız gözlemdir."}
    return out

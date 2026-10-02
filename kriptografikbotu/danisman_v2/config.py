"""Kripto Danışman V2: every threshold, limit and cache time, in one place.

Each value can be overridden with an environment variable named ADVISOR_<NAME> (e.g. ADVISOR_MIN_STOP_ATR15=1.75).
Nothing here was fitted to history. The values come from the V2 brief and from the first advisor (danisman.py);
where the research has something to say about a value it is written next to it. Changing a value in RULES changes
the ruleset hash, so the paper log keeps the records of each setting apart.

Units: *_PCT values are percentages (0.35 means 0.35 %), *_ATR15 / *_ATR1H are multiples of that timeframe's ATR14.
"""
from __future__ import annotations

import hashlib
import json
import os

ADVISOR_VERSION = "2.0.0"
RULESET_REVISION = 2             # raise it when the decision CODE changes in a way the values below cannot show


def _env(name: str, default):
    raw = os.getenv(f"ADVISOR_{name}")
    if raw is None or raw.strip() == "":
        return default
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, tuple):
        return tuple(x.strip() for x in raw.split(",") if x.strip())
    return type(default)(raw)


# ---------------- data ----------------
MAX_DATA_AGE_SECONDS = _env("MAX_DATA_AGE_SECONDS", 1800)    # last closed 15m candle older than this: DATA_STALE, no plan
AI_CANDLES_15M = _env("AI_CANDLES_15M", 32)                  # closed candles per timeframe shown to the AI analysts
AI_CANDLES_1H = _env("AI_CANDLES_1H", 24)
AI_CANDLES_4H = _env("AI_CANDLES_4H", 18)
AI_CANDLES_1D = _env("AI_CANDLES_1D", 14)

# ---------------- support / resistance ----------------
ZONE_CLUSTER_ATR1H = _env("ZONE_CLUSTER_ATR1H", 0.25)        # confirmed swings closer than this are one zone
ZONES_KEPT = _env("ZONES_KEPT", 5)                           # zones kept on each side of the price, nearest first

# ---------------- breakout stop-limit ----------------
# Trigger = top of the resistance + one tick. Research (daily bars): bigger breakout buffers only made results worse.
EXECUTION_MIN_TICKS = _env("EXECUTION_MIN_TICKS", 2)         # the limit sits at least this many ticks above the trigger
EXECUTION_ATR15_BUFFER = _env("EXECUTION_ATR15_BUFFER", 0.10)
MAX_EXECUTION_BUFFER_PCT = _env("MAX_EXECUTION_BUFFER_PCT", 0.25)   # ...and never more than this share of the trigger
NO_CHASE_ATR15 = _env("NO_CHASE_ATR15", 0.50)                # price this far above the trigger: no order, wait for a retest
PLAN_RANGE_ATR1H = _env("PLAN_RANGE_ATR1H", 3.0)             # a resistance farther away than this is not planned for yet

# ---------------- retest / reclaim ----------------
RETEST_ZONE_ATR1H = _env("RETEST_ZONE_ATR1H", 0.25)          # the retest zone reaches this far above the broken level
RETEST_CONFIRM_MAX_BARS = _env("RETEST_CONFIRM_MAX_BARS", 4)  # a confirming 15m candle older than this is not an entry
RECLAIM_HOLD_BARS = _env("RECLAIM_HOLD_BARS", 2)             # closed 15m candles that must hold the level after a reclaim

# ---------------- initial stop ----------------
STRUCTURAL_STOP_ATR1H_BUFFER = _env("STRUCTURAL_STOP_ATR1H_BUFFER", 0.15)   # stop = support low minus this
# A stop nearer than this sits inside normal movement. NOT a tested number: the whipsaws seen on BNB/BTC/ETH are a
# hypothesis; research.py compares 1.25 / 1.50 / 1.75 / 2.00 on paper before anyone changes it.
MIN_STOP_ATR15 = _env("MIN_STOP_ATR15", 1.50)
MAX_STOP_DISTANCE_PCT = _env("MAX_STOP_DISTANCE_PCT", 12.0)  # a technical stop farther than this: no order (as in V1)

# ---------------- take profit ----------------
MIN_TP_ATR1H = _env("MIN_TP_ATR1H", 0.75)                    # a resistance nearer than this is noise, not a target
FALLBACK_TP_R = _env("FALLBACK_TP_R", 2.5)                   # no resistance above: this many R (a research fallback)
TRAIL_REFERENCE_ATR1H = _env("TRAIL_REFERENCE_ATR1H", 3.0)   # best trailing stop on DAILY bars; a reference only here

# ---------------- position size ----------------
RISK_PER_TRADE_PCT = _env("RISK_PER_TRADE_PCT", 0.35)        # of the portfolio, lost if the stop is hit
MAX_NEW_POSITION_PCT = _env("MAX_NEW_POSITION_PCT", 3.0)     # one new position, of the portfolio
# The four exposure limits below are CONFIGURED_POLICY: placeholders the admin sets to their own taste. They come
# from no test and are never shown as a research result.
MAX_TOTAL_CRYPTO_EXPOSURE_PCT = _env("MAX_TOTAL_CRYPTO_EXPOSURE_PCT", 60.0)   # only checked when every market is known
MAX_ALT_EXPOSURE_PCT = _env("MAX_ALT_EXPOSURE_PCT", 30.0)
MAX_MEME_EXPOSURE_PCT = _env("MAX_MEME_EXPOSURE_PCT", 5.0)
MAX_CORRELATED_EXPOSURE_PCT = _env("MAX_CORRELATED_EXPOSURE_PCT", 25.0)       # holdings that move with the coin
EXPOSURE_WARN_SHARE = _env("EXPOSURE_WARN_SHARE", 0.8)       # warn from this share of a limit on
HIGH_CORRELATION = _env("HIGH_CORRELATION", 0.75)            # 1h-return correlation at or above this: "moves together"
MANY_POSITIONS_WARN = _env("MANY_POSITIONS_WARN", 10)        # a warning only; limits are by exposure, not by count
FEE_PCT = _env("FEE_PCT", 0.10)                              # per side, for the break-even level

# ---------------- managing an open position ----------------
BREAKEVEN_R = _env("BREAKEVEN_R", 1.0)                       # before this the initial structural stop stays
PROFIT_LOCK_R = _env("PROFIT_LOCK_R", 2.0)                   # from here a higher low / 1h support may carry the stop
HIGHER_LOW_ATR15_BUFFER = _env("HIGHER_LOW_ATR15_BUFFER", 0.25)
# R unit when the first stop was never recorded. R measured with it is ESTIMATED_R and is shown as an estimate.
INITIAL_RISK_FALLBACK_ATR1H = _env("INITIAL_RISK_FALLBACK_ATR1H", 1.5)
# A position counts as the fill of the last released V2 plan (and takes that plan's stop as its first stop) when its
# entry lies between the plan's trigger and limit, give or take this share.
PLAN_ENTRY_MATCH_PCT = _env("PLAN_ENTRY_MATCH_PCT", 0.5)
REJECTION_WICK_RATIO = _env("REJECTION_WICK_RATIO", 0.5)     # upper wick share of a candle that touched a resistance
SUPPORT_LOST_BARS = _env("SUPPORT_LOST_BARS", 3)             # closed 1h candles in which a support break counts as fresh
MAJOR_SUPPORT_MIN_TOUCHES = _env("MAJOR_SUPPORT_MIN_TOUCHES", 2)   # a support with fewer reactions is not "major"

# ---------------- macro (OpenBB) ----------------
MACRO_CAUTION_MINUTES = _env("MACRO_CAUTION_MINUTES", 60)    # a high-impact event this close: caution on new entries
MACRO_BLOCK_MINUTES = _env("MACRO_BLOCK_MINUTES", 15)        # ...this close: no new entry (0 = never block)
# No free calendar provider says how important an event is. The advisor does not guess: an event is "high impact" only
# when its name contains one of these words (comma separated in ADVISOR_MACRO_HIGH_IMPACT_KEYWORDS). Empty = unknown.
MACRO_HIGH_IMPACT_KEYWORDS = _env("MACRO_HIGH_IMPACT_KEYWORDS", ())
MACRO_COUNTRIES = _env("MACRO_COUNTRIES", ("United States", "US"))
CALENDAR_CACHE_SECONDS = _env("CALENDAR_CACHE_SECONDS", 900)
MACRO_CACHE_SECONDS = _env("MACRO_CACHE_SECONDS", 1800)
CROSS_ASSET_CACHE_SECONDS = _env("CROSS_ASSET_CACHE_SECONDS", 300)
OPENBB_TIMEOUT_SECONDS = _env("OPENBB_TIMEOUT_SECONDS", 150)   # one OpenBB read (it goes on in the background and fills the cache)
MACRO_WAIT_SECONDS = _env("MACRO_WAIT_SECONDS", 40)          # a coin analysis waits this long for macro, then goes on DEGRADED

# ---------------- AI analysts ----------------
AI_TIMEOUT_SECONDS = _env("AI_TIMEOUT_SECONDS", 60)          # one attempt of one analyst
# Hard limit for the three analysts together (they run in parallel). An analyst that has not answered by then is
# FAILED / TIMEOUT_TOTAL, which makes the consensus DEGRADED: no buy plan. Measured: 11-43 s per analyst.
AI_TOTAL_TIMEOUT_SECONDS = _env("AI_TOTAL_TIMEOUT_SECONDS", 100)
AI_MAX_RETRIES = _env("AI_MAX_RETRIES", 1)                   # one retry after a timeout or an answer that is not valid JSON
AI_MAX_TOKENS = _env("AI_MAX_TOKENS", 6000)

# ---------------- paper research ----------------
WHIPSAW_BARS = _env("WHIPSAW_BARS", 4)                       # closed 15m candles after a stop in which a reclaim is a whipsaw
RESEARCH_HORIZON_HOURS = _env("RESEARCH_HORIZON_HOURS", 72)  # a paper trade still open after this is closed at the price
MIN_SAMPLE = _env("MIN_SAMPLE", 30)                          # fewer finished paper trades than this: INCONCLUSIVE
STOP_VARIANTS_ATR15 = (1.25, 1.50, 1.75, 2.00)               # compared on paper only

# Everything that can change a decision, a level or a position size. Texts, cache times and AI settings are not rules.
RULES = ("RULESET_REVISION", "MAX_DATA_AGE_SECONDS", "ZONE_CLUSTER_ATR1H", "ZONES_KEPT", "EXECUTION_MIN_TICKS",
         "EXECUTION_ATR15_BUFFER", "MAX_EXECUTION_BUFFER_PCT", "NO_CHASE_ATR15", "PLAN_RANGE_ATR1H", "RETEST_ZONE_ATR1H",
         "RETEST_CONFIRM_MAX_BARS", "RECLAIM_HOLD_BARS", "STRUCTURAL_STOP_ATR1H_BUFFER", "MIN_STOP_ATR15",
         "MAX_STOP_DISTANCE_PCT", "MIN_TP_ATR1H", "FALLBACK_TP_R", "TRAIL_REFERENCE_ATR1H", "RISK_PER_TRADE_PCT",
         "MAX_NEW_POSITION_PCT", "MAX_TOTAL_CRYPTO_EXPOSURE_PCT", "MAX_ALT_EXPOSURE_PCT", "MAX_MEME_EXPOSURE_PCT",
         "MAX_CORRELATED_EXPOSURE_PCT", "EXPOSURE_WARN_SHARE", "HIGH_CORRELATION", "MANY_POSITIONS_WARN", "FEE_PCT",
         "BREAKEVEN_R", "PROFIT_LOCK_R", "HIGHER_LOW_ATR15_BUFFER", "INITIAL_RISK_FALLBACK_ATR1H", "PLAN_ENTRY_MATCH_PCT",
         "REJECTION_WICK_RATIO",
         "SUPPORT_LOST_BARS", "MAJOR_SUPPORT_MIN_TOUCHES", "MACRO_CAUTION_MINUTES", "MACRO_BLOCK_MINUTES", "MACRO_HIGH_IMPACT_KEYWORDS")


def ruleset(base: dict | None = None) -> dict:
    """The V2 rules. base: the first advisor's ruleset (its swing, trend and breakout-state code is reused, so a
    change there is a change here)."""
    return {"v2": {k: globals()[k] for k in RULES}, "v1_primitives": base or {}}


def ruleset_hash(base: dict | None = None) -> str:
    text = json.dumps(ruleset(base), sort_keys=True, separators=(",", ":"), default=list)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


POLICY_LIMITS = ("MAX_TOTAL_CRYPTO_EXPOSURE_PCT", "MAX_ALT_EXPOSURE_PCT", "MAX_MEME_EXPOSURE_PCT", "MAX_CORRELATED_EXPOSURE_PCT")
TIMEOUTS = ("AI_TIMEOUT_SECONDS", "AI_MAX_RETRIES", "AI_TOTAL_TIMEOUT_SECONDS", "MACRO_WAIT_SECONDS", "OPENBB_TIMEOUT_SECONDS")


def policy() -> dict:
    """The exposure limits with what they are: the admin's configured policy, not something a test produced."""
    return {"basis": "CONFIGURED_POLICY", "limits": {k: globals()[k] for k in POLICY_LIMITS},
            "note": "Yapılandırılmış politika: yöneticinin tercihi. Araştırma ya da geçmiş test sonucu değildir."}


def timeouts() -> dict:
    return {k: globals()[k] for k in TIMEOUTS}


def public() -> dict:
    """The thresholds for the admin panel (no secrets live in this file)."""
    return {k: globals()[k] for k in RULES if k != "RULESET_REVISION"}

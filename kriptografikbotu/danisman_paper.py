"""Paper log of the Kripto Danışman: what it said, and what the market did afterwards. Research only.

    log()              store the records of a /danis or /firsat run (danisman.paper_row), never twice
    update_outcomes()  for records old enough, fill in the outcome from the 15m candles that followed
    stats()            count the outcomes per setup class (7 days, 30 days, everything)

Storage: the bot's MongoDB (collection advisor_paper, in the database of STATE_MONGO_URL) when it runs in the cloud,
so a deploy does not wipe it and the daily database backup includes it; a JSONL file on this PC. One record per
symbol + setup_id + 15m close + ruleset_hash + data_origin (unique index): the same setup at the same close is never
written twice, a NO_SETUP / AVOID coin is written once per candle (the comparison group), and the same market setup
judged by a newer ruleset, or replayed later, is a record of its own.

Provenance: data_origin is LIVE (a real run), REPLAY (a past moment computed again) or TEST. Statistics never mix
them silently: LIVE and the current ruleset_hash are the default, anything else has to be asked for and is named in
the header. Records written before this existed are kept and marked REPLAY / ruleset "legacy". The outcome tracker
fills LIVE and REPLAY records, never TEST ones, and never touches data_origin.

Rules of this file:
- the outcome uses candles AFTER the record's close; the record's own fields are never rewritten, only "outcome";
- nothing in danisman.py reads this data: no threshold, parameter or decision changes because of it;
- it never sends an order.

Outcome fields (in record["outcome"]), each horizon only once it has fully passed:
  outcome_1h / _4h / _24h                       return from the record's price to the close at the horizon, %
  max_favorable_excursion_* / max_adverse_*     highest high / lowest low inside the horizon, % of the price
  triggered, fill_price, trigger_time           did the plan's entry happen within 24 h (stop-limit: the trigger was
                                                touched and the limit could fill; retest: a 15m candle reached the
                                                zone and closed above the level; a ready setup: at the record's price)
  mfe_r, mae_r, stopped, reached_1R, reached_2R, reached_next_resistance
                                                after the fill, in units of the plan's risk; a candle that touches the
                                                stop ends the trade first (the bar does not say which came first)
  broke_invalidation                            a 15m close under the invalidation level
  result_r_conservative / _optimistic / _resolved
                                                the paper trade ends at the stop (-1R) or at the first target (+1R),
                                                whichever comes first; neither within 24 h: the 24 h close, in R.
                                                A 15m candle that holds both is intrabar_ambiguous, and so is a
                                                stop-limit's entry candle whose low is under the stop (that low may
                                                be from before the fill): conservative counts the stop, optimistic
                                                does not, and the 1m candles of that quarter hour decide `resolved`
                                                when they can (intrabar_resolution)
  breakout only: broke_resistance, closed_above_resistance, fell_back_below_resistance, time_to_failure (minutes),
            max_gain_before_failure (%); immediate_false_breakout (entered, and one of the first 4 closed candles
            closed back under the resistance before 1R was seen), late_breakout_failure (it reached 1R or held
            4 candles first, and fell back under the resistance later)
  retest:   entered_retest_zone, confirmed_retest
  BLOCKED_SETUP (a setup an outside filter held back): nothing was entered, so triggered / fill_price stay empty;
            would_trigger, would_hit_1R, would_hit_2R, virtual_mfe_r, virtual_mae_r, virtual_result_r say what
            the plan would have done, for comparison only
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import statistics
import time
from datetime import datetime, timezone

import httpx
import pandas as pd

logger = logging.getLogger(__name__)
HERE = pathlib.Path(__file__).resolve().parent
COLLECTION = "advisor_paper"
HORIZONS = {"1h": 3_600_000, "4h": 14_400_000, "24h": 86_400_000}
M15 = 900_000
DAY = 86_400_000
GIVE_UP_MS = 2 * DAY            # no candles this long after a horizon (pair delisted): the horizon is closed empty
BASES = ("https://data-api.binance.vision", "https://api.binance.com")
CLASSES = ("READY_TO_WATCH", "WAIT_FOR_BREAKOUT", "WAIT_FOR_RETEST", "PULLBACK_SETUP", "BLOCKED_SETUP", "NO_SETUP", "AVOID")
CLASS_TR = {"READY_TO_WATCH": "İzlemeye hazır", "WAIT_FOR_BREAKOUT": "Kırılım bekleniyor",
            "WAIT_FOR_RETEST": "Geri test bekleniyor", "PULLBACK_SETUP": "Düzeltme kurulumu",
            "BLOCKED_SETUP": "Engelli kurulum", "NO_SETUP": "Kurulum yok", "AVOID": "Uzak dur"}
BLOCK_REASONS = {"BTC_MARKET_RISK": "BTC riski nedeniyle", "HTF_DOWNTREND": "4H düşüş nedeniyle",
                 "PORTFOLIO_CONCENTRATION": "Portföy yoğunluğu nedeniyle", "INSUFFICIENT_HISTORY": "Yetersiz geçmiş nedeniyle",
                 "OTHER": "Diğer"}
TARGET_R = 1.0                  # the paper trade's first target, in units of its risk
FAST_FAIL_BARS = 4              # a breakout that closes back under the resistance within this many candles failed at once
M1 = 60_000
NOT_AMBIGUOUS, RESOLVED_1M = "NOT_AMBIGUOUS", "RESOLVED_1M"
STOP_FIRST, TARGET_FIRST = "STOP_FIRST_CONSERVATIVE", "TARGET_FIRST_OPTIMISTIC"   # the second is never assumed here
PERIODS = {"son 7 gün": 7 * DAY, "son 30 gün": 30 * DAY, "tüm dönem": None}


ORIGINS = ("LIVE", "REPLAY", "TEST")
TRACKED = ("LIVE", "REPLAY")    # what the outcome tracker fills in; TEST records are left alone
LEGACY = "legacy"               # ruleset_hash of records written before the advisor was versioned
ORIGIN_TR = {"LIVE": "Canlı paper veri", "REPLAY": "Replay araştırma verisi", "TEST": "Test verisi",
             "ALL": "Tüm paper kayıtları (canlı + replay + test birlikte)"}
KEY_FIELDS = ("symbol", "setup_id", "close_ms", "ruleset_hash", "data_origin")


def normalize(row: dict) -> dict:
    """Records from before provenance existed: kept, marked REPLAY (they were replays and experiments, and must
    never count as live) under the ruleset "legacy"."""
    if "data_origin" not in row:
        row.update(data_origin="REPLAY", ruleset_hash=row.get("ruleset_hash") or LEGACY,
                   advisor_version=row.get("advisor_version") or "0.0.0", git_commit=row.get("git_commit"),
                   working_tree_dirty=row.get("working_tree_dirty"), generated_at=row.get("logged_at"),
                   market_timestamp=row.get("timestamp"), market_timestamp_ms=row["close_ms"])
    return row


def key(row: dict) -> tuple:
    return tuple(row[k] for k in KEY_FIELDS)


# ---------------- storage ----------------
class JsonlStore:
    """One record per line. Fine for this PC; the cloud uses MongoStore."""

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self._rows: dict[tuple, dict] | None = None
        self._dirty = False

    def _load(self) -> dict:
        if self._rows is None:
            self._rows = {}
            if self.path.exists():
                with self.path.open(encoding="utf-8") as fh:
                    for line in fh:
                        try:
                            row = normalize(json.loads(line))
                            self._rows[key(row)] = row
                        except (ValueError, KeyError):
                            continue
        return self._rows

    def insert(self, rows: list[dict]) -> int:
        have, new = self._load(), []
        for row in rows:
            if key(row) not in have:
                have[key(row)] = row
                new.append(row)
        if new:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in new))
        return len(new)

    def all(self) -> list[dict]:
        return list(self._load().values())

    def pending(self, now_ms: int, origins: tuple = TRACKED) -> list[dict]:
        return [r for r in self._load().values() if r["data_origin"] in origins and _due(r, now_ms)]

    def update(self, row_key: tuple, outcome: dict, done: list[str]) -> None:
        row = self._load()[row_key]
        row["outcome"], row["outcome_done"] = outcome, done
        self._dirty = True

    def flush(self) -> None:
        if self._dirty:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in self._rows.values()), encoding="utf-8")
            tmp.replace(self.path)
            self._dirty = False


class MongoStore:
    """Collection advisor_paper with a unique index on (symbol, setup_id, close_ms)."""

    def __init__(self, collection):
        self.c = collection
        # records from before provenance: mark them (never delete), then replace the old, narrower unique index
        self.c.update_many({"data_origin": {"$exists": False}}, [{"$set": {
            "data_origin": "REPLAY", "ruleset_hash": {"$ifNull": ["$ruleset_hash", LEGACY]},
            "advisor_version": {"$ifNull": ["$advisor_version", "0.0.0"]}, "generated_at": "$logged_at",
            "market_timestamp": "$timestamp", "market_timestamp_ms": "$close_ms"}}])
        if "setup_at_close" in self.c.index_information():
            self.c.drop_index("setup_at_close")
        self.c.create_index([(k, 1) for k in KEY_FIELDS], unique=True, name="setup_at_close_by_ruleset_and_origin")
        self.c.create_index("close_ms")

    @staticmethod
    def _filter(row_key: tuple) -> dict:
        return dict(zip(KEY_FIELDS, row_key))

    def insert(self, rows: list[dict]) -> int:
        from pymongo import UpdateOne
        if not rows:
            return 0
        res = self.c.bulk_write([UpdateOne(self._filter(key(r)), {"$setOnInsert": r}, upsert=True) for r in rows],
                                ordered=False)
        return res.upserted_count

    def all(self) -> list[dict]:
        return list(self.c.find({}, {"_id": 0}))

    def pending(self, now_ms: int, origins: tuple = TRACKED) -> list[dict]:
        rows = self.c.find({"close_ms": {"$lte": now_ms - HORIZONS["1h"]}, "data_origin": {"$in": list(origins)},
                            "$or": [{"outcome_done": {"$ne": "24h"}},
                                    {"outcome.intrabar_ambiguous": True, "outcome.intrabar_checked": {"$ne": True}}]},
                           {"_id": 0})
        return [r for r in rows if _due(r, now_ms)]

    def update(self, row_key: tuple, outcome: dict, done: list[str]) -> None:
        self.c.update_one(self._filter(row_key), {"$set": {"outcome": outcome, "outcome_done": done}})

    def flush(self) -> None:
        pass


_store = None


def store():
    """MongoDB where the bot has one (STATE_MONGO_URL), else the JSONL file. ADVISOR_PAPER_FILE forces a file."""
    global _store
    if _store is None:
        path, url = os.getenv("ADVISOR_PAPER_FILE"), os.getenv("STATE_MONGO_URL", "")
        if not path and url:
            try:
                from pymongo import MongoClient
                db = MongoClient(url, serverSelectionTimeoutMS=15000)[os.getenv("STATE_DB_NAME", "kapanis")]
                _store = MongoStore(db[COLLECTION])
            except Exception as e:      # the log must not disappear because the database is down
                logger.warning("Advisor paper log: MongoDB unavailable (%s), writing to the file instead", e)
        if _store is None:
            _store = JsonlStore(path or HERE / "research" / "advisor_paper.jsonl")
    return _store


def log(rows: list[dict], st=None) -> int:
    """Store new records; returns how many were new."""
    return (st or store()).insert(rows)


# ---------------- outcome ----------------
def _unresolved(row: dict) -> bool:
    oc = row.get("outcome") or {}
    return bool(oc.get("intrabar_ambiguous")) and not oc.get("intrabar_checked")


def _due(row: dict, now_ms: int) -> bool:
    done = row.get("outcome_done") or []
    return any(h not in done and now_ms >= row["close_ms"] + ms for h, ms in HORIZONS.items()) or _unresolved(row)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _pct(a: float, b: float) -> float:
    return round((a / b - 1) * 100, 3)


def _walk(h, l, c, start: int, fill: float, stop: float, target: float, entry_candle: int | None, optimistic: bool):
    """The paper trade from candle `start` on: (result in R, the candle that ended it or None, was that an assumption).

    The stop ends it at -1R, the target at +TARGET_R; with neither, the last close in R. A candle does not say in
    which order it traded, so two cases need an assumption:
    - it holds both the stop and the target;
    - it is the candle inside which a stop-limit order filled, its low is under the stop but it closed above it:
      that low may have come before the fill.
    Conservative: the stop counts in both cases. Optimistic: the target counts in the first, the low is ignored in
    the second."""
    for i in range(start, len(h)):
        touched, reached = l[i] <= stop, h[i] >= target
        if touched:
            before_fill = i == entry_candle and c[i] > stop
            if optimistic and before_fill:
                touched = False
            elif optimistic and reached:
                return TARGET_R, i, True
            else:
                return -1.0, i, bool(reached or before_fill)
        if reached:
            return TARGET_R, i, False
    return round(float((c[-1] - fill) / (fill - stop)), 2), None, False


def plan_outcome(row: dict, w: pd.DataFrame) -> tuple[dict, int | None]:
    """Did the plan's entry happen in the 24 h after the record, and how far did the price go in units of its risk.
    Returns (fields, index of the first candle the trade was exposed to or None)."""
    out = {"triggered": None, "fill_price": None, "trigger_time": None, "mfe_r": None, "mae_r": None, "stopped": None,
           "reached_1R": None, "reached_2R": None, "reached_next_resistance": None, "result_r_conservative": None,
           "result_r_optimistic": None, "result_r_resolved": None, "intrabar_ambiguous": None,
           "intrabar_resolution": None, "intrabar_candle_ms": None, "intrabar_fill_inside": None}
    kind, stop = row.get("plan_type"), row.get("stop")
    if not kind or stop is None:
        return out, None
    t, o, h, l, c = (w[k].values for k in ("t", "o", "h", "l", "c"))
    fill, start, when = None, None, None    # the fill price, the first candle the trade is exposed to, the fill time
    if kind == "STOP_LIMIT":
        trig, lim = row["trigger"], row["limit"]
        hit = next((i for i in range(len(w)) if h[i] >= trig), None)
        if hit is not None:
            if o[hit] <= lim:
                fill, start, when = max(o[hit], trig), hit, int(t[hit])
            else:                       # gapped over the limit: the order rests there and fills if the price returns
                back = next((j for j in range(hit, len(w)) if l[j] <= lim), None)
                if back is not None:
                    fill, start, when = lim, back, int(t[back])
    elif kind == "RETEST_WAIT":
        top, conf = row["retest_zone"][1], row["retest_confirmation_price"]
        hit = next((i for i in range(len(w)) if l[i] <= top and c[i] > conf), None)
        if hit is not None:             # the confirming candle's close is the entry; the trade starts on the next one
            fill, start, when = c[hit], hit + 1, int(t[hit]) + M15
    else:                               # a setup that was ready: entered at the record's price
        fill, start, when = row["price"], 0, row["close_ms"]
    out["triggered"] = fill is not None
    if fill is None:
        return out, None
    out["fill_price"] = float(fill)
    out["trigger_time"] = _iso(when)
    risk = fill - stop
    if risk <= 0:
        return out, start
    target = fill + TARGET_R * risk
    high, low, stopped = fill, fill, False
    for i in range(start, len(w)):      # how far it went before the stop (the stop is assumed to come first)
        low = min(low, l[i])
        if l[i] <= stop:
            stopped = True
            break
        high = max(high, h[i])
    entry_candle = start if kind == "STOP_LIMIT" else None
    cons, at, assumed = _walk(h, l, c, start, fill, stop, target, entry_candle, optimistic=False)
    opt = _walk(h, l, c, start, fill, stop, target, entry_candle, optimistic=True)[0]
    amb = int(t[at]) if assumed else None
    nxt = row.get("resistance_1")
    out.update(mfe_r=round((high - fill) / risk, 2), mae_r=round((low - fill) / risk, 2), stopped=stopped,
               reached_1R=bool(high >= fill + risk), reached_2R=bool(high >= fill + 2 * risk),
               reached_next_resistance=None if nxt is None else bool(high >= nxt),
               result_r_conservative=cons, result_r_optimistic=opt, result_r_resolved=cons if amb is None else None,
               intrabar_ambiguous=amb is not None, intrabar_resolution=NOT_AMBIGUOUS if amb is None else STOP_FIRST,
               intrabar_candle_ms=amb, intrabar_fill_inside=bool(assumed and at == entry_candle))
    return out, start


def resolve_intrabar(row: dict, outcome: dict, minutes: pd.DataFrame | None, bars: pd.DataFrame | None = None) -> dict:
    """Use the 1m candles of an ambiguous quarter hour to see what really came first: result_r_resolved and
    intrabar_resolution = RESOLVED_1M. Unchanged (resolved stays empty) when the 1m candles are missing or one
    minute again holds both. bars: the 15m candles of the record's window, needed when the trade survives the
    ambiguous candle and goes on. The conservative result is never rewritten."""
    out = dict(outcome)
    out["intrabar_checked"] = True
    if not outcome.get("intrabar_ambiguous") or minutes is None or len(minutes) == 0:
        return out
    at, fill, stop = outcome["intrabar_candle_ms"], outcome["fill_price"], row["stop"]
    target = fill + TARGET_R * (fill - stop)
    m = minutes[(minutes.t >= at) & (minutes.t < at + M15)].sort_values("t")
    live = not outcome.get("intrabar_fill_inside")      # the order filled inside this candle: find that minute first
    result = None
    for hi, lo, cl in zip(m.h.values, m.l.values, m.c.values):
        entry_minute = False
        if not live:
            if hi < row["trigger"]:
                continue
            live = entry_minute = True
        touched = lo <= stop and not (entry_minute and cl > stop)   # the entry minute's low may be from before the fill
        if touched and hi >= target:
            return out                                  # still both in one minute: stays conservative
        if touched or hi >= target:
            result = -1.0 if touched else TARGET_R
            break
    if not live:
        return out                                      # the fill is not in the 1m candles
    if result is None:                                  # it survived this candle: the trade goes on from the next one
        if bars is None:
            return out
        w = bars[(bars.t > at) & (bars.t < row["close_ms"] + HORIZONS["24h"])]
        if len(w):
            result, _, assumed = _walk(w.h.values, w.l.values, w.c.values, 0, fill, stop, target, None, optimistic=False)
            if assumed:
                return out                              # a later candle is ambiguous too: not settled here
        else:
            result = round(float((m.c.values[-1] - fill) / (fill - stop)), 2)
    out.update(result_r_resolved=result, intrabar_resolution=RESOLVED_1M)
    return out


def breakout_outcome(row: dict, w: pd.DataFrame, plan: dict, start: int | None) -> dict:
    """Breakout setups only: was the resistance broken, did a candle close above it, did it fail, and how."""
    level = row.get("level")
    if row.get("entry_type") != "BREAKOUT" or level is None:
        return {}
    t, h, c = w.t.values, w.h.values, w.c.values
    already = row.get("decision") == "BUY_SETUP"          # the record itself is the close above the level
    first = -1 if already else next((i for i in range(len(w)) if c[i] > level), None)
    out = {"broke_resistance": bool(already or (h > level).any()), "closed_above_resistance": first is not None,
           "fell_back_below_resistance": None, "time_to_failure": None, "max_gain_before_failure": None,
           "immediate_false_breakout": None, "late_breakout_failure": None}
    if first is not None:
        fail = next((j for j in range(first + 1, len(w)) if c[j] <= level), None)
        since = row["close_ms"] if first < 0 else int(t[first]) + M15
        seg = h[first + 1:(fail + 1 if fail is not None else len(w))]
        out.update(fell_back_below_resistance=fail is not None,
                   time_to_failure=None if fail is None else round((int(t[fail]) + M15 - since) / 60_000),
                   max_gain_before_failure=_pct(float(max(seg.max(), level)), level) if len(seg) else 0.0)
    if plan.get("triggered") and start is not None and plan.get("fill_price") is not None:
        # after the entry: the first close back under the resistance, and whether 1R was seen before it
        fill = plan["fill_price"]
        one_r = fill + (fill - row["stop"])
        fail = next((j for j in range(start, len(w)) if c[j] <= level), None)
        seen = fail is not None and bool((h[start:fail + 1] >= one_r).any())
        fast = fail is not None and fail < start + FAST_FAIL_BARS and not seen
        out.update(immediate_false_breakout=bool(fast), late_breakout_failure=bool(fail is not None and not fast))
    return out


def retest_outcome(row: dict, w: pd.DataFrame, plan: dict) -> dict:
    if row.get("plan_type") != "RETEST_WAIT":
        return {}
    return {"entered_retest_zone": bool((w.l.values <= row["retest_zone"][1]).any()), "confirmed_retest": plan["triggered"]}


def compute_outcome(row: dict, bars: pd.DataFrame, now_ms: int) -> tuple[dict, list[str]]:
    """The record's outcome as far as `now_ms` allows: (outcome, horizons done). bars: 15m candles (t, o, h, l, c).
    Only candles that open at or after the record's close and have themselves closed by now_ms are used."""
    close_ms, p0 = row["close_ms"], row["price"]
    out, done = dict(row.get("outcome") or {}), list(row.get("outcome_done") or [])
    bars = bars[(bars.t >= close_ms) & (bars.t + M15 <= now_ms) & (bars.t < close_ms + HORIZONS["24h"])]
    for name, ms in HORIZONS.items():
        due = close_ms + ms
        if name in done or now_ms < due:
            continue
        w = bars[bars.t < due]
        complete = len(w) and int(w.t.iloc[-1]) + M15 >= due
        if not complete and now_ms < due + GIVE_UP_MS:
            continue                    # the last candles are not there yet: try again later
        if len(w):
            out[f"outcome_{name}"] = _pct(float(w.c.iloc[-1]), p0)
            out[f"max_favorable_excursion_{name}"] = _pct(float(w.h.max()), p0)
            out[f"max_adverse_excursion_{name}"] = _pct(float(w.l.min()), p0)
            if name == "24h":
                plan, start = plan_outcome(row, w)
                inv = row.get("invalidation")
                out["broke_invalidation"] = None if inv is None else bool((w.c.values < inv).any())
                if row.get("setup_class") == "BLOCKED_SETUP":
                    # nothing was entered: only what the held-back plan WOULD have done, under other names
                    out.update(triggered=None, fill_price=None, trigger_time=None, would_trigger=plan["triggered"],
                               would_hit_1R=plan["reached_1R"], would_hit_2R=plan["reached_2R"],
                               virtual_mfe_r=plan["mfe_r"], virtual_mae_r=plan["mae_r"],
                               virtual_result_r=plan["result_r_conservative"])
                else:
                    out.update(plan)
                    out.update(breakout_outcome(row, w, plan, start))
                    out.update(retest_outcome(row, w, plan))
        done.append(name)
    return out, done


async def _klines(client, pair: str, interval: str, start_ms: int, end_ms: int, step: int) -> pd.DataFrame:
    """Candles of [start_ms, end_ms) from Binance (the open one included; compute_outcome drops it)."""
    rows, at = [], start_ms
    while at < end_ms and len(rows) < 5000:
        got = None
        for base in BASES:
            try:
                r = await client.get(f"{base}/api/v3/klines", timeout=20,
                                     params={"symbol": pair, "interval": interval, "startTime": at,
                                             "limit": min(1000, max(1, (end_ms - at) // step))})
            except httpx.HTTPError:
                continue
            if r.status_code == 200:
                got = r.json()
                break
            if r.status_code == 400:    # the pair is gone
                got = []
                break
        if not got:
            break
        rows += got
        at = int(got[-1][0]) + step
        if len(got) < 1000:
            break
    return pd.DataFrame({"t": [int(x[0]) for x in rows], "o": [float(x[1]) for x in rows], "h": [float(x[2]) for x in rows],
                         "l": [float(x[3]) for x in rows], "c": [float(x[4]) for x in rows]})


async def update_outcomes(st=None, now_ms: int | None = None, candles=None, minutes=None, origins: tuple = TRACKED) -> dict:
    """Fill in the outcome horizons that have passed, and look at 1m candles for the quarter hours that hold both
    the stop and the target. candles / minutes: async (pair, start_ms, end_ms) -> frame, instead of the network.
    origins: LIVE and REPLAY records by default; TEST records only when a test asks for them. Only "outcome" and
    "outcome_done" are written: data_origin and every other field of a record stay as they were.
    Returns {"pending": records looked at, "updated": records that changed, "resolved_1m": ambiguities settled}."""
    st = st or store()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    rows = st.pending(now, origins)
    by_pair: dict[str, list[dict]] = {}
    for r in rows:
        by_pair.setdefault(r["pair"], []).append(r)
    updated, resolved, client = 0, 0, None
    try:
        if by_pair and (candles is None or minutes is None):
            client = httpx.AsyncClient()
            if candles is None:
                async def candles(pair, start, end):
                    return await _klines(client, pair, "15m", start, end, M15)
            if minutes is None:
                async def minutes(pair, start, end):
                    return await _klines(client, pair, "1m", start, end, M1)
        for pair, group in by_pair.items():
            try:
                bars = await candles(pair, min(r["close_ms"] for r in group),
                                     min(max(r["close_ms"] for r in group) + HORIZONS["24h"], now))
            except Exception as e:
                logger.warning("Advisor paper outcomes: candles for %s failed: %s", pair, e)
                continue
            for r in group:
                outcome, done = compute_outcome(r, bars, now)
                if outcome.get("intrabar_ambiguous") and not outcome.get("intrabar_checked"):
                    try:
                        at = outcome["intrabar_candle_ms"]
                        window = bars[(bars.t >= r["close_ms"]) & (bars.t + M15 <= now)] if len(bars) else bars
                        outcome = resolve_intrabar(r, outcome, await minutes(pair, at, at + M15), window)
                        resolved += outcome["intrabar_resolution"] == RESOLVED_1M
                    except Exception as e:      # no 1m data now: the conservative result stands, try again later
                        logger.warning("Advisor paper outcomes: 1m candles for %s failed: %s", pair, e)
                if done != (r.get("outcome_done") or []) or outcome != (r.get("outcome") or {}):
                    st.update(key(r), outcome, done)
                    updated += 1
    finally:
        if client is not None:
            await client.aclose()
        st.flush()
    return {"pending": len(rows), "updated": updated, "resolved_1m": resolved}


# ---------------- statistics ----------------
def stats(rows: list[dict], now_ms: int | None = None, origin: str = "LIVE", ruleset_hash: str | None = None) -> dict:
    """Per period: every setup class, the blocked setups by reason (virtual), breakout failures, intrabar ambiguity.
    A setup seen on several scans counts once: its first record is the one measured. The main numbers use the
    conservative result. Reading only: nothing in the advisor changes because of these numbers.

    origin: LIVE (default), REPLAY, TEST or ALL. ruleset_hash: only records judged by that ruleset (the callers pass
    the current one; None = every version). What was left out is counted in the result, never dropped silently."""
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    origin = origin.upper()
    rows = [normalize(dict(r)) for r in rows]
    total = len(rows)
    rows = [r for r in rows if origin == "ALL" or r["data_origin"] == origin]
    other_origins = total - len(rows)
    kept = [r for r in rows if ruleset_hash is None or r.get("ruleset_hash") == ruleset_hash]
    other_versions, rows = len(rows) - len(kept), kept
    first: dict[str, dict] = {}
    for r in sorted(rows, key=lambda x: x["close_ms"]):
        first.setdefault(r["setup_id"], r)
    share = lambda xs: round(sum(xs) / len(xs) * 100, 1) if xs else None
    mean = lambda xs: round(statistics.fmean(xs), 2) if xs else None
    med = lambda xs: round(statistics.median(xs), 2) if xs else None
    have = lambda ocs, k: [o[k] for o in ocs if o.get(k) is not None]
    out = {"origin": origin, "ruleset_hash": ruleset_hash, "records": len(rows), "setups": len(first),
           "excluded_other_origins": other_origins, "excluded_other_versions": other_versions, "periods": {}}
    for label, span in PERIODS.items():
        sel = [r for r in first.values() if span is None or r["close_ms"] >= now - span]
        measured = lambda rs: [r["outcome"] for r in rs if "24h" in (r.get("outcome_done") or [])]
        classes = {}
        for cls in CLASSES:
            rs = [r for r in sel if r.get("setup_class") == cls]
            oc = measured(rs)
            trig = [o for o in oc if o.get("triggered")]
            classes[cls] = {"count": len(rs), "measured": len(oc),
                            "trigger_rate_%": share(have(oc, "triggered")),
                            "hit_1R_%": share(have(trig, "reached_1R")), "hit_2R_%": share(have(trig, "reached_2R")),
                            "mean_mfe_r": mean(have(trig, "mfe_r")), "mean_mae_r": mean(have(trig, "mae_r")),
                            "mean_result_r": mean(have(trig, "result_r_conservative")),
                            "median_24h_return_%": med(have(oc, "outcome_24h"))}
        blocked = {}
        for reason in ["ALL", *BLOCK_REASONS]:
            rs = [r for r in sel if r.get("setup_class") == "BLOCKED_SETUP" and reason in ("ALL", r.get("blocked_reason"))]
            oc = measured(rs)
            would = [o for o in oc if o.get("would_trigger")]
            blocked[reason] = {"count": len(rs), "measured": len(oc), "median_24h_return_%": med(have(oc, "outcome_24h")),
                               "would_trigger_%": share(have(oc, "would_trigger")),
                               "would_hit_1R_%": share(have(would, "would_hit_1R")),
                               "would_hit_2R_%": share(have(would, "would_hit_2R")),
                               "mean_virtual_mfe_r": mean(have(would, "virtual_mfe_r")),
                               "mean_virtual_mae_r": mean(have(would, "virtual_mae_r"))}
        real = [o for o in measured([r for r in sel if r.get("setup_class") != "BLOCKED_SETUP"]) if o.get("triggered")]
        entered = [o for o in real if o.get("immediate_false_breakout") is not None]      # breakout family only
        amb = [o for o in real if o.get("intrabar_ambiguous")]
        cons, opt = have(real, "result_r_conservative"), have(real, "result_r_optimistic")
        out["periods"][label] = {
            "classes": classes, "blocked": blocked,
            "breakout": {"entered": len(entered), "immediate_false_breakout_%": share(have(entered, "immediate_false_breakout")),
                         "late_breakout_failure_%": share(have(entered, "late_breakout_failure"))},
            "intrabar": {"trades": len(real), "ambiguous": len(amb),
                         "ambiguous_%": round(len(amb) / len(real) * 100, 1) if real else None,
                         "resolved_1m": sum(o.get("intrabar_resolution") == RESOLVED_1M for o in amb),
                         "resolved_1m_%": share([o.get("intrabar_resolution") == RESOLVED_1M for o in amb]),
                         "mean_result_r_conservative": mean(cons), "mean_result_r_optimistic": mean(opt),
                         "optimistic_minus_conservative_r": round(mean(opt) - mean(cons), 2) if cons else None,
                         "mean_result_r_resolved": mean(have(real, "result_r_resolved"))}}
    return out


def format_stats(s: dict, update: dict | None = None) -> str:
    v = lambda x, unit="": "—" if x is None else f"{x:g}{unit}"
    lines = [f"📒 {ORIGIN_TR[s['origin']]} — {s['records']} kayıt, {s['setups']} ayrı kurulum",
             "Kural seti: " + (f"{s['ruleset_hash']} (güncel)" if s["ruleset_hash"] else "bütün sürümler birlikte")]
    if s["excluded_other_versions"]:
        lines.append(f"Başka danışman sürümlerinden {s['excluded_other_versions']} kayıt hariç tutuldu.")
    if s["excluded_other_origins"]:
        lines.append(f"Bu rapora girmeyen başka kaynaklı kayıt: {s['excluded_other_origins']} "
                     "(/danis stats replay · /danis stats all).")
    if update:
        lines.append(f"Sonuç güncellemesi: {update['pending']} kayıt bekliyordu, {update['updated']} kayıt ilerledi"
                     + (f", {update['resolved_1m']} belirsiz mum 1m veriyle çözüldü." if update.get("resolved_1m") else "."))
    for label, p in s["periods"].items():
        lines += ["", f"{label.upper()}"]
        for cls, t in p["classes"].items():
            if cls == "BLOCKED_SETUP":
                continue                 # reported below, by reason and with virtual results
            lines.append(f"{CLASS_TR[cls]} [{cls}]: {t['count']} kurulum, {t['measured']} ölçüldü (24s)")
            if not t["measured"]:
                continue
            if t["trigger_rate_%"] is None:
                lines.append(f"   ortanca 24s getiri {v(t['median_24h_return_%'], '%')}")
            else:
                lines.append(f"   tetiklenme {v(t['trigger_rate_%'], '%')} · 1R {v(t['hit_1R_%'], '%')} · 2R {v(t['hit_2R_%'], '%')} · "
                             f"ort. MFE {v(t['mean_mfe_r'], 'R')} · ort. MAE {v(t['mean_mae_r'], 'R')} · "
                             f"ort. sonuç {v(t['mean_result_r'], 'R')} · ortanca 24s getiri {v(t['median_24h_return_%'], '%')}")
        b = p["blocked"]
        lines.append(f"Engelli kurulumlar [BLOCKED_SETUP]: {b['ALL']['count']} kurulum, {b['ALL']['measured']} ölçüldü "
                     "(sanal: işlem yapılmadı)")
        for reason, text in BLOCK_REASONS.items():
            t = b[reason]
            if not t["count"]:
                continue
            lines.append(f"   {text}: {t['count']}" + ("" if not t["measured"] else
                         f" · ortanca 24s getiri {v(t['median_24h_return_%'], '%')} · tetiklenirdi {v(t['would_trigger_%'], '%')} · "
                         f"1R'ye giderdi {v(t['would_hit_1R_%'], '%')} · 2R'ye giderdi {v(t['would_hit_2R_%'], '%')} · "
                         f"MFE {v(t['mean_virtual_mfe_r'], 'R')} · MAE {v(t['mean_virtual_mae_r'], 'R')}"))
        k, i = p["breakout"], p["intrabar"]
        lines.append(f"Kırılım (girişi gerçekleşen {k['entered']}): hemen sahte kırılım {v(k['immediate_false_breakout_%'], '%')} · "
                     f"geç bozulma {v(k['late_breakout_failure_%'], '%')}")
        lines.append(f"Mum içi belirsizlik ({i['trades']} işlem): belirsiz {v(i['ambiguous_%'], '%')} · 1m ile çözülen "
                     f"{v(i['resolved_1m_%'], '%')} · ort. sonuç temkinli {v(i['mean_result_r_conservative'], 'R')}, iyimser "
                     f"{v(i['mean_result_r_optimistic'], 'R')} (fark {v(i['optimistic_minus_conservative_r'], 'R')})")
    lines += ["", "Aynı kurulum birkaç taramada görülürse bir kez sayılır (ilk kaydı ölçülür). Sonuç = stop (−1R) ya da ilk hedef "
              "(+1R), hangisi önce gelirse; ikisi aynı mumdaysa temkinli hesap stopu sayar. Engelli kurulumların sonuçları "
              "sanaldır. Bu sayılar yalnız raporlanır: hiçbir eşik ya da karar bunlara göre değişmez, emir gönderilmez."]
    return "\n".join(lines)


def versions(rows: list[dict]) -> list[dict]:
    """Which advisor versions wrote the log: per advisor_version + ruleset_hash, the records by origin and the span
    of market time they cover. Oldest first."""
    groups: dict[tuple, dict] = {}
    for r in (normalize(dict(x)) for x in rows):
        g = groups.setdefault((r.get("advisor_version"), r.get("ruleset_hash")), {
            "advisor_version": r.get("advisor_version"), "ruleset_hash": r.get("ruleset_hash"), "LIVE": 0, "REPLAY": 0,
            "TEST": 0, "first_ms": r["close_ms"], "last_ms": r["close_ms"], "git_commits": set()})
        g[r["data_origin"]] += 1
        g["first_ms"], g["last_ms"] = min(g["first_ms"], r["close_ms"]), max(g["last_ms"], r["close_ms"])
        if r.get("git_commit"):
            g["git_commits"].add(r["git_commit"][:10] + ("+dirty" if r.get("working_tree_dirty") else ""))
    out = sorted(groups.values(), key=lambda g: g["first_ms"])
    for g in out:
        g.update(first=_iso(g["first_ms"]), last=_iso(g["last_ms"]), git_commits=sorted(g["git_commits"]))
    return out


def format_versions(vs: list[dict], current: str | None = None) -> str:
    lines = ["📒 Danışman sürümleri (paper log)"]
    if not vs:
        lines.append("Henüz kayıt yok.")
    for g in vs:
        lines.append(f"{g['advisor_version']} · kural seti {g['ruleset_hash']}" + (" (güncel)" if g["ruleset_hash"] == current else "")
                     + f": canlı {g['LIVE']} kayıt · replay {g['REPLAY']} · test {g['TEST']} · ilk {g['first']} · son {g['last']}"
                     + (f" · kod {', '.join(g['git_commits'])}" if g["git_commits"] else ""))
    lines.append("İstatistikler varsayılan olarak yalnız güncel kural setinin canlı kayıtlarını sayar.")
    return "\n".join(lines)

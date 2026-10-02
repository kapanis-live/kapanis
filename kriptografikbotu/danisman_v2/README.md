# Kripto Danışman V2

Decision support for one admin: analysis, a stop-limit buy plan, a position-protection plan and a market scan.
**It never places an order.** There is no exchange key, no order endpoint and no code path that could send one.

```
Binance candles (15m / 1h / 4h / 1d, closed only)          execution-sensitive price data
        │
        ▼
MarketSnapshot (snapshot.py)                               one frozen picture: indicators, confirmed swings, zones,
        │                                                  breakout / retest / reclaim facts, BTC regime, portfolio,
        │        OpenBB MacroSnapshot (macro.py) ──────►   macro (calendar, rates, inflation, employment, equities)
        ▼
Rule engine (planner.py, protection.py)                    deterministic: trigger, limit, stop, invalidation, target,
        │                                                  position size, current R, stop management
        ▼
3 independent AI analyses (agents.py)                      three ROLES (TECHNICAL, RISK, REGIME), same snapshot, one
        │                                                  JSON verdict each; they never set a price. Roles, not
        │                                                  models: by default all three run on one model
        ▼
Consensus (consensus.py)                                   plain rules; Risk and Regime are vetoes; a missing
        │                                                  analyst means no buy
        ▼
Plan  +  paper log (research.py → danisman_paper)          validation only: outcomes never feed back into a rule
```

## What each part does

| Part | Role |
|---|---|
| **Binance** | The only source of crypto candles and prices. The open candle gives `current_price` and nothing else. |
| **OpenBB** | Macro and cross-asset context: economic calendar, rates, inflation, employment, S&P 500 / Nasdaq 100 / VIX. A risk filter for new entries, never a buy signal. |
| **Technical engine** | The first advisor's indicator, swing, trend and breakout-state code (`danisman.py`, unchanged) plus V2's zones, retest / reclaim facts and planners. All arithmetic lives here. |
| **3 AI analyses** | Three independent analyst roles: explain, argue and veto. Technical judges the setup, Risk the plan and the portfolio, Regime looks for reasons not to trade. This is not a three-model consensus unless three different models are configured; the health endpoint and the panel report how many distinct models there are. |
| **Consensus** | `TECHNICAL == BUY` and `RISK == APPROVE` and `REGIME != BLOCK`, all three answered, and the rule engine itself has a complete, unblocked plan. Anything else is WAIT / NO_TRADE / BLOCKED_SETUP / DEGRADED_CONSENSUS / CONSENSUS_DISAGREEMENT. Never "2 of 3". |
| **Order planner** | Stop-limit buy: trigger = top of the resistance + 1 tick; limit = trigger + max(2 ticks, 0.10 ATR15), capped at 0.25 %; stop = support low − 0.15 ATR(1h); size from the risk budget. |
| **Paper** | Every run is recorded in the first advisor's paper log under V2's own ruleset hash. Exit styles and whipsaws are measured there. |

## Evidence status: RESEARCH, not a proven edge

Every plan carries `evidence_status: RESEARCH_UNPROVEN`. What the project's own tests found:

- the 15m breakout rule lost about 0.21R per trade (no better than random entries);
- the 2023–2025 intraday lab (`research/strategy_lab_v3.py`) tested breakout-retest, failed-breakout reclaim and four
  other setups on 15m / 1h / 4h: none had a positive mean R in both the development and the validation period;
- a bigger breakout buffer, a hard R/R ≥ 1.5 filter and selling half at a first target each made results worse or no better;
- a 3 ATR trailing stop did best on **daily** bars; that is not evidence for 15m / 1h, so it is shown as a reference only.

The advisor explains the structure and keeps the risk small. It is not evidence that a trade makes money. The locked
last year of data is never used to tune anything here, and `MIN_STOP_ATR15` is not tuned from a few whipsawed stops.

## Buy flow

1. Blocks first (no plan is released when one applies): `DATA_STALE`, `DATA_ERROR`, `INSUFFICIENT_HISTORY`,
   `TREND_1H_DOWN`, `4H_STRONG_DOWN`, `HTF_STRONG_DOWNTREND`, `BTC_MARKET_RISK` (BTC 1h and 4h both in a strong
   downtrend), `MACRO_EVENT_BLOCK`, `NO_VALID_STOP`, `MAX_EXPOSURE_REACHED`, `PORTFOLIO_CONCENTRATION_HARD_LIMIT`.
   A blocked setup keeps its levels on record (`BLOCKED_SETUP`, `withheld_plan`).
2. Setup, from closed 15m candles:
   - **BREAKOUT** pending: a resistance within reach → a resting stop-limit (`WAIT_FOR_BREAKOUT`).
   - **BREAKOUT** confirmed: a close above the level and the price within `NO_CHASE_ATR15` of the trigger (`BUY_SETUP`).
   - **NO_CHASE**: farther than that → `WAIT_FOR_RETEST`; nothing is bought until a 15m candle enters the retest zone
     and closes above the broken level.
   - **RETEST** confirmed: trigger = that candle's high + 1 tick.
   - **RECLAIM**: a failed breakout taken back and held for `RECLAIM_HOLD_BARS` candles. Watch only: it collects
     paper results before it may ever be offered.
   - A failed breakout that was not reclaimed gives no buy.
3. Stop: the nearest structural level under the entry that leaves `MIN_STOP_ATR15` of room; a nearer one is skipped
   (`STOP_TOO_TIGHT`). No level, or only one farther than `MAX_STOP_DISTANCE_PCT`: no plan. Never a fixed percentage.
   The stop (with its buffer) and the invalidation (the level itself) are shown separately.
4. Size: `portfolio × RISK_PER_TRADE_PCT ÷ stop distance`, then the smallest of that, `MAX_NEW_POSITION_PCT`, the room
   under each exposure limit and the cash; rounded down to the exchange's step; nothing under its minimum.
   Without a portfolio size: `PORTFOLIO_REQUIRED_FOR_SIZING`.
5. The three analysts read the snapshot and the engine's result; the consensus releases the plan or says why not.

## Sell = position protection

`SAT` never means a market sell. The plan gives a take profit, a stop, the invalidation, the current R and what to
watch next. R is the distance from the entry to the first stop (stored with the position).

When the first stop is not on record (an old position, several buys), R is measured from an assumed 1.5 ATR(1h) unit
and is **ESTIMATED_R**: `current_R_estimated: true`, shown as `~1.3R (estimated)`, never as a real R. A position whose
entry matches the last released V2 plan (between its trigger and limit) takes that plan's stop as its first stop, so
trades taken from V2 plans have a real R.

| State | Stop |
|---|---|
| `INITIAL` (< +1R) | the first structural stop; not moved to break-even |
| `PROFIT_1R` | break-even + fees, only if the price keeps `MIN_STOP_ATR15` of room |
| `PROFIT_2R` / `TRENDING` | a confirmed 15m higher low − 0.25 ATR15, or the 1h support − 0.15 ATR(1h) |
| `PROTECT` | weakness: 15m turned down, 1h closed under its SMA20, a resistance rejected the price |
| `EXITED` | a closed 15m candle traded at or under the stop |

The stop is monotonic: it never moves down between runs unless the admin types one by hand. Exit reasons are
structural (invalidation closed under, 4h turned strongly down, a major support lost, a failed breakout that was
bought). RSI alone never sells and never buys. Take profit: the first 1h resistance at least `MIN_TP_ATR1H` away,
else 2.5R marked as a research fallback, else none.

## Macro (OpenBB)

OpenBB 5 cannot be installed next to the site's backend (it needs FastAPI ≥ 0.137, the backend pins 0.110), so it
lives in its own virtual environment and is called as a short-lived process:

```
python -m venv .venv-openbb
.venv-openbb\Scripts\pip install openbb        # about 1.1 GB
set OPENBB_PYTHON=<path>\.venv-openbb\Scripts\python.exe
```

or as a separate worker on the internal network: `python openbb_worker.py serve 8010` and `OPENBB_URL=http://openbb:8010`.
It is **not** in the production image (`WITH_OPENBB=0`); the staging plan is `kapanis/deploy/OPENBB_STAGING.md`.

Works without any provider key (measured 2026-10-02): Nasdaq / BLS / Federal Reserve calendars, Treasury rates, EFFR,
OECD CPI, unemployment and short-term rate, Fed inflation expectations, Cboe SPX and VIX, Nasdaq 100, US market status.
Needs a key: every `obb.fred.*` series (FRED), EIA, Congress. Not installed by default: yfinance, FMP, Trading Economics.

No calendar provider reports how important an event is, and the advisor does not guess. An event is "high impact"
only when its name contains a word from `ADVISOR_MACRO_HIGH_IMPACT_KEYWORDS` (e.g. `cpi,nonfarm,fomc`); with the list
empty the impact is `null` and no macro caution or block is raised. When OpenBB is missing or a read fails,
`macro_status` is `DEGRADED` / `UNAVAILABLE` and the technical report is unaffected.

## AI analysts

Any OpenAI-compatible chat endpoint. Per role: `TECHNICAL_AI_PROVIDER`, `TECHNICAL_AI_MODEL`, and optionally
`TECHNICAL_AI_BASE_URL` / `TECHNICAL_AI_API_KEY` (same for `RISK_` and `REGIME_`). Providers: `deepseek`
(`DEEPSEEK_API_KEY`), `nvidia` (`NVIDIA_API_KEY`, or `KIMI_API_KEY` / `GLM_API_KEY`), `openai` (`OPENAI_API_KEY`),
`custom`. Timeout `ADVISOR_AI_TIMEOUT_SECONDS`, one retry, invalid JSON is retried once and then counts as FAILED.
A role without a key is `NOT_CONFIGURED`: the consensus is `DEGRADED_CONSENSUS` and no buy plan is released.

Timeouts: `ADVISOR_AI_TIMEOUT_SECONDS` (60) per attempt, one retry, and a hard `ADVISOR_AI_TOTAL_TIMEOUT_SECONDS` (100) for
the three together; they run in parallel. An analyst that has not answered by then is `FAILED / TIMEOUT_TOTAL` and the
consensus is `DEGRADED_CONSENSUS`: no buy. Macro is waited for at most `ADVISOR_MACRO_WAIT_SECONDS` (40). The panel's
request timeout is 180 s; the site's Caddy proxy sets no response timeout.

Default: all three roles on `deepseek` / `deepseek-flash` (three separate calls, three briefs). Measured 2026-10-02
with a real snapshot (about 12.5k prompt tokens per call): DeepSeek answered in 11–43 s with valid JSON; the
NVIDIA-hosted Kimi K3 and GLM 5.3 did not answer within 330 s, so they are not the default. One run costs three calls.

## Admin API (site backend)

`/api/admin/advisor/health · analyze · buy-plan · sell-plan · scan · macro · paper-stats · consensus-history · portfolio`

The session is verified on the server; the caller must be the owner and, when `ADMIN_EMAILS` is set, on that list.
Nothing the browser claims about itself is used. Runs are stored in `advisor_consensus_runs` (decision, verdicts,
hashes, models, latencies, `admin_user_hash`; no e-mail, no key), position states in `advisor_positions`.

## Configuration

Every threshold is in `config.py`, documented, and can be overridden with `ADVISOR_<NAME>`. A changed threshold
changes the ruleset hash, so paper statistics of different settings are never mixed.

The four exposure limits (total crypto 60 %, altcoins 30 %, memecoins 5 %, correlated holdings 25 %) are
**CONFIGURED_POLICY**: placeholders for the admin's own preference. They come from no test, and the API and the panel
label them that way. `MAX_NEW_POSITION_PCT` (3 %) and `RISK_PER_TRADE_PCT` (0.35 %) are the admin's stated sizes.

## Tests

```
python -m unittest test_danisman_v2 -v                          # engine, planners, consensus, macro, paper, whipsaw
cd ../kapanis/backend && python -m unittest tests.test_advisor_v2_api -v    # admin only, no secrets, audit log
```

## Known limits

- The setups are untested on intraday history; treat every plan as a hypothesis with a small, fixed risk.
- A scan asks no model: its levels are the engine's candidates, not released plans.
- Correlation is measured against at most 8 holdings (1h returns, last 200 candles).
- A position with several buys has no single "first stop": R is then measured from an assumed 1.5 ATR(1h) unit, and
  the page says so. Typing the real first stop fixes it.
- Macro event impact is unknown unless the keyword list is set.

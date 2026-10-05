# History tests behind the bot's rules

Run from this folder with the bot's venv; klines are cached in `./kl/` (git-ignored).

| Script | Question | Result (2026-09-28) |
|---|---|---|
| `research_sr.py` | Do resistance zones (`market.sr_zones`) turn price back more than random levels? Does the scanner's breakout AL make money? | Zones 55.4% vs random 55.7%. Breakout: -0.21R per trade (95% range -0.29..-0.13), 1,856 trades, no better than random entries. |
| `research_gate.py` | Same breakout with the gate's extra rules (BTC gate, R/R >= 1.5, stop >= 1 ATR) | -0.22R per trade, 890 trades |
| `lab.py` | Textbook daily rules (SMA200, golden cross, Donchian, RSI2, Bollinger, NR7), 15 coins and 40 BIST stocks | Nothing beats buy & hold in both halves; BIST buy & hold wins everywhere |
| `lab_xs.py`, `lab_xs2.py` | Monthly momentum rotation | +118%/yr on today's 15 large coins, collapses (-30%/yr, -98% drawdown) once coins that died are included: survivorship bias |
| `lab_risk.py` | Trend rules vs random in/out with the same time in the market (76 coins incl. dead ones) | Donchian 20/10 + 200-day filter beat buy & hold and random timing in both halves: the only rule the bot offers (`kapanis/backend/trend_rule.py`) |

Because of these results the bot's automatic buy suggestions are off (`config.BUY_SIGNALS`), resistance zones are
information only, and the tested daily exit (close below the 10-day low) is used in exit analyses and plans.

## Strategy Engine 2.0 (2026-09-28)

`engine.py` (common standard), `regime.py` (TREND_UP / TREND_DOWN / YATAY / YUKSEK_VOL / PANIK per day, from past data),
`strategies.py` (candidates written once with textbook parameters), `run_v2.py` (runs all, writes results_v2.json).
Standard: daily close decisions, costs, delisted coins included, the LAST 365 DAYS LOCKED until the final score,
buy & hold and 20 random-timing twins with the same exposure and holding length, yearly folds, per-regime trade results.

| Strategy | Crypto | BIST |
|---|---|---|
| Trend following (Donchian 20/10 + SMA200) | RESEARCH: dev 9.6 %/yr vs random -2.1 (64 % of coins beat their twin); locked year 0.0 vs 0.0 (51 %) while buy & hold fell 54 % | RESEARCH: dev 17.5 vs random 11.2 but buy & hold 37.0; locked year -1.4 vs 6.3 |
| Trend pullback | REJECTED | REJECTED |
| Volatility contraction breakout | REJECTED (dev 0.0 vs -2.9, 56 %) | REJECTED |
| Relative strength vs benchmark | REJECTED | REJECTED |
| Mean reversion in low-ADX ranges | REJECTED | REJECTED |

No rule is PRODUCTION. The regime table per strategy (trades by regime at entry) is in results_v2.json; it is too thin
and too bull-market-dominated to choose strategies by regime (no meta-strategy until a candidate passes on its own).

## Stop-limit / order planning layer (2026-10-01)

`stop_limit.py` (the layer: resistance clusters, stop-limit trigger and limit, structural/ATR stop, targets, trailing
stop, position size, `TradePlan`), `stop_limit_bt.py` (history test, writes `stop_limit_results.json`),
`../test_stop_limit.py` (formulas, fills, no look-ahead). It sits on top of the 0/1 strategies and changes none of them;
it is not wired to the bot or the site. `python research/stop_limit.py BTC` prints a plan from live daily bars.

Test: daily bars, 76 coins (dead ones included) and 40 BIST stocks, commission 0.1 % / 0.2 % per side plus 0.05 % / 0.10 %
slippage on every stop fill, orders computed at one close and filled on the next day. Parameters were chosen on the
development period only (before the last 730 days), one dimension at a time, the default kept unless a variant was
0.5 %/yr better; the validation year confirms, the locked last year is scored once.

Median yearly result per asset, rule vs its random twin (share of assets that beat their twin):

| | Development | Validation | Locked last 12 months | Verdict |
|---|---|---|---|---|
| Crypto, defaults from the brief | -5.2 vs -0.3 (37 %) | -4.7 vs 0.0 (38 %) | -2.4 vs 0.0 (34 %) | fails everywhere |
| Crypto, development-chosen | 7.8 vs 0.0 (65 %) | 0.2 vs -0.8 (46 %) | 3.6 vs -8.5 (64 %) | RESEARCH |
| BIST, defaults from the brief | 5.7 vs 3.4 (62 %) | -4.7 vs 0.0 (36 %) | -0.6 vs 0.0 (45 %) | RESEARCH |
| BIST, development-chosen | 23.3 vs 18.9 (60 %) | 1.4 vs 0.9 (43 %) | -0.1 vs 3.1 (36 %) | RESEARCH |

What the development period said: a breakout buffer does not help (0 was best in crypto, 0.1 % in BIST); a trailing stop
of 3 ATR beat every tighter one including the regime bands; the "R/R to the next resistance >= 1.5" filter removed
profitable trades (no filter was best); selling half at TP1 halved the result; the breakout score did not separate
good from bad breakouts in crypto and only weakly in BIST; a 1 ATR stop was the worst stop. Buying the confirmed close
instead of the stop-limit fill gave a similar result (about 45 % of stop-limit fills closed back under the resistance
on the entry day). BIST buy & hold beat every variant. Nothing is PRODUCTION; ABD was not tested.

## Stop distance and noise (`whipsaw.py`, 2026-10-04)

78 coins (dead ones included), closed 15m candles, 24 hours after each entry. Development 2023-01..2024-09, validation
the year after; the two agree within 2 points.

| Stop under the entry | Low touched it in 24 h | of those, closed back above the entry | +1R before the stop | net R |
|---|---|---|---|---|
| 1 ATR(15m) | 89 % | 82 % | 47 % | -0.50 |
| 2 ATR | 78 % | 71 % | 48 % | -0.27 |
| 3 ATR | 67 % | 61 % | 47 % | -0.18 |
| 4 ATR | 56 % | 52 % | 45 % | -0.13 |
| 6 ATR | 39 % | 39 % | 36 % | -0.08 |

A stop of a few 15m ATR is inside normal noise. No distance makes the 20-candle breakout entry profitable; entries on
a fixed grid (no setup) give the same picture. Used only as a measurement line on the signal card
(`signal_life.STOP_NOISE`); nothing is suggested from it.

Regime as an entry filter (same day's `results_v2.json`, `rejime_gore`): the trend rule has 11 trades opened in PANIK
(profit factor 0.38) out of 1105, too few to decide; the turn-of-month rule is best in PANIK (371 trades, 69 % hit,
profit factor 3.63). A "no new longs in PANIK" block is not supported and is not wired in.

## Better-drawn levels (`levels_lab.py`, 2026-10-05)

Three ways to draw support / resistance (the bot's pivot clusters, volume-profile nodes, only pivots followed by a
2 ATR reaction), five events on a 1h close, 77 coins, a 1 ATR(4h) race over 48 hours, 0.1 % per side, against zones
of the same width at random prices. 15 method x event pairs, development and validation: none passes.

| Event (pivot levels) | Hit, real / random | Daily mean net R, real / random |
|---|---|---|
| Held at support | 50 % / 52 % | -0.03 / +0.01 |
| Breakout | 49 % / 50 % | -0.13 / -0.14 |
| Retest after a breakout | 53.5 % / 50-52 % | -0.04 / -0.09 |
| Stopped at resistance (down) | 50 % / 49 % | -0.05 / -0.03 |
| Breakdown (down) | 49 % / 48 % | -0.15 / -0.19 |

Volume-profile and reaction-filtered levels give the same picture. The only repeatable difference from random is the
retest after a breakout (about +2-3 points of hit rate in both periods, with both pivot variants), and it is still
below zero after costs. Levels stay an information line; nothing is suggested from them.

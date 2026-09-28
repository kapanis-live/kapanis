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

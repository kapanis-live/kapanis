"""Candidate strategies, each written ONCE with textbook parameters before testing (no tuning on results).

Every function takes an indicator frame (engine.indicators + benchmark columns) and returns 0/1 positions decided on
each day's close. The exit is part of the rule.
"""
import numpy as np


def trend_donchian(df):
    """Baseline (already in production): in on a close above the 20-day high and SMA200, out below the 10-day low."""
    c, hi, lo, s200 = df.c.values, df.hi20.values, df.lo10.values, df.sma200.values
    pos, hold = np.zeros(len(df)), 0
    for i in range(len(df)):
        if not hold and c[i] > hi[i] and c[i] > s200[i]:
            hold = 1
        elif hold and c[i] < lo[i]:
            hold = 0
        pos[i] = hold
    return pos


def trend_pullback(df):
    """In an uptrend (close > SMA200, SMA50 > SMA200, 63-day return above the benchmark's), buy the first close back
    above the previous day's high after the price dipped to the 20-day EMA within the last 3 days.
    Exit: close below the 10-day low, or below entry − 2 ATR."""
    n = len(df)
    c, h, l = df.c.values, df.h.values, df.l.values
    ema, s50, s200, lo, atr = df.ema20.values, df.sma50.values, df.sma200.values, df.lo10.values, df.atr.values
    rs = (df.ret63 - df.bench_ret63).values
    pos, hold, stop = np.zeros(n), 0, 0.0
    for i in range(3, n):
        trend = c[i] > s200[i] and s50[i] > s200[i] and rs[i] > 0
        dipped = min(l[i - 3:i]) <= max(ema[i - 3:i])
        if not hold and trend and dipped and c[i] > h[i - 1]:
            hold, stop = 1, c[i] - 2 * atr[i]
        elif hold and (c[i] < lo[i] or c[i] < stop):
            hold = 0
        pos[i] = hold
    return pos


def vol_contraction(df):
    """After a squeeze (Bollinger width AND ATR in the bottom 20 % of the last 100 days, on any of the last 5 days),
    buy a close above the 20-day high on 1.5× average volume. Exit: close below the 10-day low."""
    n = len(df)
    c, hi, lo, v, vma = df.c.values, df.hi20.values, df.lo10.values, df.v.values, df.vol_ma20.values
    squeeze = ((df.bbw_rank <= 0.2) & (df.atr_rank <= 0.2)).values
    pos, hold = np.zeros(n), 0
    for i in range(5, n):
        if not hold and squeeze[i - 5:i + 1].any() and c[i] > hi[i] and v[i] > 1.5 * vma[i]:
            hold = 1
        elif hold and c[i] < lo[i]:
            hold = 0
        pos[i] = hold
    return pos


def relative_strength(df):
    """Hold while stronger than the benchmark over 63 days AND close > SMA200 AND SMA50 > SMA200.
    Checked every 21 days (monthly), so it does not flip daily."""
    n = len(df)
    ok = ((df.ret63 > df.bench_ret63) & (df.c > df.sma200) & (df.sma50 > df.sma200)).values
    pos, hold = np.zeros(n), 0
    for i in range(n):
        if i % 21 == 0:
            hold = int(ok[i])
        pos[i] = hold
    return pos


def mean_reversion_range(df):
    """Only when trend strength is low (ADX < 20) and above SMA200: buy RSI(2) < 10 closes below the lower
    Bollinger band. Exit: close above SMA20 or after 5 days."""
    n = len(df)
    c, s20, s200, adx, rsi, bbl = df.c.values, df.sma20.values, df.sma200.values, df.adx.values, df.rsi2.values, df.bb_lo.values
    pos, hold, days = np.zeros(n), 0, 0
    for i in range(n):
        if not hold and c[i] > s200[i] and adx[i] < 20 and rsi[i] < 10 and c[i] < bbl[i]:
            hold, days = 1, 0
        elif hold:
            days += 1
            if c[i] > s20[i] or days >= 5:
                hold = 0
        pos[i] = hold
    return pos


ALL = {"trend_takibi (mevcut)": trend_donchian, "trend_geri_cekilme": trend_pullback,
       "sikisma_kirilimi": vol_contraction, "goreli_guc": relative_strength, "yatayda_donus": mean_reversion_range}

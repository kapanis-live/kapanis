"""Regime v2: one market state per day for the benchmark (BTC for crypto, XU100 for BIST), from past data only.

Order of precedence:
PANIK        20-day return <= -15 %, or ATR in the top 10 % of the last 100 days while below the 50-day average
YUKSEK_VOL   ATR in the top 20 % of the last 100 days
TREND_UP     close > SMA200, SMA50 > SMA200, ADX >= 20
TREND_DOWN   close < SMA200 and SMA50 < SMA200
YATAY        everything else (weak trend strength, mixed averages)
"""
import pandas as pd

LABELS = ["TREND_UP", "TREND_DOWN", "YATAY", "YUKSEK_VOL", "PANIK"]


def label(df: pd.DataFrame) -> pd.DataFrame:
    r20 = df.c / df.c.shift(20) - 1
    out = []
    for i in range(len(df)):
        row = df.iloc[i]
        if pd.isna(row.sma200) or pd.isna(row.atr_rank) or pd.isna(row.adx):
            out.append("?")
        elif r20.iloc[i] <= -0.15 or (row.atr_rank >= 0.9 and row.c < row.sma50):
            out.append("PANIK")
        elif row.atr_rank >= 0.8:
            out.append("YUKSEK_VOL")
        elif row.c > row.sma200 and row.sma50 > row.sma200 and row.adx >= 20:
            out.append("TREND_UP")
        elif row.c < row.sma200 and row.sma50 < row.sma200:
            out.append("TREND_DOWN")
        else:
            out.append("YATAY")
    df["regime"] = out
    return df

"""Kripto Danışman: "şimdi ne yapayım?" for one coin, from the exchange's own candles. Decision support only.

    Binance klines (15m, 1h, 4h, 1d; closed candles only)
      -> indicators            view():  SMA20/50/200, EMA20, VWAP, RSI14, ATR14, volume MA20, Donchian, slopes
      -> market structure      trend_state(), levels():  confirmed swings, ATR clusters, supports / resistances
      -> breakout state        find_breakout():  NONE / TESTING / CONFIRMED / FAILED_BREAKOUT (closed 15m candles)
      -> risk + stop-limit     research/stop_limit.py:  trigger, limit, stop, R/R, trailing; size_position()
      -> advisor               analyze():  one decision, the evidence for it, what would change it

Roles of the timeframes: 15m entry timing, 1h main direction and structure, 4h trend filter, 1d context.
It never places an order and never opens a position. The breakout and stop rules here were NOT history-tested on
intraday candles (the daily test is in research/README.md, status RESEARCH), so the report explains the structure;
it is not evidence that a trade makes money. Nothing after `asof` can influence a report: every frame is cut to the
candles closed by then, and a swing is only known once its right-hand candles have closed.

    python danisman.py HYPE
    python danisman.py BTC --portfolio 287
    python danisman.py SOL --portfolio 287 --position 24.5 --avg-price 120.45 --holdings BTC,ETH
    python danisman.py --tara --portfolio 287 --holdings BTC,ETH     # scan the most traded pairs
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import math
import os
import pathlib
import re
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone

import httpx
import numpy as np
import pandas as pd

RESEARCH = pathlib.Path(__file__).resolve().parent / "research"
log = logging.getLogger(__name__)


def _load(name: str):
    """Import a research module by path (research/ is not a package and must not shadow the bot's modules)."""
    key = f"research_{name}"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, RESEARCH / f"{name}.py")
        sys.modules[key] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sys.modules[key])
    return sys.modules[key]


sl = _load("stop_limit")

# ---------------- version ----------------
ADVISOR_VERSION = "1.0.0"        # the advisor as a product; raise it when its behaviour changes for the user
RULESET_REVISION = 1             # raise it when the decision CODE changes in a way the constants in ruleset() cannot show
ORIGINS = ("LIVE", "REPLAY", "TEST")   # where a paper record comes from: a real run, a replayed moment, a test

# ---------------- config ----------------
TFS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
BARS = 500                       # candles fetched per timeframe
TREND_BARS = 60                  # closed candles a timeframe needs for its trend (SMA50, its slope, two swings); with
#                                  fewer it is INSUFFICIENT_HISTORY and takes no part in the decision or the evidence
SMA200_BARS = 205
NEED_BARS = {"15m": 120, "1h": 120, "4h": 0, "1d": 0}   # below this there is no report at all (a pair listed days ago)
QUOTES = ("USDT", "USDC", "FDUSD", "BTC")   # tried in this order; a BTC quote is analysed but never sized in USDT
SCAN_QUOTES = ("USDT", "USDC", "FDUSD")
SCAN_LIMIT = 60                  # the scan covers this many of the most traded pairs (plus the holdings)
SCAN_TOP = 10                    # setups shown
SCAN_REJECTED = 5                # "not now" coins shown with their reason
SCAN_PARALLEL = 6                # coins fetched at the same time
MIN_QUOTE_VOLUME = 5_000_000     # 24 h volume in the quote currency below this: not scanned
MAX_CORRELATED = 4               # at most this many coins that move together (holdings count) are put forward
STOP_OK_PCT = 5.0                # ranking: a stop farther than this is "far"
NEAR_PCT = (1.0, 3.0)            # ranking: the re-check level is near / medium / far (in % of the price)
# The scan covers real spot crypto only. Exchange metadata decides first (trading status, spot permission, the
# LEVERAGED permission, the permission signature that tokenized stocks share); these lists cover what the metadata
# does not say. A coin whose price sits at 1.00 all day is treated as a stablecoin whatever it is called.
STABLES = {"USDT", "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "USDE", "USD1", "XUSD", "BFUSD", "PYUSD", "USTC", "RLUSD",
           "USDS", "FRAX", "LUSD", "GUSD", "SUSD", "EURI", "AEUR", "EURC"}
FIAT = {"EUR", "GBP", "TRY", "BRL", "ARS", "UAH", "JPY", "AUD", "RUB", "PLN", "RON", "ZAR", "MXN", "COP", "CZK", "IDRT",
        "BIDR", "NGN", "BKRW", "VAI"}
COMMODITIES = {"PAXG", "XAUT", "XAUM", "KAU", "KAG", "XAG"}
WRAPPED = {"WBTC", "WBETH", "BNSOL", "WETH", "WSTETH", "CBBTC", "STETH", "BETH"}     # the same asset twice
KNOWN_STOCKS = {"NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "AMD", "INTC", "COIN", "MSTR", "PLTR", "QQQ", "SPY",
                "HOOD", "CRCL", "AVGO", "ORCL", "TSM", "BABA", "IBM", "ARM", "DELL", "PYPL", "GS", "TQQQ", "SOXL"}
EQUITY_GROUP_MIN = 10            # a permission signature shared by this many symbols...
EQUITY_GROUP_SHARE = 0.8         # ...of which this share is named like a stock token (TICKER + "B") is the stock group
META_SECONDS = 6 * 3600          # exchange metadata is kept this long in memory
EXCLUDE_TR = {"INACTIVE": "işleme kapalı / spot işlem izni yok", "LEVERAGED": "kaldıraçlı token",
              "EQUITY_TOKEN": "hisse / ETF tokenı", "STABLE": "stabil coin", "FIAT": "itibari para paritesi",
              "COMMODITY": "altın / emtia tokenı", "WRAPPED": "sarılmış varlık (aynı coinin kopyası)",
              "LOW_VOLUME": "24 saatlik hacim düşük", "BAD_NAME": "desteklenmeyen kod"}
BASES = ("https://data-api.binance.vision", "https://api.binance.com")
SLOPE_BARS = 5                   # an average's slope = its change over this many candles, in %
LOOKBACK = 250                   # candles searched for swings, per timeframe
REACTION_ATR = 1.0               # a swing is a level only if the price moved this many ATR away within K candles
ROOM_ATR = 0.5                   # a breakout with less room than this (1h ATR) to the next resistance is not one
BREAKOUT_WINDOW = 8              # 15m candles: a first close above a level this recently is a fresh breakout
FAILED_WINDOW = 16               # 15m candles: closed above the level, now back under it
RETEST_WINDOW = 96               # 15m candles (24 h) a broken level stays "the breakout level"
NEAR_ATR = 1.0                   # entry allowed while the price is within this many 1h ATR of the level
RETEST_ATR = 0.25                # a pullback this close above the broken level (1h ATR) has reached the retest zone
LOW_RR = 1.5                     # R/R to the first resistance under this: "target room is narrow" (never a trade filter)
PLAN_ATR = 3.0                   # a resistance farther than this (1h ATR) is not planned for yet
RISK_PCT = 0.005                 # of the portfolio, lost if the stop is hit
MAX_POSITION = {"MAJOR": (0.15, 0.20), "ALT": (0.10, 0.15), "MEME": (0.05, 0.10)}   # (volatile, calm) share of portfolio
MAJORS = {"BTC", "ETH", "BNB", "SOL", "XRP"}
MEMES = {"DOGE", "SHIB", "PEPE", "WIF", "BONK", "FLOKI", "MEME", "TRUMP", "FARTCOIN", "PENGU", "BOME", "NEIRO", "TURBO"}
HIGH_VOL_ATR_PCT = 0.06          # daily ATR / price at or above this: the lower cap of the class
MIN_ORDER_USDT = 5.0
TRAIL_ATR = 3.0                  # best in the daily history test; not tested on intraday candles
PROFIT_ATR = 2.0                 # open profit above this many 1h ATR (and 3 %): protect it
HIGH_CORR = 0.75                 # 1h-return correlation with a holding at or above this
FEE = 0.001
# buffer: the daily test found that bigger breakout buffers only made results worse, so the trigger sits just above
# the level (0.05 %) to skip one-tick wicks; the limit keeps the fill close to the trigger
PARAMS = sl.Params(pct_buffer=0.0005, atr_buffer=0.0, limit_cap=0.004, max_risk_pct=0.12, stop_mode="kombine",
                   trail=TRAIL_ATR, min_rr=0.0, min_score=-99)

DECISION_TR = {"BUY_SETUP": "ALIM KURULUMU VAR", "WAIT_FOR_BREAKOUT": "BEKLE — kırılım bekleniyor",
               "WAIT_FOR_RETEST": "BEKLE — geri test bekleniyor", "HOLD": "TUT", "PROTECT_PROFIT": "KÂRI KORU",
               "REDUCE_RISK": "RİSKİ AZALT", "AVOID": "UZAK DUR", "NO_SETUP": "KURULUM YOK",
               "BLOCKED_SETUP": "ENGELLİ — teknik kurulum var, dış filtre nedeniyle kullanılmıyor"}
TREND_TR = {"STRONG_UPTREND": "güçlü yükseliş", "UPTREND": "yükseliş", "RANGE": "yatay", "DOWNTREND": "düşüş",
            "STRONG_DOWNTREND": "güçlü düşüş", "INSUFFICIENT_HISTORY": "veri yetersiz"}
# why there is no trade to look for: one plain reason per coin (the scan's "not now" list)
REASON_TR = {"BTC_BEARISH": "BTC kısa vadede düşüşte", "NO_ROOM": "hedefe alan yok (üstteki dirençler stop mesafesinden yakın)",
             "HTF_CONFLICT": "1H ve 4H ters yönde", "INSUFFICIENT_HISTORY": "veri yetersiz",
             "STOP_TOO_FAR": "stop çok uzak", "DOWNTREND_1H": "1H ana yön aşağı", "DOWNTREND_4H": "4H güçlü düşüşte",
             "FAILED_BREAKOUT": "sahte kırılım; seviye geri alınmadı", "NO_LEVEL": "yakında planlanabilir seviye yok",
             "PULLBACK_WAIT": "düzeltme bölgesinde, 15m dönüş henüz yok", "NO_DATA": "borsa verisi alınamadı"}
GROUPS = ("READY_TO_WATCH", "WAIT_FOR_BREAKOUT", "WAIT_FOR_RETEST", "PULLBACK_SETUP", "BLOCKED_SETUP", "NO_SETUP", "AVOID")
GROUP_TR = {"READY_TO_WATCH": "İzlemeye hazır (kurulum tamam)", "WAIT_FOR_BREAKOUT": "Kırılım bekleniyor",
            "WAIT_FOR_RETEST": "Geri test bekleniyor", "PULLBACK_SETUP": "Düzeltme kurulumu",
            "BLOCKED_SETUP": "Engelli kurulum", "NO_SETUP": "Kurulum yok", "AVOID": "Uzak dur"}
# A technical setup that an outside filter keeps from being used is BLOCKED_SETUP, not "no setup": the setup is real
# and stays on record (underlying_setup, blocked_plan) so that what it would have done can be compared later.
BLOCK_TR = {"BTC_MARKET_RISK": "BTC kısa vadede düşüşte", "HTF_DOWNTREND": "4h düşüş trendinde",
            "PORTFOLIO_CONCENTRATION": "portföydeki coinlerle birlikte hareket ediyor",
            "INSUFFICIENT_HISTORY": "4h geçmişi yetersiz, trend filtresi çalışmıyor", "OTHER": "bir dış filtre engelliyor"}
BLOCK_RECHECK = {"BTC_MARKET_RISK": "BTC 1h yapısı toparlanırsa (SMA20 üstü kapanış)",
                 "HTF_DOWNTREND": "4h kapanış SMA20 üstüne çıkarsa", "PORTFOLIO_CONCENTRATION": "portföydeki yoğunlaşma azalırsa",
                 "INSUFFICIENT_HISTORY": f"4h'de {TREND_BARS} kapanmış mum birikince", "OTHER": None}
BLOCKABLE = ("READY_TO_WATCH", "WAIT_FOR_BREAKOUT", "WAIT_FOR_RETEST", "PULLBACK_SETUP")
DOWN = ("DOWNTREND", "STRONG_DOWNTREND")
UP = ("UPTREND", "STRONG_UPTREND")
RESEARCH_NOTE = ("Kanıt durumu: 15m kırılım kuralı geçmiş testte kazandırmadı (işlem başı −0,21R); günlük stop-limit "
                 "motoru ARAŞTIRMA aşamasında. Bu rapor yapıyı açıklar, kazanç kanıtı değildir. Emir gönderilmez.")


class NoPair(Exception):
    pass


# ---------------- data ----------------
async def _klines(client: httpx.AsyncClient, pair: str, tf: str, limit: int = BARS) -> pd.DataFrame:
    last = None
    for base in BASES:
        try:
            r = await client.get(f"{base}/api/v3/klines", params={"symbol": pair, "interval": tf, "limit": limit}, timeout=20)
        except httpx.HTTPError as e:
            last = e
            continue
        if r.status_code == 400:
            raise NoPair(pair)
        if r.status_code != 200:
            last = RuntimeError(f"{r.status_code}: {r.text[:120]}")
            continue
        rows = r.json()
        return pd.DataFrame({"t": [int(x[0]) for x in rows], "o": [float(x[1]) for x in rows], "h": [float(x[2]) for x in rows],
                             "l": [float(x[3]) for x in rows], "c": [float(x[4]) for x in rows],
                             "v": [float(x[7]) for x in rows]})   # quote volume
    raise RuntimeError(f"Binance'e ulaşılamadı ({pair} {tf}): {last}")


async def fetch(symbol: str, holdings: list[str] | None = None, client: httpx.AsyncClient | None = None,
                btc: dict | None = None, quotes: tuple = QUOTES) -> dict:
    """Raw candles (the last row of each frame may still be open): the coin, BTC, and 1h candles of the holdings.
    btc: BTC frames fetched once by the caller (the scan), instead of once per coin."""
    symbol = symbol.upper().replace("/", "").removesuffix("USDT") or "BTC"
    own = client is None
    client = client or httpx.AsyncClient()
    try:
        pair = quote = None
        for q in quotes:
            if q == symbol:
                continue
            try:
                first = await _klines(client, symbol + q, "1h")
                pair, quote = symbol + q, q
                break
            except NoPair:
                continue
        if pair is None:
            raise NoPair(f"{symbol}: Binance'te {', '.join(QUOTES)} paritesi yok")
        rest = await asyncio.gather(*[_klines(client, pair, tf) for tf in ("15m", "4h", "1d")])
        frames = {"15m": rest[0], "1h": first, "4h": rest[1], "1d": rest[2]}
        if symbol == "BTC":
            btc = frames
        elif btc is None:
            b = await asyncio.gather(*[_klines(client, "BTCUSDT", tf) for tf in ("15m", "1h", "4h")])
            btc = {"15m": b[0], "1h": b[1], "4h": b[2]}
        others = {}
        for h in [x.upper() for x in (holdings or []) if x.upper() != symbol][:8]:
            try:
                others[h] = btc["1h"] if h == "BTC" else await _klines(client, h + "USDT", "1h", 300)
            except Exception:
                continue
        return {"symbol": symbol, "pair": pair, "quote": quote, "frames": frames, "btc": btc, "others": others}
    finally:
        if own:
            await client.aclose()


def split(df: pd.DataFrame, tf: str, asof_ms: int) -> tuple[pd.DataFrame, dict | None]:
    """(candles closed by asof, the candle that was still open at asof or None)."""
    closed = df[df.t + TFS[tf] <= asof_ms].reset_index(drop=True)
    live = df[(df.t <= asof_ms) & (df.t + TFS[tf] > asof_ms)]
    return closed, (None if live.empty else {k: float(live.iloc[-1][k]) for k in ("t", "o", "h", "l", "c", "v")})


# ---------------- indicators ----------------
def view(df: pd.DataFrame, tf: str):
    """Closed candles of one timeframe -> arrays (stop_limit.prepare) plus the advisor's extra indicators."""
    b = sl.prepare(df)
    c, h, l, v = (pd.Series(x) for x in (b.c, b.h, b.l, b.v))
    b.tf, b.t = tf, df.t.values.astype("int64")
    b.ema20 = c.ewm(span=20, adjust=False).mean().values
    b.atr_rank = (pd.Series(b.atr) / c).rolling(100).rank(pct=True).values
    b.hi20, b.lo20 = h.rolling(20).max().values, l.rolling(20).min().values
    b.don_hi, b.don_lo = h.rolling(20).max().shift(1).values, l.rolling(10).min().shift(1).values
    for n in (20, 50, 200):
        s = pd.Series(getattr(b, f"sma{n}"))
        setattr(b, f"slope{n}", ((s / s.shift(SLOPE_BARS) - 1) * 100).values)
    b.vwap = None
    if tf in ("15m", "1h"):          # anchored to the UTC day
        day = b.t // 86_400_000
        b.vwap = (((h + l + c) / 3 * v).groupby(day).cumsum() / v.groupby(day).cumsum()).values
    return b


def _n(x, nd: int | None = None):
    """JSON-safe number: NaN/None -> None."""
    if x is None:
        return None
    x = float(x)
    if x != x or math.isinf(x):
        return None
    return round(x, nd) if nd is not None else x


def snapshot(b) -> dict:
    i = b.n - 1
    return {"close": _n(b.c[i]), "sma20": _n(b.sma20[i]), "sma50": _n(b.sma50[i]), "sma200": _n(b.sma200[i]),
            "ema20": _n(b.ema20[i]), "rsi14": _n(b.rsi[i], 1), "atr14": _n(b.atr[i]),
            "atr_pct": _n(b.atr[i] / b.c[i] * 100, 2), "atr_percentile": _n(b.atr_rank[i] * 100, 0),
            "volume_ma20": _n(b.vma20[i]), "volume_ratio": _n(b.v[i] / b.vma20[i], 2) if b.vma20[i] > 0 else None,
            "vwap": None if b.vwap is None else _n(b.vwap[i]), "high20": _n(b.hi20[i]), "low20": _n(b.lo20[i]),
            "donchian_high20": _n(b.don_hi[i]), "donchian_low10": _n(b.don_lo[i]),
            "slope_sma20_pct": _n(b.slope20[i], 2), "slope_sma50_pct": _n(b.slope50[i], 2),
            "slope_sma200_pct": _n(b.slope200[i], 2)}


# ---------------- market structure ----------------
def confirmed_swings(b, kind: str) -> np.ndarray:
    """Indices of the swing highs ("H") or lows ("L") that are known at the last candle: K candles have closed after
    each. Neighbouring candles with the same extreme are one swing."""
    idx, arr = (b.ph_idx, b.h) if kind == "H" else (b.pl_idx, b.l)
    out = []
    for j in idx[idx <= b.n - 1 - sl.K]:
        if not (out and j - out[-1] <= sl.K and arr[j] == arr[out[-1]]):
            out.append(int(j))
    return np.array(out, dtype=int)


def trend_state(b) -> dict:
    """One of five states from the averages AND the swing structure, with the reasons in plain words."""
    i, tf = b.n - 1, b.tf
    c, s20, s50, s200, slope = b.c[i], b.sma20[i], b.sma50[i], b.sma200[i], b.slope50[i]
    reasons = [f"{tf} kapanış SMA20 {'üstünde' if c > s20 else 'altında'}",
               f"{tf} SMA20 {'>' if s20 > s50 else '<'} SMA50",
               f"{tf} SMA50 eğimi {'pozitif' if slope > 0 else 'negatif'} (%{slope:+.2f})" if slope == slope else
               f"{tf} SMA50 eğimi hesaplanamadı"]
    ma = 1 if c > s20 > s50 and slope > 0 else -1 if c < s20 < s50 and slope < 0 else 0
    hi, lo = b.h[confirmed_swings(b, "H")][-2:], b.l[confirmed_swings(b, "L")][-2:]
    st = 0
    if len(hi) == 2 and len(lo) == 2:
        st = 1 if hi[1] > hi[0] and lo[1] > lo[0] else -1 if hi[1] < hi[0] and lo[1] < lo[0] else 0
        reasons.append(f"{tf} son iki swing tepe {'yükseliyor' if hi[1] > hi[0] else 'düşüyor'}, "
                       f"son iki swing dip {'yükseliyor' if lo[1] > lo[0] else 'düşüyor'}")
    else:
        reasons.append(f"{tf} swing yapısı için yeterli dönüş yok")
    above = None if s200 != s200 else bool(c > s200)
    reasons.append(f"{tf} SMA200 yok (veri kısa)" if above is None else
                   f"{tf} fiyat SMA200 {'üstünde' if above else 'altında'}")
    total = ma + st
    state = ("STRONG_UPTREND" if total == 2 and above else "UPTREND" if total >= 1 else
             "STRONG_DOWNTREND" if total == -2 and above is False else "DOWNTREND" if total <= -1 else "RANGE")
    return {"state": state, "tr": TREND_TR[state], "reasons": reasons, "averages": ma, "structure": st, "above_sma200": above}


def swing_points(b) -> list[dict]:
    """Confirmed swings of one timeframe that the price reacted to (it moved REACTION_ATR away within the K
    confirming candles), each with the moment it became known (K candles after it formed)."""
    i, step, out = b.n - 1, TFS[b.tf], []
    for kind, arr in (("H", b.h), ("L", b.l)):
        idx = confirmed_swings(b, kind)
        for j in idx[idx >= i - LOOKBACK]:
            after = slice(j + 1, j + sl.K + 1)
            move = b.h[j] - b.l[after].min() if kind == "H" else b.h[after].max() - b.l[j]
            if not move >= REACTION_ATR * b.atr[j]:
                continue
            out.append({"price": float(arr[j]), "t": int(b.t[j]), "known": int(b.t[j + sl.K]) + step, "tf": {b.tf},
                        "kind": kind, "vol": float(b.v[j] / b.vma20[j]) if b.vma20[j] > 0 else math.nan})
    return out


def levels(views: dict, price: float, now_ms: int) -> tuple[list[dict], list[dict]]:
    """(supports, resistances), nearest first: the 1h and 4h swings clustered by the 1h ATR.

    A level's strength is not a score: it is its parts (touch count, volume on the reactions, recency, timeframes).
    A swing seen on several timeframes is one touch. 15m swings never make a level; one that falls inside an
    existing zone counts as another touch of it.
    """
    atr = views["1h"].atr[-1]
    pts: dict[tuple, dict] = {}
    for tf in ("4h", "1h"):
        for p in swing_points(views[tf]) if tf in views else []:
            q = pts.get((p["kind"], p["price"]))
            if q:
                q["tf"] |= p["tf"]
                q["known"] = min(q["known"], p["known"])
            else:
                pts[(p["kind"], p["price"])] = p
    tol = max(sl.CLUSTER_ATR * atr, sl.CLUSTER_PCT * price)
    groups, base = [], None
    for p in sorted(pts.values(), key=lambda x: x["price"]):
        if base is None or p["price"] - base > tol:
            groups.append([p])
            base = p["price"]
        else:
            groups[-1].append(p)
    minor = [p for p in swing_points(views["15m"]) if (p["kind"], p["price"]) not in pts]
    sup, res = [], []
    for g in groups:
        lo, hi = g[0]["price"], g[-1]["price"]
        g = g + [p for p in minor if lo <= p["price"] <= hi]
        tfs = set().union(*[p["tf"] for p in g])
        vols = [p["vol"] for p in g if p["vol"] == p["vol"]]
        age = (now_ms - max(p["t"] for p in g)) / TFS["1h"]
        is_res = hi >= price          # inside the zone counts as resistance: it has to be closed above
        lvl = {"price": hi if is_res else lo, "zone": [lo, hi], "touch_count": len(g), "age_bars": round(age),
               "distance_pct": round((max(lo, price) if is_res else hi) / price * 100 - 100, 2),
               "strength": {"touch_count": len(g), "volume_on_reactions": round(float(np.mean(vols)), 2) if vols else None,
                            "recency": f"son temas {age:.0f} saat önce", "timeframe": sorted(tfs, key=list(TFS).index)},
               "highs": sum(p["kind"] == "H" for p in g), "known": min(p["known"] for p in g)}
        (res if is_res else sup).append(lvl)
    return sup[::-1], res


def main_level(lvls: list[dict]) -> dict | None:
    """The nearest level with at least two touches; a single-touch level only when there is no other."""
    return next((x for x in lvls if x["touch_count"] >= 2), lvls[0] if lvls else None)


def level_state(c, h, lo: float, top: float, start: int, live: dict | None = None) -> tuple[str, int | None]:
    """The breakout state machine of one level (zone lo..top) over the closed candles from `start` on:

        NONE <-> TESTING        a candle's high reaches the zone without a close above it
        -> CONFIRMED            a candle CLOSES above the top
        -> FAILED_BREAKOUT      a later candle closes back at or under the top
        -> RECLAIM_TESTING      after failing, the price left the zone and a later candle's high reaches it again
        -> CONFIRMED            ...and closes above the top (reclaimed)
    An open candle (`live`) can move NONE to TESTING and FAILED_BREAKOUT to RECLAIM_TESTING; it never confirms.
    A price that was already above the level when the window starts did not break out: falling under it is not a
    failed breakout. Returns (state, the last candle that closed above the top after coming from under it)."""
    state, last_above, away, came_from_below = "NONE", None, False, False
    for t in range(start, len(c)):
        if c[t] > top:
            if came_from_below:
                state, last_above, away = "CONFIRMED", t, False
        else:
            came_from_below = True
            if state == "CONFIRMED":
                state = "FAILED_BREAKOUT"
            elif state in ("FAILED_BREAKOUT", "RECLAIM_TESTING"):
                away = away or h[t] < lo
                state = "RECLAIM_TESTING" if away and h[t] >= lo else "FAILED_BREAKOUT"
            else:
                state = "TESTING" if h[t] >= lo else "NONE"
    if live is not None and live["h"] >= lo:
        state = "TESTING" if state == "NONE" else "RECLAIM_TESTING" if state == "FAILED_BREAKOUT" and away else state
    return state, last_above


def find_breakout(b15, sup: list[dict], res: list[dict], atr1h: float, live: dict | None) -> dict:
    """Where the price stands against its levels, from CLOSED 15m candles. An open candle can only be TESTING."""
    i, c, step = b15.n - 1, b15.c, TFS["15m"]

    def candle(t):
        rng = b15.h[t] - b15.l[t]
        return {"volume_ratio": _n(b15.v[t] / b15.vma20[t], 2) if b15.vma20[t] > 0 else None,
                "body_atr": _n(abs(b15.c[t] - b15.o[t]) / b15.atr[t], 2),
                "upper_wick_ratio": _n((b15.h[t] - max(b15.o[t], b15.c[t])) / rng, 2) if rng > 0 else 0.0,
                "rsi": _n(b15.rsi[t], 1), "time": _iso(int(b15.t[t]) + step)}

    best = None
    for lvl in sup:                                   # a level the price is above now: was it crossed recently?
        top = lvl["zone"][1]
        if not lvl["highs"]:
            continue
        for t in range(i, max(i - RETEST_WINDOW, 1), -1):
            if c[t - 1] <= top < c[t]:
                if lvl["known"] <= b15.t[t] and (best is None or t > best["bar"]):
                    best = {"bar": t, "level": lvl}
                break
    room = (res[0]["zone"][0] - c[i]) / atr1h if res else math.inf
    if best and room >= ROOM_ATR:
        t, lvl = best["bar"], best["level"]
        top = lvl["zone"][1]
        q = candle(t)
        # a retest: after the breakout the price moved at least half an ATR away, then came back down to the level
        peak = t + int(np.argmax(b15.h[t:i + 1]))
        back = bool(b15.h[peak] - top >= 0.5 * atr1h and peak < i and b15.l[peak + 1:i + 1].min() <= top + 0.25 * atr1h)
        return {"status": "CONFIRMED", "level": top, "zone": lvl["zone"], "bars_ago": i - t, "fresh": i - t < BREAKOUT_WINDOW,
                "quality_ok": bool((q["volume_ratio"] or 0) >= 1.0 and q["upper_wick_ratio"] < 0.5), "candle": q,
                "retested": back,
                "distance_atr": _n((c[i] - top) / atr1h, 2), "touch_count": lvl["touch_count"],
                "room_atr": None if room == math.inf else _n(room, 2)}
    def machine(lvl):
        # only candles after the level became known count, and only the last FAILED_WINDOW of them
        start = max(i - FAILED_WINDOW, int(np.searchsorted(b15.t, lvl["known"])), 0)
        return level_state(c, b15.h, lvl["zone"][0], lvl["zone"][1], start, live)

    for lvl in res:                                   # closed above it a short while ago and fell back under it
        state, above = machine(lvl)
        if state in ("FAILED_BREAKOUT", "RECLAIM_TESTING"):
            return {"status": state, "level": lvl["zone"][1], "zone": lvl["zone"], "bars_ago": i - above,
                    "candle": candle(above), "touch_count": lvl["touch_count"],
                    "open_candle_above": bool(live and live["c"] > lvl["zone"][1])}
    m = main_level(res)
    if m and machine(m)[0] == "TESTING":
        return {"status": "TESTING", "level": m["zone"][1], "zone": m["zone"], "touch_count": m["touch_count"],
                "open_candle_above": bool(live and live["c"] > m["zone"][1]), "candle": candle(i)}
    return {"status": "NONE", "level": m["price"] if m else None, "zone": m["zone"] if m else None,
            "touch_count": m["touch_count"] if m else None}


# ---------------- risk ----------------
def technical_stop(entry: float, atr: float, candidates: list[tuple[float, str]], below: float | None = None) -> dict:
    """Stop from the first candidate (in priority order) that is 1-3 ATR under the entry, padded 0.15 ATR; the 1.5 ATR
    stop when none fits. A nearer candidate that was skipped is reported: a stop there sits inside normal movement.
    below: the invalidation level (and so the stop) may not be above this, e.g. the bottom of a retest zone."""
    skipped = [(lvl, name) for lvl, name in candidates if 0 < entry - lvl < sl.MIN_STRUCT_ATR * atr]
    fit = next(((lvl, name) for lvl, name in candidates
                if sl.MIN_STRUCT_ATR * atr <= entry - lvl <= sl.MAX_STRUCT_ATR * atr), None)
    stop, invalid, text = sl.stop_level(entry, atr, fit[0] if fit else math.nan, math.nan, math.nan, PARAMS)
    source = f"{fit[1]} − {PARAMS.stop_atr_pad:g} ATR" if fit else f"{sl.ATR_STOP:g} ATR (1-3 ATR arasında teknik seviye yok)"
    if below is not None and invalid > below:
        invalid, stop, source = below, min(stop, below), source + "; bölgenin altına indirildi"
    out = {"technical_stop": stop, "invalid_level": invalid, "distance_pct": round((entry - stop) / entry * 100, 2),
           "distance_atr": round((entry - stop) / atr, 2), "source": source}
    if skipped:
        lvl, name = skipped[0]
        out["too_tight"] = {"level": lvl, "name": name, "distance_atr": round((entry - lvl) / atr, 2)}
    return out


def coin_class(symbol: str) -> str:
    return "MAJOR" if symbol in MAJORS else "MEME" if symbol in MEMES else "ALT"


def size_position(portfolio: float, entry: float, stop: float, symbol: str, daily_atr_pct: float,
                  risk_pct: float = RISK_PCT) -> dict:
    """USDT to put in so that the stop costs risk_pct of the portfolio, capped by the coin's class."""
    cls = coin_class(symbol)
    volatile, calm = MAX_POSITION[cls]
    cap = volatile if daily_atr_pct >= HIGH_VOL_ATR_PCT else calm
    risk = portfolio * risk_pct
    wanted = risk / ((entry - stop) / entry)
    amount = min(wanted, portfolio * cap)
    return {"portfolio_usdt": portfolio, "risk_usdt": round(risk, 2), "position_usdt": round(amount, 2),
            "quantity": amount / entry, "portfolio_share_pct": round(amount / portfolio * 100, 1),
            "loss_at_stop_usdt": round(amount * (entry - stop) / entry, 2), "coin_class": cls, "cap_pct": cap * 100,
            "capped": wanted > portfolio * cap, "below_exchange_minimum": amount < MIN_ORDER_USDT}


def correlations(frame: pd.DataFrame, others: dict[str, pd.DataFrame], asof_ms: int) -> dict:
    """Correlation of 1h returns (last 200 closed candles) with each holding."""
    base = split(frame, "1h", asof_ms)[0].set_index("t").c.pct_change()
    out = {}
    for sym, df in others.items():
        r = split(df, "1h", asof_ms)[0].set_index("t").c.pct_change()
        j = pd.concat([base, r], axis=1, join="inner").dropna().tail(200)
        if len(j) >= 50:
            out[sym] = round(float(j.iloc[:, 0].corr(j.iloc[:, 1])), 2)
    return out


# ---------------- advisor ----------------
def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _p(x) -> str:
    if x is None or x != x:
        return "—"
    a = abs(x)
    if a >= 10000:
        return f"{x:,.0f}"
    return f"{x:.2f}" if a >= 10 else f"{x:.3f}" if a >= 1 else f"{x:.{3 - math.floor(math.log10(a))}f}" if a > 0 else "0"


def _zone(z) -> str:
    return _p(z[0]) if z[1] - z[0] < 1e-12 or _p(z[0]) == _p(z[1]) else f"{_p(z[0])}-{_p(z[1])}"


def _research_line(d1) -> str | None:
    """The tested daily trend rule's own 0/1, as one line of evidence (it never decides here)."""
    try:
        n = d1.n
        if n < 210:
            return None
        frame = pd.DataFrame({"c": d1.c, "hi20": d1.don_hi, "lo10": d1.don_lo, "sma200": d1.sma200})
        inside = bool(_load("strategies").trend_donchian(frame)[-1])
        return (f"Günlük trend kuralı (Donchian 20/10 + SMA200, durumu ARAŞTIRMA): {'içeride' if inside else 'dışarıda'} "
                "— bilgi; tek başına alım sebebi değil")
    except Exception:
        return None


def setup_class(decision: str, scenario: str, reason: str | None) -> str:
    """What kind of setup a report is, for the research log (LOW_RR does not change the class)."""
    if scenario == "POSITION":
        return "POSITION"
    if decision == "BUY_SETUP":
        return "PULLBACK_SETUP" if scenario == "PULLBACK" else "READY_TO_WATCH"
    if decision in ("WAIT_FOR_BREAKOUT", "WAIT_FOR_RETEST", "AVOID"):
        return decision
    return "PULLBACK_SETUP" if reason == "PULLBACK_WAIT" else "NO_SETUP"


def setup_identity(symbol: str, decision: str, scenario: str, reason: str | None, level: float | None,
                   candle_time: str | None, as_of_ms: int) -> dict:
    """A deterministic id for "the same setup": seen again on the next scan it keeps its id; a new technical level
    (or a new breakout candle) makes a new one.

    breakout waiting   symbol, BREAKOUT, the resistance
    breakout / retest  symbol, the entry type, the broken resistance, the 15m candle that closed above it
    pullback           symbol, PULLBACK, the UTC day (the averages it rests on move every hour)
    nothing to do      symbol, the decision, its reason, the UTC day: one comparison record a day, not a setup
    """
    cls = setup_class(decision, scenario, reason)
    day = datetime.fromtimestamp(as_of_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    lvl = None if level is None else f"{level:.5g}"
    if cls in ("NO_SETUP", "AVOID", "POSITION"):
        parts = [symbol, decision, reason or "-", day]
    elif cls == "PULLBACK_SETUP":
        parts = [symbol, "PULLBACK", day]
    elif cls == "WAIT_FOR_BREAKOUT":
        parts = [symbol, "BREAKOUT", lvl]
    else:
        parts = [symbol, scenario, lvl, candle_time]
    key = "|".join(str(p) for p in parts)
    return {"setup_id": hashlib.sha1(key.encode()).hexdigest()[:16], "setup_key": key, "setup_class": cls}


PLAN_FIELDS = {"STOP_LIMIT": ("trigger_price", "limit_price", "initial_stop", "invalid_level"),
               "RETEST_WAIT": ("retest_zone_low", "retest_zone_high", "retest_confirmation_price", "initial_stop",
                               "invalid_level")}
ENTRY_FIELDS = ("entry", "limit_price", "initial_stop", "invalid_level")       # a setup that is ready now


def plan_missing(plan: dict) -> list[str]:
    """What keeps a plan from being actionable: a required level that is absent, or levels that contradict each other."""
    out = [k for k in PLAN_FIELDS.get(plan.get("type"), ENTRY_FIELDS) if _n(plan.get(k)) is None]
    if out:
        return out
    entry, stop, invalid = plan["entry"], plan["initial_stop"], plan["invalid_level"]
    if not stop < entry:
        out.append("stop girişin altında değil")
    if not stop <= invalid < entry:
        out.append("geçersizlik seviyesi stop ile giriş arasında değil")
    if plan.get("type") == "STOP_LIMIT" and not plan["trigger_price"] <= plan["limit_price"]:
        out.append("limit tetiğin altında")
    if plan.get("type") == "RETEST_WAIT":
        if not invalid < plan["retest_zone_low"]:
            out.append("geçersizlik geri test bölgesinin altında değil")
        if not plan["retest_zone_low"] <= plan["retest_confirmation_price"]:
            out.append("teyit fiyatı bölgenin altında")
    return out


def analyze(data: dict, portfolio_usdt: float | None = None, position_usdt: float | None = None,
            average_price: float | None = None, asof_ms: int | None = None) -> dict:
    """The report for data = fetch(...). Pure: no network, no clock unless asof_ms is None (then: now)."""
    live_mode = asof_ms is None
    asof = int(time.time() * 1000) if live_mode else int(asof_ms)
    symbol, pair = data["symbol"], data["pair"]
    views, live15, counts = {}, None, {}
    for tf in TFS:
        closed, live = split(data["frames"][tf], tf, asof)
        counts[tf] = len(closed)
        if len(closed) < NEED_BARS[tf]:
            raise ValueError(f"{pair} {tf}: {len(closed)} kapanmış mum var, en az {NEED_BARS[tf]} gerekli (parite çok yeni)")
        if len(closed) >= TREND_BARS:        # a timeframe without enough candles takes no part at all
            views[tf] = view(closed, tf)
        if tf == "15m":
            live15 = live if live_mode else None     # a replay never sees inside the open candle
    insufficient = [tf for tf in TFS if tf not in views]
    b15, b1, b4, d1 = views["15m"], views["1h"], views.get("4h"), views.get("1d")
    close15 = float(b15.c[-1])
    price = float(live15["c"]) if live15 else close15
    atr = float(b1.atr[-1])
    missing = {"state": "INSUFFICIENT_HISTORY", "tr": TREND_TR["INSUFFICIENT_HISTORY"], "averages": 0, "structure": 0,
               "above_sma200": None}
    trend = {tf: trend_state(views[tf]) if tf in views else
             {**missing, "reasons": [f"{tf}: {counts[tf]} kapanmış mum var, trend için {TREND_BARS} gerekir"]} for tf in TFS}
    sup, res = levels(views, close15, asof)
    bo = find_breakout(b15, sup, res, atr, live15)
    R, S = main_level(res), (sup[0] if sup else None)
    if bo["status"] == "RECLAIM_TESTING":            # the level being re-tested is the one to plan against
        R = next(x for x in res if x["zone"] == bo["zone"])
    h1, h4, m15 = trend["1h"]["state"], trend["4h"]["state"], trend["15m"]["state"]

    roles = {"4h": "trend filtresi", "15m": "giriş zamanlaması"}
    evidence = [f"1h (ana yön): {trend['1h']['tr']} — " + "; ".join(trend["1h"]["reasons"][:2] + trend["1h"]["reasons"][3:4])]
    evidence += [f"{tf} ({role}): {trend[tf]['tr']}" for tf, role in roles.items() if tf in views]
    if d1 is not None:
        evidence.append(f"1d (genel bağlam): {trend['1d']['tr']}; {trend['1d']['reasons'][-1]}")
    if R:
        evidence.append(f"{_zone(R['zone'])} direnci {R['touch_count']} kez tepki almış "
                        f"({'+'.join(R['strength']['timeframe'])}), " + (f"fiyatın %{R['distance_pct']:g} üstünde" if R["distance_pct"] > 0
                                                              else "fiyat bölgenin içinde"))
    if S:
        evidence.append(f"{_zone(S['zone'])} desteği {S['touch_count']} temas, fiyatın %{abs(S['distance_pct']):g} altında")
    s15 = snapshot(b15)
    evidence.append(f"RSI {b1.rsi[-1]:.0f} (1h), {b15.rsi[-1]:.0f} (15m)"
                    + ("; 1h aşırı alım bölgesinde" if b1.rsi[-1] > 75 else ""))
    evidence.append(f"Son kapanan 15m mum hacmi 20 mum ortalamasının {s15['volume_ratio']}x'i"
                    if s15["volume_ratio"] is not None else "15m hacim ortalaması hesaplanamadı")
    warnings: list[dict] = []

    def warn(code, text):
        warnings.append({"code": code, "text": text})

    if insufficient:
        warn("INSUFFICIENT_HISTORY", ", ".join(f"{tf} ({counts[tf]} mum)" for tf in insufficient)
             + f": trend için en az {TREND_BARS} kapanmış mum gerekir; bu zaman dilimleri karara ve kanıta katılmadı"
             + (" (4h trend filtresi yok)" if "4h" in insufficient else ""))
    if data["quote"] == "BTC":
        warn("QUOTE_BTC_WARNING", f"{pair}: USDT/USDC/FDUSD paritesi yok, analiz BTC paritesiyle yapıldı. Fiyatlar BTC "
                                  "cinsinden; USDT pozisyon büyüklüğü üretilmez.")

    # BTC regime: an altcoin is never judged without it
    btc = None
    if symbol != "BTC":
        bt = {tf: trend_state(view(split(data["btc"][tf], tf, asof)[0], tf)) for tf in ("15m", "1h", "4h")}
        risk = bt["1h"]["state"] == "STRONG_DOWNTREND" or (bt["1h"]["state"] in DOWN and bt["15m"]["state"] in DOWN)
        btc = {"trend": {tf: x["state"] for tf, x in bt.items()}, "market_risk": bool(risk)}
        evidence.append("BTC: " + ", ".join(f"{tf} {x['tr']}" for tf, x in bt.items()))
        if risk:
            warn("MARKET_RISK", "BTC kısa vadede düşüş yapısında (15m ve 1h): altcoin güçlü görünse de yeni giriş riskli")
    market_risk = bool(btc and btc["market_risk"])

    corr = correlations(data["frames"]["1h"], data.get("others") or {}, asof)
    high = {k: v for k, v in corr.items() if v >= HIGH_CORR}
    alts = [k for k in (data.get("others") or {}) if k not in MAJORS]
    if len(high) >= 2 or (symbol not in MAJORS and len(alts) >= 5):
        warn("PORTFOLIO_CONCENTRATION",
             (f"Portföydeki {', '.join(f'{k} ({v:g})' for k, v in high.items())} ile birlikte hareket ediyor. " if high else "")
             + (f"Portföyde zaten {len(alts)} altcoin var. " if len(alts) >= 5 else "") + "Yeni pozisyon aynı riski büyütür.")
    line = _research_line(d1) if d1 is not None else None

    # ---- decision for a new position ----
    decision, scenario, invalid_if, recheck_if, plan, stop_info, scenarios = "NO_SETUP", "NO_TRADE", None, None, None, None, []
    retest = pullback = None
    setup_level = setup_candle = None      # what makes this setup the same setup on the next scan (setup_id)
    reason = None            # REASON_TR code: why there is nothing to do (set whenever no plan is offered)
    recheck_price = None     # the level whose close would change the picture (the scan sorts by the distance to it)
    res_above = lambda lim: [x for x in res if x["zone"][0] > lim]

    def rr(entry, stop, lim):
        ups = res_above(lim)
        vals = [round((x["zone"][0] - entry) / (entry - stop), 2) for x in ups[:2]]
        return (vals + [None, None])[:2], [x["zone"][0] for x in ups[:2]]

    def make_plan(kind, entry, trigger, limit, cands, reason, below=None):
        st = technical_stop(entry, atr, cands, below)
        (rr1, rr2), tps = rr(entry, st["technical_stop"], limit if limit is not None else entry)
        return st, {"type": kind, "entry": entry, "trigger_price": trigger, "limit_price": limit,
                    "initial_stop": st["technical_stop"], "invalid_level": st["invalid_level"],
                    "risk_per_unit": entry - st["technical_stop"], "RR_to_resistance_1": rr1, "RR_to_resistance_2": rr2,
                    "resistance_1": tps[0] if tps else None, "resistance_2": tps[1] if len(tps) > 1 else None,
                    "reason": reason}

    swing_low = sl.swing_low_at(b1, b1.n - 1)
    support_cands = [(x["zone"][0], f"{_zone(x['zone'])} desteği") for x in sup]
    limit_now = close15 + max(close15 * PARAMS.limit_pct, atr * PARAMS.limit_atr)

    if h1 in DOWN or h4 == "STRONG_DOWNTREND":
        decision, reason = "AVOID", "DOWNTREND_1H" if h1 in DOWN else "DOWNTREND_4H"
        evidence.append("1h ana yön aşağı: yükseliş kurulumu aranmaz" if h1 in DOWN else
                        "4h güçlü düşüşte: 15m/1h kırılımları güvenilir sayılmaz")
        recheck_if = (f"{_p(R['price'])} üzerinde 1h kapanış ve yükselen dip oluşursa" if R else
                      "1h kapanış SMA20 üstüne çıkar ve dipler yükselirse")
        recheck_price = R["price"] if R else None
    elif bo["status"] == "CONFIRMED":
        recheck_price = bo["level"]
        setup_level, setup_candle = bo["level"], bo["candle"]["time"]
        lvl, zone_lo = bo["level"], bo["zone"][0]
        q = bo["candle"]
        evidence.append(f"{_p(lvl)} direnci {bo['bars_ago']} mum önce 15m kapanışla kırıldı: hacim {q['volume_ratio']}x, "
                        f"gövde {q['body_atr']} ATR (15m), üst fitil %{(q['upper_wick_ratio'] or 0) * 100:.0f}")
        near = bo["distance_atr"] <= NEAR_ATR
        cands = [(zone_lo, f"kırılan {_zone(bo['zone'])} bölgesi"), (swing_low, "son 1h swing dip"), *support_cands]
        bullish = b15.c[-1] > b15.o[-1]
        if bo["fresh"] and bo["quality_ok"] and near:
            scenario = "BREAKOUT"
        elif bo["retested"] and near and bullish:
            scenario = "RETEST"
            evidence.append(f"Fiyat kırılan seviyeye geri çekildi ve 15m kapanışla üstünde tutundu ({_p(lvl)})")
        if scenario != "NO_TRADE":
            decision = "BUY_SETUP"
            stop_info, plan = make_plan(scenario, close15, None, limit_now, cands,
                                        f"{_p(lvl)} üstünde kapanış geldi; giriş {_p(limit_now)} üstünde kovalanmaz.")
            invalid_if = f"{_p(zone_lo)} altında 15m kapanış (kırılım geri alınır)"
            recheck_if = (f"{_p(plan['resistance_1'])} direncine yaklaşınca" if plan["resistance_1"] else
                          "fiyat 1R ilerleyince stopu gözden geçir")
        else:
            decision, scenario = "WAIT_FOR_RETEST", "RETEST"
            why = ("kırılım mumunda hacim/gövde teyidi zayıf" if bo["fresh"] and not bo["quality_ok"] else
                   f"fiyat seviyeden {bo['distance_atr']} ATR uzaklaştı" if not near else "geri test henüz tutunma göstermedi")
            evidence.append(f"Giriş kovalanmıyor: {why}")
            # the retest: the price comes back to the broken resistance, and a 15m candle that reached the zone closes
            # above the level again. Nothing is bought under the zone; the stop goes under the zone AND the swing low.
            zone_top = lvl + RETEST_ATR * atr
            stop_info, plan = make_plan(
                "RETEST_WAIT", lvl, None, lvl + max(lvl * PARAMS.limit_pct, atr * PARAMS.limit_atr),
                cands[1:],        # the zone itself is not a stop candidate here: `below` already puts the stop under it
                f"{_p(lvl)} direnci kapanışla kırıldı. Fiyat {_p(zone_lo)}-{_p(zone_top)} bölgesine geri çekilip bir 15m mum "
                f"{_p(lvl)} üstünde kapanırsa geri test teyit olur; bölgenin altında giriş yapılmaz.",
                below=zone_lo - PARAMS.stop_atr_pad * atr)
            retest = {"broken_resistance": lvl, "retest_zone_low": zone_lo, "retest_zone_high": zone_top,
                      "retest_confirmation_price": lvl, "retest_stop": plan["initial_stop"],
                      "retest_invalidation": plan["invalid_level"],
                      "retest_distance_pct": round(max(close15 - zone_top, 0.0) / close15 * 100, 2)}
            plan.update(retest)
            recheck_price = zone_top
            invalid_if = f"{_p(plan['invalid_level'])} altında 15m kapanış (geri test bölgesi ve altındaki dip kaybedilir)"
            recheck_if = (f"fiyat {_p(zone_lo)}-{_p(zone_top)} bölgesine geri çekilip bir 15m mum {_p(lvl)} üstünde kapanırsa"
                          + (f"; aradaki {_zone(S['zone'])} desteği tutarsa geri test gelmeyebilir"
                             if S and S["zone"][0] > zone_top else ""))
        scenarios.append({"type": scenario, "level": lvl, "status": decision})
    elif bo["status"] == "FAILED_BREAKOUT":
        reason, recheck_price = "FAILED_BREAKOUT", bo["level"]
        evidence.append(f"{_p(bo['level'])} üstünde 15m kapanış geldi ama fiyat geri altına döndü: sahte kırılım "
                        f"({bo['bars_ago']} mum önce)")
        recheck_if = f"{_p(bo['level'])} üzerinde yeniden 15m kapanış, bu kez ortalamanın üstünde hacimle"
        invalid_if = f"{_p(S['price'])} altında 15m kapanış" if S else None
        scenarios.append({"type": "BREAKOUT", "level": bo["level"], "status": "FAILED_BREAKOUT"})
    else:
        # pullback inside an uptrend, at the 1h EMA20 / SMA20
        ema, sma = float(b1.ema20[-1]), float(b1.sma20[-1])
        zone_hi, zone_lo = max(ema, sma), min(ema, sma)
        if h1 in UP and h4 not in DOWN:
            # a pullback comes DOWN to the averages: the price was at least 1 ATR above them, touched them in the last
            # three 1h candles, and has neither broken far below nor already run away again
            touched = (b1.h[-12:-3].max() >= zone_hi + atr and b1.l[-3:].min() <= zone_hi + 0.25 * atr
                       and zone_lo - 0.5 * atr <= close15 <= zone_hi + NEAR_ATR * atr)
            turned = b15.c[-1] > b15.ema20[-1] and b15.c[-1] > b15.h[-2]
            if touched:
                scenarios.append({"type": "PULLBACK", "level": zone_hi, "status": "BUY_SETUP" if turned else "dönüş bekleniyor"})
                pullback = {"entry_zone_low": zone_lo, "entry_zone_high": zone_hi + 0.25 * atr,
                            "confirmation_price": float(max(b15.ema20[-1], b15.h[-2])),
                            "invalidation": zone_lo - 0.5 * atr, "confirmed": bool(turned)}
                evidence.append(f"Yükseliş trendinde fiyat 1h EMA20/SMA20 bölgesine ({_p(zone_lo)}-{_p(zone_hi)}) geri çekildi"
                                + ("; 15m önceki mumun tepesini ve EMA20'yi geçti" if turned else "; 15m dönüş henüz yok"))
                if turned:
                    decision, scenario = "BUY_SETUP", "PULLBACK"
                    cands = [(swing_low, "son 1h swing dip"), *support_cands, (zone_lo, "1h EMA20/SMA20 bölgesi")]
                    stop_info, plan = make_plan("PULLBACK", close15, None, limit_now, cands,
                                                "Trend yönünde düzeltme sonrası 15m dönüş; giriş limitin üstünde kovalanmaz.")
                    invalid_if = f"{_p(plan['invalid_level'])} altında 15m kapanış"
                    recheck_if = f"{_p(plan['resistance_1'])} direncine yaklaşınca" if plan["resistance_1"] else None
                else:
                    reason, recheck_price = "PULLBACK_WAIT", float(max(b15.ema20[-1], b15.h[-1]))
                    recheck_if = f"15m kapanış EMA20 ({_p(float(b15.ema20[-1]))}) ve önceki mumun tepesi üstüne çıkarsa"
                    invalid_if = f"{_p(zone_lo - 0.5 * atr)} altında 1h kapanış (düzeltme derinleşir)"
        if decision == "NO_SETUP" and R and (R["zone"][0] - close15) <= PLAN_ATR * atr:
            decision, scenario, reason = "WAIT_FOR_BREAKOUT", "BREAKOUT", None
            top = recheck_price = setup_level = R["zone"][1]
            trigger, limit = (float(x) for x in sl.entry_order(top, atr, PARAMS))
            cands = [(S["zone"][0], f"{_zone(S['zone'])} desteği")] if S else []
            cands += [(swing_low, "son 1h swing dip"), *support_cands[1:]]
            stop_info, plan = make_plan("STOP_LIMIT", trigger, trigger, limit, cands,
                                        f"{_p(top)} direncinin üstünde kapanış aranıyor. {_p(trigger)} tetik, tek fitillik "
                                        f"kırılımları elemek için direncin %{PARAMS.pct_buffer * 100:g} üstünde; daha büyük "
                                        "tampon geçmiş testte sonucu kötüleştirdi.")
            evidence.append("Kırılım durumu: " + (
                "direnç test ediliyor, kapanış teyidi yok" if bo["status"] == "TESTING" else
                f"önceki kırılım başarısız oldu ({bo['bars_ago']} mum önce), seviye yeniden test ediliyor; teyit için "
                "ortalamanın üstünde hacimle 15m kapanış gerekir" if bo["status"] == "RECLAIM_TESTING" else
                "fiyat direncin altında, kırılım yok"))
            if bo["status"] == "RECLAIM_TESTING":
                warn("FAILED_BEFORE", f"{_p(top)} seviyesinde son {FAILED_WINDOW} mum içinde sahte kırılım oldu")
            if bo.get("open_candle_above"):
                evidence.append("Açık 15m mum direncin üstünde; mum kapanmadan teyit sayılmaz")
            if R["touch_count"] < 2:
                warn("SINGLE_TOUCH", "Direnç tek temasa dayanıyor; kümelenme yok")
            invalid_if = f"{_p(plan['invalid_level'])} altında 15m kapanış"
            recheck_if = f"{_p(top)} üzerinde 15m kapanış" + (f" veya {_p(S['price'])} desteğinin kaybı" if S else "")
            scenarios.append({"type": "BREAKOUT", "level": top, "status": bo["status"]})
        elif decision == "NO_SETUP":
            evidence.append("Yakında planlanabilir bir direnç ya da düzeltme bölgesi yok" if not scenarios else
                            "Kurulum henüz tamamlanmadı")
            if reason is None:
                reason, recheck_price = "NO_LEVEL", (R["price"] if R else ema)
            recheck_if = recheck_if or (f"{_p(R['price'])} direncine yaklaşınca ya da 1h EMA20 ({_p(ema)}) bölgesine "
                                        "geri çekilince" if R else f"1h EMA20 ({_p(ema)}) bölgesine geri çekilince")

    if plan:
        if stop_info.get("too_tight"):
            t = stop_info["too_tight"]
            warn("STOP_TOO_TIGHT", f"En yakın teknik seviye ({t['name']}, {_p(t['level'])}) girişe {t['distance_atr']} ATR "
                                   "uzaklıkta: normal oynaklığın içinde. Stop bir sonraki seviyeye/ATR'ye alındı.")
        if plan["RR_to_resistance_1"] is not None and plan["RR_to_resistance_1"] < LOW_RR and not (
                plan["RR_to_resistance_2"] is not None and plan["RR_to_resistance_2"] < 1.0):
            warn("LOW_RR", ("Kırılım seviyesi yakın ancak üst direnç nedeniyle hedef alanı dar" if plan["type"] == "STOP_LIMIT"
                            else "Üst direnç nedeniyle hedef alanı dar")
                 + f" (ilk direnç {_p(plan['resistance_1'])}, R/R {plan['RR_to_resistance_1']:g}). "
                   "R/R otomatik işlem filtresi değildir; yalnız açıklamayı ve sıralamayı etkiler.")
        rr2 = plan["RR_to_resistance_2"]
        if stop_info["distance_pct"] / 100 > PARAMS.max_risk_pct:
            decision, scenario, plan, reason, retest = "NO_SETUP", "NO_TRADE", None, "STOP_TOO_FAR", None
            evidence.append(f"Stop mesafesi %{stop_info['distance_pct']:g}: olağan dışı geniş, işlem önerilmez")
        elif rr2 is not None and rr2 < 1.0:      # even the second resistance is closer than the stop: no room
            top2 = next(x["zone"][1] for x in res if x["zone"][0] == plan["resistance_2"])
            evidence.append(f"Hedefe yer yok: üstteki iki direnç ({_p(plan['resistance_1'])}, {_p(plan['resistance_2'])}) "
                            f"stop mesafesinden yakın (R/R {plan['RR_to_resistance_1']:g} / {rr2:g})")
            recheck_if, recheck_price = f"{_p(top2)} üzerinde 15m kapanış (üstteki dirençler aşılınca alan açılır)", top2
            decision, scenario, plan, reason, retest = "NO_SETUP", "NO_TRADE", None, "NO_ROOM", None
    if h4 in DOWN and decision in ("BUY_SETUP", "WAIT_FOR_BREAKOUT", "WAIT_FOR_RETEST"):
        warn("HTF_DOWNTREND", "4h düşüş trendinde: 15m/1h kırılımı yüksek güvenli sayılmaz")
    if decision == "BUY_SETUP":
        recheck_price = close15                      # ready now: nothing to wait for

    missing = plan_missing(plan) if plan else []
    if missing:
        warn("PLAN_INCOMPLETE", "Plan eksik ya da tutarsız (" + ", ".join(missing) + "): uygulanabilir sayılmaz")
    actionable = plan is not None and not missing

    # daily volatility decides the position cap; scaled from 4h or 1h when the pair has no daily history yet
    d_atr_pct = (float(d1.atr[-1] / d1.c[-1]) if d1 is not None else float(b4.atr[-1] / b4.c[-1]) * 2.4 if b4 is not None
                 else atr / close15 * 4.9)
    sizing = size_note = None
    if plan:
        if data["quote"] == "BTC":
            size_note = "BTC paritesi: USDT pozisyon büyüklüğü üretilmez."
        elif not portfolio_usdt:
            size_note = "Portföy büyüklüğü bilinmiyor."
        else:
            sizing = size_position(float(portfolio_usdt), plan["entry"], plan["initial_stop"], symbol, d_atr_pct)
    trailing = {"suggested_trailing_atr": TRAIL_ATR, "atr_timeframe": "1h",
                "trailing_distance_pct": round(TRAIL_ATR * atr / price * 100, 2),
                "note": "3 ATR günlük geçmiş testte en iyisiydi; 1 saatlik mumda test edilmedi"}

    # ---- an existing position changes the question ----
    position = None
    if position_usdt and average_price:
        st = technical_stop(price, atr, [(swing_low, "son 1h swing dip"), *support_cands])
        pnl = (price / average_price - 1) * 100
        qty = position_usdt / price
        be = average_price * (1 + 2 * FEE)
        scenario, plan, sizing, scenarios, size_note, reason = "POSITION", None, None, [], None, None
        retest = pullback = None
        actionable = False
        recheck_price = R["price"] if R else None
        if h1 in DOWN:
            action, decision = "REDUCE", "REDUCE_RISK"
            text = (f"1h yapı bozuldu ({trend['1h']['tr']}). Pozisyonu küçült; kalan için {_p(st['technical_stop'])} stop. "
                    + (f"{_p(R['price'])} üzerinde 15m kapanış gelirse görünüm iyileşir." if R else ""))
        elif pnl >= max(3.0, PROFIT_ATR * atr / price * 100):
            action, decision = "PROTECT_PROFIT", "PROTECT_PROFIT"
            floor = max(be, st["technical_stop"], price - TRAIL_ATR * atr)
            st["protect_stop"] = floor
            text = (f"Kâr %{pnl:.1f}. Stopu en az {_p(floor)} seviyesine çek (başa baş {_p(be)}, iz süren {TRAIL_ATR:g} ATR). "
                    + (f"{_p(R['price'])} direncinde tepki gelirse kısmi satış düşün." if R else "Üstte yakın direnç yok."))
        elif pnl < 0:
            action, decision = "EXIT_IF_INVALIDATED", "HOLD"
            text = (f"Şu anda zarar %{abs(pnl):.1f}. 1h yapı henüz bozulmadı ({trend['1h']['tr']}). "
                    f"{_p(st['invalid_level'])} teknik geçersizlik: altında 15m kapanış gelirse çık. "
                    + (f"{_p(R['price'])} üzerinde 15m kapanış gelirse görünüm iyileşir." if R else ""))
        else:
            action, decision = "HOLD", "HOLD"
            text = (f"Kâr %{pnl:.1f}, yapı bozulmadı ({trend['1h']['tr']}). Stop {_p(st['technical_stop'])}; "
                    + (f"ilk direnç {_p(R['price'])}." if R else "üstte yakın direnç yok."))
        if market_risk and action != "REDUCE":
            text += " BTC kısa vadede düşüşte: stopu gevşetme."
        position = {"average_price": average_price, "current_price": price, "position_usdt": position_usdt,
                    "quantity": qty, "unrealized_pnl_pct": round(pnl, 2),
                    "unrealized_pnl_usdt": round(position_usdt - qty * average_price, 2),
                    "technical_stop": st["technical_stop"], "invalid_level": st["invalid_level"],
                    "break_even_level": be, "nearest_resistance": R["price"] if R else None,
                    "protect_stop": st.get("protect_stop"), "action": action, "text": text}
        stop_info = st
        invalid_if = f"{_p(st['invalid_level'])} altında 15m kapanış"
        recheck_if = (f"{_p(R['price'])} üzerinde 15m kapanış" if R else "yeni bir direnç oluşunca") + \
                     f" veya {_p(st['invalid_level'])} seviyesinin kaybı"

    if line:
        evidence.append(line)
    pub = lambda xs: [{k: v for k, v in x.items() if k not in ("highs", "known")} for x in xs[:4]]
    out = {"symbol": symbol, "pair": pair,
            "quote_note": None if data["quote"] == "USDT" else f"USDT paritesi yok; {pair} kullanıldı",
            **setup_identity(symbol, decision, scenario, reason, setup_level, setup_candle, int(b15.t[-1]) + TFS["15m"]),
            "as_of": _iso(int(b15.t[-1]) + TFS["15m"]), "as_of_ms": int(b15.t[-1]) + TFS["15m"], "price": price,
            "price_source": "açık 15m mum; teyit için kullanılmaz" if live15 else "son kapanan 15m mum",
            "last_closed_15m": close15, "decision": decision, "decision_tr": DECISION_TR[decision], "scenario": scenario,
            "scenarios": scenarios, "reason_code": reason, "reason": REASON_TR.get(reason),
            "evidence": evidence, "warnings": warnings, "invalid_if": invalid_if,
            "recheck_if": recheck_if, "recheck_price": _n(recheck_price), "insufficient_history": insufficient,
            "trend": {tf: {k: v for k, v in x.items() if k != "tr"} | {"label": x["tr"]}
                                                for tf, x in trend.items()},
            "timeframe_roles": {"15m": "giriş zamanlaması", "1h": "ana yön / yapı", "4h": "trend filtresi", "1d": "genel bağlam"},
            "indicators": {tf: snapshot(v) for tf, v in views.items()}, "supports": pub(sup), "resistances": pub(res),
            "main_resistance": R["zone"] if R else None, "main_support": S["zone"] if S else None,
            "breakout": {"breakout_status": bo["status"], **{k: v for k, v in bo.items() if k != "status"}},
            "plan": plan, "actionable": actionable, "retest": retest, "pullback": pullback,
            "stop": stop_info, "trailing": trailing, "position_size": sizing,
            "position_size_note": size_note, "btc": btc,
            "correlation": corr, "position": position, "current_candle": live15,
            "underlying_setup": None, "blocked_reason": None, "blocked_plan": None,
            "live": live_mode,                       # False: computed for a given past moment (asof_ms)
            "research_note": RESEARCH_NOTE}
    # outside filters, in this order: they do not erase the technical setup, they keep it from being used
    why = ("BTC_MARKET_RISK" if market_risk else "HTF_DOWNTREND" if h4 in DOWN else
           "PORTFOLIO_CONCENTRATION" if any(w["code"] == "PORTFOLIO_CONCENTRATION" for w in warnings) else
           "INSUFFICIENT_HISTORY" if "4h" in insufficient else None)
    if why and position is None and out["setup_class"] in BLOCKABLE:
        block(out, why)
    return out


def block(rep: dict, reason: str) -> dict:
    """Turn a report with a technical setup into BLOCKED_SETUP. The setup's kind and its plan are kept for the record
    (underlying_setup, blocked_plan); there is no plan to act on and no position size. It gets its own setup_id."""
    reason = reason if reason in BLOCK_TR else "OTHER"
    under = rep["setup_class"]
    key = f"{rep['setup_key']}|BLOCKED|{reason}"
    text = f"{GROUP_TR[under]} kurulumu var ama {BLOCK_TR[reason]}"
    rep["evidence"].append(f"Teknik kurulum var ({under}) ama {BLOCK_TR[reason]}: şimdi kullanılmıyor")
    again = "; ".join(x for x in (BLOCK_RECHECK[reason], rep["recheck_if"]) if x)
    rep.update(decision="BLOCKED_SETUP", decision_tr=DECISION_TR["BLOCKED_SETUP"], underlying_setup=under,
               blocked_reason=reason, blocked_plan=rep["plan"], plan=None, actionable=False, position_size=None,
               position_size_note=None, setup_class="BLOCKED_SETUP", setup_key=key,
               setup_id=hashlib.sha1(key.encode()).hexdigest()[:16], reason_code=reason, reason=text,
               recheck_if=again or None)
    return rep


def format_report(r: dict) -> str:
    """The same report as Turkish text (Telegram / terminal)."""
    t, cur = r["trend"], r["pair"][len(r["symbol"]):]
    lines = [f"{r['symbol']}/{cur} — Kripto Danışman", f"Fiyat: {_p(r['price'])} ({r['price_source']})"]
    if r["quote_note"]:
        lines.append(f"Not: {r['quote_note']}")
    lines += ["", f"Durum: {r['decision_tr']} [{r['decision']}]", ""]
    if r["position"]:
        p = r["position"]
        lines += [f"Pozisyon: ortalama {_p(p['average_price'])}, şimdi {_p(p['current_price'])}, "
                  f"K/Z %{p['unrealized_pnl_pct']:+.2f} ({p['unrealized_pnl_usdt']:+.2f} {cur})",
                  f"Öneri [{p['action']}]: {p['text']}",
                  f"Teknik stop: {_p(p['technical_stop'])} · başa baş: {_p(p['break_even_level'])} · "
                  f"en yakın direnç: {_p(p['nearest_resistance'])}", ""]
    lines.append("Trend: " + " · ".join(f"{tf} {t[tf]['label']}" for tf in TFS))
    res, sup = r["resistances"], r["supports"]
    if res:
        lines.append(f"Ana direnç: {_zone(res[0]['zone'])} ({res[0]['touch_count']} temas, "
                     f"{'+'.join(res[0]['strength']['timeframe'])})")
        if len(res) > 1:
            lines.append("Sonraki direnç: " + " · ".join(_zone(x["zone"]) for x in res[1:3]))
    else:
        lines.append("Direnç: üstte kayıtlı direnç yok")
    lines.append("Destek: " + (" · ".join(_zone(x["zone"]) for x in sup[:3]) if sup else "altta kayıtlı destek yok"))
    lines.append(f"Kırılım durumu: {r['breakout']['breakout_status']}")
    pl, st = r["plan"] or r["blocked_plan"], r["stop"]
    if pl:
        lines.append("")
        if r["blocked_reason"]:
            lines.append(f"ENGELLİ: {r['reason']}. Aşağıdaki teknik plan yalnız bilgi içindir, uygulanmaz:")
        if pl["type"] == "STOP_LIMIT":
            lines += ["Stop-limit alış planı:", f"Tetik: {_p(pl['trigger_price'])}", f"Limit: {_p(pl['limit_price'])}"]
        elif pl["type"] == "RETEST_WAIT":
            lines += ["Geri test planı (henüz giriş yok):", f"Kırılan direnç: {_p(pl['broken_resistance'])}",
                      f"Geri test bölgesi: {_p(pl['retest_zone_low'])}-{_p(pl['retest_zone_high'])} "
                      f"(fiyatın %{pl['retest_distance_pct']:g} altında)",
                      f"Teyit: bölgeye inen bir 15m mumun {_p(pl['retest_confirmation_price'])} üstünde kapanması; "
                      f"giriş en fazla {_p(pl['limit_price'])}"]
        else:
            lines += [f"Giriş planı ({pl['type']}):", f"Giriş: {_p(pl['entry'])} civarı, en fazla {_p(pl['limit_price'])}"]
        lines += [f"Sebep: {pl['reason']}", f"Teknik stop: {_p(pl['initial_stop'])} ({st['source']})",
                  f"Stop mesafesi: %{st['distance_pct']:g} / {st['distance_atr']:g} ATR (1h)",
                  f"Teknik geçersizlik: {_p(pl['invalid_level'])}",
                  "R/R: " + (" / ".join(f"{x:g}" for x in (pl["RR_to_resistance_1"], pl["RR_to_resistance_2"]) if x is not None)
                             or "üstte direnç yok") + (f" (dirençler {_p(pl['resistance_1'])}"
                                                       + (f", {_p(pl['resistance_2'])})" if pl["resistance_2"] else ")")
                                                       if pl["resistance_1"] else "")]
    tr = r["trailing"]
    lines.append(f"İz süren stop: {tr['suggested_trailing_atr']:g} ATR = fiyatın %{tr['trailing_distance_pct']:g}'i "
                 f"({tr['atr_timeframe']} ATR; {tr['note']})")
    s = r["position_size"]
    if s:
        lines.append(f"Pozisyon: portföy {s['portfolio_usdt']:g} {cur} ise yaklaşık {s['position_usdt']:g} {cur} "
                     f"(%{s['portfolio_share_pct']:g}); stop olursa kayıp {s['loss_at_stop_usdt']:g} {cur}"
                     + (f". {s['coin_class']} sınırı %{s['cap_pct']:g} uygulandı" if s["capped"] else "")
                     + (f". Borsa alt sınırının ({MIN_ORDER_USDT:g}) altında" if s["below_exchange_minimum"] else ""))
    elif r["position_size_note"]:
        lines.append(f"Pozisyon: {r['position_size_note']}")
    lines += ["", "Neden:", *[f"- {x}" for x in r["evidence"]]]
    if r["warnings"]:
        lines += ["", "Uyarılar:", *[f"- [{w['code']}] {w['text']}" for w in r["warnings"]]]
    if r["invalid_if"]:
        lines += ["", f"Geçersiz olur: {r['invalid_if']}"]
    if r["recheck_if"]:
        lines.append(f"Tekrar kontrol: {r['recheck_if']}")
    lines += ["", f"Veri: {r['as_of']} kapanışına kadar kapanmış mumlar.", r["research_note"]]
    return "\n".join(lines)


async def advise(symbol: str, portfolio_usdt: float | None = None, position_usdt: float | None = None,
                 average_price: float | None = None, holdings: list[str] | None = None) -> dict:
    """Fetch and analyze: the one call the bot, the CLI and the web API use."""
    return analyze(await fetch(symbol, holdings), portfolio_usdt, position_usdt, average_price)


# ---------------- scan: the same analysis over many coins ----------------
# No new technical rule lives here. Every coin goes through analyze() unchanged; the scan only groups the reports,
# orders them and trims the list. The order is lexicographic: first the tier (how complete and how close the plan
# is), then the tie-breakers, in the order written below. There is no combined score.
# in this order (internal names; the report shows the sentence, not the letter). A plan whose target room is narrow
# (LOW_RR) is never refused: it only ranks under every complete plan that has room.
TIERS = {"A": "plan tam, hedef alanı yeterli ve kontrol seviyesi yakın",
         "C": "geri test planı tam (bölge, teyit, teknik stop), hedef alanı yeterli",
         "D": "düzeltme kurulumu (giriş bölgesi, geçersizlik), hedef alanı yeterli",
         "B": "kırılım planı tam (tetik, limit, teknik stop), hedef alanı yeterli",
         "B_LOW_RR": "plan tam ama hedef alanı dar (LOW_RR)",
         "E": "plan eksik ya da henüz uygulanabilir değil"}
TIER_ORDER = list(TIERS)
TIE_BREAKERS = ["BTC kaynaklı piyasa riski yok", "her zaman diliminde yeterli geçmiş var",
                "1h ve 4h aynı yönde (yükseliş)", "yeniden kontrol seviyesi fiyata yakın", "teknik stop mesafesi makul",
                "hedefe yeterli alan var"]
RANKING = list(TIERS.values()) + TIE_BREAKERS
RETEST_FIELDS = ("broken_resistance", "retest_zone_low", "retest_zone_high", "retest_confirmation_price", "retest_stop",
                 "retest_invalidation", "retest_distance_pct")
LOW_RR_NOTE = "Kırılım seviyesi yakın ancak üst direnç nedeniyle hedef alanı dar."


_meta = {"at": 0.0, "data": None}


async def _get_json(client, path: str, params: dict | None = None, timeout: float = 60):
    last = None
    for base in BASES:
        try:
            r = await client.get(f"{base}{path}", params=params, timeout=timeout) if params else \
                await client.get(f"{base}{path}", timeout=timeout)
        except httpx.HTTPError as e:
            last = e
            continue
        if r.status_code == 200:
            return r.json()
        last = RuntimeError(f"{r.status_code}: {r.text[:120]}")
    raise RuntimeError(f"Binance {path} alınamadı: {last}")


def parse_meta(info: dict) -> dict:
    """exchangeInfo -> {symbol: {base, quote, active, leveraged, equity}}.

    Tokenized stocks are found from the metadata itself: they share one permission signature (the set of trading
    groups allowed to trade them) that no coin has. The signature whose members are almost all named TICKER+"B" and
    that has at least EQUITY_GROUP_MIN members is that group; every symbol carrying it is an equity token, whatever
    its name."""
    out, groups = {}, {}
    for x in info.get("symbols", []):
        perms = {p for group in (x.get("permissionSets") or []) for p in group} | set(x.get("permissions") or [])
        sig = hash(tuple(sorted(p for p in perms if p.startswith("TRD_GRP"))))
        active = x.get("status") == "TRADING" and x.get("isSpotTradingAllowed", True)
        out[x["symbol"]] = {"base": x["baseAsset"], "quote": x["quoteAsset"], "active": active,
                            "leveraged": "LEVERAGED" in perms, "sig": sig, "equity": False}
        if active and perms:
            groups.setdefault(sig, set()).add(x["baseAsset"])
    stock_like = re.compile(r"[A-Z]{1,6}B")
    equity = {sig for sig, bases in groups.items() if len(bases) >= EQUITY_GROUP_MIN
              and sum(bool(stock_like.fullmatch(b)) for b in bases) >= EQUITY_GROUP_SHARE * len(bases)}
    for row in out.values():
        row["equity"] = row.pop("sig") in equity
    return out


async def exchange_meta(client) -> dict | None:
    """Binance's symbol metadata, kept for META_SECONDS. None when it cannot be fetched (names decide then)."""
    if _meta["data"] is not None and time.monotonic() - _meta["at"] < META_SECONDS:
        return _meta["data"]
    try:
        _meta.update(at=time.monotonic(), data=parse_meta(await _get_json(client, "/api/v3/exchangeInfo")))
    except Exception as e:
        log.warning("Exchange metadata unavailable, falling back to names: %s", e)
        return _meta["data"]
    return _meta["data"]


def exclusion(coin: str, ticker: dict, meta_row: dict | None, bases: set[str]) -> str | None:
    """Why a coin is not scanned (an EXCLUDE_TR code), or None. Metadata first; names only for what it cannot say."""
    if not (coin and coin.isascii() and coin.isalnum()):
        return "BAD_NAME"
    if meta_row is not None:
        if meta_row["leveraged"]:
            return "LEVERAGED"
        if meta_row["equity"]:
            return "EQUITY_TOKEN"
        if not meta_row["active"]:
            return "INACTIVE"
    else:   # no metadata: a leveraged token is COIN + UP/DOWN/BULL/BEAR of a coin that itself is listed (JUP is not "J" up)
        m = re.fullmatch(r"(.+?)(UP|DOWN|BULL|BEAR)", coin)
        if m and m.group(1) in bases:
            return "LEVERAGED"
        if coin.endswith("B") and coin[:-1] in KNOWN_STOCKS:
            return "EQUITY_TOKEN"
    for code, names in (("STABLE", STABLES), ("FIAT", FIAT), ("COMMODITY", COMMODITIES), ("WRAPPED", WRAPPED)):
        if coin in names:
            return code
    try:    # pinned to 1.00: a stablecoin by behaviour (a quote stablecoin's own pairs look like this)
        last, hi, lo = float(ticker["lastPrice"]), float(ticker["highPrice"]), float(ticker["lowPrice"])
        if 0.97 <= last <= 1.03 and hi - lo <= 0.01 * last:
            return "STABLE"
    except (KeyError, ValueError, TypeError):
        pass
    if float(ticker.get("quoteVolume") or 0) < MIN_QUOTE_VOLUME:
        return "LOW_VOLUME"
    return None


async def universe(client: httpx.AsyncClient, limit: int = SCAN_LIMIT, with_excluded: bool = False):
    """The most traded real spot coins as (coin, quote), most traded first: one quote per coin (USDT, else USDC, else
    FDUSD). with_excluded: also the coins left out, each with its reason (debug)."""
    rows = await _get_json(client, "/api/v3/ticker/24hr", timeout=30)
    meta = await exchange_meta(client)
    quoted = []
    for x in rows:
        m = meta.get(x["symbol"]) if meta else None
        if m:
            if m["quote"] in SCAN_QUOTES:
                quoted.append((m["base"], m["quote"], x, m))
        else:
            q = next((q for q in SCAN_QUOTES if x["symbol"].endswith(q)), None)
            if q:
                quoted.append((x["symbol"][:-len(q)], q, x, None))
    bases = {coin for coin, _, _, _ in quoted}
    best, excluded = {}, {}
    for coin, q, x, m in quoted:
        why = exclusion(coin, x, m, bases)
        rank = SCAN_QUOTES.index(q)
        if why:
            if coin not in best and (coin not in excluded or rank < excluded[coin][0]):
                excluded[coin] = (rank, {"symbol": coin, "pair": x["symbol"], "reason_code": why, "reason": EXCLUDE_TR[why]})
        elif coin not in best or rank < best[coin][0]:
            best[coin] = (rank, q, float(x.get("quoteVolume") or 0))
            excluded.pop(coin, None)
    ordered = sorted(best.items(), key=lambda kv: -kv[1][2])
    pairs = [(coin, q) for coin, (_, q, _) in (ordered[:limit] if limit else ordered)]
    if not with_excluded:
        return pairs
    return pairs, sorted((v for _, v in excluded.values()), key=lambda v: (v["reason_code"], v["symbol"]))


def group_of(r: dict) -> str:
    d = r["decision"]
    if d == "BLOCKED_SETUP":
        return d                                     # a real setup an outside filter holds back: its own group
    if d == "BUY_SETUP":
        if r["scenario"] == "PULLBACK":
            return "PULLBACK_SETUP"
        # narrow room to the next resistance: not shown as a ready setup, it waits for that resistance to break
        return "WAIT_FOR_BREAKOUT" if any(w["code"] == "LOW_RR" for w in r["warnings"]) else "READY_TO_WATCH"
    if d in ("WAIT_FOR_BREAKOUT", "WAIT_FOR_RETEST", "AVOID"):
        return d
    return "PULLBACK_SETUP" if r["reason_code"] == "PULLBACK_WAIT" else "NO_SETUP"


def scan_row(r: dict, held: bool) -> dict:
    """One coin's report reduced to the scan's columns."""
    plan, st, rt, pb = r["plan"], r["stop"], r["retest"] or {}, r["pullback"] or {}
    codes = [w["code"] for w in r["warnings"]]
    row = {"symbol": r["symbol"], "pair": r["pair"], "current_price": r["price"], "decision": r["decision"],
           "group": group_of(r), "entry_type": "PULLBACK" if r["reason_code"] == "PULLBACK_WAIT" else
           None if r["scenario"] == "NO_TRADE" else r["scenario"],
           "1h_trend": r["trend"]["1h"]["state"], "4h_trend": r["trend"]["4h"]["state"],
           "main_resistance": r["main_resistance"], "main_support": r["main_support"],
           "trigger": plan["trigger_price"] if plan else None, "limit": plan["limit_price"] if plan else None,
           "technical_stop": plan["initial_stop"] if plan else None,
           "invalidation": plan["invalid_level"] if plan else pb.get("invalidation"),
           "stop_distance_pct": st["distance_pct"] if plan else None,
           "RR_to_resistance_1": plan["RR_to_resistance_1"] if plan else None,
           **{k: rt.get(k) for k in RETEST_FIELDS},
           "pullback_zone": [pb["entry_zone_low"], pb["entry_zone_high"]] if pb else None,
           "pullback_confirmation_price": pb.get("confirmation_price"),
           "trailing_atr": r["trailing"]["suggested_trailing_atr"], "trailing_pct": r["trailing"]["trailing_distance_pct"],
           "volume_ratio": r["indicators"]["15m"]["volume_ratio"], "RSI": r["indicators"]["1h"]["rsi14"],
           "ATR": r["indicators"]["1h"]["atr14"],
           "recheck_if": r["recheck_if"], "recheck_price": r["recheck_price"], "invalid_if": r["invalid_if"],
           "warnings": codes, "insufficient_history": r["insufficient_history"],
           "position_size": r["position_size"], "position_size_note": r["position_size_note"],
           "underlying_setup": r["underlying_setup"], "blocked_reason": r["blocked_reason"],
           "reason_code": r["reason_code"], "reason": r["reason"], "held": held, "has_plan": plan is not None,
           "actionable": bool(r["actionable"]), "low_rr": "LOW_RR" in codes}
    row["low_rr_note"] = LOW_RR_NOTE if row["low_rr"] else None
    row["tier"] = tier_of(row)
    rr1 = row["RR_to_resistance_1"]
    room = "Üstte yakın direnç yok." if rr1 is None else "R/R yeterli."
    row["summary"] = {
        "A": f"Plan hazır ve seviye yakın. {room}",
        "C": f"Geri test planı hazır. {room} Retest bölgesine yaklaşırsa yeniden kontrol.",
        "D": "Düzeltme bölgesinde; 15m dönüş teyidi bekleniyor.",
        "B": f"Kırılım planı hazır: tetik, limit ve stop tanımlı. {room}",
        "B_LOW_RR": ("Kırılım seviyesi yakın ancak hedef alanı dar. " if row["group"] == "WAIT_FOR_BREAKOUT" else
                     "Üst direnç nedeniyle hedef alanı dar. ") + "Plan mevcut fakat LOW_RR nedeniyle alt sırada.",
        "E": "Henüz uygulanabilir plan yok; izleme adayı."}[row["tier"]]
    return row


def _distance(row: dict) -> float | None:
    return abs(row["recheck_price"] / row["current_price"] - 1) * 100 if row["recheck_price"] else None


def tier_of(row: dict) -> str:
    """The ranking tier (TIERS, best first). Every tier above B_LOW_RR needs a complete plan WITH room to the target."""
    dist, g = _distance(row), row["group"]
    if row["actionable"] and row["low_rr"]:
        return "B_LOW_RR"
    if row["actionable"] and dist is not None and dist <= NEAR_PCT[0]:
        return "A"
    if g == "WAIT_FOR_RETEST" and row["actionable"] and all(row[k] is not None for k in RETEST_FIELDS):
        return "C"
    if g == "PULLBACK_SETUP" and row["pullback_zone"] and row["invalidation"] is not None:
        return "D"
    if g == "WAIT_FOR_BREAKOUT" and row["actionable"]:
        return "B"
    return "E"


def rank_key(row: dict, order: int) -> tuple[tuple, list[str]]:
    """The scan's order as a tuple (False and small sort first) and the same thing in words: the tier, then the
    tie-breakers in TIE_BREAKERS order. The 1h/4h agreement only decides between setups of the same tier."""
    h1, h4 = row["1h_trend"], row["4h_trend"]
    risk = "MARKET_RISK" in row["warnings"]
    short = bool(row["insufficient_history"])
    align = 0 if h1 in UP and h4 in UP else 2 if h4 in DOWN else 1
    dist = _distance(row)
    bucket = 3 if dist is None else 0 if dist <= NEAR_PCT[0] else 1 if dist <= NEAR_PCT[1] else 2
    stop_ok = row["stop_distance_pct"] is not None and row["stop_distance_pct"] <= STOP_OK_PCT
    rr1 = row["RR_to_resistance_1"]
    room = row["has_plan"] and (rr1 is None or rr1 >= LOW_RR)
    words = [TIERS[row["tier"]],
             "BTC riski var" if risk else "BTC riski yok",
             "geçmiş eksik (" + ", ".join(row["insufficient_history"]) + ")" if short else "veri yeterli",
             {0: "1h ve 4h yükselişte", 1: f"1h {TREND_TR[h1]}, 4h {TREND_TR[h4]}: yön uyumu tam değil",
              2: f"1h {TREND_TR[h1]}, 4h {TREND_TR[h4]}: ters"}[align],
             "kontrol seviyesi belirsiz" if dist is None else
             f"kontrol seviyesi %{dist:.1f} uzakta ({('yakın', 'orta', 'uzak')[bucket]})",
             "stop yok" if row["stop_distance_pct"] is None else
             f"stop %{row['stop_distance_pct']:g} ({'makul' if stop_ok else 'uzak'})"]
    return (TIER_ORDER.index(row["tier"]), row["low_rr"], risk, short, align, bucket, not stop_ok, not room,
            999.0 if dist is None else dist, order), words


def build_scan(reports: list[dict], failed: list[dict], closes: dict[str, pd.Series], holdings: list[str],
               portfolio_usdt: float | None) -> dict:
    """reports: analyze() results in scan order (holdings first, then by traded volume). Pure."""
    rows = [scan_row(r, r["symbol"] in holdings) for r in reports]
    rets = pd.DataFrame({k: v.pct_change() for k, v in closes.items()}).tail(200)
    cm = rets.corr(min_periods=50) if len(rets.columns) else pd.DataFrame()

    def corr(a, b):
        if a not in cm or b not in cm:
            return None
        v = cm.at[a, b]
        return None if v != v else round(float(v), 2)

    candidates = []
    for order, row in enumerate(rows):
        if row["group"] in GROUPS[:4]:
            key, words = rank_key(row, order)
            row["rank_reasons"] = words
            candidates.append((key, row))
    picked, skipped = [], []
    for _, row in sorted(candidates, key=lambda x: x[0]):
        others = [s for s in [p["symbol"] for p in picked] + holdings if s != row["symbol"] and s not in MAJORS]
        partners = [s for s in dict.fromkeys(others) if (corr(row["symbol"], s) or 0) >= HIGH_CORR]
        row["moves_with"] = [s for s in holdings if s != row["symbol"] and (corr(row["symbol"], s) or 0) >= HIGH_CORR]
        if row["symbol"] not in MAJORS and len(partners) >= MAX_CORRELATED:
            skipped.append({"symbol": row["symbol"], "group": row["group"], "tier": row["tier"], "moves_with": partners})
            row.update(underlying_setup=row["group"], group="BLOCKED_SETUP", blocked_reason="PORTFOLIO_CONCENTRATION",
                       reason=f"{GROUP_TR[row['group']]} kurulumu var ama {BLOCK_TR['PORTFOLIO_CONCENTRATION']}")
        elif len(picked) < SCAN_TOP:
            picked.append(row)
    not_now = [{"symbol": r["symbol"], "group": r["group"], "reason_code": r["reason_code"] or "NO_LEVEL",
                "reason": r["reason"] or REASON_TR["NO_LEVEL"], "recheck_if": r["recheck_if"], "held": r["held"]}
               for r in rows if r["group"] in ("NO_SETUP", "AVOID") or
               (r["group"] == "BLOCKED_SETUP" and r["blocked_reason"] != "PORTFOLIO_CONCENTRATION")]
    # holdings first, then the setups an outside filter blocks, then the rest in scan order
    rejected = sorted(failed + not_now, key=lambda x: (not x.get("held"), x["group"] != "BLOCKED_SETUP"))
    pairs = [{"a": a, "b": b, "correlation": corr(a, b)} for i, a in enumerate(holdings) for b in holdings[i + 1:]
             if (corr(a, b) or 0) >= HIGH_CORR]
    classes = {c: [h for h in holdings if coin_class(h) == c] for c in MAX_POSITION}
    note = ("Portföy bilgisi verilmedi." if not holdings else
            (f"{len(pairs)} çift birlikte hareket ediyor (1h getiri korelasyonu ≥ {HIGH_CORR:g}): "
             + ", ".join(f"{p['a']}–{p['b']} {p['correlation']:g}" for p in pairs) + ". " if pairs else
             "Eldeki coinler arasında yüksek korelasyon yok. ")
            + f"Dağılım: {len(classes['MAJOR'])} majör, {len(classes['ALT'])} altcoin, {len(classes['MEME'])} memecoin.")
    btc = next((r["btc"] for r in reports if r["btc"]), None)
    return {"as_of": reports[0]["as_of"] if reports else None, "scanned": len(reports) + len(failed),
            "portfolio_usdt": portfolio_usdt, "btc": btc, "ranking": RANKING,
            "groups": {g: [r["symbol"] for r in rows if r["group"] == g] for g in GROUPS},
            "tiers": {t: [r["symbol"] for _, r in sorted(candidates, key=lambda x: x[0]) if r["tier"] == t] for t in TIERS},
            "results": picked, "not_now": rejected[:SCAN_REJECTED], "not_now_total": len(rejected),
            "skipped_correlated": skipped,
            "portfolio": {"holdings": holdings, "high_correlation_pairs": pairs, "classes": classes, "note": note},
            "research_note": RESEARCH_NOTE}


# ---------------- paper log (research only) ----------------
# Every /danis and /firsat run leaves one record per analysed coin: what the advisor said and the levels it gave.
# danisman_paper.py stores them, fills in what happened afterwards and counts the results. Nothing here or there
# reads those results back into the analysis: no threshold or decision depends on them, and no order is ever sent.
PAPER_HORIZONS = {"1h": 3_600_000, "4h": 14_400_000, "24h": 86_400_000}


def ruleset() -> dict:
    """Everything that can change a decision, a level, a position size or the scan's order. Its hash names the
    version of the advisor's logic. Not in it, on purpose: texts, emoji, formatting, cache times, how many coins the
    scan covers. Code changes that no constant shows are covered by RULESET_REVISION."""
    return {
        "revision": RULESET_REVISION,
        "timeframes": list(TFS), "quotes": list(QUOTES),
        "history": {"bars": BARS, "trend_bars": TREND_BARS, "sma200_bars": SMA200_BARS, "need_bars": NEED_BARS},
        "trend": {"slope_bars": SLOPE_BARS, "swing_k": sl.K},
        "levels": {"lookback": LOOKBACK, "reaction_atr": REACTION_ATR, "cluster_atr": sl.CLUSTER_ATR,
                   "cluster_pct": sl.CLUSTER_PCT},
        "breakout": {"window": BREAKOUT_WINDOW, "failed_window": FAILED_WINDOW, "room_atr": ROOM_ATR, "near_atr": NEAR_ATR,
                     "plan_atr": PLAN_ATR},
        "retest": {"window": RETEST_WINDOW, "zone_atr": RETEST_ATR},
        "stop": {"min_struct_atr": sl.MIN_STRUCT_ATR, "max_struct_atr": sl.MAX_STRUCT_ATR, "atr_stop": sl.ATR_STOP,
                 "params": asdict(PARAMS)},
        "low_rr": LOW_RR, "trailing_atr": TRAIL_ATR, "profit_atr": PROFIT_ATR,
        "filters": {"blockable": list(BLOCKABLE), "high_corr": HIGH_CORR, "max_correlated": MAX_CORRELATED,
                    "order": ["BTC_MARKET_RISK", "HTF_DOWNTREND", "PORTFOLIO_CONCENTRATION", "INSUFFICIENT_HISTORY"]},
        "sizing": {"risk_pct": RISK_PCT, "max_position": MAX_POSITION, "majors": sorted(MAJORS), "memes": sorted(MEMES),
                   "high_vol_atr_pct": HIGH_VOL_ATR_PCT, "min_order": MIN_ORDER_USDT, "fee": FEE},
        "ranking": {"tiers": TIER_ORDER, "near_pct": list(NEAR_PCT), "stop_ok_pct": STOP_OK_PCT},
    }


def ruleset_hash(rules: dict | None = None) -> str:
    """12 hex characters of the SHA-256 of the ruleset, written with sorted keys."""
    text = json.dumps(ruleset() if rules is None else rules, sort_keys=True, separators=(",", ":"), default=list)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


_code: dict | None = None


def code_version() -> dict:
    """{"git_commit", "working_tree_dirty"} of the code that is running. From ADVISOR_GIT_COMMIT, else git itself,
    else the .git_commit file written when the code is published (the server image has no .git)."""
    global _code
    if _code is None:
        here = pathlib.Path(__file__).resolve().parent
        commit, dirty = os.getenv("ADVISOR_GIT_COMMIT") or None, None
        if commit is None:
            try:
                git = lambda *a: subprocess.run(["git", *a], cwd=here, capture_output=True, text=True, timeout=10,
                                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                head = git("rev-parse", "HEAD")
                if head.returncode == 0 and head.stdout.strip():
                    commit, dirty = head.stdout.strip(), bool(git("status", "--porcelain").stdout.strip())
            except Exception:
                pass
        if commit is None and (here / ".git_commit").exists():
            # written by the deploy script right before the image is built: the SHA, and "dirty" on a second line
            # when the checkout had local changes
            parts = (here / ".git_commit").read_text(encoding="utf-8").split()
            if parts:
                commit, dirty = parts[0], "dirty" in parts[1:]
        _code = {"git_commit": commit, "working_tree_dirty": dirty}
    return _code


def data_origin(report: dict) -> str:
    """LIVE for a real run, REPLAY for a report computed for a past moment. ADVISOR_DATA_ORIGIN (the test suites set
    it to TEST) wins, so a test can never write a LIVE record."""
    forced = (os.getenv("ADVISOR_DATA_ORIGIN") or "").upper()
    return forced if forced in ORIGINS else "LIVE" if report.get("live") else "REPLAY"


def paper_row(r: dict, source: str, origin: str | None = None) -> dict:
    """One report as a paper-log record. Unique by symbol + setup_id + the 15m close it was computed on + the ruleset
    that judged it + where it comes from. setup_id is the market setup; ruleset_hash is the logic that looked at it."""
    plan = r["plan"] or r["blocked_plan"] or {}      # a blocked setup keeps its plan, for the virtual comparison only
    pb, i1, i15 = r["pullback"] or {}, r["indicators"]["1h"], r["indicators"]["15m"]
    entry_type = "PULLBACK" if r["reason_code"] == "PULLBACK_WAIT" else None if r["scenario"] == "NO_TRADE" else r["scenario"]
    close_ms = r["as_of_ms"]
    bo = r["breakout"]
    return {"symbol": r["symbol"], "pair": r["pair"], "setup_id": r["setup_id"], "setup_key": r["setup_key"],
            "setup_class": r["setup_class"], "underlying_setup": r["underlying_setup"],
            "blocked_reason": r["blocked_reason"], "close_ms": close_ms, "timestamp": r["as_of"],
            # generated_at: when this report was really produced; market_timestamp: the last closed 15m candle it rests on
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "market_timestamp": r["as_of"], "market_timestamp_ms": close_ms,
            "data_origin": origin if origin in ORIGINS else data_origin(r), "source": source,
            "advisor_version": ADVISOR_VERSION, "ruleset_hash": ruleset_hash(), **code_version(),
            "decision": r["decision"], "entry_type": entry_type, "group": group_of(r), "actionable": bool(r["actionable"]),
            "breakout_status": bo["breakout_status"], "price": r["last_closed_15m"], "live_price": r["price"],
            "trend_1h": r["trend"]["1h"]["state"], "trend_4h": r["trend"]["4h"]["state"],
            "resistance": r["main_resistance"], "support": r["main_support"],
            # the level a breakout is measured against: the resistance waited on, or the one already broken
            "level": bo.get("level") if entry_type in ("BREAKOUT", "RETEST") else None,
            "plan_type": plan.get("type"), "entry": plan.get("entry"), "trigger": plan.get("trigger_price"),
            "limit": plan.get("limit_price"), "stop": plan.get("initial_stop"),
            "invalidation": plan.get("invalid_level", pb.get("invalidation")),
            "resistance_1": plan.get("resistance_1"), "risk_per_unit": plan.get("risk_per_unit"),
            "retest_zone": [plan["retest_zone_low"], plan["retest_zone_high"]] if "retest_zone_low" in plan else None,
            "retest_confirmation_price": plan.get("retest_confirmation_price"),
            "pullback_zone": [pb["entry_zone_low"], pb["entry_zone_high"]] if pb else None,
            "volume_ratio": i15["volume_ratio"], "rsi_1h": i1["rsi14"], "rsi_15m": i15["rsi14"], "atr_1h": i1["atr14"],
            "btc_regime": None if not r["btc"] else {**r["btc"]["trend"], "market_risk": r["btc"]["market_risk"]},
            "warnings": [w["code"] for w in r["warnings"]], "reason_code": r["reason_code"],
            # what happened next is measured from `price`, on the closed 15m candles after close_ms, at these moments
            "outcome_due_ms": {h: close_ms + ms for h, ms in PAPER_HORIZONS.items()},
            "outcome": {}, "outcome_done": []}


def paper_log(reports: list[dict], source: str, origin: str | None = None) -> int:
    """Store the reports' records (duplicates are skipped by the store). A failure here never breaks a report."""
    try:
        import danisman_paper
        return danisman_paper.log([paper_row(r, source, origin) for r in reports])
    except Exception as e:
        log.warning("Advisor paper log failed: %s", e)
        return 0


def paper_stats(rows: list[dict], origin: str = "LIVE", all_rulesets: bool = False, now_ms: int | None = None) -> dict:
    """The paper log's statistics with the advisor's defaults: LIVE records judged by the CURRENT ruleset. Replays,
    tests and older rulesets are only counted when asked for (origin="REPLAY" / "ALL", all_rulesets=True)."""
    import danisman_paper
    return danisman_paper.stats(rows, now_ms, origin, None if all_rulesets else ruleset_hash())


async def scan(portfolio_usdt: float | None = None, holdings: list[str] | None = None, limit: int = SCAN_LIMIT,
               symbols: list | None = None, fetcher=None, asof_ms: int | None = None, paper: str | None = None,
               debug: bool = False) -> dict:
    """Analyze the most traded coins (and the holdings) and return the setups worth watching.

    symbols: coins to scan instead of the exchange's list ("SOL" or ("SOL", "USDT")). fetcher: async coin -> fetch()
    data, instead of the network (tests, replays). paper: write every report to the paper log under this source
    name. debug: also return the coins the universe filter left out, with the reason."""
    held = list(dict.fromkeys(h.upper().removesuffix("USDT") for h in (holdings or [])))
    client, excluded = None, None
    try:
        if fetcher is None:
            client = httpx.AsyncClient()
            if symbols:
                pairs = [(s, None) if isinstance(s, str) else tuple(s) for s in symbols]
            elif debug:
                pairs, excluded = await universe(client, limit, with_excluded=True)
            else:
                pairs = await universe(client, limit)
            quote = dict(pairs)
            b = await asyncio.gather(*[_klines(client, "BTCUSDT", tf) for tf in ("15m", "1h", "4h")])
            btc = {"15m": b[0], "1h": b[1], "4h": b[2]}

            async def fetcher(coin):
                q = quote.get(coin)
                return await fetch(coin, client=client, btc=btc, quotes=(q,) if q else SCAN_QUOTES)
            coins = [p[0] for p in pairs]
        else:
            coins = [s if isinstance(s, str) else s[0] for s in symbols or []]
        coins = list(dict.fromkeys(held + [c.upper() for c in coins]))
        gate = asyncio.Semaphore(SCAN_PARALLEL)

        async def one(coin):
            async with gate:
                try:
                    return coin, await fetcher(coin), None
                except Exception as e:
                    return coin, None, e
        got = await asyncio.gather(*[one(c) for c in coins])
    finally:
        if client is not None:
            await client.aclose()
    now = int(time.time() * 1000) if asof_ms is None else int(asof_ms)
    reports, failed, closes = [], [], {}
    for coin, data, err in got:
        if err is None:
            try:
                reports.append(analyze(data, portfolio_usdt, asof_ms=asof_ms))
                closes[coin] = split(data["frames"]["1h"], "1h", now)[0].set_index("t").c
                continue
            except ValueError as e:      # too few candles for any report: a pair listed days ago
                err = e
        code = "INSUFFICIENT_HISTORY" if isinstance(err, ValueError) else "NO_DATA"
        failed.append({"symbol": coin, "group": "NO_SETUP", "reason_code": code, "reason": REASON_TR[code],
                       "recheck_if": None, "held": coin in held})
    out = build_scan(reports, failed, closes, held, portfolio_usdt)
    by_symbol = {r["symbol"]: r for r in reports}
    for x in out["skipped_correlated"]:          # held back by the portfolio: recorded as blocked, like the other filters
        block(by_symbol[x["symbol"]], "PORTFOLIO_CONCENTRATION")
    if paper:
        out["paper_logged"] = paper_log(reports, paper)
    if excluded is not None:
        out["excluded"] = excluded
    return out


def format_scan(s: dict) -> str:
    """The scan as Turkish text (Telegram / terminal)."""
    zone = lambda z: _zone(z) if z else "—"
    lines = [f"🔎 Kripto Danışman taraması — {s['scanned']} parite" + (f", {s['as_of']}" if s["as_of"] else "")]
    if s["btc"]:
        lines.append("BTC: " + " · ".join(f"{tf} {TREND_TR[v]}" for tf, v in s["btc"]["trend"].items())
                     + (" — MARKET_RISK: BTC kısa vadede düşüşte" if s["btc"]["market_risk"] else ""))
    lines.append("Gruplar: " + " · ".join(f"{GROUP_TR[g]} {len(v)}" for g, v in s["groups"].items()))
    if not s["results"]:
        lines += ["", "Şu an öne çıkan teknik kurulum yok."]
    for n, r in enumerate(s["results"], 1):
        lines += ["", f"{n}) {r['symbol']} — {GROUP_TR[r['group']]} [{r['decision']}]"
                  + (f" · {r['entry_type']}" if r["entry_type"] else "") + (" · portföyde" if r["held"] else ""),
                  f"   {r['summary']}",
                  f"   Fiyat {_p(r['current_price'])} · 1h {TREND_TR[r['1h_trend']]} / 4h {TREND_TR[r['4h_trend']]} · "
                  f"RSI {r['RSI']:g} (1h) · hacim {r['volume_ratio']}x (15m)",
                  f"   Direnç {zone(r['main_resistance'])} · destek {zone(r['main_support'])}"]
        stop = f"teknik stop {_p(r['technical_stop'])} (%{r['stop_distance_pct']:g}) · geçersizlik {_p(r['invalidation'])}" \
            if r["has_plan"] else ""
        if r["retest_zone_low"] is not None:
            lines += [f"   Kırılan direnç {_p(r['broken_resistance'])} · geri test bölgesi {_p(r['retest_zone_low'])}-"
                      f"{_p(r['retest_zone_high'])} (fiyatın %{r['retest_distance_pct']:g} altında)",
                      f"   Teyit: bölgeye inen 15m mumun {_p(r['retest_confirmation_price'])} üstünde kapanması · {stop}"]
        elif r["trigger"] is not None:
            lines.append(f"   Tetik {_p(r['trigger'])} · limit {_p(r['limit'])} · {stop}")
        elif r["has_plan"]:
            lines.append(f"   Giriş en fazla {_p(r['limit'])} · {stop}")
        elif r["pullback_zone"]:
            lines.append(f"   Giriş bölgesi {zone(r['pullback_zone'])} · teyit: 15m kapanış "
                         f"{_p(r['pullback_confirmation_price'])} üstünde · geçersizlik {_p(r['invalidation'])}")
        lines.append(f"   İz süren stop {r['trailing_atr']:g} ATR = %{r['trailing_pct']:g}")
        ps = r["position_size"]
        if ps:
            lines.append(f"   Pozisyon: yaklaşık {ps['position_usdt']:g} USDT (portföyün %{ps['portfolio_share_pct']:g}'i), "
                         f"stop olursa kayıp {ps['loss_at_stop_usdt']:g}")
        elif r["position_size_note"]:
            lines.append(f"   Pozisyon: {r['position_size_note']}")
        if r["recheck_if"]:
            lines.append(f"   Tekrar kontrol: {r['recheck_if']}")
        if r["invalid_if"]:
            lines.append(f"   Geçersiz olur: {r['invalid_if']}")
        lines.append("   Sıralama: " + "; ".join(r["rank_reasons"]))
        if r["warnings"] or r.get("moves_with"):
            lines.append("   Uyarı: " + ", ".join(r["warnings"] + ([f"portföydeki {', '.join(r['moves_with'])} ile birlikte "
                                                                    "hareket ediyor"] if r.get("moves_with") else [])))
    if s["skipped_correlated"]:
        lines += ["", "Birlikte hareket ettiği için öne çıkarılmayanlar: "
                  + "; ".join(f"{x['symbol']} ({', '.join(x['moves_with'])} ile)" for x in s["skipped_correlated"][:6])]
    if s["not_now"]:
        lines += ["", "Şu an işlem aranmayacaklar:"]
        lines += [f"- {x['symbol']}: {x['reason']}" + (" (portföyde)" if x.get("held") else "") for x in s["not_now"]]
        if s["not_now_total"] > len(s["not_now"]):
            lines.append(f"  (+{s['not_now_total'] - len(s['not_now'])} coin daha)")
    if s.get("excluded") is not None:
        lines += ["", "Tarama dışı bırakılanlar (debug):"]
        by: dict[str, list] = {}
        for x in s["excluded"]:
            by.setdefault(x["reason_code"], []).append(x["symbol"])
        for code, names in sorted(by.items()):
            shown = "" if code in ("LOW_VOLUME", "INACTIVE") else ": " + ", ".join(names[:40]) + (" …" if len(names) > 40 else "")
            lines.append(f"- {EXCLUDE_TR[code]} ({len(names)}){shown}")
    lines += ["", f"Portföy: {s['portfolio']['note']}",
              "Sıralama (sırayla, tek puan yok): " + "; ".join(s["ranking"]) + ".", s["research_note"]]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Kripto Danışman (karar destek; emir göndermez)")
    ap.add_argument("symbol", nargs="?")
    ap.add_argument("--tara", action="store_true", help="en çok işlem gören pariteleri tara, kurulumları sırala")
    ap.add_argument("--limit", type=int, default=SCAN_LIMIT, help=f"taranacak parite sayısı (varsayılan {SCAN_LIMIT}; 0 = hepsi)")
    ap.add_argument("--portfolio", type=float, help="portföy büyüklüğü (USDT); verilmezse pozisyon tutarı hesaplanmaz")
    ap.add_argument("--position", type=float, help="eldeki pozisyonun bugünkü değeri (USDT)")
    ap.add_argument("--avg-price", type=float, help="ortalama alış fiyatı")
    ap.add_argument("--holdings", default="", help="portföydeki coinler: BTC,ETH,SOL")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--debug", action="store_true", help="taramada dışarıda bırakılan sembolleri sebebiyle göster")
    ap.add_argument("--no-log", action="store_true", help="araştırma kaydına (paper log) yazma")
    ap.add_argument("--paper-stats", action="store_true", help="paper log sonuçlarını güncelle ve istatistikleri göster")
    ap.add_argument("--origin", default="live", choices=["live", "replay", "test", "all", "versions"],
                    help="--paper-stats için veri kaynağı (varsayılan live; versions = danışman sürümleri)")
    ap.add_argument("--all-rulesets", action="store_true", help="--paper-stats: yalnız güncel kural seti yerine hepsi")
    a = ap.parse_args()
    held = [x for x in a.holdings.split(",") if x]
    if a.paper_stats:
        import danisman_paper
        done = asyncio.run(danisman_paper.update_outcomes())
        rows = danisman_paper.store().all()
        if a.origin == "versions":
            st = danisman_paper.versions(rows)
            text = danisman_paper.format_versions(st, ruleset_hash())
        else:
            st = paper_stats(rows, a.origin.upper(), a.all_rulesets)
            text = danisman_paper.format_stats(st, done)
        print(json.dumps({"update": done, "stats": st}, ensure_ascii=False, indent=1) if a.json else text)
    elif a.tara:
        out = asyncio.run(scan(a.portfolio, held, a.limit, paper=None if a.no_log else "cli-tara", debug=a.debug))
        print(json.dumps(out, ensure_ascii=False, indent=1) if a.json else format_scan(out))
    elif not a.symbol:
        ap.error("coin kodu ya da --tara gerekli")
    else:
        rep = asyncio.run(advise(a.symbol, a.portfolio, a.position, a.avg_price, held))
        if not a.no_log:
            paper_log([rep], "cli")
        print(json.dumps(rep, ensure_ascii=False, indent=1) if a.json else format_report(rep))

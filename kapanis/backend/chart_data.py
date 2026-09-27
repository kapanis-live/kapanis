"""Candles + indicators for the panel's chart page (any coin, BIST or US ticker, any timeframe).

Crypto comes from Binance, BIST (.IS) and US stocks from Yahoo. Only closed candles matter for the bot's
rules, but the chart also shows the still-forming last candle so the price on screen is current.
Indicators are computed here in plain Python: SMA 20/50/200, RSI 14 (Wilder), volume MA 20 and VWAP
(intraday: reset every session day; daily/weekly: rolling 20 candles).
"""
import time
from datetime import datetime, timezone

import httpx
import technical_indicators

BINANCE = ["https://api.binance.com", "https://data-api.binance.vision"]
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Kapanis panel chart)"}
TIMEFRAMES = ["15m", "1h", "4h", "1d", "1w"]
# Yahoo has no 4h interval: 4h is built from 1h candles.
YAHOO_TF = {"15m": ("15m", "60d"), "1h": ("60m", "730d"), "4h": ("60m", "730d"), "1d": ("1d", "5y"), "1w": ("1wk", "10y")}
SHOW = 320           # candles sent to the browser
CACHE_SECONDS = 60
_cache: dict = {}


class ChartError(Exception):
    pass


def detect(symbol: str, market: str | None) -> tuple[str, str]:
    """-> (market, clean code). KRIPTO: BTC, BIST: THYAO, ABD: NVDA."""
    s = symbol.upper().replace("-", "/").strip()
    if s.endswith(".IS"):
        return "BIST", s[:-3]
    if s.endswith(".US"):
        return "ABD", s[:-3]
    if "/" in s:
        return "KRIPTO", s.split("/")[0]
    if s.endswith("USDT") and len(s) > 5:
        return "KRIPTO", s[:-4]
    return (market or "KRIPTO").upper(), s


# Daily session close in UTC (with a margin for data delay): a daily candle counts only after it.
DAILY_CLOSE_UTC = {"BIST": (15, 20), "ABD": (21, 10)}


def last_closed(candles: list[dict], market: str, now: float | None = None) -> dict | None:
    """Pure: the last CLOSED daily candle. Crypto closes at 00:00 UTC; BIST and US at their session end.
    The still-forming candle of today never counts (close rule)."""
    import datetime as _dt
    now = time.time() if now is None else now
    for c in reversed(candles or []):
        start = _dt.datetime.fromtimestamp(c["t"], _dt.timezone.utc)
        if market in DAILY_CLOSE_UTC:
            h, m = DAILY_CLOSE_UTC[market]
            closes = start.replace(hour=h, minute=m, second=0, microsecond=0)
            if closes < start:
                closes += _dt.timedelta(days=1)
        else:
            closes = start + _dt.timedelta(days=1)
        if closes.timestamp() <= now:
            return c
    return None


async def _binance(client: httpx.AsyncClient, code: str, tf: str) -> list[dict]:
    last = None
    for base in BINANCE:
        try:
            r = await client.get(f"{base}/api/v3/klines", params={"symbol": code + "USDT", "interval": tf, "limit": 600}, timeout=15)
            if r.status_code == 400:
                raise ChartError(f"Binance'te {code}/USDT yok")
            r.raise_for_status()
            return [{"t": int(k[0]) // 1000, "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4]), "v": float(k[5])}
                    for k in r.json()]
        except ChartError:
            raise
        except Exception as e:  # try the mirror
            last = e
    raise ChartError(f"Binance verisi alınamadı: {last}")


async def _yahoo(client: httpx.AsyncClient, ysym: str, tf: str) -> tuple[list[dict], str]:
    interval, rng = YAHOO_TF[tf]
    r = await client.get(YAHOO + ysym, params={"interval": interval, "range": rng}, headers=HEADERS, timeout=20)
    if r.status_code == 404:
        raise ChartError(f"Yahoo'da {ysym} bulunamadı")
    r.raise_for_status()
    res = (r.json().get("chart") or {}).get("result")
    if not res:
        raise ChartError(f"Yahoo'da {ysym} bulunamadı")
    res = res[0]
    q = res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(res.get("timestamp") or []):
        o, h, lo, c, v = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
        if None in (o, h, lo, c) or (not v and o == h == lo == c):  # empty placeholder bar (pre-market, holiday)
            continue
        rows.append({"t": int(t), "o": float(o), "h": float(h), "l": float(lo), "c": float(c), "v": float(v or 0)})
    if tf == "4h":
        rows = _group(rows, 4 * 3600)
    return rows, res["meta"].get("currency") or ""


def _group(rows: list[dict], seconds: int) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        key = r["t"] - r["t"] % seconds
        if out and out[-1]["t"] == key:
            b = out[-1]
            b["h"], b["l"], b["c"], b["v"] = max(b["h"], r["h"]), min(b["l"], r["l"]), r["c"], b["v"] + r["v"]
        else:
            out.append({**r, "t": key})
    return out


def sma(values: list[float], n: int) -> list[float | None]:
    out, s = [], 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def rsi(closes: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_g, avg_l = gains / n, losses / n
    out[n] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (n - 1) + max(d, 0)) / n
        avg_l = (avg_l * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


def vwap(rows: list[dict], intraday: bool, window: int = 20) -> list[float | None]:
    out: list[float | None] = []
    if intraday:  # session VWAP: resets at each UTC day
        day, pv, vol = None, 0.0, 0.0
        for r in rows:
            d = datetime.fromtimestamp(r["t"], timezone.utc).date()
            if d != day:
                day, pv, vol = d, 0.0, 0.0
            typical = (r["h"] + r["l"] + r["c"]) / 3
            pv += typical * r["v"]
            vol += r["v"]
            out.append(pv / vol if vol else None)
        return out
    for i in range(len(rows)):
        part = rows[max(0, i - window + 1): i + 1]
        vol = sum(r["v"] for r in part)
        out.append(sum((r["h"] + r["l"] + r["c"]) / 3 * r["v"] for r in part) / vol if vol and i >= window - 1 else None)
    return out


def zones(rows: list[dict], price: float, lookback: int = 200, top: int = 3) -> dict:
    """Support/resistance zones from swing highs/lows (3 candles each side) of CLOSED candles, clustered by
    ~1.2 x average true range. Nearest `top` below and above the last price, with how many swings touched each."""
    r = rows[-lookback - 1:-1]  # the last candle may still be open
    if len(r) < 10:
        return {"destek": [], "direnc": []}
    tr = [max(k["h"] - k["l"], abs(k["h"] - p["c"]), abs(k["l"] - p["c"])) for p, k in zip(r, r[1:])]
    band = max(sum(tr[-14:]) / min(14, len(tr)) * 1.2, price * 0.004)
    pts = []
    for i in range(3, len(r) - 3):
        win = r[i - 3:i + 4]
        if r[i]["h"] == max(k["h"] for k in win):
            pts.append(r[i]["h"])
        if r[i]["l"] == min(k["l"] for k in win):
            pts.append(r[i]["l"])
    pts.sort()
    clusters = []
    for v in pts:
        if clusters and v - clusters[-1][0] <= band:  # compare with the zone start: no chaining
            clusters[-1].append(v)
        else:
            clusters.append([v])
    zs = [{"alt": min(c), "ust": max(c), "orta": sum(c) / len(c), "dokunma": len(c)} for c in clusters]
    fmt = lambda z: {k: (_round(v) if k != "dokunma" else v) for k, v in z.items()}
    below = sorted((z for z in zs if z["orta"] < price), key=lambda z: -z["orta"])[:top]
    above = sorted((z for z in zs if z["orta"] >= price), key=lambda z: z["orta"])[:top]
    return {"destek": [fmt(z) for z in below], "direnc": [fmt(z) for z in above]}


def _round(v):
    if v is None:
        return None
    return float(f"{v:.8g}")


async def chart(symbol: str, tf: str = "1d", market: str | None = None) -> dict:
    if tf not in TIMEFRAMES:
        raise ChartError(f"Zaman dilimi {', '.join(TIMEFRAMES)} olmalı")
    mkt, code = detect(symbol, market)
    key = (mkt, code, tf)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    async with httpx.AsyncClient() as client:
        if mkt == "KRIPTO":
            rows, currency = await _binance(client, code, tf), "USD"
        elif mkt == "BIST":
            rows, currency = await _yahoo(client, code + ".IS", tf)
        else:
            rows, currency = await _yahoo(client, code, tf)
    if len(rows) < 2:
        raise ChartError("Bu zaman diliminde yeterli mum yok")
    closes = [r["c"] for r in rows]
    series = {
        "sma5": sma(closes, 5), "sma10": sma(closes, 10), "sma20": sma(closes, 20),
        "sma50": sma(closes, 50), "sma100": sma(closes, 100), "sma200": sma(closes, 200),
        "rsi": rsi(closes), "vol_ma": sma([r["v"] for r in rows], 20),
        "vwap": vwap(rows, intraday=tf in ("15m", "1h", "4h")),
    }
    series.update(technical_indicators.calculate(rows))
    rows_out = rows[-SHOW:]
    cut = len(rows) - len(rows_out)
    last, prev = rows[-1], rows[-2]
    doc = {
        "symbol": code, "market": mkt, "tf": tf, "currency": currency or ("TRY" if mkt == "BIST" else "USD"),
        "candles": [{k: (_round(v) if k != "t" else v) for k, v in r.items()} for r in rows_out],
        **{name: [_round(v) for v in vals[cut:]] for name, vals in series.items()},
        "last": {"price": _round(last["c"]), "change_pct": round((last["c"] / prev["c"] - 1) * 100, 2) if prev["c"] else None,
                 "rsi": _round(series["rsi"][-1]), "sma20": _round(series["sma20"][-1]), "sma50": _round(series["sma50"][-1]),
                 "sma200": _round(series["sma200"][-1]), "vwap": _round(series["vwap"][-1]),
                 "volume": last["v"], "vol_ma": _round(series["vol_ma"][-1])},
        "vwap_note": "seans VWAP (her gün sıfırlanır)" if tf in ("15m", "1h", "4h") else "20 mumluk hareketli VWAP",
        "zones": zones(rows, last["c"]),
        "note": "Son mum henüz kapanmamış olabilir; botun kuralları yalnız kapanmış mumu sayar.",
    }
    _cache[key] = (time.time(), doc)
    return doc

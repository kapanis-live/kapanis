"""Binance public klines + indicator calculation. No API key needed."""
import time
from datetime import datetime, timezone

import httpx
import pandas as pd

import config
import derivatives

BINANCE_BASES = ["https://api.binance.com", "https://data-api.binance.vision"]


class SymbolNotFound(Exception):
    pass


async def fetch_klines(client: httpx.AsyncClient, symbol: str, interval: str,
                       limit: int = config.KLINE_LIMIT) -> pd.DataFrame:
    """Return closed candles only (the still-open candle is dropped)."""
    last_error = None
    for base in BINANCE_BASES:
        try:
            r = await client.get(f"{base}/api/v3/klines",
                                 params={"symbol": symbol, "interval": interval, "limit": limit},
                                 timeout=15)
        except httpx.HTTPError as e:
            last_error = e
            continue
        if r.status_code == 400 and "Invalid symbol" in r.text:
            raise SymbolNotFound(symbol)
        if r.status_code != 200:
            last_error = RuntimeError(f"{base} {r.status_code}: {r.text[:200]}")
            continue
        rows = r.json()
        df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume",
                                         "close_time", "qv", "n", "tbv", "tqv", "ignore"])
        df = df[["open_time", "open", "high", "low", "close", "volume", "close_time"]]
        df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
        now_ms = int(time.time() * 1000)
        return df[df["close_time"] < now_ms].reset_index(drop=True)
    raise RuntimeError(f"Binance unreachable for {symbol} {interval}: {last_error}")


def _rma(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    df["sma20"] = c.rolling(20).mean()
    df["sma50"] = c.rolling(50).mean()
    df["sma200"] = c.rolling(200).mean()

    delta = c.diff()
    gain = _rma(delta.clip(lower=0), 14)
    loss = _rma(-delta.clip(upper=0), 14)
    df["rsi14"] = 100 - 100 / (1 + gain / loss)

    prev_close = c.shift()
    tr = pd.concat([h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
    df["atr14"] = _rma(tr, 14)

    df["vol_avg20"] = v.rolling(20).mean()

    # Daily VWAP, resets at 00:00 UTC (03:00 Turkey time)
    day = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.date
    tpv = (h + l + c) / 3 * v
    df["vwap"] = tpv.groupby(day).cumsum() / v.groupby(day).cumsum()
    return df


def _num(x):
    if x is None or pd.isna(x):
        return None
    return float(f"{float(x):.6g}")


def _ts(ms) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def summarize(df: pd.DataFrame, with_vwap: bool) -> dict:
    last = df.iloc[-1]
    out = {
        "son_kapanis_mum_utc": _ts(last["open_time"]),
        "kapanis": _num(last["close"]),
        "sma20": _num(last["sma20"]),
        "sma50": _num(last["sma50"]),
        "sma200": _num(last["sma200"]),
        "rsi14": _num(last["rsi14"]),
        "atr14": _num(last["atr14"]),
        "hacim": _num(last["volume"]),
        "hacim_ort20": _num(last["vol_avg20"]),
        "periyot_yuksek": _num(df["high"].max()),
        "periyot_dusuk": _num(df["low"].min()),
        "mum_sayisi": len(df),
    }
    if with_vwap:
        out["gunluk_vwap"] = _num(last["vwap"])
    return out


# --- support / resistance zones -------------------------------------------------
# Ported from the Crypto Radar project: swing pivots on 4h (and 1d, weighted 1.5x)
# clustered within ~0.35 ATR into zones. More touches = stronger zone.

def _pivots(df: pd.DataFrame, left: int, right: int, weight: float = 1.0) -> tuple[list[dict], list[dict]]:
    lows, highs = [], []
    h, l, v = df["high"].to_numpy(), df["low"].to_numpy(), df["volume"].to_numpy()
    for i in range(left, len(df) - right):
        if h[i] == h[i - left:i + right + 1].max():
            highs.append({"price": float(h[i]), "volume": float(v[i]) * weight})
        if l[i] == l[i - left:i + right + 1].min():
            lows.append({"price": float(l[i]), "volume": float(v[i]) * weight})
    return lows, highs


def _cluster(points: list[dict], bandwidth: float) -> list[dict]:
    clusters = []
    for pt in sorted(points, key=lambda p: p["price"]):
        near = next((c for c in clusters if abs(c["center"] - pt["price"]) <= bandwidth), None)
        if near is None:
            clusters.append({"points": [pt], "center": pt["price"]})
            continue
        near["points"].append(pt)
        weights = [max(p["volume"], 1) for p in near["points"]]
        near["center"] = sum(p["price"] * w for p, w in zip(near["points"], weights)) / sum(weights)
    zones = []
    for c in clusters:
        prices = [p["price"] for p in c["points"]]
        half = max(bandwidth * 0.35, (max(prices) - min(prices)) / 2)
        zones.append({"alt": c["center"] - half, "ust": c["center"] + half, "orta": c["center"],
                      "dokunma": len(c["points"])})
    return zones


def sr_zones(df4h: pd.DataFrame, df1d: pd.DataFrame | None, price: float, atr4h: float | None, top: int = 3) -> dict:
    """Nearest support zones below and resistance zones above the price."""
    if df4h is None or df4h.empty or not price:
        return {"destekler": [], "direncler": []}
    bandwidth = max((atr4h if atr4h and atr4h == atr4h else price * 0.015) * 0.35, price * 0.0015)
    lows, highs = _pivots(df4h, 3, 3)
    if df1d is not None and len(df1d) > 5:
        dl, dh = _pivots(df1d, 2, 2, weight=1.5)
        lows += dl
        highs += dh
    supports = sorted((z for z in _cluster(lows, bandwidth) if z["orta"] < price), key=lambda z: -z["orta"])
    resistances = sorted((z for z in _cluster(highs, bandwidth) if z["ust"] > price), key=lambda z: z["orta"])

    def fmt(z):
        return {"alt": _num(z["alt"]), "ust": _num(z["ust"]), "orta": _num(z["orta"]), "dokunma": z["dokunma"],
                "uzaklik_yuzde": round((z["orta"] / price - 1) * 100, 2)}
    out = {"destekler": [fmt(z) for z in supports[:top]], "direncler": [fmt(z) for z in resistances[:top]]}
    if not resistances:
        out["not"] = f"Fiyat son {len(df4h)} adet 4h mumun pivot tepelerinin üstünde: yapısal direnç yok, hedef için yuvarlak seviye/ATR kullan."
    elif not supports:
        out["not"] = f"Fiyat son {len(df4h)} adet 4h mumun pivot diplerinin altında: yapısal destek yok."
    return out


async def snapshot(client: httpx.AsyncClient, coin: str) -> dict:
    symbol = coin + config.QUOTE
    result = {"sembol": symbol, "zaman_dilimleri": {}}
    frames = {}
    for tf in config.TIMEFRAMES:
        df = add_indicators(await fetch_klines(client, symbol, tf))
        frames[tf] = df
        if df.empty:
            continue
        result["zaman_dilimleri"][tf] = summarize(df, with_vwap=tf in ("15m", "1h"))
        if tf == "15m":
            recent = df.tail(config.RECENT_CANDLES)
            result["son_15dk_mumlar"] = [
                {"utc": _ts(r.open_time), "a": _num(r.open), "y": _num(r.high), "d": _num(r.low),
                 "k": _num(r.close), "hacim": _num(r.volume), "hacim_ort20": _num(r.vol_avg20)}
                for r in recent.itertuples()
            ]
    price_df = frames.get("15m")
    if price_df is not None and not price_df.empty and frames.get("4h") is not None and not frames["4h"].empty:
        result["destek_direnc"] = sr_zones(frames["4h"], frames.get("1d"), float(price_df.close.iloc[-1]),
                                           float(frames["4h"].atr14.iloc[-1]))
    try:
        result["vadeli"] = await derivatives.snapshot(client, coin)
    except Exception as e:
        result["vadeli"] = {"hata": str(e)}
    try:
        result["emir_defteri"] = await order_book(client, symbol)
    except Exception as e:
        result["emir_defteri"] = {"hata": str(e)[:80]}
    try:
        import conversation_store
        import structure
        plan = conversation_store.load_state()["planlar"].get(coin)
        # regime, structure (HH/HL, BOS, CHoCH), liquidity, volume profile, momentum, confluence — all in code
        result["teknik_motor"] = structure.analyze(frames, result.get("vadeli"), plan, entry_tf="15m", htf_list=("1d", "4h"))
    except Exception as e:
        result["teknik_motor"] = {"hata": str(e)[:120]}
    return result


async def order_book(client: httpx.AsyncClient, symbol: str, band_pct: float = 1.0) -> dict:
    """Bid vs ask size within ±band_pct of the mid price, and the biggest wall on each side.
    Orders can be cancelled: context only, never a guaranteed support/resistance."""
    r = await client.get(f"{BINANCE_BASES[0]}/api/v3/depth", params={"symbol": symbol, "limit": 1000}, timeout=15)
    r.raise_for_status()
    book = r.json()
    bids = [(float(p), float(q)) for p, q in book["bids"]]
    asks = [(float(p), float(q)) for p, q in book["asks"]]
    if not bids or not asks:
        return {"hata": "boş defter"}
    mid = (bids[0][0] + asks[0][0]) / 2
    lo, hi = mid * (1 - band_pct / 100), mid * (1 + band_pct / 100)
    bid_usd = sum(p * q for p, q in bids if p >= lo)
    ask_usd = sum(p * q for p, q in asks if p <= hi)
    wall_b = max(((p, p * q) for p, q in bids if p >= lo), key=lambda x: x[1], default=None)
    wall_a = max(((p, p * q) for p, q in asks if p <= hi), key=lambda x: x[1], default=None)
    return {"bant_yuzde": band_pct, "alis_usd": round(bid_usd), "satis_usd": round(ask_usd),
            "dengesizlik": round((bid_usd - ask_usd) / (bid_usd + ask_usd), 3) if bid_usd + ask_usd else None,
            "en_buyuk_alis_duvari": {"fiyat": _num(wall_b[0]), "usd": round(wall_b[1])} if wall_b else None,
            "en_buyuk_satis_duvari": {"fiyat": _num(wall_a[0]), "usd": round(wall_a[1])} if wall_a else None,
            "spread_yuzde": round((asks[0][0] / bids[0][0] - 1) * 100, 4),
            "not": "emirler iptal edilebilir; kesin destek/direnç sayılmaz"}


_filters_cache: dict[str, tuple[float, dict]] = {}


async def order_filters(client: httpx.AsyncClient, symbol: str) -> dict:
    """Spot order limits for a pair from exchangeInfo (cached 24h): min notional, min qty, qty step."""
    hit = _filters_cache.get(symbol)
    if hit and time.time() - hit[0] < 86400:
        return hit[1]
    r = await client.get(f"{BINANCE_BASES[0]}/api/v3/exchangeInfo", params={"symbol": symbol}, timeout=15)
    if r.status_code == 400 and "Invalid symbol" in r.text:
        raise SymbolNotFound(symbol)
    r.raise_for_status()
    info = r.json()["symbols"][0]
    f = {x["filterType"]: x for x in info["filters"]}
    notional = f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}
    lot = f.get("LOT_SIZE", {})
    out = {"durum": info["status"], "min_tutar_usd": float(notional.get("minNotional", 0)),
           "min_adet": float(lot.get("minQty", 0)), "adet_adimi": float(lot.get("stepSize", 0))}
    _filters_cache[symbol] = (time.time(), out)
    return out


async def ticker_24h(client: httpx.AsyncClient, symbol: str) -> dict:
    """Last price and the 24h reference price (crypto trades around the clock, so "daily" = 24h)."""
    r = await client.get(f"{BINANCE_BASES[0]}/api/v3/ticker/24hr", params={"symbol": symbol}, timeout=10)
    if r.status_code == 400 and "Invalid symbol" in r.text:
        raise SymbolNotFound(symbol)
    r.raise_for_status()
    j = r.json()
    return {"fiyat": float(j["lastPrice"]), "onceki_kapanis": float(j["openPrice"]),
            "degisim_yuzde": float(j["priceChangePercent"])}


async def last_price(client: httpx.AsyncClient, symbol: str) -> float:
    r = await client.get(f"{BINANCE_BASES[0]}/api/v3/ticker/price", params={"symbol": symbol}, timeout=10)
    if r.status_code == 400 and "Invalid symbol" in r.text:
        raise SymbolNotFound(symbol)
    r.raise_for_status()
    return float(r.json()["price"])


async def fetch_range(client: httpx.AsyncClient, symbol: str, interval: str,
                      start_ms: int, end_ms: int | None = None) -> pd.DataFrame:
    """Closed candles from start_ms onward, paginated 1000 at a time."""
    frames = []
    cursor = start_ms
    end_ms = end_ms or int(time.time() * 1000)
    while cursor < end_ms:
        r = await client.get(f"{BINANCE_BASES[0]}/api/v3/klines", timeout=20,
                             params={"symbol": symbol, "interval": interval, "startTime": cursor,
                                     "endTime": end_ms, "limit": 1000})
        if r.status_code == 400 and "Invalid symbol" in r.text:
            raise SymbolNotFound(symbol)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        frames.extend(rows)
        cursor = rows[-1][0] + 1
        if len(rows) < 1000:
            break
    df = pd.DataFrame(frames, columns=["open_time", "open", "high", "low", "close", "volume",
                                       "close_time", "qv", "n", "tbv", "tqv", "ignore"])
    df = df[["open_time", "open", "high", "low", "close", "volume", "close_time"]]
    df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df[df["close_time"] < int(time.time() * 1000)].drop_duplicates("open_time").reset_index(drop=True)

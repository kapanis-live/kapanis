"""US stocks: prices (Tiingo with a free key, Yahoo as fallback), NYSE calendar, market regime, technicals.

Symbols are stored as "AAPL.US" (piyasa "ABD", currency USD) so they never collide with crypto tickers.
Only CLOSED bars are used. US stocks are traded medium/long term here: weekly bias, daily setup/timing.

Tiingo free tier: 1000 requests/day and 50 distinct symbols/hour. Every Tiingo call is counted (settings.json);
near the limit, and for bulk scans (the S&P 100 ranking), Yahoo is used instead.
"""
import asyncio
import logging
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

import alerts_store
import config
import market
import structure

log = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Kapanis US reader)"}
TIINGO = "https://api.tiingo.com"
TIINGO_DAILY_LIMIT = 900        # stay under the 1000/day free limit
TIINGO_SYMBOLS_PER_HOUR = 45    # stay under 50 distinct symbols/hour
CACHE_SECONDS = {"1h": 300, "1d": 900, "1wk": 3600, "1mo": 6 * 3600}
_cache: dict[tuple, tuple[float, pd.DataFrame]] = {}

# NYSE 2026: closed days and 13:00 half days (nyse.com holiday calendar).
CLOSED_2026 = {"2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
               "2026-09-07", "2026-11-26", "2026-12-25"}
HALF_2026 = {"2026-11-27", "2026-12-24"}

INDEXES = {"SPY": "S&P 500 (SPY)", "QQQ": "Nasdaq-100 (QQQ)"}
SECTOR_ETF = {"Technology": "XLK", "Financial Services": "XLF", "Healthcare": "XLV", "Consumer Cyclical": "XLY",
              "Consumer Defensive": "XLP", "Energy": "XLE", "Industrials": "XLI", "Communication Services": "XLC",
              "Utilities": "XLU", "Real Estate": "XLRE", "Basic Materials": "XLB"}
SP100 = """AAPL ABBV ABT ACN ADBE AIG AMD AMGN AMT AMZN AVGO AXP BA BAC BK BKNG BLK BMY C CAT CL CMCSA COF COP COST CRM
CSCO CVS CVX DE DHR DIS DUK EMR FDX GD GE GILD GM GOOGL GS HD HON IBM INTC INTU ISRG JNJ JPM KO LIN LLY LMT LOW MA MCD
MDLZ MDT MET META MMM MO MRK MS MSFT NEE NFLX NKE NOW NVDA ORCL PEP PFE PG PLTR PM PYPL QCOM RTX SBUX SCHW SO SPG T TGT
TMO TMUS TSLA TXN UBER UNH UNP UPS USB V VZ WFC WMT XOM""".split()


def ticker(sym: str) -> str:
    return sym.upper().removesuffix(".US")


def key(t: str) -> str:
    return ticker(t) + ".US"


def now_ny() -> datetime:
    return datetime.now(NY)


def trading_day(d: date | None = None) -> bool:
    d = d or now_ny().date()
    return d.weekday() < 5 and d.isoformat() not in CLOSED_2026


def session_open(when: datetime | None = None) -> bool:
    w = (when or now_ny()).astimezone(NY)
    close = (13, 0) if w.date().isoformat() in HALF_2026 else (16, 0)
    return trading_day(w.date()) and (9, 30) <= (w.hour, w.minute) < close


def session_text() -> str:
    w = now_ny()
    tr = datetime.now(ZoneInfo("Europe/Istanbul"))
    offset = round((tr.utcoffset() - w.utcoffset()).total_seconds() / 3600)
    return (f"ABD seansı {'AÇIK' if session_open() else 'kapalı'} · New York {w.strftime('%H:%M')} · "
            f"Türkiye saatiyle {9 + offset}:30–{16 + offset}:00")


# --- Tiingo budget ---------------------------------------------------------------------------------------

def _tiingo_ok(sym: str) -> bool:
    if not config.TIINGO_API_KEY:
        return False
    s = alerts_store.load_settings()
    u = s.get("tiingo_kullanim", {})
    today, hour = now_ny().date().isoformat(), now_ny().strftime("%Y-%m-%dT%H")
    if u.get("gun") != today:
        u = {"gun": today, "istek": 0, "saat": hour, "semboller": []}
    if u.get("saat") != hour:
        u["saat"], u["semboller"] = hour, []
    if u["istek"] >= TIINGO_DAILY_LIMIT:
        return False
    if sym not in u["semboller"] and len(u["semboller"]) >= TIINGO_SYMBOLS_PER_HOUR:
        return False
    u["istek"] += 1
    if sym not in u["semboller"]:
        u["semboller"].append(sym)
    s["tiingo_kullanim"] = u
    alerts_store.save_settings(s)
    return True


def tiingo_usage() -> dict:
    return alerts_store.load_settings().get("tiingo_kullanim", {})


# --- bars ----------------------------------------------------------------------------------------------

def _closed(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Keep only finished bars. df has open_time (ms UTC)."""
    if df.empty:
        return df
    start = pd.to_datetime(df.open_time, unit="ms", utc=True).dt.tz_convert(NY)
    now = now_ny()
    if interval == "1h":
        end = start + pd.Timedelta(hours=1)
        cap = start.dt.normalize() + pd.Timedelta(hours=16)
        end = end.where(end <= cap, cap)
        done = end + pd.Timedelta(minutes=2) <= now
    elif interval == "1d":
        final = (now.hour, now.minute) >= (16, 15)
        done = (start.dt.date < now.date()) | ((start.dt.date == now.date()) & final)
    elif interval == "1wk":
        week_end = (start + pd.Timedelta(days=4)).dt.date
        done = (week_end < now.date()) | ((week_end == now.date()) & ((now.hour, now.minute) >= (16, 15)))
    else:  # 1mo
        done = (start + pd.DateOffset(months=1)).dt.date <= now.date()
    out = df[done.values].copy()
    out["close_time"] = out["open_time"]
    return out.reset_index(drop=True)


async def _yahoo(client: httpx.AsyncClient, sym: str, interval: str) -> pd.DataFrame:
    rng = {"1h": "6mo", "1d": "5y", "1wk": "10y", "1mo": "20y"}[interval]
    r = await client.get(YAHOO + sym, params={"interval": interval, "range": rng}, headers=HEADERS, timeout=20)
    if r.status_code == 404:
        raise market.SymbolNotFound(sym)
    r.raise_for_status()
    res = (r.json().get("chart") or {}).get("result")
    if not res:
        raise market.SymbolNotFound(sym)
    res = res[0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({"ts": res.get("timestamp", []), "open": q["open"], "high": q["high"], "low": q["low"],
                       "close": q["close"], "volume": q["volume"]}).dropna()
    df["open_time"] = (df.pop("ts").astype("int64") * 1000)
    return df


async def _tiingo_daily(client: httpx.AsyncClient, sym: str) -> pd.DataFrame:
    start = (now_ny() - timedelta(days=5 * 365)).date().isoformat()
    r = await client.get(f"{TIINGO}/tiingo/daily/{sym.lower()}/prices", timeout=20,
                         params={"startDate": start, "token": config.TIINGO_API_KEY})
    if r.status_code == 404:
        raise market.SymbolNotFound(sym)
    r.raise_for_status()
    rows = r.json()
    df = pd.DataFrame([{"open_time": int(pd.Timestamp(x["date"][:10], tz=NY).timestamp() * 1000),
                        "open": x["adjOpen"], "high": x["adjHigh"], "low": x["adjLow"], "close": x["adjClose"],
                        "volume": x["adjVolume"]} for x in rows])
    return df


async def _tiingo_hourly(client: httpx.AsyncClient, sym: str) -> pd.DataFrame:
    start = (now_ny() - timedelta(days=60)).date().isoformat()
    r = await client.get(f"{TIINGO}/iex/{sym.lower()}/prices", timeout=20,
                         params={"startDate": start, "resampleFreq": "1hour", "columns": "open,high,low,close,volume",
                                 "token": config.TIINGO_API_KEY})
    r.raise_for_status()
    return pd.DataFrame([{"open_time": int(pd.Timestamp(x["date"]).timestamp() * 1000), "open": x["open"],
                          "high": x["high"], "low": x["low"], "close": x["close"], "volume": x.get("volume") or 0}
                         for x in r.json()])


async def fetch(client: httpx.AsyncClient, sym: str, interval: str, bulk: bool = False) -> pd.DataFrame:
    """Closed bars for a US ticker or ETF/index (SPY, ^VIX). bulk=True keeps Tiingo for single-symbol use."""
    sym = ticker(sym)
    ck = (sym, interval)
    hit = _cache.get(ck)
    if hit and time.time() - hit[0] < CACHE_SECONDS[interval]:
        return hit[1].copy()
    df = None
    if not bulk and not sym.startswith("^") and interval in ("1d", "1h") and _tiingo_ok(sym):
        try:
            df = await (_tiingo_daily(client, sym) if interval == "1d" else _tiingo_hourly(client, sym))
        except market.SymbolNotFound:
            raise
        except Exception as e:
            log.warning("Tiingo %s %s failed, Yahoo fallback: %s", sym, interval, e)
            df = None
    if df is None or df.empty:
        df = await _yahoo(client, sym, interval)
    df = _closed(df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float}), interval)
    _cache[ck] = (time.time(), df)
    return df.copy()


async def last_price(client: httpx.AsyncClient, sym: str) -> float:
    sym = ticker(sym)
    if not sym.startswith("^") and _tiingo_ok(sym):
        try:
            r = await client.get(f"{TIINGO}/iex/", params={"tickers": sym.lower(), "token": config.TIINGO_API_KEY}, timeout=15)
            r.raise_for_status()
            row = r.json()[0]
            price = row.get("tngoLast") or row.get("last") or row.get("prevClose")
            if price:
                return float(price)
        except Exception as e:
            log.warning("Tiingo last price %s failed: %s", sym, e)
    r = await client.get(YAHOO + sym, params={"interval": "1d", "range": "5d"}, headers=HEADERS, timeout=15)
    if r.status_code == 404:
        raise market.SymbolNotFound(sym)
    r.raise_for_status()
    res = (r.json().get("chart") or {}).get("result")
    if not res:
        raise market.SymbolNotFound(sym)
    return float(res[0]["meta"]["regularMarketPrice"])


async def day_quote(client: httpx.AsyncClient, sym: str) -> dict:
    price = await last_price(client, sym)
    d = await fetch(client, sym, "1d")
    today = now_ny().date()
    last_day = datetime.fromtimestamp(int(d.open_time.iloc[-1]) / 1000, NY).date() if len(d) else None
    # After the close the last daily bar IS today's session: its change is measured against the bar before it.
    same_as_last = len(d) and abs(price / float(d.close.iloc[-1]) - 1) < 1e-5
    prev = (float(d.close.iloc[-2]) if (last_day == today or same_as_last) and len(d) > 1 else float(d.close.iloc[-1])) if len(d) else None
    return {"fiyat": price, "onceki_kapanis": prev, "gun": last_day.isoformat() if last_day else None,
            "bugun_islem": session_open()}


_sec_map: dict | None = None


async def is_us_ticker(client: httpx.AsyncClient, t: str) -> bool:
    """True if SEC lists the ticker (company) or Yahoo returns a US-exchange chart (ETF)."""
    global _sec_map
    t = ticker(t)
    if _sec_map is None:
        try:
            r = await client.get("https://www.sec.gov/files/company_tickers.json", timeout=20,
                                 headers={"User-Agent": config.SEC_USER_AGENT})
            _sec_map = {v["ticker"].upper(): v["cik_str"] for v in r.json().values()}
        except Exception as e:
            log.warning("SEC ticker map failed: %s", e)
            _sec_map = {}
    if t in _sec_map:
        return True
    try:
        r = await client.get(YAHOO + t, params={"interval": "1d", "range": "5d"}, headers=HEADERS, timeout=15)
        meta = r.json()["chart"]["result"][0]["meta"]
        return meta.get("currency") == "USD" and meta.get("exchangeName") in ("NMS", "NYQ", "PCX", "NGM", "NCM", "ASE", "BTS")
    except Exception:
        return False


def cik(t: str) -> int | None:
    return (_sec_map or {}).get(ticker(t))


# --- market regime ---------------------------------------------------------------------------------------

def _trend_state(d: pd.DataFrame) -> dict:
    last = d.iloc[-1]
    above200 = bool(last.close > last.sma200) if last.sma200 == last.sma200 else False
    golden = bool(last.sma50 > last.sma200) if last.sma50 == last.sma50 and last.sma200 == last.sma200 else False
    state = "AÇIK" if above200 and golden else "TEMKİNLİ" if above200 else "KAPALI"
    return {"durum": state, "kapanis": market._num(last.close), "sma50": market._num(last.sma50),
            "sma200": market._num(last.sma200), "rsi14": market._num(last.rsi14),
            "getiri_3a_yuzde": round((last.close / d.close.iloc[-64] - 1) * 100, 2) if len(d) > 64 else None}


async def regime(client: httpx.AsyncClient) -> dict:
    """S&P 500 / Nasdaq-100 gate, VIX, 10Y yield, dollar index. The index gate is the US 'BTC gate'."""
    out = {}
    for sym, name in INDEXES.items():
        try:
            out[sym] = {"ad": name, **_trend_state(market.add_indicators(await fetch(client, sym, "1d", bulk=True)))}
        except Exception as e:
            out[sym] = {"ad": name, "hata": str(e)[:60]}
    for sym, name in (("^VIX", "VIX"), ("^TNX", "ABD 10Y faiz"), ("DX-Y.NYB", "Dolar endeksi")):
        try:
            d = await fetch(client, sym, "1d", bulk=True)
            out[name] = {"son": market._num(d.close.iloc[-1]), "20g_once": market._num(d.close.iloc[-21]) if len(d) > 21 else None}
        except Exception as e:
            out[name] = {"hata": str(e)[:60]}
    states = [out[s].get("durum") for s in INDEXES]
    out["kapi"] = "KAPALI" if "KAPALI" in states else "TEMKİNLİ" if "TEMKİNLİ" in states else "AÇIK"
    vix = (out.get("VIX") or {}).get("son")
    if vix is not None:
        out["vix_yorum"] = "yüksek oynaklık/korku" if vix >= 25 else "sakin" if vix < 15 else "normal"
    out["seans"] = session_text()
    return out


# --- technicals for one stock ------------------------------------------------------------------------------

def _rs(stock: pd.Series, bench: pd.Series, days: int) -> float | None:
    if len(stock) <= days or len(bench) <= days:
        return None
    return round(((stock.iloc[-1] / stock.iloc[-days - 1]) - (bench.iloc[-1] / bench.iloc[-days - 1])) * 100, 1)


def technicals(d: pd.DataFrame, w: pd.DataFrame, m: pd.DataFrame | None, spy: pd.DataFrame, qqq: pd.DataFrame,
               sector: pd.DataFrame | None) -> dict:
    """Monthly/weekly/daily trend, moving averages, 52w high, relative strength, base/breakout,
    volatility contraction, accumulation volume, earnings-style gaps. Pure."""
    last = d.iloc[-1]
    close = float(last.close)
    ma10w = w.close.rolling(10).mean().iloc[-1] if len(w) >= 10 else None
    high52 = float(d.close.tail(252).max())
    sma50_rising = len(d) > 70 and d.sma50.iloc[-1] > d.sma50.iloc[-21]
    out = {
        "kapanis": market._num(close),
        "trend": {tf: structure.structure(df)["trend"] for tf, df in (("aylık", m), ("haftalık", w), ("günlük", d))
                  if df is not None and len(df) >= 30},
        "sma50": market._num(last.sma50), "sma200": market._num(last.sma200),
        "sma50_yukseliyor": bool(sma50_rising), "ma10h": market._num(ma10w),
        "hizalama": ("fiyat > 50G > 200G (güçlü)" if close > last.sma50 > last.sma200 else
                     "fiyat < 50G < 200G (zayıf)" if close < last.sma50 < last.sma200 else "karışık"),
        "zirveye_uzaklik_yuzde": round((close / high52 - 1) * 100, 1),
        "rs_spy": {k: _rs(d.close, spy.close, n) for k, n in (("3a", 63), ("6a", 126), ("12a", 252))},
        "rs_qqq_6a": _rs(d.close, qqq.close, 126),
        "rs_sektor_6a": _rs(d.close, sector.close, 126) if sector is not None and len(sector) else None,
        "stage": structure.stage(w),
    }
    # volatility contraction: the last three pullbacks from swing highs getting smaller
    sw = structure.swings(d.tail(180), 3, 3)
    depths = []
    for i in range(1, len(sw)):
        if sw[i - 1]["tur"] == "tepe" and sw[i]["tur"] == "dip":
            depths.append(round((sw[i]["fiyat"] / sw[i - 1]["fiyat"] - 1) * 100, 1))
    depths = depths[-3:]
    out["geri_cekilmeler_yuzde"] = depths
    out["volatilite_daralmasi"] = bool(len(depths) == 3 and depths[0] < depths[1] < depths[2] < 0)
    # accumulation: volume on up days vs down days over 50 sessions
    tail = d.tail(50)
    up_v = tail.volume[tail.close > tail.close.shift()].sum()
    dn_v = tail.volume[tail.close < tail.close.shift()].sum()
    out["yukselis_dusus_hacim_orani_50g"] = round(float(up_v / dn_v), 2) if dn_v else None
    # the largest gap in 90 sessions (typically earnings) and whether it held
    g = d.tail(91).reset_index(drop=True)
    gaps = (g.open / g.close.shift() - 1) * 100
    if len(gaps.dropna()):
        i = int(gaps.abs().idxmax())
        size = float(gaps.iloc[i])
        if abs(size) >= 4:
            prev_close = float(g.close.iloc[i - 1])
            held = close > prev_close if size > 0 else close < prev_close
            out["buyuk_bosluk"] = {"gun_once": len(g) - 1 - i, "yuzde": round(size, 1),
                                   "hacim_kat": round(float(g.volume.iloc[i] / g.volume.iloc[max(0, i - 20):i].mean()), 1) if i > 1 else None,
                                   "korundu": bool(held)}
    return out

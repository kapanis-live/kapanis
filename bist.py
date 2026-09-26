"""Borsa İstanbul: data (Yahoo Finance, free, ~15 min delayed), index gate and BIST-specific rules.

BIST differs from crypto and gets its own strategy:
- Free data is ~15 minutes delayed, so decisions use DAILY closes (setup) and 1-HOUR closes (entry
  timing), never 15m candles.
- Session 10:00-18:00 TR, weekdays only. No new closed bar = nothing to decide (covers holidays).
- The gate is the BIST 100 index (XU100) instead of BTC; USD/TRY is watched because a rising stock can
  be a falling one in dollar terms when the lira weakens fast.
- Overnight gap risk: minimum R/R 1.5. Daily ±10% price limits: never chase a stock near its ceiling.
- Whole lots only; fees (commission + BSMV) and slippage are in the backtest.
"""
import logging
import time
from datetime import datetime, timedelta

import httpx
import pandas as pd

import alerts_store
import config
import market
from macro import TR

log = logging.getLogger(__name__)

YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Kapanis BIST reader)"}
INDEX = "XU100.IS"
FX = "USDTRY=X"
DATA_DELAY_MIN = 16          # Yahoo BIST quotes lag ~15 minutes
SESSION_END = (18, 0)        # continuous trading ends 18:00; closing auction follows
DAILY_FINAL_AFTER = (18, 30)  # today's daily bar counts as closed after auction + delay
HALF_DAYS_2026 = {"2026-03-19", "2026-05-26", "2026-10-28"}
CLOSED_DAYS_2026 = {"2026-01-01", "2026-03-20", "2026-04-23", "2026-05-01", "2026-05-19",
                    "2026-05-27", "2026-05-28", "2026-05-29", "2026-07-15", "2026-10-29"}
_cache: dict[tuple, tuple[float, pd.DataFrame]] = {}
CACHE_SECONDS = {"1h": 240, "1d": 900, "1wk": 3600}


def yahoo_symbol(ticker: str) -> str:
    t = ticker.upper().strip()
    return t if t.endswith(".IS") or "=" in t else f"{t}.IS"  # "=": FX (USDTRY=X) and futures (GC=F)


def ticker(symbol: str) -> str:
    return symbol.upper().removesuffix(".IS")


def now_tr() -> datetime:
    return datetime.now(TR)


def watchlist() -> list[str]:
    """Official BIST 30 changes effective 2026-10-01: TRMET replaces DSTKF."""
    if not calendar_current():
        raise RuntimeError("BIST 30 listesi ve seans takvimi 2027 için güncellenmeli")
    names = list(config.BIST_WATCHLIST)
    if now_tr().date().isoformat() >= "2026-10-01":
        names = ["TRMET" if name == "DSTKF" else name for name in names]
    return names


def calendar_current() -> bool:
    return now_tr().year <= 2026


def session_open(when: datetime | None = None) -> bool:
    w = when or now_tr()
    day = w.date().isoformat()
    end = (13, 0) if day in HALF_DAYS_2026 else SESSION_END
    return trading_day(w) and (10, 0) <= (w.hour, w.minute) < end


def trading_day(when: datetime | None = None) -> bool:
    w = when or now_tr()
    return w.year <= 2026 and w.weekday() < 5 and w.date().isoformat() not in CLOSED_DAYS_2026


def _check(r: httpx.Response, symbol: str) -> None:
    """Yahoo answers an unknown ticker with 404; report it like an empty chart result."""
    if r.status_code == 404:
        raise market.SymbolNotFound(yahoo_symbol(symbol))
    r.raise_for_status()


async def fetch(client: httpx.AsyncClient, symbol: str, interval: str) -> pd.DataFrame:
    """Closed bars only, same columns as market.fetch_klines (times in ms)."""
    symbol = yahoo_symbol(symbol)
    key = (symbol, interval)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS.get(interval, 300):
        return hit[1].copy()
    rng = {"1h": "6mo", "1d": "2y", "1wk": "5y"}[interval]
    r = await client.get(YAHOO + symbol, params={"interval": interval, "range": rng}, headers=HEADERS, timeout=20)
    _check(r, symbol)
    res = (r.json().get("chart") or {}).get("result")
    if not res:
        raise market.SymbolNotFound(symbol)
    res = res[0]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({"ts": res.get("timestamp", []), "open": q["open"], "high": q["high"],
                       "low": q["low"], "close": q["close"], "volume": q["volume"]}).dropna()
    if df.empty:
        return df
    start = pd.to_datetime(df.ts, unit="s", utc=True).dt.tz_convert(TR)
    now = now_tr()
    if interval == "1h":
        # Bars start at :30; the last one of the day ends at the 18:00 session close.
        end = start + pd.Timedelta(hours=1)
        cap = start.dt.normalize() + pd.Timedelta(hours=SESSION_END[0], minutes=SESSION_END[1])
        half = start.dt.strftime("%Y-%m-%d").isin(HALF_DAYS_2026)
        cap = cap.where(~half, start.dt.normalize() + pd.Timedelta(hours=13))
        end = end.where(end <= cap, cap)
        # Yahoo also emits an 18:00 price-only row: start == capped end, volume 0.
        # It is not a trading hour and must never become an entry signal.
        closed = (start < cap) & (end + pd.Timedelta(minutes=DATA_DELAY_MIN) <= now)
        if symbol != INDEX:
            closed &= df.volume > 0
    elif interval == "1d":
        day = start.dt.date
        final_after = (13, 30) if now.date().isoformat() in HALF_DAYS_2026 else DAILY_FINAL_AFTER
        final = (now.hour, now.minute) >= final_after
        closed = (day < now.date()) | ((day == now.date()) & final)
        end = start.dt.normalize() + pd.Timedelta(hours=18, minutes=10)
        half = start.dt.strftime("%Y-%m-%d").isin(HALF_DAYS_2026)
        end = end.where(~half, start.dt.normalize() + pd.Timedelta(hours=13))
    else:  # weekly: closed once the week is over
        end = start + pd.Timedelta(days=7)
        closed = end <= now
    # Explicit ms conversion: pandas may keep second resolution, so astype(int64) isn't safe.
    epoch = pd.Timestamp(0, tz="UTC")
    df["open_time"] = ((start - epoch) // pd.Timedelta(milliseconds=1)).astype("int64")
    df["close_time"] = ((end - epoch) // pd.Timedelta(milliseconds=1)).astype("int64")
    df = df[closed.values][["open_time", "open", "high", "low", "close", "volume", "close_time"]]
    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float}).reset_index(drop=True)
    _cache[key] = (time.time(), df)
    return df.copy()


async def last_price(client: httpx.AsyncClient, symbol: str) -> float:
    """Latest (delayed) trade price."""
    r = await client.get(YAHOO + yahoo_symbol(symbol), params={"interval": "1d", "range": "5d"}, headers=HEADERS, timeout=15)
    _check(r, symbol)
    res = (r.json().get("chart") or {}).get("result")
    if not res:
        raise market.SymbolNotFound(symbol)
    return float(res[0]["meta"]["regularMarketPrice"])


def _num(x):
    return market._num(x)


async def index_gate(client: httpx.AsyncClient) -> dict:
    """BIST 100 trend (the BIST version of the BTC gate) and USD/TRY pressure."""
    d = market.add_indicators(await fetch(client, INDEX, "1d"))
    h = market.add_indicators(await fetch(client, INDEX, "1h"))
    last = d.iloc[-1]
    above50 = bool(last.close > last.sma50) if last.sma50 == last.sma50 else False
    above200 = bool(last.close > last.sma200) if last.sma200 == last.sma200 else False
    state = "AÇIK" if above50 else ("TEMKİNLİ" if above200 else "KAPALI")
    out = {"durum": state, "xu100_kapanis": _num(last.close), "sma50": _num(last.sma50), "sma200": _num(last.sma200),
           "rsi14": _num(last.rsi14), "saatlik_kapanis": _num(h.iloc[-1].close) if not h.empty else None,
           "saatlik_sma20": _num(h.iloc[-1].sma20) if not h.empty else None,
           "getiri_20g_yuzde": round((last.close / d.close.iloc[-21] - 1) * 100, 2) if len(d) > 21 else None}
    try:
        fx = await fetch(client, FX, "1d")
        chg5 = (fx.close.iloc[-1] / fx.close.iloc[-6] - 1) * 100 if len(fx) > 6 else None
        out["usdtry"] = _num(fx.close.iloc[-1])
        out["usdtry_5g_yuzde"] = None if chg5 is None else round(chg5, 2)
        out["usdtry_baski"] = bool(chg5 is not None and chg5 > config.BIST_FX_STRESS_PCT)
        if out["getiri_20g_yuzde"] is not None and len(fx) > 21:
            fx20 = (fx.close.iloc[-1] / fx.close.iloc[-21] - 1) * 100
            out["xu100_dolar_bazli_20g_yuzde"] = round((1 + out["getiri_20g_yuzde"] / 100) / (1 + fx20 / 100) * 100 - 100, 2)
    except Exception as e:
        out["usdtry_hata"] = str(e)[:80]
    return out


def lots_for(budget_tl: float, price: float) -> int:
    return int(budget_tl // price) if price > 0 else 0


def budget_tl() -> int | None:
    """BIST capital is entered in Telegram and persisted in settings.json."""
    value = alerts_store.load_settings().get("bist_budget_tl")
    return value if type(value) is int and value > 0 else None


def tranche_tl(risk_off: bool, volume_ok: bool, open_tl: float) -> tuple[float, list[str]]:
    """BIST first tranche in TL, decided in code. Separate budget from crypto."""
    budget = budget_tl()
    if budget is None:
        return 0.0, ["BIST bütçesi girilmedi: /bist butce 5000"]
    tl = budget * config.BIST_FIRST_TRANCHE_PCT / 100
    notes = []
    if risk_off or not volume_ok:
        tl = budget * config.BIST_REDUCED_TRANCHE_PCT / 100
        notes.append("piyasa/kur temkinli" if risk_off else "hacim teyidi yok")
    room = budget * config.BIST_FIRST_TRANCHE_PCT / 100 - open_tl
    if room < tl:
        tl = max(room, 0.0)
        notes.append(f"açık BIST pozisyonları {open_tl:,.0f} TL: ilk kademe limiti dolu/kısıldı")
    return round(tl, 2), notes


async def snapshot(client: httpx.AsyncClient, tick: str) -> dict:
    """What DeepSeek sees for a BIST stock: daily/hourly/weekly summaries, zones, index and FX."""
    sym = yahoo_symbol(tick)
    out = {"sembol": sym, "piyasa": "BIST", "veri_gecikmesi_dk": 15, "zaman_dilimleri": {}}
    frames = {}
    for tf in ("1wk", "1d", "1h"):
        df = market.add_indicators(await fetch(client, sym, tf))
        frames[tf] = df
        if not df.empty:
            out["zaman_dilimleri"][{"1wk": "1w"}.get(tf, tf)] = market.summarize(df, with_vwap=False)
    d = frames["1d"]
    if not d.empty:
        out["destek_direnc"] = market.sr_zones(d, frames["1wk"], float(d.close.iloc[-1]), float(d.atr14.iloc[-1]))
        out["gunluk_degisim_yuzde"] = round((d.close.iloc[-1] / d.close.iloc[-2] - 1) * 100, 2) if len(d) > 1 else None
        out["son_5_gun"] = [{"tarih": datetime.fromtimestamp(r.open_time / 1000, TR).strftime("%d.%m"),
                             "k": _num(r.close), "hacim": _num(r.volume), "hacim_ort20": _num(r.vol_avg20)}
                            for r in d.tail(5).itertuples()]
        idx = market.add_indicators(await fetch(client, INDEX, "1d"))
        if len(d) > 21 and len(idx) > 21:
            out["goreceli_guc_20g_puan"] = round(((d.close.iloc[-1] / d.close.iloc[-21]) -
                                                 (idx.close.iloc[-1] / idx.close.iloc[-21])) * 100, 2)
    return out


# --- Turkish macro calendar: the BIST twin of the US CPI/FOMC gate ------------------------------
# TCMB PPK rate decisions (14:00 TR), source: tcmb.gov.tr 2026 schedule. TÜİK CPI: 3rd of each
# month 10:00 (next business day if the 3rd is a weekend).
PPK_DATES = ["2026-01-22", "2026-03-12", "2026-04-22", "2026-06-11", "2026-07-23", "2026-09-10",
             "2026-10-22", "2026-12-10"]
TR_EVENT_BLOCK_HOURS = 2      # no new BIST entry this close before a release
TR_EVENT_AFTER_MIN = 30       # ...nor in the first half hour after it


def tr_events(days: int = 45) -> list[dict]:
    now = now_tr()
    out = [{"olay": "TCMB faiz kararı (PPK)", "tr_zaman": datetime.fromisoformat(d).replace(hour=14, tzinfo=TR)}
           for d in PPK_DATES]
    for k in range(-1, days // 28 + 2):
        y, m = now.year + (now.month - 1 + k) // 12, (now.month - 1 + k) % 12 + 1
        day = datetime(y, m, 3, 10, 0, tzinfo=TR)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        out.append({"olay": "TÜİK enflasyon (TÜFE)", "tr_zaman": day})
    horizon = now + timedelta(days=days)
    rows = [e for e in out if now - timedelta(hours=1) <= e["tr_zaman"] <= horizon]
    rows.sort(key=lambda e: e["tr_zaman"])
    return [{"olay": e["olay"], "tr_zaman": e["tr_zaman"].isoformat(),
             "kalan_saat": round((e["tr_zaman"] - now).total_seconds() / 3600, 1)} for e in rows]


def tr_event_risk() -> dict | None:
    """The release that currently blocks a new BIST entry, if any."""
    for e in tr_events(3):
        h = e["kalan_saat"]
        if -TR_EVENT_AFTER_MIN / 60 <= h <= TR_EVENT_BLOCK_HOURS:
            return e
    return None


async def day_quote(client: httpx.AsyncClient, symbol: str) -> dict:
    """Latest (delayed) price and the previous session's close, for daily % change."""
    r = await client.get(YAHOO + yahoo_symbol(symbol), params={"interval": "1d", "range": "5d"}, headers=HEADERS, timeout=15)
    _check(r, symbol)
    res = (r.json().get("chart") or {}).get("result")
    if not res:
        raise market.SymbolNotFound(symbol)
    res = res[0]
    closes = [(t, c) for t, c in zip(res.get("timestamp", []), res["indicators"]["quote"][0]["close"]) if c is not None]
    price = float(res["meta"]["regularMarketPrice"])
    last_day = datetime.fromtimestamp(closes[-1][0], TR).date() if closes else None
    prev = float(closes[-2][1]) if len(closes) > 1 else None
    return {"fiyat": price, "onceki_kapanis": prev, "gun": last_day.isoformat() if last_day else None,
            "bugun_islem": last_day == now_tr().date()}

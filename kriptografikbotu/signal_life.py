"""How long a buy signal stays valid, and what the card should say about it now.

A signal ("sinyal aktif" card with Aldım/Pas) is only worth acting on while:
- no candle of its timeframe has closed below the stop level since the signal (close-only rule) -> else GEÇERSİZ
- fewer than LIFE_CANDLES candles have closed since the signal                                  -> else SÜRESİ DOLDU
- the live price is not more than LATE_PCT above the signal close                                -> else GEÇ KALDIN
The card's top button shows this state with the signal's age and the live price; a background job
keeps it current. Pressing Aldım on a stale signal asks first and marks the buy as a late entry.
Also: the track record of past signals (hit rate, average R) that every new card shows.
"""
from datetime import datetime

import httpx

import alerts_store
import backtest
import bist
import market
import positions

LIFE_CANDLES = {"15m": 8, "1h": 6, "4h": 4, "1d": 3}   # 15m: 2 hours
LATE_PCT = {"KRIPTO": 1.0, "BIST": 1.5, "ABD": 1.5}
WATCH_HOURS = 24         # cards older than this are no longer updated
STOP_COOLDOWN_HOURS = 4  # no new signal on a pair for this long after its stop was hit
MIN_TRACK = 5            # decided signals before a hit rate is shown

LABELS = {"aktif": "🟢 Aktif", "gec": "🏃 GEÇ KALDIN", "suresi_doldu": "⌛ SÜRESİ DOLDU", "gecersiz": "⛔ GEÇERSİZ"}
FINAL = {"suresi_doldu", "gecersiz"}


def classify(entry: float, stop: float | None, closes_since: list[float], price: float, tf: str, market_name: str) -> str:
    """Pure: state of a signal from the closes after it and the live price."""
    if stop is not None and any(c < stop for c in closes_since):
        return "gecersiz"
    if len(closes_since) >= LIFE_CANDLES.get(tf, 8):
        return "suresi_doldu"
    if price > entry * (1 + LATE_PCT.get(market_name, 1.0) / 100):
        return "gec"
    return "aktif"


async def evaluate(client: httpx.AsyncClient, d: dict) -> dict:
    """{durum, etiket, fiyat, fark_yuzde, yas_dk} for one decision."""
    mkt = d.get("piyasa") or "KRIPTO"
    tf = d.get("timeframe") or "15m"
    entry = float(d["kapanis"])
    if mkt == "BIST":
        df = await bist.fetch(client, d["symbol"], "1h" if tf == "1h" else "1d")
        price = await bist.last_price(client, d["symbol"])
    else:
        df = await market.fetch_klines(client, d["symbol"], tf, limit=60)
        price = await market.last_price(client, d["symbol"])
    signal_ms = int(d.get("mum_ms") or 0)
    step = backtest.TF_MS.get(tf, 900_000)
    now_ms = datetime.now().timestamp() * 1000
    # closed candles that opened after the signal candle
    closes = [float(r.close) for r in df.itertuples() if int(r.open_time) > signal_ms and int(r.open_time) + step <= now_ms]
    state = classify(entry, d.get("iptal"), closes, price, tf, mkt)
    age = (alerts_store.now_tr() - datetime.fromisoformat(d["zaman"])).total_seconds() / 60
    return {"durum": state, "etiket": LABELS[state], "fiyat": price, "fark_yuzde": round((price / entry - 1) * 100, 2),
            "yas_dk": round(age)}


def _age(minutes: float) -> str:
    return f"{minutes:.0f} dk" if minutes < 90 else f"{minutes / 60:.1f} sa"


def status_text(life: dict) -> str:
    return f"{life['etiket']} · {_age(life['yas_dk'])} önce · şimdi {life['fiyat']:.6g} ({life['fark_yuzde']:+.2f}%)"


def stop_cooldown(pair: str, now: datetime | None = None) -> str | None:
    """A stop on this pair within STOP_COOLDOWN_HOURS -> reason text, else None."""
    now = now or alerts_store.now_tr()
    for p in reversed(positions.load()):
        if p["pair"] != pair or p["durum"] != "kapali" or not p.get("kapanis_zamani"):
            continue
        stopped = (p.get("neden") or "") in ("stop", "iptal") or \
            (p.get("stop") is not None and p.get("kapanis_fiyat") is not None and p["kapanis_fiyat"] <= p["stop"])
        hours = (now - datetime.fromisoformat(p["kapanis_zamani"])).total_seconds() / 3600
        if stopped and 0 <= hours < STOP_COOLDOWN_HOURS:
            return f"{pair} {hours:.1f} saat önce stop oldu; {STOP_COOLDOWN_HOURS} saat yeni giriş yok (intikam işlemi koruması)"
    return None


def track_record(decisions: list[dict] | None = None, market_name: str = "KRIPTO", last: int = 50) -> dict:
    """Past gate-passed buy signals with a final close-based result."""
    ds = [d for d in (decisions if decisions is not None else positions.load_decisions())
          if d.get("karar") == "AL" and (d.get("kapi") or {}).get("ok") and (d.get("piyasa") or "KRIPTO") == market_name
          and (d.get("sonuc") or {}).get("sonuc") in ("hedef", "stop")][-last:]
    rs = [d["sonuc"]["R"] for d in ds if d["sonuc"].get("R") is not None]
    hits = sum(d["sonuc"]["sonuc"] == "hedef" for d in ds)
    return {"n": len(ds), "hedef": hits, "stop": len(ds) - hits,
            "isabet_yuzde": round(hits / len(ds) * 100) if ds else None,
            "ort_R": round(sum(rs) / len(rs), 2) if rs else None}


def track_line(market_name: str = "KRIPTO") -> str:
    t = track_record(market_name=market_name)
    if t["n"] < MIN_TRACK:
        return f"📏 Geçmiş: {t['n']} sonuçlanmış sinyal var; isabet oranı {MIN_TRACK} sinyalden sonra gösterilir (/karne)."
    return (f"📏 Geçmiş (son {t['n']} sinyal, kapanışla): hedef {t['hedef']} / stop {t['stop']} · isabet %{t['isabet_yuzde']}"
            + (f" · ort. {t['ort_R']:+.2f}R" if t["ort_R"] is not None else ""))


def midas_stop(stop: float | None, atr: float | None) -> tuple[float, float] | None:
    """The bot's stop is close-based; a broker stop (Midas) fires on a touch, so it belongs a bit lower:
    stop − 0.5 ATR (tight) .. stop − 1 ATR (wide)."""
    if stop is None or not atr or atr != atr:
        return None
    return stop - atr, stop - 0.5 * atr

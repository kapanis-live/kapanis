"""Exit / top analysis for open positions — the same engine for crypto and BIST.

Answers "should I hold, trim or sell, and where do I move my stop?" with rules computed in code:
- top signs (trim): stretched far above SMA20, RSI exhaustion with a red candle, bearish RSI divergence,
  price inside a resistance zone while in profit, high-volume distribution candle, target reached
- trend damage: close below SMA20 (trim), close below SMA50 or the trailing stop (sell), stop broken (sell)
- stop management: chandelier trailing stop (highest close since entry − 3×ATR) and breakeven at +1R,
  only ever suggested upward (goalpost rule)
Crypto is judged on 4h closes (zones from 4h + 1d), BIST on daily closes (zones from 1d + 1w).
Only CLOSED candles are used. No DeepSeek call here.
"""
import logging
from datetime import datetime

import httpx
import pandas as pd

import bist
import us
import config
import market

log = logging.getLogger(__name__)

STRETCH_ATR = 2.5
RSI_HOT = 75
TRAIL_ATR = 3.0
VERDICT_RANK = {"TUT": 0, "KISMİ SAT": 1, "SAT": 2}
TF_LABEL = {"1wk": "haftalık", "1d": "günlük", "4h": "4s", "1h": "1s"}


def _nan(x) -> bool:
    return x is None or x != x


def _g(x) -> str:
    return "—" if x is None else f"{x:.6g}"


async def frames(client: httpx.AsyncClient, pos: dict) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Signal frame + higher frame for zones, per market."""
    if pos.get("piyasa") == "ABD":  # US: medium/long term, weekly closes like BIST
        sig = market.add_indicators(await us.fetch(client, pos["symbol"], "1wk", bulk=True))
        htf = market.add_indicators(await us.fetch(client, pos["symbol"], "1d"))
        if len(sig) >= 30:
            return sig, htf, "1wk"
        return htf, sig, "1d"
    if pos.get("piyasa") == "BIST":
        # BIST is held medium/long-term: judged on WEEKLY closes, zones from daily + weekly pivots.
        sig = market.add_indicators(await bist.fetch(client, pos["symbol"], "1wk"))
        htf = market.add_indicators(await bist.fetch(client, pos["symbol"], "1d"))
        if len(sig) >= 30:
            return sig, htf, "1wk"
        return htf, sig, "1d"  # too little weekly history (new listing): daily closes
    sig = market.add_indicators(await market.fetch_klines(client, pos["symbol"], "4h"))
    if len(sig) < 30:
        # Newly listed coin: not enough 4h closes yet. Judge on 1h closes with 4h zones until history builds up.
        htf = sig
        sig = market.add_indicators(await market.fetch_klines(client, pos["symbol"], "1h"))
        return sig, htf, "1h"
    htf = market.add_indicators(await market.fetch_klines(client, pos["symbol"], "1d"))
    return sig, htf, "4h"


def analyze(pos: dict, sig: pd.DataFrame, htf: pd.DataFrame, tf: str, price: float | None = None) -> dict:
    """Deterministic exit verdict for one open position."""
    last, prev = sig.iloc[-1], sig.iloc[-2]
    tf = TF_LABEL.get(tf, tf)  # user-facing name: "haftalık", "günlük", "4s", "1s"
    close = float(last.close)
    price = float(price) if price is not None else close
    entry, stop, target = pos["giris"], pos.get("stop"), pos.get("hedef")
    atr = None if _nan(last.atr14) else float(last.atr14)
    risk0 = entry - pos["stop_ilk"] if pos.get("stop_ilk") else None
    r_now = (close - entry) / risk0 if risk0 and risk0 > 0 else None
    in_profit = close > entry
    signals = []  # (level, text) level: sat | kismi | bilgi

    # --- hard exits -------------------------------------------------------------------
    if stop is not None and close < stop:
        signals.append(("sat", f"Stop {_g(stop)} altında kapanış ({_g(close)}) — kural: sat"))
    if not _nan(last.sma50) and close < last.sma50:
        signals.append(("sat", f"{tf} kapanış SMA50 ({_g(float(last.sma50))}) altında — orta vadeli trend bozuldu"))
    elif not _nan(last.sma20) and close < last.sma20:
        signals.append(("kismi", f"{tf} kapanış SMA20 ({_g(float(last.sma20))}) altında — trend zayıfladı, azalt"))

    # Chandelier trailing stop from the highest close since the position was opened.
    opened_ms = int(datetime.fromisoformat(pos["acilis"]).timestamp() * 1000)
    raw_tf = next((k for k, v in TF_LABEL.items() if v == tf), tf)
    since = sig[sig.open_time >= opened_ms - _tf_ms(raw_tf)]
    window = since if len(since) >= 2 else sig.tail(22)
    peak_close = float(window.close.max())
    trail = peak_close - TRAIL_ATR * atr if atr else None
    if trail is not None and close < trail:
        signals.append(("sat", f"İz süren stop ({_g(trail)}) kapanışla kırıldı — tepeden {TRAIL_ATR:g}×ATR geri çekilme"))

    # --- top signs (trim) -----------------------------------------------------------------
    if atr and not _nan(last.sma20):
        stretch = (close - float(last.sma20)) / atr
        if stretch >= STRETCH_ATR:
            signals.append(("kismi", f"Aşırı uzama: fiyat SMA20'nin {stretch:.1f}×ATR üstünde — tepe bölgesi, kısmi kâr"))
    rsi = None if _nan(last.rsi14) else float(last.rsi14)
    red = close < float(last.open)
    if rsi is not None and rsi >= RSI_HOT:
        signals.append(("kismi" if red else "bilgi",
                        f"RSI {rsi:.0f}" + (" + kırmızı mum: yorulma işareti" if red else ": aşırı alım (henüz dönüş mumu yok)")))
    div = _bearish_divergence(sig)
    if div:
        signals.append(("kismi", div))
    if not _nan(last.vol_avg20) and last.vol_avg20 and red and last.volume > 1.5 * last.vol_avg20:
        body_low = (close - float(last.low)) <= (float(last.high) - float(last.low)) / 3
        if body_low and in_profit:
            signals.append(("kismi", f"Hacimli dağıtım mumu (hacim x{last.volume / last.vol_avg20:.1f}, dipte kapanış)"))
    if target is not None and close >= target:
        signals.append(("kismi", f"Hedef {_g(target)} kapanışla görüldü — kâr al ya da stopu yukarı taşı"))

    zones = market.sr_zones(sig, htf, close, atr or 0.0, top=2)
    top_zone = zones["direncler"][0] if zones["direncler"] else None
    if top_zone and in_profit and atr:
        if top_zone["alt"] - 0.5 * atr <= close <= top_zone["ust"]:
            # information only: in the 2026-09 history test these zones turned price back no more often than random levels
            signals.append(("bilgi", f"Direnç bölgesi yakınında: {_g(top_zone['alt'])}–{_g(top_zone['ust'])} "
                                     f"({top_zone['dokunma']} dokunma; testte rastgele seviyeden farksız, karar için kullanma)"))

    # The trend rule's exit (research status: keeps you out of big falls, gains not proven): a DAILY close below the lowest low of the previous 10 days.
    trend_exit = daily_trend_exit(htf if pos.get("piyasa", "KRIPTO") == "KRIPTO" else None)
    if trend_exit and close < trend_exit:
        signals.append(("kismi", f"Günlük kapanış 10 günün dibinin ({_g(trend_exit)}) altında — trend kuralı "
                                 "burada çıkar (geçmişte büyük düşüşlerin çoğundan böyle uzak durdu; kazandırdığı kanıtlanmadı)"))

    # --- stop suggestion (never down) -----------------------------------------------------
    candidates = []
    if trail is not None and trail < close:
        candidates.append((trail, f"iz süren stop (en yüksek kapanış {_g(peak_close)} − {TRAIL_ATR:g}×ATR)"))
    if r_now is not None and r_now >= 1 and (stop is None or stop < entry):
        candidates.append((entry, "başa baş (+1R'ye ulaşıldı, risk sıfırlanır)"))
    suggestion = None
    best = max(candidates, key=lambda c: c[0], default=None)
    if best and (stop is None or best[0] > stop):
        suggestion = {"seviye": round(best[0], 6), "neden": best[1]}

    levels = [lvl for lvl, _ in signals]
    verdict = "SAT" if "sat" in levels else "KISMİ SAT" if "kismi" in levels else "TUT"
    peak_hint = None
    if top_zone:
        peak_hint = f"{_g(top_zone['alt'])}–{_g(top_zone['ust'])} ({top_zone['dokunma']} dokunma, %{top_zone['uzaklik_yuzde']:+.1f})"
    elif zones.get("not"):
        peak_hint = f"yapısal direnç yok; son tepe kapanış {_g(peak_close)}"
    return {
        "karar": verdict, "sinyaller": signals, "stop_onerisi": suggestion, "olasi_tepe": peak_hint,
        "kapanis": close, "fiyat": price, "zaman_dilimi": tf, "mum": int(last.open_time),
        "R": None if r_now is None else round(r_now, 2),
        "kar_yuzde": round((price / entry - 1) * 100, 2), "rsi": None if rsi is None else round(rsi, 1),
        "destekler": zones["destekler"][:1],
        "trend_cikis": trend_exit,
    }


def daily_trend_exit(daily: pd.DataFrame | None) -> float | None:
    """Lowest low of the 10 daily candles before the last closed one (the trend rule's exit level)."""
    if daily is None or len(daily) < 12:
        return None
    return float(daily.low.iloc[-11:-1].min())


def _tf_ms(tf: str) -> int:
    return {"4h": 14_400_000, "1d": 86_400_000, "1wk": 604_800_000}.get(tf, 3_600_000)


def _bearish_divergence(sig: pd.DataFrame) -> str | None:
    """Higher close in the last 5 candles than in the 15 before, but a lower RSI peak."""
    if len(sig) < 25 or sig.rsi14.tail(20).isna().any():
        return None
    recent, before = sig.tail(5), sig.iloc[-20:-5]
    if recent.close.max() > before.close.max() and recent.rsi14.max() <= before.rsi14.max() - 3:
        return (f"Negatif uyumsuzluk: fiyat yeni tepe yaptı ({_g(float(recent.close.max()))}) ama RSI düşük tepe "
                f"({recent.rsi14.max():.0f} < {before.rsi14.max():.0f})")
    return None


def text(pos: dict, a: dict, price: float | None = None) -> str:
    cur = pos.get("para", "USD")
    icon = {"TUT": "🟢", "KISMİ SAT": "🟠", "SAT": "🔴"}[a["karar"]]
    qty = f"{pos['adet']:.0f} adet" if pos.get("piyasa") == "BIST" else f"{pos['adet']:.6g} adet"
    pnl = (a["fiyat"] - pos["giris"]) * pos["adet"]
    lines = [f"{icon} #{pos['id']} {pos['pair']} — KARAR: {a['karar']}",
             f"{qty} @ {_g(pos['giris'])} → {_g(a['fiyat'])} ({a['kar_yuzde']:+.2f}%, {pnl:+,.2f} {cur}"
             + (f", {a['R']:+.2f}R" if a["R"] is not None else "") + f") · {a['zaman_dilimi']} kapanışı"]
    mark = {"sat": "❗", "kismi": "⚠️", "bilgi": "ℹ️"}
    lines += [f"{mark[lvl]} {t}" for lvl, t in a["sinyaller"]] or ["✅ Çıkış işareti yok: trend ve momentum sağlam."]
    if a["olasi_tepe"]:
        lines.append(f"🎯 Olası tepe/direnç: {a['olasi_tepe']}")
    if a["stop_onerisi"]:
        lines.append(f"🔒 Stop önerisi: {_g(pos.get('stop'))} → {_g(a['stop_onerisi']['seviye'])} ({a['stop_onerisi']['neden']})")
    elif pos.get("stop") is not None:
        lines.append(f"🔒 Stop {_g(pos['stop'])} yerinde (aşağı çekilmez)")
    if a["karar"] == "KISMİ SAT":
        lines.append("Öneri: pozisyonun yarısını sat, kalanın stopunu yukarı çek.")
    elif a["karar"] == "SAT":
        lines.append("Öneri: kural gereği sat. Tutarsan kural ihlali olarak kaydedilir.")
    return "\n".join(lines)


async def review(pos: dict) -> tuple[dict, str] | None:
    if pos.get("piyasa") == "DIGER":
        return None  # gold/FX savings: no exit verdicts
    async with httpx.AsyncClient() as client:
        try:
            sig, htf, tf = await frames(client, pos)
            if pos.get("piyasa") == "ABD":
                price = await us.last_price(client, pos["symbol"])
            elif pos.get("piyasa") == "BIST":
                price = await bist.last_price(client, pos["symbol"])
            else:
                price = await market.last_price(client, pos["symbol"])
        except Exception as e:
            log.warning("Exit review failed for %s: %s", pos["pair"], e)
            return None
    if len(sig) < 30:
        return None
    a = analyze(pos, sig, htf, tf, price)
    return a, text(pos, a)

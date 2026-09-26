"""Binance USDT-M futures public data: funding, open interest, long/short ratio. No key needed.

Spot is what the user trades; futures data only shows how crowded leveraged traders are.
"""
import logging

import httpx

log = logging.getLogger(__name__)

FAPI = "https://fapi.binance.com"


async def _get(client: httpx.AsyncClient, path: str, **params):
    r = await client.get(f"{FAPI}{path}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


async def snapshot(client: httpx.AsyncClient, coin: str) -> dict:
    symbol = f"{coin}USDT"
    try:
        premium = await _get(client, "/fapi/v1/premiumIndex", symbol=symbol)
        history = await _get(client, "/fapi/v1/fundingRate", symbol=symbol, limit=100)
        oi = await _get(client, "/futures/data/openInterestHist", symbol=symbol, period="1h", limit=25)
        ls = await _get(client, "/futures/data/globalLongShortAccountRatio", symbol=symbol, period="1h", limit=25)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            return {"hata": f"{symbol} vadeli kontratı yok"}
        raise

    rates = [float(h["fundingRate"]) for h in history]
    interval_h = round((history[-1]["fundingTime"] - history[-2]["fundingTime"]) / 3_600_000) if len(history) > 1 else 8
    per_day = 24 / interval_h if interval_h else 3
    last_7d = rates[-int(7 * per_day):]
    current = float(premium["lastFundingRate"])

    out = {
        "funding_son_yuzde": round(current * 100, 4),
        "baz_yuzde": round((float(premium["markPrice"]) / float(premium["indexPrice"]) - 1) * 100, 4),
        "funding_araligi_saat": interval_h,
        "funding_7g_ort_yuzde": round(sum(last_7d) / len(last_7d) * 100, 4) if last_7d else None,
        "funding_yillik_yuzde": round(current * per_day * 365 * 100, 1),
        "funding_100_kayit_yuzdelik": round(sum(r <= current for r in rates) / len(rates) * 100) if rates else None,
    }
    if len(oi) >= 2:
        first, last = float(oi[0]["sumOpenInterestValue"]), float(oi[-1]["sumOpenInterestValue"])
        out["acik_pozisyon_usd"] = round(last)
        out["acik_pozisyon_24s_degisim_yuzde"] = round((last / first - 1) * 100, 2)
    if ls:
        out["long_short_hesap_orani"] = float(ls[-1]["longShortRatio"])
        out["long_short_24s_once"] = float(ls[0]["longShortRatio"])
    try:  # taker buy/sell volume ratio: a free CVD/delta proxy (>1 = aggressive buyers dominate)
        taker = await _get(client, "/futures/data/takerlongshortRatio", symbol=symbol, period="1h", limit=24)
        ratios = [float(t["buySellRatio"]) for t in taker]
        if ratios:
            out["alim_satim_orani_24s"] = round(sum(ratios) / len(ratios), 3)
            out["alim_satim_orani_son_1s"] = round(ratios[-1], 3)
    except Exception as e:
        log.debug("Taker ratio failed for %s: %s", symbol, e)
    out["fiyat_oi_yorumu"] = price_oi_hint(out)
    out["yorum_ipucu"] = crowding_hint(out)
    return out


def price_oi_hint(d: dict) -> str | None:
    """Price/OI relation needs the 24h price change, which the caller adds; here only the OI side."""
    oi = d.get("acik_pozisyon_24s_degisim_yuzde")
    if oi is None:
        return None
    return ("OI 24 saatte artıyor: yeni pozisyon açılıyor" if oi > 2 else
            "OI 24 saatte azalıyor: pozisyon kapanıyor (short kapatma ya da long tasfiyesi)" if oi < -2 else "OI yatay")


def crowding_hint(d: dict) -> str:
    """Deterministic label so the model doesn't have to guess thresholds."""
    f = d.get("funding_son_yuzde")
    if f is None:
        return "veri yok"
    per_8h = f * 8 / d.get("funding_araligi_saat", 8)
    if per_8h >= 0.05:
        return "funding çok yüksek: long tarafı kalabalık, long tasfiye riski"
    if per_8h <= -0.02:
        return "funding negatif: short tarafı kalabalık, short sıkışması olasılığı"
    return "funding normal"

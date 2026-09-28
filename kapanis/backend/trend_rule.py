"""The one rule that passed our history test: crypto trend following (Donchian 20/10 with a 200-day filter).

Rule (daily closes only):
- IN  when the close is above the highest high of the previous 20 days AND above the 200-day average
- OUT when the close is below the lowest low of the previous 10 days
Test (2026-09-28, kriptografikbotu/research/lab_risk.py): 76 Binance coins since 2019, including coins that collapsed or were
delisted (LUNA, FTT, SRM, ...), 0.1 % cost per side, median per coin, period split in two halves.
It beat buy & hold AND random in/out timing with the same time in the market in both halves. It does not beat
buy & hold on BIST (TL inflation lifts everything), so it is offered for crypto only.
"""
import time

import chart_data

EVIDENCE = {
    "tarih": "2026-09-28",
    "evren": "76 kripto (batan/listeden çıkanlar dahil), 2019'dan bugüne, günlük kapanış, işlem başı %0,1 maliyet",
    "satirlar": [
        {"donem": "1. yarı", "kural": 23.8, "al_tut": 0.2, "rastgele": 0.1, "kural_dusus": -60.5, "al_tut_dusus": -93.4, "piyasada": 23},
        {"donem": "2. yarı", "kural": -0.7, "al_tut": -37.4, "rastgele": -7.7, "kural_dusus": -55.6, "al_tut_dusus": -90.3, "piyasada": 17},
    ],
    "not": ("Değerler coin başına ortanca yıllık getiri (%) ve en büyük düşüş (%). 'Rastgele' = aynı sürede piyasada kalan "
            "rastgele giriş-çıkış. Kural yükselişlerin bir kısmını yakaladı, çöküşlerin çoğundan uzak durdu; "
            "ikinci yarıda yine de kazandırmadı, sadece daha az kaybettirdi. Geçmiş sonuç geleceği garanti etmez. "
            "BIST'te al-tut'u geçemedi, bu yüzden yalnız kriptoda sunuluyor."),
}
UNIVERSE = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "TRX", "AVAX", "LINK", "DOT", "BCH", "LTC", "NEAR",
            "UNI", "ATOM", "ETC", "FIL", "AAVE", "ARB", "OP", "SUI", "INJ", "HBAR", "XLM", "APT", "TIA", "ONDO", "HYPE", "ENA"]
_cache: dict = {}


def state(candles: list[dict], sma200: list, now: float | None = None) -> dict | None:
    """Pure: where the rule stands on the last CLOSED daily candle (crypto closes at 00:00 UTC)."""
    now = time.time() if now is None else now
    closed = [i for i, c in enumerate(candles) if c["t"] + 86400 <= now]
    if len(closed) < 21:
        return None
    i = closed[-1]
    c = candles[i]
    hi20 = max(x["h"] for x in candles[i - 20:i])
    lo10 = min(x["l"] for x in candles[i - 10:i])
    s200 = sma200[i] if i < len(sma200) else None
    # replay the rule over the visible history so "in trend" means the rule would be holding now
    hold, since = False, None
    for j in range(20, i + 1):
        cj = candles[j]["c"]
        h20 = max(x["h"] for x in candles[j - 20:j])
        l10 = min(x["l"] for x in candles[j - 10:j])
        s = sma200[j] if j < len(sma200) else None
        if not hold and s is not None and cj > h20 and cj > s:
            hold, since = True, candles[j]["t"]
        elif hold and cj < l10:
            hold, since = False, candles[j]["t"]
    entry_today = hold and since == c["t"]
    exit_today = not hold and since == c["t"]
    return {"kapanis": c["c"], "mum": c["t"], "ust20": hi20, "alt10": lo10, "sma200": s200, "trendde": hold,
            "giris_bugun": entry_today, "cikis_bugun": exit_today, "degisim": since,
            "girise_uzaklik_yuzde": None if hold else round((max(hi20, s200 or 0) / c["c"] - 1) * 100, 2),
            "cikisa_uzaklik_yuzde": round((c["c"] / lo10 - 1) * 100, 2) if hold else None}


async def coin_state(code: str) -> dict | None:
    doc = await chart_data.chart(code, "1d", "KRIPTO")
    return state(doc["candles"], doc.get("sma200") or [])


async def universe_states() -> list[dict]:
    hit = _cache.get("u")
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    out = []
    for code in UNIVERSE:
        try:
            s = await coin_state(code)
        except Exception:
            continue
        if s:
            out.append({"kod": code, **s})
    _cache["u"] = (time.time(), out)
    return out

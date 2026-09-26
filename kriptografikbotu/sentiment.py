"""Crypto crowd sentiment, free sources, cached 30 minutes:
- alternative.me Fear & Greed index (0 = extreme fear, 100 = extreme greed), daily.
- CoinGecko /global: BTC and ETH dominance, stablecoin share of total market cap, 24h market cap change.
Rising stablecoin share = money waiting on the side (or fleeing); rising BTC dominance = altcoins weaker.
Used by the crypto gate only for sizing (extreme greed -> smaller first tranche), never as an entry reason.
"""
import logging
import time

import httpx

import config

log = logging.getLogger(__name__)

TTL = 30 * 60
STABLES = ("usdt", "usdc", "dai", "usde", "fdusd")
LABELS = {"Extreme Fear": "aşırı korku", "Fear": "korku", "Neutral": "nötr", "Greed": "açgözlülük",
          "Extreme Greed": "aşırı açgözlülük"}
_cache: tuple[float, dict] | None = None


async def summary(force: bool = False) -> dict:
    global _cache
    if _cache and not force and time.time() - _cache[0] < TTL:
        return _cache[1]
    out: dict = {}
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0 (Kapanis)"}) as client:
        try:
            r = await client.get("https://api.alternative.me/fng/", params={"limit": 8}, timeout=15)
            rows = r.json()["data"]
            now, week = int(rows[0]["value"]), int(rows[-1]["value"])
            out["korku_acgozluluk"] = {"deger": now, "etiket": LABELS.get(rows[0]["value_classification"],
                                                                          rows[0]["value_classification"]),
                                       "7g_once": week, "7g_degisim": now - week}
        except Exception as e:
            out["korku_acgozluluk"] = {"hata": str(e)[:80]}
        try:
            r = await client.get("https://api.coingecko.com/api/v3/global", timeout=15)
            g = r.json()["data"]
            pct = g["market_cap_percentage"]
            out["piyasa"] = {"btc_dominans": round(pct.get("btc", 0), 2), "eth_dominans": round(pct.get("eth", 0), 2),
                             "stablecoin_payi": round(sum(pct.get(s, 0) for s in STABLES), 2),
                             "toplam_deger_24s_yuzde": round(g.get("market_cap_change_percentage_24h_usd") or 0, 2)}
        except Exception as e:
            out["piyasa"] = {"hata": str(e)[:80]}
    if _cache and "hata" in out.get("korku_acgozluluk", {}) and "hata" not in _cache[1].get("korku_acgozluluk", {}):
        out["korku_acgozluluk"] = {**_cache[1]["korku_acgozluluk"], "not": "önbellekten (kaynak şu an yanıt vermiyor)"}
    _cache = (time.time(), out)
    return out


def greed_note(s: dict) -> str | None:
    """Reason to shrink the first tranche, or None."""
    f = s.get("korku_acgozluluk", {})
    if f.get("deger") is not None and f["deger"] >= config.GREED_EXTREME:
        return f"Korku & Açgözlülük {f['deger']} ({f['etiket']})"
    return None


def gate_check(s: dict) -> tuple[bool, str]:
    """Non-blocking line for the crypto gate."""
    f = s.get("korku_acgozluluk", {})
    if "deger" not in f:
        return False, "Korku & Açgözlülük alınamadı"
    v = f["deger"]
    detail = f"Korku & Açgözlülük {v} ({f['etiket']}, 7g {f['7g_degisim']:+d})"
    if v >= config.GREED_EXTREME:
        return False, detail + ": kalabalık iyimser, ilk kademe küçültüldü"
    if v <= config.FEAR_EXTREME:
        return False, detail + ": kırılımlar sık başarısız olur, teyide ekstra dikkat"
    return True, detail


def text(s: dict) -> str:
    f, m = s.get("korku_acgozluluk", {}), s.get("piyasa", {})
    lines = ["🌡 KRİPTO DUYGU"]
    if "deger" in f:
        bar = "▰" * round(f["deger"] / 10) + "▱" * (10 - round(f["deger"] / 10))
        lines.append(f"Korku & Açgözlülük: {f['deger']} {bar} {f['etiket']} (7 gün önce {f['7g_once']}, {f['7g_degisim']:+d})")
    else:
        lines.append(f"Korku & Açgözlülük: alınamadı ({f.get('hata', '?')})")
    if "btc_dominans" in m:
        lines.append(f"BTC dominansı %{m['btc_dominans']} · ETH %{m['eth_dominans']} · stablecoin payı %{m['stablecoin_payi']}")
        lines.append(f"Toplam piyasa değeri 24s %{m['toplam_deger_24s_yuzde']:+.2f}")
    else:
        lines.append(f"Dominans: alınamadı ({m.get('hata', '?')})")
    lines.append(f"Kural: ≥{config.GREED_EXTREME} aşırı açgözlülükte ilk kademe {config.REDUCED_TRANCHE_USD} USD'ye iner; "
                 f"≤{config.FEAR_EXTREME} aşırı korkuda sadece uyarı. Duygu tek başına AL/SAT sebebi değildir.")
    return "\n".join(lines)

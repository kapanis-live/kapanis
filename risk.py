"""Portfolio concentration, correlation and value history (for the chart).

- Weights are computed in TL: crypto USD values are converted with today's USD/TRY.
- Sector map covers BIST 30 (plus a few frequent names); anything else is "Diğer".
- Correlation uses 30 daily returns; crypto and BIST are aligned on common dates (weekdays).
  Two assets above HIGH_CORR move as one position, whatever their names.
- History is rebuilt from positions and daily closes (no snapshots needed): for each day, the value of
  what was held that day and what it had cost.
"""
import logging
from datetime import datetime, timedelta
from itertools import combinations

import httpx
import pandas as pd

import assets
import bist
import us
import config
import market
from macro import TR

log = logging.getLogger(__name__)

SECTORS = {
    "AKBNK": "Banka", "GARAN": "Banka", "ISCTR": "Banka", "VAKBN": "Banka", "YKBNK": "Banka", "HALKB": "Banka",
    "TSKB": "Banka", "KCHOL": "Holding", "SAHOL": "Holding", "DOHOL": "Holding", "AGHOL": "Holding",
    "ALARK": "Holding", "THYAO": "Havacılık", "PGSUS": "Havacılık", "TAVHL": "Havacılık",
    "FROTO": "Otomotiv", "TOASO": "Otomotiv", "DOAS": "Otomotiv", "OTKAR": "Otomotiv",
    "EREGL": "Demir-çelik", "KRDMD": "Demir-çelik", "TRALT": "Madencilik", "TRMET": "Madencilik",
    "KOZAL": "Madencilik", "KOZAA": "Madencilik", "TUPRS": "Enerji", "PETKM": "Kimya", "SASA": "Kimya",
    "GUBRF": "Kimya", "HEKTS": "Kimya", "ASTOR": "Enerji ekipmanı", "ENKAI": "İnşaat", "EKGYO": "GYO",
    "BIMAS": "Perakende", "MGROS": "Perakende", "SOKM": "Perakende", "AEFES": "Gıda-içecek",
    "CCOLA": "Gıda-içecek", "ULKER": "Gıda-içecek", "TCELL": "Telekom", "TTKOM": "Telekom",
    "ASELS": "Savunma", "SISE": "Cam-sanayi", "DSTKF": "Finans", "ARCLK": "Dayanıklı tüketim",
    "VESTL": "Dayanıklı tüketim", "ENJSA": "Enerji", "AKSEN": "Enerji", "ODAS": "Enerji",
}


def sector(pos_or_group: dict) -> str:
    if pos_or_group.get("piyasa", "KRIPTO") == "KRIPTO":
        return "Kripto"
    if assets.is_other(pos_or_group):
        return assets.ASSETS.get(pos_or_group["symbol"], {}).get("sektor", "Diğer")
    if pos_or_group.get("piyasa") == "ABD":
        return "ABD hisse"
    return SECTORS.get(bist.ticker(pos_or_group["symbol"]), "Diğer")


def name(g: dict) -> str:
    if assets.is_other(g):
        return assets.name(g["symbol"])
    if g.get("piyasa") == "ABD":
        return us.ticker(g["symbol"])
    return bist.ticker(g["symbol"]) if g.get("piyasa") == "BIST" else g["pair"].split("/")[0]


def concentration(groups: list[dict], usdtry: float | None) -> dict:
    """groups: [{symbol, pair, piyasa, deger (own currency)}]. Pure: weights and warnings."""
    rows = []
    for g in groups:
        tl = g["deger"] if g.get("piyasa") in ("BIST", assets.MARKET) else (g["deger"] * usdtry if usdtry else None)
        if tl is not None:
            rows.append({**g, "tl": tl})
    total = sum(r["tl"] for r in rows)
    if not total:
        return {"toplam_tl": 0, "varliklar": [], "sektorler": [], "uyarilar": []}
    holdings = sorted(({"ad": name(r), "yuzde": round(r["tl"] / total * 100, 1), "tl": r["tl"],
                      "sektor": sector(r)} for r in rows), key=lambda a: -a["yuzde"])
    sectors: dict[str, float] = {}
    for a in holdings:
        sectors[a["sektor"]] = sectors.get(a["sektor"], 0) + a["yuzde"]
    sector_rows = sorted(({"sektor": k, "yuzde": round(v, 1)} for k, v in sectors.items()), key=lambda s: -s["yuzde"])
    warns = []
    if len(holdings) > 1:
        for a in holdings:
            if a["yuzde"] > config.MAX_ASSET_PCT:
                warns.append(f"{a['ad']} portföyün %{a['yuzde']:g}'i (sınır %{config.MAX_ASSET_PCT}): tek varlığa bağımlısın")
        for s in sector_rows:
            if s["yuzde"] > config.MAX_SECTOR_PCT and sum(a["sektor"] == s["sektor"] for a in holdings) > 1:
                warns.append(f"{s['sektor']} portföyün %{s['yuzde']:g}'i (sınır %{config.MAX_SECTOR_PCT}): aynı haberle hepsi birlikte düşer")
    return {"toplam_tl": round(total, 2), "varliklar": holdings, "sektorler": sector_rows, "uyarilar": warns}


async def daily_closes(client: httpx.AsyncClient, g: dict) -> pd.Series:
    """Closed daily closes indexed by TR date (ISO string)."""
    if assets.is_other(g):
        df = await assets.daily(client, g["symbol"])
    elif g.get("piyasa") == "ABD":
        df = await us.fetch(client, g["symbol"], "1d", bulk=True)
    elif g.get("piyasa") == "BIST":
        df = await bist.fetch(client, g["symbol"], "1d")
    else:
        df = await market.fetch_klines(client, g["symbol"], "1d")
    days = [datetime.fromtimestamp(int(t) / 1000, TR).date().isoformat() for t in df.open_time]
    return pd.Series(df.close.astype(float).values, index=days)


def correlations(closes: dict[str, pd.Series], days: int = 30) -> dict:
    """Pairwise correlation of daily returns on common dates. Pure."""
    frame = pd.DataFrame(closes).dropna()
    rets = frame.pct_change().dropna().tail(days)
    if len(rets) < 15 or rets.shape[1] < 2:
        return {"gun": len(rets), "ciftler": [], "yuksek": [], "kripto_ort": None}
    corr = rets.corr()
    pairs = [{"a": a, "b": b, "r": round(float(corr.loc[a, b]), 2)} for a, b in combinations(corr.columns, 2)]
    pairs.sort(key=lambda p: -p["r"])
    return {"gun": len(rets), "ciftler": pairs, "yuksek": [p for p in pairs if p["r"] >= config.HIGH_CORR]}


def correlation_warnings(corr: dict, crypto_names: set[str]) -> list[str]:
    warns = []
    crypto_pairs = [p for p in corr["ciftler"] if p["a"] in crypto_names and p["b"] in crypto_names]
    if len(crypto_names) >= 2 and crypto_pairs:
        avg = sum(p["r"] for p in crypto_pairs) / len(crypto_pairs)
        corr["kripto_ort"] = round(avg, 2)
        if avg >= config.HIGH_CORR:
            warns.append(f"{len(crypto_names)} coinin ortalama korelasyonu {avg:.2f}: fiilen TEK pozisyon, "
                         "çeşitlendirme sanma")
    for p in corr["yuksek"]:
        if not (p["a"] in crypto_names and p["b"] in crypto_names):
            warns.append(f"{p['a']} ile {p['b']} korelasyonu {p['r']:.2f}: birlikte hareket ediyorlar")
    return warns


async def full_report(groups: list[dict], usdtry: float | None) -> dict:
    conc = concentration(groups, usdtry)
    closes = {}
    async with httpx.AsyncClient() as client:
        for g in groups[:12]:
            try:
                closes[name(g)] = await daily_closes(client, g)
            except Exception as e:
                log.warning("Closes failed for %s: %s", g["pair"], e)
    corr = correlations(closes)
    crypto = {name(g) for g in groups if g.get("piyasa", "KRIPTO") == "KRIPTO"} & set(closes)
    conc["korelasyon"] = corr
    conc["uyarilar"] += correlation_warnings(corr, crypto)
    return conc


async def value_history(items: list[dict], days: int = 90) -> list[dict]:
    """[{tarih, deger_tl, maliyet_tl}] for the last `days` days from positions (open and closed)."""
    today = datetime.now(TR).date()
    start = today - timedelta(days=days)
    relevant = [p for p in items if not p.get("kapanis_zamani") or p["kapanis_zamani"][:10] >= start.isoformat()]
    if not relevant:
        return []
    closes, fx = {}, None
    async with httpx.AsyncClient() as client:
        for sym in {p["symbol"] for p in relevant}:
            p = next(x for x in relevant if x["symbol"] == sym)
            try:
                closes[sym] = await daily_closes(client, {"symbol": sym, "piyasa": p.get("piyasa", "KRIPTO"), "pair": p["pair"]})
            except Exception as e:
                log.warning("History closes failed for %s: %s", sym, e)
        try:
            fx = await daily_closes(client, {"symbol": bist.FX, "piyasa": "BIST", "pair": bist.FX})
        except Exception as e:
            log.warning("USD/TRY history failed: %s", e)
    out = []
    for i in range(days + 1):
        day = (start + timedelta(days=i)).isoformat()
        rate = _asof(fx, day) if fx is not None else None
        value = cost = 0.0
        held = False
        for p in relevant:
            opened, closed = p["acilis"][:10], (p.get("kapanis_zamani") or "9999")[:10]
            if not opened <= day < closed or p["symbol"] not in closes:
                continue
            px = _asof(closes[p["symbol"]], day)
            if px is None:
                continue
            k = 1.0 if p.get("para") == "TL" else rate
            if k is None:
                continue
            value += px * p["adet"] * k
            cost += p["giris"] * p["adet"] * k
            held = True
        if held:
            out.append({"tarih": day, "deger_tl": round(value, 2), "maliyet_tl": round(cost, 2)})
    return out


def _asof(series: pd.Series, day: str) -> float | None:
    s = series[series.index <= day]
    return float(s.iloc[-1]) if len(s) else None

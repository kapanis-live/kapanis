"""Gold and foreign currency as portfolio assets (piyasa "DIGER", priced in TL).

- Gram altın = gold futures (Yahoo GC=F, USD per troy ounce) × USD/TRY ÷ 31.1035. This is the
  international (has) gram price; Kapalıçarşı and bank prices differ by their spread.
- Dolar = USDTRY=X, Euro = EURTRY=X.
Daily closes use bist.fetch (closed daily bars only), so charts, correlation and history work the same
way as for stocks. These assets get no TUT/SAT exit verdicts: they are savings, not trades.
TEFAS funds are not supported: tefas.gov.tr blocks automated requests.
"""
import httpx
import pandas as pd

import bist

MARKET = "DIGER"
OUNCE_GRAMS = 31.1035
ASSETS = {
    "GRAM_ALTIN": {"ad": "Gram altın", "birim": "gram", "emoji": "🥇", "sektor": "Altın"},
    "USD": {"ad": "Dolar", "birim": "USD", "emoji": "💵", "sektor": "Döviz"},
    "EUR": {"ad": "Euro", "birim": "EUR", "emoji": "💶", "sektor": "Döviz"},
}
ALIASES = {"ALTIN": "GRAM_ALTIN", "GRAM": "GRAM_ALTIN", "GRAMALTIN": "GRAM_ALTIN", "GRAM_ALTIN": "GRAM_ALTIN",
           "GOLD": "GRAM_ALTIN", "XAU": "GRAM_ALTIN", "DOLAR": "USD", "USD": "USD", "USDTRY": "USD",
           "EURO": "EUR", "EUR": "EUR", "EURTRY": "EUR", "AVRO": "EUR"}


def normalize(code: str) -> str | None:
    t = code.strip().upper().replace(" ", "").replace("İ", "I")
    return ALIASES.get(t)


def is_other(p: dict) -> bool:
    return p.get("piyasa") == MARKET


def name(sym: str) -> str:
    return ASSETS.get(sym, {}).get("ad", sym)


async def daily(client: httpx.AsyncClient, sym: str) -> pd.DataFrame:
    """Closed daily bars (open_time ms, close) in TL."""
    if sym == "USD":
        return await bist.fetch(client, bist.FX, "1d")
    if sym == "EUR":
        return await bist.fetch(client, "EURTRY=X", "1d")
    gold = await bist.fetch(client, "GC=F", "1d")
    fx = await bist.fetch(client, bist.FX, "1d")
    g = gold[["open_time", "close"]].copy()
    g["gun"] = pd.to_datetime(g.open_time, unit="ms", utc=True).dt.tz_convert(bist.TR).dt.date
    f = fx[["open_time", "close"]].copy()
    f["gun"] = pd.to_datetime(f.open_time, unit="ms", utc=True).dt.tz_convert(bist.TR).dt.date
    m = g.merge(f[["gun", "close"]].rename(columns={"close": "kur"}), on="gun", how="inner")
    m["close"] = m["close"] * m["kur"] / OUNCE_GRAMS
    return m[["open_time", "close"]].reset_index(drop=True)


async def last_price(client: httpx.AsyncClient, sym: str) -> float:
    if sym == "USD":
        return await bist.last_price(client, bist.FX)
    if sym == "EUR":
        return await bist.last_price(client, "EURTRY=X")
    return await bist.last_price(client, "GC=F") * await bist.last_price(client, bist.FX) / OUNCE_GRAMS


async def quote(client: httpx.AsyncClient, sym: str) -> dict:
    """Same shape as bist.day_quote: live price and the previous daily close."""
    price = await last_price(client, sym)
    d = await daily(client, sym)
    prev = float(d.close.iloc[-1]) if len(d) else None
    return {"fiyat": price, "onceki_kapanis": prev, "gun": None, "bugun_islem": True}

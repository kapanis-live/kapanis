"""Free RSS news: fetch, merge duplicates across sources, tag, and rate relevance.

Adapted from the Crypto Radar project with one deliberate change: source reliability
(how official the outlet is) and crypto relevance (does it touch crypto/markets at all)
are separate fields. An official White House post about a museum visit is reliable
but irrelevant, and must never be labeled a catalyst.
"""
import asyncio
import calendar
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import feedparser
import httpx

from macro import TR

log = logging.getLogger(__name__)

FEEDS = [
    ("https://www.coindesk.com/arc/outboundfeeds/rss/", "CoinDesk", "birinci sınıf"),
    ("https://www.theblock.co/rss.xml", "The Block", "birinci sınıf"),
    ("https://cointelegraph.com/rss", "Cointelegraph", "ikincil"),
    ("https://decrypt.co/feed", "Decrypt", "ikincil"),
    ("https://www.federalreserve.gov/feeds/press_all.xml", "Federal Reserve", "resmi"),
    ("https://www.sec.gov/news/pressreleases.rss", "SEC", "resmi"),
    ("https://www.cftc.gov/RSS/RSSGP/rssgp.xml", "CFTC", "resmi"),
    ("https://www.whitehouse.gov/news/feed/", "Beyaz Saray", "resmi"),
    ("https://home.treasury.gov/system/files/126/rss.xml", "ABD Hazine", "resmi"),
]
TIER_RANK = {"resmi": 3, "birinci sınıf": 2, "ikincil": 1}

# Only distinctive names: "near", "link", "sol", "uni", "arb", "hype" are ordinary words.
COIN_KEYWORDS = {
    "BTC": ["bitcoin", "btc"], "ETH": ["ethereum", "ether", "eth"], "SOL": ["solana"],
    "NEAR": ["near protocol"], "ONDO": ["ondo"], "HYPE": ["hyperliquid"], "AAVE": ["aave"],
    "UNI": ["uniswap"], "BCH": ["bitcoin cash"], "XRP": ["xrp", "ripple"], "LINK": ["chainlink"],
    "AVAX": ["avalanche", "avax"], "ARB": ["arbitrum"],
}
CRYPTO_WORDS = ["crypto", "stablecoin", "digital asset", "blockchain", "token", "defi", "tokeniz",
                "exchange-traded", "etf", "coinbase", "binance", "tether", "usdc", "web3", "mining", "miner",
                "exploit", "bridge", "nft", "wallet", "dao", "on-chain", "onchain", "dex", "layer 2", "layerzero",
                "polymarket", "prediction market", "altcoin", "memecoin", "airdrop", "validator", "zcash", "solana",
                "sats", "satoshi", "microstrategy", "strategy inc", "saylor", "kraken", "okx", "bybit", "bitget"]
MARKET_WORDS = ["fomc", "interest rate", "rate cut", "rate hike", "inflation", "cpi", "pce", "payroll",
                "unemployment", "gdp", "treasury yield", "yields", "balance sheet", "monetary policy",
                "tariff", "debt ceiling", "powell", "dollar"]
TYPE_RULES = [
    ("hack", ["hack", "exploit", "breach", "stolen", "drain"]),
    ("regülasyon", ["sec ", "cftc", "lawsuit", "regulat", "clarity act", "enforcement", "court", "settlement", "charges"]),
    ("etf", ["etf", "inflow", "outflow", "blackrock", "grayscale", "fidelity"]),
    ("makro", ["fed ", "fomc", "inflation", "cpi", "pce", "rate cut", "rate hike", "interest rate", "payroll",
               "unemployment", "gdp", "treasury", "yield", "powell"]),
    ("token unlock", ["unlock", "vesting", "token release"]),
    ("ağ/protokol", ["upgrade", "mainnet", "hard fork", "staking", "testnet"]),
    ("siyaset", ["trump", "white house", "senate", "congress", "executive order"]),
]
STOP = set("the a an and or of to in on for with is are be at from by as it its this that new will has have".split())
CACHE_SECONDS = 600
_cache = {"ts": 0.0, "items": []}


def _has(text: str, word: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(word.strip()) + r"(?![a-z0-9])", text) is not None


def _coins(text: str) -> list[str]:
    return [c for c, kws in COIN_KEYWORDS.items() if any(_has(text, k) for k in kws)]


def _type(text: str) -> str:
    padded = f" {text} "
    return next((label for label, kws in TYPE_RULES if any(k in padded for k in kws)), "genel")


def _relevance(text: str, coins: list[str]) -> str:
    """doğrudan = names a coin; piyasa = crypto or macro-market topic; düşük = neither."""
    if coins:
        return "doğrudan"
    if any(w in text for w in CRYPTO_WORDS) or any(w in text for w in MARKET_WORDS):
        return "piyasa"
    return "düşük"


def _tokens(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in STOP and len(w) > 2}


async def _fetch(client: httpx.AsyncClient, url: str, source: str, tier: str) -> list[dict]:
    for attempt in range(2):  # official feeds (Fed) sometimes answer 404 for a moment
        try:
            r = await client.get(url, timeout=12, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (Kapanis crypto news reader)"})
            r.raise_for_status()
            break
        except Exception as e:
            if attempt == 0:
                await asyncio.sleep(3)
                continue
            log.warning("News feed %s failed: %s", source, e)
            return []
    parsed = feedparser.parse(r.content)
    out = []
    for e in parsed.entries[:25]:
        title = (e.get("title") or "").strip()
        if not title:
            continue
        stamp = e.get("published_parsed") or e.get("updated_parsed")
        dt = datetime.fromtimestamp(calendar.timegm(stamp), tz=timezone.utc) if stamp else datetime.now(timezone.utc)
        summary = re.sub(r"<[^>]+>", "", e.get("summary", "")).strip()[:280]
        text = f"{title} {summary}".lower()
        link = e.get("link", "")
        out.append({"baslik": title, "ozet": summary, "link": link if link.startswith("http") else "",
                    "kaynak": source, "kaynak_turu": tier, "ts": dt.timestamp(),
                    "tur": _type(text), "coinler": _coins(text), "_text": text, "_tokens": _tokens(title)})
    return out


def _merge(items: list[dict]) -> list[dict]:
    """Group the same story reported by different outlets within 24 hours."""
    items.sort(key=lambda x: x["ts"], reverse=True)
    groups = []
    for it in items:
        for g in groups:
            union = len(g["_tokens"] | it["_tokens"]) or 1
            same = (len(g["_tokens"] & it["_tokens"]) / union >= 0.5
                    or SequenceMatcher(None, g["baslik"].lower(), it["baslik"].lower()).ratio() >= 0.54)
            if same and abs(g["ts"] - it["ts"]) < 86400:
                if it["kaynak"] not in g["kaynaklar"]:
                    g["kaynaklar"].append(it["kaynak"])
                    g["_tiers"].append(it["kaynak_turu"])
                g["coinler"] = sorted(set(g["coinler"]) | set(it["coinler"]))
                g["_text"] += " " + it["_text"]
                break
        else:
            groups.append({**it, "kaynaklar": [it["kaynak"]], "_tiers": [it["kaynak_turu"]]})

    out = []
    for g in groups:
        best_tier = max(g["_tiers"], key=TIER_RANK.get)
        relevance = _relevance(g["_text"], g["coinler"])
        n = len(g["kaynaklar"])
        out.append({
            "zaman_tr": datetime.fromtimestamp(g["ts"], tz=TR).strftime("%d.%m %H:%M"),
            "ts": g["ts"], "baslik": g["baslik"], "ozet": g["ozet"], "link": g["link"],
            "tur": g["tur"], "coinler": g["coinler"], "kaynaklar": g["kaynaklar"], "kaynak_sayisi": n,
            # How official/established the best outlet is. Says nothing about market impact.
            "kaynak_guvenilirligi": best_tier,
            # Whether the story touches crypto or markets at all.
            "kripto_ilgisi": relevance,
            "dogrulama": "çok kaynaklı" if n >= 2 else "tek kaynak, doğrulanmadı",
            "katalizor_adayi": relevance != "düşük" and (g["tur"] in ("regülasyon", "makro", "etf", "hack") or n >= 2),
        })
    return out


async def get_news(force: bool = False) -> list[dict]:
    if not force and time.time() - _cache["ts"] < CACHE_SECONDS and _cache["items"]:
        return _cache["items"]
    async with httpx.AsyncClient() as client:
        batches = await asyncio.gather(*(_fetch(client, u, s, t) for u, s, t in FEEDS))
    items = _merge([it for b in batches for it in b])[:80]
    _cache.update(ts=time.time(), items=items)
    return items


def for_model(items: list[dict], coins: list[str], hours: int = 48, limit: int = 12) -> list[dict]:
    """Relevant headlines for an analysis: coin-specific first, then market-wide catalysts."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
    recent = [n for n in items if n["ts"] >= cutoff and n["kripto_ilgisi"] != "düşük"]
    direct = [n for n in recent if set(n["coinler"]) & set(coins)]
    market = [n for n in recent if n not in direct and n["katalizor_adayi"]]
    picked = (direct[:6] + market)[:limit]
    return [{k: n[k] for k in ("zaman_tr", "baslik", "tur", "coinler", "kaynaklar", "kaynak_guvenilirligi",
                               "kripto_ilgisi", "dogrulama")} for n in picked]


# --- Borsa İstanbul news (Google News RSS, Turkish) -------------------------------------------
# There is no free KAP API; Google News aggregates Turkish outlets (AA, Bloomberg HT, Dünya, ...),
# including their KAP-based stories. Same rules: source reliability != market impact, single
# source = not verified, and auto-generated "daily technical analysis" pages are not news.
GNEWS = "https://news.google.com/rss/search"
BIST_TIER1 = ("Anadolu Ajansı", "Bloomberght", "Bloomberg HT", "Dünya", "Ekonomim", "Reuters", "KAP",
              "Borsa İstanbul", "Habertürk", "NTV", "Para Analiz", "Foreks")
BIST_NOISE = ("teknik analiz", "hisse yorum", "hedef fiyat listesi", "canlı borsa", "günün en çok")
BIST_TYPES = [
    ("KAP/şirket", ["kap", "bildirim", "bilanço", "finansal sonuç", "net kâr", "net kar", "temettü", "bedelsiz",
                    "sermaye artırımı", "geri alım", "pay alım", "ihale", "sözleşme", "sipariş", "yatırım kararı"]),
    ("regülasyon", ["spk", "ceza", "soruşturma", "tedbir", "brüt takas", "kredili işlem yasağı", "temerrüt"]),
    ("makro", ["tcmb", "merkez bankası", "faiz", "enflasyon", "tüfe", "cari açık", "kredi notu", "cds", "dolar/tl"]),
]
_bist_cache: dict[str, tuple[float, list[dict]]] = {}


def _bist_type(text: str) -> str:
    # Whole-word match: "kap" must not hit "kapattı", "faiz" must not hit "faizsiz" etc.
    return next((label for label, kws in BIST_TYPES if any(_has(text, k) for k in kws)), "genel")


async def bist_news(ticker: str | None = None, force: bool = False) -> list[dict]:
    query = f"{ticker} hisse" if ticker else "Borsa İstanbul BIST 100"
    hit = _bist_cache.get(query)
    if hit and not force and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    async with httpx.AsyncClient() as client:
        r = await client.get(GNEWS, params={"q": query, "hl": "tr", "gl": "TR", "ceid": "TR:tr"}, timeout=15,
                             follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Kapanis news reader)"})
        r.raise_for_status()
    raw = []
    for e in feedparser.parse(r.content).entries[:60]:
        title = (e.get("title") or "").strip()
        source = (e.get("source") or {}).get("title") or title.rsplit(" - ", 1)[-1]
        title = title.rsplit(" - ", 1)[0] if " - " in title else title
        text = title.lower()
        if not title or any(n in text for n in BIST_NOISE):
            continue
        stamp = e.get("published_parsed")
        dt = datetime.fromtimestamp(calendar.timegm(stamp), tz=timezone.utc) if stamp else datetime.now(timezone.utc)
        tier = "birinci sınıf" if any(t.lower() in source.lower() for t in BIST_TIER1) else "ikincil"
        raw.append({"baslik": title, "ozet": "", "link": e.get("link", ""), "kaynak": source, "kaynak_turu": tier,
                    "ts": dt.timestamp(), "tur": _bist_type(text), "coinler": [ticker] if ticker and ticker.lower() in text else [],
                    "_text": text + (" borsa hisse" if ticker else " borsa"), "_tokens": _tokens(title)})
    items = _merge(raw)[:40]
    for n in items:  # every item here is market news by construction
        n["kripto_ilgisi"] = "doğrudan" if n["coinler"] else "piyasa"
        n["katalizor_adayi"] = n["tur"] in ("KAP/şirket", "regülasyon", "makro") or n["kaynak_sayisi"] >= 2
    _bist_cache[query] = (time.time(), items)
    return items


async def bist_for_model(ticker: str | None, hours: int = 72, limit: int = 10) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
    items = [n for n in (await bist_news(ticker) if ticker else []) if n["ts"] >= cutoff]
    items += [n for n in await bist_news(None) if n["ts"] >= cutoff and n["katalizor_adayi"]]
    return [{k: n[k] for k in ("zaman_tr", "baslik", "tur", "kaynaklar", "kaynak_guvenilirligi", "dogrulama")}
            for n in items[:limit]]

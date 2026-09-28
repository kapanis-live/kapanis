"""Risky headlines about what the user holds or watches, pushed immediately.

Sources: Binance announcements (delisting catalog 161 + news catalog 49 for monitoring/seed tags),
the crypto RSS feeds (news.get_news) and Google News for each held/listed BIST stock (news.bist_news).
A headline is a CANDIDATE when it names a watched asset AND contains a risk keyword. Keyword matches alone were
wrong too often ("Months after the Kelp hack, Chainlink adds bridge checks" is not a Chainlink hack), so each
candidate's article is read and a model answers: does it report a NEW NEGATIVE event hitting THIS asset itself?
Only then it is sent. Binance's own delisting/monitoring announcements are official and skip the check.
If no model answers, the headline is sent marked "doğrulanamadı". Seen headlines are remembered
(settings "risk_haber_gorulen") so each one is handled once.
"""
import hashlib
import logging
import re
import time

import httpx

import alerts_store
import bist
import config
import conversation_store as store
import news
import positions

log = logging.getLogger(__name__)

BINANCE_CMS = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
BINANCE_CATALOGS = (161, 49)
CRYPTO_WORDS = ["delist", "monitoring tag", "seed tag", "hack", "exploit", "drained", "stolen", "vulnerability",
                "sec sues", "lawsuit", "charged", "halt", "suspend", "rug", "insolv", "bankrupt", "depeg",
                "outage", "unlock", "investigation"]
BIST_WORDS = ["iflas", "konkordato", "spk", "soruşturma", "tedbir", "işlem yasağı", "kottan çık", "borsa kotundan",
              "bedelli", "sermaye artırımı", "zarar açıkladı", "net zarar", "ceza", "haciz", "vbts", "brüt takas",
              "açığa satış yasağı", "pay satışı", "ortak satış", "gözaltı", "operasyon", "temerrüt", "dava"]
MAX_SEEN = 400
MAX_AGE_HOURS = 24


def watched() -> tuple[set[str], set[str]]:
    """(crypto tickers, BIST tickers) the user holds, plans, lists or has live alarms on."""
    crypto, stocks = set(), set()
    keys = [p["symbol"] for p in positions.open_positions() if p.get("piyasa") in (None, "KRIPTO", "BIST")]
    keys += alerts_store.load_settings().get("plan_listesi") or []
    keys += list(store.load_state()["planlar"])
    for pair, items in alerts_store.load_alerts().items():
        if any(a["durum"] in alerts_store.ACTIVE_STATES for a in items):
            keys.append(pair)
    for k in keys:
        k = k.upper()
        if k.endswith(".US"):
            continue  # US headlines come with /abd analyses
        if k.endswith(".IS"):
            stocks.add(bist.ticker(k))
        else:
            coin = k.replace("/", "").removesuffix(config.QUOTE)
            if coin:
                crypto.add(coin)
    return crypto, stocks


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(word.lower())}(?![a-z0-9])", text) is not None


COIN_NAMES = {"SOL": ["solana"], "XRP": ["ripple"], "LINK": ["chainlink"], "AVAX": ["avalanche"],
              "ARB": ["arbitrum"], "AAVE": ["aave"], "UNI": ["uniswap"], "HYPE": ["hyperliquid"], "ONDO": ["ondo"],
              "NEAR": ["near protocol"], "BCH": ["bitcoin cash"]}
# BTC and ETH appear in almost every crypto headline (market-wide hacks, lawsuits): alerting on them is noise.
SKIP_COINS = {"BTC", "ETH"}


def match(title: str, crypto: set[str], stocks: set[str]) -> tuple[str, str] | None:
    """(asset, keyword) if the headline names a watched asset and a risk word. Pure.
    Coins match by their UPPERCASE ticker (so the word "near" is not NEAR) or their project name."""
    low = title.lower()
    for coin in sorted(crypto - SKIP_COINS):
        named = (re.search(rf"(?<![A-Za-z0-9]){re.escape(coin)}(?![A-Za-z0-9])", title)
                 or any(_has_word(low, n) for n in COIN_NAMES.get(coin, [])))
        if named:
            kw = _keyword(low, CRYPTO_WORDS)
            if kw:
                return coin, kw
    for t in sorted(stocks):
        if _has_word(low, t.lower()):
            kw = _keyword(low, BIST_WORDS)
            if kw:
                return t, kw
    return None


def _keyword(low: str, words: list[str]) -> str | None:
    """First risk word that starts a word in the headline ("delist" matches "delisting", "rug" not "drug")."""
    return next((w for w in words if re.search(rf"(?<![a-zçğıöşü0-9]){re.escape(w)}", low)), None)


async def article_text(url: str) -> str:
    """Readable text of a news page (tags stripped), or "" if it cannot be fetched."""
    if not url:
        return ""
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Kapanis)"}) as c:
            r = await c.get(url)
        html = r.text if r.status_code < 400 else ""
    except Exception:
        return ""
    html = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()[:8000]


async def verify(asset: str, keyword: str, item: dict) -> dict | None:
    """Model check of one candidate: {"gonder", "ozet"}, or None when no model answered (then it is sent, marked)."""
    import llm
    text = await article_text(item.get("link", "")) or item["baslik"]
    res = await llm.classify_risk_news(asset, keyword, item["baslik"], text)
    if not res:
        return None
    return {"gonder": res["dogrudan"] and res["yeni"] and res["yon"] == "olumsuz", "ozet": res["ozet"] or res["tur"]}


def _key(title: str) -> str:
    return hashlib.sha1(title.strip().lower().encode()).hexdigest()[:16]


async def _binance(client: httpx.AsyncClient) -> list[dict]:
    out = []
    for cat in BINANCE_CATALOGS:
        try:
            r = await client.get(BINANCE_CMS, params={"type": 1, "catalogId": cat, "pageNo": 1, "pageSize": 15},
                                 timeout=15, headers={"User-Agent": "Mozilla/5.0 (Kapanis)"})
            for c in r.json()["data"]["catalogs"]:
                for a in c.get("articles", []):
                    out.append({"baslik": a["title"], "ts": a["releaseDate"] / 1000, "kaynak": "Binance duyuru",
                                "link": f"https://www.binance.com/en/support/announcement/{a['code']}"})
        except Exception as e:
            log.warning("Binance announcements %s failed: %s", cat, e)
    return out


async def check() -> list[str]:
    crypto, stocks = watched()
    if not crypto and not stocks:
        return []
    items = []
    async with httpx.AsyncClient() as client:
        if crypto:
            items += await _binance(client)
    if crypto:
        try:
            items += [{"baslik": n["baslik"], "ts": n["ts"], "kaynak": ", ".join(n["kaynaklar"]), "link": n.get("link", "")}
                      for n in await news.get_news()]
        except Exception as e:
            log.warning("Crypto news for risk check failed: %s", e)
    for t in sorted(stocks)[:12]:
        try:
            items += [{"baslik": n["baslik"], "ts": n["ts"], "kaynak": ", ".join(n["kaynaklar"]), "link": n.get("link", "")}
                      for n in await news.bist_news(t)]
        except Exception as e:
            log.warning("BIST news for %s failed: %s", t, e)
    s = alerts_store.load_settings()
    seen = s.get("risk_haber_gorulen", [])
    cutoff = time.time() - MAX_AGE_HOURS * 3600
    held = {bist.ticker(p["symbol"]) if p.get("piyasa") == "BIST" else p["pair"].split("/")[0]
            for p in positions.open_positions()}
    msgs = []
    for n in sorted(items, key=lambda x: x["ts"]):
        if n["ts"] < cutoff or _key(n["baslik"]) in seen:
            continue
        m = match(n["baslik"], crypto, stocks)
        if not m:
            continue
        seen.append(_key(n["baslik"]))
        asset, kw = m
        official = n["kaynak"] == "Binance duyuru"
        verdict = None if official else await verify(asset, kw, n)
        if verdict and not verdict["gonder"]:
            log.info("Risk headline dropped after reading (%s): %s — %s", asset, n["baslik"], verdict["ozet"])
            continue
        note = ("" if official else f"\nMakale okundu: {verdict['ozet']}" if verdict
                else "\n(doğrulanamadı: yalnız başlıkta kelime eşleşti)")
        msgs.append(f"🚨 RİSK HABERİ — {asset} ({kw})\n{n['baslik']}{note}\nKaynak: {n['kaynak']}"
                    + (f" · {n['link']}" if n.get("link") else "")
                    + ("\nPozisyonun var: stopunu kontrol et. Haber tek başına SAT sebebi değil; kapanışı bekle."
                       if asset in held else "\nListende/planında var: yeni giriş öncesi aslını kontrol et."))
    s["risk_haber_gorulen"] = seen[-MAX_SEEN:]
    alerts_store.save_settings(s)
    return msgs[:8]

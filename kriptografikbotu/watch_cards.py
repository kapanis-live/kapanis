"""Three facts added to every watch-list row, and the risk label of the earnings calendar.

  güç      the asset's 6-month return minus its benchmark's (BIST 100, S&P 500, BTC), in points (watchlist.rows)
  bilanço  days to the next earnings report, from the company calendar the bot already keeps (features.py)
  puan     the fundamental score the bot already computes (fundamentals.py for BIST, us_fund.py for the US),
           refreshed once a day for the watch list and the holdings

Descriptions, not suggestions: nothing here says AL or SAT. The thresholds are the ones the US card uses.
"""
import asyncio
import logging
from datetime import date

import alerts_store
import config

log = logging.getLogger(__name__)

SCORES = config.DATA_DIR / "takip_puan.json"
STRONG_PP = 10          # 6-month return this many points over / under the benchmark = GÜÇLÜ / ZAYIF
EARNINGS_SOON = 14      # days: ORTA inside this, YÜKSEK inside config.US_EARNINGS_BLOCK_DAYS
SIX_MONTHS = 126        # trading days (crypto: calendar days; close enough for a label)
PARALLEL = 2


def strength(pp) -> str | None:
    return None if pp is None else "GÜÇLÜ" if pp >= STRONG_PP else "ZAYIF" if pp <= -STRONG_PP else "NÖTR"


def six_month_return(closes) -> float | None:
    """% change over the last SIX_MONTHS closed bars; None with a shorter history."""
    if closes is None or len(closes) <= SIX_MONTHS:
        return None
    then, now = float(closes.iloc[-SIX_MONTHS - 1]), float(closes.iloc[-1])
    return (now / then - 1) * 100 if then > 0 else None


def earnings_risk(days) -> str | None:
    if days is None or days < 0:
        return None
    return "YÜKSEK" if days <= config.US_EARNINGS_BLOCK_DAYS else "ORTA" if days <= EARNINGS_SOON else "DÜŞÜK"


def calendar_item(item: dict, today: date) -> dict:
    """A company-calendar item with the days left, and for an earnings report its gap-risk label."""
    days = (date.fromisoformat(item["tarih"]) - today).days
    return {**item, "gun": days, "risk": earnings_risk(days) if item.get("tur") == "bilanco" else None}


def load_scores() -> dict:
    return alerts_store._load(SCORES, {"tarih": None, "puanlar": {}})


async def refresh_scores(codes: list[tuple[str, str]], today: str) -> dict:
    """Once a day: the fundamental score of each (market, code). A stock whose report fails keeps yesterday's."""
    doc = load_scores()
    if doc.get("tarih") == today:
        return doc
    import fundamentals
    import us_fund
    slots = asyncio.Semaphore(PARALLEL)
    scores = dict(doc.get("puanlar") or {})

    async def one(mkt, code):
        async with slots:
            try:
                if mkt == "BIST":
                    p = (await fundamentals.report(code))["puan"]
                    scores[f"{mkt}:{code}"] = {"skor": p["skor"], "etiket": p.get("etiket"), "tarih": today}
                elif mkt == "ABD":
                    p = (await us_fund.report(code))["puan"]
                    scores[f"{mkt}:{code}"] = {"skor": p["skor"], "etiket": p.get("durum"), "tarih": today}
            except Exception as e:
                log.info("Watch score %s %s failed: %s", mkt, code, str(e)[:100])
    await asyncio.gather(*[one(m, c) for m, c in codes])
    wanted = {f"{m}:{c}" for m, c in codes}
    doc = {"tarih": today, "puanlar": {k: v for k, v in scores.items() if k in wanted}}
    alerts_store._save(SCORES, doc)
    return doc


def enrich(markets: dict, calendar: list[dict], scores: dict, today: date) -> dict:
    """Add bilanço and puan to the rows of watchlist.panel_rows() (in place; rows with an error are left alone)."""
    earn = {}
    for i in calendar:
        if i.get("tur") == "bilanco":
            earn.setdefault((i["piyasa"], i["kod"]), i["tarih"])        # the calendar is sorted: the first is the next
    for mkt, rows in markets.items():
        for r in rows:
            if "hata" in r:
                continue
            day = earn.get((mkt, r["kod"]))
            days = (date.fromisoformat(day) - today).days if day else None
            s = scores.get(f"{mkt}:{r['kod']}") or {}
            r.update(bilanco_tarih=day, bilanco_gun=days, bilanco_risk=earnings_risk(days),
                     puan=s.get("skor"), puan_etiket=s.get("etiket"))
    return markets

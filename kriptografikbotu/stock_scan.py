"""The stock table: every stock of a universe (S&P 100, the BIST list) on one screen, with the same columns as a card.

Per stock: price, day change, trend, strength against the index, RSI, days to earnings and its gap risk, the
fundamental score and the coarse valuation label. Built once a day after the close (slow: one fundamentals report
per stock) and on request; the result is kept in data/tarama_<market>.json and sent to the panel.

A table to look things up and sort, not a list of suggestions: no timing rule passed the history tests on stocks
(research/README.md), so nothing here is ranked as "buy". Every label is a description with fixed thresholds.
"""
import asyncio
import logging
import time
from datetime import date

import httpx

import alerts_store
import bist
import bist_card
import config
import fundamentals
import universe
import us
import us_card
import us_fund
import watch_cards
import watchlist

log = logging.getLogger(__name__)

PARALLEL = 2
MARKETS = {"ABD": "🇺🇸 ABD (S&P 100)", "BIST": "🇹🇷 BIST"}
_running: set[str] = set()


def path(mkt: str):
    return config.DATA_DIR / f"tarama_{mkt.lower()}.json"


def codes(mkt: str) -> list[str]:
    return list(us.SP100) if mkt == "ABD" else list(universe.bist_names())


def load(mkt: str) -> dict | None:
    return alerts_store._load(path(mkt), None)


def fresh(mkt: str) -> dict | None:
    """Today's table, if it was already built."""
    doc = load(mkt)
    return doc if doc and doc.get("gun") == alerts_store.now_tr().date().isoformat() else None


def running(mkt: str) -> bool:
    return mkt in _running


async def _facts(client, mkt: str, code: str, today: date) -> dict:
    """Score, valuation label, sector and days to earnings of one stock."""
    if mkt == "ABD":
        f = await us_fund.report(code)
        y = f.get("analist") or {}
        return {"puan": f["puan"]["skor"], "puan_etiket": f["puan"].get("durum"), "degerleme": us_card.valuation(f)["etiket"],
                "sektor": y.get("sektor"), "bilanco_tarih": y.get("sonraki_bilanco"), "revizyon": us_card.revisions(y)["etiket"]}
    f = await fundamentals.report(code)
    try:
        import features
        day = (await features._yahoo_calendar(client, bist.yahoo_symbol(code))).get("bilanco")
    except Exception:
        day = None
    return {"puan": f["puan"]["skor"], "puan_etiket": f["puan"].get("etiket"), "degerleme": bist_card.valuation(f)["etiket"],
            "sektor": f.get("grup"), "bilanco_tarih": day, "revizyon": None}


async def run(mkt: str, only: list[str] | None = None) -> dict:
    """Build the table of one market (only: a few codes, for tests and partial runs)."""
    if mkt in _running:
        raise RuntimeError("tarama zaten çalışıyor")
    _running.add(mkt)
    t0 = time.time()
    try:
        names = only or codes(mkt)
        today = alerts_store.now_tr().date()
        rows = {r["kod"]: r for r in await watchlist.rows(mkt, names)}
        slots = asyncio.Semaphore(PARALLEL)
        facts: dict[str, dict] = {}
        async with httpx.AsyncClient() as client:
            async def one(code):
                async with slots:
                    try:
                        facts[code] = await _facts(client, mkt, code, today)
                    except Exception as e:
                        log.info("Scan %s %s: %s", mkt, code, str(e)[:100])
            await asyncio.gather(*[one(c) for c in names])
        out = []
        for code in names:
            r, f = rows.get(code) or {}, facts.get(code) or {}
            if "hata" in r or not r:
                continue
            day = f.get("bilanco_tarih")
            days = (date.fromisoformat(day) - today).days if day else None
            out.append({"kod": code, "fiyat": r["fiyat"], "gun_yuzde": r["gun_yuzde"], "hafta_yuzde": r["hafta_yuzde"], "trend": r["trend"],
                        "guc": r.get("guc"), "guc_6a": r.get("guc_6a"), "rsi": r["rsi"], "puan": f.get("puan"),
                        "puan_etiket": f.get("puan_etiket"), "degerleme": f.get("degerleme"), "sektor": f.get("sektor"),
                        "revizyon": f.get("revizyon"), "bilanco_tarih": day, "bilanco_gun": days if days is None or days >= 0 else None,
                        "bilanco_risk": watch_cards.earnings_risk(days)})
        doc = {"id": f"tarama_{mkt.lower()}", "tur": "tarama", "piyasa": mkt, "gun": today.isoformat(),
               "zaman": alerts_store.now_tr().isoformat(timespec="seconds"), "sure_sn": round(time.time() - t0),
               "istenen": len(names), "satirlar": out, "temeli_eksik": sum(r["puan"] is None for r in out),
               "kaynaklar": (["fiyat ve göreli güç: Yahoo Finance", "temel puan ve değerleme: SEC EDGAR + Yahoo analist verisi",
                              "bilanço takvimi: Yahoo Finance"] if mkt == "ABD" else
                             ["fiyat ve göreli güç: Yahoo Finance (~15 dk gecikmeli)", "temel puan ve değerleme: İş Yatırım mali tabloları",
                              "bilanço takvimi: Yahoo Finance (kesin tarih için KAP)"])}
        if not only:
            alerts_store._save(path(mkt), doc)
        return doc
    finally:
        _running.discard(mkt)


def text(doc: dict, top: int = 12) -> str:
    rows = doc["satirlar"]
    scored = sorted((r for r in rows if r["puan"] is not None), key=lambda r: -r["puan"])
    unit = "$" if doc["piyasa"] == "ABD" else "₺"

    def line(r):
        return (f"{r['kod']} {watchlist._p(r['fiyat'])}{unit} · puan {r['puan']} · {r['trend']}"
                + (f" · güç {r['guc']}" if r.get("guc") else "") + (f" · {r['degerleme']}" if r.get("degerleme") else "")
                + (f" · bilanço {r['bilanco_gun']}g" + (" ⚠️" if r["bilanco_risk"] == "YÜKSEK" else "") if r.get("bilanco_gun") is not None and r["bilanco_gun"] <= 14 else ""))
    soon = sorted((r for r in rows if r.get("bilanco_risk") == "YÜKSEK"), key=lambda r: r["bilanco_gun"])
    strong = sum(r.get("guc") == "GÜÇLÜ" for r in rows)
    up = sum(str(r["trend"]).startswith("↗") for r in rows)
    lines = [f"{MARKETS[doc['piyasa']]} — HİSSE TABLOSU · {len(rows)} hisse · {doc['zaman'][:16].replace('T', ' ')}",
             f"Trend yukarı: {up} · endeksten güçlü: {strong} · bilançosu 5 gün içinde: {len(soon)}", "",
             f"Temel puanı en yüksek {min(top, len(scored))} (sıralama, öneri değil):", *[line(r) for r in scored[:top]]]
    if soon:
        lines += ["", "Bilançosu 5 gün içinde (boşluk riski): " + ", ".join(f"{r['kod']} ({r['bilanco_gun']}g)" for r in soon[:15])]
    if doc.get("temeli_eksik"):
        lines.append(f"({doc['temeli_eksik']} hissenin temel verisi alınamadı)")
    lines += ["", f"Tamamı ve sıralama: {config.PUBLIC_URL}/app/tarama",
              "Tablo bakmak ve sıralamak içindir. Hisselerde test edilen zamanlama kurallarının hiçbiri al-tut'u geçemedi; puan getiri tahmini değildir."]
    return "\n".join(lines)

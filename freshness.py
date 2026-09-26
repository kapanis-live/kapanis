"""How current every data source is. Used by /durum, the web panel and the decision slip.

Each source gets: last update time, age, and a status — güncel / eski / bayat / yok.
Thresholds follow each source's natural rhythm (15m candles vs. monthly CPI).
"""
import json
import time
from datetime import date, datetime, timedelta, timezone

import httpx

import config
import bist
import costs
import macro
import market
import news

STATUS_ICON = {"güncel": "🟢", "eski": "🟡", "bayat": "🔴", "yok": "⚪"}
# Sources the decision gate actually depends on; the rest are informational.
GATE_SOURCES = {"Binance 15m mum", "FRED (faiz/dolar/VIX)", "Veri takvimi"}
_last_push = {"ts": None}


def mark_push():
    _last_push["ts"] = time.time()


def _status(age_s: float | None, warn_s: float, stale_s: float) -> str:
    if age_s is None:
        return "yok"
    return "güncel" if age_s <= warn_s else "eski" if age_s <= stale_s else "bayat"


def _age_text(age_s: float | None) -> str:
    if age_s is None:
        return "—"
    if age_s < 3600:
        return f"{age_s / 60:.0f} dk"
    if age_s < 172800:
        return f"{age_s / 3600:.1f} sa"
    return f"{age_s / 86400:.0f} gün"


def _row(name: str, when: datetime | None, age_s: float | None, warn_s: float, stale_s: float,
         note: str = "", failed: bool = False) -> dict:
    st = "bayat" if failed else _status(age_s, warn_s, stale_s)
    return {"kaynak": name, "durum": st, "zaman": when.isoformat() if when else None,
            "yas": _age_text(age_s), "not": ("yenilenemedi; " if failed else "") + note,
            "kapiyi_etkiler": name in GATE_SOURCES}


async def collect() -> list[dict]:
    now = datetime.now(timezone.utc)
    rows = []

    # Binance: the last closed 15m BTC candle should be at most one candle old.
    try:
        async with httpx.AsyncClient() as client:
            df = await market.fetch_klines(client, "BTC" + config.QUOTE, "15m", limit=3)
        closed = datetime.fromtimestamp((int(df.open_time.iloc[-1]) + 900_000) / 1000, tz=timezone.utc)
        rows.append(_row("Binance 15m mum", closed, (now - closed).total_seconds(), 16 * 60, 45 * 60, "BTC/USDT"))
    except Exception as e:
        rows.append(_row("Binance 15m mum", None, None, 0, 0, str(e)[:60], failed=True))

    m = await macro.summary()
    stale = set(m.get("guncel_degil", []))
    fred = m.get("fred", {})
    if "hata" in fred:
        rows.append(_row("FRED", None, None, 0, 0, fred["hata"][:60], failed=True))
    else:
        d = fred.get("DGS10", {}).get("tarih")
        when = datetime.fromisoformat(d).replace(tzinfo=timezone.utc) if d else None
        # Daily series publish with a 1-2 business day lag; a weekend adds two more days.
        rows.append(_row("FRED (faiz/dolar/VIX)", when, (now - when).total_seconds() if when else None,
                         4 * 86400, 7 * 86400, f"son gözlem {d}", failed="fred" in stale))
    bls = m.get("bls", {})
    per = bls.get("enflasyon", {}).get("donem")
    if per:
        y, mo = map(int, per.split("-"))
        # Month M is released mid month M+1; a period older than ~2 months means a missed release.
        release = datetime(y + (mo // 12), mo % 12 + 1, 15, tzinfo=timezone.utc)
        rows.append(_row("BLS (CPI/NFP)", release, (now - release).total_seconds(), 35 * 86400, 50 * 86400,
                         f"son dönem {per}", failed="bls" in stale))
    else:
        rows.append(_row("BLS (CPI/NFP)", None, None, 0, 0, bls.get("hata", "")[:60], failed=True))
    cot = (m.get("cftc_cme") or {}).get("BTC")
    if isinstance(cot, dict) and "rapor_tarihi" in cot:
        when = datetime.fromisoformat(cot["rapor_tarihi"]).replace(tzinfo=timezone.utc)
        # Tuesday data, Friday release: 3-10 days old is normal.
        rows.append(_row("CFTC COT", when, (now - when).total_seconds(), 11 * 86400, 18 * 86400,
                         f"rapor {cot['rapor_tarihi']}", failed="cftc" in stale))
    else:
        rows.append(_row("CFTC COT", None, None, 0, 0, "", failed=True))
    try:
        cache = json.loads(config.MACRO_CACHE_FILE.read_text(encoding="utf-8")).get("takvim", {})
        when = datetime.fromtimestamp(cache["ts"], tz=timezone.utc) if cache.get("ts") else None
    except Exception:
        when = None
    rows.append(_row("Veri takvimi", when, (now - when).total_seconds() if when else None, 13 * 3600, 36 * 3600,
                     failed="takvim" in stale))

    try:
        items = await news.get_news()
        newest = max((i["ts"] for i in items), default=None)
        when = datetime.fromtimestamp(newest, tz=timezone.utc) if newest else None
        rows.append(_row("Haberler (RSS)", when, (now - when).total_seconds() if when else None, 6 * 3600, 24 * 3600,
                         f"{len(items)} başlık"))
    except Exception as e:
        rows.append(_row("Haberler (RSS)", None, None, 0, 0, str(e)[:60], failed=True))

    # BIST (Yahoo, ~15 min delayed): last closed 1h bar; outside the session the age is expected.
    try:
        async with httpx.AsyncClient() as client:
            h = await bist.fetch(client, "THYAO", "1h")
        closed = datetime.fromtimestamp(int(h.close_time.iloc[-1]) / 1000, tz=timezone.utc)
        age = (now - closed).total_seconds()
        if bist.session_open():
            rows.append(_row("BIST 1s mum (Yahoo)", closed, age, 95 * 60, 150 * 60, "~15 dk gecikmeli"))
        else:
            rows.append({**_row("BIST 1s mum (Yahoo)", closed, age, 10**9, 10**9, "seans kapalı"), "kapiyi_etkiler": False})
    except Exception as e:
        rows.append(_row("BIST 1s mum (Yahoo)", None, None, 0, 0, str(e)[:60], failed=True))

    used = costs._rows()
    when = datetime.fromisoformat(used[-1]["utc"]) if used else None
    rows.append({"kaynak": "DeepSeek son çağrı", "durum": "güncel" if when else "yok",
                 "zaman": when.isoformat() if when else None,
                 "yas": _age_text((now - when).total_seconds()) if when else "—", "not": "bilgi amaçlı",
                 "kapiyi_etkiler": False})

    if config.WEB_URL:
        ts = _last_push["ts"]
        when = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
        rows.append(_row("Panele son gönderim", when, time.time() - ts if ts else None,
                         3 * config.WEB_SYNC_INTERVAL, 10 * config.WEB_SYNC_INTERVAL))
    return rows


def text(rows: list[dict]) -> str:
    lines = ["🩺 VERİ GÜNCELLİĞİ"]
    for r in rows:
        lines.append(f"{STATUS_ICON[r['durum']]} {r['kaynak']}: {r['yas']}" + (f" — {r['not']}" if r["not"] else ""))
    blocking = [r["kaynak"] for r in rows if r["kapiyi_etkiler"] and r["durum"] in ("bayat", "yok")]
    other = [r["kaynak"] for r in rows if not r["kapiyi_etkiler"] and r["durum"] in ("bayat", "yok")
             and r["kaynak"] != "DeepSeek son çağrı"]
    if blocking:
        lines.append("\n❌ Karar kapısı AL vermez, bayat/eksik: " + ", ".join(blocking))
    else:
        lines.append("\n✅ Karar kapısının kullandığı veriler (Binance, FRED, takvim) güncel.")
    if other:
        lines.append("ℹ️ Bilgi amaçlı kaynaklarda sorun: " + ", ".join(other))
    return "\n".join(lines)


def snapshot(rows: list[dict]) -> dict:
    """Compact per-source times for the decision slip."""
    return {r["kaynak"]: {"durum": r["durum"], "zaman": r["zaman"]} for r in rows}

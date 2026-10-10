"""Did the portfolio beat the simple alternatives? And what happened after each sell?

Benchmarks (all in TL, over the same holding periods as the open positions, weighted by TL cost):
BIST 100 (XU100), BTC (converted with USD/TRY), gram altın, USD and a TL deposit at the user's rate
(/kiyas faiz 45, yearly %, compounded daily, gross). Without a rate the deposit row is left empty.

After-sale check: 5 and 20 days after a sell, the price is compared with the sell price. Up more than
AFTER_SALE_PCT = sold early, down more than that = good exit, otherwise neutral. Stored on the sold
records (pos["satis_sonrasi"]) and summarized in the journal.
"""
import logging
from datetime import datetime, timedelta

import httpx
import pandas as pd

import alerts_store
import assets
import bist
import market
import notify_prefs
import positions
from macro import TR

log = logging.getLogger(__name__)

AFTER_SALE_PCT = 3.0
CHECK_DAYS = (5, 20)
BENCHMARKS = [("XU100", "BIST 100"), ("BTC", "BTC"), ("GRAM_ALTIN", "Gram altın"), ("USD", "Dolar")]


def deposit_rate() -> float | None:
    v = alerts_store.load_settings().get("mevduat_faiz")
    return float(v) if v else None


def set_deposit_rate(pct: float):
    s = alerts_store.load_settings()
    s["mevduat_faiz"] = pct
    alerts_store.save_settings(s)


def _series(df: pd.DataFrame) -> pd.Series:
    days = [datetime.fromtimestamp(int(t) / 1000, TR).date().isoformat() for t in df.open_time]
    return pd.Series(df.close.astype(float).values, index=days)


def _asof(s: pd.Series, day: str) -> float | None:
    x = s[s.index <= day]
    return float(x.iloc[-1]) if len(x) else None


async def benchmark_series(client: httpx.AsyncClient) -> dict[str, pd.Series]:
    """Daily TL closes for each benchmark, plus live prices under "_son"."""
    out, live = {}, {}
    fx = _series(await bist.fetch(client, bist.FX, "1d"))
    fx_now = await bist.last_price(client, bist.FX)
    try:
        out["XU100"] = _series(await bist.fetch(client, bist.INDEX, "1d"))
        live["XU100"] = await bist.last_price(client, bist.INDEX)
    except Exception as e:
        log.warning("XU100 series failed: %s", e)
    try:
        btc = _series(await market.fetch_klines(client, "BTCUSDT", "1d"))
        out["BTC"] = pd.Series([v * (_asof(fx, d) or float("nan")) for d, v in btc.items()], index=btc.index).dropna()
        live["BTC"] = await market.last_price(client, "BTCUSDT") * fx_now
    except Exception as e:
        log.warning("BTC series failed: %s", e)
    try:
        out["GRAM_ALTIN"] = _series(await assets.daily(client, "GRAM_ALTIN"))
        live["GRAM_ALTIN"] = await assets.last_price(client, "GRAM_ALTIN")
    except Exception as e:
        log.warning("Gold series failed: %s", e)
    out["USD"], live["USD"] = fx, fx_now
    out["_son"] = live
    return out


def compare(rows: list[dict], series: dict, rate: float | None, today: str | None = None) -> dict:
    """rows: [{acilis (ISO), maliyet_tl, deger_tl}]. Portfolio vs each benchmark over the same periods. Pure."""
    today = today or datetime.now(TR).date().isoformat()
    cost = sum(r["maliyet_tl"] for r in rows)
    value = sum(r["deger_tl"] for r in rows)
    if not cost:
        return {"portfoy_yuzde": None, "kiyas": []}
    result = []
    for key, label in BENCHMARKS:
        s = series.get(key)
        now = series.get("_son", {}).get(key)
        if s is None or now is None:
            result.append({"ad": label, "yuzde": None})
            continue
        bench, ok = 0.0, True
        for r in rows:
            start = _asof(s, r["acilis"][:10])
            if not start:
                ok = False
                break
            bench += r["maliyet_tl"] * now / start
        result.append({"ad": label, "yuzde": round((bench / cost - 1) * 100, 2) if ok else None})
    if rate:
        bench = 0.0
        for r in rows:
            days = (datetime.fromisoformat(today) - datetime.fromisoformat(r["acilis"][:10])).days
            bench += r["maliyet_tl"] * (1 + rate / 100 / 365) ** max(days, 0)
        result.append({"ad": f"Mevduat %{rate:g}", "yuzde": round((bench / cost - 1) * 100, 2)})
    else:
        result.append({"ad": "Mevduat", "yuzde": None, "not": "faiz gir: /kiyas faiz 45"})
    mine = round((value / cost - 1) * 100, 2)
    for b in result:
        b["fark"] = None if b["yuzde"] is None else round(mine - b["yuzde"], 2)
    return {"portfoy_yuzde": mine, "kiyas": result}


def rows_from_portfolio(pf: dict) -> list[dict]:
    """TL cost/value per open position from collect_portfolio() output."""
    fx_now = pf.get("usdtry")
    rows = []
    for g in pf["gruplar"]:
        for r in g.get("satirlar", []):
            if r.get("tarih_yok"):
                continue  # bought on an unknown day: no fair comparison
            if r["para"] == "TL":
                rows.append({"acilis": r["acilis"], "maliyet_tl": r["maliyet"], "deger_tl": r["deger"]})
            elif fx_now:
                rows.append({"acilis": r["acilis"], "maliyet_tl": r["maliyet"] * fx_now, "deger_tl": r["deger"] * fx_now,
                             "usd": True})
    return rows


def text(res: dict, skipped: int = 0) -> str:
    note = (f"\n📅 {skipped} varlığın alış tarihi bilinmiyor, kıyasa girmedi: /duzelt ID tarih=2025-03-01" if skipped else "")
    if res["portfoy_yuzde"] is None:
        return "Kıyaslanacak (alış tarihi bilinen) pozisyon yok." + note
    lines = [f"🏁 KIYAS (TL bazında, aynı tarihlerde aynı parayı koysaydın)",
             f"Senin portföyün: %{res['portfoy_yuzde']:+.2f}"]
    for b in res["kiyas"]:
        if b["yuzde"] is None:
            lines.append(f"  {b['ad']}: —" + (f" ({b['not']})" if b.get("not") else " (veri yok)"))
            continue
        mark = "✅ yendin" if b["fark"] > 0 else "❌ geride"
        lines.append(f"  {b['ad']}: %{b['yuzde']:+.2f} → {mark} ({b['fark']:+.2f} puan)")
    lines.append("Kripto maliyetleri alış günündeki kurla değil bugünkü kurla TL'ye çevrilir; kur farkı ayrıca "
                 "portföydeki 'TL bazında' satırında.")
    return "\n".join(lines) + note


def skipped_count(pf: dict) -> int:
    return sum(1 for g in pf["gruplar"] for r in g.get("satirlar", []) if r.get("tarih_yok"))


# --- after-sale follow-up ----------------------------------------------------------------------------

def _sold_groups(items: list[dict]) -> dict[tuple, list[dict]]:
    groups: dict[tuple, list[dict]] = {}
    for p in items:
        if p["durum"] == "kapali" and p.get("kapanis_zamani") and p.get("kapanis_fiyat"):
            groups.setdefault((p["symbol"], p["kapanis_zamani"][:16]), []).append(p)
    return groups


def verdict(pct: float) -> str:
    if pct >= AFTER_SALE_PCT:
        return "erken satış"
    if pct <= -AFTER_SALE_PCT:
        return "iyi çıkış"
    return "nötr"


async def _price(client: httpx.AsyncClient, p: dict) -> float:
    if assets.is_other(p):
        return await assets.last_price(client, p["symbol"])
    if p.get("piyasa") == "BIST":
        return await bist.last_price(client, p["symbol"])
    if p.get("piyasa") == "ABD":
        import us
        return await us.last_price(client, p["symbol"])
    return await market.last_price(client, p["symbol"])


async def after_sale_check(now: datetime | None = None) -> list[str]:
    """Messages for sells that reached 5 or 20 days today. Marks them so each is reported once."""
    now = now or alerts_store.now_tr()
    items = positions.load()
    msgs, changed = [], False
    async with httpx.AsyncClient() as client:
        for (sym, minute), group in _sold_groups(items).items():
            sold = datetime.fromisoformat(group[0]["kapanis_zamani"])
            age = (now - sold).days
            done = group[0].get("satis_sonrasi", {})
            due = [d for d in CHECK_DAYS if age >= d and str(d) not in done and age < d + 7]
            if not due:
                continue
            try:
                price = await _price(client, group[0])
            except Exception as e:
                log.warning("After-sale price failed for %s: %s", sym, e)
                continue
            sell = group[0]["kapanis_fiyat"]
            pct = (price / sell - 1) * 100
            for p in group:
                p.setdefault("satis_sonrasi", {}).update({str(d): round(pct, 2) for d in due})
            changed = True
            qty = sum(p["adet"] for p in group)
            cur = group[0].get("para", "USD")
            name = assets.name(sym) if assets.is_other(group[0]) else bist.ticker(sym) if group[0].get("piyasa") == "BIST" else group[0]["pair"]
            v = verdict(pct)
            icon = {"erken satış": "😬", "iyi çıkış": "👍", "nötr": "➖"}[v]
            # tagged with the sold item's market: the send gate drops it when that market is switched off
            msgs.append(notify_prefs.tag(
                f"{icon} {name}: sattıktan {max(due)} gün sonra %{pct:+.2f} ({sell:g} → {price:g}) — {v}. "
                f"Tutsaydın fark {qty * (price - sell):+,.2f} {cur}."
                + (" Bir dahaki sefere satmadan önce iz süren stopu kullan." if v == "erken satış" else ""),
                None if assets.is_other(group[0]) else group[0].get("piyasa", "KRIPTO")))
    if changed:
        positions.save(items)
    return msgs


def after_sale_summary(since: str) -> dict:
    """For the journal: how sells looked 5 days later."""
    rows = []
    for group in _sold_groups(positions.load()).values():
        p = group[0]
        if p["kapanis_zamani"] >= since and "5" in p.get("satis_sonrasi", {}):
            rows.append(p["satis_sonrasi"]["5"])
    return {"n": len(rows), "erken": sum(r >= AFTER_SALE_PCT for r in rows),
            "iyi": sum(r <= -AFTER_SALE_PCT for r in rows),
            "ort_5g": round(sum(rows) / len(rows), 2) if rows else None}

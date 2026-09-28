"""Measurements, not predictions: a user's own report card, portfolio health, and the trend rule's live record.

- /api/karne           closed trades from the user's own portfolio: hit rate, average win/loss, holding time,
                       sales below the stop, and what the price did after each sale
- /api/portfolio/health open positions: weight (in TL), fall from the peak since buying, where the tested crypto
                       trend rule stands, pairs that move together (90-day daily returns)
- trend live record    every entry/exit of the crypto trend rule from the day it went live, with the result;
                       only trades that START after the record began count (no back-filled winners)
All prices are closed daily candles (chart_data), never the forming one.
"""
import datetime as dt
import math
import time

from fastapi import APIRouter, Depends

import chart_data
import trend_rule

COST = 0.001            # per side, crypto (same as the history test)
HIGH_CORR = 0.8
HEAVY_PCT = 40.0


def _ts(iso: str | None) -> float:
    try:
        return dt.datetime.fromisoformat(iso).timestamp() if iso else 0.0
    except ValueError:
        return 0.0


def daily_closes(doc: dict, market: str, now: float | None = None) -> list[tuple[float, float]]:
    """[(close time, close)] of CLOSED daily candles."""
    import user_alerts
    now = time.time() if now is None else now
    out = []
    for c in doc.get("candles") or []:
        closed_at = user_alerts.bar_close_ts(c, market, "1d")
        if closed_at <= now:
            out.append((closed_at, c["c"]))
    return out


def correlation(a: list[tuple[float, float]], b: list[tuple[float, float]], days: int = 90) -> float | None:
    """Pearson correlation of daily returns on common dates (last `days` returns)."""
    da = {dt.datetime.fromtimestamp(t, dt.timezone.utc).date(): c for t, c in a}
    db_ = {dt.datetime.fromtimestamp(t, dt.timezone.utc).date(): c for t, c in b}
    days_common = sorted(set(da) & set(db_))[-(days + 1):]
    if len(days_common) < 30:
        return None
    ra = [da[days_common[i]] / da[days_common[i - 1]] - 1 for i in range(1, len(days_common))]
    rb = [db_[days_common[i]] / db_[days_common[i - 1]] - 1 for i in range(1, len(days_common))]
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va, vb = sum((x - ma) ** 2 for x in ra), sum((y - mb) ** 2 for y in rb)
    return None if va <= 0 or vb <= 0 else round(cov / math.sqrt(va * vb), 2)


def report(doc: dict, after: dict[str, tuple[float, float]] | None = None) -> dict:
    """Pure: the user's report card from their portfolio document.
    after = {"PIYASA:KOD": (close time, last close)}; a sale's post-sale move needs a close AFTER the sale."""
    after = after or {}
    positions = {p["id"]: p for p in doc.get("positions", [])}
    trades = []
    for t in doc.get("transactions", []):
        if t.get("tur") != "satis":
            continue
        p = positions.get(t.get("pozisyon_id")) or {}
        cost = p.get("maliyet")
        if not cost:
            continue
        ret = (t["fiyat"] / cost - 1) * 100
        held = (_ts(t.get("zaman")) - _ts(p.get("acilis"))) / 86400 if p.get("acilis") else None
        stop = p.get("stop")
        seen = after.get(f"{t.get('piyasa')}:{t.get('kod')}")
        later = seen[1] if seen and seen[0] > _ts(t.get("zaman")) else None
        trades.append({"kod": t.get("kod"), "piyasa": t.get("piyasa"), "para": t.get("para"), "zaman": t.get("zaman"),
                       "fiyat": t["fiyat"], "maliyet": cost, "getiri_yuzde": round(ret, 2), "kar": t.get("kar"),
                       "gun": None if held is None else round(max(held, 0), 1),
                       "stop_alti": bool(stop is not None and t["fiyat"] < stop),
                       "sonra_yuzde": None if not later else round((later / t["fiyat"] - 1) * 100, 2)})
    wins = [x for x in trades if x["getiri_yuzde"] > 0]
    losses = [x for x in trades if x["getiri_yuzde"] <= 0]
    avg = lambda xs, k: round(sum(x[k] for x in xs) / len(xs), 2) if xs else None  # noqa: E731
    realized: dict[str, float] = {}
    for x in trades:
        realized[x["para"] or "USD"] = round(realized.get(x["para"] or "USD", 0.0) + float(x["kar"] or 0), 2)
    below = [x for x in trades if x["stop_alti"]]
    early = [x for x in trades if x["sonra_yuzde"] is not None and x["getiri_yuzde"] > 0 and x["sonra_yuzde"] >= 10]
    return {
        "islem": len(trades), "kazanan": len(wins), "kaybeden": len(losses),
        "isabet_yuzde": round(len(wins) / len(trades) * 100) if trades else None,
        "ort_kazanc_yuzde": avg(wins, "getiri_yuzde"), "ort_kayip_yuzde": avg(losses, "getiri_yuzde"),
        "ort_gun_kazanan": avg([x for x in wins if x["gun"] is not None], "gun"),
        "ort_gun_kaybeden": avg([x for x in losses if x["gun"] is not None], "gun"),
        "gerceklesen": realized,
        "stop_alti_satis": len(below), "stop_alti_ort_yuzde": avg(below, "getiri_yuzde"),
        "erken_satis": len(early),
        "islemler": sorted(trades, key=lambda x: x["zaman"] or "", reverse=True)[:30],
        "not": None if len(trades) >= 10 else "10 kapalı işlemden az: oranlar henüz tesadüfe açık.",
    }


def build_router(get_db, current_user) -> APIRouter:
    r = APIRouter(prefix="/api")

    async def last_bar(kod: str, market: str) -> tuple[float, float] | None:
        try:
            closes = daily_closes(await chart_data.chart(kod, "1d", market), market)
            return closes[-1] if closes else None
        except Exception:
            return None

    async def last_close(kod: str, market: str) -> float | None:
        bar = await last_bar(kod, market)
        return bar[1] if bar else None

    @r.get("/karne")
    async def my_report(user: dict = Depends(current_user)):
        doc = await get_db().portfolios.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
        after = {}
        for t in doc.get("transactions", [])[-200:]:
            if t.get("tur") == "satis":
                key = f"{t.get('piyasa')}:{t.get('kod')}"
                if key not in after:
                    after[key] = await last_bar(t["kod"], t["piyasa"])
        return report(doc, {k: v for k, v in after.items() if v})

    @r.get("/portfolio/health")
    async def health(user: dict = Depends(current_user)):
        doc = await get_db().portfolios.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
        usdtry = await last_close("USDTRY=X", "ABD")
        rows, series = [], {}
        for p in doc.get("positions", []):
            if p.get("durum") != "acik":
                continue
            try:
                ch = await chart_data.chart(p["kod"], "1d", p["piyasa"])
            except Exception:
                continue
            closes = daily_closes(ch, p["piyasa"])
            if not closes:
                continue
            last = closes[-1][1]
            since = [c for t, c in closes if t >= _ts(p.get("acilis")) - 86400] or [last]
            peak = max(max(since), p["maliyet"])
            value = p["adet"] * last
            tl = value if p.get("para") == "TL" else (value * usdtry if usdtry else None)
            trend = trend_rule.state(ch["candles"], ch.get("sma200") or []) if p["piyasa"] == "KRIPTO" else None
            series[p["id"]] = closes
            rows.append({"id": p["id"], "kod": p["kod"], "piyasa": p["piyasa"], "para": p.get("para"), "adet": p["adet"],
                         "maliyet": p["maliyet"], "fiyat": last, "deger": round(value, 2), "deger_tl": None if tl is None else round(tl, 2),
                         "getiri_yuzde": round((last / p["maliyet"] - 1) * 100, 2),
                         "tepeden_yuzde": round((last / peak - 1) * 100, 2), "stop": p.get("stop"),
                         "trend": None if not trend else {"trendde": trend["trendde"], "alt10": trend["alt10"],
                                                          "cikisa_uzaklik_yuzde": trend["cikisa_uzaklik_yuzde"]}})
        total = sum(x["deger_tl"] for x in rows if x["deger_tl"] is not None)
        for x in rows:
            x["agirlik_yuzde"] = round(x["deger_tl"] / total * 100, 1) if total and x["deger_tl"] is not None else None
        pairs = []
        ids = [x["id"] for x in rows]
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                c = correlation(series[ids[i]], series[ids[j]])
                if c is not None and c >= HIGH_CORR:
                    a, b = rows[i], rows[j]
                    if a["kod"] != b["kod"]:
                        pairs.append({"a": a["kod"], "b": b["kod"], "r": c})
        warnings = []
        for x in rows:
            if x["agirlik_yuzde"] and x["agirlik_yuzde"] > HEAVY_PCT and len(rows) > 1:
                warnings.append(f"{x['kod']} portföyünün %{x['agirlik_yuzde']:g}'i: tek varlığa çok bağlısın.")
            if x["trend"] and not x["trend"]["trendde"]:
                warnings.append(f"{x['kod']}: trend kuralına göre dışarıda (10 günün dibi {x['trend']['alt10']:.6g}).")
            if x["stop"] is None:
                warnings.append(f"{x['kod']}: stop yok.")
        for pr in pairs:
            warnings.append(f"{pr['a']} ile {pr['b']} birlikte hareket ediyor (90 günlük korelasyon {pr['r']:.2f}): risk açısından tek pozisyon say.")
        return {"pozisyonlar": sorted(rows, key=lambda x: -(x["agirlik_yuzde"] or 0)), "usdtry": usdtry,
                "toplam_tl": round(total, 2) if total else None, "korelasyon": pairs, "uyarilar": warnings}

    return r


# ---------------- live record of the crypto trend rule ----------------
async def record_trend(db, now: float | None = None) -> int:
    """Open a live trade on each NEW entry and close it on the exit. Returns the number of changes."""
    now = time.time() if now is None else now
    meta = await db.trend_live.find_one({"id": "meta"})
    if not meta:
        meta = {"id": "meta", "baslangic": now}
        await db.trend_live.insert_one(dict(meta))
    changes = 0
    for s in await trend_rule.universe_states():
        open_trade = await db.trend_live.find_one({"kod": s["kod"], "durum": "acik"})
        if s["trendde"] and not open_trade and s["degisim"] and s["degisim"] + 86400 > meta["baslangic"]:
            await db.trend_live.update_one({"id": f"t_{s['kod']}_{s['degisim']}"}, {"$setOnInsert": {
                "id": f"t_{s['kod']}_{s['degisim']}", "kod": s["kod"], "durum": "acik", "giris_t": s["degisim"],
                "giris": s["degisim_kapanis"]}}, upsert=True)
            changes += 1
        elif open_trade and not s["trendde"]:
            entry = open_trade.get("giris")
            exit_price = s["degisim_kapanis"] or s["kapanis"]  # the close of the exit candle
            ret = None if not entry else round(((exit_price * (1 - COST)) / (entry * (1 + COST)) - 1) * 100, 2)
            await db.trend_live.update_one({"id": open_trade["id"]}, {"$set": {
                "durum": "kapali", "cikis_t": s["degisim"], "cikis": exit_price, "getiri_yuzde": ret}})
            changes += 1
    return changes


async def trend_record(db) -> dict:
    meta = await db.trend_live.find_one({"id": "meta"}, {"_id": 0})
    trades = await db.trend_live.find({"kod": {"$exists": True}}, {"_id": 0}).sort("giris_t", -1).to_list(500)
    closed = [t for t in trades if t["durum"] == "kapali" and t.get("getiri_yuzde") is not None]
    states = {s["kod"]: s for s in await trend_rule.universe_states()}
    for t in trades:
        if t["durum"] == "acik" and t.get("giris") and t["kod"] in states:
            t["simdi_yuzde"] = round((states[t["kod"]]["kapanis"] / t["giris"] - 1) * 100, 2)
    wins = [t for t in closed if t["getiri_yuzde"] > 0]
    return {"baslangic": meta and dt.datetime.fromtimestamp(meta["baslangic"], dt.timezone.utc).isoformat(),
            "kapali": len(closed), "acik": sum(1 for t in trades if t["durum"] == "acik"),
            "isabet_yuzde": round(len(wins) / len(closed) * 100) if closed else None,
            "ort_getiri_yuzde": round(sum(t["getiri_yuzde"] for t in closed) / len(closed), 2) if closed else None,
            "islemler": trades[:40]}

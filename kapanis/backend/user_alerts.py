"""Users' own close-based alarms, checked by the web service; the bot only delivers them to Telegram.

Kinds
- price: "THYAO daily close above 300"      (tur=fiyat, yon=ustu|alti, seviye)
- RSI:   "BTC 4h RSI below 30"              (tur=rsi)
- automatic, from the user's portfolio: an open position's stop broken / target reached on a daily close.
Rules
- Only CLOSED candles count (same rule as the bot): crypto 1h/4h/1d, BIST and US daily (session close).
- A candle that closed before the alarm was created never fires it.
- Price/RSI alarms fire once, then stay in the list as "tetiklendi". A position warning fires once per level
  (moving the stop up creates a new warning level).
Every firing becomes an event (user_alert_events). The bot fetches undelivered events for users with a linked
Telegram chat and sends them with a link to the chart; events of users without Telegram are shown in the panel.
"""
import asyncio
import datetime as dt
import logging
import time
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import chart_data
import tom
import trend_rule

log = logging.getLogger(__name__)

MAX_ACTIVE = 20
CHECK_SECONDS = 300
TIMEFRAMES = {"KRIPTO": ["1h", "4h", "1d"], "BIST": ["1d"], "ABD": ["1d"]}
TF_SECONDS = {"1h": 3600, "4h": 14400, "1d": 86400}
TF_LABEL = {"1h": "1 saatlik", "4h": "4 saatlik", "1d": "günlük"}
TF_LABEL_EN = {"1h": "1-hour", "4h": "4-hour", "1d": "daily"}


def english(user: dict | None) -> bool:
    """The account chose English on the site (users.dil); messages written for it follow that choice."""
    return (user or {}).get("dil") == "en"
EVENT_DAYS = 30
CAPSULE_DAYS = 30


class AlertBody(BaseModel):
    piyasa: str
    kod: str
    tur: str = "fiyat"      # fiyat | rsi | trend (tested crypto trend rule: entry/exit changes, daily)
    yon: str = "ustu"       # ustu | alti
    seviye: float = 0.0
    tf: str = "1d"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def bar_close_ts(candle: dict, market: str, tf: str) -> float:
    """When a candle closed (UTC seconds). Daily BIST/US close at the session end, crypto daily at 00:00 UTC."""
    start = dt.datetime.fromtimestamp(candle["t"], dt.timezone.utc)
    if tf == "1d" and market in chart_data.DAILY_CLOSE_UTC:
        h, m = chart_data.DAILY_CLOSE_UTC[market]
        closes = start.replace(hour=h, minute=m, second=0, microsecond=0)
        if closes < start:
            closes += dt.timedelta(days=1)
        return closes.timestamp()
    return candle["t"] + TF_SECONDS.get(tf, 86400)


def last_closed_bar(doc: dict, market: str, tf: str, now: float | None = None) -> tuple[dict, float | None, float] | None:
    """(candle, rsi at that candle, close time) of the newest closed candle in a chart_data document."""
    now = time.time() if now is None else now
    candles, rsis = doc.get("candles") or [], doc.get("rsi") or []
    for i in range(len(candles) - 1, -1, -1):
        closed_at = bar_close_ts(candles[i], market, tf)
        if closed_at <= now:
            return candles[i], (rsis[i] if i < len(rsis) else None), closed_at
    return None


def crossed(value: float | None, yon: str, level: float) -> bool:
    if value is None:
        return False
    return value > level if yon == "ustu" else value < level


def _fmt(x) -> str:
    return "—" if x is None else f"{x:,.8g}".replace(",", "X").replace(".", ",").replace("X", ".")


def describe(a: dict, en: bool = False) -> str:
    if en:
        if a["tur"] == "ay_donumu":
            return f"{'BIST' if a['piyasa'] == 'BIST' else 'Crypto'} turn-of-the-month window (entry / exit days)"
        if a["tur"] == "trend":
            return f"{a['kod']} trend following (Donchian 20/10 + 200 days, daily)"
        what = "RSI" if a["tur"] == "rsi" else "close"
        return f"{a['kod']} {TF_LABEL_EN.get(a['tf'], a['tf'])} {what} {'above' if a['yon'] == 'ustu' else 'below'} {_fmt(a['seviye'])}"
    if a["tur"] == "ay_donumu":
        return f"{'BIST' if a['piyasa'] == 'BIST' else 'Kripto'} ay dönümü penceresi (giriş/çıkış günleri)"
    if a["tur"] == "trend":
        return f"{a['kod']} trend takibi (Donchian 20/10 + 200 gün, günlük)"
    what = "RSI" if a["tur"] == "rsi" else "kapanış"
    return f"{a['kod']} {TF_LABEL.get(a['tf'], a['tf'])} {what} {_fmt(a['seviye'])} {'üstünde' if a['yon'] == 'ustu' else 'altında'}"


def build_router(get_db, current_user, require_bot_key) -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.get("/alarms")
    async def my_alarms(user: dict = Depends(current_user)):
        d = get_db()
        alarms = await d.user_alerts.find({"user_id": user["id"]}, {"_id": 0}).sort("olusturma", -1).to_list(200)
        events = await d.user_alert_events.find({"user_id": user["id"]}, {"_id": 0, "chat_id": 0}) \
            .sort("zaman", -1).to_list(50)
        return {"alarmlar": alarms, "olaylar": events,
                "telegram": bool(user.get("telegram_chat_id")) or user.get("role") in ("owner", "admin"),
                "sinir": MAX_ACTIVE, "zaman_dilimleri": TIMEFRAMES}

    @r.post("/alarms")
    async def create_alarm(body: AlertBody, user: dict = Depends(current_user)):
        mkt = body.piyasa.upper()
        if mkt not in TIMEFRAMES:
            raise HTTPException(status_code=400, detail="Piyasa KRIPTO, BIST ya da ABD olmalı.")
        if body.tf not in TIMEFRAMES[mkt]:
            raise HTTPException(status_code=400, detail=f"{mkt} için zaman dilimi: {', '.join(TIMEFRAMES[mkt])}.")
        if body.tur not in ("fiyat", "rsi", "trend", "ay_donumu") or body.yon not in ("ustu", "alti"):
            raise HTTPException(status_code=400, detail="Tür fiyat/rsi/trend, yön ustu/alti olmalı.")
        if body.tur == "trend" and (mkt != "KRIPTO" or body.tf != "1d"):
            raise HTTPException(status_code=400, detail="Trend takibi yalnız kriptoda ve günlük kapanışta test edildi.")
        if body.tur == "ay_donumu":
            if mkt not in ("BIST", "KRIPTO"):
                raise HTTPException(status_code=400, detail="Ay dönümü BIST ve kripto için test edildi.")
            body.kod, body.tf = ("XU100" if mkt == "BIST" else "BTC"), "1d"
            if await get_db().user_alerts.find_one({"user_id": user["id"], "tur": "ay_donumu", "piyasa": mkt, "durum": "aktif"}):
                raise HTTPException(status_code=400, detail="Bu piyasa için ay dönümü bildirimi zaten açık.")
        if body.tur not in ("trend", "ay_donumu") and (not (0 < body.seviye < 1e9) or (body.tur == "rsi" and not 1 <= body.seviye <= 99)):
            raise HTTPException(status_code=400, detail="Seviye geçersiz (RSI için 1-99).")
        kod = (body.kod or "").strip().upper().removesuffix(".IS").removesuffix("/USDT")
        if not kod or len(kod) > 15 or not all(c.isalnum() or c in ".-" for c in kod):
            raise HTTPException(status_code=400, detail="Geçerli bir kod yaz (ör. THYAO, BTC, NVDA).")
        d = get_db()
        if await d.user_alerts.count_documents({"user_id": user["id"], "durum": "aktif"}) >= MAX_ACTIVE:
            raise HTTPException(status_code=400, detail=f"En fazla {MAX_ACTIVE} aktif alarm olabilir; eskilerden sil.")
        try:  # the symbol must exist on its market; also gives the current value for the answer
            doc = await chart_data.chart(kod, body.tf, mkt)
        except Exception:
            raise HTTPException(status_code=404, detail=f"{kod} {mkt} piyasasında bulunamadı.")
        bar = last_closed_bar(doc, mkt, body.tf)
        trend = trend_rule.state(doc["candles"], doc.get("sma200") or []) if body.tur == "trend" else None
        if body.tur == "trend" and not trend:
            raise HTTPException(status_code=400, detail=f"{kod} için yeterli günlük geçmiş yok.")
        now = _now()
        alarm = {"id": f"ua_{ObjectId()}", "user_id": user["id"], "piyasa": mkt, "kod": kod, "tur": body.tur,
                 "yon": body.yon, "seviye": body.seviye, "tf": body.tf, "durum": "aktif",
                 "olusturma": now.isoformat(), "olusturma_ts": now.timestamp(),
                 "son_kapanis": bar[0]["c"] if bar else None, "son_rsi": bar[1] if bar else None,
                 **({"trendde": trend["trendde"], "trend": trend} if trend else {})}
        await d.user_alerts.insert_one(dict(alarm))
        alarm.pop("_id", None)
        return alarm

    @r.delete("/alarms/{alarm_id}")
    async def delete_alarm(alarm_id: str, user: dict = Depends(current_user)):
        res = await get_db().user_alerts.delete_one({"id": alarm_id, "user_id": user["id"]})
        if not res.deleted_count:
            raise HTTPException(status_code=404, detail="Alarm bulunamadı.")
        return {"ok": True}

    @r.get("/strategies/lab")
    async def lab(_: dict = Depends(current_user)):
        """Every strategy we tested, with the same standard and a verdict (PRODUCTION / RESEARCH / REJECTED)."""
        import json
        import pathlib
        return json.loads((pathlib.Path(__file__).with_name("lab_results.json")).read_text(encoding="utf-8"))

    @r.get("/strategies/tom")
    async def tom_windows(_: dict = Depends(current_user)):
        return {"pencereler": [tom.window("BIST"), tom.window("KRIPTO")]}

    @r.get("/strategies/trend")
    async def trend_board(_: dict = Depends(current_user)):
        """The tested crypto trend rule: its history test and where each large coin stands today."""
        import insights
        return {"kanit": trend_rule.EVIDENCE, "coinler": await trend_rule.universe_states(),
                "canli": await insights.trend_record(get_db())}

    @r.get("/bot/alarm-events")
    async def pending_events(_: bool = Depends(require_bot_key)):
        """Undelivered events of users with a linked Telegram chat (oldest first)."""
        return await get_db().user_alert_events.find(
            {"gonderildi": False, "$or": [{"chat_id": {"$ne": None}}, {"sahip": True}]}, {"_id": 0}) \
            .sort("zaman", 1).to_list(50)

    @r.post("/bot/alarm-events/{event_id}/sent")
    async def event_sent(event_id: str, _: bool = Depends(require_bot_key)):
        await get_db().user_alert_events.update_one({"id": event_id}, {"$set": {"gonderildi": True}})
        return {"ok": True}

    return r


async def _event(db, user: dict, kod: str, piyasa: str, tf: str, text: str, key: str | None = None) -> bool:
    """Store one firing. key makes it idempotent (position warnings); False if it already existed."""
    doc = {"id": key or f"ue_{ObjectId()}", "user_id": str(user["_id"]), "kod": kod, "piyasa": piyasa, "tf": tf,
           "metin": text, "zaman": _now().isoformat(), "expires_at": _now() + dt.timedelta(days=EVENT_DAYS),
           # the owner's Telegram is the bot's own chat (not stored on the account): the bot sends those there
           "chat_id": user.get("telegram_chat_id"), "sahip": user.get("role") in ("owner", "admin"),
           "gonderildi": not (user.get("telegram_chat_id") or user.get("role") in ("owner", "admin"))}
    res = await db.user_alert_events.update_one({"id": doc["id"]}, {"$setOnInsert": doc}, upsert=True)
    return res.upserted_id is not None


async def run_once(db, now: float | None = None) -> int:
    """Check every active alarm and every open position's stop/target once. Returns the number of firings."""
    now = time.time() if now is None else now
    charts: dict[tuple, dict | None] = {}

    async def doc_of(mkt: str, kod: str, tf: str):
        await bar(mkt, kod, tf)
        return charts.get((mkt, kod, tf))

    async def bar(mkt: str, kod: str, tf: str):
        key = (mkt, kod, tf)
        if key not in charts:
            try:
                charts[key] = await chart_data.chart(kod, tf, mkt)
            except Exception as e:
                log.warning("Alarm data %s %s %s failed: %s", mkt, kod, tf, e)
                charts[key] = None
        doc = charts[key]
        return last_closed_bar(doc, mkt, tf, now) if doc else None

    users: dict[str, dict | None] = {}

    async def user_of(uid: str):
        if uid not in users:
            try:
                users[uid] = await db.users.find_one({"_id": ObjectId(uid)}, {"telegram_chat_id": 1, "role": 1, "dil": 1})
            except Exception:
                users[uid] = None
        return users[uid]

    fired = 0
    async for a in db.user_alerts.find({"durum": "aktif", "tur": "trend"}):
        doc = await doc_of("KRIPTO", a["kod"], "1d")
        st = trend_rule.state(doc["candles"], doc.get("sma200") or [], now) if doc else None
        if not st:
            continue
        await db.user_alerts.update_one({"id": a["id"]}, {"$set": {"son_kapanis": st["kapanis"], "trend": st}})
        if st["trendde"] == a.get("trendde"):
            continue
        await db.user_alerts.update_one({"id": a["id"]}, {"$set": {"trendde": st["trendde"]}})
        u = await user_of(a["user_id"])
        if not u:
            continue
        if st["trendde"]:
            text = (f"📈 {a['kod']}: trend takibi GİRİŞ — günlük kapanış {_fmt(st['kapanis'])}, 20 günün tepesinin "
                    f"({_fmt(st['ust20'])}) ve 200 günlük ortalamanın üstünde. Kuralın çıkışı: günlük kapanış "
                    f"{_fmt(st['alt10'])} (10 günün dibi, her gün güncellenir) altına inerse.")
        else:
            text = (f"📉 {a['kod']}: trend takibi ÇIKIŞ — günlük kapanış {_fmt(st['kapanis'])}, 10 günün dibinin "
                    f"({_fmt(st['alt10'])}) altında. Kural bu noktada piyasadan çıkar.")
        text += " Bu kural araştırma aşamasında: kazandırdığı kanıtlanmadı, düşüşte dışarıda kalmaya yarıyor. Karar senin."
        if english(u):
            text = ((f"📈 {a['kod']}: trend following ENTRY — daily close {_fmt(st['kapanis'])}, above the 20-day high "
                     f"({_fmt(st['ust20'])}) and the 200-day average. The rule exits if the daily close falls below "
                     f"{_fmt(st['alt10'])} (the 10-day low, updated each day).") if st["trendde"] else
                    (f"📉 {a['kod']}: trend following EXIT — daily close {_fmt(st['kapanis'])}, below the 10-day low "
                     f"({_fmt(st['alt10'])}). The rule leaves the market here."))
            text += " This rule is at the research stage: it is not proven to make money; it helps to stay out in a fall. The decision is yours."
        if await _event(db, u, a["kod"], "KRIPTO", "1d", text, key=f"trend_{a['id']}_{st['mum']}_{int(st['trendde'])}"):
            fired += 1

    # turn of the month: at noon (TR) on the entry day and on the exit day
    local = dt.datetime.fromtimestamp(now, tom.TR)
    if local.hour >= 12:
        async for a in db.user_alerts.find({"durum": "aktif", "tur": "ay_donumu"}):
            w = tom.window(a["piyasa"], local.date())
            days = w["gunler"]
            today = local.date().isoformat()
            u = await user_of(a["user_id"])
            if not u:
                continue
            close = "18:00 BIST kapanışı" if a["piyasa"] == "BIST" else "günlük kapanış (03:00 TR)"
            name = "BIST" if a["piyasa"] == "BIST" else "Kripto"
            if today == days[0]:
                text = (f"📅 {name} ay dönümü penceresi bugün başlıyor: kural bugünkü {close} ile girer, "
                        f"{days[-1][8:10]}.{days[-1][5:7]} kapanışında çıkar. Test edilmiş tek kural; kazancı küçük, karar senin.")
            elif today == days[-1]:
                text = f"📅 {name} ay dönümü penceresi bugün bitiyor: kural bugünkü {close} ile çıkar. Sıradaki pencere gelecek ay sonu."
            else:
                continue
            if english(u):
                close = "18:00 BIST close" if a["piyasa"] == "BIST" else "daily close (03:00 TR)"
                name = "BIST" if a["piyasa"] == "BIST" else "Crypto"
                text = ((f"📅 The {name} turn-of-the-month window starts today: the rule enters at today's {close} and exits at the close of "
                         f"{days[-1][8:10]}.{days[-1][5:7]}. The only tested rule; its gain is small, the decision is yours.") if today == days[0] else
                        f"📅 The {name} turn-of-the-month window ends today: the rule exits at today's {close}. The next window is at the end of next month.")
            if await _event(db, u, a["kod"], a["piyasa"], "1d", text, key=f"tom_{a['id']}_{today}"):
                fired += 1

    async for a in db.user_alerts.find({"durum": "aktif", "tur": {"$nin": ["trend", "ay_donumu"]}}):
        b = await bar(a["piyasa"], a["kod"], a["tf"])
        if not b:
            continue
        candle, rsi, closed_at = b
        value = rsi if a["tur"] == "rsi" else candle["c"]
        await db.user_alerts.update_one({"id": a["id"]}, {"$set": {"son_kapanis": candle["c"], "son_rsi": rsi}})
        if closed_at <= a["olusturma_ts"] or not crossed(value, a["yon"], a["seviye"]):
            continue
        u = await user_of(a["user_id"])
        if not u:
            continue
        when = dt.datetime.fromtimestamp(closed_at, dt.timezone.utc).isoformat()
        await db.user_alerts.update_one({"id": a["id"], "durum": "aktif"}, {"$set": {
            "durum": "tetiklendi", "tetik": {"zaman": when, "kapanis": candle["c"], "rsi": rsi}}})
        extra = f" (kapanış {_fmt(candle['c'])})" if a["tur"] == "rsi" else ""
        text = f"🔔 Alarmın: {describe(a)} — {TF_LABEL.get(a['tf'], a['tf'])} mum {_fmt(value)} ile kapandı{extra}."
        if english(u):
            extra = f" (close {_fmt(candle['c'])})" if a["tur"] == "rsi" else ""
            text = f"🔔 Your alert: {describe(a, en=True)} — the {TF_LABEL_EN.get(a['tf'], a['tf'])} candle closed at {_fmt(value)}{extra}."
        await _event(db, u, a["kod"], a["piyasa"], a["tf"], text)
        fired += 1

    # decision capsule: 30 days after buying, the thesis written at the time comes back with what happened since
    async for pf in db.portfolios.find({"positions.kapsul": {"$exists": True}}, {"user_id": 1, "positions": 1}):
        u = await user_of(pf["user_id"])
        if not u:
            continue
        for p in pf["positions"]:
            k = p.get("kapsul")
            opened = dt.datetime.fromisoformat(p.get("acilis") or "1970-01-01T00:00:00+00:00").timestamp()
            if not k or now - opened < CAPSULE_DAYS * 86400:
                continue
            b = await bar(p["piyasa"], p["kod"], "1d")
            if not b:
                continue
            last = b[0]["c"]
            ch = (last / p["maliyet"] - 1) * 100
            state = "hâlâ elinde" if p.get("durum") == "acik" else f"sattın ({_fmt(p.get('kapanis_fiyat'))})"
            text = (f"💊 Karar kapsülü — {p['kod']}, {CAPSULE_DAYS} gün önce {_fmt(p['maliyet'])}'den aldın.\n"
                    f"O gün yazdığın: “{k['tez']}”\n"
                    + (f"Çıkış şartın: “{k['cikis_sarti']}”\n" if k.get("cikis_sarti") else "")
                    + f"Şimdi: {_fmt(last)} ({ch:+.1f}%), {state}. Tezin tuttu mu, şartın gerçekleşti mi? Cevabını günlüğüne yaz.")
            if english(u):
                state = "you still hold it" if p.get("durum") == "acik" else f"you sold it ({_fmt(p.get('kapanis_fiyat'))})"
                text = (f"💊 Decision capsule — {p['kod']}, you bought it {CAPSULE_DAYS} days ago at {_fmt(p['maliyet'])}.\n"
                        f"What you wrote that day: “{k['tez']}”\n"
                        + (f"Your exit condition: “{k['cikis_sarti']}”\n" if k.get("cikis_sarti") else "")
                        + f"Now: {_fmt(last)} ({ch:+.1f}%), {state}. Did your thesis hold, did your condition happen? Write the answer in your journal.")
            if await _event(db, u, p["kod"], p["piyasa"], "1d", text, key=f"kapsul_{p['id']}"):
                fired += 1

    async for pf in db.portfolios.find({"positions.durum": "acik"}, {"user_id": 1, "positions": 1}):
        u = await user_of(pf["user_id"])
        if not u:
            continue
        for p in pf["positions"]:
            if p.get("durum") == "acik" and p.get("piyasa") == "KRIPTO":
                doc = await doc_of("KRIPTO", p["kod"], "1d")
                st = trend_rule.state(doc["candles"], doc.get("sma200") or [], now) if doc else None
                if st and st["kapanis"] < st["alt10"] and st["mum"] + 86400 > dt.datetime.fromisoformat(
                        p.get("acilis") or "1970-01-01T00:00:00+00:00").timestamp():
                    text = (f"📉 {p['kod']}: günlük kapanış {_fmt(st['kapanis'])}, 10 günün dibinin ({_fmt(st['alt10'])}) altında. "
                            "Trend kuralı burada çıkar; geçmişte büyük düşüşlerin çoğundan böyle uzak durdu (kazandırdığı kanıtlanmadı). "
                            "Karar senin.")
                    if english(u):
                        text = (f"📉 {p['kod']}: daily close {_fmt(st['kapanis'])}, below the 10-day low ({_fmt(st['alt10'])}). "
                                "The trend rule exits here; in the past it stayed away from most large falls this way (not proven to make money). "
                                "The decision is yours.")
                    if await _event(db, u, p["kod"], "KRIPTO", "1d", text, key=f"pos_{p['id']}_trend_{st['mum']}"):
                        fired += 1
            if p.get("durum") != "acik" or (p.get("stop") is None and p.get("hedef") is None):
                continue
            b = await bar(p["piyasa"], p["kod"], "1d")
            if not b:
                continue
            candle, _, closed_at = b
            if closed_at <= dt.datetime.fromisoformat(p.get("acilis") or "1970-01-01T00:00:00+00:00").timestamp():
                continue
            day = dt.datetime.fromtimestamp(closed_at, dt.timezone.utc).date().isoformat()
            if p.get("stop") is not None and candle["c"] < p["stop"]:
                text = (f"🔴 {p['kod']}: günlük kapanış {_fmt(candle['c'])}, stopun {_fmt(p['stop'])} altında. "
                        "Kural: kapanışla stop kırıldı. Karar senin; sattıysan portföyünde 'Sattım' ile kaydet.")
                if english(u):
                    text = (f"🔴 {p['kod']}: daily close {_fmt(candle['c'])}, below your stop {_fmt(p['stop'])}. "
                            "Rule: the stop broke on a close. The decision is yours; if you sold, record it in your portfolio.")
                if await _event(db, u, p["kod"], p["piyasa"], "1d", text, key=f"pos_{p['id']}_stop_{p['stop']}"):
                    fired += 1
            elif p.get("hedef") is not None and candle["c"] >= p["hedef"]:
                text = (f"🎯 {p['kod']}: günlük kapanış {_fmt(candle['c'])}, hedefin {_fmt(p['hedef'])} üstünde "
                        f"({day}). Kâr al ya da stopu yukarı taşı; plan için Kriz Planı sayfası.")
                if english(u):
                    text = (f"🎯 {p['kod']}: daily close {_fmt(candle['c'])}, above your target {_fmt(p['hedef'])} "
                            f"({day}). Take profit or move the stop up; see the Crisis Plan page for a plan.")
                if await _event(db, u, p["kod"], p["piyasa"], "1d", text, key=f"pos_{p['id']}_hedef_{p['hedef']}"):
                    fired += 1
    return fired


async def ensure_indexes(db):
    await db.user_alerts.create_index([("user_id", 1), ("durum", 1)])
    await db.user_alert_events.create_index([("user_id", 1), ("zaman", -1)])
    await db.user_alert_events.create_index([("gonderildi", 1), ("zaman", 1)])
    await db.user_alert_events.create_index("expires_at", expireAfterSeconds=0)


async def loop(get_db):
    """Background checker started with the web service."""
    await asyncio.sleep(20)
    while True:
        try:
            n = await run_once(get_db())
            if n:
                log.info("User alarms fired: %d", n)
            import insights
            await insights.record_trend(get_db())
            w = await weekly_once(get_db())
            if w:
                log.info("Weekly summaries queued: %d", w)
        except Exception:
            log.exception("User alarm check failed")
        await asyncio.sleep(CHECK_SECONDS)


# ---------------- weekly summary (Sunday evening, same delivery path) ----------------
TR = dt.timezone(dt.timedelta(hours=3))
WEEKLY_AT = (6, 20)       # Sunday (weekday 6) 20:00 Turkish time
NEAR_STOP_PCT = 3.0


def _money(v: float, cur: str) -> str:
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{_fmt(round(abs(v), 2))} {'TL' if cur == 'TL' else '$'}"


def close_on_or_before(doc: dict, market: str, ts: float) -> float | None:
    """Close of the last daily candle that had closed by ts."""
    best = None
    for c in doc.get("candles") or []:
        if bar_close_ts(c, market, "1d") <= ts:
            best = c["c"]
    return best


async def weekly_text(db, user: dict, now: float) -> str | None:
    """One Telegram message: the week's result per currency, closed trades, fired alarms, positions near the stop."""
    uid = str(user["_id"])
    week_ago = now - 7 * 86400
    since_iso = dt.datetime.fromtimestamp(week_ago, dt.timezone.utc).isoformat()
    pf = await db.portfolios.find_one({"user_id": uid}) or {}
    moves: dict[str, float] = {}
    near, lines = [], []
    for p in pf.get("positions", []):
        if p.get("durum") != "acik":
            continue
        try:
            doc = await chart_data.chart(p["kod"], "1d", p["piyasa"])
        except Exception:
            continue
        last = close_on_or_before(doc, p["piyasa"], now)
        if last is None:
            continue
        opened = dt.datetime.fromisoformat(p["acilis"]).timestamp() if p.get("acilis") else 0
        base = p["maliyet"] if opened > week_ago else close_on_or_before(doc, p["piyasa"], week_ago)
        if base:
            cur = p.get("para") or "USD"
            moves[cur] = moves.get(cur, 0.0) + p["adet"] * (last - base)
        if p.get("stop") and last > p["stop"] and (last / p["stop"] - 1) * 100 <= NEAR_STOP_PCT:
            near.append(f"{p['kod']} {_fmt(last)} (stop {_fmt(p['stop'])}, {(last / p['stop'] - 1) * 100:.1f}% above)" if english(user) else
                        f"{p['kod']} {_fmt(last)} (stop {_fmt(p['stop'])}, %{(last / p['stop'] - 1) * 100:.1f} yukarıda)")
    realized: dict[str, float] = {}
    sold = []
    for t in pf.get("transactions", []):
        if t.get("tur") == "satis" and t.get("zaman", "") >= since_iso:
            cur = t.get("para") or "USD"
            realized[cur] = realized.get(cur, 0.0) + float(t.get("kar") or 0)
            sold.append(t["kod"])
    fired = await db.user_alert_events.count_documents({"user_id": uid, "zaman": {"$gte": since_iso}, "tur": {"$ne": "ozet"}})
    if not moves and not realized and not fired and not near:
        return None
    if english(user):
        lines.append("📅 Weekly summary")
        if moves:
            lines.append("Open positions this week: " + " · ".join(_money(v, c) for c, v in moves.items()) + " (at daily closes, unrealized)")
        if realized:
            lines.append(f"Closed ({', '.join(dict.fromkeys(sold))}): " + " · ".join(_money(v, c) for c, v in realized.items()))
        if fired:
            lines.append(f"{fired} alerts / warnings arrived this week (details: My Alerts).")
        if near:
            lines.append("⚠️ Close to the stop: " + "; ".join(near[:5]))
        lines.append("Past results do not show the future; the decision is yours.")
        return "\n".join(lines)
    lines.append("📅 Haftalık özet")
    if moves:
        lines.append("Açık pozisyonlar bu hafta: " + " · ".join(_money(v, c) for c, v in moves.items())
                     + " (günlük kapanışlarla, gerçekleşmemiş)")
    if realized:
        lines.append(f"Kapattıkların ({', '.join(dict.fromkeys(sold))}): " + " · ".join(_money(v, c) for c, v in realized.items()))
    if fired:
        lines.append(f"Bu hafta {fired} alarm/uyarı geldi (ayrıntı: Alarmlarım).")
    if near:
        lines.append("⚠️ Stopa yakın: " + "; ".join(near[:5]))
    lines.append("Geçmiş sonuç geleceği göstermez; karar senin.")
    return "\n".join(lines)


async def weekly_once(db, now: float | None = None) -> int:
    """Send the Sunday summary once per week (idempotent through the event id)."""
    now = time.time() if now is None else now
    local = dt.datetime.fromtimestamp(now, TR)
    if (local.weekday(), local.hour) < WEEKLY_AT or local.weekday() != WEEKLY_AT[0]:
        return 0
    week = local.strftime("%G-%V")
    sent = 0
    async for u in db.users.find({"$or": [{"telegram_chat_id": {"$ne": None}}, {"role": {"$in": ["owner", "admin"]}}]},
                                 {"telegram_chat_id": 1, "role": 1, "dil": 1}):
        key = f"ozet_{u['_id']}_{week}"
        if await db.user_alert_events.find_one({"id": key}, {"_id": 1}):
            continue
        text = await weekly_text(db, u, now)
        if text and await _event(db, u, "", "", "1w", text, key=key):
            await db.user_alert_events.update_one({"id": key}, {"$set": {"tur": "ozet"}})
            sent += 1
    return sent

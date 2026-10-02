"""Per-user data: each signed-in person's own real portfolio and their Telegram link.

Every query filters on the verified user id taken from the session; a user id is never read from the
request body or URL. Kapanış records what the user tells it; it never connects to a broker and never trades.

portfolios (one document per user)
  user_id, rev, cash_balance {TL, USD},
  positions   [{id, piyasa, kod, adet, maliyet, stop, hedef, acilis, durum, kapanis_fiyat, kapanis}]
  transactions[{id, zaman, tur: alis|satis|nakit|silme, piyasa, kod, adet, fiyat, tutar, para, pozisyon_id, kar}]

telegram_links: {code_hash, user_id, expires_at, used} - one-time codes, 10 minutes, stored hashed.
"""
import asyncio
import hashlib
import httpx
import math
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import chart_data
import limits

# Users' own AI API keys are stored encrypted with this Fernet key (web process env only, never in git).
# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
KEY_ENCRYPTION_KEY = os.environ.get("KEY_ENCRYPTION_KEY", "")
PROVIDERS = {
    # name: (label, how to check the key without spending anything meaningful)
    "deepseek": ("DeepSeek", "GET", "https://api.deepseek.com/models", None),
    "nvidia": ("NVIDIA (Kimi / GLM)", "POST", "https://integrate.api.nvidia.com/v1/chat/completions",
               {"model": "meta/llama-3.1-8b-instruct", "messages": [{"role": "user", "content": "ok"}], "max_tokens": 1}),
}


def _fernet():
    from cryptography.fernet import Fernet
    if not KEY_ENCRYPTION_KEY:
        raise HTTPException(status_code=503, detail="Sunucuda anahtar şifreleme ayarlı değil (KEY_ENCRYPTION_KEY).")
    return Fernet(KEY_ENCRYPTION_KEY.encode())


def mask(tail: str) -> str:
    return f"••••{tail}"

STREAM_SECONDS = 300  # one live-update connection; the browser reconnects after it
MARKETS = {"KRIPTO": "USD", "BIST": "TL", "ABD": "USD"}
LINK_MINUTES = 10
MAX_OPEN_POSITIONS = 200


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _num(v, name: str, positive: bool = True) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} sayı olmalı.")
    if not math.isfinite(x) or (x <= 0 if positive else x < 0):
        raise HTTPException(status_code=400, detail=f"{name} {'sıfırdan büyük' if positive else 'negatif olmayan'} bir sayı olmalı.")
    return x


def _code(kod: str) -> str:
    k = (kod or "").strip().upper().removesuffix(".IS").removesuffix(".US").split("/")[0]
    if not k or len(k) > 15 or not all(c.isalnum() or c in ".-" for c in k):
        raise HTTPException(status_code=400, detail="Geçerli bir kod yaz (ör. THYAO, BTC, NVDA).")
    return k


def hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


class PositionBody(BaseModel):
    piyasa: str
    kod: str
    adet: float
    maliyet: float
    stop: Optional[float] = None
    hedef: Optional[float] = None
    tez: Optional[str] = None          # karar kapsülü: neden aldım
    cikis_sarti: Optional[str] = None  # karar kapsülü: ne olursa satarım


class StopBody(BaseModel):
    stop: float


class SellBody(BaseModel):
    fiyat: float
    adet: Optional[float] = None


class CashBody(BaseModel):
    para: str
    tutar: float


class AiKeyBody(BaseModel):
    saglayici: str
    anahtar: str


class LinkBody(BaseModel):
    code: str
    chat_id: int
    username: Optional[str] = None


class BotPositionBody(PositionBody):
    chat_id: int


class BotChatBody(BaseModel):
    chat_id: int


class ApplyRiskBody(BaseModel):
    position_ids: list[str] = []


async def ensure_indexes(db):
    await db.portfolios.create_index("user_id", unique=True)
    await db.telegram_links.create_index("code_hash", unique=True)
    await db.telegram_links.create_index("expires_at", expireAfterSeconds=3600)
    await db.risk_proposals.create_index("expires_at", expireAfterSeconds=0)


def build_router(get_db, current_user, require_bot_key, require_owner=None) -> APIRouter:
    """get_db() returns the current database handle (looked up per request, so tests can swap it)."""
    r = APIRouter(prefix="/api")

    async def load(uid: str) -> dict:
        doc = await get_db().portfolios.find_one({"user_id": uid}, {"_id": 0})
        if doc is None:
            doc = {"user_id": uid, "rev": 0, "cash_balance": {"TL": 0.0, "USD": 0.0}, "positions": [],
                   "transactions": [], "risk_target_pct": 1.0, "risk_mode": "normal"}
            await get_db().portfolios.update_one({"user_id": uid}, {"$setOnInsert": doc}, upsert=True)
            doc = await get_db().portfolios.find_one({"user_id": uid}, {"_id": 0})
        doc.setdefault("risk_target_pct", 1.0)
        doc.setdefault("risk_mode", "normal")
        return doc

    async def save(doc: dict):
        """Optimistic write: fails instead of overwriting a change made in another tab meanwhile."""
        rev = doc["rev"]
        res = await get_db().portfolios.update_one(
            {"user_id": doc["user_id"], "rev": rev},
            {"$set": {"cash_balance": doc["cash_balance"], "positions": doc["positions"],
                      "transactions": doc["transactions"][-2000:], "rev": rev + 1,
                      "risk_target_pct": doc["risk_target_pct"], "risk_mode": doc["risk_mode"]}})
        if res.matched_count == 0:
            raise HTTPException(status_code=409, detail="Portföy başka bir sekmede değişti; sayfayı yenileyip tekrar dene.")
        doc["rev"] = rev + 1
        return doc

    def tx(doc, **kw):
        doc["transactions"].append({"id": f"tx_{ObjectId()}", "zaman": _now().isoformat(), **kw})

    def find_open(doc, pid):
        pos = next((p for p in doc["positions"] if p["id"] == pid), None)
        if not pos or pos["durum"] != "acik":
            raise HTTPException(status_code=404, detail="Açık pozisyon bulunamadı.")
        return pos

    @r.get("/portfolio")
    async def get_portfolio(user: dict = Depends(current_user)):
        return await load(user["id"])

    @r.get("/portfolio/stream")
    async def portfolio_stream(user: dict = Depends(current_user)):
        """Server-sent events: 'rev' whenever this user's portfolio changes (e.g. /ekle in Telegram).
        Only the revision number is sent, never portfolio contents; the page then reloads its own data.
        Each connection lasts 5 minutes and the browser reconnects (with a fresh session token)."""
        uid = user["id"]
        slot = limits.StreamSlot(uid).__enter__()  # 429 when this user already has too many open

        async def events():
            try:
                last, beat, started = None, time.monotonic(), time.monotonic()
                while time.monotonic() - started < STREAM_SECONDS:
                    doc = await get_db().portfolios.find_one({"user_id": uid}, {"rev": 1})
                    rev = (doc or {}).get("rev", 0)
                    if rev != last:
                        yield f"event: rev\ndata: {rev}\n\n"
                        last, beat = rev, time.monotonic()
                    elif time.monotonic() - beat > 15:
                        yield ": ping\n\n"
                        beat = time.monotonic()
                    await asyncio.sleep(1.5)
            finally:
                slot.__exit__(None, None, None)  # also when the browser closes the tab

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @r.post("/portfolio/positions")
    async def add_position(body: PositionBody, user: dict = Depends(current_user)):
        mkt = body.piyasa.upper()
        if mkt not in MARKETS:
            raise HTTPException(status_code=400, detail="Piyasa KRIPTO, BIST ya da ABD olmalı.")
        kod = _code(body.kod)
        adet, maliyet = _num(body.adet, "Adet"), _num(body.maliyet, "Maliyet")
        if mkt == "BIST" and not float(adet).is_integer():
            raise HTTPException(status_code=400, detail="BIST'te adet tam sayı olmalı.")
        stop = _num(body.stop, "Stop") if body.stop is not None else None
        hedef = _num(body.hedef, "Hedef") if body.hedef is not None else None
        if stop is not None and stop >= maliyet:
            raise HTTPException(status_code=400, detail="Stop maliyetin altında olmalı (spot, yalnız alım).")
        if hedef is not None and hedef <= maliyet:
            raise HTTPException(status_code=400, detail="Hedef maliyetin üstünde olmalı.")
        doc = await load(user["id"])
        if sum(1 for p in doc["positions"] if p["durum"] == "acik") >= MAX_OPEN_POSITIONS:
            raise HTTPException(status_code=400, detail=f"En fazla {MAX_OPEN_POSITIONS} açık pozisyon.")
        pos = {"id": f"up_{ObjectId()}", "piyasa": mkt, "kod": kod, "adet": adet, "maliyet": maliyet, "stop": stop,
               "hedef": hedef, "para": MARKETS[mkt], "acilis": _now().isoformat(), "durum": "acik",
               **({"kapsul": {"tez": (body.tez or "").strip()[:500], "cikis_sarti": (body.cikis_sarti or "").strip()[:300]}}
                  if (body.tez or "").strip() else {})}
        doc["positions"].append(pos)
        tx(doc, tur="alis", piyasa=mkt, kod=kod, adet=adet, fiyat=maliyet, tutar=round(adet * maliyet, 2),
           para=MARKETS[mkt], pozisyon_id=pos["id"])
        await save(doc)
        return pos

    @r.get("/bot/telegram/linked/{chat_id}")
    async def telegram_linked(chat_id: int, _: bool = Depends(require_bot_key)):
        """Is this Telegram chat linked to a site account? (the bot asks before doing costly work)"""
        return {"bagli": bool(await get_db().users.find_one({"telegram_chat_id": chat_id}, {"_id": 1}))}

    @r.post("/bot/telegram/position")
    async def telegram_add_position(body: BotPositionBody, _: bool = Depends(require_bot_key)):
        """A linked private Telegram chat records a purchase; no broker order is placed."""
        accounts = await get_db().users.find({"telegram_chat_id": body.chat_id}, {"_id": 1, "email": 1}).to_list(2)
        if not accounts:
            raise HTTPException(status_code=404, detail="Bu Telegram hesabı siteye bağlı değil.")
        if len(accounts) > 1:  # never guess which account a purchase belongs to
            raise HTTPException(status_code=409, detail="Bu Telegram sohbeti birden fazla hesaba bağlı görünüyor; sitede bağlantıyı yeniden kur.")
        account = accounts[0]
        uid = str(account["_id"])
        pos = await add_position(PositionBody(**body.model_dump(exclude={"chat_id"})), {"id": uid})
        # mark where it came from (the panel shows "Telegram'dan eklendi"); rev already moved in add_position
        await get_db().portfolios.update_one({"user_id": uid, "positions.id": pos["id"]}, {"$set": {"positions.$.kaynak": "telegram"}})
        email = account.get("email") or ""
        name, _, domain = email.partition("@")
        return {**pos, "kaynak": "telegram", "hesap": (name[:2] + "***@" + domain) if domain else ""}

    @r.patch("/portfolio/positions/{pid}/stop")
    async def move_stop(pid: str, body: StopBody, user: dict = Depends(current_user)):
        stop = _num(body.stop, "Stop")
        doc = await load(user["id"])
        pos = find_open(doc, pid)
        # Goalpost rule, same as the bot: an open position's stop may only move up.
        if pos.get("stop") is not None and stop < pos["stop"]:
            raise HTTPException(status_code=409, detail=f"Stop aşağı çekilemez (şu an {pos['stop']:g}). Kural: stop yalnız yukarı.")
        pos["stop"] = stop
        await save(doc)
        return pos

    @r.post("/portfolio/positions/{pid}/sell")
    async def sell(pid: str, body: SellBody, user: dict = Depends(current_user)):
        price = _num(body.fiyat, "Satış fiyatı")
        doc = await load(user["id"])
        pos = find_open(doc, pid)
        qty = pos["adet"] if body.adet is None else _num(body.adet, "Adet")
        if qty > pos["adet"] + 1e-12:
            raise HTTPException(status_code=400, detail=f"Elinde {pos['adet']:g} adet var.")
        if pos["piyasa"] == "BIST" and not float(qty).is_integer():
            raise HTTPException(status_code=400, detail="BIST'te adet tam sayı olmalı.")
        profit = round((price - pos["maliyet"]) * qty, 2)
        tx(doc, tur="satis", piyasa=pos["piyasa"], kod=pos["kod"], adet=qty, fiyat=price, tutar=round(qty * price, 2),
           para=pos["para"], pozisyon_id=pos["id"], kar=profit)
        if abs(qty - pos["adet"]) < 1e-12:
            pos.update(durum="kapali", kapanis_fiyat=price, kapanis=_now().isoformat())
        else:
            pos["adet"] = round(pos["adet"] - qty, 10)
        await save(doc)
        return {"pozisyon": pos, "kar": profit}

    @r.delete("/portfolio/positions/{pid}")
    async def delete_position(pid: str, user: dict = Depends(current_user)):
        """Remove an open record without a sale (entered by mistake, or the user does not want to give a price).
        No profit or loss is booked: the report card only counts sales."""
        doc = await load(user["id"])
        pos = find_open(doc, pid)
        doc["positions"] = [p for p in doc["positions"] if p["id"] != pid]
        tx(doc, tur="silme", piyasa=pos["piyasa"], kod=pos["kod"], adet=pos["adet"], para=pos["para"], pozisyon_id=pid)
        await save(doc)
        return {"silindi": pid}

    @r.put("/portfolio/cash")
    async def set_cash(body: CashBody, user: dict = Depends(current_user)):
        para = body.para.upper()
        if para not in ("TL", "USD"):
            raise HTTPException(status_code=400, detail="Para birimi TL ya da USD.")
        amount = _num(body.tutar, "Tutar", positive=False)
        doc = await load(user["id"])
        doc["cash_balance"][para] = amount
        tx(doc, tur="nakit", para=para, tutar=amount)
        await save(doc)
        return doc["cash_balance"]

    @r.get("/portfolio/quotes")
    async def quotes(user: dict = Depends(current_user)):
        """Last closed-bar close for each open position (shared 60 s cache in chart_data)."""
        doc = await load(user["id"])
        out = {}
        for p in doc["positions"]:
            key = f"{p['piyasa']}:{p['kod']}"
            if p["durum"] != "acik" or key in out:
                continue
            try:
                c = await chart_data.chart(p["kod"], "1d", p["piyasa"])
                last = chart_data.last_closed(c.get("candles"), p["piyasa"])
                out[key] = last["c"] if last else None
            except Exception:
                out[key] = None
        return out

    async def create_risk_proposal(uid: str) -> dict:
        doc = await load(uid)
        suggestions, affected = [], []
        for pos in doc["positions"]:
            if pos["durum"] != "acik":
                continue
            try:
                chart = await chart_data.chart(pos["kod"], "1d", pos["piyasa"])
                last = chart_data.last_closed(chart["candles"], pos["piyasa"])  # never today's forming candle
                price = last["c"] if last else None
            except Exception:
                price = None
            old = pos.get("stop")
            row = {"id": pos["id"], "kod": pos["kod"], "piyasa": pos["piyasa"], "para": pos.get("para"),
                   "adet": pos["adet"], "maliyet": pos["maliyet"], "fiyat": price, "eski_stop": old,
                   # money lost if the price fell to the stop from the last close (a stop is not a guaranteed fill)
                   "risk_simdi": round(pos["adet"] * (price - old), 2) if price and old is not None and price > old else None,
                   "onerilen_stop": None, "risk_sonra": None}
            if price:
                proposed = round(max(pos["maliyet"], price * 0.95, old or 0), 6)
                if price > pos["maliyet"] * 1.05 and proposed < price and (old is None or proposed > old):
                    row.update(onerilen_stop=proposed, risk_sonra=round(pos["adet"] * (price - proposed), 2))
                    suggestions.append({"id": pos["id"], "kod": pos["kod"], "piyasa": pos["piyasa"],
                                        "fiyat": price, "eski_stop": old, "onerilen_stop": proposed})
            affected.append(row)
        now = _now()
        proposal = {"id": f"risk_{ObjectId()}", "user_id": uid, "portfolio_rev": doc["rev"],
                    "created_at": now.isoformat(), "expires_at": now + timedelta(minutes=15),
                    "old_target_pct": doc["risk_target_pct"], "new_target_pct": round(doc["risk_target_pct"] / 2, 4),
                    "suggestions": suggestions, "affected": affected, "status": "pending",
                    # what can be undone: the risk target yes; a raised stop no (goalpost rule, stops only move up)
                    "geri_alinabilir": {"risk_hedefi": True, "stoplar": False}}
        await get_db().risk_proposals.insert_one(dict(proposal))
        proposal.pop("_id", None)
        proposal["expires_at"] = proposal["expires_at"].isoformat()
        return proposal

    @r.post("/risk/proposals")
    async def new_risk_proposal(user: dict = Depends(current_user)):
        return await create_risk_proposal(user["id"])

    @r.post("/bot/telegram/risk-proposal")
    async def telegram_risk_proposal(body: BotChatBody, _: bool = Depends(require_bot_key)):
        account = await get_db().users.find_one({"telegram_chat_id": body.chat_id}, {"_id": 1})
        if not account:
            raise HTTPException(status_code=404, detail="Önce Telegram hesabını siteye bağla.")
        return await create_risk_proposal(str(account["_id"]))

    @r.get("/risk/proposals/latest")
    async def latest_risk_proposal(user: dict = Depends(current_user)):
        row = await get_db().risk_proposals.find_one({"user_id": user["id"], "status": "pending",
                                                      "expires_at": {"$gt": _now()}}, {"_id": 0}, sort=[("created_at", -1)])
        if row:
            row["expires_at"] = row["expires_at"].isoformat()
        return row or {}

    @r.post("/risk/proposals/{proposal_id}/apply")
    async def apply_risk_proposal(proposal_id: str, body: ApplyRiskBody, user: dict = Depends(current_user)):
        proposal = await get_db().risk_proposals.find_one({"id": proposal_id, "user_id": user["id"],
                                                            "status": "pending", "expires_at": {"$gt": _now()}})
        if not proposal:
            raise HTTPException(status_code=404, detail="Kriz planı bulunamadı ya da süresi doldu.")
        doc = await load(user["id"])
        if doc["rev"] != proposal["portfolio_rev"]:
            raise HTTPException(status_code=409, detail="Portföy değişti. Yeni kriz planı oluştur.")
        wanted = set(body.position_ids)
        offered = {row["id"]: row for row in proposal["suggestions"]}
        if not wanted.issubset(offered):
            raise HTTPException(status_code=400, detail="Plan dışı stop seçildi.")
        doc["risk_target_pct"] = proposal["new_target_pct"]
        doc["risk_mode"] = "defansif"
        for pos in doc["positions"]:
            if pos["id"] in wanted:
                pos["stop"] = offered[pos["id"]]["onerilen_stop"]
        tx(doc, tur="risk_off", eski_hedef=proposal["old_target_pct"], yeni_hedef=proposal["new_target_pct"],
           stoplar=list(wanted))
        await save(doc)
        await get_db().risk_proposals.update_one({"id": proposal_id}, {"$set": {"status": "applied"}})
        return {"risk_target_pct": doc["risk_target_pct"], "risk_mode": doc["risk_mode"], "updated_stops": list(wanted)}

    @r.post("/risk/restore-target")
    async def restore_risk_target(user: dict = Depends(current_user)):
        doc = await load(user["id"])
        if doc["risk_mode"] != "defansif":
            raise HTTPException(status_code=409, detail="Defansif hedef açık değil.")
        latest = next((x for x in reversed(doc["transactions"]) if x.get("tur") == "risk_off"), None)
        if not latest:
            raise HTTPException(status_code=409, detail="Önceki risk hedefi bulunamadı.")
        doc["risk_target_pct"] = latest["eski_hedef"]
        doc["risk_mode"] = "normal"
        tx(doc, tur="risk_target_restore", yeni_hedef=doc["risk_target_pct"])
        await save(doc)
        return {"risk_target_pct": doc["risk_target_pct"], "risk_mode": doc["risk_mode"]}

    # ---------------- Users' own AI API keys ----------------
    @r.get("/ai-keys")
    async def ai_keys(user: dict = Depends(current_user)):
        """Which keys the user saved: masked, never the key itself."""
        u = await get_db().users.find_one({"_id": ObjectId(user["id"])}, {"ai_keys": 1})
        saved = (u or {}).get("ai_keys") or {}
        return {"sifreleme": bool(KEY_ENCRYPTION_KEY),
                "anahtarlar": {p: ({"maske": mask(saved[p]["son4"]), "eklendi": saved[p].get("eklendi")} if p in saved else None)
                               for p in PROVIDERS},
                "etiketler": {p: v[0] for p, v in PROVIDERS.items()}}

    @r.put("/ai-keys")
    async def save_ai_key(body: AiKeyBody, user: dict = Depends(current_user)):
        prov, key = body.saglayici.lower(), body.anahtar.strip()
        if prov not in PROVIDERS:
            raise HTTPException(status_code=400, detail="Sağlayıcı deepseek ya da nvidia olmalı.")
        if not 20 <= len(key) <= 300 or any(c.isspace() for c in key):
            raise HTTPException(status_code=400, detail="Anahtar biçimi geçersiz.")
        f = _fernet()
        label, method, url, body_json = PROVIDERS[prov]
        try:  # the provider says whether the key works; the key is sent only to that provider
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.request(method, url, headers={"Authorization": f"Bearer {key}"}, json=body_json)
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail=f"{label} şu an doğrulanamadı, biraz sonra tekrar dene.")
        if resp.status_code in (401, 403):
            raise HTTPException(status_code=400, detail=f"{label} bu anahtarı kabul etmedi.")
        await get_db().users.update_one({"_id": ObjectId(user["id"])}, {"$set": {f"ai_keys.{prov}": {
            "enc": f.encrypt(key.encode()).decode(), "son4": key[-4:], "eklendi": _now().isoformat()}}})
        return {"ok": True, "maske": mask(key[-4:])}

    @r.delete("/ai-keys/{prov}")
    async def delete_ai_key(prov: str, user: dict = Depends(current_user)):
        if prov not in PROVIDERS:
            raise HTTPException(status_code=400, detail="Bilinmeyen sağlayıcı.")
        await get_db().users.update_one({"_id": ObjectId(user["id"])}, {"$unset": {f"ai_keys.{prov}": ""}})
        return {"ok": True}

    @r.get("/bot/user-keys/{uid}")
    async def bot_user_keys(uid: str, _: bool = Depends(require_bot_key)):
        """For the bot only, and only while that user has an analysis waiting: the decrypted keys, in memory."""
        since = (_now() - timedelta(hours=2)).isoformat()
        waiting = await get_db().commands.find_one({"user_id": uid, "type": "analysis.request", "status": "pending",
                                                    "own_keys": True, "created_at": {"$gte": since}})
        if not waiting:
            raise HTTPException(status_code=404, detail="Bekleyen analiz yok.")
        u = await get_db().users.find_one({"_id": ObjectId(uid)}, {"ai_keys": 1})
        f = _fernet()
        out = {}
        for prov, v in ((u or {}).get("ai_keys") or {}).items():
            try:
                out[prov] = f.decrypt(v["enc"].encode()).decode()
            except Exception:
                continue  # rotated encryption key: the user has to enter it again
        if not out:
            raise HTTPException(status_code=404, detail="Anahtar yok.")
        return out

    # ---------------- Account: export and delete (KVKK / GDPR) ----------------
    async def my_data(uid: str) -> dict:
        user = await get_db().users.find_one({"_id": ObjectId(uid)}, {"password_hash": 0, "ai_keys": 0})
        return {
            "hesap": {k: (str(v) if k == "_id" else v) for k, v in (user or {}).items()},
            "portfoy": await get_db().portfolios.find_one({"user_id": uid}, {"_id": 0}),
            "analizler": await get_db().analyses.find({"user_id": uid}, {"_id": 0}).to_list(5000),
            "stratejiler": await get_db().strategies.find({"user_id": uid}, {"_id": 0}).to_list(5000),
            "kriz_planlari": await get_db().risk_proposals.find({"user_id": uid}, {"_id": 0}).to_list(5000),
            "istekler": await get_db().commands.find({"user_id": uid}, {"_id": 0, "telegram_chat_id": 0}).to_list(5000),
            "alarmlar": await get_db().user_alerts.find({"user_id": uid}, {"_id": 0}).to_list(5000),
            "uyarilar": await get_db().user_alert_events.find({"user_id": uid}, {"_id": 0, "chat_id": 0}).to_list(5000),
        }

    @r.get("/account/export")
    async def export(user: dict = Depends(current_user)):
        """Everything Kapanış stores about the signed-in user, as JSON."""
        return {"olusturma": _now().isoformat(), **await my_data(user["id"])}

    @r.delete("/account")
    async def delete_account(user: dict = Depends(current_user)):
        """Delete the user's portfolio, analyses, requests, link codes and account (and the Clerk account)."""
        if user.get("role") in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="Sistem sahibinin hesabı buradan silinemez (bot bu hesaba bağlı).")
        uid = user["id"]
        if user.get("clerk_id"):
            import identity
            if not await identity.delete_clerk_user(user["clerk_id"]):
                raise HTTPException(status_code=502, detail="Giriş hesabı silinemedi, biraz sonra tekrar dene.")
        d = get_db()
        await d.portfolios.delete_many({"user_id": uid})
        await d.analyses.delete_many({"user_id": uid})
        await d.strategies.delete_many({"user_id": uid})
        await d.risk_proposals.delete_many({"user_id": uid})
        await d.commands.delete_many({"user_id": uid})
        await d.telegram_links.delete_many({"user_id": uid})
        await d.user_alerts.delete_many({"user_id": uid})
        await d.user_alert_events.delete_many({"user_id": uid})
        await d.users.delete_one({"_id": ObjectId(uid)})
        return {"ok": True}

    if require_owner is not None:
        @r.get("/admin/users")
        async def admin_users(_: dict = Depends(require_owner)):
            """Owner overview: who signed up and how much they use (no portfolio contents)."""
            d = get_db()
            since = (_now() - timedelta(days=1)).isoformat()
            out = []
            async for u in d.users.find({}, {"password_hash": 0}).sort("created_at", -1).limit(1000):
                own = sorted((u.get("ai_keys") or {}).keys())
                uid = str(u["_id"])
                pf = await d.portfolios.find_one({"user_id": uid}, {"positions": 1})
                out.append({
                    "email": u.get("email"), "rol": u.get("role"), "kayit": u.get("created_at"),
                    "giris": "Clerk" if u.get("clerk_id") else "yerel", "telegram": bool(u.get("telegram_chat_id")),
                    "kendi_anahtari": own,
                    "acik_pozisyon": sum(1 for p in (pf or {}).get("positions", []) if p.get("durum") == "acik"),
                    "analiz_24s": await d.commands.count_documents({"user_id": uid, "type": "analysis.request", "created_at": {"$gte": since}}),
                    "analiz_toplam": await d.analyses.count_documents({"user_id": uid}),
                })
            total = await d.commands.count_documents({"role": "user", "type": "analysis.request", "created_at": {"$gte": since}})
            return {"kullanicilar": out, "kullanici_analiz_24s": total}

    # ---------------- Telegram link ----------------
    @r.get("/telegram/status")
    async def tg_status(user: dict = Depends(current_user)):
        return {"bagli": bool(user.get("telegram_chat_id")), "kullanici_adi": user.get("telegram_username")}

    @r.post("/telegram/link-code")
    async def tg_code(user: dict = Depends(current_user)):
        recent = await get_db().telegram_links.count_documents({"user_id": user["id"], "created_at": {"$gte": _now() - timedelta(hours=1)}})
        if recent >= 5:
            raise HTTPException(status_code=429, detail="Çok fazla kod istendi; bir saat sonra tekrar dene.")
        code = "KP-" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
        await get_db().telegram_links.insert_one({"code_hash": hash_code(code), "user_id": user["id"], "used": False,
                                            "created_at": _now(), "expires_at": _now() + timedelta(minutes=LINK_MINUTES)})
        return {"kod": code, "dakika": LINK_MINUTES}

    @r.delete("/telegram/link")
    async def tg_unlink(user: dict = Depends(current_user)):
        await get_db().users.update_one({"_id": ObjectId(user["id"])}, {"$unset": {"telegram_chat_id": "", "telegram_username": ""}})
        return {"ok": True}

    @r.post("/bot/telegram/link")
    async def tg_link(body: LinkBody, _: bool = Depends(require_bot_key)):
        """The bot received /bagla KOD from a chat: bind that chat to the code's user (one use, 10 minutes)."""
        now = _now()
        link = await get_db().telegram_links.find_one_and_update(
            {"code_hash": hash_code(body.code), "used": False, "expires_at": {"$gt": now}},
            {"$set": {"used": True, "used_at": now}})
        if not link:
            raise HTTPException(status_code=404, detail="Kod geçersiz ya da süresi dolmuş.")
        # one chat belongs to one account
        await get_db().users.update_many({"telegram_chat_id": body.chat_id, "_id": {"$ne": ObjectId(link["user_id"])}},
                                   {"$unset": {"telegram_chat_id": "", "telegram_username": ""}})
        await get_db().users.update_one({"_id": ObjectId(link["user_id"])},
                                  {"$set": {"telegram_chat_id": body.chat_id, "telegram_username": body.username}})
        user = await get_db().users.find_one({"_id": ObjectId(link["user_id"])}, {"email": 1})
        return {"ok": True, "email": (user or {}).get("email")}

    return r

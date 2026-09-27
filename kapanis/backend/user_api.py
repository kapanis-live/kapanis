"""Per-user data: each signed-in person's own real portfolio and their Telegram link.

Every query filters on the verified user id taken from the session; a user id is never read from the
request body or URL. Kapanış records what the user tells it; it never connects to a broker and never trades.

portfolios (one document per user)
  user_id, rev, cash_balance {TL, USD},
  positions   [{id, piyasa, kod, adet, maliyet, stop, hedef, acilis, durum, kapanis_fiyat, kapanis}]
  transactions[{id, zaman, tur: alis|satis|nakit, piyasa, kod, adet, fiyat, tutar, para, pozisyon_id, kar}]

telegram_links: {code_hash, user_id, expires_at, used} - one-time codes, 10 minutes, stored hashed.
"""
import hashlib
import math
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import chart_data

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


class StopBody(BaseModel):
    stop: float


class SellBody(BaseModel):
    fiyat: float
    adet: Optional[float] = None


class CashBody(BaseModel):
    para: str
    tutar: float


class LinkBody(BaseModel):
    code: str
    chat_id: int
    username: Optional[str] = None


async def ensure_indexes(db):
    await db.portfolios.create_index("user_id", unique=True)
    await db.telegram_links.create_index("code_hash", unique=True)
    await db.telegram_links.create_index("expires_at", expireAfterSeconds=3600)


def build_router(get_db, current_user, require_bot_key) -> APIRouter:
    """get_db() returns the current database handle (looked up per request, so tests can swap it)."""
    r = APIRouter(prefix="/api")

    async def load(uid: str) -> dict:
        doc = await get_db().portfolios.find_one({"user_id": uid}, {"_id": 0})
        if doc is None:
            doc = {"user_id": uid, "rev": 0, "cash_balance": {"TL": 0.0, "USD": 0.0}, "positions": [], "transactions": []}
            await get_db().portfolios.update_one({"user_id": uid}, {"$setOnInsert": doc}, upsert=True)
            doc = await get_db().portfolios.find_one({"user_id": uid}, {"_id": 0})
        return doc

    async def save(doc: dict):
        """Optimistic write: fails instead of overwriting a change made in another tab meanwhile."""
        rev = doc["rev"]
        res = await get_db().portfolios.update_one(
            {"user_id": doc["user_id"], "rev": rev},
            {"$set": {"cash_balance": doc["cash_balance"], "positions": doc["positions"],
                      "transactions": doc["transactions"][-2000:], "rev": rev + 1}})
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
               "hedef": hedef, "para": MARKETS[mkt], "acilis": _now().isoformat(), "durum": "acik"}
        doc["positions"].append(pos)
        tx(doc, tur="alis", piyasa=mkt, kod=kod, adet=adet, fiyat=maliyet, tutar=round(adet * maliyet, 2),
           para=MARKETS[mkt], pozisyon_id=pos["id"])
        await save(doc)
        return pos

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
                out[key] = c["candles"][-1]["c"] if c.get("candles") else None
            except Exception:
                out[key] = None
        return out

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

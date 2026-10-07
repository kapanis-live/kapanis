"""App notifications (Web Push): the same messages the bot sends to Telegram also reach the installed app / browser.

GET    /api/push/key          the public VAPID key the browser subscribes with
GET    /api/push/status       how many of this user's devices are subscribed
POST   /api/push/subscribe    {endpoint, keys: {p256dh, auth}} from PushManager.subscribe()
POST   /api/push/unsubscribe  {endpoint}
POST   /api/push/test         a test notification to this user's devices
POST   /api/bot/push          the bot: {chat_id | sahip, baslik, metin, url} -> that account's devices   (bot key)

No extra service and no third-party SDK: the message is encrypted for the browser here (RFC 8291, aes128gcm) and
signed with this server's own VAPID key (RFC 8292), then posted to the push endpoint the browser gave us.
The VAPID key pair is created on first use and kept in the database (app_secrets), never in the repository.
A subscription the push service reports as gone (404 / 410) is deleted.
"""
import asyncio
import base64
import json
import logging
import os
import struct
import time
from urllib.parse import urlparse

import httpx
import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

log = logging.getLogger(__name__)

MAX_DEVICES = 8
TTL_SECONDS = 6 * 3600        # a notification older than this is not worth delivering
CONTACT = os.environ.get("PUSH_CONTACT", "mailto:destek@kapanis.live")
_keys: dict | None = None


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _point(key) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def new_keys() -> dict:
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    return {"id": "vapid", "private_pem": pem, "public": b64(_point(key))}


async def keys(db) -> dict:
    global _keys
    if _keys is None:
        doc = await db.app_secrets.find_one({"id": "vapid"}, {"_id": 0})
        if not doc:
            doc = new_keys()
            await db.app_secrets.update_one({"id": "vapid"}, {"$setOnInsert": doc}, upsert=True)
            doc = await db.app_secrets.find_one({"id": "vapid"}, {"_id": 0})     # another worker may have won the race
        _keys = doc
    return _keys


def encrypt(payload: bytes, p256dh: str, auth: str, sender=None, salt: bytes | None = None) -> bytes:
    """RFC 8291: one aes128gcm record for the browser that owns (p256dh, auth)."""
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(p256dh))
    sender = sender or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    sender_pub = _point(sender)
    shared = sender.exchange(ec.ECDH(), receiver)
    ikm = HKDF(hashes.SHA256(), 32, unb64(auth), b"WebPush: info\x00" + unb64(p256dh) + sender_pub).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)          # 0x02: the last (only) record
    return salt + struct.pack(">I", 4096) + bytes([len(sender_pub)]) + sender_pub + body


def vapid_header(endpoint: str, k: dict, now: float | None = None) -> str:
    u = urlparse(endpoint)
    token = jwt.encode({"aud": f"{u.scheme}://{u.netloc}", "exp": int((now or time.time()) + 12 * 3600), "sub": CONTACT},
                       k["private_pem"], algorithm="ES256")
    return f"vapid t={token}, k={k['public']}"


async def send(client: httpx.AsyncClient, sub: dict, payload: dict, k: dict) -> int:
    """Post one notification; returns the push service's status code (0 = network error)."""
    try:
        body = encrypt(json.dumps(payload, ensure_ascii=False).encode(), sub["keys"]["p256dh"], sub["keys"]["auth"])
        r = await client.post(sub["endpoint"], content=body, timeout=15, headers={
            "Authorization": vapid_header(sub["endpoint"], k), "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream", "TTL": str(TTL_SECONDS), "Urgency": "normal"})
        return r.status_code
    except Exception as e:
        log.warning("Push to %s failed: %s", urlparse(sub.get("endpoint", "")).netloc, str(e)[:120])
        return 0


async def notify(db, user_id: str, title: str, text: str, url: str = "/app") -> dict:
    """Send to every device of one account. Dead subscriptions are removed."""
    subs = await db.push_subscriptions.find({"user_id": user_id}, {"_id": 0}).to_list(MAX_DEVICES)
    if not subs:
        return {"cihaz": 0, "gitti": 0}
    k = await keys(db)
    payload = {"baslik": title[:80], "metin": text[:400], "url": url}
    async with httpx.AsyncClient() as client:
        codes = await asyncio.gather(*[send(client, s, payload, k) for s in subs])
    gone = [s["endpoint"] for s, c in zip(subs, codes) if c in (404, 410)]
    if gone:
        await db.push_subscriptions.delete_many({"endpoint": {"$in": gone}})
    return {"cihaz": len(subs), "gitti": sum(200 <= c < 300 for c in codes), "silinen": len(gone)}


class Keys(BaseModel):
    p256dh: str
    auth: str


class Subscription(BaseModel):
    endpoint: str
    keys: Keys


class Endpoint(BaseModel):
    endpoint: str


class BotPush(BaseModel):
    chat_id: int | None = None
    sahip: bool = False
    baslik: str = "Kapanış"
    metin: str
    url: str = "/app"


def build_router(get_db, current_user, require_bot_key, is_owner) -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.get("/push/key")
    async def public_key(_: dict = Depends(current_user)):
        return {"key": (await keys(get_db()))["public"]}

    @r.get("/push/status")
    async def status(user: dict = Depends(current_user)):
        return {"cihaz": await get_db().push_subscriptions.count_documents({"user_id": user["id"]})}

    @r.post("/push/subscribe")
    async def subscribe(body: Subscription, user: dict = Depends(current_user)):
        host = urlparse(body.endpoint)
        if host.scheme != "https" or not host.netloc or len(body.endpoint) > 1000:
            raise HTTPException(status_code=400, detail="Geçersiz bildirim adresi.")
        try:
            if len(unb64(body.keys.p256dh)) != 65 or len(unb64(body.keys.auth)) != 16:
                raise ValueError
        except Exception:
            raise HTTPException(status_code=400, detail="Geçersiz bildirim anahtarı.")
        db = get_db()
        mine = await db.push_subscriptions.count_documents({"user_id": user["id"], "endpoint": {"$ne": body.endpoint}})
        if mine >= MAX_DEVICES:
            raise HTTPException(status_code=400, detail=f"En fazla {MAX_DEVICES} cihaz. Birini kapatıp tekrar dene.")
        await db.push_subscriptions.update_one({"endpoint": body.endpoint}, {"$set": {
            "endpoint": body.endpoint, "keys": body.keys.model_dump(), "user_id": user["id"], "zaman": time.time()}}, upsert=True)
        return {"ok": True, "cihaz": mine + 1}

    @r.post("/push/unsubscribe")
    async def unsubscribe(body: Endpoint, user: dict = Depends(current_user)):
        res = await get_db().push_subscriptions.delete_one({"endpoint": body.endpoint, "user_id": user["id"]})
        return {"ok": True, "silinen": res.deleted_count}

    @r.post("/push/test")
    async def test(user: dict = Depends(current_user)):
        out = await notify(get_db(), user["id"], "Kapanış", "Test bildirimi: uygulama bildirimleri çalışıyor.", "/app/hesap")
        if not out["cihaz"]:
            raise HTTPException(status_code=400, detail="Bu hesapta bildirim açık cihaz yok.")
        return out

    @r.post("/bot/push")
    async def from_bot(body: BotPush, _: bool = Depends(require_bot_key)):
        db = get_db()
        user = None
        if body.chat_id is not None:
            user = await db.users.find_one({"telegram_chat_id": body.chat_id}, {"_id": 0, "id": 1})
        if user is None and body.sahip:      # the owner's chat is not always linked to the owner's account
            async for u in db.users.find({}, {"_id": 0}):
                if is_owner(u):
                    user = u
                    break
        if not user:
            return {"cihaz": 0, "gitti": 0}
        return await notify(db, user["id"], body.baslik, body.metin, body.url)

    return r


async def ensure_indexes(db):
    await db.push_subscriptions.create_index("endpoint", unique=True)
    await db.push_subscriptions.create_index("user_id")

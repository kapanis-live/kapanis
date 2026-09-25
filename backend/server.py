from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import logging
import jwt
import bcrypt
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, APIRouter, Request, Response, HTTPException, Depends, Header
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr
from typing import Optional, Any
from bson import ObjectId

import mock_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"
ACCESS_MINUTES = 60
REFRESH_DAYS = 30
BOT_API_KEY = os.environ["BOT_API_KEY"]
MAX_FAILED = 5
LOCK_MINUTES = 15

app = FastAPI()
api = APIRouter(prefix="/api")


# ---------------- Auth helpers ----------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email, "type": "access",
               "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_MINUTES)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {"sub": user_id, "type": "refresh",
               "exp": datetime.now(timezone.utc) + timedelta(days=REFRESH_DAYS)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def set_auth_cookies(response: Response, access: str, refresh: str):
    response.set_cookie("access_token", access, httponly=True, secure=True, samesite="none",
                        max_age=ACCESS_MINUTES * 60, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=True, samesite="none",
                        max_age=REFRESH_DAYS * 24 * 3600, path="/")


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Oturum bulunamadı. Lütfen giriş yapın.")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Geçersiz oturum.")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı.")
        user["id"] = str(user["_id"])
        user.pop("_id", None)
        user.pop("password_hash", None)
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Geçersiz oturum.")


async def require_bot_key(x_bot_key: Optional[str] = Header(None)):
    if x_bot_key != BOT_API_KEY:
        raise HTTPException(status_code=401, detail="Geçersiz bot anahtarı.")
    return True


class LoginBody(BaseModel):
    email: EmailStr
    password: str


# ---------------- Auth endpoints ----------------
@api.post("/auth/login")
async def login(body: LoginBody, request: Request, response: Response):
    email = body.email.lower()
    # Kubernetes ingress arkasında gerçek IP X-Forwarded-For'un ilk kaydındadır.
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")
    ident = f"{ip}:{email}"
    attempt = await db.login_attempts.find_one({"identifier": ident})
    now = datetime.now(timezone.utc)
    if attempt and attempt.get("locked_until"):
        locked_until = datetime.fromisoformat(attempt["locked_until"])
        if locked_until > now:
            raise HTTPException(status_code=429, detail="Çok fazla hatalı deneme. 15 dakika sonra tekrar deneyin.")

    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user["password_hash"]):
        count = (attempt["count"] + 1) if attempt else 1
        update = {"identifier": ident, "count": count}
        if count >= MAX_FAILED:
            update["locked_until"] = (now + timedelta(minutes=LOCK_MINUTES)).isoformat()
        await db.login_attempts.update_one({"identifier": ident}, {"$set": update}, upsert=True)
        raise HTTPException(status_code=401, detail="E-posta veya şifre hatalı.")

    await db.login_attempts.delete_one({"identifier": ident})
    uid = str(user["_id"])
    access = create_access_token(uid, email)
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    return {"id": uid, "email": email, "name": user.get("name", "Admin"), "role": user.get("role", "admin"), "access_token": access}


@api.post("/auth/refresh")
async def refresh_token(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="Oturum bulunamadı.")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Geçersiz oturum.")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı.")
        uid = str(user["_id"])
        access = create_access_token(uid, user["email"])
        new_refresh = create_refresh_token(uid)
        set_auth_cookies(response, access, new_refresh)
        return {"ok": True}
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Geçersiz oturum.")


@api.post("/auth/logout")
async def logout(response: Response, user: dict = Depends(get_current_user)):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"ok": True}


@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return user


# ---------------- Data helpers ----------------
async def _list(collection: str):
    docs = await db[collection].find({}, {"_id": 0}).to_list(1000)
    return docs


async def _one(collection: str):
    doc = await db[collection].find_one({}, {"_id": 0})
    return doc


# ---------------- Panel data endpoints (JWT) ----------------
@api.get("/overview")
async def get_overview(user: dict = Depends(get_current_user)):
    return await _one("overview")


@api.get("/alerts")
async def get_alerts(user: dict = Depends(get_current_user)):
    return await _list("alerts")


@api.get("/positions")
async def get_positions(user: dict = Depends(get_current_user)):
    return await _list("positions")


@api.get("/decisions")
async def get_decisions(user: dict = Depends(get_current_user)):
    return await _list("decisions")


@api.get("/signals")
async def get_signals(user: dict = Depends(get_current_user)):
    return await _list("signals")


@api.get("/signals/{signal_id}")
async def get_signal(signal_id: str, user: dict = Depends(get_current_user)):
    doc = await db.signals.find_one({"id": signal_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Sinyal bulunamadı.")
    return doc


@api.get("/macro")
async def get_macro(user: dict = Depends(get_current_user)):
    return await _one("macro")


@api.get("/derivatives")
async def get_derivatives(user: dict = Depends(get_current_user)):
    return await _list("derivatives")


@api.get("/usage")
async def get_usage(user: dict = Depends(get_current_user)):
    return await _one("usage")


@api.get("/report")
async def get_report(user: dict = Depends(get_current_user)):
    return await _one("report")


@api.get("/backtest")
async def get_backtest(user: dict = Depends(get_current_user)):
    return await _one("backtest")


@api.get("/settings")
async def get_settings(user: dict = Depends(get_current_user)):
    return await _one("settings")


@api.get("/candles/{symbol}")
async def get_candles(symbol: str, user: dict = Depends(get_current_user)):
    doc = await db.candles.find_one({"id": symbol}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Grafik verisi bulunamadı.")
    return doc


# ---------------- Command creation (panel actions -> queued) ----------------
async def _queue_command(cmd_type: str, payload: dict) -> dict:
    cmd = {
        "id": f"cmd_{ObjectId()}",
        "type": cmd_type,
        "payload": payload,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.commands.insert_one(dict(cmd))
    cmd.pop("_id", None)
    return cmd


class AlertBody(BaseModel):
    symbol: str
    side: str
    entry: float
    stop: float
    target: float
    note: Optional[str] = ""


@api.post("/alerts")
async def create_alert(body: AlertBody, user: dict = Depends(get_current_user)):
    cmd = await _queue_command("alert.create", body.model_dump())
    return {"queued": True, "command": cmd}


@api.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str, user: dict = Depends(get_current_user)):
    cmd = await _queue_command("alert.delete", {"id": alert_id})
    return {"queued": True, "command": cmd}


class StopBody(BaseModel):
    stop: float


@api.patch("/positions/{position_id}/stop")
async def update_stop(position_id: str, body: StopBody, user: dict = Depends(get_current_user)):
    pos = await db.positions.find_one({"id": position_id}, {"_id": 0})
    if not pos:
        raise HTTPException(status_code=404, detail="Pozisyon bulunamadı.")
    if pos["status"] == "open":
        # Goalpost kuralı: açık pozisyonda stop, riski artıracak yönde çekilemez.
        if pos["side"] == "long" and body.stop < pos["stop"]:
            raise HTTPException(status_code=409, detail="Goalpost kuralı: açık long pozisyonda stop aşağı çekilemez.")
        if pos["side"] == "short" and body.stop > pos["stop"]:
            raise HTTPException(status_code=409, detail="Goalpost kuralı: açık short pozisyonda stop yukarı çekilemez.")
    cmd = await _queue_command("position.stop", {"id": position_id, "stop": body.stop})
    return {"queued": True, "command": cmd}


@api.post("/positions/{position_id}/close")
async def close_position(position_id: str, user: dict = Depends(get_current_user)):
    cmd = await _queue_command("position.close", {"id": position_id})
    return {"queued": True, "command": cmd}


class DecisionBody(BaseModel):
    verdict: str  # "Aldım" veya "Pas"


@api.post("/decisions/{decision_id}/action")
async def decision_action(decision_id: str, body: DecisionBody, user: dict = Depends(get_current_user)):
    if body.verdict not in ("Aldım", "Pas"):
        raise HTTPException(status_code=400, detail="Geçersiz karar.")
    cmd = await _queue_command("decision.action", {"id": decision_id, "verdict": body.verdict})
    return {"queued": True, "command": cmd}


@api.get("/commands")
async def list_commands(user: dict = Depends(get_current_user)):
    return await db.commands.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)


# ---------------- Bot endpoints (X-Bot-Key) ----------------
INGEST_COLLECTIONS = {"alerts", "positions", "decisions", "macro", "derivatives", "usage", "candles",
                      "signals", "report", "backtest", "overview", "settings"}


@api.post("/ingest/{collection}")
async def ingest(collection: str, request: Request, _: bool = Depends(require_bot_key)):
    if collection not in INGEST_COLLECTIONS:
        raise HTTPException(status_code=400, detail="Bilinmeyen koleksiyon.")
    body = await request.json()
    items = body if isinstance(body, list) else [body]
    upserted = 0
    for item in items:
        if "id" not in item:
            raise HTTPException(status_code=400, detail="Her kayıtta 'id' alanı gerekli.")
        await db[collection].update_one({"id": item["id"]}, {"$set": item}, upsert=True)
        upserted += 1
    return {"ok": True, "collection": collection, "upserted": upserted}


@api.get("/commands/pending")
async def pending_commands(_: bool = Depends(require_bot_key)):
    return await db.commands.find({"status": "pending"}, {"_id": 0}).sort("created_at", 1).to_list(500)


@api.post("/commands/{command_id}/done")
async def command_done(command_id: str, _: bool = Depends(require_bot_key)):
    res = await db.commands.update_one({"id": command_id}, {"$set": {"status": "done", "done_at": datetime.now(timezone.utc).isoformat()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Komut bulunamadı.")
    return {"ok": True}


@api.get("/")
async def root():
    return {"message": "Kapanış API", "status": "ok"}


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------- Startup: indexes + seed ----------------
async def seed_admin():
    email = os.environ["ADMIN_EMAIL"].lower()
    password = os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": email})
    if existing is None:
        await db.users.insert_one({
            "email": email, "password_hash": hash_password(password),
            "name": "Admin", "role": "admin", "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("Admin seeded: %s", email)
    elif not verify_password(password, existing["password_hash"]):
        await db.users.update_one({"email": email}, {"$set": {"password_hash": hash_password(password)}})
        logger.info("Admin password updated")


async def seed_mock():
    for collection, items in mock_data.SEED.items():
        for item in items:
            await db[collection].update_one({"id": item["id"]}, {"$setOnInsert": item}, upsert=True)


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.login_attempts.create_index("identifier")
    await seed_admin()
    await seed_mock()
    logger.info("Startup complete")


@app.on_event("shutdown")
async def shutdown():
    client.close()

from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import asyncio
import os
import hmac
import logging
import math
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
import chart_data
import identity
import limits
import insights
import risk_budget
import user_alerts
import user_api
import advisor_api
from starlette.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# The bot and the panel share one MongoDB (Atlas in the cloud): STATE_MONGO_URL works for both.
mongo_url = os.environ.get("MONGO_URL") or os.environ["STATE_MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get("DB_NAME") or os.environ.get("STATE_DB_NAME") or "kapanis"]

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"
ACCESS_MINUTES = 60
REFRESH_DAYS = 30
BOT_API_KEY = os.environ["BOT_API_KEY"]
MAX_FAILED = 5
LOCK_MINUTES = 15

app = FastAPI()


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """Every /api request counts against the client IP's per-minute budget (the stream counts once when opened)."""
    if request.url.path.startswith("/api/") and not limits.hit(f"ip:{limits.client_ip(request)}", limits.IP_PER_MINUTE):
        return JSONResponse({"detail": "Çok sık istek gönderildi; bir dakika sonra tekrar dene."}, status_code=429)
    return await call_next(request)
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


def _public_user(user: dict) -> dict:
    user = dict(user)
    user["id"] = str(user.pop("_id"))
    user.pop("password_hash", None)
    user["kendi_anahtari"] = sorted((user.pop("ai_keys", None) or {}).keys())  # never the encrypted keys
    return user


async def get_current_user(request: Request) -> dict:
    bearer = request.headers.get("Authorization", "")
    bearer = bearer[7:] if bearer.startswith("Bearer ") else None
    # Clerk session tokens are RS256 and arrive as a Bearer header; the legacy cookie token is HS256.
    if bearer and identity.clerk_enabled():
        try:
            if jwt.get_unverified_header(bearer).get("alg") == "RS256":
                return _public_user(await identity.user_from_clerk(db, bearer))
        except identity.AuthError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Geçersiz oturum.")
    if not identity.legacy_enabled():
        raise HTTPException(status_code=401, detail="Oturum bulunamadı. Lütfen giriş yapın.")
    token = request.cookies.get("access_token") or bearer
    if not token:
        raise HTTPException(status_code=401, detail="Oturum bulunamadı. Lütfen giriş yapın.")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Geçersiz oturum.")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı.")
        return _public_user(user)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Oturum süresi doldu.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Geçersiz oturum.")


async def require_bot_key(x_bot_key: Optional[str] = Header(None), x_kapanis_public: Optional[str] = Header(None)):
    # The site's reverse proxy marks every request that came from the internet (X-Kapanis-Public).
    # Bot endpoints are for the worker on the internal network only: even a leaked key does not work from outside.
    if x_kapanis_public:
        raise HTTPException(status_code=404, detail="Not found")
    if not x_bot_key or not hmac.compare_digest(x_bot_key, BOT_API_KEY):
        raise HTTPException(status_code=401, detail="Geçersiz bot anahtarı.")
    return True


async def require_owner(user: dict = Depends(get_current_user)) -> dict:
    """The bot's own portfolio, signals, alarms and settings belong to its owner only."""
    if not identity.is_owner(user):
        raise HTTPException(status_code=403, detail="Bu bölüm yalnız sistem sahibine açık.")
    return user


class LoginBody(BaseModel):
    email: EmailStr
    password: str


# ---------------- Auth endpoints ----------------
@api.get("/auth/config")
async def auth_config():
    """Public: which sign-in the panel should show. The Clerk publishable key is public by design."""
    return {"mode": identity.AUTH_MODE, "clerk": identity.clerk_enabled(),
            "clerk_publishable_key": identity.PUBLISHABLE_KEY if identity.clerk_enabled() else "",
            "legacy": identity.legacy_enabled(),
            "telegram_bot": os.environ.get("TELEGRAM_BOT_USERNAME", "").lstrip("@"),
            # shown on the privacy page as the data controller's contact; empty = the contact page
            "iletisim": os.environ.get("CONTACT_EMAIL", "")}


@api.post("/auth/login")
async def login(body: LoginBody, request: Request, response: Response):
    if not identity.legacy_enabled():
        raise HTTPException(status_code=404, detail="Bu sitede giriş Google ya da e-posta kodu ile yapılır.")
    email = body.email.lower()
    # The client can write X-Forwarded-For itself, so only the entry our own proxy appended
    # (the right-most one) is trusted, and only when TRUST_PROXY=1. Lockout is per e-mail too,
    # so rotating IPs doesn't bypass it.
    ip = request.client.host if request.client else "unknown"
    if os.environ.get("TRUST_PROXY") == "1":
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            ip = fwd.split(",")[-1].strip()
    ident = f"{ip}:{email}"
    account = await db.login_attempts.find_one({"identifier": f"*:{email}"})
    if account and account.get("locked_until") and datetime.fromisoformat(account["locked_until"]) > datetime.now(timezone.utc):
        raise HTTPException(status_code=429, detail="Çok fazla hatalı deneme. 15 dakika sonra tekrar deneyin.")
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
        acc_count = (account["count"] + 1) if account else 1
        acc_update = {"identifier": f"*:{email}", "count": acc_count}
        if acc_count >= MAX_FAILED * 2:
            acc_update["locked_until"] = (now + timedelta(minutes=LOCK_MINUTES)).isoformat()
        await db.login_attempts.update_one({"identifier": f"*:{email}"}, {"$set": acc_update}, upsert=True)
        raise HTTPException(status_code=401, detail="E-posta veya şifre hatalı.")

    await db.login_attempts.delete_many({"identifier": {"$in": [ident, f"*:{email}"]}})
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
async def get_overview(user: dict = Depends(require_owner)):
    return await _one("overview")


@api.get("/extras")
async def get_extras(user: dict = Depends(require_owner)):
    """Portfolio-level features from the bot: benchmark, shadow portfolio, discipline, journal, savings plans."""
    return await _one("extras") or {"id": "extras", "guncelleme": None}


@api.get("/alerts")
async def get_alerts(user: dict = Depends(require_owner)):
    return await _list("alerts")


@api.get("/positions")
async def get_positions(user: dict = Depends(require_owner)):
    return await _list("positions")


@api.get("/decisions")
async def get_decisions(user: dict = Depends(require_owner)):
    return await _list("decisions")


@api.get("/signals")
async def get_signals(user: dict = Depends(require_owner)):
    return await _list("signals")


@api.get("/signals/{signal_id}")
async def get_signal(signal_id: str, user: dict = Depends(require_owner)):
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
async def get_usage(user: dict = Depends(require_owner)):
    return await _one("usage")


@api.get("/report")
async def get_report(user: dict = Depends(require_owner)):
    return await _one("report")


@api.get("/backtest")
async def get_backtest(user: dict = Depends(require_owner)):
    return await _one("backtest")


@api.get("/settings")
async def get_settings(user: dict = Depends(require_owner)):
    return await _one("settings")


@api.get("/candles/{symbol}")
async def get_candles(symbol: str, user: dict = Depends(get_current_user)):
    doc = await db.candles.find_one({"id": symbol}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Grafik verisi bulunamadı.")
    return doc


@api.get("/chart/{symbol}")
async def get_chart(symbol: str, tf: str = "1d", market: Optional[str] = None, user: dict = Depends(get_current_user)):
    """Candles + SMA20/50/200, RSI, volume MA and VWAP for any coin, BIST or US ticker."""
    limits.check_user(user["id"], "chart", limits.CHART_PER_MINUTE)  # each new symbol is an outbound request
    try:
        return await chart_data.chart(symbol, tf, market)
    except chart_data.ChartError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.getLogger(__name__).warning("Chart %s %s failed: %s", symbol, tf, e)
        raise HTTPException(status_code=502, detail="Grafik verisi şu an alınamadı, biraz sonra tekrar dene.")


# ---------------- Command creation (panel actions -> queued) ----------------
async def _queue_command(cmd_type: str, payload: dict, user: dict) -> dict:
    cmd = {
        "id": f"cmd_{ObjectId()}",
        "request_id": f"req_{ObjectId()}",
        "type": cmd_type,
        "payload": payload,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user["id"],
        "role": "owner" if identity.is_owner(user) else "user",
        # where this user's results may also go; None = site only
        "telegram_chat_id": user.get("telegram_chat_id"),
        # the analysis runs on the user's own API keys (the bot fetches them only while this is pending)
        "own_keys": bool(user.get("kendi_anahtari")) and not identity.is_owner(user),
    }
    await db.commands.insert_one(dict(cmd))
    cmd.pop("_id", None)
    return cmd


class AlertBody(BaseModel):
    symbol: str
    side: str
    entry: float
    stop: Optional[float] = None    # "altına inerse" alarmında iptal/hedef yok
    target: Optional[float] = None
    note: Optional[str] = ""
    timeframe: Optional[str] = "15m"
    cooldown: Optional[str] = "1h"


@api.post("/alerts")
async def create_alert(body: AlertBody, user: dict = Depends(require_owner)):
    cmd = await _queue_command("alert.create", body.model_dump(), user)
    return {"queued": True, "command": cmd}


@api.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str, user: dict = Depends(require_owner)):
    cmd = await _queue_command("alert.delete", {"id": alert_id}, user)
    return {"queued": True, "command": cmd}


class StopBody(BaseModel):
    stop: float


@api.patch("/positions/{position_id}/stop")
async def update_stop(position_id: str, body: StopBody, user: dict = Depends(require_owner)):
    pos = await db.positions.find_one({"id": position_id}, {"_id": 0})
    if not pos:
        raise HTTPException(status_code=404, detail="Pozisyon bulunamadı.")
    if pos["status"] == "open":
        # Goalpost kuralı: açık pozisyonda stop, riski artıracak yönde çekilemez.
        if pos["side"] == "long" and body.stop < pos["stop"]:
            raise HTTPException(status_code=409, detail="Goalpost kuralı: açık long pozisyonda stop aşağı çekilemez.")
        if pos["side"] == "short" and body.stop > pos["stop"]:
            raise HTTPException(status_code=409, detail="Goalpost kuralı: açık short pozisyonda stop yukarı çekilemez.")
    cmd = await _queue_command("position.stop", {"id": position_id, "stop": body.stop}, user)
    return {"queued": True, "command": cmd}


class CloseBody(BaseModel):
    price: Optional[float] = None
    when: Optional[str] = None  # ISO time of the real sale; default now (the bot's clock)


@api.post("/positions/{position_id}/close")
async def close_position(position_id: str, body: Optional[CloseBody] = None,
                         user: dict = Depends(require_owner)):
    pos = await db.positions.find_one({"id": position_id}, {"_id": 0})
    if not pos or pos.get("status") != "open":
        raise HTTPException(status_code=404, detail="Açık pozisyon bulunamadı.")
    is_bist = pos.get("market") == "BIST" or pos.get("symbol", "").endswith(".IS")
    if is_bist and (body is None or body.price is None or not 0 < body.price < 1e9):
        raise HTTPException(status_code=400, detail="BIST için gerçekleşen satış fiyatı gerekli.")
    payload = {"id": position_id}
    if body is not None and body.price is not None:
        if not 0 < body.price < 1e9:
            raise HTTPException(status_code=400, detail="Satış fiyatı geçersiz.")
        payload["price"] = body.price
    if body is not None and body.when:
        try:
            when = datetime.fromisoformat(body.when.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Satış zamanı okunamadı.")
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone(timedelta(hours=3)))  # the form sends Turkish local time
        now = datetime.now(timezone.utc)
        if when > now + timedelta(minutes=5) or when < now - timedelta(days=366):
            raise HTTPException(status_code=400, detail="Satış zamanı gelecekte ya da bir yıldan eski olamaz.")
        payload["when"] = when.isoformat()
    cmd = await _queue_command("position.close", payload, user)
    return {"queued": True, "command": cmd}


class DecisionBody(BaseModel):
    verdict: str  # "Aldım" veya "Pas"


@api.post("/decisions/{decision_id}/action")
async def decision_action(decision_id: str, body: DecisionBody, user: dict = Depends(require_owner)):
    if body.verdict not in ("Aldım", "Pas"):
        raise HTTPException(status_code=400, detail="Geçersiz karar.")
    cmd = await _queue_command("decision.action", {"id": decision_id, "verdict": body.verdict}, user)
    return {"queued": True, "command": cmd}


# Panel actions the bot applies with its own functions (same rules as Telegram). Only these types are accepted.
USER_ACTION_TYPES = {"analysis.request"}
USER_DAILY_ANALYSES = int(os.environ.get("USER_DAILY_ANALYSES", "5"))  # on the owner's keys; 0 = own key required
USER_KEY_DAILY_ANALYSES = int(os.environ.get("USER_KEY_DAILY_ANALYSES", "50"))  # on the user's own keys
# All non-owner users together: caps the paid AI bill however many people sign up
GLOBAL_DAILY_ANALYSES = int(os.environ.get("GLOBAL_DAILY_ANALYSES", "100"))
ACTION_TYPES = {"analysis.request", "plan.add", "plan.remove", "firsat.run", "target.set", "watch.rules",
                "paper.open", "paper.close", "lesson.request", "check.request", "ind.create", "ind.delete",
                "compare.request", "dividend.refresh", "backtest.run", "settings.set", "fundamentals.request"}


class ActionBody(BaseModel):
    type: str
    payload: dict = {}


class StrategyRules(BaseModel):
    fk_max: Optional[float] = None
    momentum_min: Optional[float] = None
    quality_min: Optional[float] = None


class StrategyBody(BaseModel):
    name: str
    rules: StrategyRules


def _validated_strategy(body: StrategyBody) -> dict:
    name = body.name.strip()
    if not 2 <= len(name) <= 40 or any(ch in name for ch in "<>/\\"):
        raise HTTPException(status_code=400, detail="Strateji adı 2–40 karakter olmalı.")
    r = body.rules
    if any(v is not None and not math.isfinite(v) for v in (r.fk_max, r.momentum_min, r.quality_min)):
        raise HTTPException(status_code=400, detail="Koşullar sonlu sayı olmalı.")
    if r.fk_max is not None and not 0 < r.fk_max <= 100:
        raise HTTPException(status_code=400, detail="F/K üst sınırı 0–100 arasında olmalı.")
    if r.momentum_min is not None and not -100 <= r.momentum_min <= 300:
        raise HTTPException(status_code=400, detail="3 aylık göreli momentum -100 ile 300 arasında olmalı.")
    if r.quality_min is not None and not 0 <= r.quality_min <= 100:
        raise HTTPException(status_code=400, detail="Kalite puanı 0–100 arasında olmalı.")
    return {"name": name, "name_key": name.casefold(), "rules": r.model_dump()}


async def _queue_strategy_run(strategy: dict, user: dict, top_n: int = 3) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    count = await db.commands.count_documents({"user_id": user["id"], "type": "strategy.scan", "created_at": {"$gte": since}})
    if count >= 5:
        raise HTTPException(status_code=429, detail="Günde en fazla 5 strateji taraması yapılabilir.")
    pending = await db.commands.find_one({"user_id": user["id"], "type": "strategy.scan", "status": "pending"})
    if pending:
        raise HTTPException(status_code=409, detail="Önceki strateji taraman sürüyor.")
    return await _queue_command("strategy.scan", {"strategy_id": strategy["id"], "top_n": top_n}, user)


@api.get("/strategies")
async def list_strategies(user: dict = Depends(get_current_user)):
    return await db.strategies.find({"user_id": user["id"]}, {"_id": 0, "name_key": 0}).sort("created_at", -1).to_list(20)


@api.post("/strategies")
async def create_strategy(body: StrategyBody, user: dict = Depends(get_current_user)):
    value = _validated_strategy(body)
    if await db.strategies.count_documents({"user_id": user["id"]}) >= 20:
        raise HTTPException(status_code=400, detail="En fazla 20 strateji kaydedebilirsin.")
    if await db.strategies.find_one({"user_id": user["id"], "name_key": value["name_key"]}):
        raise HTTPException(status_code=409, detail="Bu adla bir stratejin var.")
    doc = {"id": f"st_{ObjectId()}", "user_id": user["id"], **value,
           "created_at": datetime.now(timezone.utc).isoformat()}
    await db.strategies.insert_one(dict(doc))
    doc.pop("_id", None)
    doc.pop("name_key", None)
    return doc


@api.delete("/strategies/{strategy_id}")
async def delete_strategy(strategy_id: str, user: dict = Depends(get_current_user)):
    result = await db.strategies.delete_one({"id": strategy_id, "user_id": user["id"]})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Strateji bulunamadı.")
    return {"ok": True}


@api.post("/strategies/{strategy_id}/run")
async def run_strategy(strategy_id: str, user: dict = Depends(get_current_user)):
    strategy = await db.strategies.find_one({"id": strategy_id, "user_id": user["id"]})
    if not strategy:
        raise HTTPException(status_code=404, detail="Strateji bulunamadı.")
    return await _queue_strategy_run(strategy, user)


class TelegramStrategyRun(BaseModel):
    chat_id: int
    name: str


@api.get("/strategies/{strategy_id}/history")
async def strategy_history(strategy_id: str, user: dict = Depends(get_current_user)):
    """Forward record of a strategy: each past scan's picks and their return since that scan vs BIST 100.
    Point-in-time fundamentals are not available for free, so this is NOT a historical backtest."""
    runs = await db.analyses.find({"user_id": user["id"], "strategy_id": strategy_id, "rows": {"$exists": True}},
                                  {"_id": 0, "id": 1, "zaman": 1, "rows": 1, "xu100": 1, "gecen": 1}).sort("zaman", -1).to_list(10)
    closes: dict[str, float | None] = {}

    async def close_of(code: str):
        if code not in closes:
            try:
                c = await chart_data.chart(code, "1d", "BIST")
                last = chart_data.last_closed(c.get("candles"), "BIST")
                closes[code] = last["c"] if last else None
            except Exception:
                closes[code] = None
        return closes[code]

    index_now = await close_of("XU100")
    out = []
    for run in runs:
        picks = []
        for r in run.get("rows") or []:
            now = await close_of(r["kod"])
            picks.append({"kod": r["kod"], "fiyat_o_gun": r.get("fiyat"), "fiyat_simdi": now,
                          "getiri": round((now / r["fiyat"] - 1) * 100, 2) if now and r.get("fiyat") else None})
        rets = [p["getiri"] for p in picks if p["getiri"] is not None]
        idx = round((index_now / run["xu100"] - 1) * 100, 2) if index_now and run.get("xu100") else None
        out.append({"id": run["id"], "zaman": run["zaman"], "secilen": picks, "gecen": run.get("gecen"),
                    "ortalama_getiri": round(sum(rets) / len(rets), 2) if rets else None, "xu100_getiri": idx})
    return {"kosular": out, "not": "Tarama anından bu yana, eşit ağırlıklı, maliyet ve temettü hariç, son kapanışlarla. "
            "Geriye dönük test değildir: bilançoların geçmişteki hâli ücretsiz kaynaklarda yok. Gelecek için garanti değildir."}


@api.post("/bot/telegram/strategy-run")
async def telegram_strategy_run(body: TelegramStrategyRun, _: bool = Depends(require_bot_key)):
    account = await db.users.find_one({"telegram_chat_id": body.chat_id})
    if not account:
        raise HTTPException(status_code=404, detail="Telegram hesabını siteden bağla.")
    user = _public_user(account)
    strategy = await db.strategies.find_one({"user_id": user["id"], "name_key": body.name.strip().casefold()})
    if not strategy:
        raise HTTPException(status_code=404, detail="Bu adla kayıtlı strateji bulunamadı.")
    return await _queue_strategy_run(strategy, user)


class TelegramQuantRun(BaseModel):
    chat_id: int
    top_n: int = 3


@api.post("/bot/telegram/quant-run")
async def telegram_quant_run(body: TelegramQuantRun, _: bool = Depends(require_bot_key)):
    if not 1 <= body.top_n <= 10:
        raise HTTPException(status_code=400, detail="1–10 hisse iste.")
    account = await db.users.find_one({"telegram_chat_id": body.chat_id})
    if not account:
        raise HTTPException(status_code=404, detail="Telegram hesabını siteden bağla.")
    return await _queue_strategy_run({"id": "builtin:quality_momentum"}, _public_user(account), body.top_n)


@api.get("/bot/strategies/{strategy_id}")
async def bot_get_strategy(strategy_id: str, _: bool = Depends(require_bot_key)):
    strategy = await db.strategies.find_one({"id": strategy_id}, {"_id": 0, "name_key": 0})
    if not strategy:
        raise HTTPException(status_code=404, detail="Strateji bulunamadı.")
    return strategy


@api.post("/actions")
async def panel_action(body: ActionBody, user: dict = Depends(get_current_user)):
    if body.type not in ACTION_TYPES:
        raise HTTPException(status_code=400, detail="Bilinmeyen işlem.")
    if not identity.is_owner(user):
        # Everyone else may only ask for an analysis (the bot's portfolio tools use the owner's budgets).
        if body.type not in USER_ACTION_TYPES:
            raise HTTPException(status_code=403, detail="Bu işlem yalnız sistem sahibine açık.")
        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        own = bool(user.get("kendi_anahtari"))
        limit = USER_KEY_DAILY_ANALYSES if own else USER_DAILY_ANALYSES
        if limit <= 0:
            raise HTTPException(status_code=403, detail="Analiz için kendi API anahtarını gir: Hesap → Yapay zekâ anahtarların.")
        used = await db.commands.count_documents({"user_id": user["id"], "type": "analysis.request", "created_at": {"$gte": since}})
        if used >= limit:
            raise HTTPException(status_code=429, detail=f"Günlük analiz hakkın doldu ({limit}/gün). Yarın tekrar dene."
                                + ("" if own else " Kendi API anahtarını girersen hakkın artar."))
        if not own:  # the shared (owner-paid) capacity
            everyone = await db.commands.count_documents({"role": "user", "own_keys": {"$ne": True}, "type": "analysis.request",
                                                          "created_at": {"$gte": since}})
            if everyone >= GLOBAL_DAILY_ANALYSES:
                raise HTTPException(status_code=429, detail="Bugünkü ortak analiz kapasitesi doldu. Kendi API anahtarınla devam edebilirsin.")
    if body.type == "analysis.request":
        codes = body.payload.get("kodlar") or [body.payload.get("kod")]
        if not any(codes) or len(codes) > 10:
            raise HTTPException(status_code=400, detail="1–10 kod seç.")
    if body.type == "compare.request" and not 2 <= len(body.payload.get("kodlar") or []) <= 4:
        raise HTTPException(status_code=400, detail="2–4 hisse seç.")
    cmd = await _queue_command(body.type, body.payload, user)
    return {"queued": True, "command": cmd}


@api.get("/quota")
async def quota(user: dict = Depends(get_current_user)):
    """Today's analysis allowance for the panel's QuotaMeter (the owner has no limit)."""
    if identity.is_owner(user):
        return {"sahip": True}
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    used = await db.commands.count_documents({"user_id": user["id"], "type": "analysis.request", "created_at": {"$gte": since}})
    own = bool(user.get("kendi_anahtari"))
    shared_used = await db.commands.count_documents({"role": "user", "own_keys": {"$ne": True}, "type": "analysis.request",
                                                     "created_at": {"$gte": since}})
    return {"sahip": False, "kullanilan": used, "sinir": USER_DAILY_ANALYSES, "anahtarla_sinir": USER_KEY_DAILY_ANALYSES,
            "kendi_anahtari": own, "ortak_dolu": (not own) and shared_used >= GLOBAL_DAILY_ANALYSES}


@api.get("/analyses")
async def get_analyses(kod: Optional[str] = None, user: dict = Depends(get_current_user)):
    q = {"kodlar": kod.upper()} if kod else {}
    # Each user sees only their own analyses; the owner also sees the ones made before accounts existed.
    q["$or"] = [{"user_id": user["id"]}] + ([{"user_id": {"$exists": False}}] if identity.is_owner(user) else [])
    return await db.analyses.find(q, {"_id": 0}).sort("zaman", -1).to_list(30)


@api.get("/sonuclar/{tur}")
async def get_result(tur: str, user: dict = Depends(require_owner)):
    """Latest result of a panel tool (kontrol, karsilastirma), pushed by the bot."""
    return await db.sonuclar.find_one({"id": tur}, {"_id": 0}) or {"id": tur, "zaman": None}


@api.get("/firsat")
async def get_firsat(user: dict = Depends(require_owner)):
    return await _one("firsat") or {"id": "firsat", "zaman": None}


@api.get("/commands")
async def list_commands(user: dict = Depends(get_current_user)):
    q = {"$or": [{"user_id": user["id"]}, {"user_id": {"$exists": False}}]} if identity.is_owner(user) else {"user_id": user["id"]}
    return await db.commands.find(q, {"_id": 0, "telegram_chat_id": 0}).sort("created_at", -1).to_list(200)


# ---------------- Bot endpoints (X-Bot-Key) ----------------
INGEST_COLLECTIONS = {"sonuclar", "alerts", "positions", "decisions", "macro", "derivatives", "usage", "candles",
                      "signals", "report", "backtest", "overview", "settings", "extras", "analyses", "firsat"}


@api.post("/ingest/{collection}")
async def ingest(collection: str, request: Request, replace: bool = False,
                 _: bool = Depends(require_bot_key)):
    """Upsert by id. With ?replace=true the payload is the full collection: other ids are deleted."""
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
    deleted = 0
    if replace:
        res = await db[collection].delete_many({"id": {"$nin": [i["id"] for i in items]}})
        deleted = res.deleted_count
    await db.bot_status.update_one({"id": "bot"}, {"$set": {"id": "bot", "last_ingest": datetime.now(timezone.utc).isoformat()}}, upsert=True)
    return {"ok": True, "collection": collection, "upserted": upserted, "deleted": deleted}


@api.get("/bot/status")
async def bot_status(user: dict = Depends(get_current_user)):
    doc = await db.bot_status.find_one({"id": "bot"}, {"_id": 0})
    return doc or {"id": "bot", "last_ingest": None}


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
app.include_router(user_api.build_router(lambda: db, get_current_user, require_bot_key, require_owner))
app.include_router(user_alerts.build_router(lambda: db, get_current_user, require_bot_key))
app.include_router(insights.build_router(lambda: db, get_current_user))
app.include_router(risk_budget.build_router(lambda: db, get_current_user))
app.include_router(advisor_api.build_router(get_current_user, require_owner))

# Serve the prebuilt panel (frontend/build) from this same server, so the panel opens in seconds
# instead of waiting for the React dev server to compile. /api routes above take precedence.
FRONTEND_BUILD = ROOT_DIR.parent / "frontend" / "build"
if FRONTEND_BUILD.is_dir():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app.mount("/static", StaticFiles(directory=FRONTEND_BUILD / "static"), name="static")
    # Kullanıcının kendi logoları (frontend/public/logos/KOD.png): yeniden derleme gerekmeden okunur
    LOGO_DIR = ROOT_DIR.parent / "frontend" / "public" / "logos"
    if not LOGO_DIR.is_dir() and (FRONTEND_BUILD / "logos").is_dir():
        LOGO_DIR = FRONTEND_BUILD / "logos"  # cloud image: only the build is shipped (it contains the logos)
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/logos", StaticFiles(directory=LOGO_DIR), name="logos")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        candidate = (FRONTEND_BUILD / full_path).resolve()
        if full_path and candidate.is_file() and FRONTEND_BUILD.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_BUILD / "index.html")  # client-side routes like /app/makro

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
    await db.users.create_index("clerk_id", unique=True, sparse=True)
    await db.users.create_index("telegram_chat_id", sparse=True)
    await db.commands.create_index([("user_id", 1), ("type", 1), ("created_at", -1)])
    await db.analyses.create_index([("user_id", 1), ("zaman", -1)])
    await db.strategies.create_index([("user_id", 1), ("name_key", 1)], unique=True)
    await user_api.ensure_indexes(db)
    await user_alerts.ensure_indexes(db)
    if os.environ.get("ALARM_LOOP", "1") == "1":  # users' close-based alarms (tests turn it off)
        asyncio.create_task(user_alerts.loop(lambda: db))
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.login_attempts.create_index("identifier")
    if identity.legacy_enabled():
        await seed_admin()
    if os.environ.get("SEED_MOCK") == "1":  # real data comes from the bot via /api/ingest
        await seed_mock()
    if os.environ.get("ADMIN_PASSWORD") == "Kapanis2026":
        logger.warning("ADMIN_PASSWORD is the published default; change it before going live")
    logger.info("Startup complete")


@app.on_event("shutdown")
async def shutdown():
    client.close()

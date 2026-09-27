"""Who is calling: Clerk session tokens (cloud) or the legacy single-admin cookie (local personal use).

AUTH_MODE
  legacy  only the old e-mail/password admin login (the password hash lives in MongoDB) - local default
  clerk   only Clerk: Google or e-mail + password with an e-mail code, handled entirely by Clerk
  both    either (useful while moving from local to cloud)

Roles
  owner   the person whose bot this is (OWNER_EMAIL, or the legacy admin): sees the bot's portfolio, signals, alarms
  user    anyone else who signed up: sees market data and only their own portfolio / analyses

Kapanış never stores Clerk passwords. A Clerk user is accepted only when Clerk reports the primary
e-mail as verified (Google e-mails are verified by Google, e-mail sign-ups by the Clerk code).
"""
import base64
import os
import time
from datetime import datetime, timezone

import httpx
import jwt

AUTH_MODE = os.environ.get("AUTH_MODE", "legacy").lower()
# The panel is Create React App, not Vite; the publishable key reaches the browser at runtime through
# /api/auth/config, so either variable name works and no rebuild is needed when it changes.
PUBLISHABLE_KEY = os.environ.get("CLERK_PUBLISHABLE_KEY") or os.environ.get("VITE_CLERK_PUBLISHABLE_KEY") or ""


def frontend_api(publishable_key: str) -> str:
    """pk_test_/pk_live_ + base64("<frontend-api-host>$") -> "https://<frontend-api-host>" ("" if malformed)."""
    try:
        b64 = publishable_key.split("_", 2)[2]
        host = base64.b64decode(b64 + "=" * (-len(b64) % 4)).decode("ascii").rstrip("$")
    except Exception:
        return ""
    return f"https://{host}" if host and "." in host and "/" not in host else ""


_FAPI = frontend_api(PUBLISHABLE_KEY)
CLERK_ISSUER = os.environ.get("CLERK_ISSUER") or _FAPI
CLERK_JWKS_URL = os.environ.get("CLERK_JWKS_URL") or (f"{_FAPI}/.well-known/jwks.json" if _FAPI else "")
CLERK_SECRET_KEY = os.environ.get("CLERK_SECRET_KEY", "")
CLERK_API = os.environ.get("CLERK_API_URL", "https://api.clerk.com/v1")
# Origins allowed to have minted the token (Clerk "azp" claim), e.g. https://kapanis.app
AUTHORIZED_PARTIES = [o.strip().rstrip("/") for o in os.environ.get("CLERK_AUTHORIZED_PARTIES", "").split(",") if o.strip()]
OWNER_EMAIL = (os.environ.get("OWNER_EMAIL") or os.environ.get("ADMIN_EMAIL") or "").lower()
OWNER_ROLES = ("owner", "admin")


class AuthError(Exception):
    """Message is shown to the user (Turkish)."""


def clerk_enabled() -> bool:
    return AUTH_MODE in ("clerk", "both") and bool(CLERK_JWKS_URL and CLERK_SECRET_KEY)


def legacy_enabled() -> bool:
    return AUTH_MODE in ("legacy", "both")


def is_owner(user: dict) -> bool:
    return (user or {}).get("role") in OWNER_ROLES


_jwks_client = None


def _jwks():
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(CLERK_JWKS_URL, cache_keys=True, lifespan=3600)
    return _jwks_client


def verify_clerk_token(token: str) -> dict:
    """Signature (RS256, Clerk JWKS), expiry, issuer and authorized party. Returns the claims."""
    try:
        key = _jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], issuer=CLERK_ISSUER or None,
                            options={"verify_aud": False, "require": ["exp", "sub"]}, leeway=10)
    except jwt.ExpiredSignatureError:
        raise AuthError("Oturum süresi doldu.")
    except (jwt.InvalidTokenError, jwt.PyJWKClientError) as e:
        raise AuthError(f"Geçersiz oturum ({type(e).__name__}).")
    azp = (claims.get("azp") or "").rstrip("/")
    if AUTHORIZED_PARTIES and azp and azp not in AUTHORIZED_PARTIES:
        raise AuthError("Bu oturum başka bir siteden açılmış.")
    return claims


_profile_cache: dict[str, tuple[float, dict]] = {}


async def fetch_clerk_profile(clerk_id: str) -> dict:
    """Primary e-mail and whether it is verified, from the Clerk Backend API (cached 5 minutes)."""
    hit = _profile_cache.get(clerk_id)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{CLERK_API}/users/{clerk_id}", headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"})
    if r.status_code != 200:
        raise AuthError("Hesap bilgisi doğrulanamadı, biraz sonra tekrar dene.")
    u = r.json()
    primary = next((e for e in u.get("email_addresses") or [] if e.get("id") == u.get("primary_email_address_id")), None)
    if not primary:
        raise AuthError("Hesapta e-posta adresi yok.")
    profile = {"email": primary["email_address"].lower(),
               "verified": (primary.get("verification") or {}).get("status") == "verified",
               "name": " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or None}
    _profile_cache[clerk_id] = (time.time(), profile)
    return profile


async def delete_clerk_user(clerk_id: str) -> bool:
    """Remove the account from Clerk too (account deletion). True when Clerk confirms or it was already gone."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.delete(f"{CLERK_API}/users/{clerk_id}", headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"})
    _profile_cache.pop(clerk_id, None)
    return r.status_code in (200, 404)


async def user_from_clerk(db, token: str) -> dict:
    """Verified Clerk token -> the Kapanış user document (created on first sign-in)."""
    claims = verify_clerk_token(token)
    clerk_id = claims["sub"]
    user = await db.users.find_one({"clerk_id": clerk_id})
    if user is None or not user.get("email_verified"):
        profile = await fetch_clerk_profile(clerk_id)
        if not profile["verified"]:
            raise AuthError("E-posta adresin doğrulanmadı. Mailine gelen kodu gir.")
        role = "owner" if OWNER_EMAIL and profile["email"] == OWNER_EMAIL else "user"
        now = datetime.now(timezone.utc).isoformat()
        existing = user or await db.users.find_one({"email": profile["email"]})
        if existing:  # e.g. the legacy admin signing in with Clerk for the first time: same account
            update = {"clerk_id": clerk_id, "email_verified": True}
            if existing.get("role") not in OWNER_ROLES:
                update["role"] = role
            await db.users.update_one({"_id": existing["_id"]}, {"$set": update})
        else:
            await db.users.insert_one({"clerk_id": clerk_id, "email": profile["email"], "name": profile["name"],
                                       "role": role, "email_verified": True, "created_at": now})
        user = await db.users.find_one({"clerk_id": clerk_id})
    return user

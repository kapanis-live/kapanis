"""Kapanış backend integration tests."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else "https://decision-panel-2.preview.emergentagent.com"
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@kapanis.io"
ADMIN_PASSWORD = "Kapanis2026"
BOT_KEY = "dev-bot-key-2026-secret-change-me"


@pytest.fixture(scope="session")
def auth_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return s


# ---------- Auth ----------
class TestAuth:
    def test_login_success(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == ADMIN_EMAIL
        assert "id" in data
        # cookies set
        assert "access_token" in s.cookies.get_dict() or "access_token" in r.cookies.get_dict()

    def test_me_with_cookie(self, auth_session):
        r = auth_session.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 200
        assert r.json()["email"] == ADMIN_EMAIL

    def test_me_unauth(self):
        r = requests.get(f"{API}/auth/me", timeout=15)
        assert r.status_code == 401

    def test_wrong_password(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"}, timeout=15)
        assert r.status_code == 401

    def test_refresh(self, auth_session):
        r = auth_session.post(f"{API}/auth/refresh", timeout=15)
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_logout_and_relogin(self):
        s = requests.Session()
        s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
        r = s.post(f"{API}/auth/logout", timeout=15)
        assert r.status_code == 200
        r2 = s.get(f"{API}/auth/me", timeout=15)
        assert r2.status_code == 401

    def test_brute_force_lock(self):
        # Use a unique email so we don't lock the real admin from this IP
        bogus = f"lockme_{uuid.uuid4().hex[:6]}@kapanis.io"
        last_status = None
        for _ in range(6):
            r = requests.post(f"{API}/auth/login", json={"email": bogus, "password": "x"}, timeout=15)
            last_status = r.status_code
        # After >=5 fails should be locked (429)
        assert last_status == 429, f"expected 429 got {last_status}"


# ---------- Data endpoints ----------
DATA_ENDPOINTS = [
    "/overview", "/alerts", "/positions", "/decisions", "/signals",
    "/macro", "/derivatives", "/usage", "/report", "/backtest",
    "/settings", "/candles/BTC-USDT",
]


@pytest.mark.parametrize("path", DATA_ENDPOINTS)
def test_data_endpoints_authed(auth_session, path):
    r = auth_session.get(f"{API}{path}", timeout=15)
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
    body = r.json()
    assert body is not None


@pytest.mark.parametrize("path", DATA_ENDPOINTS)
def test_data_endpoints_unauth(path):
    r = requests.get(f"{API}{path}", timeout=15)
    assert r.status_code == 401


def test_signal_by_id(auth_session):
    r = auth_session.get(f"{API}/signals/sig_btc_1", timeout=15)
    assert r.status_code == 200
    assert r.json()["id"] == "sig_btc_1"


# ---------- Commands / queue ----------
class TestCommands:
    def test_create_alert_queued(self, auth_session):
        r = auth_session.post(f"{API}/alerts", json={
            "symbol": "TEST/USDT", "side": "long", "entry": 100, "stop": 95, "target": 115, "note": "TEST_alert"
        }, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["queued"] is True
        assert data["command"]["status"] == "pending"

    def test_delete_alert_queued(self, auth_session):
        r = auth_session.delete(f"{API}/alerts/alr_near_retest", timeout=15)
        assert r.status_code == 200
        assert r.json()["command"]["status"] == "pending"

    def test_close_position_queued(self, auth_session):
        r = auth_session.post(f"{API}/positions/pos_sol_1/close", timeout=15)
        assert r.status_code == 200
        assert r.json()["command"]["status"] == "pending"

    def test_decision_action_queued(self, auth_session):
        r = auth_session.post(f"{API}/decisions/dec_near_1/action", json={"verdict": "Aldım"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["command"]["status"] == "pending"

    def test_list_commands(self, auth_session):
        r = auth_session.get(f"{API}/commands", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ---------- Goalpost ----------
class TestGoalpost:
    def test_lower_stop_blocked(self, auth_session):
        r = auth_session.patch(f"{API}/positions/pos_btc_1/stop", json={"stop": 80000}, timeout=15)
        assert r.status_code == 409

    def test_higher_stop_queued(self, auth_session):
        r = auth_session.patch(f"{API}/positions/pos_btc_1/stop", json={"stop": 83500}, timeout=15)
        assert r.status_code == 200
        assert r.json()["command"]["status"] == "pending"


# ---------- Bot endpoints ----------
class TestBot:
    def test_ingest_requires_key(self):
        r = requests.post(f"{API}/ingest/alerts", json={"id": "x"}, timeout=15)
        assert r.status_code == 401

    def test_ingest_with_key(self):
        r = requests.post(
            f"{API}/ingest/alerts",
            headers={"X-Bot-Key": BOT_KEY},
            json={"id": "TEST_ingest_alr", "symbol": "TEST/USDT", "side": "long"},
            timeout=15,
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_pending_commands_bot(self):
        r = requests.get(f"{API}/commands/pending", headers={"X-Bot-Key": BOT_KEY}, timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_command_done(self, auth_session):
        # create a command via panel first
        c = auth_session.post(f"{API}/positions/pos_sol_1/close", timeout=15).json()
        cid = c["command"]["id"]
        r = requests.post(f"{API}/commands/{cid}/done", headers={"X-Bot-Key": BOT_KEY}, timeout=15)
        assert r.status_code == 200
        assert r.json()["ok"] is True

"""alerts.json (price alerts) and settings.json (quiet hours) persistence."""
import json
import os
import re
from datetime import datetime, timedelta

import config
from macro import TR

ACTIVE_STATES = ("aktif", "tetiklendi")  # states that still need the websocket
_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def now_tr() -> datetime:
    return datetime.now(TR).replace(microsecond=0)


# --- alerts ------------------------------------------------------------------

def load_alerts() -> dict[str, list[dict]]:
    return _load(config.ALERTS_FILE, {})


def save_alerts(alerts: dict):
    _save(config.ALERTS_FILE, alerts)


def pair_to_symbol(pair: str) -> str:
    return pair.replace("/", "").upper()


def add_alert(pair: str, alert: dict) -> dict:
    alerts = load_alerts()
    items = alerts.setdefault(pair, [])
    alert = {"id": max((a["id"] for a in items), default=0) + 1, **alert,
             "durum": "aktif", "son_tetik_zamani": None, "tetikler": [],
             "olusturulma": now_tr().isoformat()}
    items.append(alert)
    save_alerts(alerts)
    return alert


def streams() -> set[tuple[str, str]]:
    """(SYMBOL, timeframe) pairs that have at least one live alert."""
    # BIST alarms (".IS") are checked on Yahoo bars in bist_signals.check_alarms, never on Binance
    # websockets: one invalid stream name would break the whole combined crypto connection.
    return {(pair_to_symbol(pair), a["timeframe"])
            for pair, items in load_alerts().items() if not pair.upper().endswith((".IS", ".US"))
            for a in items if a["durum"] in ACTIVE_STATES}


def parse_duration(text: str) -> timedelta | None:
    m = re.fullmatch(r"(\d+)([mhd])", text.lower())
    if not m:
        return None
    n, unit = int(m[1]), m[2]
    return timedelta(minutes=n) if unit == "m" else timedelta(hours=n) if unit == "h" else timedelta(days=n)


# --- settings ----------------------------------------------------------------

def load_settings() -> dict:
    s = _load(config.SETTINGS_FILE, {})
    s.setdefault("quiet_hours", None)  # "09:00-16:00"
    s.setdefault("quiet_days", [])     # ["Mon", ...]; empty = every day
    return s


def save_settings(s: dict):
    _save(config.SETTINGS_FILE, s)


def parse_quiet_hours(text: str) -> tuple[str, str] | None:
    m = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)", text)
    return (f"{m[1]}:{m[2]}", f"{m[3]}:{m[4]}") if m else None


def parse_days(text: str) -> list[str] | None:
    days = [d.strip().capitalize()[:3] for d in text.split(",") if d.strip()]
    return days if days and all(d in _DAYS for d in days) else None


def is_quiet(when: datetime | None = None) -> bool:
    s = load_settings()
    if not s["quiet_hours"]:
        return False
    when = when or now_tr()
    if s["quiet_days"] and _DAYS[when.weekday()] not in s["quiet_days"]:
        return False
    start, end = s["quiet_hours"].split("-")
    hhmm = when.strftime("%H:%M")
    return start <= hhmm < end if start < end else hhmm >= start or hhmm < end

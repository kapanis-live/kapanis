"""Notification control for the owner's chat: quiet windows, full mute, held messages.

- /sessizlik: recurring windows the user describes in words ("hafta içi 12.00-14.30 arası bildirim atma").
  During a window automatic messages are held, not sent; when it ends one summary arrives.
- /sessiz: no automatic message at all until /plan (or /sessiz kapat).
Replies to the user's own commands and button presses always arrive (see main.RetryBot).
Settings live in settings.json: "sessizlik" (list of windows), "sessiz" (bool), "bekleyen_bildirimler".
"""
import re
from datetime import datetime

import alerts_store

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_TR = {"Mon": "Pzt", "Tue": "Sal", "Wed": "Çar", "Thu": "Per", "Fri": "Cum", "Sat": "Cmt", "Sun": "Paz"}
# Longest names first: "cumartesi" contains "cuma", "pazartesi" contains "pazar".
_DAY_WORDS = [("cumartesi", "Sat"), ("pazartesi", "Mon"), ("çarşamba", "Wed"), ("carsamba", "Wed"),
              ("perşembe", "Thu"), ("persembe", "Thu"), ("salı", "Tue"), ("sali", "Tue"),
              ("cuma", "Fri"), ("pazar", "Sun")]
MAX_HELD = 60


def parse_window(text: str) -> dict | None:
    """'her hafta içi 12.00 14.30 arası bildirim atma' -> {"gunler": [Mon..Fri], "bas": "12:00", "bit": "14:30"}."""
    t = text.lower().replace("i̇", "i")
    times = [(int(h), int(m or 0)) for h, m in re.findall(r"\b([01]?\d|2[0-3])(?:[.:]([0-5]\d))?\b(?![.,]\d)", t)
             if not re.fullmatch(r"\d{3,}", h)]
    if len(times) < 2:
        return None
    (h1, m1), (h2, m2) = times[0], times[1]
    start, end = f"{h1:02d}:{m1:02d}", f"{h2:02d}:{m2:02d}"
    if start == end:
        return None
    days: list[str] = []
    if "hafta içi" in t or "hafta ici" in t or "haftaiçi" in t or "haftaici" in t:
        days += DAYS[:5]
    if "hafta sonu" in t or "haftasonu" in t:
        days += DAYS[5:]
    rest = t
    for word, day in _DAY_WORDS:
        if re.search(rf"\b{word}", rest):
            days.append(day)
            rest = re.sub(rf"\b{word}\w*", " ", rest)
    days = [d for d in DAYS if d in set(days)] or DAYS[:]  # none named = every day
    return {"gunler": days, "bas": start, "bit": end}


def describe(w: dict) -> str:
    g = w["gunler"]
    days = ("her gün" if len(g) == 7 else "hafta içi" if g == DAYS[:5] else "hafta sonu" if g == DAYS[5:]
            else ", ".join(DAY_TR[d] for d in g))
    return f"{days} {w['bas']}–{w['bit']}"


def windows() -> list[dict]:
    return alerts_store.load_settings().get("sessizlik") or []


def add_window(w: dict) -> list[dict]:
    s = alerts_store.load_settings()
    items = [x for x in s.get("sessizlik") or [] if x != w] + [w]
    s["sessizlik"] = items
    alerts_store.save_settings(s)
    return items


def remove_window(index: int) -> dict | None:
    s = alerts_store.load_settings()
    items = s.get("sessizlik") or []
    if not 1 <= index <= len(items):
        return None
    gone = items.pop(index - 1)
    s["sessizlik"] = items
    alerts_store.save_settings(s)
    return gone


def clear_windows():
    s = alerts_store.load_settings()
    s["sessizlik"] = []
    alerts_store.save_settings(s)


def in_window(w: dict, when: datetime) -> bool:
    hhmm = when.strftime("%H:%M")
    if w["bas"] < w["bit"]:
        return DAYS[when.weekday()] in w["gunler"] and w["bas"] <= hhmm < w["bit"]
    # Over midnight (22:00-07:00): the part after midnight belongs to the previous day's window.
    if hhmm >= w["bas"]:
        return DAYS[when.weekday()] in w["gunler"]
    return hhmm < w["bit"] and DAYS[(when.weekday() - 1) % 7] in w["gunler"]


def active_window(when: datetime | None = None) -> dict | None:
    when = when or alerts_store.now_tr()
    return next((w for w in windows() if in_window(w, when)), None)


def is_muted_all() -> bool:
    return bool(alerts_store.load_settings().get("sessiz"))


def set_muted_all(on: bool):
    s = alerts_store.load_settings()
    s["sessiz"] = on
    alerts_store.save_settings(s)


def muted(when: datetime | None = None) -> bool:
    return is_muted_all() or active_window(when) is not None


def hold(text: str | None, kind: str = "mesaj"):
    s = alerts_store.load_settings()
    held = s.setdefault("bekleyen_bildirimler", [])
    held.append({"saat": alerts_store.now_tr().strftime("%d.%m %H:%M"), "tur": kind, "metin": (text or "")[:400]})
    s["bekleyen_bildirimler"] = held[-MAX_HELD:]
    alerts_store.save_settings(s)


def take_held() -> list[dict]:
    s = alerts_store.load_settings()
    held = s.get("bekleyen_bildirimler") or []
    if held:
        s["bekleyen_bildirimler"] = []
        alerts_store.save_settings(s)
    return held


def digest(held: list[dict]) -> str:
    """One message for everything held while quiet: first line of each, newest last."""
    lines = [f"🔔 Sessizken {len(held)} bildirim birikti:"]
    for h in held[-25:]:
        first = next((ln.strip() for ln in h["metin"].splitlines() if ln.strip()), "grafik" if h["tur"] == "foto" else "")
        lines.append(f"• {h['saat']} {first[:140]}")
    if len(held) > 25:
        lines.insert(1, f"(ilk {len(held) - 25} tanesi gösterilmiyor)")
    lines.append("\nGüncel durum: /plan · alarmlar: /alarmlar · portföy: /portfoy. "
                 "Sessizken gelen AL sinyali artık bayat olabilir: fiyatı kontrol etmeden kovalama.")
    return "\n".join(lines)

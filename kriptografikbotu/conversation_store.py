"""Conversation history and coin plan state, both persisted as JSON."""
import json
import os
import time

import config

LEVEL_KEYS = ("tetik", "teyit", "iptal", "hedef")


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# --- history -----------------------------------------------------------------

def load_history() -> list[dict]:
    return _load(config.HISTORY_FILE, [])


def append_history(user_text: str, assistant_text: str):
    history = load_history()
    history += [{"role": "user", "content": user_text},
                {"role": "assistant", "content": assistant_text}]
    _save(config.HISTORY_FILE, history[-config.HISTORY_STORE_TURNS * 2:])


def clear_history():
    _save(config.HISTORY_FILE, [])


# --- state -------------------------------------------------------------------

def load_state() -> dict:
    state = _load(config.STATE_FILE, {})
    state.setdefault("planlar", {})
    state.setdefault("btc_not", None)
    return state


def save_state(state: dict):
    _save(config.STATE_FILE, state)


def _to_float(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def apply_update(update: dict) -> list[str]:
    """Merge the model's <STATE> block into state.json. Returns warnings for the user.

    Enforces the goalpost rule in code: with an open position the stop (iptal)
    can't move down, and the plan can't be dropped.
    """
    state = load_state()
    plans = state["planlar"]
    warnings = []

    for coin, new in (update.get("planlar") or {}).items():
        coin = coin.upper()
        old = plans.get(coin, {})
        merged = dict(old)
        for key in LEVEL_KEYS:
            if key in new:
                merged[key] = _to_float(new[key])
        if "not" in new:
            merged["not"] = new["not"]

        if old.get("pozisyon") and old.get("iptal") is not None:
            if merged.get("iptal") is None or merged["iptal"] < old["iptal"]:
                warnings.append(f"⚠️ {coin}: pozisyon açık, iptal {old['iptal']} altına çekilemez (goalpost yasağı). Eski iptal korundu.")
                merged["iptal"] = old["iptal"]

        if any(merged.get(k) != old.get(k) for k in LEVEL_KEYS):
            merged.pop("bekleyen_teyit", None)
            if coin.endswith(".IS"):
                merged.pop("sinyal_verildi", None)
        merged["guncelleme"] = int(time.time())
        merged.setdefault("pozisyon", False)
        plans[coin] = merged

    for coin in update.get("iptal_edilen") or []:
        coin = coin.upper()
        if coin not in plans:
            continue
        if plans[coin].get("pozisyon"):
            warnings.append(f"⚠️ {coin}: pozisyon açıkken plan silinmedi. Önce /pozisyon {coin} kapali yaz.")
            continue
        del plans[coin]

    if update.get("btc_not"):
        state["btc_not"] = update["btc_not"]

    save_state(state)
    return warnings

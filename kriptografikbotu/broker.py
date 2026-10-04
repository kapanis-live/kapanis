"""Coins the user's broker (Midas) does not offer in USD/USDT: they are left out of every crypto scan.

A hard filter, not a model: a setup on a coin the user cannot buy is noise. The list is the user's own (/midas);
the defaults are the coins the user reported. Coins already held are still analysed (the scans add holdings back).
"""
import re

import alerts_store

KEY = "midas_yok"
DEFAULT = ["STX", "JASMY", "INJ", "TAO"]


def blocked() -> set[str]:
    return set(alerts_store.load_settings().get(KEY, DEFAULT))


def _coins(words) -> list[str]:
    return [w for w in (re.sub(r"(USDT|USD)$", "", str(x).upper().strip(",;")) for x in words) if w.isascii() and w.isalnum()]


def change(words, block: bool) -> list[str]:
    """Add (block) or remove coins; returns the coins that changed."""
    s = alerts_store.load_settings()
    cur = list(s.get(KEY, DEFAULT))
    changed = [c for c in dict.fromkeys(_coins(words)) if (c not in cur) == block]
    s[KEY] = sorted(set(cur) | set(changed)) if block else [c for c in cur if c not in changed]
    alerts_store.save_settings(s)
    return changed


def text() -> str:
    b = sorted(blocked())
    return ("🚫 Midas'ta alınamayan coinler (taramalara girmez): " + (", ".join(b) if b else "yok")
            + "\nEkle: /midas yok STX JASMY\nÇıkar: /midas var STX\nElindeki coin listede olsa da analiz edilir.")

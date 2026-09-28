"""Constrained Turkish BIST quant request parsing (/quant and plain text). Voice input was removed."""
import re


def top_n(text: str) -> int | None:
    t = " ".join((text or "").casefold().split())
    if "bist" not in t or "momentum" not in t or not ("kalite" in t or "quality" in t):
        return None
    match = re.search(r"\b(10|[1-9])\s*(?:hisse\w*|adet|tane)\b", t)
    if match:
        return int(match.group(1))
    words = {"bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10}
    for word, n in words.items():
        if re.search(rf"\b{word}\s*(?:hisse\w*|adet|tane)\b", t):
            return n
    return 3


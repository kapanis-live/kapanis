"""Portfolio-level alarms, per market (BIST TL, crypto USDT, gold/FX TL), on balance = holdings + cash.

Two kinds:
- percent from now: "kripto %-10" -> fires when the crypto balance is 10% below its value when the alarm was set
- level: "bist 20000" -> fires when the BIST balance crosses 20,000 TL (direction taken from where it is now)
Each alarm fires once; it is then marked done. Stored in settings.json ("portfoy_alarmlari").
"""
import re

import alerts_store

MARKETS = {"abd": "ABD", "amerika": "ABD", "bist": "BIST", "kripto": "KRIPTO", "kripto para": "KRIPTO", "coin": "KRIPTO", "altin": "DIGER",
           "altın": "DIGER", "doviz": "DIGER", "döviz": "DIGER"}
UNITS = {"BIST": "TL", "KRIPTO": "USDT", "DIGER": "TL", "ABD": "USD"}
NAMES = {"BIST": "🇹🇷 BIST", "KRIPTO": "🪙 Kripto", "DIGER": "🥇 Altın/Döviz", "ABD": "🇺🇸 ABD"}


def load() -> list[dict]:
    return alerts_store.load_settings().get("portfoy_alarmlari", [])


def save(items: list[dict]):
    s = alerts_store.load_settings()
    s["portfoy_alarmlari"] = items
    alerts_store.save_settings(s)


def parse(text: str) -> dict | None:
    """"kripto %-10", "bist 20000", "kripto portföyüm %10 düşerse" -> {piyasa, tur, deger}. Pure."""
    low = text.lower().replace(",", ".")
    mkt = next((v for k, v in MARKETS.items() if re.search(rf"(?<![a-zçğıöşü]){k}", low)), None)
    if not mkt:
        return None
    pct = re.search(r"%\s*([+-]?\d+(?:\.\d+)?)|([+-]?\d+(?:\.\d+)?)\s*%", low)
    if pct:
        v = float(pct.group(1) or pct.group(2))
        if not any(c in (pct.group(1) or pct.group(2)) for c in "+-"):
            if any(w in low for w in ("düş", "dus", "kayb", "azal", "eksi")):
                v = -v
        return {"piyasa": mkt, "tur": "yuzde", "deger": v} if v else None
    num = re.search(r"(\d+(?:\.\d+)?)", low)
    if num:
        return {"piyasa": mkt, "tur": "seviye", "deger": float(num.group(1))}
    return None


def add(alarm: dict, balance_now: float) -> dict:
    items = load()
    a = {"id": max((x["id"] for x in items), default=0) + 1, **alarm, "baslangic": round(balance_now, 2),
         "durum": "aktif", "olusturma": alerts_store.now_tr().isoformat()}
    if a["tur"] == "yuzde":
        a["esik"] = round(balance_now * (1 + a["deger"] / 100), 2)
        a["yon"] = "ALTINA" if a["deger"] < 0 else "USTUNE"
    else:
        a["esik"] = a["deger"]
        a["yon"] = "ALTINA" if a["deger"] < balance_now else "USTUNE"
    items.append(a)
    save(items)
    return a


def remove(alarm_id: int) -> bool:
    items = load()
    left = [a for a in items if a["id"] != alarm_id]
    save(left)
    return len(left) < len(items)


def label(a: dict) -> str:
    unit = UNITS[a["piyasa"]]
    what = (f"%{a['deger']:+g} ({a['baslangic']:,.2f} → {a['esik']:,.2f} {unit})" if a["tur"] == "yuzde"
            else f"{a['esik']:,.2f} {unit}")
    return f"#{a['id']} {NAMES[a['piyasa']]} bakiye {what} {'altına inerse' if a['yon'] == 'ALTINA' else 'üstüne çıkarsa'} [{a['durum']}]"


def check(balances: dict[str, float]) -> list[str]:
    """balances: market -> current balance. Returns messages for alarms that fired (marks them done). Pure-ish."""
    items, msgs = load(), []
    for a in items:
        if a["durum"] != "aktif" or a["piyasa"] not in balances:
            continue
        now = balances[a["piyasa"]]
        hit = now <= a["esik"] if a["yon"] == "ALTINA" else now >= a["esik"]
        if hit:
            a["durum"] = "tetiklendi"
            a["tetik_zamani"] = alerts_store.now_tr().isoformat()
            unit = UNITS[a["piyasa"]]
            change = (now / a["baslangic"] - 1) * 100 if a["baslangic"] else 0
            msgs.append(f"🔔 PORTFÖY ALARMI — {NAMES[a['piyasa']]}: bakiye {now:,.2f} {unit} "
                        f"({'eşiğin altında' if a['yon'] == 'ALTINA' else 'eşiğin üstünde'}: {a['esik']:,.2f}). "
                        f"Alarm kurulduğundan beri %{change:+.2f}.\nDetay: /bakiye · /portfoy")
    if msgs:
        save(items)
    return msgs

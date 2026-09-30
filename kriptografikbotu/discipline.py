"""Discipline shield: stop giving AL signals when the user is likely on tilt.

Rules (all in code, checked by both decision gates):
- LOSS_STREAK losing trades in a row (both markets together: tilt is about the person) -> no new AL
  for COOLDOWN_HOURS after the last loss.
- Realized loss today above DAILY_LOSS_PCT of that market's budget -> no new AL in that market today.
Only short-term trades count (positions.is_trade): accumulation buys and imported holdings don't.
Several records closed in the same minute for the same asset (FIFO / partial sells) are one trade.
"/disiplin sifirla" forgives the current streak; the override itself is logged as a rule event.
"""
from datetime import datetime, timedelta

import alerts_store
import bist
import config
import positions


def closed_trades(items: list[dict] | None = None) -> list[dict]:
    """Closed short-term trades, merged per (asset, minute), oldest first."""
    items = positions.load() if items is None else items
    merged: dict[tuple, dict] = {}
    for p in items:
        if p["durum"] != "kapali" or not p.get("kapanis_zamani") or not positions.is_trade(p):
            continue
        key = (p["symbol"], p["kapanis_zamani"][:16])
        t = merged.setdefault(key, {"symbol": p["symbol"], "pair": p["pair"], "piyasa": p.get("piyasa", "KRIPTO"),
                                    "para": p.get("para", "USD"), "zaman": p["kapanis_zamani"], "pnl": 0.0,
                                    "ids": []})
        t["pnl"] += (p["kapanis_fiyat"] - p["giris"]) * p["adet"]
        t["ids"].append(p["id"])
    return sorted(merged.values(), key=lambda t: t["zaman"])


def budget(market: str) -> float | None:
    if market == "ABD":
        v = alerts_store.load_settings().get("abd_butce_usd")
        return float(v) if v else None
    return float(config.CRYPTO_BUDGET_USD) if market == "KRIPTO" else bist.budget_tl()


def status(now: datetime | None = None, items: list[dict] | None = None) -> dict:
    """{"engel": bool, "piyasa_engel": {"KRIPTO": reason|None, "BIST": reason|None}, "seri": n, ...}"""
    now = now or alerts_store.now_tr()
    s = alerts_store.load_settings()
    forgiven = s.get("disiplin_af")
    trades = closed_trades(items)
    streak_trades = [t for t in trades if not forgiven or t["zaman"] > forgiven]
    streak, last_loss = 0, None
    for t in reversed(streak_trades):
        if t["pnl"] >= 0:
            break
        streak += 1
        last_loss = last_loss or t["zaman"]
    until = None
    if streak >= config.LOSS_STREAK and last_loss:
        end = datetime.fromisoformat(last_loss) + timedelta(hours=config.COOLDOWN_HOURS)
        if end > now:
            until = end
    today = now.date().isoformat()
    per_market = {}
    for mkt in ("KRIPTO", "BIST", "ABD"):
        loss = -sum(t["pnl"] for t in trades if t["piyasa"] == mkt and t["zaman"][:10] == today)
        b = budget(mkt)
        limit = b * config.DAILY_LOSS_PCT / 100 if b else None
        cur = "TL" if mkt == "BIST" else "USD"
        reason = None
        if limit and loss > limit:
            reason = (f"bugünkü gerçekleşen zarar {loss:,.2f} {cur} > günlük sınır {limit:,.2f} {cur} "
                      f"(bütçenin %{config.DAILY_LOSS_PCT:g}'ü): bugün yeni giriş yok")
        if until:
            reason = (f"üst üste {streak} zarar: {until.strftime('%d.%m %H:%M')}'e kadar yeni giriş yok (tilt koruması)"
                      + (f"; ayrıca {reason}" if reason else ""))
        per_market[mkt] = {"engel": reason, "gunluk_zarar": round(loss, 2), "gunluk_sinir": limit, "para": cur}
    return {"aktif": s.get("disiplin", True), "seri": streak, "bekleme_bitis": until.isoformat() if until else None,
            "piyasa": per_market}


def check(market: str) -> tuple[bool, str]:
    """For the gates: (passed, detail)."""
    st = status()
    if not st["aktif"]:
        return True, "disiplin kalkanı kapalı (/disiplin ac)"
    reason = st["piyasa"][market]["engel"]
    if reason:
        return False, reason
    m = st["piyasa"][market]
    # gunluk_zarar is a loss as a positive number; show it as today's realized P/L (a loss is negative)
    limit = (f", bugün gerçekleşen K/Z {-m['gunluk_zarar']:+,.2f} {m['para']} (sınır −{m['gunluk_sinir']:,.2f})"
             if m["gunluk_sinir"] else "")
    return True, f"zarar serisi {st['seri']}/{config.LOSS_STREAK}{limit}"


def forgive() -> None:
    s = alerts_store.load_settings()
    now = alerts_store.now_tr().isoformat()
    s["disiplin_af"] = now
    s.setdefault("disiplin_olaylari", []).append({"zaman": now, "tur": "af", "not": "tilt beklemesi elle kaldırıldı"})
    alerts_store.save_settings(s)


def set_enabled(on: bool) -> None:
    s = alerts_store.load_settings()
    s["disiplin"] = on
    if not on:
        s.setdefault("disiplin_olaylari", []).append({"zaman": alerts_store.now_tr().isoformat(), "tur": "kapatma",
                                                       "not": "disiplin kalkanı kapatıldı"})
    alerts_store.save_settings(s)


VIOLATION_LABELS = {"stop_asagi": "stopu aşağı çekme denemesi", "sat_tut": "SAT kararına rağmen tutma",
                    "stop_tut": "stop kırıldı, tutuldu", "limit": "bütçe/kademe sınırı aşıldı",
                    "af": "tilt beklemesini elle kaldırma", "kapatma": "disiplin kalkanını kapatma",
                    "diger": "diğer"}


def _kind(v: dict) -> str:
    if v.get("tur"):
        return v["tur"]
    text = v.get("not", "")
    if "stop kapanışla kırıldı" in text:
        return "stop_tut"
    if "limit" in text or "sınır" in text:
        return "limit"
    return "diger"


def violations(since: str) -> dict[str, list[dict]]:
    """Rule events since an ISO time, grouped by kind (position violations + shield overrides)."""
    out: dict[str, list[dict]] = {}
    for p in positions.load():
        for v in p.get("kural_ihlali", []):
            if v["zaman"] >= since:
                out.setdefault(_kind(v), []).append({**v, "pair": p["pair"], "id": p["id"]})
    for v in alerts_store.load_settings().get("disiplin_olaylari", []):
        if v["zaman"] >= since:
            out.setdefault(v["tur"], []).append(v)
    return out


def text(since: str) -> str:
    st = status()
    lines = ["🛡 DİSİPLİN KALKANI " + ("açık" if st["aktif"] else "KAPALI")]
    lines.append(f"Zarar serisi: {st['seri']} (sınır {config.LOSS_STREAK})"
                 + (f" · bekleme {datetime.fromisoformat(st['bekleme_bitis']).strftime('%d.%m %H:%M')}'e kadar"
                    if st["bekleme_bitis"] else ""))
    for mkt, title in (("KRIPTO", "🪙 Kripto"), ("BIST", "🇹🇷 BIST")):
        m = st["piyasa"][mkt]
        limit = f"{m['gunluk_sinir']:,.2f} {m['para']}" if m["gunluk_sinir"] else "bütçe yok"
        lines.append(f"{title}: bugün {-m['gunluk_zarar']:+,.2f} {m['para']} (sınır −{limit}) · "
                     + ("⛔ " + m["engel"] if m["engel"] else "✅ yeni giriş serbest"))
    v = violations(since)
    if v:
        lines.append("Kural olayları: " + ", ".join(f"{VIOLATION_LABELS.get(k, k)} {len(x)}" for k, x in v.items()))
    else:
        lines.append("Kural olayı yok 👍")
    return "\n".join(lines)

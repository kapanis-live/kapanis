"""Shadow portfolio: what if every "🟢 ŞİMDİ AL" had been bought exactly as the bot said?

Every decision with karar "AL" whose code gate passed becomes a virtual trade: entry at the signal
close, the bot's stop and target judged on closes (backtest.outcome), size = the bot's first tranche
(USD for crypto, TL for BIST), fees and slippage deducted on both sides. Open ones are valued at the
latest close. The user's real trades from the same signals are shown next to it.
"""
import logging
import time

import backtest
import config
import positions

log = logging.getLogger(__name__)

REFRESH_SECONDS = 15 * 60


def signals(since: str) -> list[dict]:
    return [d for d in positions.load_decisions()
            if d["zaman"] >= since and d.get("karar") == "AL" and (d.get("kapi") or {}).get("ok")]


async def refresh(decisions: list[dict], limit: int = 20) -> None:
    """Store/refresh the close-based outcome on each decision (same format as web_sync)."""
    done = 0
    now = time.time()
    for d in decisions:
        s = d.get("sonuc")
        if s and (s["sonuc"] in ("hedef", "stop") or now - s.get("kontrol_ts", 0) < REFRESH_SECONDS):
            continue
        if done >= limit:
            break
        try:
            res = await backtest.evaluate_decision(d)
        except Exception as e:
            log.warning("Shadow outcome for decision %s failed: %s", d["id"], e)
            continue
        cikis = None if res["cikis"] is None else float(res["cikis"])
        d["sonuc"] = {"sonuc": res["sonuc"], "cikis": cikis, "mum": res["mum"],
                      "R": None if res["R"] is None else float(res["R"]), "kontrol_ts": now}
        positions.update_decision(d["id"], sonuc=d["sonuc"])
        done += 1


def trade(d: dict) -> dict | None:
    """Virtual P/L of one signal. Pure."""
    s = d.get("sonuc") or {}
    if s.get("cikis") is None or not d.get("kademe_usd"):
        return None
    bist = d.get("piyasa") == "BIST"
    side_cost = (config.BIST_FEE_PCT + config.BIST_SLIPPAGE_PCT if bist
                 else config.BACKTEST_FEE_PCT + config.BACKTEST_SLIPPAGE_PCT) / 100
    size = float(d["kademe_usd"])
    entry, exit_ = float(d["kapanis"]), float(s["cikis"])
    qty = (d.get("lot") or 0) if bist and d.get("lot") else size / entry
    gross = qty * (exit_ - entry)
    fees = qty * (entry + exit_) * side_cost
    return {"id": d["id"], "pair": d["pair"], "para": "TL" if bist else "USD", "sonuc": s["sonuc"],
            "giris": entry, "cikis": exit_, "net": round(gross - fees, 2), "tutar": size,
            "aldin": d.get("aksiyon") == "aldi"}


def summary(since: str) -> dict:
    out: dict[str, dict] = {}
    for d in signals(since):
        t = trade(d)
        if not t:
            continue
        o = out.setdefault(t["para"], {"sinyal": 0, "kapanan": 0, "kazanan": 0, "acik": 0, "net": 0.0,
                                       "acik_net": 0.0, "aldigin": 0, "kacan_net": 0.0, "islemler": []})
        o["sinyal"] += 1
        if t["sonuc"] in ("hedef", "stop"):
            o["kapanan"] += 1
            o["kazanan"] += t["net"] > 0
            o["net"] += t["net"]
        else:
            o["acik"] += 1
            o["acik_net"] += t["net"]
        if t["aldin"]:
            o["aldigin"] += 1
        else:
            o["kacan_net"] += t["net"]
        o["islemler"].append(t)
    real: dict[str, float] = {}
    for p in positions.load():
        if p.get("karar_id") and p["durum"] == "kapali" and (p.get("kapanis_zamani") or "") >= since:
            cur = p.get("para", "USD")
            real[cur] = real.get(cur, 0.0) + (p["kapanis_fiyat"] - p["giris"]) * p["adet"]
    for cur, o in out.items():
        o["gercek_net"] = round(real.get(cur, 0.0), 2)
        o["net"], o["acik_net"], o["kacan_net"] = round(o["net"], 2), round(o["acik_net"], 2), round(o["kacan_net"], 2)
    return out


def text(s: dict, days: int) -> str:
    if not s:
        return (f"👻 GÖLGE PORTFÖY (son {days} gün): henüz kapıdan geçmiş 🟢 ŞİMDİ AL sinyali yok.\n"
                "Bot AL verdikçe burada 'hepsini alsaydın' sonucu birikir.")
    lines = [f"👻 GÖLGE PORTFÖY — son {days} gün: botun her 🟢 ŞİMDİ AL'ını aynen alsaydın"]
    for cur, o in s.items():
        rate = f", isabet %{o['kazanan'] / o['kapanan'] * 100:.0f}" if o["kapanan"] else ""
        lines += [f"\n{'🇹🇷 BIST' if cur == 'TL' else '🪙 Kripto'}: {o['sinyal']} sinyal · {o['kapanan']} kapandı "
                  f"({o['kazanan']} kazanan{rate}) · {o['acik']} açık",
                  f"  Gölge net: {o['net']:+,.2f} {cur} kapanan + {o['acik_net']:+,.2f} {cur} açık (komisyon/kayma düşülmüş)",
                  f"  Senin bu sinyallerden gerçek sonucun: {o['gercek_net']:+,.2f} {cur} ({o['aldigin']} tanesini aldın)"]
        if o["sinyal"] > o["aldigin"]:
            lines.append(f"  Almadığın sinyallerin gölge sonucu: {o['kacan_net']:+,.2f} {cur}")
        for t in o["islemler"][-5:]:
            lines.append(f"  #{t['id']} {t['pair']} {t['giris']:g} → {t['cikis']:g} {t['sonuc']} {t['net']:+,.2f}")
    lines.append("\n10 kapanan sinyalden azsa sonuç tesadüf olabilir. Kapanışa göre ölçülür; gerçek dolum farklı olabilir.")
    return "\n".join(lines)

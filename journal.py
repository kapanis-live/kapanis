"""Trade journal: why a trade was opened and closed, and what the pattern says.

The reasons are stored on the position (pos["gunluk"]). The summary groups closed trades by buy reason
and sell reason and measures plan adherence from prices, not from the user's words:
- stop respected: exit at or above the stop (small slippage allowed)
- late stop: exit clearly below the stop (the stop was ignored)
- early exit out of fear: sold between stop and target with the reason "korku"
"""
import positions

BUY_REASONS = {"plan": "📈 Plan/kırılım", "dip": "🔄 Dipten dönüş", "haber": "📰 Haber",
               "tavsiye": "👥 Tavsiye/sosyal medya", "fomo": "😬 FOMO (kaçırma korkusu)", "diger": "✍️ Diğer"}
SELL_REASONS = {"hedef": "🎯 Hedef", "stop": "🛑 Stop", "sinyal": "📉 Çıkış sinyali", "korku": "😨 Korku",
                "para": "💸 Para lazım", "diger": "✍️ Diğer"}
MISTAKES = {"fomo": "FOMO ile alım", "tavsiye": "tavsiyeyle alım", "korku": "korkuyla erken satış",
            "gec_stop": "stopu geç uygulama", "stop_asagi": "stopu aşağı çekme denemesi",
            "sat_tut": "SAT kararına rağmen tutma", "stop_tut": "stop kırıldı, tutuldu"}
SLIPPAGE = 0.01  # exit up to 1% below the stop still counts as "stop respected"


def set_reason(pos_id: int, side: str, code: str, note: str | None = None):
    items = positions.load()
    for p in items:
        if p["id"] == pos_id:
            j = p.setdefault("gunluk", {})
            j[f"{side}_neden"] = code
            if note:
                j[f"{side}_not"] = note[:300]
    positions.save(items)


def adherence(p: dict) -> str | None:
    """How the exit relates to the plan (closed positions with a stop)."""
    if p["durum"] != "kapali" or p.get("stop") is None:
        return None
    price, stop, target = p["kapanis_fiyat"], p["stop"], p.get("hedef")
    if price < stop * (1 - SLIPPAGE):
        return "gec_stop"
    if price <= stop * (1 + SLIPPAGE):
        return "stop_uygulandi"
    if target is not None and price >= target:
        return "hedef"
    return "arada"


def summary(since: str) -> dict:
    """Closed trades since `since` grouped by reasons, plus the most frequent mistake."""
    closed = [p for p in positions.load() if p["durum"] == "kapali" and (p.get("kapanis_zamani") or "") >= since
              and positions.is_trade(p)]
    by_buy: dict[str, dict] = {}
    by_sell: dict[str, dict] = {}
    mistakes: dict[str, int] = {}
    plan = {"stop_uygulandi": 0, "gec_stop": 0, "hedef": 0, "arada": 0}
    for p in closed:
        pnl = (p["kapanis_fiyat"] - p["giris"]) * p["adet"]
        j = p.get("gunluk", {})
        for table, key in ((by_buy, j.get("al_neden", "yok")), (by_sell, j.get("sat_neden", "yok"))):
            row = table.setdefault(key, {"n": 0, "kazanan": 0, "pnl": {}})
            row["n"] += 1
            row["kazanan"] += pnl > 0
            row["pnl"][p.get("para", "USD")] = row["pnl"].get(p.get("para", "USD"), 0) + pnl
        a = adherence(p)
        if a:
            plan[a] += 1
        if a == "gec_stop":
            mistakes["gec_stop"] = mistakes.get("gec_stop", 0) + 1
        if j.get("al_neden") in ("fomo", "tavsiye") and pnl < 0:
            mistakes[j["al_neden"]] = mistakes.get(j["al_neden"], 0) + 1
        if j.get("sat_neden") == "korku" and a == "arada":
            mistakes["korku"] = mistakes.get("korku", 0) + 1
    for p in positions.load():
        for v in p.get("kural_ihlali", []):
            if v["zaman"] >= since and v.get("tur") in MISTAKES:
                mistakes[v["tur"]] = mistakes.get(v["tur"], 0) + 1
    top = max(mistakes.items(), key=lambda kv: kv[1]) if mistakes else None
    import benchmark  # after-sale moves (5 days after each sell)
    return {"satis_sonrasi": benchmark.after_sale_summary(since),
            "islem": len(closed), "alis_nedeni": by_buy, "satis_nedeni": by_sell, "plan_uyumu": plan,
            "hatalar": mistakes, "en_sik_hata": {"hata": MISTAKES[top[0]], "sayi": top[1]} if top else None}


def text(s: dict) -> str:
    if not s["islem"]:
        return "📓 Günlük: bu dönemde kapanan işlem yok."

    def rows(table: dict, labels: dict) -> list[str]:
        out = []
        for k, r in sorted(table.items(), key=lambda kv: -kv[1]["n"]):
            money = ", ".join(f"{v:+,.2f} {c}" for c, v in r["pnl"].items())
            out.append(f"  {labels.get(k, 'neden yazılmadı')}: {r['n']} işlem, {r['kazanan']} kazanan, {money}")
        return out

    p = s["plan_uyumu"]
    lines = [f"📓 İŞLEM GÜNLÜĞÜ — {s['islem']} kapanan işlem", "Neden aldın?", *rows(s["alis_nedeni"], BUY_REASONS),
             "Neden sattın?", *rows(s["satis_nedeni"], SELL_REASONS),
             f"Plana uyum: stop uygulandı {p['stop_uygulandi']} · hedefte satış {p['hedef']} · arada satış {p['arada']}"
             + (f" · ⚠️ stop geç uygulandı {p['gec_stop']}" if p["gec_stop"] else "")]
    a = s.get("satis_sonrasi") or {}
    if a.get("n"):
        lines.append(f"Satıştan 5 gün sonra: ortalama %{a['ort_5g']:+.2f} · erken satış {a['erken']} · iyi çıkış {a['iyi']} "
                     f"({a['n']} satış)")
    if s["en_sik_hata"]:
        lines.append(f"En sık hata: {s['en_sik_hata']['hata']} ({s['en_sik_hata']['sayi']} kez). Bu hafta buna dikkat.")
    else:
        lines.append("Tekrarlayan hata yok 👍")
    return "\n".join(lines)

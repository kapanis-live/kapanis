""""Şu an alabileceğim tetiklenen bir hisse ya da coin var mı?" — one answer across both markets.

Everything is computed in code from live (crypto) / ~15-min delayed (BIST) data:
1. General blockers per market: discipline shield, first-tranche room, BTC gate + macro regime + sentiment
   (crypto), BIST 100 gate + TR data releases + budget (BIST).
2. Every saved plan, classified against the last CLOSED candle (15m crypto, daily BIST) and the live price:
   triggered+confirmed / triggered, waiting for confirmation / near the trigger / waiting / broken.
   Triggered plans are run through the same decision gate as a signal, with the live price as entry.
3. Recent ŞİMDİ AL signals the user hasn't acted on: still valid only if the price hasn't run away
   (more than CHASE_PCT above the signal close) and is above the stop.
4. Crypto scanner on the last closed 15m candle (new breakout candidates; they still need confirmation).
The verdict per item: ALINABİLİR (every rule passes now), KURAL EKSİK (triggered but a rule fails),
YAKLAŞIYOR, KAÇTI (don't chase). Nothing is bought; the bot never trades.
"""
import logging
import time
from datetime import datetime, timedelta

import httpx

import alerts_store
import bist
import bist_signals
import config
import conversation_store as store
import discipline
import gate
import macro
import market
import positions
import scanner
import sentiment
import us
import us_signals

log = logging.getLogger(__name__)

CHASE_PCT = {"KRIPTO": 1.5, "BIST": 3.0, "ABD": 3.0}   # price this far above the signal close = it ran away
SIGNAL_HOURS = {"KRIPTO": 6, "BIST": 72, "ABD": 72}   # how long an unacted ŞİMDİ AL is still worth showing
NEAR_ATR = 0.5
MARKET_ORDER = {"KRIPTO": 0, "ABD": 1, "BIST": 2}   # USDT and USD rows come first, TL rows last
BIST_ROWS = 3                                        # TL rows listed per group; the rest are only counted


def _nan(x) -> bool:
    return x is None or x != x


def _classify(tetik, iptal, hedef, prev_close, close, atr, pending: bool) -> str:
    """Plan state from the last two CLOSED candles. Pure."""
    if iptal is not None and close < iptal:
        return "bozuldu"
    if hedef is not None and close >= hedef:
        return "hedefte"
    if tetik is None:
        return "bekliyor"
    if close > tetik and (prev_close > tetik or pending):
        return "tetik_teyitli"
    if close > tetik:
        return "tetik_teyit_bekliyor"
    if atr and 0 < tetik - close <= NEAR_ATR * atr:
        return "yaklasiyor"
    return "bekliyor"


async def _crypto_blockers(client) -> dict:
    out = {}
    ok, why = discipline.check("KRIPTO")
    out["disiplin"] = None if ok else why
    try:
        btc = market.add_indicators(await market.fetch_klines(client, "BTC" + config.QUOTE, "15m"))
        b = btc.iloc[-1]
        out["btc_kapi"] = "AÇIK" if b.close > b.sma50 else "KAPALI"
    except Exception as e:
        out["btc_kapi"] = f"alınamadı ({str(e)[:40]})"
    try:
        reg = (await macro.summary()).get("rejim", {})
        out["makro"] = f"{reg.get('skor', '?')} ({reg.get('etiket', 'doğrulanamadı')})"
        out["risk_off"] = "skor" not in reg or reg["skor"] <= -2
    except Exception:
        out["makro"], out["risk_off"] = "doğrulanamadı", True
    try:
        s = await sentiment.summary()
        f = s.get("korku_acgozluluk", {})
        out["duygu"] = f"{f['deger']} ({f['etiket']})" if "deger" in f else "alınamadı"
        out["acgozluluk"] = sentiment.greed_note(s)
    except Exception:
        out["duygu"], out["acgozluluk"] = "alınamadı", None
    usd, notes = positions.tranche_usd("?", out["risk_off"], True, 0.0, greed=out["acgozluluk"])
    out["kademe"] = usd
    out["kademe_not"] = "; ".join(notes)
    try:
        soon = [e for e in macro.upcoming(await macro.calendar(), 2) if e["kalan_saat"] >= 0]
        out["veri"] = f"{soon[0]['olay']} {soon[0]['kalan_saat']:g} saat sonra" if soon else None
    except Exception:
        out["veri"] = None
    return out


async def _bist_blockers(client) -> dict:
    out = {"seans": "açık" if bist.session_open() else "kapalı", "gecikme_dk": 15}
    ok, why = discipline.check("BIST")
    out["disiplin"] = None if ok else why
    try:
        g = await bist.index_gate(client)
        out["endeks"] = g["durum"]
        out["usdtry_baski"] = bool(g.get("usdtry_baski"))
    except Exception as e:
        out["endeks"] = f"alınamadı ({str(e)[:40]})"
    ev = bist.tr_event_risk()
    out["tr_veri"] = f"{ev['olay']} {ev['kalan_saat']:+g} saat" if ev else None
    out["butce"] = bist.budget_tl()
    tl, notes = bist.tranche_tl(out.get("endeks") != "AÇIK", True, bist_signals.open_bist_tl())
    out["kademe_tl"] = tl
    out["kademe_not"] = "; ".join(notes)
    return out


def _gate_summary(g: dict) -> dict:
    return {"ok": bool(g["ok"]), "kalan": g.get("kalan", []), "rr": g.get("rr"),
            "maddeler": [m for m in g.get("maddeler", []) if m.startswith("❌")][:4]}


async def _crypto_plans(client, blockers: dict) -> list[dict]:
    items = []
    for coin, p in store.load_state()["planlar"].items():
        if coin.endswith(".IS") or p.get("pozisyon"):
            continue
        tetik, iptal, hedef = p.get("tetik"), p.get("iptal"), p.get("hedef")
        try:
            df = market.add_indicators(await market.fetch_klines(client, coin + config.QUOTE, "15m"))
            price = await market.last_price(client, coin + config.QUOTE)
        except Exception as e:
            items.append({"piyasa": "KRIPTO", "kod": coin, "durum": "veri_yok", "not": str(e)[:60]})
            continue
        prev, last = df.iloc[-2], df.iloc[-1]
        atr = None if _nan(last.atr14) else float(last.atr14)
        state = _classify(tetik, iptal, hedef, float(prev.close), float(last.close), atr, bool(p.get("bekleyen_teyit")))
        row = {"piyasa": "KRIPTO", "kod": coin, "durum": state, "fiyat": price, "kapanis": float(last.close),
               "tetik": tetik, "iptal": iptal, "hedef": hedef, "otomatik": bool(p.get("otomatik")),
               "uzaklik_yuzde": round((tetik / price - 1) * 100, 2) if tetik else None}
        if state in ("tetik_teyitli", "tetik_teyit_bekliyor") and iptal is not None:
            trigger_bar = last if float(prev.close) <= (tetik or 0) else prev
            avg = trigger_bar.vol_avg20
            vol_ok = bool(not _nan(avg) and avg and trigger_bar.volume > avg)
            g = await gate.evaluate(client, pair=f"{coin}/{config.QUOTE}", direction="ABOVE", entry=price,
                                    iptal=iptal, hedef=hedef, timeframe="15m", candle=None, volume_ok=vol_ok,
                                    volume_ratio=float(trigger_bar.volume / avg) if not _nan(avg) and avg else None)
            row["kapi"] = _gate_summary(g)
            row["kademe_usd"] = g.get("kademe_usd")
            if tetik and price > tetik * (1 + CHASE_PCT["KRIPTO"] / 100):
                row["durum"] = "kacti"
        items.append(row)
    return items


async def _bist_plans(client) -> list[dict]:
    items = []
    for sym, p in store.load_state()["planlar"].items():
        if not sym.endswith(".IS") or p.get("pozisyon"):
            continue
        tetik, iptal, hedef = p.get("tetik"), p.get("iptal"), p.get("hedef")
        try:
            d = market.add_indicators(await bist.fetch(client, sym, "1d"))
            price = await bist.last_price(client, sym)
        except Exception as e:
            items.append({"piyasa": "BIST", "kod": bist.ticker(sym), "durum": "veri_yok", "not": str(e)[:60]})
            continue
        prev, last = d.iloc[-2], d.iloc[-1]
        atr = None if _nan(last.atr14) else float(last.atr14)
        state = _classify(tetik, iptal, hedef, float(prev.close), float(last.close), atr, False)
        if p.get("sinyal_verildi"):
            state = "tetik_teyitli"
        elif state == "bekliyor" and tetik and price > tetik:
            state = "gun_ici_ustunde"  # above the trigger intraday; the daily close decides after 18:30
        row = {"piyasa": "BIST", "kod": bist.ticker(sym), "durum": state, "fiyat": price, "kapanis": float(last.close),
               "tetik": tetik, "iptal": iptal, "hedef": hedef, "otomatik": bool(p.get("bist_aday")),
               "uzaklik_yuzde": round((tetik / price - 1) * 100, 2) if tetik else None}
        if state in ("tetik_teyitli", "tetik_teyit_bekliyor", "gun_ici_ustunde") and iptal is not None and price > iptal:
            g = await bist_signals.evaluate(client, symbol=sym, entry=price, iptal=iptal, hedef=hedef, level=tetik,
                                            hour_bar=None, bar_tf="1d")
            row["kapi"] = _gate_summary(g)
            row["adet"] = g.get("lot")
            if tetik and price > tetik * (1 + CHASE_PCT["BIST"] / 100):
                row["durum"] = "kacti"
        items.append(row)
    return items


async def _us_plans(client) -> list[dict]:
    items = []
    for key, p in store.load_state()["planlar"].items():
        if not key.endswith(".US") or p.get("pozisyon"):
            continue
        tetik, iptal, hedef = p.get("tetik"), p.get("iptal"), p.get("hedef")
        try:
            d = market.add_indicators(await us.fetch(client, key, "1d"))
            price = await us.last_price(client, key)
        except Exception as e:
            items.append({"piyasa": "ABD", "kod": us.ticker(key), "durum": "veri_yok", "not": str(e)[:60]})
            continue
        prev, last = d.iloc[-2], d.iloc[-1]
        atr = None if _nan(last.atr14) else float(last.atr14)
        state = _classify(tetik, iptal, hedef, float(prev.close), float(last.close), atr, bool(p.get("bekleyen_teyit")))
        if p.get("sinyal_verildi"):
            state = "tetik_teyitli"
        elif state == "bekliyor" and tetik and price > tetik:
            state = "gun_ici_ustunde"
        row = {"piyasa": "ABD", "kod": us.ticker(key), "durum": state, "fiyat": price, "kapanis": float(last.close),
               "tetik": tetik, "iptal": iptal, "hedef": hedef,
               "uzaklik_yuzde": round((tetik / price - 1) * 100, 2) if tetik else None}
        if state in ("tetik_teyitli", "tetik_teyit_bekliyor", "gun_ici_ustunde") and iptal is not None and price > iptal:
            g = await us_signals.evaluate(client, t=key, entry=price, iptal=iptal, hedef=hedef)
            row["kapi"] = _gate_summary(g)
            row["kademe_usd"] = g.get("kademe_usd")
            if tetik and price > tetik * 1.03:
                row["durum"] = "kacti"
        items.append(row)
    return items


async def _recent_signals(client) -> list[dict]:
    """ŞİMDİ AL signals not acted on yet, still inside their window."""
    out = []
    now = alerts_store.now_tr()
    planned = set(store.load_state()["planlar"])
    for d in reversed(positions.load_decisions()[-40:]):
        mkt = d.get("piyasa") or "KRIPTO"
        if d.get("karar") != "AL" or not (d.get("kapi") or {}).get("ok") or d.get("aksiyon"):
            continue
        if datetime.fromisoformat(d["zaman"]) < now - timedelta(hours=SIGNAL_HOURS[mkt]):
            continue
        code = bist.ticker(d["symbol"]) if mkt == "BIST" else us.ticker(d["symbol"]) if mkt == "ABD" else d["pair"].split("/")[0]
        if (d["symbol"] if mkt in ("BIST", "ABD") else code) in planned:
            continue  # the plan row already covers it
        try:
            price = await (bist.last_price(client, d["symbol"]) if mkt == "BIST" else us.last_price(client, d["symbol"])
                           if mkt == "ABD" else market.last_price(client, d["symbol"]))
        except Exception:
            continue
        entry = float(d["kapanis"])
        state = ("bozuldu" if d.get("iptal") is not None and price < d["iptal"] else
                 "kacti" if price > entry * (1 + CHASE_PCT[mkt] / 100) else "sinyal_gecerli")
        out.append({"piyasa": mkt, "kod": code, "durum": state, "fiyat": price, "sinyal_kapanis": entry,
                    "iptal": d.get("iptal"), "hedef": d.get("hedef"), "karar_id": d["id"],
                    "yas_saat": round((now - datetime.fromisoformat(d["zaman"])).total_seconds() / 3600, 1),
                    "konsey": {m: v["karar"] for m, v in (d.get("konsey") or {}).items()}})
    return out


async def collect() -> dict:
    t0 = time.time()
    async with httpx.AsyncClient() as client:
        kb = await _crypto_blockers(client)
        bb = await _bist_blockers(client)
        crypto = await _crypto_plans(client, kb)
        stocks = await _bist_plans(client)
        us_items = await _us_plans(client)
        signals = await _recent_signals(client)
    try:
        candidates = [{"piyasa": "KRIPTO", "kod": c["coin"], "durum": "yeni_aday", "fiyat": c["kapanis"],
                       "tetik": c["tetik"], "iptal": c["iptal"], "hedef": c["hedef"], "hacim_orani": c["hacim_orani"]}
                      for c in await scanner.scan()]
    except Exception as e:
        log.warning("Scanner in opportunity check failed: %s", e)
        candidates = []
    items = sorted(signals + crypto + stocks + us_items + candidates, key=lambda i: MARKET_ORDER.get(i["piyasa"], 0))
    buyable = [i for i in items if (i["durum"] == "sinyal_gecerli") or
               (i["durum"] in ("tetik_teyitli", "gun_ici_ustunde") and (i.get("kapi") or {}).get("ok"))]
    return {"zaman": alerts_store.now_tr().isoformat(), "sure_sn": round(time.time() - t0, 1),
            "kripto_engeller": kb, "bist_engeller": bb, "kalemler": items, "alinabilir": buyable}


FLAG = {"BIST": "🇹🇷", "ABD": "🇺🇸", "KRIPTO": "🪙"}
LABELS = {"sinyal_gecerli": "🟢 AL sinyali hâlâ geçerli", "tetik_teyitli": "🔔 tetik + teyit kapanışla geldi",
          "gun_ici_ustunde": "🔔 gün içinde tetiğin üstünde (günlük kapanış 18:30'da kesinleşir)",
          "tetik_teyit_bekliyor": "⏳ tetik kapandı, teyit mumu bekleniyor", "yaklasiyor": "👀 tetiğe yaklaşıyor",
          "kacti": "🏃 fiyat kaçtı — kovalama", "yeni_aday": "🆕 tarayıcı adayı (teyit bekliyor)",
          "bozuldu": "❌ iptal altında — plan bozuk", "hedefte": "🎯 hedefte — geç kalındı",
          "bekliyor": "⏸ tetik bekleniyor", "veri_yok": "veri alınamadı"}


def _g(x) -> str:
    return "—" if x is None else f"{x:.6g}"


def _front(rows: list[dict], limit: int) -> tuple[list[dict], int]:
    """Rows to list (USDT/USD first, at most BIST_ROWS TL rows) and how many TL rows were left out."""
    rows = sorted(rows, key=lambda i: MARKET_ORDER.get(i["piyasa"], 0))
    tl = [i for i in rows if i["piyasa"] == "BIST"]
    shown = ([i for i in rows if i["piyasa"] != "BIST"] + tl[:BIST_ROWS])[:limit]
    return shown, len(tl) - sum(i["piyasa"] == "BIST" for i in shown)


def text(res: dict) -> str:
    buy = sorted(res["alinabilir"], key=lambda i: MARKET_ORDER.get(i["piyasa"], 0))
    kb, bb = res["kripto_engeller"], res["bist_engeller"]
    lines = [f"🔎 ŞU AN ALINABİLECEK: {len(buy)} " + ("✅" if buy else "— şu an kurallara uyan giriş yok"),
             f"({datetime.fromisoformat(res['zaman']).strftime('%H:%M')} · {res['sure_sn']:g} sn · kripto canlı, BIST ~15 dk gecikmeli)"]
    for i in buy:
        unit = "TL" if i["piyasa"] == "BIST" else "USD" if i["piyasa"] == "ABD" else "USDT"
        size = (f" · ilk kademe {i['adet']} adet" if i.get("adet") else f" · ilk kademe {i['kademe_usd']:g} USD" if i.get("kademe_usd") else "")
        votes = i.get("konsey") or {}
        council = f" · konsey {sum(v == 'AL' for v in votes.values())}/{len(votes)} AL" if votes else ""
        lines.append(f"{FLAG.get(i['piyasa'], '🪙')} {i['kod']} {_g(i['fiyat'])} {unit} — {LABELS[i['durum']]}"
                     f" · iptal {_g(i.get('iptal'))} · hedef {_g(i.get('hedef'))}{size}{council}")
    groups = [("🔔 Tetiklendi ama kural eksik", [i for i in res["kalemler"] if i not in buy and i.get("kapi") and not i["kapi"]["ok"]
                                               and i["durum"] not in ("kacti", "bozuldu")]),
              ("🏃 Kaçtı / geç kalındı", [i for i in res["kalemler"] if i["durum"] in ("kacti", "hedefte")]),
              ("👀 Yaklaşıyor / teyit bekleniyor", [i for i in res["kalemler"] if i["durum"] in ("yaklasiyor", "tetik_teyit_bekliyor", "yeni_aday")
                                                   and not (i.get("kapi") and i["kapi"]["ok"])])]
    for title, rows in groups:
        if not rows:
            continue
        lines += ["", title]
        shown, hidden = _front(rows, 8)
        for i in shown:
            why = ""
            if i.get("kapi") and not i["kapi"]["ok"]:
                why = " · eksik: " + ", ".join(i["kapi"]["kalan"][:4])
            dist = f" · tetiğe %{i['uzaklik_yuzde']:+.2f}" if i.get("uzaklik_yuzde") is not None and i["durum"] == "yaklasiyor" else ""
            lines.append(f"{FLAG.get(i['piyasa'], '🪙')} {i['kod']} {_g(i.get('fiyat'))} — {LABELS[i['durum']]}{dist}{why}")
        if hidden:
            lines.append(f"🇹🇷 +{hidden} BIST (TL) kalemi daha")
    waiting, hidden = _front([i for i in res["kalemler"] if i["durum"] == "bekliyor"], 10)
    if waiting:
        lines += ["", "⏸ Bekleyen planlar: " + ", ".join(
            f"{i['kod']} (tetiğe %{i['uzaklik_yuzde']:+.1f})" if i.get("uzaklik_yuzde") is not None else i["kod"] for i in waiting)
            + (f" · +{hidden} BIST (TL)" if hidden else "")]
    k_block = [f"BTC kapı {kb['btc_kapi']}", f"makro {kb['makro']}", f"duygu {kb['duygu']}",
               f"kademe {kb['kademe']:g} USD" + (f" ({kb['kademe_not']})" if kb["kademe_not"] else "")]
    if kb.get("veri"):
        k_block.append(f"⚠️ {kb['veri']}")
    if kb.get("disiplin"):
        k_block.append(f"⛔ {kb['disiplin']}")
    b_block = [f"seans {bb['seans']}", f"BIST 100 kapı {bb['endeks']}",
               f"bütçe {bb['butce']:,} TL" if bb.get("butce") else "bütçe girilmedi (/bist butce)",
               f"kademe {bb['kademe_tl']:,.0f} TL" + (f" ({bb['kademe_not']})" if bb["kademe_not"] else "")]
    if bb.get("usdtry_baski"):
        b_block.append("⚠️ USD/TRY baskısı")
    if bb.get("tr_veri"):
        b_block.append(f"⚠️ {bb['tr_veri']}")
    if bb.get("disiplin"):
        b_block.append(f"⛔ {bb['disiplin']}")
    lines += ["", "🪙 Kripto ortamı: " + " · ".join(k_block), "🇹🇷 BIST ortamı: " + " · ".join(b_block)]
    if not res["kalemler"]:
        lines.append("\nTakipte plan yok. Plan için: /plan ekle BTC THYAO → 🎯 plan kur, ya da /tara, /guc.")
    lines.append("\nBot işlem yapmaz: 'alınabilir' = kapanış teyidi geldi ve kod kapısındaki bütün kurallar şu an geçiyor. "
                 "Emirden önce fiyatı kontrol et.")
    return "\n".join(lines)

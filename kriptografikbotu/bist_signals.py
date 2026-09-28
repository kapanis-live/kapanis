"""BIST strategy: daily breakout setup + 1-hour entry confirmation + BIST decision gate.

Flow
1. Daily scan (after the 18:30 final daily close): a BIST 30 stock CLOSES above a daily/weekly
   resistance zone with volume above its 20-day average, above its daily SMA50, stronger than the
   BIST 100 over 20 days, and not near the +10% ceiling. It becomes an automatic plan ("aday").
2. Next session(s): when a 1-hour bar CLOSES above the level, the BIST gate checks every rule.
   Pass -> "🟢 ŞİMDİ AL (BIST)" with whole lots. Fail -> 🟡 with the failed rules, plan dropped.
3. Manual plans from /bist analysis (keys like "THYAO.IS") follow the crypto pattern on 1h bars:
   close above tetik -> next 1h close holds teyit -> gate.
Everything numeric is computed here; DeepSeek only comments on a passed signal.
"""
import logging
import time
from datetime import datetime, timezone

import httpx

import alerts_store
import bist
import config
import conversation_store as store
import discipline
import market
import positions

log = logging.getLogger(__name__)

CANDIDATE_TTL_DAYS = 7        # an unconfirmed daily candidate expires after this many calendar days
FRESH_HOURLY_SECONDS = 50 * 60  # 1h bar must have closed (plus data delay) within this window


def _check(rule, passed, detail, blocking=True):
    return {"kural": rule, "durum": "gecti" if passed else ("kaldi" if blocking else "uyari"),
            "detay": detail, "engelleyici": blocking}


def _nan(x):
    return x is None or x != x


def open_bist_tl() -> float:
    return sum(p["miktar_usd"] for p in positions.open_positions() if p.get("piyasa") == "BIST" and positions.is_trade(p))


def is_bist_plan(key: str) -> bool:
    return key.upper().endswith(".IS")


def discard_candidate(symbol: str):
    """A declined automatic BIST candidate must stop appearing as an active plan."""
    state = store.load_state()
    plan = state["planlar"].get(symbol)
    if plan and plan.get("bist_aday") and not plan.get("pozisyon"):
        del state["planlar"][symbol]
        store.save_state(state)


def _relative_strength(daily, index) -> float | None:
    if len(daily) < 21 or len(index) < 21:
        return None
    return ((daily.close.iloc[-1] / daily.close.iloc[-21]) -
            (index.close.iloc[-1] / index.close.iloc[-21])) * 100


def _setup(d, w, idx) -> dict | None:
    """Two daily setups; all levels come from closed bars available at scan time."""
    if len(d) < 60 or len(idx) < 21:
        return None
    prev, last = d.iloc[-2], d.iloc[-1]
    atr = float(last.atr14)
    rs = _relative_strength(d, idx)
    if _nan(atr) or atr <= 0 or rs is None or rs <= 0 or _nan(last.sma50) or last.close <= last.sma50:
        return None
    change = (last.close / prev.close - 1) * 100
    if change > config.BIST_MAX_DAILY_CHANGE_PCT:
        return None
    if not w.empty and "sma20" in w and len(w) >= 20:
        wl = w.iloc[-1]  # medium/long-term: only buy when the weekly trend points up
        if _nan(wl.sma20) or wl.close <= wl.sma20:
            return None
    zones = market.sr_zones(d.iloc[:-1], w, float(prev.close), atr, top=5)
    resistance = zones["direncler"]
    volume_ratio = float(last.volume / last.vol_avg20) if not _nan(last.vol_avg20) and last.vol_avg20 > 0 else 0

    setup = None
    if resistance and prev.close <= resistance[0]["ust"] < last.close and volume_ratio >= 1.2:
        zone = resistance[0]
        setup = {"strateji": "Hacimli direnç kırılımı", "tetik": zone["ust"],
                 "iptal": min(float(zone["alt"]), float(last.low)) - 0.1 * atr,
                 "dokunma": zone["dokunma"], "hacim_orani": volume_ratio,
                 "not": f"Günlük direnç {zone['alt']:.4g}–{zone['ust']:.4g} ({zone['dokunma']} dokunma) hacimle kırıldı"}
    elif (not _nan(prev.sma20) and not _nan(prev.sma50) and prev.sma20 > prev.sma50
          and prev.low <= prev.sma20 + 0.25 * atr and prev.close >= prev.sma50
          and last.close > prev.high and last.close > last.sma20 and volume_ratio >= 0.8):
        setup = {"strateji": "Trend içi geri çekilme", "tetik": float(last.high),
                 "iptal": float(prev.low) - 0.1 * atr, "dokunma": None,
                 "hacim_orani": volume_ratio,
                 "not": f"SMA20'ye geri çekilme sonrası günlük kapanış önceki tepeyi geçti"}
    if setup is None:
        return None

    entry = float(last.close)
    # Medium-term stop: below the setup low, and at least 1.5 daily ATR away so normal swings don't hit it.
    stop = min(setup["iptal"], entry - 1.5 * atr)
    if not stop < entry:
        return None
    # Target: the first resistance at least BIST_MIN_TARGET_PCT above entry. Without one, an explicit
    # projection (that percentage or 3 ATR), never presented as a known price level.
    floor = max(entry, setup["tetik"]) * (1 + config.BIST_MIN_TARGET_PCT / 100)
    above = [z for z in resistance if z["orta"] >= floor]
    target = float(above[0]["orta"]) if above else max(floor, max(entry, setup["tetik"]) + 3 * atr)
    roundtrip = entry * 2 * (config.BIST_FEE_PCT + config.BIST_SLIPPAGE_PCT) / 100
    if (target - entry - roundtrip) / (entry - stop + roundtrip) < config.BIST_MIN_RR:
        return None
    setup.update(iptal=round(stop, 4), hedef=round(target, 4),
                 hedef_turu="direnç" if above else f"projeksiyon (%{config.BIST_MIN_TARGET_PCT:g} / 3×ATR)",
                 kapanis=entry, degisim=change, rs=rs)
    return setup


async def evaluate(client: httpx.AsyncClient, *, symbol: str, entry: float, iptal: float | None,
                   hedef: float | None, level: float | None, hour_bar=None, volume_ok: bool | None = None,
                   bar_tf: str = "1h") -> dict:
    """The BIST decision gate. bar_tf "1d": the signal is a final daily close (medium/long-term mode)."""
    checks = []
    tick = bist.ticker(symbol)
    daily = market.add_indicators(await bist.fetch(client, symbol, "1d"))
    d_last = daily.iloc[-1]
    atr_d = None if _nan(d_last.atr14) else float(d_last.atr14)

    daily_mode = bar_tf == "1d"
    if hour_bar is not None and daily_mode:
        bar_day = datetime.fromtimestamp(int(hour_bar.open_time) / 1000, bist.TR).date()
        checks.append(_check("mum güncelliği", bar_day == bist.now_tr().date(),
                             f"günlük kapanış {bar_day.strftime('%d.%m')} (bugünün kesin kapanışı olmalı)"))
    elif hour_bar is not None:
        age = time.time() - int(hour_bar.close_time) / 1000
        checks.append(_check("mum güncelliği", 0 <= age <= FRESH_HOURLY_SECONDS + bist.DATA_DELAY_MIN * 60,
                             f"1s mum {max(age, 0) / 60:.0f} dk önce kapandı (veri ~15 dk gecikmeli)"))
    if not daily_mode:
        checks.append(_check("seans", bist.session_open(), "Alım kararı yalnız açık seansta verilir"))
    try:
        wk = market.add_indicators(await bist.fetch(client, symbol, "1wk"))
        wl = wk.iloc[-1]
        up = not _nan(wl.sma20) and wl.close > wl.sma20
        checks.append(_check("haftalık trend", up, f"haftalık kapanış {wl.close:.4g}, haftalık SMA20 {wl.sma20:.4g}"
                             + ("" if up else " — orta/uzun vade için haftalık trend yukarı olmalı")))
        import structure
        st = structure.stage(wk)
        if st:
            checks.append(_check("stage", st["stage"] in (1, 2), st["aciklama"], blocking=False))
    except Exception as e:
        checks.append(_check("haftalık trend", False, f"haftalık veri alınamadı, doğrulanamadı ({e})"))
    checks.append(_check("günlük trend", not _nan(d_last.sma50) and d_last.close > d_last.sma50,
                         f"günlük kapanış {d_last.close:.4g}, SMA50 {d_last.sma50:.4g}"))
    try:
        index_daily = market.add_indicators(await bist.fetch(client, bist.INDEX, "1d"))
        rs = _relative_strength(daily, index_daily)
        stock_day = datetime.fromtimestamp(int(d_last.open_time) / 1000, bist.TR).date()
        index_day = datetime.fromtimestamp(int(index_daily.iloc[-1].open_time) / 1000, bist.TR).date()
        same_day = stock_day == index_day
        checks.append(_check("göreceli güç", rs is not None and rs > 0 and same_day,
                             f"20g BIST100 farkı {rs:+.2f} puan" if rs is not None and same_day else "endeks/hisse günlük verisi eşleşmiyor"))
    except Exception as e:
        checks.append(_check("göreceli güç", False, f"doğrulanamadı ({e})"))

    rr = None
    if iptal is None or hedef is None or entry <= iptal:
        checks.append(_check("R/R", False, "iptal/hedef yok ya da fiyat iptalin altında"))
    else:
        roundtrip = entry * 2 * (config.BIST_FEE_PCT + config.BIST_SLIPPAGE_PCT) / 100
        rr = round((hedef - entry - roundtrip) / (entry - iptal + roundtrip), 2)
        checks.append(_check("net R/R", rr >= config.BIST_MIN_RR,
                             f"maliyet sonrası R/R {rr:.2f}, eşik {config.BIST_MIN_RR:g} (orta/uzun vade)"))
        if atr_d:
            wide = entry - iptal >= 0.5 * atr_d
            checks.append(_check("ATR stop", wide, f"stop mesafesi {entry - iptal:.4g} vs 0.5×günlük ATR {0.5 * atr_d:.4g}"
                                 + ("" if wide else " — iğneye takılır, stopu genişlet")))

    if volume_ok is None:
        volume_ok = not _nan(d_last.vol_avg20) and d_last.volume > d_last.vol_avg20
    checks.append(_check("hacim", bool(volume_ok), "kırılım günü hacmi 20 günlük ortalamanın " +
                         ("üstünde" if volume_ok else "altında / doğrulanamadı")))

    # Chasing guards: today's move vs. the +10% daily limit, and distance above the broken level.
    # In daily mode the signal bar is the last daily bar itself, so compare with the one before it.
    prev_close = float(daily.close.iloc[-2] if daily_mode and len(daily) > 1 else daily.close.iloc[-1])
    today_chg = (entry / prev_close - 1) * 100
    checks.append(_check("tavan", today_chg <= config.BIST_MAX_DAILY_CHANGE_PCT,
                         f"bugün %{today_chg:+.1f} (tavan %10'a yakın hisse kovalanmaz)"))
    if level is not None and atr_d:
        stretch = (entry - level) / atr_d
        checks.append(_check("boşluk", stretch <= 1.0, f"fiyat seviyenin {stretch:.2f}×ATR üstünde"
                             + ("" if stretch <= 1.0 else " — boşluklu açılış, kovalama yok")))

    try:
        g = await bist.index_gate(client)
        state = g["durum"]
        checks.append(_check("BIST 100 kapı", state != "KAPALI",
                             f"XU100 {g['xu100_kapanis']} — {state} (SMA50 {g['sma50']}, SMA200 {g['sma200']})"))
        risk_off = state != "AÇIK"
        if g.get("usdtry_baski"):
            risk_off = True
            checks.append(_check("USD/TRY", False, f"kur 5 günde %{g['usdtry_5g_yuzde']:+.2f}: TL baskı altında, "
                                 "dolar bazlı getiri yanıltıcı olabilir", blocking=False))
    except Exception as e:
        risk_off = True
        checks.append(_check("BIST 100 kapı", False, f"endeks verisi alınamadı, doğrulanamadı ({e})"))

    ev = bist.tr_event_risk()
    checks.append(_check("TR veri", ev is None,
                         "2 saat içinde TCMB/TÜİK verisi yok" if ev is None else
                         f"{ev['olay']} {ev['kalan_saat']:+g} saat — veri öncesi/hemen sonrası yeni giriş yok"))

    d_ok, d_detail = discipline.check("BIST")
    checks.append(_check("disiplin", d_ok, d_detail))

    tl, notes = bist.tranche_tl(risk_off, bool(volume_ok), open_bist_tl())
    lots = bist.lots_for(tl, entry)
    if iptal is not None and entry > iptal:
        risk_per_lot = entry - iptal + entry * 2 * (config.BIST_FEE_PCT + config.BIST_SLIPPAGE_PCT) / 100
        risk_room = (bist.budget_tl() or 0) * config.BIST_MAX_RISK_PCT / 100
        lots = min(lots, int(risk_room // risk_per_lot))
        checks.append(_check("işlem riski", lots >= 1,
                             f"stop ve maliyetle en fazla {risk_room:g} TL risk, {lots} adet"))
    checks.append(_check("bütçe/adet", lots >= 1,
                         f"{lots} adet × {entry:g} = {lots * entry:,.0f} TL" + (f" ({'; '.join(notes)})" if notes else "")
                         if lots >= 1 else ("; ".join(notes) or f"1 adet ({entry:g} TL) kademeden pahalı") + ", pas"))

    ok = all(c["durum"] != "kaldi" for c in checks)
    icon = {"gecti": "✅", "kaldi": "❌", "uyari": "⚠️"}
    return {
        "ok": ok, "piyasa": "BIST", "sembol": bist.yahoo_symbol(symbol), "hisse": tick,
        "giris": entry, "iptal": iptal, "hedef": hedef, "rr": rr, "butce_tl": bist.budget_tl(),
        "kademe_tl": round(lots * entry, 2), "lot": lots,
        "kademe_notlari": notes, "risk_off": risk_off, "hacim_ok": bool(volume_ok), "kurallar": checks,
        "gostergeler": {key: market._num(d_last[key]) for key in
                        ("close", "sma20", "sma50", "sma200", "rsi14", "volume", "vol_avg20", "atr14")},
        "maddeler": [f"{icon[c['durum']]} {c['kural']}: {c['detay']}" for c in checks],
        "kalan": [c["kural"] for c in checks if c["durum"] == "kaldi"],
        "mum": None if hour_bar is None else {
            "acilis_utc": market._ts(hour_bar.open_time), "zaman_dilimi": bar_tf, "kapanis": float(hour_bar.close)},
        "mum_ms": None if hour_bar is None else int(hour_bar.open_time),
    }


async def daily_scan() -> list[dict]:
    """Find daily breakout candidates across BIST 30 and save them as automatic plans."""
    state = store.load_state()
    held = {p["symbol"] for p in positions.open_positions() if p.get("piyasa") == "BIST"}
    found = []
    async with httpx.AsyncClient() as client:
        idx = await bist.fetch(client, bist.INDEX, "1d")
        if len(idx) < 21:
            return found
        for tick in bist.watchlist():
            sym = bist.yahoo_symbol(tick)
            if sym in state["planlar"] or sym in held:
                continue
            try:
                d = market.add_indicators(await bist.fetch(client, sym, "1d"))
                w = market.add_indicators(await bist.fetch(client, sym, "1wk"))
            except Exception as e:
                log.warning("BIST scan fetch failed for %s: %s", tick, e)
                continue
            if len(d) < 60:
                continue
            last = d.iloc[-1]
            day = datetime.fromtimestamp(last.open_time / 1000, bist.TR).date().isoformat()
            if day != datetime.fromtimestamp(idx.iloc[-1].open_time / 1000, bist.TR).date().isoformat():
                continue
            if alerts_store.load_settings().get("bist_son_aday", {}).get(sym) == day:
                continue
            setup = _setup(d, w, idx)
            if setup is None:
                continue
            plan = {
                "piyasa": "BIST", "tetik": setup["tetik"], "teyit": setup["tetik"],
                "iptal": setup["iptal"], "hedef": setup["hedef"], "strateji": setup["strateji"],
                "not": f"BIST tarayıcı: {setup['not']}; BIST100'e göre 20g güç {setup['rs']:+.1f} puan; hedef {setup['hedef_turu']}",
                "otomatik": True, "pozisyon": False, "guncelleme": int(time.time()),
                "bist_aday": True, "aday_gunu": day, "son_saat": None,
            }
            state = store.load_state()
            state["planlar"][sym] = plan
            store.save_state(state)
            s = alerts_store.load_settings()
            s.setdefault("bist_son_aday", {})[sym] = day
            alerts_store.save_settings(s)
            found.append({"sembol": sym, "hisse": tick, "kapanis": setup["kapanis"], "degisim": setup["degisim"],
                          "rs": setup["rs"], "hacim_orani": setup["hacim_orani"],
                          "dokunma": setup["dokunma"], "hedef_turu": setup["hedef_turu"], **plan})
    return found


async def hourly_check() -> list[dict]:
    """Short-term mode only: move BIST plans forward on 1h closes."""
    if config.BIST_CONFIRM_TF != "1h":
        return []
    return await _check_plans("1h")


async def daily_check() -> list[dict]:
    """Medium/long-term mode: move BIST plans forward on the final daily close (after 18:30)."""
    if config.BIST_CONFIRM_TF != "1d":
        return []
    return await _check_plans("1d")


async def _check_plans(tf: str) -> list[dict]:
    """On each newly closed bar of `tf`, move BIST plans forward. Returns events for main.py to send."""
    label = "günlük" if tf == "1d" else "1s"
    events = []
    state = store.load_state()
    async with httpx.AsyncClient() as client:
        for sym, p in list(state["planlar"].items()):
            if not is_bist_plan(sym):
                continue
            try:
                h = market.add_indicators(await bist.fetch(client, sym, tf))
            except Exception as e:
                log.warning("BIST hourly fetch failed for %s: %s", sym, e)
                continue
            if len(h) < 2:
                continue
            last, prev = h.iloc[-1], h.iloc[-2]
            bar = int(last.open_time)
            if p.get("son_saat") == bar:
                continue
            p["son_saat"] = bar
            close = float(last.close)
            tetik, teyit, iptal, hedef = (p.get(k) for k in ("tetik", "teyit", "iptal", "hedef"))

            if p.get("bist_aday"):
                age_days = (time.time() - p.get("guncelleme", time.time())) / 86400
                if age_days > CANDIDATE_TTL_DAYS and not p.get("pozisyon"):
                    p["_sil"] = True
                    continue
                if p.get("sinyal_verildi") or p.get("pozisyon"):
                    continue  # one ŞİMDİ AL per candidate; position tracking is separate
                bar_day = datetime.fromtimestamp(bar / 1000, bist.TR).date().isoformat()
                if bar_day <= p.get("aday_gunu", ""):
                    continue  # daily setup may only trigger in a later trading session
                if not _fresh(last, tf):
                    continue
                if iptal is not None and close < iptal:
                    events.append({"tur": "bozuldu", "sembol": sym, "metin": f"{label} kapanış {close:g} iptalin ({iptal:g}) altında: aday düştü."})
                    p["_sil"] = True
                elif tetik is not None and close > tetik:
                    g = await evaluate(client, symbol=sym, entry=close, iptal=iptal, hedef=hedef, level=tetik,
                                       hour_bar=last, volume_ok=True, bar_tf=tf)
                    events.append({"tur": "kapi", "sembol": sym, "kapi": g, "plan": p})
                    if g["ok"]:
                        p["sinyal_verildi"] = True
                    else:
                        p["_sil"] = True
                continue

            # Manual BIST plans: trigger then confirmation on closes of `tf`.
            if p.get("pozisyon") or p.get("sinyal_verildi") or (tf == "1h" and not bist.session_open()):
                continue
            if not _fresh(last, tf):
                continue
            if p.get("bekleyen_teyit") == int(prev.open_time) and teyit is not None:
                p.pop("bekleyen_teyit", None)
                if close >= teyit:
                    g = await evaluate(client, symbol=sym, entry=close, iptal=iptal, hedef=hedef, level=tetik,
                                       hour_bar=last, bar_tf=tf)
                    events.append({"tur": "kapi", "sembol": sym, "kapi": g, "plan": p})
                    if g["ok"]:
                        p["sinyal_verildi"] = True
                else:
                    events.append({"tur": "teyit_bozuldu", "sembol": sym, "metin": f"teyit {label} mumu {close:g} ile {teyit:g} altında kapandı."})
            elif iptal is not None and prev.close >= iptal > close:
                events.append({"tur": "iptal", "sembol": sym, "metin": f"{label} mum {close:g} ile İPTAL {iptal:g} altında kapandı."})
            elif tetik is not None and prev.close <= tetik < close:
                p["bekleyen_teyit"] = bar
                events.append({"tur": "tetik", "sembol": sym, "metin": f"{label} mum {close:g} ile TETİK {tetik:g} üstünde kapandı; sonraki {label} mum teyit."})
            elif hedef is not None and prev.close < hedef <= close:
                events.append({"tur": "hedef", "sembol": sym, "metin": f"{label} mum {close:g} ile HEDEF {hedef:g} üstünde kapandı."})
            elif tetik is not None and not _nan(last.atr14) and 0 < tetik - close <= 0.5 * float(last.atr14) \
                    and time.time() - p.get("son_yakinlik", 0) > 3 * 3600:
                back = h.iloc[-4]
                rising = close > float(back.close)
                vol_up = not _nan(last.vol_avg20) and last.volume > last.vol_avg20
                if rising and (vol_up or (not _nan(back.rsi14) and last.rsi14 - back.rsi14 >= 3)):
                    p["son_yakinlik"] = int(time.time())
                    events.append({"tur": "yaklasiyor", "sembol": sym,
                                   "metin": f"1s kapanış {close:g}, tetiğe ({tetik:g}) %{(tetik / close - 1) * 100:.2f} kaldı; "
                                            "yükselişte" + (", hacim ortalama üstü" if vol_up else ", RSI güçleniyor")
                                            + f". Henüz tetik değil: {label} KAPANIŞ tetiğin üstünde olmalı."})

    fresh = store.load_state()
    for sym, p in state["planlar"].items():
        if not is_bist_plan(sym) or sym not in fresh["planlar"]:
            continue
        if p.get("_sil") and not fresh["planlar"][sym].get("pozisyon"):
            del fresh["planlar"][sym]
            continue
        for k in ("son_saat", "bekleyen_teyit", "sinyal_verildi", "son_yakinlik"):
            if k in p:
                fresh["planlar"][sym][k] = p[k]
            else:
                fresh["planlar"][sym].pop(k, None)
    store.save_state(fresh)
    return events


def _fresh(last, tf: str) -> bool:
    """1h: closed within the last hour (+ data delay). 1d: today's final daily bar."""
    if tf == "1d":
        return datetime.fromtimestamp(int(last.open_time) / 1000, bist.TR).date() == bist.now_tr().date()
    age = time.time() - int(last.close_time) / 1000
    return bist.session_open() and 0 <= age <= FRESH_HOURLY_SECONDS + bist.DATA_DELAY_MIN * 60


async def record_purchase(d: dict) -> tuple[dict, str | None]:
    """"Aldım" on a BIST decision: whole lots at the (delayed) last price, TL budget re-checked now."""
    async with httpx.AsyncClient() as client:
        price = await bist.last_price(client, d["symbol"])
    kapi = d.get("kapi") or {}
    tl, notes = bist.tranche_tl(kapi.get("risk_off", True), kapi.get("hacim_ok", False), open_bist_tl())
    allowed_lots = bist.lots_for(tl, price)
    if d.get("iptal") is not None and price > d["iptal"]:
        risk_lot = price - d["iptal"] + price * 2 * (config.BIST_FEE_PCT + config.BIST_SLIPPAGE_PCT) / 100
        allowed_lots = min(allowed_lots, int(((bist.budget_tl() or 0) * config.BIST_MAX_RISK_PCT / 100) // risk_lot))
    proposed_lots = d.get("lot") or 1
    lots = min(allowed_lots, proposed_lots) if allowed_lots else proposed_lots
    if not allowed_lots:
        warning = ("⚠️ BIST bütçe/risk sınırı artık işlem tutarına izin vermiyor"
                   + (f" ({'; '.join(notes)})" if notes else "")
                   + ". Alım kaydedildi; gerçek adet farklıysa /duzelt ID adet=N.")
    elif lots < proposed_lots:
        warning = f"ℹ️ Bütçe/risk değişti: önerilen {proposed_lots} adet yerine {lots} adet kaydedildi. Gerçek lotu /duzelt ID adet=ADET ile düzelt."
    else:
        warning = None
    pos = positions.open_position(d["pair"], price, lots * price, d.get("iptal"), d.get("hedef"), "1h",
                                  source=f"BIST karar #{d['id']}", decision_id=d["id"], market_name="BIST",
                                  symbol=d["symbol"])
    if warning:
        warning = warning.replace("/duzelt ID", f"/duzelt {pos['id']}")
    if not allowed_lots:
        positions.add_violation(pos["id"], "BIST bütçe/risk sınırı doluyken alındı")
    positions.set_decision_action(d["id"], "aldi")
    return pos, warning


async def check_alarms(timeframes: tuple[str, ...]) -> tuple[list, list]:
    """BIST close-only alarms (1h during the session, 1d after the final close).

    Same semantics as the crypto websocket engine: only a CLOSED bar's close counts, cooldown
    between triggers, and after a trigger the stop/target are tracked on closes.
    Returns (fired, notices): fired = [(pair, alert, df)], notices = [(pair, alert, text)].
    """
    fired, notices = [], []
    alerts = alerts_store.load_alerts()
    now = alerts_store.now_tr()
    async with httpx.AsyncClient() as client:
        for pair, items in alerts.items():
            if not is_bist_plan(pair):
                continue
            for a in items:
                if a["timeframe"] not in timeframes or a["durum"] not in alerts_store.ACTIVE_STATES:
                    continue
                try:
                    df = market.add_indicators(await bist.fetch(client, pair, a["timeframe"]))
                except Exception as e:
                    log.warning("BIST alarm fetch failed for %s: %s", pair, e)
                    continue
                if df.empty or a.get("son_mum") == int(df.iloc[-1].open_time):
                    continue
                last = df.iloc[-1]
                a["son_mum"] = int(last.open_time)
                close = float(last.close)
                long = a["yon"] == "ABOVE"
                if a["tetikler"]:
                    if a.get("iptal") is not None and (close < a["iptal"] if long else close > a["iptal"]):
                        a["durum"], a["iptal_nedeni"] = "iptal", "kapanis"
                        notices.append((pair, a, f"❌ {pair} #{a['id']}: {a['timeframe']} kapanış {close:g} İPTAL "
                                                 f"{a['iptal']:g} ötesinde. Alarm iptal."))
                        continue
                    if a.get("hedef") is not None and (close >= a["hedef"] if long else close <= a["hedef"]):
                        a["durum"] = "pasif"
                        notices.append((pair, a, f"🎯 {pair} #{a['id']}: {a['timeframe']} kapanış {close:g} HEDEF "
                                                 f"{a['hedef']:g} gördü. Alarm pasif."))
                        continue
                if a["durum"] == "tetiklendi":
                    if now - datetime.fromisoformat(a["son_tetik_zamani"]) < alerts_store.parse_duration(a["cooldown"]):
                        continue
                    a["durum"] = "aktif"
                if (close > a["tetik"]) if long else (close < a["tetik"]):
                    a["durum"] = "tetiklendi"
                    a["son_tetik_zamani"] = now.isoformat()
                    a["tetikler"].append(now.isoformat())
                    fired.append((pair, dict(a), df))
    alerts_store.save_alerts(alerts)
    return fired, notices

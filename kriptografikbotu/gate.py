"""The single decision gate. Alarm triggers, plan confirmations and "Aldım" all pass through here.

Every rule is checked in code; DeepSeek only explains. A blocking failure means no AL.
Missing or stale data never passes silently: it fails the check ("doğrulanamadı").
"""
import logging
import time
from datetime import datetime, timezone

import httpx

import alerts_store
import backtest
import config
import discipline
import freshness
import macro
import market
import positions
import sentiment
import signal_life

log = logging.getLogger(__name__)

FRESH_CANDLE_SECONDS = 5 * 60  # a signal candle must have closed within this window


def _check(rule: str, passed: bool, detail: str, blocking: bool = True) -> dict:
    return {"kural": rule, "durum": "gecti" if passed else ("kaldi" if blocking else "uyari"),
            "detay": detail, "engelleyici": blocking}


def _icon(c: dict) -> str:
    return {"gecti": "✅", "kaldi": "❌", "uyari": "⚠️"}[c["durum"]]


def _nan(x) -> bool:
    return x is None or x != x


async def evaluate(client: httpx.AsyncClient, *, pair: str, direction: str, entry: float,
                   iptal: float | None, hedef: float | None, timeframe: str = "15m",
                   candle=None, volume_ok: bool | None = None) -> dict:
    """Run every entry rule.

    candle: the closed signal candle (row with open_time, close, volume, vol_avg20, atr14).
            None when evaluating at "Aldım" time, where entry is the live price.
    volume_ok: overrides the candle's volume check (e.g. the trigger candle was the previous one).
    """
    coin = pair.split("/")[0]
    symbol = alerts_store.pair_to_symbol(pair)
    checks = []

    checks.append(_check("yön", direction == "ABOVE",
                         "yükseliş kırılımı (spot alım)" if direction == "ABOVE"
                         else "BELOW alarmı düşüş uyarısıdır; spot alım kapısı sadece ABOVE için"))

    if candle is not None:
        closed_at = (int(candle.open_time) + backtest.TF_MS[timeframe]) / 1000
        age = time.time() - closed_at
        checks.append(_check("mum güncelliği", 0 <= age <= FRESH_CANDLE_SECONDS,
                             f"sinyal mumu {age / 60:.1f} dk önce kapandı" if age >= 0 else "mum henüz kapanmadı"))

    if iptal is None or hedef is None:
        checks.append(_check("R/R", False, "iptal veya hedef yok: R/R hesaplanamadı"))
        rr = None
    elif entry <= iptal:
        checks.append(_check("R/R", False, f"fiyat {entry:.6g} iptalin ({iptal:.6g}) altında/eşit"))
        rr = None
    else:
        rr = round((hedef - entry) / (entry - iptal), 2)

    # Macro: fail closed. Unknown regime counts as RİSK-OFF for sizing and thresholds.
    macro_ok, risk_off, soon, why = True, False, [], ""
    try:
        m = await macro.summary()
        regime = m.get("rejim", {})
        stale = m.get("guncel_degil", [])
        if "hata" in regime or "skor" not in regime:
            macro_ok, why = False, f"rejim hesaplanamadı ({regime.get('hata', '?')})"
        elif "fred" in stale:
            macro_ok, why = False, "FRED yenilenemedi, eldeki veri süresi dolmuş"
        else:
            risk_off = regime["skor"] <= -2
        soon = [e for e in macro.upcoming(await macro.calendar(strict=True), 2) if e["kalan_saat"] >= 0]
    except Exception as e:
        macro_ok, why = False, f"takvim/rejim alınamadı ({e})"
    if not macro_ok:
        risk_off = True
    min_rr = 1.5 if risk_off else 1.0
    if rr is not None:
        checks.append(_check("R/R", rr >= min_rr,
                             f"R/R {rr:.2f}, eşik {min_rr:g}" + (" (RİSK-OFF/doğrulanamadı)" if risk_off else "")))

    atr = None if candle is None else candle.atr14
    if not _nan(atr) and iptal is not None and entry > iptal:
        # Mandatory: a stop closer than one ATR is hit by normal noise (wicks), whatever the R/R looks like.
        wide = entry - iptal >= atr
        checks.append(_check("ATR stop", wide, f"stop mesafesi {entry - iptal:.4g} (%{(entry - iptal) / entry * 100:.1f}) "
                             f"{'≥' if wide else '<'} 1×ATR {atr:.4g}" + ("" if wide else " — iğneye takılır, stopu genişlet")))

    cooldown = signal_life.stop_cooldown(pair)
    if cooldown:
        checks.append(_check("bekleme", False, cooldown))

    if volume_ok is None and candle is not None:
        avg = candle.vol_avg20
        volume_ok = not _nan(avg) and avg > 0 and candle.volume > avg
        vol_detail = (f"kırılım mumu hacmi x{candle.volume / avg:.2f} MA20" if not _nan(avg) and avg
                      else "Volume MA20 yok, doğrulanamadı")
    else:
        vol_detail = "sinyal anındaki hacim teyidi " + ("vardı" if volume_ok else "yoktu/doğrulanamadı")
    volume_ok = bool(volume_ok)
    checks.append(_check("hacim", volume_ok, vol_detail))

    if coin != "BTC":
        try:
            btc = market.add_indicators(await market.fetch_klines(client, "BTC" + config.QUOTE, "15m"))
            b = btc.iloc[-1]
            btc_age = time.time() - (int(b.open_time) + backtest.TF_MS["15m"]) / 1000
            gate_open = not _nan(b.sma50) and b.close > b.sma50 and btc_age <= 20 * 60
            checks.append(_check("BTC kapı", gate_open,
                                 f"BTC 15m kapanış {b.close:.6g} SMA50 {b.sma50:.6g} {'üstünde' if b.close > b.sma50 else 'altında'}"
                                 if btc_age <= 20 * 60 else "BTC mumu güncel değil, doğrulanamadı"))
        except Exception as e:
            checks.append(_check("BTC kapı", False, f"BTC verisi alınamadı, doğrulanamadı ({e})"))

    try:
        import structure
        frames = {tf: market.add_indicators(await market.fetch_klines(client, symbol, tf)) for tf in ("1d", "4h", "1h", "15m")}
        eng = structure.analyze(frames, None, {"tetik": None, "iptal": iptal, "hedef": hedef},
                                entry_tf="15m", htf_list=("1d", "4h"))
        s4 = eng["yapi"].get("4h", {})
        ok4 = s4.get("trend") != "düşüş" and not (s4.get("choch") or "").startswith("düşüş")
        checks.append(_check("yapı (4h)", ok4, f"4h {s4.get('trend', '?')}" + (f" · {s4['choch']}" if s4.get("choch") else "")
                             + (" — yapıya karşı alım" if not ok4 else ""), blocking=False))
        conf = eng["konfluens"]["skor"]
        checks.append(_check("konfluens", conf is not None and conf >= 50, f"setup kalitesi {conf}/100 (olasılık değil)",
                             blocking=False))
        sweep_bear = [x for x in eng["likidite"]["supurme"] if "üstten" in x]
        if sweep_bear:
            checks.append(_check("likidite", False, sweep_bear[0], blocking=False))
    except Exception as e:
        log.warning("Structure engine in gate failed for %s: %s", pair, e)

    if not macro_ok:
        checks.append(_check("makro", False, f"doğrulanamadı: {why}"))
    else:
        checks.append(_check("makro", not soon, "2 saat içinde makro veri yok" if not soon else
                             f"{soon[0]['olay']} {soon[0]['kalan_saat']:g} saat sonra — veri öncesi giriş yok"))

    try:
        filters = await market.order_filters(client, symbol)
        exchange_min = filters["min_tutar_usd"]
        if filters["durum"] != "TRADING":
            checks.append(_check("emir", False, f"parite işlemde değil ({filters['durum']})"))
    except Exception as e:
        exchange_min = 0.0
        checks.append(_check("emir", False, f"borsa emir filtreleri alınamadı ({e})"))
    try:
        senti = await sentiment.summary()
    except Exception as e:
        senti = {"korku_acgozluluk": {"hata": str(e)[:80]}}
    greed = sentiment.greed_note(senti)
    tranche, tranche_notes = positions.tranche_usd(pair, risk_off, volume_ok, exchange_min, greed=greed)
    s_ok, s_detail = sentiment.gate_check(senti)
    checks.append(_check("duygu", s_ok, s_detail, blocking=False))
    d_ok, d_detail = discipline.check("KRIPTO")
    checks.append(_check("disiplin", d_ok, d_detail))
    checks.append(_check("bütçe", tranche > 0,
                         f"ilk kademe {tranche:g} USD" + (f" ({'; '.join(tranche_notes)})" if tranche_notes else "")
                         if tranche > 0 else "; ".join(tranche_notes) or "limit dolu, pas"))
    heavy = portfolio_weight_warning(pair, tranche)
    if heavy:
        checks.append(_check("portföy", False, heavy, blocking=False))

    ok = all(c["durum"] != "kaldi" for c in checks)
    try:
        data_times = freshness.snapshot(await freshness.collect())
    except Exception as e:
        data_times = {"hata": str(e)[:80]}
    return {
        "veri": data_times,  # when each source was last current, for the decision slip
        "ok": ok, "giris": entry, "iptal": iptal, "hedef": hedef, "rr": rr,
        "kademe_usd": tranche,
        "kademe_notlari": tranche_notes, "risk_off": risk_off, "hacim_ok": volume_ok, "acgozluluk": greed,
        "kurallar": checks,
        "maddeler": [f"{_icon(c)} {c['kural']}: {c['detay']}" for c in checks],
        "kalan": [c["kural"] for c in checks if c["durum"] == "kaldi"],
        "mum": None if candle is None else {
            "acilis_utc": datetime.fromtimestamp(int(candle.open_time) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "zaman_dilimi": timeframe, "kapanis": float(candle.close),
            "hacim": float(candle.volume), "hacim_ort20": None if _nan(candle.vol_avg20) else float(candle.vol_avg20)},
        "korelasyon": [p["pair"] for p in positions.open_positions() if p["pair"] != pair],
        "atr": None if _nan(atr) else float(atr),
        "adet": round(tranche / entry, 6) if tranche > 0 and entry > 0 else None,
        "midas_stop": signal_life.midas_stop(iptal, None if _nan(atr) else float(atr)),
    }


def portfolio_weight_warning(pair: str, tranche: float) -> str | None:
    """Open crypto positions by cost: one coin above MAX_ASSET_PCT of the crypto book is a warning on every new signal."""
    book: dict[str, float] = {}
    for p in positions.open_positions():
        if p.get("piyasa", "KRIPTO") == "KRIPTO":
            book[p["pair"]] = book.get(p["pair"], 0.0) + float(p.get("miktar_usd") or 0)
    if tranche > 0:
        book[pair] = book.get(pair, 0.0) + tranche
    total = sum(book.values())
    if total <= 0 or len(book) < 2:
        return None
    heavy = [(k, v / total * 100) for k, v in book.items() if v / total * 100 > config.MAX_COIN_PCT]
    if not heavy:
        return None
    k, pct = max(heavy, key=lambda x: x[1])
    return (f"{k.split('/')[0]} kripto portföyünün %{pct:.0f}'i (sınır %{config.MAX_COIN_PCT}): "
            + ("bu alımla tek coine yükleniyorsun" if k == pair else "yeni pozisyon açmadan önce yoğunlaşmayı düşün"))


def card_lines(g: dict) -> list[str]:
    """Size and broker-stop lines under a passed signal (numbers from code, never from the model)."""
    out = []
    entry = g.get("giris") or g.get("close")
    if g.get("adet") and g.get("iptal") is not None and entry and entry > g["iptal"]:
        risk = g["kademe_usd"] * (entry - g["iptal"]) / entry
        out.append(f"📦 Öneri: {g['kademe_usd']:g} USD ≈ {g['adet']:.6g} adet · stopa kadar risk ≈ {risk:.2f} USD")
    if g.get("midas_stop"):
        lo, hi = g["midas_stop"]
        out.append(f"🛡 Midas stop önerisi: {hi:.6g} – {lo:.6g} (iptal − 0,5…1 ATR). Bot iptali kapanışla verir; "
                   "borsa stopu dokununca çalışır, o yüzden biraz aşağıda dursun.")
    return out


def summary_line(g: dict) -> str:
    """One authoritative line under every AI analysis."""
    if g["ok"]:
        return "\n".join([f"🔒 Kod kapısı: GEÇTİ — ilk kademe {g['kademe_usd']:g} USD, R/R {g['rr']}", *card_lines(g),
                          signal_life.track_line("KRIPTO")])
    return "🔒 Kod kapısı: KALDI — " + ", ".join(g["kalan"]) + " (AL yok)"


async def record_purchase(d: dict, source_suffix: str = "") -> tuple[dict, str | None]:
    if d.get("piyasa") == "ABD":
        import us_signals
        pos, warning = await us_signals.record_purchase(d)
        plan_key = d["symbol"]
    elif d.get("piyasa") == "BIST":
        import bist_signals  # BIST has whole lots and a TL budget
        pos, warning = await bist_signals.record_purchase(d)
        plan_key = d["symbol"]
    else:
        pos, warning = await _record_crypto_purchase(d, source_suffix)
        plan_key = d["pair"].split("/")[0]
    # The matching plan now has an open position: goalpost rule applies and status shows 💼.
    import conversation_store
    state = conversation_store.load_state()
    if plan_key in state["planlar"]:
        state["planlar"][plan_key]["pozisyon"] = True
        conversation_store.save_state(state)
    return pos, warning


async def _record_crypto_purchase(d: dict, source_suffix: str = "") -> tuple[dict, str | None]:
    """"Aldım" on a decision. The tranche is recomputed now (positions may have changed since the
    alarm). The buy already happened, so it is recorded either way; a breached cap is flagged."""
    async with httpx.AsyncClient() as client:
        price = await market.last_price(client, d["symbol"])
        try:
            exchange_min = (await market.order_filters(client, d["symbol"]))["min_tutar_usd"]
        except Exception:
            exchange_min = 0.0
    kapi = d.get("kapi") or {}
    fresh, notes = positions.tranche_usd(d["pair"], kapi.get("risk_off", True), kapi.get("hacim_ok", False), exchange_min,
                                         greed=kapi.get("acgozluluk"))
    warning = None
    if fresh > 0:
        usd = fresh
        if d.get("kademe_usd") and fresh < d["kademe_usd"]:
            warning = f"ℹ️ Kademe {d['kademe_usd']:g} → {fresh:g} USD (alarmdan beri pozisyon açılmış)."
    else:
        usd = d.get("kademe_usd") or config.REDUCED_TRANCHE_USD
        warning = ("⚠️ Kural ihlali: ilk kademe limiti dolu (" + "; ".join(notes) + "). "
                   "Kayıt tutuldu; gerçek miktar farklıysa /duzelt.")
    pos = positions.open_position(d["pair"], price, usd, d.get("iptal"), d.get("hedef"), d["timeframe"],
                                  source=f"alarm #{d['alarm_id']}{source_suffix}", decision_id=d["id"])
    if fresh <= 0:
        positions.add_violation(pos["id"], "ilk kademe limiti doluyken alındı")
    positions.set_decision_action(d["id"], "aldi")
    return pos, warning


def rule_stats(decisions: list[dict]) -> list[dict]:
    """Per rule: how decided trades ended when the rule passed vs. when it failed.

    Uses only decisions with a gate record and a final close-based outcome (hedef or stop),
    so the numbers answer "which rule actually separated winners from losers".
    """
    table: dict[str, dict] = {}
    for d in decisions:
        res = (d.get("sonuc") or {}).get("sonuc")
        rules = (d.get("kapi") or {}).get("kurallar")
        if res not in ("hedef", "stop") or not rules:
            continue
        for r in rules:
            side = "gecti" if r["durum"] == "gecti" else "kaldi"
            row = table.setdefault(r["kural"], {"gecti": {"hedef": 0, "stop": 0}, "kaldi": {"hedef": 0, "stop": 0}})
            row[side][res] += 1

    out = []
    for rule, row in table.items():
        def pct(s):
            n = s["hedef"] + s["stop"]
            return {"n": n, "hedef": s["hedef"], "stop": s["stop"],
                    "isabet_yuzde": round(s["hedef"] / n * 100) if n else None}
        out.append({"kural": rule, "gectiginde": pct(row["gecti"]), "kaldiginda": pct(row["kaldi"])})
    return sorted(out, key=lambda x: -(x["gectiginde"]["n"] + x["kaldiginda"]["n"]))


MIN_RULE_SAMPLE = 20  # decided trades per rule before any advice is shown
MIN_SIDE_SAMPLE = 5   # ...and at least this many on each side (passed / failed)


def rule_advice(stats: list[dict]) -> list[str]:
    """Observations about which gate rules separate winners from losers. Never changes a rule."""
    out = []
    for r in stats:
        g, k = r["gectiginde"], r["kaldiginda"]
        if g["n"] + k["n"] < MIN_RULE_SAMPLE or min(g["n"], k["n"]) < MIN_SIDE_SAMPLE:
            continue
        diff = g["isabet_yuzde"] - k["isabet_yuzde"]
        if diff >= 15:
            out.append(f"✅ {r['kural']}: işe yarıyor — geçtiğinde hedef %{g['isabet_yuzde']}, kaldığında %{k['isabet_yuzde']}.")
        elif diff <= 5:
            out.append(f"🤔 {r['kural']}: fark yaratmıyor — kaldığında da hedef %{k['isabet_yuzde']} (geçtiğinde "
                       f"%{g['isabet_yuzde']}). Boşuna işlem kaçırıyor olabilir; kural değiştirilmedi, sadece gözlem.")
        else:
            out.append(f"➖ {r['kural']}: hafif fark ({diff:+d} puan), karar için erken.")
    return out


def rule_scorecard(decisions: list[dict]) -> str:
    stats = rule_stats(decisions)
    total = sum(1 for d in decisions if (d.get("sonuc") or {}).get("sonuc") in ("hedef", "stop") and (d.get("kapi") or {}).get("kurallar"))
    lines = [f"📐 KURAL KARNESİ — {total} sonuçlanmış karar (hedef/stop, kapanışla)"]
    for r in stats:
        g, k = r["gectiginde"], r["kaldiginda"]
        fmt = lambda s: f"{s['n']} karar, hedef %{s['isabet_yuzde']}" if s["n"] else "veri yok"
        lines.append(f"{r['kural']}: geçtiğinde {fmt(g)} | kaldığında {fmt(k)}")
    advice = rule_advice(stats)
    if advice:
        lines += ["", *advice]
    else:
        lines.append(f"\nÖneri için kural başına en az {MIN_RULE_SAMPLE} sonuçlanmış karar (her iki tarafta ≥{MIN_SIDE_SAMPLE}) "
                     "gerekiyor. Kararlar biriktikçe burada 'şu kural fark yaratmıyor' gibi gözlemler çıkar.")
    lines.append("Kurallar otomatik değişmez; değiştirmek senin kararın.")
    return "\n".join(lines)

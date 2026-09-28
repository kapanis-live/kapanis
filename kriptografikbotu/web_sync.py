"""Bridge between the bot and the Kapanış web panel.

The panel's backend never reads the bot's files. Instead:
- push_all() converts bot state into the panel's document shapes and sends each
  collection to POST /api/ingest/{collection}?replace=true (full snapshot per collection).
- process_commands() pulls actions queued in the panel (GET /api/commands/pending),
  applies them with the same rules as Telegram, and marks them done.
Every request carries X-Bot-Key. Nothing here runs unless WEB_URL and BOT_API_KEY are set.
"""
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

import httpx

import alerts_store
import backtest
import bist
import bist_signals
import config
import conversation_store as store
import costs
import derivatives
import freshness
import gate
import macro
import market
import positions

log = logging.getLogger(__name__)

ENDED_ALERT_DAYS = 3        # finished alerts stay visible this long
CLOSED_POSITIONS_SHOWN = 10
SIGNALS_SHOWN = 30
PENDING_DECISION_HOURS = 24  # an unanswered alert decision expires from "Bekleyen kararlar" after this
DERIVATIVE_COINS = ["BTC", "ETH"]
ALERT_MAX_DISTANCE = 0.5  # panel alarm trigger must be within ±50% of the current price

ALERT_STATUS = {"aktif": "armed", "tetiklendi": "triggered", "iptal": "cancelled", "pasif": "cancelled"}


def enabled() -> bool:
    return bool(config.WEB_URL and config.BOT_API_KEY)


def _headers() -> dict:
    return {"X-Bot-Key": config.BOT_API_KEY}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rr(entry, stop, target) -> float | None:
    if None in (entry, stop, target) or entry == stop:
        return None
    return round(abs(target - entry) / abs(entry - stop), 2)


def _alert_doc_id(pair: str, alert_id: int) -> str:
    return f"{pair.replace('/', '-')}-{alert_id}"


# --- bot state -> panel documents ----------------------------------------------

def build_alerts() -> list[dict]:
    cutoff = (alerts_store.now_tr() - timedelta(days=ENDED_ALERT_DAYS)).isoformat()
    out = []
    for pair, items in alerts_store.load_alerts().items():
        for a in items:
            last = a["son_tetik_zamani"] or a["olusturulma"]
            if a["durum"] not in alerts_store.ACTIVE_STATES and last < cutoff:
                continue
            note = f"KAPANIŞ {a['yon']} · {a['timeframe']} · cooldown {a['cooldown']}"
            if not a["hacim_sart"]:
                note += " · hacim şartı yok"
            if a["durum"] == "pasif":
                note += " · hedef kapanışla görüldü"
            elif a.get("iptal_nedeni") == "kapanis":
                note += " · iptal seviyesi kapanışla kırıldı"
            elif a.get("iptal_nedeni") == "kullanici":
                note += " · elle iptal edildi"
            if a["tetikler"]:
                note += f" · {len(a['tetikler'])} kez tetiklendi"
            out.append({
                "id": _alert_doc_id(pair, a["id"]), "symbol": pair,
                "side": "long" if a["yon"] == "ABOVE" else "short",
                "entry": a["tetik"], "stop": a.get("iptal"), "target": a.get("hedef"),
                "rr": _rr(a["tetik"], a.get("iptal"), a.get("hedef")),
                "status": ALERT_STATUS[a["durum"]], "note": note,
                "created_at": a["olusturulma"], "queued": False,
            })
    return sorted(out, key=lambda d: d["created_at"], reverse=True)


def build_positions(prices: dict[str, float]) -> list[dict]:
    items = positions.load()
    open_items = [p for p in items if p["durum"] == "acik"]
    closed = sorted((p for p in items if p["durum"] == "kapali"),
                    key=lambda p: p["kapanis_zamani"], reverse=True)[:CLOSED_POSITIONS_SHOWN]
    out = []
    for p in open_items + closed:
        price = p["kapanis_fiyat"] if p["durum"] == "kapali" else prices.get(p["symbol"], p["giris"])
        r = positions.pnl(p, price)
        out.append({
            "id": f"pos_{p['id']}", "symbol": p["pair"], "side": "long",
            "market": p.get("piyasa", "KRIPTO"), "currency": p.get("para", "USD"),
            "entry": p["giris"], "stop": p["stop"], "target": p["hedef"], "current": price,
            "size": round(p["adet"], 8), "rr": _rr(p["giris"], p.get("stop_ilk"), p["hedef"]),
            "pnl": r["pnl_usd"], "pnl_pct": r["pnl_yuzde"],
            "opened_at": p["acilis"], "status": "open" if p["durum"] == "acik" else "closed", "queued": False,
        })
    return out


def _decision_expired(d: dict) -> bool:
    age = alerts_store.now_tr() - datetime.fromisoformat(d["zaman"])
    return age > timedelta(hours=PENDING_DECISION_HOURS)


def _first_line(text: str | None, limit: int = 180) -> str:
    line = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    return line if len(line) <= limit else line[:limit - 1] + "…"


def build_decisions() -> list[dict]:
    out = []
    for d in positions.load_decisions()[-SIGNALS_SHOWN:]:
        verdict = {"aldi": "Aldım", "pas": "Pas"}.get(d["aksiyon"])
        note = f"Sinyal: {SIGNAL_WORDS.get(d['karar'], d['karar'])}"
        if d.get("piyasa") == "BIST":
            note += f" · ilk kademe {d.get('lot', 0)} adet / {d.get('kademe_usd', 0):g} TL · Yahoo verisi gecikmeli"
        elif d.get("kademe_usd"):
            note += f" · ilk kademe {d['kademe_usd']:g} USD"
        if d.get("uyarilar"):
            note += " · " + "; ".join(d["uyarilar"])
        out.append({
            "id": f"dec_{d['id']}", "symbol": d["pair"], "kind": "KARAR", "verdict": verdict,
            "market": d.get("piyasa", "KRIPTO"), "currency": "TL" if d.get("piyasa") == "BIST" else "USD",
            "entry": d["kapanis"], "stop": d.get("iptal"), "target": d.get("hedef"),
            "rr": _rr(d["kapanis"], d.get("iptal"), d.get("hedef")), "chart_note": note,
            "status": "pending" if verdict is None and not _decision_expired(d) else "resolved",
            "created_at": d["zaman"], "queued": False,
        })
    return out


def _indicator_panels(g: dict, tf: str) -> tuple[list[dict], int]:
    """Four facts panels from the indicator snapshot taken at trigger time, plus a -5..+5 score."""
    c = g.get("close")
    score = 0
    above = []
    for key in ("sma20", "sma50", "sma200"):
        if c is not None and g.get(key) is not None:
            is_above = c > g[key]
            score += 1 if is_above else -1
            above.append(f"{key.upper()} {'üstü' if is_above else 'altı'}")
    rsi = g.get("rsi14")
    if rsi is not None:
        score += 1 if rsi > 55 else -1 if rsi < 45 else 0
    vol, avg = g.get("volume"), g.get("vol_avg20")
    vol_ratio = vol / avg if vol and avg else None
    if vol_ratio is not None:
        score += 1 if vol_ratio > 1 else -1
    trend = "Yukarı" if score >= 2 else "Aşağı" if score <= -2 else "Karışık"
    panels = [
        {"key": "trend", "title": f"Trend ({tf})", "value": trend, "detail": ", ".join(above) or "SMA verisi yok"},
        {"key": "momentum", "title": "RSI(14)", "value": "—" if rsi is None else f"{rsi:.1f}",
         "detail": "aşırı alım bölgesi" if rsi and rsi >= 70 else "aşırı satım bölgesi" if rsi and rsi <= 30 else "nötr bant"},
        {"key": "volume", "title": "Hacim / MA20", "value": "—" if vol_ratio is None else f"x{vol_ratio:.2f}",
         "detail": "kırılım hacmi teyitli" if vol_ratio and vol_ratio > 1 else "hacim teyidi yok, doğrulanamadı"},
        {"key": "structure", "title": "ATR(14) / VWAP", "value": "—" if g.get("atr14") is None else f"{g['atr14']:g}",
         "detail": "günlük VWAP " + ("—" if g.get("vwap") is None else f"{g['vwap']:g}")},
    ]
    return panels, max(-5, min(5, score))


OUTCOME_REFRESH_SECONDS = 15 * 60
OUTCOME_PER_PUSH = 5


async def refresh_outcomes():
    """What happened after each decision (close-based, same as backtests). Final results
    (hedef/stop) are stored once; open ones are re-checked at most every 15 minutes."""
    done = 0
    now = datetime.now(timezone.utc).timestamp()
    for d in reversed(positions.load_decisions()[-SIGNALS_SHOWN:]):
        if done >= OUTCOME_PER_PUSH:
            break
        s = d.get("sonuc")
        if s and (s["sonuc"] in ("hedef", "stop") or now - s["kontrol_ts"] < OUTCOME_REFRESH_SECONDS):
            continue
        try:
            res = await backtest.evaluate_decision(d)
        except Exception as e:
            log.warning("Outcome for decision %s failed: %s", d["id"], e)
            continue
        cikis = None if res["cikis"] is None else float(res["cikis"])
        positions.update_decision(d["id"], sonuc={"sonuc": res["sonuc"], "cikis": cikis, "mum": res["mum"],
                                                  "R": None if res["R"] is None else float(res["R"]),
                                                  "kontrol_ts": now})
        done += 1


def build_signals() -> list[dict]:
    out = []
    for d in reversed(positions.load_decisions()[-SIGNALS_SHOWN:]):
        panels, score = _indicator_panels(d.get("gostergeler") or {}, d.get("gostergeler_tf", d["timeframe"]))
        reason = "; ".join(d.get("uyarilar") or []) or f"kapanış {d['kapanis']:g}"
        out.append({
            "id": f"sig_{d['id']}", "symbol": d["pair"], "timeframe": d["timeframe"],
            "market": d.get("piyasa", "KRIPTO"), "currency": "TL" if d.get("piyasa") == "BIST" else "USD",
            "type": f"Kapanış {'ABOVE' if d['yon'] == 'ABOVE' else 'BELOW'}", "score": score,
            "summary": _first_line(d.get("analiz")) or f"Sinyal: {SIGNAL_WORDS.get(d['karar'], d['karar'])}",
            "created_at": d["zaman"],
            "analysis": {"panels": panels,
                         "bot_decision": {"verdict": d["karar"], "confidence": None, "reason": reason},
                         "text": d.get("analiz"),
                         # Why AL/BEKLE/PAS: the code gate's rule-by-rule result and what happened after.
                         "gate": d.get("kapi"),
                         "outcome": d.get("sonuc"),
                         "user_action": {"aldi": "Aldım", "pas": "Pas"}.get(d.get("aksiyon"))},
        })
    return out


async def build_candles(client: httpx.AsyncClient, pairs: set[str]) -> list[dict]:
    out = []
    for pair in sorted(pairs):
        try:
            df = market.add_indicators(await market.fetch_klines(client, alerts_store.pair_to_symbol(pair), "1h", 300))
        except Exception as e:
            log.warning("Candles for %s failed: %s", pair, e)
            continue
        tail = df.tail(120)
        last = df.iloc[-1]
        out.append({
            "id": pair.replace("/", "-"), "symbol": pair, "timeframe": "1H",
            "candles": [{"t": datetime.fromtimestamp(r.open_time / 1000, tz=timezone.utc).isoformat(),
                         "o": r.open, "h": r.high, "l": r.low, "c": r.close, "v": r.volume}
                        for r in tail.itertuples()],
            "sma20": market._num(last.sma20), "sma50": market._num(last.sma50), "sma200": market._num(last.sma200),
        })
    return out


def build_macro(m: dict, events: list[dict]) -> dict:
    rj = m.get("rejim", {})
    fred = m.get("fred", {})
    comp_values = {
        "likidite": ("Net likidite", fred.get("net_likidite_milyar_usd", {}).get("4h_degisim_yuzde"), "%"),
        "dolar": ("Geniş dolar endeksi", fred.get("DTWEXBGS", {}).get("4h_degisim_yuzde"), "%"),
        "kredi_spreadi": ("HY kredi spreadi", fred.get("BAMLH0A0HYM2", {}).get("4h_degisim"), " puan"),
        "vix": ("VIX", fred.get("VIXCLS", {}).get("son"), ""),
        "reel_faiz": ("10Y reel faiz", fred.get("DFII10", {}).get("4h_degisim"), " puan"),
    }
    components = []
    for key, s in (rj.get("bilesenler") or {}).items():
        name, value, unit = comp_values[key]
        shown = "—" if value is None else (f"{value:g}" if key == "vix" else f"4h {value:+g}{unit}")
        components.append({"name": name, "value": shown, "score": s})

    notes = ["Rejim skoru net likidite, dolar, kredi spreadi, VIX ve reel faizin 4 haftalık yönünden "
             "kodla hesaplanır; rüzgarın yönünü anlatır, tahmin değildir."]
    enf = m.get("bls", {}).get("enflasyon")
    if enf:
        notes.append(f"CPI {enf['donem']}: yıllık %{enf['cpi_yillik']}, core %{enf['core_yillik']}, "
                     f"core 3 ay yıllıklandırılmış %{enf['core_3ay_yilliklandirilmis']} ({enf.get('trend', '?')}).")
    ist = m.get("bls", {}).get("istihdam")
    if ist:
        notes.append(f"NFP son 3 ay (bin): {', '.join('?' if x is None else f'{x:g}' for x in ist['nfp_degisim_bin_son3'])}; "
                     f"işsizlik %{ist['issizlik']}.")
    for coin, c in (m.get("cftc_cme") or {}).items():
        if isinstance(c, dict) and "kaldiracli_fon_net" in c:
            notes.append(f"COT {coin} ({c['rapor_tarihi']}): kaldıraçlı fon net {c['kaldiracli_fon_net']:+,} "
                         f"(52h yüzdelik {c['kaldiracli_fon_net_52h_yuzdelik']:g}); çoğu ETF baz işlemidir.")

    stale = any(isinstance(m.get(k), dict) and "hata" in m[k] for k in ("fred", "bls", "cftc_cme"))
    dxy = fred.get("DTWEXBGS", {})
    now_tr = datetime.now(macro.TR)
    calendar = [{"time": e["tr_zaman"], "title": e["olay"], "country": "US", "importance": "high",
                 "actual": None, "forecast": None, "previous": None}
                for e in events if now_tr - timedelta(hours=12) <= datetime.fromisoformat(e["tr_zaman"]) <= now_tr + timedelta(days=14)]
    return {
        "id": "macro_current",
        "regime_score": rj.get("skor", 0), "regime_label": rj.get("etiket", "hesaplanamadı"),
        "dxy_alt": {"label": "FRED geniş dolar endeksi, klasik DXY değil", "value": dxy.get("son"),
                    "score": (rj.get("bilesenler") or {}).get("dolar", 0)},
        "stale": stale, "updated_at": _now_iso(), "components": components,
        "calendar": calendar, "note": " ".join(notes),
    }


async def build_derivatives(client: httpx.AsyncClient, m: dict) -> list[dict]:
    out = []
    cot = m.get("cftc_cme") or {}
    for coin in DERIVATIVE_COINS:
        try:
            d = await derivatives.snapshot(client, coin)
        except Exception as e:
            log.warning("Derivatives for %s failed: %s", coin, e)
            continue
        if "hata" in d:
            continue
        c = cot.get(coin) if isinstance(cot.get(coin), dict) else {}
        out.append({
            "id": f"der_{coin.lower()}", "symbol": f"{coin}/USDT",
            "funding_rate": d["funding_son_yuzde"], "open_interest": d.get("acik_pozisyon_usd"),
            "long_short_ratio": d.get("long_short_hesap_orani"),
            "cot_percentile": c.get("kaldiracli_fon_net_52h_yuzdelik"), "basis": d.get("baz_yuzde"),
            "updated_at": _now_iso(),
        })
    return out


def build_usage() -> dict:
    today = datetime.now(macro.TR).date()
    rows = [r for r in costs._rows() if datetime.fromisoformat(r["utc"]).astimezone(macro.TR).date() == today]
    hourly = [{"hour": h, "cost": 0.0, "calls": 0} for h in range(24)]
    for r in rows:
        h = datetime.fromisoformat(r["utc"]).astimezone(macro.TR).hour
        hourly[h]["cost"] = round(hourly[h]["cost"] + r["usd"], 5)
        hourly[h]["calls"] += 1
    tariff = []
    for h in range(24):
        when = datetime.now(macro.TR).replace(hour=h, minute=30).astimezone(timezone.utc)
        tier = "peak" if costs.is_peak(when) else "offpeak"
        tariff.append({"hour": h, "rate": config.DEEPSEEK_PRICES[tier]["out"],
                       "tier": "yüksek" if tier == "peak" else "düşük"})
    return {
        "id": "usage_today", "date": _now_iso(),
        "total_cost": round(sum(r["usd"] for r in rows), 5),
        "tokens_in": sum(r["hit"] + r["miss"] for r in rows),
        "tokens_out": sum(r["out"] for r in rows), "calls": len(rows),
        "hourly": hourly, "tariff": tariff,
        "usd_try": config.USD_TRY,
    }


def build_report() -> dict:
    closed = [p for p in positions.load() if p["durum"] == "kapali"]
    trades, rs = [], []
    for p in sorted(closed, key=lambda p: p["kapanis_zamani"], reverse=True):
        r = positions.pnl(p, p["kapanis_fiyat"])
        if r["R"] is not None:
            rs.append(r["R"])
        trades.append({"id": f"t{p['id']}", "symbol": p["pair"], "side": "long", "entry": p["giris"],
                       "market": p.get("piyasa", "KRIPTO"), "currency": p.get("para", "USD"),
                       "exit": p["kapanis_fiyat"], "r": r["R"] if r["R"] is not None else 0.0,
                       "result": "win" if r["pnl_usd"] > 0 else "loss", "closed_at": p["kapanis_zamani"]})
    planned = [x for x in (_rr(p["giris"], p.get("stop_ilk"), p["hedef"]) for p in closed) if x is not None]
    wins = sum(t["result"] == "win" for t in trades)
    return {
        "id": "report_current",
        "performance": {"count": len(trades), "win_rate": wins / len(trades) if trades else 0,
                        "avg_rr": round(sum(planned) / len(planned), 2) if planned else None,
                        "total_r": round(sum(rs), 2), "best": max(rs) if rs else None,
                        "worst": min(rs) if rs else None},
        "trades": trades,
        # Which rule separated winners from losers, from the decision slips' final outcomes.
        "rule_stats": gate.rule_stats(positions.load_decisions()),
    }


def build_backtest() -> dict:
    last = positions.load_last_backtest()
    if not last:
        return {"id": "bt_current", "strategy": "Henüz backtest çalıştırılmadı",
                "period": "Telegram'da /backtest komutuyla çalıştır",
                "metrics": {"trades": 0, "win_rate": 0, "profit_factor": None, "max_drawdown_r": None,
                            "expectancy_r": None, "sharpe": None},
                "equity_curve": [0], "note": "Geçmiş sonuç geleceği garanti etmez."}
    # Net of fee + slippage: the curve the user would actually have lived through.
    trades = [t for t in last.get("islemler", []) if t.get("R_net", t.get("R")) is not None]
    curve, total, peak, max_dd = [0.0], 0.0, 0.0, 0.0
    for t in trades:
        total += t.get("R_net", t["R"])
        curve.append(round(total, 2))
        peak = max(peak, total)
        max_dd = min(max_dd, total - peak)
    wins = [t.get("R_net", t["R"]) for t in trades if t.get("R_net", t["R"]) > 0]
    losses = [t.get("R_net", t["R"]) for t in trades if t.get("R_net", t["R"]) < 0]
    s = last["tum"]
    levels = "ATR varsayılanı" if last.get("atr_varsayilan") else f"iptal {last['iptal']:g} / hedef {last['hedef']:g}"
    return {
        "id": "bt_current",
        "strategy": f"{last['pair']} KAPANIŞ {last['yon']} {last['tetik']:g} {last['timeframe']} ({levels})",
        "period": last["donem"],
        "metrics": {"trades": s["islem"], "win_rate": (s["isabet_yuzde"] or 0) / 100,
                    "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses else None,
                    "max_drawdown_r": round(max_dd, 2), "expectancy_r": s.get("ort_R_net", s["ort_R"]), "sharpe": None},
        "equity_curve": curve,
        "note": "Kapanış bazlı simülasyon: giriş, stop ve hedef sadece mum kapanışıyla sayılır. Net sonuç: her tarafta "
                f"komisyon %{last.get('maliyet', {}).get('komisyon_yuzde', config.BACKTEST_FEE_PCT):g} + kayma "
                f"%{last.get('maliyet', {}).get('kayma_yuzde', config.BACKTEST_SLIPPAGE_PCT):g} düşüldü "
                f"(brüt toplam {s['toplam_R']}R, net {s.get('toplam_R_net')}R). Geçmiş sonuç geleceği garanti etmez.",
    }


def build_overview(pos_docs: list[dict], alert_docs: list[dict], decision_docs: list[dict],
                   m: dict, events: list[dict]) -> dict:
    open_pos = [p for p in pos_docs if p["status"] == "open"]
    today = alerts_store.now_tr().date().isoformat()
    def market_pnl(currency):
        realized = sum(p["pnl"] for p in pos_docs if p["status"] == "closed" and
                       p.get("currency", "USD") == currency and
                       (positions.get(int(p["id"][4:])) or {}).get("kapanis_zamani", "")[:10] == today)
        active = [p for p in open_pos if p.get("currency", "USD") == currency]
        pnl = realized + sum(p["pnl"] for p in active)
        invested = sum(p["entry"] * p["size"] for p in active)
        return round(pnl, 2), round(pnl / invested * 100, 2) if invested else 0.0

    crypto_pnl, crypto_pct = market_pnl("USD")
    bist_pnl, bist_pct = market_pnl("TL")
    open_r = 0.0
    for p in open_pos:
        raw = positions.get(int(p["id"][4:]))
        r = positions.pnl(raw, p["current"])["R"] if raw else None
        open_r += r or 0.0
    highlights = []
    last_dec = next(iter(reversed(positions.load_decisions())), None)
    if last_dec:
        highlights.append({"text": f"Son alarm kararı: {last_dec['pair']} → {last_dec['karar']} "
                                   f"(kapanış {last_dec['kapanis']:g})",
                           "tone": {"AL": "up", "PAS": "down"}.get(last_dec["karar"], "wait")})
    for e in macro.upcoming(events, 48)[:2]:
        t = datetime.fromisoformat(e["tr_zaman"]).strftime("%d.%m %H:%M")
        highlights.append({"text": f"{e['olay']} {t} TR — veriye 2 saat kala yeni giriş yok.", "tone": "wait"})
    btc_note = store.load_state().get("btc_not")
    if btc_note:
        highlights.append({"text": f"BTC kapı: {btc_note}", "tone": "info"})
    bist_candidates = [(sym, plan) for sym, plan in store.load_state()["planlar"].items()
                       if plan.get("bist_aday") and not plan.get("sinyal_verildi")]
    for sym, plan in bist_candidates[:3]:
        highlights.append({"text": f"BIST aday: {sym} · {plan.get('strateji', 'günlük kurulum')} · "
                                   f"tetik {plan['tetik']:g} TL; 1s kapanış bekleniyor.", "tone": "wait"})
    if not highlights:
        highlights.append({"text": "Yeni sinyal yok. Alarmlar kapanış bekliyor.", "tone": "info"})
    rj = m.get("rejim", {})
    return {
        "id": "overview_current", "updated_at": _now_iso(),
        "open_positions": len(open_pos),
        "armed_alerts": sum(a["status"] == "armed" for a in alert_docs),
        "pending_decisions": sum(d["status"] == "pending" for d in decision_docs),
        "day_pnl": crypto_pnl, "day_pnl_pct": crypto_pct,
        "bist_day_pnl": bist_pnl, "bist_day_pnl_pct": bist_pct,
        "open_r": round(open_r, 2),
        "regime_score": rj.get("skor", 0), "regime_label": rj.get("etiket", "hesaplanamadı"),
        "highlights": highlights,
    }


def build_settings() -> dict:
    s = alerts_store.load_settings()
    return {
        "id": "settings_current",
        "risk_per_trade_pct": None,
        "max_open_positions": None,
        "default_rr_min": 1.0,
        "timezone": "Europe/Istanbul",
        "notifications": {"telegram": True, "email": False},
        "params": [
            {"label": "Kısa vadeli bütçe", "value": "~100 USD"},
            {"label": "Varsayılan ilk kademe", "value": f"{config.DEFAULT_TRANCHE_USD} USD"},
            {"label": "BIST bütçesi / ilk kademe", "value":
             f"{bist.budget_tl():,} TL / %{config.BIST_FIRST_TRANCHE_PCT}" if bist.budget_tl() else
             "girilmedi · Telegram: /bist butce 5000"},
            {"label": "BIST net R/R / azami stop riski", "value": f"{config.BIST_MIN_RR:g} / %{config.BIST_MAX_RISK_PCT:g}"},
            {"label": "Minimum R/R", "value": "1.0 (RİSK-OFF'ta 1.5)"},
            {"label": "Ön filtre", "value": "kod" if config.PREFILTER == "kod" else "qwen3 (yerel)"},
            {"label": "Sessiz saatler", "value": s["quiet_hours"] or "kapalı"},
            {"label": "Sessiz günler", "value": ",".join(s["quiet_days"]) or "her gün"},
            {"label": "Sabah brifi", "value": f"{config.BRIEF_HOUR:02d}:{config.BRIEF_MINUTE:02d} TR"},
            {"label": "Analiz modeli", "value": config.DEEPSEEK_MODEL},
        ],
        "rules_readonly": [
            "Dokunma ≠ kapanış: sadece mum kapanışı tetikler, iğne asla.",
            "BTC kapı mantığı: her altcoin kararında BTC ayrıca kontrol edilir.",
            "Goalpost yasağı: açık pozisyonda stop aşağı çekilemez (kod engeller).",
            "R/R 1'in altındaysa pas; RİSK-OFF'ta eşik 1.5.",
            "Stop mesafesi 1×ATR'den darsa gürültü uyarısı.",
            "Kırılım mumunun hacmi Volume MA(20) üstünde olmalı; yoksa 'doğrulanamadı'.",
            "Korelasyonlu coinler tek işlem sayılır; toplam ilk kademe 20-25$.",
            "Spot, kaldıraçsız. 'Kesin kazanç' dili yok.",
            "BIST kararları günlük kurulum ve 1 saatlik kapanış kullanır; Yahoo verisi gecikmelidir.",
        ],
    }


async def _prices(client: httpx.AsyncClient, symbols: set[str]) -> dict[str, float]:
    import assets
    out = {}
    for s in symbols:
        try:
            if s in assets.ASSETS:
                out[s] = await assets.last_price(client, s)
                continue
            if s.upper().endswith(".US"):
                import us
                out[s] = await us.last_price(client, s)
                continue
            out[s] = await (bist.last_price(client, s) if s.upper().endswith(".IS") else market.last_price(client, s))
        except Exception as e:
            log.warning("Price for %s failed: %s", s, e)
    return out


async def push_all():
    """Build every collection from bot state and replace it on the web backend."""
    async with httpx.AsyncClient(timeout=30) as client:
        open_syms = {p["symbol"] for p in positions.open_positions()}
        prices = await _prices(client, open_syms)
        await refresh_outcomes()
        m = await macro.summary()
        events = await macro.calendar()
        alert_docs = build_alerts()
        pos_docs = build_positions(prices)
        decision_docs = build_decisions()
        signal_docs = build_signals()
        chart_pairs = ({"BTC/USDT"} | {a["symbol"] for a in alert_docs if a["status"] == "armed"} |
                       {p["symbol"] for p in pos_docs if p["status"] == "open"} |
                       {s["symbol"] for s in signal_docs[:10]})
        chart_pairs = {p for p in chart_pairs if not p.upper().endswith(".IS")}  # Binance candles only
        collections = {
            "alerts": alert_docs,
            "positions": pos_docs,
            "decisions": decision_docs,
            "signals": signal_docs,
            "candles": await build_candles(client, chart_pairs),
            "macro": [build_macro(m, events)],
            "derivatives": await build_derivatives(client, m),
            "usage": [build_usage()],
            "report": [build_report()],
            "backtest": [build_backtest()],
            "overview": [{**build_overview(pos_docs, alert_docs, decision_docs, m, events),
                          "veri_durumu": await freshness.collect()}],
            "settings": [build_settings()],
        }
        for name, docs in collections.items():
            r = await client.post(f"{config.WEB_URL}/api/ingest/{name}", params={"replace": "true"},
                                  json=docs, headers=_headers())
            r.raise_for_status()
    freshness.mark_push()
    log.info("Web sync: pushed %s", ", ".join(f"{k}={len(v)}" for k, v in collections.items()))


async def push_docs(collection: str, docs: list[dict], replace: bool = False):
    """Send documents to one panel collection (analyses, firsat...). replace=True: the list is the whole collection."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{config.WEB_URL}/api/ingest/{collection}", params={"replace": "true" if replace else "false"},
                              json=docs, headers=_headers())
        r.raise_for_status()


async def user_keys(user_id: str) -> dict | None:
    """A panel user's own AI keys (decrypted by the backend, only while that user has a queued analysis)."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{config.WEB_URL}/api/bot/user-keys/{user_id}", headers=_headers())
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return {k: v for k, v in r.json().items() if k in ("deepseek", "nvidia") and v} or None


_linked_cache: dict[int, tuple[float, bool]] = {}


async def telegram_linked(chat_id: int) -> bool:
    """Is this chat linked to a site account? Cached 5 minutes so a flood of messages is one lookup."""
    now = time.monotonic()
    hit = _linked_cache.get(chat_id)
    if hit and now - hit[0] < 300:
        return hit[1]
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{config.WEB_URL}/api/bot/telegram/linked/{chat_id}", headers=_headers())
    r.raise_for_status()
    linked = bool(r.json().get("bagli"))
    _linked_cache[chat_id] = (now, linked)
    return linked


async def alarm_events() -> list[dict]:
    """Site users' fired alarms waiting for Telegram delivery."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{config.WEB_URL}/api/bot/alarm-events", headers=_headers())
    r.raise_for_status()
    return r.json()


async def alarm_event_sent(event_id: str):
    async with httpx.AsyncClient(timeout=15) as client:
        (await client.post(f"{config.WEB_URL}/api/bot/alarm-events/{event_id}/sent", headers=_headers())).raise_for_status()


async def link_telegram(code: str, chat_id: int, username: str | None) -> tuple[bool, str]:
    """/bagla KOD: ask the web backend to bind this chat to the account that created the one-time code."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{config.WEB_URL}/api/bot/telegram/link", headers=_headers(),
                              json={"code": code, "chat_id": chat_id, "username": username})
    if r.status_code == 200:
        return True, r.json().get("email") or ""
    if r.status_code == 404:
        return False, "Kod geçersiz ya da süresi dolmuş (10 dakika). Siteden yeni kod al."
    r.raise_for_status()
    return False, "Bağlanamadı."


async def telegram_add_position(chat_id: int, code: str, quantity: float, price: float) -> dict:
    """Record a linked user's manually reported BIST purchase on the site."""
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{config.WEB_URL}/api/bot/telegram/position", headers=_headers(),
                              json={"chat_id": chat_id, "piyasa": "BIST", "kod": code,
                                    "adet": quantity, "maliyet": price})
    if r.status_code >= 400:
        if r.status_code == 404:
            raise ValueError("Önce sitede Hesap → Telegram bölümünden hesabını bağla.")
        try:
            detail = r.json().get("detail")
        except (ValueError, TypeError, AttributeError):
            detail = None
        raise ValueError(detail if isinstance(detail, str) else "Portföye eklenemedi; kod, adet ve fiyatı kontrol et.")
    return r.json()


async def telegram_run_strategy(chat_id: int, name: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{config.WEB_URL}/api/bot/telegram/strategy-run", headers=_headers(),
                              json={"chat_id": chat_id, "name": name})
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except (ValueError, TypeError, AttributeError):
            detail = None
        raise ValueError(detail if isinstance(detail, str) else "Strateji başlatılamadı.")
    return r.json()


async def telegram_risk_proposal(chat_id: int) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{config.WEB_URL}/api/bot/telegram/risk-proposal", headers=_headers(),
                              json={"chat_id": chat_id})
    if r.status_code == 404:
        raise ValueError("Önce sitede Hesap → Telegram bölümünden hesabını bağla.")
    r.raise_for_status()
    return r.json()


async def telegram_quant_run(chat_id: int, top_n: int) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{config.WEB_URL}/api/bot/telegram/quant-run", headers=_headers(),
                              json={"chat_id": chat_id, "top_n": top_n})
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except (ValueError, TypeError, AttributeError):
            detail = None
        raise ValueError(detail if isinstance(detail, str) else "Quant taraması başlatılamadı.")
    return r.json()


async def get_strategy(strategy_id: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{config.WEB_URL}/api/bot/strategies/{strategy_id}", headers=_headers())
    r.raise_for_status()
    return r.json()


async def push_extras(doc: dict):
    """Portfolio-level features (benchmark, shadow portfolio, discipline, journal...) as one document."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{config.WEB_URL}/api/ingest/extras", params={"replace": "true"},
                              json=[doc], headers=_headers())
        r.raise_for_status()


# --- panel commands -> bot actions ---------------------------------------------

Notify = Callable[..., Awaitable[None]]  # notify(text, command_meta)
# Panel actions that need the bot's own functions (analysis, plans, paper trades...): main.py registers them.
EXTRA_HANDLERS: dict[str, Callable[[dict], Awaitable[str]]] = {}


def _pair(symbol: str) -> str:
    s = symbol.upper().replace("-", "/").replace(" ", "")
    if "/" not in s:
        s = s[:-len(config.QUOTE)] + "/" + config.QUOTE if s.endswith(config.QUOTE) else f"{s}/{config.QUOTE}"
    return s


async def _apply(cmd: dict, refresh_alerts: Callable[[], None], notify: Notify) -> str:
    """Apply one command. Returns a short result text for the log/Telegram."""
    t, p = cmd["type"], cmd.get("payload") or {}

    if t == "alert.create":
        pair = _pair(p["symbol"])
        direction = "ABOVE" if p.get("side", "long") == "long" else "BELOW"
        tf = p.get("timeframe") or "15m"
        cooldown = (p.get("cooldown") or "1h").lower()
        trigger, stop, target = float(p["entry"]), p.get("stop"), p.get("target")
        above = direction == "ABOVE"
        if tf not in config.ALERT_TIMEFRAMES or not alerts_store.parse_duration(cooldown):
            return f"❌ Panel alarmı reddedildi: geçersiz zaman dilimi/cooldown ({tf}, {cooldown})"
        if stop is not None and (stop >= trigger if above else stop <= trigger):
            return f"❌ Panel alarmı reddedildi: {pair} {direction} için iptal tetiğin {'altında' if above else 'üstünde'} olmalı"
        if target is not None and (target <= trigger if above else target >= trigger):
            return f"❌ Panel alarmı reddedildi: {pair} {direction} için hedef tetiğin {'üstünde' if above else 'altında'} olmalı"
        async with httpx.AsyncClient() as client:
            try:
                price = await market.last_price(client, alerts_store.pair_to_symbol(pair))
            except market.SymbolNotFound:
                return f"❌ Panel alarmı reddedildi: Binance'te {pair} yok"
        # A typo (500 for 500.000) would fire on the next close: refuse levels far from the market.
        if price and not (1 - ALERT_MAX_DISTANCE <= trigger / price <= 1 + ALERT_MAX_DISTANCE):
            return (f"❌ Panel alarmı reddedildi: {pair} tetik {trigger:g}, şu anki fiyat {price:g} "
                    f"(%{abs(trigger / price - 1) * 100:.0f} uzak). Yazım hatası olabilir; kontrol edip tekrar kur.")
        a = alerts_store.add_alert(pair, {"tetik": trigger, "yon": direction, "timeframe": tf,
                                          "cooldown": cooldown, "iptal": stop, "hedef": target,
                                          "hacim_sart": True})
        refresh_alerts()
        return f"⏰ Panelden alarm kuruldu: {pair} #{a['id']} KAPANIŞ {direction} {trigger:g} {tf}"

    if t == "alert.delete":
        m = re.fullmatch(r"(.+)-(\d+)", p["id"])
        if not m:
            return f"❌ Panel: bilinmeyen alarm id {p['id']}"
        base_quote, alert_id = m[1], int(m[2])
        pair = base_quote.replace("-", "/")
        alerts = alerts_store.load_alerts()
        for a in alerts.get(pair, []):
            if a["id"] == alert_id:
                a["durum"], a["iptal_nedeni"] = "iptal", "kullanici"
                alerts_store.save_alerts(alerts)
                refresh_alerts()
                return f"🗑 Panelden alarm silindi: {pair} #{alert_id}"
        return f"❌ Panel: {pair} #{alert_id} bulunamadı"

    if t == "position.stop":
        pos_id = int(str(p["id"]).removeprefix("pos_"))
        pos, err = positions.update(pos_id, stop=float(p["stop"]))
        if err:
            return f"❌ Panel stop güncellemesi reddedildi (#{pos_id}): {err}"
        return f"🔒 Panelden stop güncellendi: #{pos_id} {pos['pair']} stop {pos['stop']:g}"

    if t == "position.close":
        pos_id = int(str(p["id"]).removeprefix("pos_"))
        pos = positions.get(pos_id)
        if not pos or pos["durum"] != "acik":
            return f"❌ Panel: açık pozisyon #{pos_id} yok"
        price = float(p.get("price") or 0)  # the price the user says they sold at
        if price <= 0:
            if pos.get("piyasa") == "BIST":
                return f"❌ Panel: BIST pozisyonu #{pos_id} için gerçekleşen satış fiyatı gerekli"
            async with httpx.AsyncClient() as client:  # no price given: current price of the right market
                price = (await _prices(client, {pos["symbol"]})).get(pos["symbol"], 0)
            if price <= 0:
                return f"❌ Panel: #{pos_id} için güncel fiyat alınamadı, satış fiyatını yazarak tekrar dene"
        when = None
        if p.get("when"):
            try:
                when = datetime.fromisoformat(p["when"]).astimezone(alerts_store.TR).isoformat()
            except ValueError:
                return f"❌ Panel: #{pos_id} için satış zamanı okunamadı"
            if when < pos.get("acilis", ""):
                return f"❌ Panel: #{pos_id} satış zamanı alış zamanından önce olamaz"
        pos = positions.close_position(pos_id, price, "panel", when=when)
        r = positions.pnl(pos, price)
        return (f"💰 Panelden kapatıldı: #{pos_id} {pos['pair']} @ {price:g}"
                + (f" ({datetime.fromisoformat(when).strftime('%d.%m %H:%M')})" if when else "")
                + f": {r['pnl_usd']:+.2f} {pos.get('para', 'USD')}")

    if t == "decision.action":
        dec_id = int(str(p["id"]).removeprefix("dec_"))
        d = positions.get_decision(dec_id)
        if not d:
            return f"❌ Panel: karar #{dec_id} yok"
        if d["aksiyon"]:
            return f"ℹ️ Karar #{dec_id} zaten işaretli ({d['aksiyon']})"
        if p.get("verdict") == "Pas":
            if d.get("piyasa") == "BIST":
                bist_signals.discard_candidate(d["symbol"])
            positions.set_decision_action(dec_id, "pas")
            return f"⏭ Panelden pas: {d['pair']} karar #{dec_id}"
        pos, warning = await gate.record_purchase(d, " (panel)")  # same path as the Telegram button
        amount = (f"{pos['adet']:.0f} adet / {pos['miktar_usd']:g} TL" if d.get("piyasa") == "BIST"
                  else f"{pos['miktar_usd']:g} USD")
        return (f"✅ Panelden 'Aldım': #{pos['id']} {d['pair']} {amount} @ {pos['giris']:g}"
                + (f"\n{warning}" if warning else ""))

    if t in EXTRA_HANDLERS:
        return await EXTRA_HANDLERS[t]({**p, "_komut": command_meta(cmd)})
    return f"❌ Panel: bilinmeyen komut {t}"


SIGNAL_WORDS = {"AL": "alım adayı (karar senin)", "BEKLE": "bekle", "PAS": "pas"}


USER_COMMANDS = {"analysis.request", "strategy.scan"}


def command_meta(cmd: dict) -> dict:
    """Who asked (set by the web backend from the verified session, never by the browser)."""
    return {k: cmd.get(k) for k in ("user_id", "role", "request_id", "telegram_chat_id", "own_keys")}


def allowed(cmd: dict) -> bool:
    """Owner (or commands queued before accounts existed) may do everything; other users only USER_COMMANDS."""
    return cmd.get("role", "owner") == "owner" or cmd.get("type") in USER_COMMANDS


async def process_commands(refresh_alerts: Callable[[], None], notify: Notify) -> int:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{config.WEB_URL}/api/commands/pending", headers=_headers())
        r.raise_for_status()
        pending = r.json()
        for cmd in pending:
            try:
                if not allowed(cmd):  # defence in depth: the backend already refuses these
                    result = f"❌ Panel: {cmd.get('type')} yalnız sistem sahibine açık"
                else:
                    result = await _apply(cmd, refresh_alerts, notify)
            except Exception as e:
                log.exception("Command %s failed", cmd.get("id"))
                result = f"❌ Panel komutu uygulanamadı ({cmd.get('type')}): {e}"
            log.info("Web command %s %s (%s): %s", cmd["id"], cmd["type"], cmd.get("role", "owner"), result[:200])
            await notify(result, command_meta(cmd))
            # Marked done even when rejected, so the panel stops showing it as queued;
            # the Telegram message explains the rejection.
            (await client.post(f"{config.WEB_URL}/api/commands/{cmd['id']}/done", headers=_headers())).raise_for_status()
    return len(pending)

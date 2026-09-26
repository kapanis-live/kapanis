"""US stocks: plan follow-up, close alarms and the US decision gate (medium/long term, DAILY closes).

Runs after the New York close (16:20 ET). A plan is triggered by a daily close above its trigger and confirmed
by the next daily close holding it; then the gate decides:
- S&P 500 / Nasdaq-100 gate not KAPALI, weekly trend up (close above the 10-week average)
- no earnings report within US_EARNINGS_BLOCK_DAYS (overnight gap risk), net R/R >= US_MIN_RR
- discipline shield, US budget (/abd butce), first tranche and max planned risk
Alarms: "AAPL.US" entries in alerts.json, daily close only.
Nothing is ever bought: the result is a message with Aldım / Pas buttons.
"""
import logging
import time
from datetime import date, datetime

import feedparser
import httpx

import alerts_store
import config
import conversation_store as store
import discipline
import market
import positions
import us
import us_fund

log = logging.getLogger(__name__)


def is_us(key: str) -> bool:
    return key.upper().endswith(".US")


def budget_usd() -> float | None:
    v = alerts_store.load_settings().get("abd_butce_usd")
    return float(v) if v else None


def open_us_usd() -> float:
    return sum(p["miktar_usd"] for p in positions.open_positions() if p.get("piyasa") == "ABD" and positions.is_trade(p))


def _check(rule, passed, detail, blocking=True):
    return {"kural": rule, "durum": "gecti" if passed else ("kaldi" if blocking else "uyari"),
            "detay": detail, "engelleyici": blocking}


async def evaluate(client: httpx.AsyncClient, *, t: str, entry: float, iptal: float | None, hedef: float | None,
                   bar=None) -> dict:
    checks = []
    t = us.ticker(t)
    if bar is not None:
        bar_day = datetime.fromtimestamp(int(bar.open_time) / 1000, us.NY).date()
        checks.append(_check("mum güncelliği", bar_day == us.now_ny().date(), f"günlük kapanış {bar_day} (bugünün kapanışı olmalı)"))
    try:
        reg = await us.regime(client)
        checks.append(_check("endeks kapısı", reg["kapi"] != "KAPALI",
                             f"SPY {reg['SPY'].get('durum')} · QQQ {reg['QQQ'].get('durum')} · VIX {(reg.get('VIX') or {}).get('son')}"))
        risk_off = reg["kapi"] != "AÇIK"
    except Exception as e:
        checks.append(_check("endeks kapısı", False, f"doğrulanamadı ({e})"))
        risk_off = True
    try:
        w = await us.fetch(client, t, "1wk", bulk=True)
        ma10 = float(w.close.rolling(10).mean().iloc[-1])
        up = float(w.close.iloc[-1]) > ma10
        checks.append(_check("haftalık trend", up, f"haftalık kapanış {w.close.iloc[-1]:.4g}, 10 haftalık ort. {ma10:.4g}"))
    except Exception as e:
        checks.append(_check("haftalık trend", False, f"doğrulanamadı ({e})"))
    try:
        y = await us_fund.yahoo_summary(client, t)
        nd = y.get("sonraki_bilanco")
        days = (date.fromisoformat(nd) - us.now_ny().date()).days if nd else None
        ok = days is None or days < 0 or days > config.US_EARNINGS_BLOCK_DAYS
        checks.append(_check("bilanço riski", ok, f"sonraki bilanço {nd or 'bilinmiyor'}" + ("" if ok else f" — {days} gün kaldı, boşluk riski")))
    except Exception as e:
        checks.append(_check("bilanço riski", False, f"bilanço tarihi doğrulanamadı ({str(e)[:60]})", blocking=False))
    rr = None
    if iptal is None or hedef is None or entry <= iptal:
        checks.append(_check("R/R", False, "iptal/hedef yok ya da fiyat iptalin altında"))
    else:
        rr = round((hedef - entry) / (entry - iptal), 2)
        checks.append(_check("R/R", rr >= config.US_MIN_RR, f"R/R {rr:.2f}, eşik {config.US_MIN_RR:g} (orta vade, bilanço boşlukları)"))
    d_ok, d_detail = discipline.check("ABD")
    checks.append(_check("disiplin", d_ok, d_detail))
    budget = budget_usd()
    qty, amount = 0.0, 0.0
    if budget is None:
        checks.append(_check("bütçe", False, "ABD bütçesi girilmedi: /abd butce 1000"))
    else:
        cap = budget * config.US_FIRST_TRANCHE_PCT / 100 * (0.6 if risk_off else 1.0)
        room = max(budget * config.US_FIRST_TRANCHE_PCT / 100 - open_us_usd(), 0)
        amount = min(cap, room)
        if iptal is not None and entry > iptal:
            max_risk = budget * config.US_MAX_RISK_PCT / 100
            amount = min(amount, max_risk / ((entry - iptal) / entry))
        qty = round(amount / entry, 4) if entry else 0
        checks.append(_check("bütçe", amount >= 10, f"ilk kademe {amount:,.0f} USD ≈ {qty:g} hisse (kesirli hisse)" if amount >= 10
                             else "kademe dolu ya da risk sınırı çok küçük, pas"))
    ok = all(c["durum"] != "kaldi" for c in checks)
    icon = {"gecti": "✅", "kaldi": "❌", "uyari": "⚠️"}
    return {"ok": ok, "piyasa": "ABD", "sembol": us.key(t), "hisse": t, "giris": entry, "iptal": iptal, "hedef": hedef,
            "rr": rr, "kademe_usd": round(amount, 2), "adet": qty, "risk_off": risk_off, "kurallar": checks,
            "maddeler": [f"{icon[c['durum']]} {c['kural']}: {c['detay']}" for c in checks],
            "kalan": [c["kural"] for c in checks if c["durum"] == "kaldi"],
            "mum_ms": None if bar is None else int(bar.open_time)}


async def daily_check() -> list[dict]:
    """After the US close: move ".US" plans forward on the final daily close."""
    events = []
    state = store.load_state()
    async with httpx.AsyncClient() as client:
        for key, p in list(state["planlar"].items()):
            if not is_us(key) or p.get("pozisyon") or p.get("sinyal_verildi"):
                continue
            try:
                d = market.add_indicators(await us.fetch(client, key, "1d"))
            except Exception as e:
                log.warning("US plan fetch failed for %s: %s", key, e)
                continue
            if len(d) < 2:
                continue
            prev, last = d.iloc[-2], d.iloc[-1]
            bar = int(last.open_time)
            if p.get("son_gun") == bar or datetime.fromtimestamp(bar / 1000, us.NY).date() != us.now_ny().date():
                continue
            p["son_gun"] = bar
            close = float(last.close)
            tetik, teyit, iptal, hedef = (p.get(k) for k in ("tetik", "teyit", "iptal", "hedef"))
            name = us.ticker(key)
            if p.get("bekleyen_teyit"):
                p.pop("bekleyen_teyit", None)
                if teyit is not None and close >= teyit:
                    g = await evaluate(client, t=name, entry=close, iptal=iptal, hedef=hedef, bar=last)
                    events.append({"tur": "kapi", "sembol": key, "kapi": g, "plan": p})
                    if g["ok"]:
                        p["sinyal_verildi"] = True
                else:
                    events.append({"tur": "teyit_bozuldu", "sembol": key, "metin": f"teyit günlük mumu {close:g} ile {teyit} altında kapandı."})
            elif iptal is not None and prev.close >= iptal > close:
                events.append({"tur": "iptal", "sembol": key, "metin": f"günlük kapanış {close:g} İPTAL {iptal:g} altında: plan bozuldu."})
            elif tetik is not None and prev.close <= tetik < close:
                p["bekleyen_teyit"] = bar
                events.append({"tur": "tetik", "sembol": key, "metin": f"günlük kapanış {close:g} TETİK {tetik:g} üstünde; yarınki kapanış teyit."})
            elif hedef is not None and prev.close < hedef <= close:
                events.append({"tur": "hedef", "sembol": key, "metin": f"günlük kapanış {close:g} HEDEF {hedef:g} üstünde."})
    fresh = store.load_state()
    for key, p in state["planlar"].items():
        if is_us(key) and key in fresh["planlar"]:
            for k in ("son_gun", "bekleyen_teyit", "sinyal_verildi"):
                if k in p:
                    fresh["planlar"][key][k] = p[k]
                else:
                    fresh["planlar"][key].pop(k, None)
    store.save_state(fresh)
    return events


async def check_alarms() -> tuple[list, list]:
    """US close-only alarms on daily bars. Same shape as bist_signals.check_alarms."""
    fired, notices = [], []
    alerts = alerts_store.load_alerts()
    now = alerts_store.now_tr()
    async with httpx.AsyncClient() as client:
        for pair, items in alerts.items():
            if not is_us(pair):
                continue
            for a in items:
                if a["durum"] not in alerts_store.ACTIVE_STATES:
                    continue
                try:
                    df = market.add_indicators(await us.fetch(client, pair, "1d"))
                except Exception as e:
                    log.warning("US alarm fetch failed for %s: %s", pair, e)
                    continue
                if df.empty or a.get("son_mum") == int(df.iloc[-1].open_time):
                    continue
                last = df.iloc[-1]
                a["son_mum"] = int(last.open_time)
                close = float(last.close)
                long = a["yon"] == "ABOVE"
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


async def record_purchase(d: dict) -> tuple[dict, str | None]:
    """"Aldım" on a US decision: the tranche in USD at the live price (fractional shares)."""
    async with httpx.AsyncClient() as client:
        price = await us.last_price(client, d["symbol"])
    usd = float(d.get("kademe_usd") or 0) or 50.0
    pos = positions.open_position(d["pair"], price, usd, d.get("iptal"), d.get("hedef"), "1d",
                                  source=f"ABD karar #{d['id']}", decision_id=d["id"], market_name="ABD", symbol=d["symbol"])
    positions.update(pos["id"], para="USD")
    positions.set_decision_action(d["id"], "aldi")
    return positions.get(pos["id"]), None


async def news(t: str, limit: int = 6) -> list[dict]:
    """English headlines for a ticker (Google News RSS, free). Titles only: verify before acting."""
    async with httpx.AsyncClient() as client:
        r = await client.get("https://news.google.com/rss/search", params={"q": f"{us.ticker(t)} stock", "hl": "en-US",
                                                                         "gl": "US", "ceid": "US:en"},
                             timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Kapanis)"})
    out = []
    for e in feedparser.parse(r.content).entries[:limit]:
        title = (e.get("title") or "").strip()
        src = (e.get("source") or {}).get("title") or title.rsplit(" - ", 1)[-1]
        out.append({"baslik": title.rsplit(" - ", 1)[0], "kaynak": src,
                    "zaman": time.strftime("%d.%m %H:%M", e.published_parsed) if e.get("published_parsed") else None})
    return out


async def market_data(t: str) -> dict:
    """Everything the AI gets for a US stock: engine report, zones, regime, news, budget."""
    t = us.ticker(t)
    rep = await us_fund.report(t)
    async with httpx.AsyncClient() as client:
        d = market.add_indicators(await us.fetch(client, t, "1d"))
        w = market.add_indicators(await us.fetch(client, t, "1wk", bulk=True))
        reg = await us.regime(client)
    zones = market.sr_zones(d, w, float(d.close.iloc[-1]), float(d.atr14.iloc[-1]))
    try:
        headlines = await news(t)
    except Exception as e:
        headlines = [{"hata": str(e)[:60]}]
    return {"ABD_HISSE": {"hisse": t, "gunluk": market.summarize(d, with_vwap=False),
                          "haftalik": market.summarize(w, with_vwap=False), "destek_direnc": zones},
            "ABD_TEMEL": rep, "ABD_PIYASA": reg, "ABD_HABERLER": headlines,
            "ABD_BUTCE": {"usd": budget_usd(), "ilk_kademe_yuzde": config.US_FIRST_TRANCHE_PCT,
                          "azami_risk_yuzde": config.US_MAX_RISK_PCT, "acik_usd": round(open_us_usd(), 2)}}

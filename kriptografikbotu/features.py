"""Panel-era features, all computed in code (the AI only writes the weekly lesson):

- plans for the panel (saved plan levels + live price + distances)
- portfolio history: one snapshot per day, plus a 90-day backfill of today's holdings
- target allocation per market and drift warnings (never a buy/sell suggestion)
- company calendar: next earnings and ex-dividend dates (Yahoo) for holdings and the watchlist
- KAP disclosures for held BIST stocks (kap.org.tr public query, free)
- watchlist condition rules (near support, RSI extremes, volume spike) -> one grouped message
- weekly lesson data (rule stats, missed/avoided signals, most frequent mistake)
- paper trading (sanal işlem): tracked like a position, never counted in the real portfolio
"""
import json
import logging
import math
import time
from datetime import datetime, timedelta

import httpx

import alerts_store
import assets
import balance
import bist
import config
import conversation_store as store
import gate
import journal
import market
import positions
import us

log = logging.getLogger(__name__)
D = config.DATA_DIR
HISTORY = D / "pf_history.json"
CALENDAR = D / "sirket_takvimi.json"
KAP_SEEN = D / "kap_seen.json"
PAPER = D / "sanal.json"
UA = {"User-Agent": "Mozilla/5.0 (Kapanis)"}


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _today() -> str:
    return alerts_store.now_tr().date().isoformat()


def market_of_key(key: str) -> tuple[str, str]:
    """Plan key -> (market, code): "THYAO.IS" -> BIST, "NVDA.US" -> ABD, "BTC" -> KRIPTO."""
    if key.upper().endswith(".IS"):
        return "BIST", key[:-3].upper()
    if key.upper().endswith(".US"):
        return "ABD", key[:-3].upper()
    return "KRIPTO", key.upper()


async def last_price(client: httpx.AsyncClient, mkt: str, code: str) -> float:
    if mkt == "BIST":
        return float((await bist.day_quote(client, code))["fiyat"])
    if mkt == "ABD":
        return float(await us.last_price(client, code))
    return float(await market.last_price(client, code + config.QUOTE))


# ---------------------------------------------------------------- plans --------------------------------------------

def _pct(a, b):
    return round((a / b - 1) * 100, 2) if a and b else None


async def plans_for_panel(chosen: list[str]) -> list[dict]:
    """Every saved plan with live price and the distance to trigger / cancel / target."""
    state = store.load_state()
    out = []
    async with httpx.AsyncClient() as client:
        keys = list(dict.fromkeys(list(state["planlar"]) + list(chosen)))
        for key in keys:
            mkt, code = market_of_key(key)
            p = state["planlar"].get(key)
            try:
                price = await last_price(client, mkt, code)
            except Exception as e:
                log.warning("Plan price %s failed: %s", key, e)
                price = None
            row = {"key": key, "kod": code, "piyasa": mkt, "fiyat": price, "listede": key in chosen, "plan": bool(p)}
            if p:
                row.update(tetik=p.get("tetik"), teyit=p.get("teyit"), iptal=p.get("iptal"), hedef=p.get("hedef"),
                           not_=p.get("not"), pozisyon=bool(p.get("pozisyon")),
                           guncelleme=datetime.fromtimestamp(p["guncelleme"]).isoformat() if p.get("guncelleme") else None,
                           tetige=_pct(p.get("tetik"), price), iptale=_pct(p.get("iptal"), price), hedefe=_pct(p.get("hedef"), price))
                t, i, h = p.get("tetik"), p.get("iptal"), p.get("hedef")
                if price is None:
                    durum = "veri yok"
                elif i and price < i:
                    durum = "bozuldu"
                elif h and price >= h:
                    durum = "hedefte"
                elif t and price >= t:
                    durum = "tetiğin üstünde"
                elif t and price >= t * 0.98:
                    durum = "tetiğe yakın"
                else:
                    durum = "bekliyor"
                row["durum"] = durum
            out.append(row)
    return out


# ---------------------------------------------------------------- portfolio history --------------------------------

def record_history(pf: dict):
    """One snapshot per day (latest wins): value per market, cost, USD/TRY and a TL total."""
    usd = pf.get("usdtry")
    day = {"usdtry": usd, "piyasa": {}}
    total_tl = 0.0
    for m, t in (pf.get("toplam") or {}).items():
        day["piyasa"][m] = {"deger": round(t["deger"], 2), "maliyet": round(t["maliyet"], 2), "para": t["para"]}
        total_tl += t["deger"] * (usd if t["para"] == "USD" and usd else 1)
    day["toplam_tl"] = round(total_tl, 2) if usd or all(t["para"] != "USD" for t in (pf.get("toplam") or {}).values()) else None
    h = _load(HISTORY, {"gunluk": {}, "geriye": None})
    h["gunluk"][_today()] = day
    _save(HISTORY, h)


async def backfill_history(days: int = 90) -> dict:
    """What today's holdings were worth each day of the last 90 days (TL), plus BIST 100 and USD/TRY.
    Cached once a day; imported holdings have no purchase date, so this is a 'current holdings' view."""
    h = _load(HISTORY, {"gunluk": {}, "geriye": None})
    if h.get("geriye") and h["geriye"].get("tarih") == _today() and h["geriye"].get("surum") == 3:
        return h["geriye"]
    open_pos = [p for p in positions.open_positions() if p.get("piyasa", "KRIPTO") in ("BIST", "KRIPTO", "ABD")]
    quotes = []
    async with httpx.AsyncClient() as client:
        async def closes(mkt, sym):
            if mkt == "BIST":
                df = await bist.fetch(client, sym, "1d")
            elif mkt == "ABD":
                df = await us.fetch(client, sym, "1d", bulk=True)
            else:
                df = await market.fetch_klines(client, sym, "1d", limit=days + 5)
            return {datetime.fromtimestamp(int(t) / 1000).date().isoformat(): float(c)
                    for t, c in zip(df.open_time.tail(days + 5), df.close.tail(days + 5))}
        fx = await closes("BIST", "USDTRY=X")
        index = await closes("BIST", bist.INDEX)
        try:
            gold = await closes("BIST", "GC=F")
        except Exception as e:
            log.warning("Gold history failed: %s", e)
            gold = {}
        for p in open_pos:
            mkt = p.get("piyasa", "KRIPTO")
            c = await closes(mkt, p["symbol"])
            if not c:
                raise ValueError(f"History has no closes for {p['symbol']}")
            quotes.append((mkt, float(p["adet"]), c))
    start = (alerts_store.now_tr().date() - timedelta(days=days)).isoformat()
    dates = sorted(d for d in set(fx) | set(index) | set(gold) | {d for _, _, c in quotes for d in c} if d <= _today())
    last_fx = last_index = last_gold = None
    last_prices = [None] * len(quotes)
    rows = []
    for d in dates:
        last_fx = fx.get(d, last_fx)
        last_index = index.get(d, last_index)
        last_gold = gold.get(d, last_gold)
        for n, (_, _, c) in enumerate(quotes):
            last_prices[n] = c.get(d, last_prices[n])
        # A market holiday keeps the last actual close. Before a symbol's first
        # available close, a complete portfolio value cannot be established.
        if d < start or not last_fx or any(px is None for px in last_prices):
            continue
        s = {"BIST": 0.0, "KRIPTO": 0.0, "ABD": 0.0}
        for (mkt, qty, _), px in zip(quotes, last_prices):
            s[mkt] += qty * px
        rows.append({"tarih": d, "bist": round(s["BIST"], 2), "kripto_usd": round(s["KRIPTO"], 2), "abd_usd": round(s["ABD"], 2),
                     "toplam_tl": round(s["BIST"] + (s["KRIPTO"] + s["ABD"]) * last_fx, 2), "usdtry": last_fx,
                     "xu100": last_index,
                     "gram_altin": round(last_gold * last_fx / assets.OUNCE_GRAMS, 2) if last_gold else None})
    h["geriye"] = {"tarih": _today(), "surum": 3, "satirlar": rows}
    _save(HISTORY, h)
    return h["geriye"]


def history_for_panel() -> dict:
    h = _load(HISTORY, {"gunluk": {}, "geriye": None})
    return {"gunluk": [{"tarih": k, **v} for k, v in sorted(h["gunluk"].items())][-365:],
            "geriye": (h.get("geriye") or {}).get("satirlar", [])}


# ---------------------------------------------------------------- target allocation --------------------------------

TARGET_KEYS = ("BIST", "KRIPTO", "ABD", "NAKIT")


def target() -> dict | None:
    return alerts_store.load_settings().get("hedef_dagilim")


def set_target(weights: dict, tolerance: float = 5) -> dict:
    w = {k: float(weights.get(k) or 0) for k in TARGET_KEYS}
    if any(not math.isfinite(v) or v < 0 for v in w.values()) or not math.isfinite(tolerance) or not 0 <= tolerance <= 100:
        raise ValueError("hedefler ve tolerans 0–100 arasında olmalı")
    total = sum(w.values())
    if total <= 0:
        raise ValueError("hedef yüzdeleri boş")
    w = {k: round(v * 100 / total, 1) for k, v in w.items()}
    w[max(w, key=w.get)] = round(w[max(w, key=w.get)] + 100 - sum(w.values()), 1)
    s = alerts_store.load_settings()
    s["hedef_dagilim"] = {**w, "tolerans": float(tolerance)}
    alerts_store.save_settings(s)
    return s["hedef_dagilim"]


def allocation(pf: dict) -> dict | None:
    """Actual weights (TL) vs target. Cash comes from /bakiye nakit. Never suggests a trade: only the drift."""
    tgt = target()
    usd = pf.get("usdtry")
    if not usd:
        return None
    val = {k: 0.0 for k in TARGET_KEYS}
    for m, t in (pf.get("toplam") or {}).items():
        if m in val:
            val[m] += t["deger"] * (usd if t["para"] == "USD" else 1)
    for m, amount in balance.cash().items():
        val["NAKIT"] += float(amount) * (usd if m in ("KRIPTO", "ABD") else 1)
    total = sum(val.values())
    if not total:
        return None
    rows = []
    for k in TARGET_KEYS:
        actual = val[k] / total * 100
        goal = (tgt or {}).get(k)
        drift = None if goal is None else round(actual - goal, 1)
        rows.append({"piyasa": k, "deger_tl": round(val[k], 2), "gercek": round(actual, 1), "hedef": goal, "sapma": drift})
    tol = (tgt or {}).get("tolerans", 5)
    return {"satirlar": rows, "toplam_tl": round(total, 2), "tolerans": tol, "hedef_var": bool(tgt),
            "asanlar": [r for r in rows if r["sapma"] is not None and abs(r["sapma"]) > tol]}


def allocation_text(a: dict) -> str | None:
    if not a or not a["asanlar"]:
        return None
    name = {"BIST": "BIST", "KRIPTO": "Kripto", "ABD": "ABD", "NAKIT": "Nakit"}
    lines = [f"⚖️ HEDEF DAĞILIMDAN SAPMA (tolerans ±{a['tolerans']:g} puan)"]
    for r in a["asanlar"]:
        lines.append(f"{name[r['piyasa']]}: şu an %{r['gercek']:g}, hedef %{r['hedef']:g} → {r['sapma']:+.1f} puan "
                     + ("fazla" if r["sapma"] > 0 else "eksik"))
    lines.append("Bu bir hatırlatmadır; alım-satım önerisi değildir. Hedefi değiştirmek: /hedef")
    return "\n".join(lines)


# ---------------------------------------------------------------- company calendar ---------------------------------

_crumb: tuple | None = None


async def _yahoo_calendar(client: httpx.AsyncClient, ysym: str) -> dict:
    global _crumb
    if _crumb is None or time.time() - _crumb[0] > 3600:
        async with httpx.AsyncClient(headers=UA, follow_redirects=True, timeout=20) as c:
            await c.get("https://fc.yahoo.com")
            _crumb = (time.time(), (await c.get("https://query2.finance.yahoo.com/v1/test/getcrumb")).text, dict(c.cookies))
    r = await client.get("https://query2.finance.yahoo.com/v10/finance/quoteSummary/" + ysym,
                         params={"modules": "calendarEvents", "crumb": _crumb[1]}, headers=UA, cookies=_crumb[2], timeout=20)
    r.raise_for_status()
    res = (r.json().get("quoteSummary") or {}).get("result") or [{}]
    ce = res[0].get("calendarEvents") or {}
    earn = [d.get("fmt") for d in (ce.get("earnings") or {}).get("earningsDate", []) if d.get("fmt")]
    return {"bilanco": earn[0] if earn else None, "temettu_hak": (ce.get("exDividendDate") or {}).get("fmt"),
            "temettu_odeme": (ce.get("dividendDate") or {}).get("fmt")}


def _calendar_codes(watch: dict) -> list[tuple[str, str]]:
    held = [(p.get("piyasa"), bist.ticker(p["symbol"]) if p.get("piyasa") == "BIST" else us.ticker(p["symbol"]))
            for p in positions.open_positions() if p.get("piyasa") in ("BIST", "ABD")]
    listed = [("BIST", c) for c in watch.get("BIST", [])] + [("ABD", c) for c in watch.get("ABD", [])]
    return list(dict.fromkeys(held + listed))


async def refresh_calendar(watch: dict) -> dict:
    """Once a day: next earnings / ex-dividend date for holdings and watchlist stocks."""
    cal = _load(CALENDAR, {"tarih": None, "kalemler": [], "hatirlatilan": []})
    if cal.get("tarih") == _today():
        return cal
    held = {(p.get("piyasa"), bist.ticker(p["symbol"]) if p.get("piyasa") == "BIST" else us.ticker(p["symbol"]))
            for p in positions.open_positions()}
    items = []
    async with httpx.AsyncClient() as client:
        for mkt, code in _calendar_codes(watch):
            try:
                ev = await _yahoo_calendar(client, code + ".IS" if mkt == "BIST" else code)
            except Exception as e:
                log.warning("Calendar %s failed: %s", code, e)
                continue
            for kind, label in (("bilanco", "Bilanço"), ("temettu_hak", "Temettü hak kullanım"), ("temettu_odeme", "Temettü ödeme")):
                if ev.get(kind) and ev[kind] >= _today():
                    items.append({"kod": code, "piyasa": mkt, "tur": kind, "etiket": label, "tarih": ev[kind],
                                  "portfoyde": (mkt, code) in held})
    items.sort(key=lambda x: (x["tarih"], not x["portfoyde"], x["kod"]))
    cal = {"tarih": _today(), "kalemler": items, "hatirlatilan": cal.get("hatirlatilan", [])[-300:]}
    _save(CALENDAR, cal)
    return cal


def calendar_for_panel(days: int = 45) -> list[dict]:
    cal = _load(CALENDAR, {"kalemler": []})
    until = (alerts_store.now_tr().date() + timedelta(days=days)).isoformat()
    return [i for i in cal.get("kalemler", []) if _today() <= i["tarih"] <= until][:60]


def calendar_reminders() -> str | None:
    """Events tomorrow (or today, if not yet told) for things the user holds or watches. Marks them as told."""
    cal = _load(CALENDAR, {"kalemler": [], "hatirlatilan": []})
    tomorrow = (alerts_store.now_tr().date() + timedelta(days=1)).isoformat()
    due = [i for i in cal.get("kalemler", []) if i["tarih"] in (_today(), tomorrow)
           and f"{i['kod']}|{i['tur']}|{i['tarih']}" not in cal.get("hatirlatilan", [])]
    if not due:
        return None
    lines = ["📅 YAKLAŞAN ŞİRKET OLAYLARI"]
    for i in due:
        when = "yarın" if i["tarih"] == tomorrow else "bugün"
        lines.append(f"{'💼 ' if i['portfoyde'] else ''}{i['kod']} ({i['piyasa']}): {i['etiket']} {when} ({i['tarih']})")
        cal.setdefault("hatirlatilan", []).append(f"{i['kod']}|{i['tur']}|{i['tarih']}")
    lines.append("Bilanço günü fiyat sert oynayabilir (gap). Tarihler Yahoo'dan; kesin tarih için KAP / şirket.")
    _save(CALENDAR, cal)
    return "\n".join(lines)


# ---------------------------------------------------------------- KAP ------------------------------------------------

KAP_URL = "https://www.kap.org.tr/tr/api/disclosure/members/byCriteria"


async def kap_new(codes: set[str]) -> list[dict]:
    """New KAP disclosures today for the given BIST codes (each told once)."""
    if not codes:
        return []
    day = alerts_store.now_tr().date().isoformat()
    body = {"fromDate": day, "toDate": day, "memberTypes": ["IGS"], "mkkMemberOidList": [], "inactiveMkkMemberOidList": [],
            "disclosureClass": "", "subjectList": [], "isLate": "", "mainSector": "", "sector": "", "subSector": "",
            "marketOidList": [], "index": "", "bdkReview": "", "bdkMemberOidList": [], "year": "", "term": "",
            "ruleType": "", "period": "", "fromSrc": False, "srcCategory": "", "discIndex": []}
    async with httpx.AsyncClient() as client:
        r = await client.post(KAP_URL, json=body, headers={**UA, "Accept": "application/json"}, timeout=25)
        r.raise_for_status()
        rows = r.json()
    seen = _load(KAP_SEEN, {"ids": [], "son": []})
    fresh = []
    for d in rows:
        stock = {c.strip() for c in (d.get("stockCodes") or "").split(",") if c.strip()}
        hit = stock & codes
        if not hit or d["disclosureIndex"] in seen["ids"]:
            continue
        seen["ids"].append(d["disclosureIndex"])
        item = {"id": d["disclosureIndex"], "kodlar": sorted(hit), "zaman": d.get("publishDate"), "konu": d.get("subject"),
                "ozet": d.get("summary"), "sirket": d.get("kapTitle"), "link": f"https://www.kap.org.tr/tr/Bildirim/{d['disclosureIndex']}"}
        fresh.append(item)
        seen["son"].append(item)
    seen["ids"] = seen["ids"][-2000:]
    seen["son"] = seen["son"][-40:]
    _save(KAP_SEEN, seen)
    return fresh


def kap_text(items: list[dict]) -> str:
    lines = ["📢 KAP BİLDİRİMİ (portföyündeki hisse)"]
    for i in items:
        lines.append(f"{', '.join(i['kodlar'])} · {i['zaman']}\n{i['konu']}" + (f" — {i['ozet']}" if i.get("ozet") else "") + f"\n{i['link']}")
    return "\n\n".join(lines)


def kap_for_panel() -> list[dict]:
    return list(reversed(_load(KAP_SEEN, {"son": []}).get("son", [])))[:20]


# ---------------------------------------------------------------- watchlist rules ----------------------------------

RULE_DEFAULTS = {"aktif": True, "destek_yakin": 1.5, "rsi_alti": 30, "rsi_ustu": 75, "hacim_kat": 2.0}
RULE_LABELS = {"destek_yakin": "desteğe yakın", "rsi_alti": "RSI düşük (çok satılmış)", "rsi_ustu": "RSI yüksek (ısınmış)",
               "hacim_kat": "hacim patlaması"}


def watch_rules() -> dict:
    return {**RULE_DEFAULTS, **(alerts_store.load_settings().get("takip_kurallari") or {})}


def set_watch_rules(**kw) -> dict:
    s = alerts_store.load_settings()
    cur = {**RULE_DEFAULTS, **(s.get("takip_kurallari") or {})}
    for k, v in kw.items():
        if k in RULE_DEFAULTS and v is not None:
            if k == "aktif":
                cur[k] = bool(v)
            else:
                n = float(v)
                limit = 100 if k != "hacim_kat" else 1000
                if not math.isfinite(n) or not 0 <= n <= limit:
                    raise ValueError(f"{k} 0–{limit} arasında olmalı")
                cur[k] = n
    s["takip_kurallari"] = cur
    alerts_store.save_settings(s)
    return cur


def check_watch_rules(rows_by_market: dict) -> str | None:
    """Rows from watchlist.rows(); each code+rule is told at most once a day."""
    rules = watch_rules()
    if not rules["aktif"]:
        return None
    s = alerts_store.load_settings()
    told = s.get("takip_kural_bildirilen", {})
    today = _today()
    told = {k: v for k, v in told.items() if v == today}
    hits = []
    for mkt, rows in rows_by_market.items():
        for r in rows:
            if "hata" in r or r.get("kapanis_fiyat") is None:
                continue
            found = []
            if rules.get("destek_yakin") and r.get("kapanis_destek_yuzde") is not None and -rules["destek_yakin"] <= r["kapanis_destek_yuzde"] <= 0:
                found.append(("destek_yakin", f"desteğe %{abs(r['kapanis_destek_yuzde']):.1f} ({r['kapanis_destek']:g})"))
            if rules.get("rsi_alti") and r.get("rsi") is not None and r["rsi"] <= rules["rsi_alti"]:
                found.append(("rsi_alti", f"RSI {r['rsi']}"))
            if rules.get("rsi_ustu") and r.get("rsi") is not None and r["rsi"] >= rules["rsi_ustu"]:
                found.append(("rsi_ustu", f"RSI {r['rsi']}"))
            if rules.get("hacim_kat") and r.get("hacim_kat") and r["hacim_kat"] >= rules["hacim_kat"]:
                found.append(("hacim_kat", f"hacim ortalamanın {r['hacim_kat']:.1f} katı"))
            for rule, detail in found:
                key = f"{mkt}|{r['kod']}|{rule}"
                if key in told:
                    continue
                told[key] = today
                hits.append(f"{r['kod']} ({mkt}): {RULE_LABELS[rule]} · {detail} · son kapanış {r['kapanis_fiyat']:g}")
    s["takip_kural_bildirilen"] = told
    alerts_store.save_settings(s)
    if not hits:
        return None
    return ("🔔 TAKİP LİSTESİ KURALLARI\n" + "\n".join(hits[:25]) + (f"\n… ve {len(hits) - 25} tane daha" if len(hits) > 25 else "")
            + "\nBu bir izleme uyarısıdır, AL sinyali değildir. Kuralları değiştir: /takip kural")


# ---------------------------------------------------------------- weekly lesson ------------------------------------

def lesson_data(days: int = 7) -> dict:
    """What the week taught, from code: which gate rule separated winners, AL signals you passed on that hit target,
    buys against the bot that lost, and the most frequent journal mistake."""
    since = (alerts_store.now_tr() - timedelta(days=days)).isoformat()
    decs = positions.load_decisions()
    week = [d for d in decs if d.get("zaman", "") >= since]
    outcome = lambda d: (d.get("sonuc") or {}).get("sonuc")
    missed = [{"kod": d["pair"], "karar": d.get("karar"), "R": (d.get("sonuc") or {}).get("R")}
              for d in week if d.get("karar") in ("AL", "ŞİMDİ AL") and d.get("aksiyon") == "pas" and outcome(d) == "hedef"]
    avoided = [{"kod": d["pair"], "karar": d.get("karar")} for d in week
               if d.get("karar") in ("AL", "ŞİMDİ AL") and d.get("aksiyon") == "pas" and outcome(d) == "stop"]
    against = [{"kod": d["pair"], "karar": d.get("karar"), "sonuc": outcome(d)} for d in week
               if d.get("karar") not in ("AL", "ŞİMDİ AL") and d.get("aksiyon") == "aldi"]
    closed = [p for p in positions.load() if p["durum"] == "kapali" and p.get("kapanis_zamani", "") >= since]
    trades = []
    for p in closed:
        r = positions.pnl(p, p["kapanis_fiyat"])
        trades.append({"kod": p["pair"], "sonuc": r["pnl_yuzde"], "R": r["R"]})
    return {"gun": days, "karar_sayisi": len(week),
            "sonuclanan": sum(1 for d in week if outcome(d) in ("hedef", "stop")),
            "kural_istatistik": gate.rule_stats(week),
            "kacirilan_al": missed, "iyi_ki_pas": avoided, "bota_karsi_alim": against,
            "kapanan_islemler": trades, "gunluk": journal.summary(since)}


# ---------------------------------------------------------------- paper trading ------------------------------------

def paper_all() -> list[dict]:
    return _load(PAPER, [])


def paper_open(mkt: str, code: str, price: float, qty: float, note: str = "") -> dict:
    if mkt not in ("KRIPTO", "BIST", "ABD") or not code or not all(math.isfinite(float(v)) and float(v) > 0 for v in (price, qty)):
        raise ValueError("piyasa, kod, fiyat ve adet geçerli olmalı")
    if mkt == "BIST" and not float(qty).is_integer():
        raise ValueError("BIST sanal işlem adedi tam sayı olmalı")
    items = paper_all()
    p = {"id": max([x["id"] for x in items] + [0]) + 1, "piyasa": mkt, "kod": code.upper(), "giris": float(price),
         "adet": float(qty), "acilis": alerts_store.now_tr().isoformat(), "durum": "acik", "not": note}
    items.append(p)
    _save(PAPER, items)
    return p


def paper_close(pid: int, price: float) -> dict | None:
    if not math.isfinite(float(price)) or float(price) <= 0:
        raise ValueError("satış fiyatı sıfırdan büyük olmalı")
    items = paper_all()
    for p in items:
        if p["id"] == pid and p["durum"] == "acik":
            p.update(durum="kapali", cikis=float(price), kapanis=alerts_store.now_tr().isoformat())
            _save(PAPER, items)
            return p
    return None


async def paper_view() -> list[dict]:
    out = []
    async with httpx.AsyncClient() as client:
        for p in paper_all():
            price = p.get("cikis")
            if p["durum"] == "acik":
                try:
                    price = await last_price(client, p["piyasa"], p["kod"])
                except Exception:
                    price = None
            cur = "TL" if p["piyasa"] == "BIST" else "USD"
            pnl = (price - p["giris"]) * p["adet"] if price is not None else None
            out.append({**p, "fiyat": price, "para": cur, "kz": round(pnl, 2) if pnl is not None else None,
                        "kz_yuzde": _pct(price, p["giris"]) if price is not None else None})
    return out


def paper_text(rows: list[dict]) -> str:
    if not rows:
        return ("🧪 Sanal işlem yok.\nGerçek para koymadan dene: /sanal al KOD FIYAT TUTAR\n"
                "Örnek: /sanal al THYAO 290 5000 (5000 TL'lik) · /sanal al BTC 84000 100 (100 USD'lik) · /sanal al NVDA 225 adet=3")
    lines = ["🧪 SANAL İŞLEMLER (gerçek portföyde sayılmaz)"]
    for r in rows:
        k = "—" if r["kz"] is None else f"{r['kz']:+,.2f} {r['para']} ({r['kz_yuzde']:+.2f}%)"
        state = "açık" if r["durum"] == "acik" else f"kapandı @ {r['cikis']:g}"
        lines.append(f"#{r['id']} {r['kod']} ({r['piyasa']}) {r['adet']:g} adet @ {r['giris']:g} → "
                     f"{'—' if r['fiyat'] is None else format(r['fiyat'], 'g')} · {k} · {state}")
    opened = [r for r in rows if r["durum"] == "acik" and r["kz"] is not None]
    if opened:
        by = {}
        for r in opened:
            by[r["para"]] = by.get(r["para"], 0) + r["kz"]
        lines.append("Açık toplam: " + " · ".join(f"{v:+,.2f} {k}" for k, v in by.items()))
    lines.append("Kapat: /sanal sat ID [FIYAT] · Yeni: /sanal al KOD FIYAT TUTAR")
    return "\n".join(lines)

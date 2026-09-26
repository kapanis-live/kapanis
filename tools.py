"""Decision tools, all computed in code (no AI):

- pre-trade check: run the market's own decision gate for a price/stop/target the user is about to use
- indicator alarms: close crosses an SMA, RSI crosses a level, volume crosses N x its 20-bar average
- stock comparison: 2-4 BIST or US stocks side by side (fundamental score, growth, margins, debt, valuation, trend)
- dividend income plan: trailing 12-month dividends of held stocks, projected month by month (gross)

None of these trades or turns into a buy signal: every message says what the code measured, nothing more.
"""
import json
import logging
import math
import time
from datetime import date, datetime, timedelta

import httpx

import alerts_store
import bist
import bist_signals
import config
import corporate
import fundamentals
import gate
import market
import positions
import us
import us_fund
import us_signals

log = logging.getLogger(__name__)
D = config.DATA_DIR
IND_ALERTS = D / "gosterge_alarmlari.json"
DIV_CACHE = D / "temettu_plani.json"
MARKETS = ("KRIPTO", "BIST", "ABD")
CUR = {"KRIPTO": "USD", "BIST": "TL", "ABD": "USD"}


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _ok_num(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def _nan(x) -> bool:
    return x is None or x != x


# ---------------------------------------------------------------- pre-trade check ----------------------------------

async def _suggest(client: httpx.AsyncClient, mkt: str, code: str, price: float) -> tuple[float, float]:
    """Stop under the nearest daily support zone, target at the nearest resistance (same idea as /portfoy ekle)."""
    if mkt == "KRIPTO":
        d = market.add_indicators(await market.fetch_klines(client, code + config.QUOTE, "4h"))
    elif mkt == "BIST":
        d = market.add_indicators(await bist.fetch(client, code, "1d"))
    else:
        d = market.add_indicators(await us.fetch(client, code, "1d"))
    last = d.iloc[-1]
    atr = float(last.atr14) if not _nan(last.atr14) else price * 0.03
    z = market.sr_zones(d, None, price, atr, top=1)
    stop = z["destekler"][0]["alt"] - 0.25 * atr if z["destekler"] else price - 2 * atr
    target = z["direncler"][0]["orta"] if z["direncler"] else price + 3 * atr
    digits = 2 if price >= 10 else 4 if price >= 0.1 else 8
    return round(stop, digits), round(target, digits)


async def pre_trade(mkt: str, code: str, entry: float | None = None, stop: float | None = None,
                    target: float | None = None) -> dict:
    """The same gate a bot signal goes through, for a trade the user is planning by hand.
    Missing entry = live price; missing stop/target = suggested from support/resistance zones (marked as such)."""
    if mkt not in MARKETS:
        raise ValueError("piyasa KRIPTO, BIST ya da ABD olmalı")
    for v in (entry, stop, target):
        if v is not None and (not _ok_num(v) or v <= 0):
            raise ValueError("fiyat, stop ve hedef sıfırdan büyük sayı olmalı")
    code = code.upper()
    notes = []
    async with httpx.AsyncClient() as client:
        live = await _last_price(client, mkt, code)
        if entry is None:
            entry = live
            notes.append("giriş = şu anki fiyat")
        if stop is None or target is None:
            s, t = await _suggest(client, mkt, code, entry)
            if stop is None:
                stop = s
                notes.append("stop destek bölgesinden önerildi")
            if target is None:
                target = t
                notes.append("hedef direnç bölgesinden önerildi")
        if stop >= entry:
            raise ValueError("stop girişin altında olmalı (spot, yalnız alım)")
        if target <= entry:
            raise ValueError("hedef girişin üstünde olmalı")
        if mkt == "KRIPTO":
            g = await gate.evaluate(client, pair=f"{code}/{config.QUOTE}", direction="ABOVE", entry=entry,
                                    iptal=stop, hedef=target)
            amount, qty = g.get("kademe_usd") or 0, (g.get("kademe_usd") or 0) / entry
        elif mkt == "BIST":
            g = await bist_signals.evaluate(client, symbol=code, entry=entry, iptal=stop, hedef=target, level=None)
            amount, qty = g.get("kademe_tl") or 0, g.get("lot") or 0
        else:
            g = await us_signals.evaluate(client, t=code, entry=entry, iptal=stop, hedef=target)
            amount, qty = g.get("kademe_usd") or 0, g.get("adet") or 0
    risk = qty * (entry - stop)
    gap = (entry / live - 1) * 100 if live else 0
    if abs(gap) > 3:
        notes.append(f"giriş şu anki fiyattan %{gap:+.1f} uzak; günlük hareket kuralları bu girişe göre hesaplandı")
    if "seans" in g.get("kalan", []):
        notes.append("seans kapalı: seans açıkken tekrar kontrol et")
    return {"piyasa": mkt, "kod": code, "para": CUR[mkt], "ok": bool(g["ok"]), "giris": entry, "stop": stop,
            "hedef": target, "anlik": live, "rr": g.get("rr"), "tutar": round(amount, 2), "adet": qty,
            "risk": round(risk, 2), "kazanc": round(qty * (target - entry), 2),
            "stop_yuzde": round((stop / entry - 1) * 100, 2), "hedef_yuzde": round((target / entry - 1) * 100, 2),
            "kurallar": g.get("kurallar", []), "kalan": g.get("kalan", []), "notlar": notes,
            "zaman": alerts_store.now_tr().isoformat()}


async def _last_price(client, mkt, code) -> float:
    if mkt == "BIST":
        return float((await bist.day_quote(client, code))["fiyat"])
    if mkt == "ABD":
        return float(await us.last_price(client, code))
    return float(await market.last_price(client, code + config.QUOTE))


def _n(x, cur=None) -> str:
    if x is None:
        return "—"
    s = f"{x:,.8f}".rstrip("0").rstrip(".") if abs(x) < 0.01 else f"{x:,.4f}".rstrip("0").rstrip(".") if abs(x) < 1 else f"{x:,.2f}"
    return f"{s} {cur}" if cur else s


def pre_trade_text(r: dict) -> str:
    icon = {"gecti": "✅", "kaldi": "❌", "uyari": "⚠️"}
    head = (f"🔒 ALIM ÖNCESİ KONTROL · {r['kod']} ({r['piyasa']})\n"
            f"Giriş {_n(r['giris'])} · stop {_n(r['stop'])} (%{r['stop_yuzde']:+.2f}) · hedef {_n(r['hedef'])} "
            f"(%{r['hedef_yuzde']:+.2f}) · R/R {r['rr'] if r['rr'] is not None else '—'}")
    if r["notlar"]:
        head += "\n(" + "; ".join(r["notlar"]) + ")"
    rules = "\n".join(f"{icon.get(c['durum'], '•')} {c['kural']}: {c['detay']}" for c in r["kurallar"])
    if r["ok"]:
        verdict = (f"\n\nKAPI: GEÇTİ. Kurallara göre ilk kademe {_n(r['tutar'], r['para'])} ≈ {r['adet']:.6g} adet · "
                   f"stopta kayıp ≈ {_n(r['risk'], r['para'])} · hedefte ≈ +{_n(r['kazanc'], r['para'])}.\n"
                   "Emir fiyatını aracı kurumdan kontrol et. Bot işlem yapmaz.")
    else:
        verdict = f"\n\nKAPI: KALDI ({', '.join(r['kalan'])}). Kurallara göre bu fiyattan alım yok."
    return head + "\n\n" + rules + verdict


# ---------------------------------------------------------------- indicator alarms ---------------------------------

INDICATORS = {"sma20": "SMA20", "sma50": "SMA50", "sma200": "SMA200", "rsi": "RSI", "hacim": "Hacim"}
TIMEFRAMES = {"KRIPTO": ("1h", "4h", "1d"), "BIST": ("1d", "1wk"), "ABD": ("1d", "1wk")}
TF_LABEL = {"1h": "1 saat", "4h": "4 saat", "1d": "günlük", "1wk": "haftalık"}
MAX_IND_ALERTS = 40


def ind_alerts() -> list[dict]:
    return _load(IND_ALERTS, [])


def ind_create(mkt: str, code: str, indicator: str, direction: str, tf: str, value: float | None = None) -> dict:
    """indicator: sma20/sma50/sma200 (close crosses the average), rsi (RSI crosses value),
    hacim (volume crosses value x its 20-bar average, only upward)."""
    code = code.upper()
    if mkt not in MARKETS or not code:
        raise ValueError("piyasa ve kod gerekli")
    if indicator not in INDICATORS:
        raise ValueError("gösterge: sma20, sma50, sma200, rsi ya da hacim")
    if tf not in TIMEFRAMES[mkt]:
        raise ValueError(f"{mkt} için zaman dilimi: {', '.join(TIMEFRAMES[mkt])}")
    if indicator == "hacim":
        direction = "ustu"
    if direction not in ("ustu", "alti"):
        raise ValueError("yön: ustu ya da alti")
    if indicator == "rsi" and not (_ok_num(value) and 0 < value < 100):
        raise ValueError("RSI seviyesi 1–99 arası olmalı")
    if indicator == "hacim" and not (_ok_num(value) and 1 < value <= 20):
        raise ValueError("hacim katı 1'den büyük, en fazla 20 olmalı")
    items = ind_alerts()
    if len([a for a in items if a["durum"] == "aktif"]) >= MAX_IND_ALERTS:
        raise ValueError(f"en fazla {MAX_IND_ALERTS} gösterge alarmı")
    a = {"id": max([x["id"] for x in items] + [0]) + 1, "piyasa": mkt, "kod": code, "gosterge": indicator,
         "yon": direction, "deger": float(value) if value is not None and indicator in ("rsi", "hacim") else None,
         "tf": tf, "durum": "aktif", "olusturma": alerts_store.now_tr().isoformat(), "son_mum": None, "tetikler": []}
    items.append(a)
    _save(IND_ALERTS, items)
    return a


def ind_delete(aid: int) -> dict | None:
    items = ind_alerts()
    hit = next((a for a in items if a["id"] == aid), None)
    if hit:
        _save(IND_ALERTS, [a for a in items if a["id"] != aid])
    return hit


def ind_label(a: dict) -> str:
    side = "üstüne çıkınca" if a["yon"] == "ustu" else "altına inince"
    if a["gosterge"].startswith("sma"):
        what = f"kapanış {INDICATORS[a['gosterge']]} {side}"
    elif a["gosterge"] == "rsi":
        what = f"RSI {a['deger']:g} {side}"
    else:
        what = f"hacim ortalamanın {a['deger']:g} katını geçince"
    return f"#{a['id']} {a['kod']} ({a['piyasa']}) {TF_LABEL[a['tf']]}: {what}"


def crossed(a: dict, prev, last) -> tuple[bool, str]:
    """Pure: did the move from the previous CLOSED bar to the last CLOSED bar cross the condition?"""
    up = a["yon"] == "ustu"
    if a["gosterge"].startswith("sma"):
        col = a["gosterge"]
        if _nan(prev[col]) or _nan(last[col]):
            return False, ""
        p, l = prev.close - prev[col], last.close - last[col]
        hit = (p <= 0 < l) if up else (p >= 0 > l)
        return hit, f"kapanış {last.close:g}, {INDICATORS[col]} {float(last[col]):g}"
    if a["gosterge"] == "rsi":
        if _nan(prev.rsi14) or _nan(last.rsi14):
            return False, ""
        v = a["deger"]
        hit = (prev.rsi14 <= v < last.rsi14) if up else (prev.rsi14 >= v > last.rsi14)
        return hit, f"RSI {float(prev.rsi14):.1f} → {float(last.rsi14):.1f}"
    if _nan(prev.vol_avg20) or _nan(last.vol_avg20) or not prev.vol_avg20 or not last.vol_avg20:
        return False, ""
    kp, kl = prev.volume / prev.vol_avg20, last.volume / last.vol_avg20
    return kp < a["deger"] <= kl, f"hacim ortalamanın {kl:.1f} katı (kapanış {last.close:g})"


async def _bars(client, mkt, code, tf):
    if mkt == "KRIPTO":
        return market.add_indicators(await market.fetch_klines(client, code + config.QUOTE, tf, limit=260))
    if mkt == "BIST":
        return market.add_indicators(await bist.fetch(client, code, tf))
    return market.add_indicators(await us.fetch(client, code, tf, bulk=True))


async def check_ind_alerts() -> list[str]:
    """Only closed bars (every fetch drops the open bar). The first check after creation only records the bar,
    so an old crossing never fires. One message per new crossing; the alarm stays active until deleted."""
    items = ind_alerts()
    active = [a for a in items if a["durum"] == "aktif"]
    if not active:
        return []
    msgs, frames = [], {}
    async with httpx.AsyncClient() as client:
        for a in active:
            key = (a["piyasa"], a["kod"], a["tf"])
            try:
                if key not in frames:
                    frames[key] = await _bars(client, *key)
                d = frames[key]
            except Exception as e:
                log.warning("Indicator alarm fetch %s failed: %s", key, e)
                continue
            if len(d) < 3:
                continue
            last, prev = d.iloc[-1], d.iloc[-2]
            bar = int(last.open_time)
            if a.get("son_mum") == bar:
                continue
            first = a.get("son_mum") is None
            a["son_mum"] = bar
            if first:
                continue
            hit, detail = crossed(a, prev, last)
            if hit:
                a["tetikler"] = (a.get("tetikler") or [])[-19:] + [alerts_store.now_tr().isoformat()]
                code_hint = f"/kontrol {a['kod']}"
                msgs.append(f"📈 GÖSTERGE ALARMI {ind_label(a)}\n{detail}.\n"
                            f"Bu bir AL sinyali değildir. Kapıdan geçirmek için: {code_hint}")
    _save(IND_ALERTS, items)
    return msgs


def ind_text() -> str:
    items = [a for a in ind_alerts() if a["durum"] == "aktif"]
    if not items:
        return ("📈 Gösterge alarmı yok.\nÖrnek: /galarm THYAO sma50 ustu 1d · /galarm BTC rsi alti 30 4h · "
                "/galarm NVDA hacim 2 1d\nYalnız kapanmış mumla tetiklenir.")
    return ("📈 GÖSTERGE ALARMLARI (yalnız kapanış)\n" + "\n".join(
        ind_label(a) + (f" · son tetik {a['tetikler'][-1][:16].replace('T', ' ')}" if a.get("tetikler") else "")
        for a in items) + "\nSil: /galarm sil ID")


# ---------------------------------------------------------------- comparison ---------------------------------------

async def _one_compare(mkt: str, code: str) -> dict:
    if mkt == "BIST":
        f = await fundamentals.report(code)
        st = f.get("stage") or {}
        async with httpx.AsyncClient() as client:
            d = market.add_indicators(await bist.fetch(client, code, "1d"))
        high = float(d.high.tail(252).max())
        return {"kod": f["hisse"], "fiyat": f.get("fiyat"), "skor": f["puan"]["skor"], "etiket": f["puan"]["etiket"],
                "buyume": f.get("kredi_buyume_usd_yuzde") if f.get("grup") == "banka" else f.get("ciro_buyume_usd_yuzde"),
                "buyume_etiket": "kredi büyümesi (USD)" if f.get("grup") == "banka" else "ciro büyümesi (USD)",
                "faaliyet_marj": f.get("faaliyet_marj_yuzde"), "net_marj": f.get("net_marj_yuzde"),
                "roe": f.get("roe_yuzde"), "borc": f.get("net_borc_favok"), "borc_etiket": "net borç/FAVÖK",
                "fk": f.get("fk"), "pd_dd": f.get("pd_dd"), "fd_favok": f.get("fd_favok"),
                "fcf_verim": f.get("fcf_verimi_yuzde"), "stage": st.get("stage"),
                "trend": _trend(d), "rsi": None if _nan(d.iloc[-1].rsi14) else round(float(d.iloc[-1].rsi14)),
                "zirveye": round((float(d.iloc[-1].close) / high - 1) * 100, 1) if high else None,
                "uyarilar": f.get("kirmizi_bayraklar", [])[:4], "parcalar": f["puan"]["parcalar"]}
    f = await us_fund.report(code)
    tech = f.get("teknik") or {}
    async with httpx.AsyncClient() as client:
        d = market.add_indicators(await us.fetch(client, code, "1d", bulk=True))
    return {"kod": f["hisse"], "fiyat": f.get("fiyat"), "skor": f["puan"]["skor"], "etiket": f["puan"]["durum"],
            "buyume": f.get("ciro_buyume_yuzde"), "buyume_etiket": "ciro büyümesi",
            "faaliyet_marj": f.get("faaliyet_marj_yuzde"), "net_marj": f.get("net_marj_yuzde"),
            "roe": f.get("roe_yuzde"), "borc": None if f.get("net_nakit") is None or not f.get("favok_ttm") else
            round(-f["net_nakit"] / f["favok_ttm"], 2), "borc_etiket": "net borç/FAVÖK",
            "fk": f.get("fk"), "pd_dd": None, "fd_favok": f.get("fd_favok"), "fcf_verim": f.get("fcf_verimi_yuzde"),
            "stage": (tech.get("stage") or {}).get("stage"), "trend": _trend(d),
            "rsi": None if _nan(d.iloc[-1].rsi14) else round(float(d.iloc[-1].rsi14)),
            "zirveye": tech.get("zirveye_uzaklik_yuzde"),
            "uyarilar": f.get("uyarilar", [])[:4], "parcalar": f["puan"]["parcalar"]}


def _trend(d) -> str:
    last = d.iloc[-1]
    if _nan(last.sma50) or _nan(last.sma200):
        return "az veri"
    c = float(last.close)
    return "güçlü" if c > last.sma50 > last.sma200 else "zayıf" if c < last.sma50 < last.sma200 else "karışık"


async def compare(mkt: str, codes: list[str]) -> dict:
    if mkt not in ("BIST", "ABD"):
        raise ValueError("karşılaştırma BIST ya da ABD hisseleri için (kripto için temel veri yok)")
    codes = list(dict.fromkeys(c.upper().removesuffix(".IS").removesuffix(".US") for c in codes if c))
    if not 2 <= len(codes) <= 4:
        raise ValueError("2–4 hisse seç")
    rows, errors = [], []
    for c in codes:  # sequential: SEC and İş Yatırım are polite-rate sources
        try:
            rows.append(await _one_compare(mkt, c))
        except Exception as e:
            log.warning("Compare %s failed: %s", c, e)
            errors.append(f"{c}: veri alınamadı ({str(e)[:50]})")
    return {"piyasa": mkt, "kodlar": codes, "satirlar": rows, "hatalar": errors,
            "zaman": alerts_store.now_tr().isoformat()}


# (key, label, higher is better? None = neutral, decimals, suffix)
COMPARE_ROWS = [
    ("skor", "Temel skor /100", True, 0, ""), ("buyume", "Büyüme (ciro; bankada kredi, USD)", True, 1, "%"),
    ("faaliyet_marj", "Faaliyet marjı", True, 1, "%"), ("net_marj", "Net marj", True, 1, "%"),
    ("roe", "ROE", True, 1, "%"), ("borc", "Net borç/FAVÖK", False, 2, ""), ("fk", "F/K", False, 1, ""),
    ("pd_dd", "PD/DD", False, 2, ""), ("fd_favok", "FD/FAVÖK", False, 1, ""), ("fcf_verim", "FCF verimi", True, 1, "%"),
    ("zirveye", "52h zirveye uzaklık", None, 1, "%"), ("rsi", "RSI (günlük)", None, 0, ""), ("stage", "Stage", None, 0, ""),
]


def best_of(rows: list[dict]) -> dict[str, str]:
    """Pure: which code is best on each comparable metric (only when at least two have a value)."""
    out = {}
    for key, _, higher, _, _ in COMPARE_ROWS:
        if higher is None:
            continue
        vals = [(r["kod"], r[key]) for r in rows if _ok_num(r.get(key))]
        if key == "fk":
            vals = [v for v in vals if v[1] > 0]
        if len(vals) >= 2:
            out[key] = (max if higher else min)(vals, key=lambda v: v[1])[0]
    return out


def compare_text(c: dict) -> str:
    rows = c["satirlar"]
    if not rows:
        return "❌ Karşılaştırma: veri alınamadı.\n" + "\n".join(c["hatalar"])
    best = best_of(rows)
    lines = [f"⚖️ KARŞILAŞTIRMA ({c['piyasa']}): " + " · ".join(r["kod"] for r in rows)]
    for key, label, _, dec, suf in COMPARE_ROWS:
        cells = []
        for r in rows:
            v = r.get(key)
            s = "—" if v is None else (f"{v:.{dec}f}{suf}" if isinstance(v, (int, float)) else str(v))
            cells.append(f"{r['kod']} {s}" + (" ★" if best.get(key) == r["kod"] else ""))
        lines.append(f"{label}: " + " | ".join(cells))
    lines.append("Trend: " + " | ".join(f"{r['kod']} {r['trend'] or '—'}" for r in rows))
    lines.append("Durum: " + " | ".join(f"{r['kod']} {r['etiket']}" for r in rows))
    for r in rows:
        if r["uyarilar"]:
            lines.append(f"⚠️ {r['kod']}: " + "; ".join(r["uyarilar"]))
    lines += c["hatalar"]
    lines.append("★ = o ölçüde en iyi. Skor kalite ölçüsüdür, yükselme olasılığı değil. Öneri değildir.")
    return "\n".join(lines)


# ---------------------------------------------------------------- dividend income plan -----------------------------

async def _dividends(client, mkt: str, code: str) -> list[dict]:
    if mkt == "BIST":
        return (await corporate.events(client, code))["temettuler"]
    r = await client.get(us.YAHOO + us.ticker(code), params={"interval": "1d", "range": "2y", "events": "div"},
                         headers=us.HEADERS, timeout=20)
    r.raise_for_status()
    res = (r.json().get("chart") or {}).get("result") or [{}]
    divs = (res[0].get("events") or {}).get("dividends") or {}
    return sorted(({"tarih": datetime.fromtimestamp(int(k), bist.TR).date().isoformat(), "ms": int(k) * 1000,
                    "tutar": float(v["amount"])} for k, v in divs.items() if v.get("amount")), key=lambda x: x["ms"])


def project(divs: list[dict], qty: float, today: date) -> dict:
    """Pure: last 12 months of dividends x current quantity, each repeated one year later (a projection from
    history, not an announcement). Also the 12 months before, for the change."""
    y1, y2 = (today - timedelta(days=365)).isoformat(), (today - timedelta(days=730)).isoformat()
    last12 = [d for d in divs if y1 < d["tarih"] <= today.isoformat()]
    prev12 = [d for d in divs if y2 < d["tarih"] <= y1]
    months = {}
    for d in last12:
        nxt = (date.fromisoformat(d["tarih"]) + timedelta(days=365)).isoformat()[:7]
        months[nxt] = round(months.get(nxt, 0) + d["tutar"] * qty, 2)
    return {"son12": round(sum(d["tutar"] for d in last12) * qty, 2),
            "onceki12": round(sum(d["tutar"] for d in prev12) * qty, 2),
            "hisse_basi": round(sum(d["tutar"] for d in last12), 4), "aylar": months,
            "odemeler": [{"tarih": d["tarih"], "tutar": d["tutar"]} for d in last12]}


async def dividend_plan(force: bool = False) -> dict:
    """Held BIST and US stocks (grouped by code). Cached 12 hours."""
    cached = _load(DIV_CACHE, None)
    if cached and not force and time.time() - cached.get("ts", 0) < 12 * 3600:
        return cached
    held: dict[tuple[str, str], float] = {}
    for p in positions.open_positions():
        mkt = p.get("piyasa", "KRIPTO")
        if mkt in ("BIST", "ABD"):
            code = bist.ticker(p["symbol"]) if mkt == "BIST" else us.ticker(p["symbol"])
            held[(mkt, code)] = held.get((mkt, code), 0) + float(p["adet"])
    today = alerts_store.now_tr().date()
    rows, totals = [], {"TL": {"son12": 0.0, "onceki12": 0.0, "deger": 0.0}, "USD": {"son12": 0.0, "onceki12": 0.0, "deger": 0.0}}
    months: dict[str, dict[str, float]] = {}
    async with httpx.AsyncClient() as client:
        for (mkt, code), qty in sorted(held.items()):
            cur = CUR[mkt]
            try:
                pr = project(await _dividends(client, mkt, code), qty, today)
                price = await _last_price(client, mkt, code)
            except Exception as e:
                log.warning("Dividend plan %s failed: %s", code, e)
                rows.append({"kod": code, "piyasa": mkt, "para": cur, "hata": str(e)[:60]})
                continue
            value = price * qty
            rows.append({"kod": code, "piyasa": mkt, "para": cur, "adet": qty, "fiyat": price, **pr,
                         "verim": round(pr["hisse_basi"] / price * 100, 2) if price and pr["hisse_basi"] else None})
            totals[cur]["son12"] += pr["son12"]
            totals[cur]["onceki12"] += pr["onceki12"]
            totals[cur]["deger"] += value
            for m, v in pr["aylar"].items():
                months.setdefault(m, {"TL": 0.0, "USD": 0.0})[cur] += v
    for t in totals.values():
        t["verim"] = round(t["son12"] / t["deger"] * 100, 2) if t["deger"] and t["son12"] else None
        t["degisim"] = round((t["son12"] / t["onceki12"] - 1) * 100, 1) if t["onceki12"] else None
        for k in ("son12", "onceki12", "deger"):
            t[k] = round(t[k], 2)
    start = today.replace(day=1)
    calendar = []
    for i in range(12):
        m = (start.replace(year=start.year + (start.month - 1 + i) // 12, month=(start.month - 1 + i) % 12 + 1)).isoformat()[:7]
        calendar.append({"ay": m, **{k: round(v, 2) for k, v in months.get(m, {"TL": 0.0, "USD": 0.0}).items()}})
    out = {"ts": time.time(), "zaman": alerts_store.now_tr().isoformat(), "satirlar": rows, "toplam": totals,
           "takvim": calendar,
           "not": "Brüt, geçen 12 ayın ödemeleri bugünkü adetle tekrarlanır (tahmin; kesin tarih ve tutarı KAP/şirket açıklar)."}
    _save(DIV_CACHE, out)
    return out


MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


def dividend_text(p: dict) -> str:
    rows = [r for r in p["satirlar"] if "hata" not in r]
    if not p["satirlar"]:
        return "💰 Portföyde BIST ya da ABD hissesi yok."
    lines = ["💰 TEMETTÜ GELİR PLANI (brüt, geçen 12 aya göre tahmin)"]
    for cur, t in p["toplam"].items():
        if t["son12"] or t["deger"]:
            lines.append(f"{cur}: yıllık ≈ {t['son12']:,.2f} {cur}" + (f" · verim %{t['verim']:.2f}" if t["verim"] else "")
                         + (f" · önceki yıla göre %{t['degisim']:+.1f}" if t["degisim"] is not None else ""))
    for r in sorted(rows, key=lambda r: -r["son12"]):
        if r["son12"]:
            lines.append(f"• {r['kod']}: {r['son12']:,.2f} {r['para']}/yıl ({r['adet']:g} adet × {r['hisse_basi']:g})"
                         + (f" · verim %{r['verim']:.2f}" if r["verim"] else ""))
    none = [r["kod"] for r in rows if not r["son12"]]
    if none:
        lines.append("Son 12 ayda temettü yok: " + ", ".join(none))
    months = [c for c in p["takvim"] if c["TL"] or c["USD"]]
    if months:
        lines.append("\nAy ay (tahmini):")
        for c in months:
            y, m = c["ay"].split("-")
            amt = " + ".join(f"{c[k]:,.2f} {k}" for k in ("TL", "USD") if c[k])
            lines.append(f"{MONTHS[int(m) - 1]} {y}: {amt}")
    lines.append(p["not"])
    return "\n".join(lines)

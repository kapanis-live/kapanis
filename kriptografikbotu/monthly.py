"""The monthly report: what the portfolio did last month, in five parts, with no forecast and no suggestion.

  1 getiri        the month's result in TL and in USD
  2 kıyas         BIST 100, S&P 500 and BTC over the same month, and USD/TRY
  3 en iyi / en kötü   the three assets that added most and the three that cost most
  4 işlemler      buys and sells inside the month, and the realized profit of the sells
  5 yoğunlaşma    the largest holding's weight at the start and at the end

How the result is measured (so new money is never counted as profit): every position is followed only while it was
held inside the month. Its start is the last close before the month, or its buy price when it was bought inside the
month; its end is the month's last close, or its sell price when it was sold inside the month. The month's result
is the sum of those gains over the sum of those start values. A holding typed into /portfoy without a purchase date
counts as held from before the month. Month ends use daily closes (BIST and US: the last session's close).

Sent on the first day of each month; /aylik shows it on request (/aylik 2026-09 for an earlier month).
"""
import asyncio
import logging
import math
import re
from datetime import date, datetime, timedelta

import httpx
import pandas as pd

import alerts_store
import assets
import benchmark
import bist
import config
import lang
import market
import positions
import risk
import us

log = logging.getLogger(__name__)

FILE = config.DATA_DIR / "aylik_rapor.json"
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
KEEP = 24      # months kept in the file


def bounds(month: str) -> tuple[str, str]:
    """("2026-08-31", "2026-09-30") for "2026-09": the last day before the month and the month's last day."""
    y, m = int(month[:4]), int(month[5:7])
    first = date(y, m, 1)
    last = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    return (first - timedelta(days=1)).isoformat(), last.isoformat()


def previous_month(today: date) -> str:
    d = today.replace(day=1) - timedelta(days=1)
    return f"{d.year}-{d.month:02d}"


def _day(iso: str | None) -> str:
    return (iso or "")[:10]


def _unknown_date(p: dict) -> bool:
    return p.get("kaynak") == "portföy" and not p.get("tarih_girildi")


def _usd(p: dict) -> bool:
    return p.get("piyasa", "KRIPTO") in ("KRIPTO", "ABD")


def compute(items: list[dict], closes: dict[str, pd.Series], fx: pd.Series, bench: dict[str, pd.Series], month: str) -> dict:
    """items: positions.load(). closes: symbol -> daily closes indexed by ISO day (native currency). fx: USD/TRY daily
    closes. bench: name -> daily closes. Pure."""
    before, last = bounds(month)
    first = month + "-01"
    fx0, fx1 = benchmark._asof(fx, before), benchmark._asof(fx, last)
    rows, skipped = {}, []
    for p in items:
        opened = "0000" if _unknown_date(p) else _day(p.get("acilis"))
        closed = _day(p.get("kapanis_zamani")) if p["durum"] == "kapali" else None
        if opened > last or (closed and closed < first):
            continue                                              # not held at any time inside the month
        s = closes.get(p["symbol"])
        start = float(p["giris"]) if opened >= first else (benchmark._asof(s, before) if s is not None else None)
        end = float(p["kapanis_fiyat"]) if closed and closed <= last and p.get("kapanis_fiyat") is not None \
            else (benchmark._asof(s, last) if s is not None else None)
        if start is None or end is None or not start > 0:
            skipped.append(risk.name(p))
            continue
        usd = _usd(p)
        # each position in both currencies, converted with the rate of its own start and end day
        f0 = benchmark._asof(fx, opened if opened >= first else before) or fx0
        f1 = benchmark._asof(fx, closed if closed and closed <= last else last) or fx1
        if not f0 or not f1:
            skipped.append(risk.name(p))
            continue
        qty = float(p["adet"])
        v0_tl, v1_tl = qty * start * (f0 if usd else 1), qty * end * (f1 if usd else 1)
        v0_usd, v1_usd = qty * start / (1 if usd else f0), qty * end / (1 if usd else f1)
        g = rows.setdefault(p["symbol"], {"ad": risk.name(p), "piyasa": p.get("piyasa", "KRIPTO"), "para": "USD" if usd else "TL",
                                           "bas_tl": 0.0, "son_tl": 0.0, "bas_usd": 0.0, "son_usd": 0.0, "bas": 0.0, "son": 0.0,
                                           "ay_basi_tl": 0.0, "ay_sonu_tl": 0.0})
        g["bas_tl"] += v0_tl
        g["son_tl"] += v1_tl
        g["bas_usd"] += v0_usd
        g["son_usd"] += v1_usd
        g["bas"] += qty * start
        g["son"] += qty * end
        if opened < first:
            g["ay_basi_tl"] += v0_tl                              # held on the first morning of the month
        if not (closed and closed <= last):
            g["ay_sonu_tl"] += v1_tl                              # still held on the last evening
    assets_ = sorted(({**g, "kazanc_tl": round(g["son_tl"] - g["bas_tl"], 2), "kazanc": round(g["son"] - g["bas"], 2),
                       "yuzde": round((g["son"] / g["bas"] - 1) * 100, 1) if g["bas"] else None} for g in rows.values()),
                     key=lambda x: -x["kazanc_tl"])
    t0, t1 = sum(g["bas_tl"] for g in rows.values()), sum(g["son_tl"] for g in rows.values())
    u0, u1 = sum(g["bas_usd"] for g in rows.values()), sum(g["son_usd"] for g in rows.values())

    def weight(key):
        total = sum(g[key] for g in rows.values())
        if total <= 0:
            return None
        top = max(rows.values(), key=lambda g: g[key])
        return {"ad": top["ad"], "yuzde": round(top[key] / total * 100, 1), "toplam_tl": round(total, 2)}

    def change(s):
        a, b = benchmark._asof(s, before), benchmark._asof(s, last)
        return round((b / a - 1) * 100, 1) if a and b else None
    # "parca": the sold part of a position that is still (partly) held; a sale, not a second buy
    buys = [p for p in items if not _unknown_date(p) and not p.get("parca") and first <= _day(p.get("acilis")) <= last]
    sells = [p for p in items if p["durum"] == "kapali" and p.get("kapanis_fiyat") is not None and first <= _day(p.get("kapanis_zamani")) <= last]
    realized: dict[str, float] = {}
    for p in sells:
        cur = "USD" if _usd(p) else "TL"
        realized[cur] = realized.get(cur, 0.0) + (float(p["kapanis_fiyat"]) - float(p["giris"])) * float(p["adet"])
    slim = lambda a: {k: a[k] for k in ("ad", "piyasa", "para", "kazanc_tl", "kazanc", "yuzde")}
    winners = [slim(a) for a in assets_ if a["kazanc_tl"] > 0][:3]
    losers = [slim(a) for a in reversed(assets_) if a["kazanc_tl"] < 0][:3]
    return {"ay": month, "ad": f"{MONTHS[int(month[5:7]) - 1]} {month[:4]}", "bas_gun": before, "son_gun": last,
            "getiri": {"tl_yuzde": round((t1 / t0 - 1) * 100, 1) if t0 else None, "usd_yuzde": round((u1 / u0 - 1) * 100, 1) if u0 else None,
                       "kazanc_tl": round(t1 - t0, 2), "kazanc_usd": round(u1 - u0, 2), "izlenen_tl": round(t0, 2)},
            "kiyas": {name: change(s) for name, s in bench.items()}, "usdtry_yuzde": change(fx),
            "en_iyi": winners, "en_kotu": losers,
            "islemler": {"alim": len(buys), "satim": len(sells), "gerceklesen": {k: round(v, 2) for k, v in realized.items()},
                         "alinan": sorted({risk.name(p) for p in buys}), "satilan": sorted({risk.name(p) for p in sells})},
            "yogunlasma": {"ay_basi": weight("ay_basi_tl"), "ay_sonu": weight("ay_sonu_tl")},
            "varlik": len(rows), "hesaplanamayan": sorted(set(skipped))}


async def _series(client, p: dict) -> pd.Series | None:
    mkt = p.get("piyasa", "KRIPTO")
    try:
        if mkt == "BIST":
            df = await bist.fetch(client, p["symbol"], "1d")
        elif mkt == "ABD":
            df = await us.fetch(client, p["symbol"], "1d", bulk=True)
        elif mkt == assets.MARKET:
            df = await assets.daily(client, p["symbol"])
        else:
            df = await market.fetch_klines(client, p["symbol"], "1d")
        return benchmark._series(df)
    except Exception as e:
        log.warning("Monthly report: no closes for %s: %s", p.get("symbol"), str(e)[:80])
        return None


MAX_ACCOUNT_POSITIONS = 400
_CODE = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,11}$")


def account_items(raw) -> list[dict]:
    """A site account's positions (as the web backend sends them) in the shape compute() reads. Rows that are not a
    valid crypto / BIST / US position are dropped; the size is capped."""
    out = []
    for p in (raw if isinstance(raw, list) else [])[:MAX_ACCOUNT_POSITIONS]:
        try:
            mkt, code = str(p.get("piyasa", "")).upper(), str(p.get("kod", "")).strip().upper()
            qty, cost = float(p["adet"]), float(p["maliyet"])
            sold = p.get("durum") == "kapali"
            price = float(p["kapanis_fiyat"]) if sold and p.get("kapanis_fiyat") is not None else None
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if mkt not in ("KRIPTO", "BIST", "ABD") or not _CODE.match(code) or not (math.isfinite(qty) and qty > 0 and math.isfinite(cost) and cost > 0):
            continue
        if price is not None and not (math.isfinite(price) and price > 0):
            continue
        pair = f"{code}/USDT" if mkt == "KRIPTO" else code
        symbol = bist.yahoo_symbol(code) if mkt == "BIST" else us.key(code) if mkt == "ABD" else alerts_store.pair_to_symbol(pair)
        out.append({"symbol": symbol, "pair": pair, "piyasa": mkt, "adet": qty, "giris": cost, "kaynak": "site",
                    "acilis": str(p.get("acilis") or ""), "durum": "kapali" if sold else "acik",
                    "kapanis_fiyat": price, "kapanis_zamani": str(p.get("kapanis") or "") if sold else None,
                    "parca": bool(p.get("parca")) and sold})
    return out


async def build(month: str | None = None, items: list[dict] | None = None) -> dict:
    """The report of one month (default: the month that just ended), from live price history.

    items: the positions to report on (a site account's, from account_items); default: the bot's own record."""
    month = month or previous_month(alerts_store.now_tr().date())
    before, last = bounds(month)
    own = items is None
    items = positions.load() if own else items
    slots = asyncio.Semaphore(6)
    async with httpx.AsyncClient() as client:
        async def one(p):
            async with slots:
                return p["symbol"], await _series(client, p)
        unique = {p["symbol"]: p for p in items}.values()
        closes = {k: v for k, v in await asyncio.gather(*[one(p) for p in unique]) if v is not None}
        fx = benchmark._series(await bist.fetch(client, bist.FX, "1d"))
        bench = {}
        for name, getter in (("BIST 100", lambda: bist.fetch(client, bist.INDEX, "1d")), ("S&P 500", lambda: us.fetch(client, "SPY", "1d", bulk=True)),
                             ("BTC", lambda: market.fetch_klines(client, "BTCUSDT", "1d"))):
            try:
                bench[name] = benchmark._series(await getter())
            except Exception as e:
                log.warning("Monthly report: benchmark %s failed: %s", name, e)
    doc = compute(items, closes, fx, bench, month)
    doc.update(uretildi=alerts_store.now_tr().isoformat(timespec="seconds"),
               kaynaklar=["fiyatlar: Binance (kripto), Yahoo Finance (BIST, ABD, USD/TRY)",
                          "pozisyonlar ve işlemler: botun kendi kaydı" if own else "pozisyonlar ve işlemler: sitedeki portföyün"])
    return doc


async def account_report(raw_positions, meta: dict, month: str | None = None) -> tuple[dict | None, str]:
    """One month's report for a site account. Returns (document for the panel or None, reply for the account's chat)."""
    uid, en = meta.get("user_id"), meta.get("dil") == "en"
    if not uid:
        return None, "❌ Panel aylık rapor: hesap bilgisi yok"
    month = month if month and re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", month) else previous_month(alerts_store.now_tr().date())
    base = {"id": f"aylik:{uid}:{month}", "tur": "aylik", "user_id": uid, "ay": month}
    items = account_items(raw_positions)
    try:
        doc = await build(month, items) if items else None
    except Exception as e:
        log.exception("Monthly report for an account failed")
        return {**base, "zaman": alerts_store.now_tr().isoformat(timespec="seconds"), "hata": str(e)[:150]}, \
            (f"❌ Monthly report: {str(e)[:150]}" if en else f"❌ Aylık rapor hazırlanamadı: {str(e)[:150]}")
    if not doc or not doc["varlik"]:
        return {**base, "zaman": alerts_store.now_tr().isoformat(timespec="seconds"), "bos": True}, \
            ("ℹ️ No position was held in that month." if en else "ℹ️ O ay içinde elde tutulan pozisyon yok.")
    return {**base, "zaman": doc["uretildi"], "bos": False, **doc}, text(doc, "en" if en else "tr")


def save(doc: dict):
    store = alerts_store._load(FILE, {"aylar": {}})
    store["aylar"][doc["ay"]] = doc
    store["aylar"] = dict(sorted(store["aylar"].items())[-KEEP:])
    alerts_store._save(FILE, store)


def history() -> list[dict]:
    return [v for _, v in sorted(alerts_store._load(FILE, {"aylar": {}})["aylar"].items(), reverse=True)]


def differences(d: dict) -> list[tuple[str, float, str]]:
    """(benchmark, the portfolio's return minus the benchmark's in points, currency of the comparison). BIST 100 is
    compared in TL, the others in USD."""
    g, out = d["getiri"], []
    for name, v in d["kiyas"].items():
        mine, cur = (g["tl_yuzde"], "TL") if name == "BIST 100" else (g["usd_yuzde"], "USD")
        if v is not None and mine is not None:
            out.append((name, round(mine - v, 1), cur))
    return out


def _p(v) -> str:
    return "—" if v is None else f"%{v:+.1f}"


def _m(v: float, cur: str) -> str:
    return f"{v:+,.0f} {cur}"


def text_en(d: dict) -> str:
    g, t, y = d["getiri"], d["islemler"], d["yogunlasma"]
    name = f"{lang.MONTHS_EN[int(d['ay'][5:7]) - 1]} {d['ay'][:4]}"
    if not d["varlik"]:
        return f"🗓 MONTHLY REPORT — {name}\nNo position was followed inside this month." + (
            f"\nNo price history for: {', '.join(d['hesaplanamayan'])}" if d["hesaplanamayan"] else "")
    lines = [f"🗓 MONTHLY REPORT — {name}",
             f"Return: TL {_p(g['tl_yuzde'])} ({_m(g['kazanc_tl'], 'TL')}) · USD {_p(g['usd_yuzde'])} ({_m(g['kazanc_usd'], 'USD')})",
             "Same month: " + " · ".join(f"{k} {_p(v)}" for k, v in d["kiyas"].items()) + f" · USD/TRY {_p(d['usdtry_yuzde'])}"]
    gaps = [f"{k} {gap:+.1f} ({cur})" for k, gap, cur in differences(d)]
    if gaps:
        lines.append("Against the index (points): " + " · ".join(gaps))
    row = lambda a: f"{a['ad']} {_p(a['yuzde'])} ({_m(a['kazanc'], a['para'])})"
    lines += ["", "Added most: " + (" · ".join(row(a) for a in d["en_iyi"]) or "none"),
              "Cost most: " + (" · ".join(row(a) for a in d["en_kotu"]) or "none"), "",
              f"Trades: {t['alim']} buys" + (f" ({', '.join(t['alinan'][:8])})" if t["alinan"] else "")
              + f" · {t['satim']} sells" + (f" ({', '.join(t['satilan'][:8])})" if t["satilan"] else ""),
              "Realized P/L: " + (" · ".join(_m(v, k) for k, v in t["gerceklesen"].items()) or "no sale")]
    a, b = y["ay_basi"], y["ay_sonu"]
    if a or b:
        lines.append("Largest holding: " + " → ".join(
            f"{w['ad']} {w['yuzde']:g}% ({label})" for w, label in ((a, "start"), (b, "end")) if w))
    if d["hesaplanamayan"]:
        lines.append(f"Left out, no price history: {', '.join(d['hesaplanamayan'])}")
    lines += ["", f"Measured only over the days each position was held (close of {d['bas_gun'][8:10]}.{d['bas_gun'][5:7]} → close of "
                  f"{d['son_gun'][8:10]}.{d['son_gun'][5:7]}; bought inside the month: from the buy price, sold inside: to the sell price). "
                  "New money is not counted as return.",
              "A summary of the past; no forecast and no suggestion."]
    return "\n".join(lines)


def text(d: dict, code: str = "tr") -> str:
    if code == "en":
        return text_en(d)
    g, t, y = d["getiri"], d["islemler"], d["yogunlasma"]
    if not d["varlik"]:
        return f"🗓 AYLIK RAPOR — {d['ad']}\nBu ay içinde izlenen pozisyon yok." + (
            f"\nFiyatı alınamayan: {', '.join(d['hesaplanamayan'])}" if d["hesaplanamayan"] else "")
    lines = [f"🗓 AYLIK RAPOR — {d['ad']}",
             f"Getiri: TL {_p(g['tl_yuzde'])} ({_m(g['kazanc_tl'], 'TL')}) · USD {_p(g['usd_yuzde'])} ({_m(g['kazanc_usd'], 'USD')})",
             "Aynı ay: " + " · ".join(f"{k} {_p(v)}" for k, v in d["kiyas"].items()) + f" · USD/TRY {_p(d['usdtry_yuzde'])}"]
    gaps = [f"{k} {gap:+.1f} ({cur})" for k, gap, cur in differences(d)]
    if gaps:
        lines.append("Endekse göre fark (puan): " + " · ".join(gaps))
    row = lambda a: f"{a['ad']} {_p(a['yuzde'])} ({_m(a['kazanc'], a['para'])})"
    lines += ["", "En çok kazandıran: " + (" · ".join(row(a) for a in d["en_iyi"]) or "yok"),
              "En çok kaybettiren: " + (" · ".join(row(a) for a in d["en_kotu"]) or "yok"), "",
              f"İşlemler: {t['alim']} alım" + (f" ({', '.join(t['alinan'][:8])})" if t["alinan"] else "")
              + f" · {t['satim']} satım" + (f" ({', '.join(t['satilan'][:8])})" if t["satilan"] else ""),
              "Gerçekleşen K/Z: " + (" · ".join(_m(v, k) for k, v in t["gerceklesen"].items()) or "satış yok")]
    a, b = y["ay_basi"], y["ay_sonu"]
    if a or b:
        lines.append("En büyük pozisyon: " + " → ".join(
            f"{w['ad']} %{w['yuzde']:g} ({label})" for w, label in ((a, "ay başı"), (b, "ay sonu")) if w))
    if d["hesaplanamayan"]:
        lines.append(f"Fiyat geçmişi alınamadığı için dışarıda kalan: {', '.join(d['hesaplanamayan'])}")
    lines += ["", f"Ölçüm: her pozisyon yalnız elde tutulduğu günler için sayılır ({d['bas_gun'][8:10]}.{d['bas_gun'][5:7]} kapanışı → "
                  f"{d['son_gun'][8:10]}.{d['son_gun'][5:7]} kapanışı; ay içinde alınan alış fiyatından, satılan satış fiyatından). "
                  "Yeni giren para getiri sayılmaz.",
              "Geçmişin özetidir; tahmin ya da öneri içermez."]
    return "\n".join(lines)

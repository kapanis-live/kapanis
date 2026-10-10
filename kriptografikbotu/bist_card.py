"""One card per BIST stock: the same decision-support card as us_card.py, from what is available for Türkiye.

Trend, strength against BIST 100, the next earnings and ex-dividend dates, the fundamental score (İş Yatırım
statements, fundamentals.py), red flags and a coarse valuation label, with the source and date of every number.
Not available for BIST for free, so not on the card: analyst estimate revisions and the exact time of past earnings
releases. Decision support, never AL / SAT; each card is appended to backups/audit/bist_kart.jsonl.
"""
import json
import logging
from datetime import datetime

import httpx

import alerts_store
import bist
import db_backup
import fundamentals
import lang
import market
import structure
import us_card
import watch_cards

log = logging.getLogger(__name__)

AUDIT = db_backup.BACKUP_DIR / "audit" / "bist_kart.jsonl"


def valuation(f: dict) -> dict:
    """Coarse on purpose: P/E over 25 or P/B over 6 = PAHALI; P/E under 8 with P/B under 1.5 (or unknown) = UCUZ; else
    MAKUL. Under inflation accounting P/E moves a lot between periods: a pointer, not a fair-value estimate."""
    pe, pb = f.get("fk"), f.get("pd_dd")
    if pe is None and pb is None:
        label = "BİLİNMİYOR"
    elif (pe is not None and pe > 25) or (pb is not None and pb > 6):
        label = "PAHALI"
    elif pe is not None and 0 < pe < 8 and (pb is None or pb < 1.5):
        label = "UCUZ"
    else:
        label = "MAKUL"
    return {"fk": pe, "pd_dd": pb, "fd_favok": f.get("fd_favok"), "fcf_verimi_yuzde": f.get("fcf_verimi_yuzde"), "etiket": label}


def build(f: dict, d, w, index, cal: dict | None, now: datetime | None = None) -> dict:
    """The card from a fundamentals.report() dict, daily / weekly bars (with indicators), BIST 100 daily bars and the
    company calendar. Pure."""
    now = now or alerts_store.now_tr()
    last = d.iloc[-1]
    close = float(last.close)
    own, bench = watch_cards.six_month_return(d.close), watch_cards.six_month_return(index.close)
    rel = round(own - bench, 1) if own is not None and bench is not None else None
    ok50, ok200 = last.sma50 == last.sma50, last.sma200 == last.sma200
    align = ("fiyat > 50G > 200G (güçlü)" if ok50 and ok200 and close > last.sma50 > last.sma200 else
             "fiyat < 50G < 200G (zayıf)" if ok50 and ok200 and close < last.sma50 < last.sma200 else "karışık")
    trend = {name: structure.structure(df)["trend"] for name, df in (("günlük", d), ("haftalık", w)) if df is not None and len(df) >= 30}
    earn = us_card.earnings((cal or {}).get("bilanco"), None, now.date())
    ahead = lambda day: day if day and day >= now.date().isoformat() else None      # Yahoo keeps last year's dividend dates
    val = valuation(f)
    notes = []
    if earn["risk"] == "YÜKSEK":
        notes.append(f"Bilanço {earn['gun']} gün sonra: açılış boşluğu riski yüksek. Yeni pozisyon bilanço sonrasına bırakılabilir ya da küçük tutulabilir.")
    elif earn["risk"] == "BİLİNMİYOR":
        notes.append("Sonraki bilanço tarihi bilinmiyor: KAP ya da şirketin yatırımcı sayfasından teyit et.")
    if align.startswith("fiyat < 50G"):
        notes.append("Fiyat 50 ve 200 günlük ortalamaların altında (zayıf yapı).")
    notes += [f"Kırmızı bayrak: {x}" for x in (f.get("kirmizi_bayraklar") or [])[:3]]
    if val["etiket"] == "PAHALI":
        notes.append("Değerleme kaba ölçüyle pahalı.")
    price_day = datetime.fromtimestamp(int(last.open_time) / 1000, bist.TR).date().isoformat()
    sources = [
        {"veri": "mali tablolar, marjlar, borç, temel puan", "kaynak": "İş Yatırım (şirketin KAP'a bildirdiği tablolar)", "tarih": f"son dönem {f.get('son_donem')}"},
        {"veri": "fiyat, ortalamalar, BIST 100'e göre güç", "kaynak": "Yahoo Finance (~15 dk gecikmeli)", "tarih": f"son kapanan gün {price_day}"},
        {"veri": "bilanço ve temettü takvimi", "kaynak": "Yahoo Finance", "tarih": "kesin tarih için KAP" if cal else "alınamadı"}]
    return {"hisse": f["hisse"], "piyasa": "BIST", "fiyat": f["fiyat"], "sektor": f.get("grup"), "endustri": None,
            "trend": {**trend, "hizalama": align, "zirveye_uzaklik_yuzde": round((close / float(d.close.tail(252).max()) - 1) * 100, 1)},
            "guc": {"endeks": "BIST 100", "endeks_6a": rel, "etiket": watch_cards.strength(rel) or "BİLİNMİYOR"},
            "bilanco": earn, "temettu": {"hak_kullanim": ahead((cal or {}).get("temettu_hak")), "odeme": ahead((cal or {}).get("temettu_odeme"))},
            "temel": {"skor": f["puan"]["skor"], "durum": f["puan"].get("etiket")}, "degerleme": val,
            "stage": (f.get("stage") or {}).get("aciklama"), "dikkat": notes, "kaynaklar": sources,
            "uretildi": now.isoformat(timespec="seconds"), "kod": us_card._version()}


async def card(code: str) -> tuple[dict, dict]:
    """(card, full fundamentals report) for one BIST stock, from live sources; the card goes to the audit log."""
    f = await fundamentals.report(code)
    sym = bist.yahoo_symbol(f["hisse"])
    async with httpx.AsyncClient() as client:
        d = market.add_indicators(await bist.fetch(client, sym, "1d"))
        w = market.add_indicators(await bist.fetch(client, sym, "1wk"))
        index = await bist.fetch(client, bist.INDEX, "1d")
        try:
            import features
            cal = await features._yahoo_calendar(client, sym)
        except Exception as e:
            log.info("BIST calendar for %s failed: %s", sym, str(e)[:80])
            cal = None
    c = build(f, d, w, index, cal)
    try:
        AUDIT.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT, "a", encoding="utf-8") as out:
            out.write(json.dumps(c, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("BIST card audit log failed: %s", e)
    return c, f


def _v(x) -> str:
    return "—" if x is None else f"{x:g}"


def text(c: dict, code: str = "tr") -> str:
    if code == "en":
        return text_en(c)
    t, g, e, v, div = c["trend"], c["guc"], c["bilanco"], c["degerleme"], c["temettu"]
    lines = [f"🇹🇷 {c['hisse']} — {c['fiyat']:g} TL" + (f" · {c['sektor']}" if c.get("sektor") else ""),
             "Trend: " + " · ".join(f"{k} {t[k]}" for k in ("günlük", "haftalık") if k in t) + f" · {t['hizalama']} · zirveye %{t['zirveye_uzaklik_yuzde']}",
             f"Güç (6 ay, BIST 100'e göre): {'—' if g['endeks_6a'] is None else format(g['endeks_6a'], '+g')} puan · {g['etiket']}",
             "Bilanço: " + (f"{e['tarih']} ({e['gun']} gün) · risk {e['risk']} · {e['kaynak']}" if e["tarih"] else "tarih bilinmiyor"),
             *([f"Temettü: hak kullanım {div['hak_kullanim'] or '—'} · ödeme {div['odeme'] or '—'}"] if div["hak_kullanim"] or div["odeme"] else []),
             f"Temel puan: {c['temel']['skor']}/100 ({c['temel']['durum']})",
             f"Değerleme: {v['etiket']} (kaba ölçü) · F/K {_v(v['fk'])} · PD/DD {_v(v['pd_dd'])} · FD/FAVÖK {_v(v['fd_favok'])}",
             *([f"Haftalık evre: {c['stage']}"] if c.get("stage") else [])]
    lines += ["", *(f"⚠️ {n}" for n in c["dikkat"])] if c["dikkat"] else []
    lines += ["", "Kaynaklar:", *(f"· {x['veri']}: {x['kaynak']} — {x['tarih']}" for x in c["kaynaklar"]),
              f"Üretildi {c['uretildi'][:16].replace('T', ' ')}" + (f" · kod {c['kod']}" if c.get("kod") else ""),
              "Karar desteği: AL/SAT önerisi değildir. Analist tahmin revizyonu ve geçmiş bilanço tepkisi BIST için ücretsiz kaynakta yok."]
    return "\n".join(lines)


def text_en(c: dict) -> str:
    """The same card in English: labels, notes and source rows (lang.label / lang.data)."""
    L = lambda v: lang.label("en", v)
    D = lambda v: lang.data("en", v)      # notes, source rows and labels the card stores in Turkish
    t, g, e, v, div = c["trend"], c["guc"], c["bilanco"], c["degerleme"], c["temettu"]
    lines = [f"🇹🇷 {c['hisse']} — {c['fiyat']:g} TL" + (f" · {c['sektor']}" if c.get("sektor") else ""),
             "Trend: " + " · ".join(f"{n} {L(t[k])}" for k, n in (("günlük", "daily"), ("haftalık", "weekly")) if k in t)
             + f" · {D(t['hizalama'])} · {t['zirveye_uzaklik_yuzde']}% below the high",
             f"Strength (6 months, against the BIST 100): {'—' if g['endeks_6a'] is None else format(g['endeks_6a'], '+g')} points · {L(g['etiket'])}",
             "Earnings: " + (f"{e['tarih']} ({e['gun']} days) · risk {L(e['risk'])} · {D(e['kaynak'])}" if e["tarih"] else "date unknown"),
             *([f"Dividend: ex-date {div['hak_kullanim'] or '—'} · payment {div['odeme'] or '—'}"] if div["hak_kullanim"] or div["odeme"] else []),
             f"Fundamental score: {c['temel']['skor']}/100 ({L(c['temel']['durum'])})",
             f"Valuation: {L(v['etiket'])} (coarse) · P/E {_v(v['fk'])} · P/B {_v(v['pd_dd'])} · EV/EBITDA {_v(v['fd_favok'])}",
             *([f"Weekly stage: {D(c['stage'])}"] if c.get("stage") else [])]
    lines += ["", *(f"⚠️ {D(n)}" for n in c["dikkat"])] if c["dikkat"] else []
    lines += ["", "Sources:", *(f"· {D(x['veri'])}: {D(x['kaynak'])} — {D(x['tarih'])}" for x in c["kaynaklar"]),
              f"Generated {c['uretildi'][:16].replace('T', ' ')}" + (f" · code {c['kod']}" if c.get("kod") else ""),
              "Decision support: not a BUY/SELL suggestion. Analyst estimate revisions and past earnings reactions are not available for BIST in a free source."]
    return "\n".join(lines)

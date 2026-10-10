"""One card per US stock: where it stands, in one screen, with the source and date of every number.

Decision support, not a signal. No US timing rule passed the history test (research/README.md: nine daily rules and
an earnings-drift rule, all behind buy & hold), so the card never says AL / SAT. It describes: trend, strength against
SPY / QQQ / the sector, the next earnings date and its gap risk, how the last report was received, where analysts'
estimates are moving, the fundamental score and a coarse valuation label. Labels come from fixed thresholds written
below; they are descriptions, not forecasts.

Every card is appended to backups/audit/abd_kart.jsonl (what was shown, from which sources, by which code version).
"""
import json
import logging
from datetime import date, datetime

import httpx

import alerts_store
import config
import db_backup
import lang
import us
import us_events
import us_fund

log = logging.getLogger(__name__)

AUDIT = db_backup.BACKUP_DIR / "audit" / "abd_kart.jsonl"
STRONG_PP = 10        # 6-month return this many points over / under the benchmark = GÜÇLÜ / ZAYIF
EARNINGS_SOON = 14    # days: ORTA risk inside this, YÜKSEK inside config.US_EARNINGS_BLOCK_DAYS
PEAD_NOTE = "Bağlam, sinyal değil: geçmiş testte iyi bilanço tepkisinden sonra piyasanın üstünde getiri çıkmadı."


def _strength(pp) -> str:
    return "BİLİNMİYOR" if pp is None else "GÜÇLÜ" if pp >= STRONG_PP else "ZAYIF" if pp <= -STRONG_PP else "NÖTR"


def earnings(next_day: str | None, estimate: str | None, today: date) -> dict:
    """The next report and its gap risk. The company's announced date wins; else the estimate from its own rhythm."""
    day, source = (next_day, "şirket takvimi (Yahoo)") if next_day else (estimate, "tahmin: önceki açıklamaların aralığı (SEC)")
    if not day:
        return {"tarih": None, "gun": None, "risk": "BİLİNMİYOR", "kaynak": None}
    days = (date.fromisoformat(day) - today).days
    if days < 0:
        return {"tarih": day, "gun": days, "risk": "BİLİNMİYOR", "kaynak": source + " (tarih geçmiş, yenisi açıklanmamış)"}
    risk = "YÜKSEK" if days <= config.US_EARNINGS_BLOCK_DAYS else "ORTA" if days <= EARNINGS_SOON else "DÜŞÜK"
    return {"tarih": day, "gun": days, "risk": risk, "kaynak": source}


def revisions(y: dict) -> dict:
    t = (y.get("tahminler") or {})
    n = t.get("+1y") or t.get("0y") or {}
    r30, r90, up, dn = n.get("revizyon_30g_yuzde"), n.get("revizyon_90g_yuzde"), n.get("yukari_30g"), n.get("asagi_30g")
    if r30 is None and up is None and dn is None:
        label = "BİLİNMİYOR"
    elif (r30 or 0) >= 1 or ((up or 0) > (dn or 0) and (r30 or 0) >= 0):
        label = "YUKARI"
    elif (r30 or 0) <= -1 or ((dn or 0) > (up or 0) and (r30 or 0) <= 0):
        label = "AŞAĞI"
    else:
        label = "YATAY"
    return {"eps_30g_yuzde": r30, "eps_90g_yuzde": r90, "yukari_30g": up, "asagi_30g": dn, "etiket": label}


def valuation(f: dict) -> dict:
    """Coarse on purpose: forward P/E over 35 or PEG over 2.5 = PAHALI; forward P/E under 15 with PEG under 1.5 (or
    unknown) = UCUZ; else MAKUL. A label for orientation, not a fair-value estimate."""
    fpe, peg, fcf = f.get("ileri_fk"), f.get("peg"), f.get("fcf_verimi_yuzde")
    if fpe is None and peg is None:
        label = "BİLİNMİYOR"
    elif (fpe is not None and fpe > 35) or (peg is not None and peg > 2.5):
        label = "PAHALI"
    elif fpe is not None and 0 < fpe < 15 and (peg is None or peg < 1.5):
        label = "UCUZ"
    else:
        label = "MAKUL"
    return {"ileri_fk": None if fpe is None else round(fpe, 1), "peg": peg, "fcf_verimi_yuzde": fcf, "etiket": label}


def build(f: dict, reaction: dict | None, estimate: str | None, price_day: str | None, yahoo_ts: float | None,
          now: datetime | None = None) -> dict:
    """The card from a us_fund.report() dict. Pure."""
    now = now or alerts_store.now_tr()
    y, t = f.get("analist") or {}, f["teknik"]
    earn = earnings(y.get("sonraki_bilanco"), estimate, us.now_ny().date() if now is None else now.astimezone(us.NY).date())
    rev, val = revisions(y), valuation(f)
    sur = [s for s in y.get("surprizler", []) if s.get("surpriz_yuzde") is not None]
    strength = {"spy_6a": t["rs_spy"].get("6a"), "qqq_6a": t.get("rs_qqq_6a"), "sektor_6a": t.get("rs_sektor_6a"),
                "sektor_etf": t.get("sektor_etf")}
    strength.update(spy=_strength(strength["spy_6a"]), qqq=_strength(strength["qqq_6a"]), sektor=_strength(strength["sektor_6a"]))
    notes = []
    if earn["risk"] == "YÜKSEK":
        notes.append(f"Bilanço {earn['gun']} gün sonra: açılış boşluğu (gap) riski yüksek. Yeni pozisyon bilanço sonrasına bırakılabilir "
                     "ya da küçük tutulabilir.")
    elif earn["risk"] == "BİLİNMİYOR":
        notes.append("Sonraki bilanço tarihi bilinmiyor: şirketin yatırımcı sayfasından teyit et.")
    if t["hizalama"].startswith("fiyat < 50G"):
        notes.append("Fiyat 50 ve 200 günlük ortalamaların altında (zayıf yapı).")
    if rev["etiket"] == "AŞAĞI":
        notes.append("Analist kâr tahminleri son 30 günde aşağı çekildi.")
    if val["etiket"] == "PAHALI":
        notes.append("Değerleme kaba ölçüyle pahalı: beklentinin altında bir bilanço daha sert düşürür.")
    sources = [
        {"veri": "bilanço, marjlar, nakit akışı", "kaynak": "SEC EDGAR (10-K / 10-Q, resmi)", "tarih": f"son çeyrek {f.get('son_ceyrek')}"},
        {"veri": "fiyat, ortalamalar, göreli güç", "kaynak": "Tiingo" if config.TIINGO_API_KEY else "Yahoo", "tarih": f"son kapanan gün {price_day}"},
        {"veri": "analist tahminleri, revizyonlar, sürprizler, bilanço takvimi", "kaynak": "Yahoo Finance",
         "tarih": datetime.fromtimestamp(yahoo_ts, alerts_store.TR).strftime("%Y-%m-%d %H:%M") if yahoo_ts else "alınamadı"},
        {"veri": "son bilanço açıklama zamanı", "kaynak": "SEC EDGAR (8-K madde 2.02, resmi)",
         "tarih": reaction["aciklama"] if reaction else "bulunamadı"}]
    return {"hisse": f["hisse"], "piyasa": "ABD", "fiyat": f["fiyat"], "sektor": y.get("sektor"), "endustri": y.get("endustri"),
            "trend": {**t["trend"], "hizalama": t["hizalama"], "zirveye_uzaklik_yuzde": t["zirveye_uzaklik_yuzde"]},
            "guc": strength, "bilanco": earn,
            "son_bilanco": {"tepki": reaction, "surpriz_yuzde": sur[-1]["surpriz_yuzde"] if sur else None,
                            "ceyrek": sur[-1]["ceyrek"] if sur else None, "not": PEAD_NOTE},
            "revizyon": rev, "temel": {"skor": f["puan"]["skor"], "durum": f["puan"]["durum"]}, "degerleme": val,
            "dikkat": notes, "kaynaklar": sources, "uretildi": now.isoformat(timespec="seconds"), "kod": _version()}


def _version() -> str | None:
    try:
        import danisman
        return (danisman.code_version().get("git_commit") or "")[:12] or None
    except Exception:
        return None


def audit(c: dict):
    try:
        AUDIT.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("US card audit log failed: %s", e)


async def card(t: str) -> tuple[dict, dict]:
    """(card, full fundamentals report) for one ticker, from live sources; the card is written to the audit log."""
    f = await us_fund.report(t)
    sym = f["hisse"]
    async with httpx.AsyncClient() as client:
        d = await us.fetch(client, sym, "1d")              # cached by us.fetch: the report just loaded these
        spy = await us.fetch(client, "SPY", "1d", bulk=True)
        try:
            times = await us_events.releases(client, sym)
        except Exception as e:
            log.warning("SEC releases for %s failed: %s", sym, e)
            times = []
    try:
        yahoo_ts = json.loads((us_fund.CACHE_DIR / f"{sym}_yahoo.json").read_text(encoding="utf-8"))["zaman"] if f.get("analist") else None
    except (OSError, ValueError, KeyError):
        yahoo_ts = None
    price_day = datetime.fromtimestamp(int(d.open_time.iloc[-1]) / 1000, us.NY).date().isoformat()
    c = build(f, us_events.last_reaction(d, spy, times), us_events.expected_next(times), price_day, yahoo_ts)
    audit(c)
    return c, f


def _n(x, suffix="") -> str:
    return "—" if x is None else f"{x:+g}{suffix}"


def text(c: dict, code: str = "tr") -> str:
    if code == "en":
        return text_en(c)
    g, e, r, v, s = c["guc"], c["bilanco"], c["revizyon"], c["degerleme"], c["son_bilanco"]
    tr = c["trend"]
    lines = [f"🇺🇸 {c['hisse']} — {c['fiyat']:g} $" + (f" · {c['sektor']} / {c['endustri']}" if c.get("sektor") else ""),
             "Trend: " + " · ".join(f"{k} {tr[k]}" for k in ("günlük", "haftalık", "aylık") if k in tr)
             + f" · {tr['hizalama']} · zirveye %{tr['zirveye_uzaklik_yuzde']}",
             f"Güç (6 ay, puan farkı): SPY {_n(g['spy_6a'])} {g['spy']} · QQQ {_n(g['qqq_6a'])} {g['qqq']}"
             + (f" · sektör {g['sektor_etf']} {_n(g['sektor_6a'])} {g['sektor']}" if g.get("sektor_etf") else ""),
             ("Bilanço: " + (f"{e['tarih']} ({e['gun']} gün) · risk {e['risk']} · {e['kaynak']}" if e["tarih"] else "tarih bilinmiyor"))]
    rc = s["tepki"]
    if rc:
        lines.append(f"Son bilanço: {rc['aciklama']} · ilk seans %{rc['tepki_yuzde']:+g} (SPY'ye göre {_n(rc['spy_gore_yuzde'], ' puan')}) · "
                     f"o günden beri %{rc['o_gunden_beri_yuzde']:+g}" + (f" · EPS sürprizi %{s['surpriz_yuzde']:+g}" if s["surpriz_yuzde"] is not None else ""))
        lines.append("   " + s["not"])
    lines += [f"Analist revizyonu: {r['etiket']} · EPS tahmini 30 gün %{_n(r['eps_30g_yuzde'])}, 90 gün %{_n(r['eps_90g_yuzde'])} · "
              f"yukarı {r['yukari_30g'] if r['yukari_30g'] is not None else '—'} / aşağı {r['asagi_30g'] if r['asagi_30g'] is not None else '—'}",
              f"Temel puan: {c['temel']['skor']}/100 ({c['temel']['durum']})",
              f"Değerleme: {v['etiket']} (kaba ölçü) · ileri F/K {v['ileri_fk'] if v['ileri_fk'] is not None else '—'} · PEG "
              f"{v['peg'] if v['peg'] is not None else '—'} · FCF verimi %{v['fcf_verimi_yuzde'] if v['fcf_verimi_yuzde'] is not None else '—'}"]
    lines += ["", *(f"⚠️ {n}" for n in c["dikkat"])] if c["dikkat"] else []
    lines += ["", "Kaynaklar:", *(f"· {x['veri']}: {x['kaynak']} — {x['tarih']}" for x in c["kaynaklar"]),
              f"Üretildi {c['uretildi'][:16].replace('T', ' ')}" + (f" · kod {c['kod']}" if c.get("kod") else ""),
              "Karar desteği: AL/SAT önerisi değildir. ABD'de test edilen zamanlama kurallarının hiçbiri al-tut'u geçemedi."]
    return "\n".join(lines)


def text_en(c: dict) -> str:
    """The same card in English: labels, notes and source rows (lang.label / lang.data)."""
    L = lambda v: lang.label("en", v)
    D = lambda v: lang.data("en", v)      # notes, source rows and labels the card stores in Turkish
    g, e, r, v, s = c["guc"], c["bilanco"], c["revizyon"], c["degerleme"], c["son_bilanco"]
    tr = c["trend"]
    dash = lambda x: "—" if x is None else x
    lines = [f"🇺🇸 {c['hisse']} — {c['fiyat']:g} $" + (f" · {c['sektor']} / {c['endustri']}" if c.get("sektor") else ""),
             "Trend: " + " · ".join(f"{n} {L(tr[k])}" for k, n in (("günlük", "daily"), ("haftalık", "weekly"), ("aylık", "monthly")) if k in tr)
             + f" · {D(tr['hizalama'])} · {tr['zirveye_uzaklik_yuzde']}% below the high",
             f"Strength (6 months, points): SPY {_n(g['spy_6a'])} {L(g['spy'])} · QQQ {_n(g['qqq_6a'])} {L(g['qqq'])}"
             + (f" · sector {g['sektor_etf']} {_n(g['sektor_6a'])} {L(g['sektor'])}" if g.get("sektor_etf") else ""),
             ("Earnings: " + (f"{e['tarih']} ({e['gun']} days) · risk {L(e['risk'])} · {D(e['kaynak'])}" if e["tarih"] else "date unknown"))]
    rc = s["tepki"]
    if rc:
        lines.append(f"Last earnings: {rc['aciklama']} · first session {rc['tepki_yuzde']:+g}% ({_n(rc['spy_gore_yuzde'], ' points')} against SPY) · "
                     f"since then {rc['o_gunden_beri_yuzde']:+g}%" + (f" · EPS surprise {s['surpriz_yuzde']:+g}%" if s["surpriz_yuzde"] is not None else ""))
        lines.append("   Context, not a signal: in the history test a good earnings reaction was not followed by a return above the market.")
    lines += [f"Analyst revisions: {L(r['etiket'])} · EPS estimate 30 days {_n(r['eps_30g_yuzde'])}%, 90 days {_n(r['eps_90g_yuzde'])}% · "
              f"up {dash(r['yukari_30g'])} / down {dash(r['asagi_30g'])}",
              f"Fundamental score: {c['temel']['skor']}/100 ({L(c['temel']['durum'])})",
              f"Valuation: {L(v['etiket'])} (coarse) · forward P/E {dash(v['ileri_fk'])} · PEG {dash(v['peg'])} · FCF yield {dash(v['fcf_verimi_yuzde'])}%"]
    lines += ["", *(f"⚠️ {D(n)}" for n in c["dikkat"])] if c["dikkat"] else []
    lines += ["", "Sources:", *(f"· {D(x['veri'])}: {D(x['kaynak'])} — {D(x['tarih'])}" for x in c["kaynaklar"]),
              f"Generated {c['uretildi'][:16].replace('T', ' ')}" + (f" · code {c['kod']}" if c.get("kod") else ""),
              "Decision support: not a BUY/SELL suggestion. No timing rule tested on US stocks beat buy-and-hold."]
    return "\n".join(lines)

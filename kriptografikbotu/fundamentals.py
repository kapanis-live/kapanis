"""BIST investment engine: company financials from İş Yatırım's public statement service (free, no key).

Hierarchy (medium/long term): is the company good -> is growth real (USD, not just inflation) -> does profit
turn into cash -> is debt safe -> ROE -> valuation -> is the chart OK for accumulating (Stage).
All numbers are computed here; the AI writes the thesis, catalysts and risks around them.

Notes
- Income and cash-flow items are year-to-date; TTM = last full year + this YTD − same YTD a year ago.
- Since 2024 Turkish statements are inflation-adjusted (TMS 29). TL growth is still inflated by the lira's
  fall, so growth is also shown in USD (period-end USD/TRY, approximate).
- Banks use a different statement (UFRS) and different metrics (ROE, P/B, loans, deposits, cost of risk).
- Shares = paid-in capital (1 TL nominal per share in Turkey), so market cap ≈ price × paid-in capital.
- Catalysts, management and holding NAV discounts are not computable here: the score leaves them out.
"""
import json
import logging
import time
from datetime import datetime

import httpx

import bist
import config
import market
import structure

log = logging.getLogger(__name__)

URL = "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124", "Referer": "https://www.isyatirim.com.tr/"}
CACHE_DIR = config.DATA_DIR / "temel"
CACHE_SECONDS = 12 * 3600
BANKS = {"AKBNK", "GARAN", "ISCTR", "YKBNK", "VAKBN", "HALKB", "TSKB", "SKBNK", "ALBRK", "ICBCT", "QNBTR", "KLNMA"}


async def _query(client: httpx.AsyncClient, code: str, group: str, periods: list[tuple[int, int]]) -> dict[str, dict]:
    params = {"companyCode": code, "exchange": "TRY", "financialGroup": group}
    for i, (y, m) in enumerate(periods, start=1):
        params[f"year{i}"], params[f"period{i}"] = y, m
    r = await client.get(URL, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    rows = r.json().get("value") or []
    out: dict[str, dict] = {}
    for i, (y, m) in enumerate(periods, start=1):
        vals = {row["itemCode"]: row.get(f"value{i}") for row in rows if row.get(f"value{i}") is not None}
        if vals and any(v not in (0, None) for v in vals.values()):
            out[f"{y}/{m}"] = {k: float(v) for k, v in vals.items()}
    return out


async def statements(client: httpx.AsyncClient, code: str) -> tuple[str, dict[str, dict]]:
    """(group, {"2026/6": {itemCode: value}}) for the last ~3 years, cached."""
    CACHE_DIR.mkdir(exist_ok=True)
    f = CACHE_DIR / f"{code}.json"
    try:
        cached = json.loads(f.read_text(encoding="utf-8"))
        if time.time() - cached["zaman"] < CACHE_SECONDS:
            return cached["grup"], cached["donemler"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    year = datetime.now().year
    groups = ["UFRS", "XI_29"] if code in BANKS else ["XI_29", "UFRS"]
    for group in groups:
        data: dict[str, dict] = {}
        for y in (year, year - 1, year - 2):
            try:
                data.update(await _query(client, code, group, [(y, 12), (y, 9), (y, 6), (y, 3)]))
            except Exception as e:
                log.warning("Statements %s %s %s failed: %s", code, group, y, e)
        key = "3Z"
        if sum(key in v for v in data.values()) >= 5:
            f.write_text(json.dumps({"zaman": time.time(), "grup": group, "donemler": data}), encoding="utf-8")
            return group, data
    raise ValueError(f"{code} için mali tablo bulunamadı (İş Yatırım)")


def _p(key: str) -> tuple[int, int]:
    y, m = key.split("/")
    return int(y), int(m)


def ttm(data: dict, code: str, period: str) -> float | None:
    """Trailing twelve months of a year-to-date item. Pure."""
    y, m = _p(period)
    cur = data.get(period, {}).get(code)
    if cur is None:
        return None
    if m == 12:
        return cur
    fy, prev = data.get(f"{y - 1}/12", {}).get(code), data.get(f"{y - 1}/{m}", {}).get(code)
    return None if fy is None or prev is None else fy + cur - prev


def _bal(data: dict, period: str, *codes: str) -> float | None:
    vals = [data.get(period, {}).get(c) for c in codes]
    return None if all(v is None for v in vals) else sum(v or 0 for v in vals)


def _g(a, b):
    return None if a is None or b in (None, 0) or (a < 0) != (b < 0) and b < 0 else round((a / b - 1) * 100, 1)


def _pct(a, b):
    return None if a is None or not b else round(a / b * 100, 1)


def compute(group: str, data: dict, price: float, fx: dict | None = None) -> dict:
    """Metrics, red flags, valuation and scores from statements. Pure (fx: period -> USD/TRY)."""
    periods = sorted(data, key=_p)
    last = next((p for p in reversed(periods) if ttm(data, "3Z", p) is not None), None)
    if last is None:
        raise ValueError("TTM hesaplanacak kadar dönem yok")
    y, m = _p(last)
    prev = f"{y - 1}/{m}"
    t = lambda code, p=last: ttm(data, code, p)
    out = {"son_donem": last, "grup": "banka" if group == "UFRS" else "sanayi/hizmet", "fiyat": price}
    shares = data[last].get("2OA")
    ni, ni_prev = t("3Z"), t("3Z", prev)
    equity, equity_prev = _bal(data, last, "2O"), _bal(data, prev, "2O")
    mcap = price * shares if shares else None
    out["piyasa_degeri_tl"] = round(mcap) if mcap else None
    out["net_kar_ttm"] = ni
    out["net_kar_buyume_yuzde"] = _g(ni, ni_prev)
    avg_eq = (equity + equity_prev) / 2 if equity and equity_prev else equity
    out["roe_yuzde"] = _pct(ni, avg_eq)
    out["fk"] = round(mcap / ni, 1) if mcap and ni and ni > 0 else None
    out["pd_dd"] = round(mcap / equity, 2) if mcap and equity and equity > 0 else None
    flags = []
    if equity is not None and equity <= 0:
        flags.append("özkaynak negatif")
    if group == "UFRS":  # bank
        loans, loans_prev = _bal(data, last, "1AF"), _bal(data, prev, "1AF")
        dep, dep_prev = _bal(data, last, "2A"), _bal(data, prev, "2A")
        out.update(kredi_buyume_yuzde=_g(loans, loans_prev), mevduat_buyume_yuzde=_g(dep, dep_prev),
                   kredi_mevduat=round(loans / dep, 2) if loans and dep else None,
                   komisyon_buyume_yuzde=_g(t("3CA"), t("3CA", prev)),
                   risk_maliyeti_yuzde=_pct(t("3CF"), (loans + loans_prev) / 2 if loans and loans_prev else loans),
                   gider_gelir_yuzde=_pct(t("3CG"), t("3CE")))
        if fx and fx.get(last) and fx.get(prev) and loans and loans_prev:
            out["kredi_buyume_usd_yuzde"] = _g(loans / fx[last], loans_prev / fx[prev])
        if out["kredi_mevduat"] and out["kredi_mevduat"] > 1.1:
            flags.append(f"kredi/mevduat {out['kredi_mevduat']} (fonlama baskısı)")
        if out["risk_maliyeti_yuzde"] and out["risk_maliyeti_yuzde"] > 3:
            flags.append(f"risk maliyeti %{out['risk_maliyeti_yuzde']} (karşılık yükü)")
    else:
        rev, rev_prev = t("3C"), t("3C", prev)
        ebit, ebit_prev = t("3DF"), t("3DF", prev)
        da = t("4CAB") or 0
        ebitda = (ebit + da) if ebit is not None else None
        fcf = t("4CB")
        debt, debt_prev = _bal(data, last, "2AA", "2BA"), _bal(data, prev, "2AA", "2BA")
        cash = _bal(data, last, "1AA", "1AB") or 0
        net_debt = (debt or 0) - cash
        out.update(
            ciro_ttm=rev, ciro_buyume_tl_yuzde=_g(rev, rev_prev),
            brut_marj_yuzde=_pct(t("3D"), rev), favok_ttm=ebitda, favok_marj_yuzde=_pct(ebitda, rev),
            faaliyet_marj_yuzde=_pct(ebit, rev), faaliyet_marj_gecen_yil_yuzde=_pct(ebit_prev, rev_prev),
            net_marj_yuzde=_pct(ni, rev), serbest_nakit_akimi_ttm=fcf,
            fcf_net_kar=round(fcf / ni, 2) if fcf is not None and ni and ni > 0 else None,
            net_borc=round(net_debt), net_borc_favok=round(net_debt / ebitda, 2) if ebitda and ebitda > 0 else None,
            faiz_karsilama=round(ebit / abs(t("3HC")), 2) if ebit is not None and t("3HC") else None,
            fd_favok=round((mcap + net_debt) / ebitda, 1) if mcap and ebitda and ebitda > 0 else None,
            fcf_verimi_yuzde=_pct(fcf, mcap),
        )
        if fx and fx.get(last) and fx.get(prev) and rev and rev_prev:
            out["ciro_buyume_usd_yuzde"] = _g(rev / fx[last], rev_prev / fx[prev])
        # red flags
        if ni and ni > 0 and fcf is not None and fcf < 0:
            flags.append("net kâr var ama serbest nakit akımı negatif")
        pre_tax, inv_income = t("3I"), t("3HA")
        if pre_tax and pre_tax > 0 and inv_income and inv_income > 0.5 * pre_tax:
            flags.append(f"vergi öncesi kârın %{inv_income / pre_tax * 100:.0f}'i yatırım faaliyeti geliri (tek seferlik olabilir)")
        rec_g, inv_g, rev_g = _g(_bal(data, last, "1AC"), _bal(data, prev, "1AC")), _g(_bal(data, last, "1AF"), _bal(data, prev, "1AF")), out["ciro_buyume_tl_yuzde"]
        if rec_g is not None and rev_g is not None and rec_g > rev_g + 25:
            flags.append(f"ticari alacaklar (%{rec_g:+.0f}) satıştan (%{rev_g:+.0f}) çok hızlı büyüyor")
        if inv_g is not None and rev_g is not None and inv_g > rev_g + 25:
            flags.append(f"stoklar (%{inv_g:+.0f}) satıştan (%{rev_g:+.0f}) çok hızlı büyüyor")
        dg = _g(debt, debt_prev)
        if dg is not None and dg > 40:
            flags.append(f"finansal borç yılda %{dg:+.0f} arttı")
        if ebit is not None and ebit < 0:
            flags.append("esas faaliyet zararı (TTM)")
        m_now, m_prev = out["faaliyet_marj_yuzde"], out["faaliyet_marj_gecen_yil_yuzde"]
        if m_now is not None and m_prev is not None and m_now < m_prev - 3:
            flags.append(f"faaliyet marjı düşüyor (%{m_prev} → %{m_now})")
        if out["net_borc_favok"] is not None and out["net_borc_favok"] > 3:
            flags.append(f"net borç/FAVÖK {out['net_borc_favok']} (yüksek)")
        if out["faiz_karsilama"] is not None and 0 < out["faiz_karsilama"] < 1.5:
            flags.append(f"faaliyet kârı finansman giderini ancak {out['faiz_karsilama']} kat karşılıyor")
    out["kirmizi_bayraklar"] = flags
    return out


def score(f: dict, stage: dict | None) -> dict:
    """Computable parts of the 100-point investment score (catalyst /10 and management /5 are left to judgment)."""
    parts: dict[str, tuple[float, float]] = {}
    roe = f.get("roe_yuzde")
    parts["kârlılık/ROE"] = (10 if roe and roe > 25 else 7 if roe and roe > 15 else 4 if roe and roe > 8 else 1, 10)
    tech = {2: 5, 1: 3, 3: 2, 4: 0}.get((stage or {}).get("stage"), 2)
    parts["teknik (Stage)"] = (tech, 5)
    if f["grup"] == "banka":
        g = f.get("kredi_buyume_usd_yuzde")
        parts["büyüme"] = (15 if g is not None and g > 15 else 10 if g is not None and g > 5 else 6 if g is not None and g > -5 else 3, 15)
        parts["finansal kalite"] = (20 - 5 * len(f["kirmizi_bayraklar"]) if f.get("net_kar_ttm", 0) > 0 else 4, 20)
        ld = f.get("kredi_mevduat")
        parts["bilanço"] = (10 if ld and ld < 0.9 else 7 if ld and ld < 1.1 else 3, 10)
        pb = f.get("pd_dd")
        ratio = pb / (roe / 100) if pb and roe and roe > 0 else None  # P/B per unit of ROE
        parts["değerleme"] = (15 if ratio is not None and ratio < 3 else 10 if ratio is not None and ratio < 5 else 5 if ratio is not None and ratio < 8 else 2, 15)
    else:
        g = f.get("ciro_buyume_usd_yuzde")
        parts["büyüme (USD)"] = (15 if g is not None and g > 15 else 10 if g is not None and g > 5 else 6 if g is not None and g > -5 else 2, 15)
        q = 0
        q += 5 if (f.get("faaliyet_marj_yuzde") or -1) > 0 else 0
        q += 5 if (f.get("net_kar_ttm") or -1) > 0 else 0
        q += 5 if not any("tek seferlik" in x for x in f["kirmizi_bayraklar"]) else 0
        q += 5 if not any("marjı düşüyor" in x for x in f["kirmizi_bayraklar"]) else 0
        parts["finansal kalite"] = (q, 20)
        nd = f.get("net_borc_favok")
        net_cash = (f.get("net_borc") or 0) < 0
        parts["bilanço"] = (10 if net_cash or (nd is not None and nd < 1) else 7 if nd is not None and nd < 2 else 4 if nd is not None and nd < 3 else 1, 10)
        fcf, ratio = f.get("serbest_nakit_akimi_ttm"), f.get("fcf_net_kar")
        parts["nakit akışı"] = (10 if fcf and fcf > 0 and ratio and ratio > 0.7 else 7 if fcf and fcf > 0 else 2 if (f.get("net_kar_ttm") or 0) > 0 else 4, 10)
        pe, ev = f.get("fk"), f.get("fd_favok")
        v = 15 if pe and pe < 8 and ev and ev < 6 else 10 if (pe and pe < 12) or (ev and ev < 8) else 6 if pe and pe < 20 else 3 if not pe else 2
        parts["değerleme"] = (v, 15)
    got = sum(max(0, a) for a, _ in parts.values())
    maxi = sum(b for _, b in parts.values())
    total = round(got / maxi * 100)
    valuation = parts.get("değerleme", (0, 15))[0]
    label = ("BİRİKTİRME ADAYI" if total >= 70 and valuation >= 10 else "KALİTELİ AMA FİYATLI" if total >= 70 else
             "İZLEME LİSTESİ" if total >= 55 else "ZAYIF — BEKLE" if total >= 40 else "TEZ ZAYIF")
    if stage and stage.get("stage") == 4:
        label += " (Stage 4: biriktirme için erken)"
    return {"skor": total, "etiket": label, "parcalar": {k: f"{max(0, a):.0f}/{b:.0f}" for k, (a, b) in parts.items()},
            "not": f"yatırım kalite skoru, getiri olasılığı DEĞİL; katalizör (10) ve yönetim (5) hariç {maxi:.0f} puan üzerinden"}


async def report(code: str) -> dict:
    code = bist.ticker(code)
    async with httpx.AsyncClient() as client:
        group, data = await statements(client, code)
        price = await bist.last_price(client, code)
        weekly = market.add_indicators(await bist.fetch(client, code, "1wk"))
        try:
            fxdf = await bist.fetch(client, bist.FX, "1wk")
            fx_series = {datetime.fromtimestamp(int(t) / 1000, bist.TR).date(): float(c) for t, c in zip(fxdf.open_time, fxdf.close)}
        except Exception:
            fx_series = {}
    fx = {}
    for p in data:
        y, m = _p(p)
        end = datetime(y, m, 28).date()
        prior = [d for d in fx_series if d <= end]
        if prior:
            fx[p] = fx_series[max(prior)]
    f = compute(group, data, price, fx)
    st = structure.stage(weekly)
    f["stage"] = st
    f["puan"] = score(f, st)
    f["hisse"] = code
    f["kaynak"] = "İş Yatırım mali tabloları (TMS 29 enflasyon muhasebesi dönemi); fiyat Yahoo ~15 dk gecikmeli"
    return f


def _m(x) -> str:
    if x is None:
        return "—"
    a = abs(x)
    return f"{x / 1e9:,.1f} mr" if a >= 1e9 else f"{x / 1e6:,.1f} mn" if a >= 1e6 else f"{x:,.0f}"


def _v(x, suffix: str = "") -> str:
    return "—" if x is None else f"{x:g}{suffix}"


def text(f: dict) -> str:
    s = f["puan"]
    lines = [f"🏢 {f['hisse']} — TEMEL ANALİZ ({f['grup']}, son dönem {f['son_donem']}, TTM)",
             f"Fiyat {f['fiyat']:g} TL · piyasa değeri {_m(f.get('piyasa_degeri_tl'))} TL",
             f"Net kâr {_m(f.get('net_kar_ttm'))} (yıllık %{_v(f.get('net_kar_buyume_yuzde'))}) · ROE %{_v(f.get('roe_yuzde'))}"]
    if f["grup"] == "banka":
        lines += [f"Kredi büyümesi %{_v(f.get('kredi_buyume_yuzde'))} (USD %{_v(f.get('kredi_buyume_usd_yuzde'))}) · "
                  f"mevduat %{_v(f.get('mevduat_buyume_yuzde'))} · kredi/mevduat {_v(f.get('kredi_mevduat'))}",
                  f"Komisyon büyümesi %{_v(f.get('komisyon_buyume_yuzde'))} · risk maliyeti %{_v(f.get('risk_maliyeti_yuzde'))} · "
                  f"gider/gelir %{_v(f.get('gider_gelir_yuzde'))}",
                  f"Değerleme: F/K {_v(f.get('fk'))} · PD/DD {_v(f.get('pd_dd'))}"]
    else:
        lines += [f"Ciro {_m(f.get('ciro_ttm'))} · büyüme TL %{_v(f.get('ciro_buyume_tl_yuzde'))} / USD %{_v(f.get('ciro_buyume_usd_yuzde'))}",
                  f"Marjlar: brüt %{_v(f.get('brut_marj_yuzde'))} · FAVÖK %{_v(f.get('favok_marj_yuzde'))} · "
                  f"faaliyet %{_v(f.get('faaliyet_marj_yuzde'))} (geçen yıl %{_v(f.get('faaliyet_marj_gecen_yil_yuzde'))}) · net %{_v(f.get('net_marj_yuzde'))}",
                  f"Nakit: serbest nakit akımı {_m(f.get('serbest_nakit_akimi_ttm'))} · FCF/net kâr {_v(f.get('fcf_net_kar'))}",
                  f"Bilanço: net borç {_m(f.get('net_borc'))} · net borç/FAVÖK {_v(f.get('net_borc_favok'))} · faiz karşılama {_v(f.get('faiz_karsilama'))}",
                  f"Değerleme: F/K {_v(f.get('fk'))} · FD/FAVÖK {_v(f.get('fd_favok'))} · PD/DD {_v(f.get('pd_dd'))} · FCF verimi %{_v(f.get('fcf_verimi_yuzde'))}"]
    st = f.get("stage")
    if st:
        lines.append(f"Teknik (haftalık): {st['aciklama']}" + (f" · {st['taban_kirilimi']}" if st.get("taban_kirilimi") else ""))
    lines.append("🚩 " + " · ".join(f["kirmizi_bayraklar"]) if f["kirmizi_bayraklar"] else "✅ Kırmızı bayrak yok")
    lines += ["", f"📊 SKOR {s['skor']}/100 → {s['etiket']}",
              " · ".join(f"{k} {v}" for k, v in s["parcalar"].items()),
              s["not"],
              "Döngüsel sektörlerde düşük F/K kâr zirvesi olabilir; tek seferlik gelirler ve katalizörler için KAP'ı kontrol et."]
    return "\n".join(lines)

"""US equity engine: SEC EDGAR financials (official, free) + Yahoo analyst estimates/earnings + technicals.

Return ≈ earnings growth + valuation change + shareholder yield, so growth and valuation are kept apart.
Computed here: growth (TTM, quarterly YoY acceleration, 3y CAGR), margins, FCF, SBC and dilution, buybacks,
shareholder yield, ROE/ROIC, net cash, interest coverage, P/E, forward P/E, PEG, EV/EBITDA, EV/Sales, FCF yield,
Rule of 40, estimate revisions (30/90 days), earnings surprises, next earnings date, short interest, insiders,
institutions, relative strength, Stage, "patlama" checklist, warning list and a 100-point quality score.
Not available for free: management guidance and earnings-call text; moat and TAM are left to judgment.
"""
import json
import logging
import time
from datetime import date, datetime, timedelta

import httpx

import config
import market
import us

log = logging.getLogger(__name__)

CACHE_DIR = config.DATA_DIR / "abd_temel"
SEC_TTL = 24 * 3600
YAHOO_TTL = 6 * 3600
QS = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

CONCEPTS = {
    "ciro": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
             "RevenueFromContractWithCustomerIncludingAssessedTax", "RevenuesNetOfInterestExpense"],
    "brut_kar": ["GrossProfit"],
    "satis_maliyeti": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "faaliyet_kari": ["OperatingIncomeLoss"],
    "net_kar": ["NetIncomeLoss", "ProfitLoss"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
    "hisse_seyreltilmis": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "isletme_nakit": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "geri_alim": ["PaymentsForRepurchaseOfCommonStock"],
    "temettu": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "faiz_gideri": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
    "amortisman": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet"],
    "vergi": ["IncomeTaxExpenseBenefit"],
    "vergi_oncesi": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                     "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
}
BALANCE = {
    "nakit": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "kisa_yatirim": ["MarketableSecuritiesCurrent", "ShortTermInvestments", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "uzun_borc": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "kisa_borc": ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings"],
    "ozkaynak": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "stok": ["InventoryNet"],
    "alacak": ["AccountsReceivableNetCurrent"],
    "hisse_sayisi": ["EntityCommonStockSharesOutstanding"],  # dei
}


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _entries(facts: dict, names: list[str], unit_pref=("USD", "USD/shares", "shares")) -> list[dict]:
    """Entries for a concept. Companies switch tags over the years (e.g. Revenues -> RevenueFromContract...),
    so the most recently reported tag leads and older tags fill the periods it doesn't cover."""
    found = []
    for name in names:
        for ns in ("us-gaap", "dei"):
            node = facts.get(ns, {}).get(name)
            if not node:
                continue
            for u in unit_pref:
                if u in node["units"] and node["units"][u]:
                    rows = node["units"][u]
                    found.append((max(r["end"] for r in rows), rows))
                    break
    if not found:
        return []
    found.sort(key=lambda x: x[0], reverse=True)
    merged = list(found[0][1])
    seen = {(r.get("start"), r["end"]) for r in merged}
    for _, rows in found[1:]:
        for r in rows:
            k = (r.get("start"), r["end"])
            if k not in seen:
                merged.append(r)
                seen.add(k)
    return merged


def quarters(entries: list[dict]) -> dict[str, float]:
    """Discrete quarter values by period end, from 3-month entries and differences of year-to-date entries. Pure."""
    by_span: dict[tuple, dict] = {}
    for e in entries:
        if "start" not in e:
            continue
        k = (e["start"], e["end"])
        if k not in by_span or e.get("filed", "") > by_span[k].get("filed", ""):
            by_span[k] = e
    q: dict[str, float] = {}
    ytd: dict[str, list[tuple[date, float]]] = {}
    for (s, e), row in by_span.items():
        days = (_d(e) - _d(s)).days
        if 80 <= days <= 100:
            q[e] = float(row["val"])
        elif days > 100:
            ytd.setdefault(s, []).append((_d(e), float(row["val"])))
    for s, rows in ytd.items():
        rows.sort()
        first_q_end = [e for (st, e) in by_span if st == s and 80 <= (_d(e) - _d(st)).days <= 100]
        prev_val, prev_end = (by_span[(s, first_q_end[0])]["val"], _d(first_q_end[0])) if first_q_end else (None, None)
        for end, val in rows:
            if prev_val is not None and end.isoformat() not in q and 80 <= (end - prev_end).days <= 100:
                q[end.isoformat()] = val - prev_val
            prev_val, prev_end = val, end
    return dict(sorted(q.items()))


def annual(entries: list[dict]) -> dict[str, float]:
    out = {}
    for e in entries:
        if "start" in e and 350 <= (_d(e["end"]) - _d(e["start"])).days <= 380:
            if e["end"] not in out or e.get("form") == "10-K":
                out[e["end"]] = float(e["val"])
    return dict(sorted(out.items()))


def instants(entries: list[dict]) -> dict[str, float]:
    out = {}
    for e in entries:
        if "start" not in e:
            out[e["end"]] = float(e["val"])
    return dict(sorted(out.items()))


def ttm(q: dict[str, float], end: str | None = None) -> float | None:
    """Sum of the four quarters ending at `end` (latest if None), if they are consecutive."""
    ends = sorted(q)
    if end is not None:
        ends = [e for e in ends if e <= end]
    if len(ends) < 4:
        return None
    last4 = ends[-4:]
    if (_d(last4[-1]) - _d(last4[0])).days > 300:
        return None
    return sum(q[e] for e in last4)


def _year_ago(ends: list[str], end: str) -> str | None:
    target = _d(end) - timedelta(days=365)
    cands = [e for e in ends if abs((_d(e) - target).days) <= 20]
    return cands[-1] if cands else None


def _g(a, b):
    return None if a is None or not b or b < 0 else round((a / b - 1) * 100, 1)


def _pct(a, b):
    return None if a is None or not b else round(a / b * 100, 1)


async def sec_facts(client: httpx.AsyncClient, t: str) -> dict:
    CACHE_DIR.mkdir(exist_ok=True)
    f = CACHE_DIR / f"{t}_sec.json"
    try:
        cached = json.loads(f.read_text(encoding="utf-8"))
        if time.time() - cached["zaman"] < SEC_TTL:
            return cached["facts"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    await us.is_us_ticker(client, t)  # loads the ticker -> CIK map
    cik = us.cik(t)
    if not cik:
        raise ValueError(f"{t} SEC'te şirket olarak bulunamadı (ETF/fon olabilir)")
    r = await client.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json",
                         headers={"User-Agent": config.SEC_USER_AGENT}, timeout=30)
    r.raise_for_status()
    facts = r.json()["facts"]
    keep = {ns: {k: v for k, v in facts.get(ns, {}).items()
                 if k in {c for names in list(CONCEPTS.values()) + list(BALANCE.values()) for c in names}}
            for ns in ("us-gaap", "dei")}
    f.write_text(json.dumps({"zaman": time.time(), "facts": keep}), encoding="utf-8")
    return keep


_crumb: tuple[float, str, dict] | None = None


async def yahoo_summary(client: httpx.AsyncClient, t: str) -> dict:
    """Analyst estimates, earnings history/calendar, key statistics. Cached per ticker."""
    global _crumb
    CACHE_DIR.mkdir(exist_ok=True)
    f = CACHE_DIR / f"{t}_yahoo.json"
    try:
        cached = json.loads(f.read_text(encoding="utf-8"))
        if time.time() - cached["zaman"] < YAHOO_TTL:
            return cached["veri"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    if _crumb is None or time.time() - _crumb[0] > 3600:
        async with httpx.AsyncClient(headers=UA, follow_redirects=True, timeout=20) as c:
            await c.get("https://fc.yahoo.com")
            crumb = (await c.get("https://query2.finance.yahoo.com/v1/test/getcrumb")).text
            _crumb = (time.time(), crumb, dict(c.cookies))
    mods = ("earningsTrend,earningsHistory,calendarEvents,defaultKeyStatistics,financialData,netSharePurchaseActivity,"
            "majorHoldersBreakdown,recommendationTrend,summaryDetail,assetProfile")
    r = await client.get(QS + t, params={"modules": mods, "crumb": _crumb[1]}, headers=UA, cookies=_crumb[2], timeout=20)
    r.raise_for_status()
    res = r.json()["quoteSummary"]["result"][0]
    raw = lambda d, k: (d.get(k) or {}).get("raw") if isinstance(d.get(k), dict) else d.get(k)
    out = {"sektor": res.get("assetProfile", {}).get("sector"), "endustri": res.get("assetProfile", {}).get("industry"),
           "calisan": res.get("assetProfile", {}).get("fullTimeEmployees"),
           "ozet": (res.get("assetProfile", {}).get("longBusinessSummary") or "")[:600]}
    sd, ks, fd = res.get("summaryDetail", {}), res.get("defaultKeyStatistics", {}), res.get("financialData", {})
    out.update(ileri_fk=raw(sd, "forwardPE"), peg=raw(ks, "pegRatio"), aciga_satis_yuzde=raw(ks, "shortPercentOfFloat"),
               temettu_verimi=raw(sd, "dividendYield"), beta=raw(sd, "beta"),
               hedef_fiyat_ort=raw(fd, "targetMeanPrice"), analist_sayisi=raw(fd, "numberOfAnalystOpinions"),
               insider_net_6a=raw(res.get("netSharePurchaseActivity", {}), "netPercentInsiderShares"),
               kurumsal_yuzde=raw(res.get("majorHoldersBreakdown", {}), "institutionsPercentHeld"))
    trends = {}
    for tr in res.get("earningsTrend", {}).get("trend", []):
        ep = tr.get("epsTrend", {})
        cur, d30, d90 = raw(ep, "current"), raw(ep, "30daysAgo"), raw(ep, "90daysAgo")
        rv = tr.get("epsRevisions", {})
        trends[tr["period"]] = {"eps_tahmin": cur, "buyume_tahmini": raw(tr, "growth"),
                                "revizyon_30g_yuzde": round((cur / d30 - 1) * 100, 2) if cur and d30 else None,
                                "revizyon_90g_yuzde": round((cur / d90 - 1) * 100, 2) if cur and d90 else None,
                                "yukari_30g": raw(rv, "upLast30days"), "asagi_30g": raw(rv, "downLast30days")}
    out["tahminler"] = trends
    out["surprizler"] = [{"ceyrek": (h.get("quarter") or {}).get("fmt"), "gercek": raw(h, "epsActual"),
                          "beklenti": raw(h, "epsEstimate"), "surpriz_yuzde": round(raw(h, "surprisePercent") * 100, 1)
                          if raw(h, "surprisePercent") is not None else None}
                         for h in res.get("earningsHistory", {}).get("history", [])]
    dates = [d.get("fmt") for d in res.get("calendarEvents", {}).get("earnings", {}).get("earningsDate", [])]
    out["sonraki_bilanco"] = dates[0] if dates else None
    rec = (res.get("recommendationTrend", {}).get("trend") or [{}])[0]
    out["analist_tavsiye"] = {k: rec.get(k) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}
    f.write_text(json.dumps({"zaman": time.time(), "veri": out}), encoding="utf-8")
    return out


def compute(facts: dict, price: float, y: dict | None = None) -> dict:
    """All SEC-based metrics, valuation and flags. Pure."""
    q = {k: quarters(_entries(facts, names)) for k, names in CONCEPTS.items()}
    a = {k: annual(_entries(facts, names)) for k, names in CONCEPTS.items() if k in ("ciro", "eps", "net_kar")}
    b = {k: instants(_entries(facts, names, ("USD", "shares"))) for k, names in BALANCE.items()}
    if not q["satis_maliyeti"] or q["brut_kar"]:
        pass
    elif q["ciro"]:
        q["brut_kar"] = {e: q["ciro"][e] - q["satis_maliyeti"][e] for e in q["ciro"] if e in q["satis_maliyeti"]}
    rev_q = q["ciro"]
    if len(rev_q) < 4:
        raise ValueError("SEC verisinde 4 çeyreklik ciro yok")
    end = max(rev_q)
    ends = sorted(rev_q)
    ya = _year_ago(ends, end)
    T = lambda k, e=end: ttm(q[k], e) if q.get(k) else None
    out = {"son_ceyrek": end, "fiyat": price}
    rev, rev_prev = T("ciro"), T("ciro", ya) if ya else None
    out["ciro_ttm"] = rev
    out["ciro_buyume_yuzde"] = _g(rev, rev_prev)
    growth_seq = []
    for e in ends[-4:]:
        p = _year_ago(ends, e)
        if p:
            growth_seq.append(_g(rev_q[e], rev_q[p]))
    out["ceyreklik_ciro_buyume_yuzde"] = growth_seq
    if len(growth_seq) >= 3 and None not in growth_seq[-3:]:
        s3 = growth_seq[-3:]
        out["ivme"] = "HIZLANIYOR" if s3[2] > s3[1] > s3[0] or s3[2] - s3[0] >= 5 else "YAVAŞLIYOR" if s3[2] < s3[0] - 5 else "STABİL"
    ann = a["ciro"]
    yrs = sorted(ann)
    if len(yrs) >= 4:
        out["ciro_cagr_3y_yuzde"] = round(((ann[yrs[-1]] / ann[yrs[-4]]) ** (1 / 3) - 1) * 100, 1) if ann[yrs[-4]] > 0 else None
    gp, ebit, ni = T("brut_kar"), T("faaliyet_kari"), T("net_kar")
    ebit_prev = T("faaliyet_kari", ya) if ya else None
    out.update(brut_marj_yuzde=_pct(gp, rev), faaliyet_marj_yuzde=_pct(ebit, rev),
               faaliyet_marj_gecen_yil_yuzde=_pct(ebit_prev, rev_prev), net_marj_yuzde=_pct(ni, rev), net_kar_ttm=ni)
    eps_q = q["eps"]
    eps, eps_prev = (ttm(eps_q), ttm(eps_q, _year_ago(sorted(eps_q), max(eps_q)))) if len(eps_q) >= 8 else (ttm(eps_q) if eps_q else None, None)
    out.update(eps_ttm=round(eps, 2) if eps else None, eps_buyume_yuzde=_g(eps, eps_prev))
    ocf, capex = T("isletme_nakit"), T("capex")
    fcf = ocf - (capex or 0) if ocf is not None else None
    fcf_prev = (T("isletme_nakit", ya) - (T("capex", ya) or 0)) if ya and T("isletme_nakit", ya) is not None else None
    sbc, buyback, divs = T("sbc"), T("geri_alim"), T("temettu")
    out.update(isletme_nakit_ttm=ocf, capex_ttm=capex, fcf_ttm=fcf, fcf_marj_yuzde=_pct(fcf, rev),
               fcf_buyume_yuzde=_g(fcf, fcf_prev), fcf_net_kar=round(fcf / ni, 2) if fcf is not None and ni and ni > 0 else None,
               sbc_ttm=sbc, sbc_ciro_yuzde=_pct(sbc, rev), sbc_fcf_yuzde=_pct(sbc, fcf) if fcf and fcf > 0 else None,
               geri_alim_ttm=buyback, temettu_ttm=divs)
    sh = q["hisse_seyreltilmis"]
    if sh:
        last_sh = sh[max(sh)]
        p = _year_ago(sorted(sh), max(sh))
        out["hisse_sayisi_yillik_degisim_yuzde"] = _g(last_sh, sh[p]) if p else None
    shares = b["hisse_sayisi"][max(b["hisse_sayisi"])] if b["hisse_sayisi"] else (sh[max(sh)] if sh else None)
    pick = lambda k: b[k][max(b[k])] if b[k] else 0.0
    pick_prev = lambda k: (b[k][_year_ago(sorted(b[k]), max(b[k]))] if b[k] and _year_ago(sorted(b[k]), max(b[k])) else None)
    cash = pick("nakit") + pick("kisa_yatirim")
    debt = pick("uzun_borc") + pick("kisa_borc")
    equity = pick("ozkaynak") or None
    eq_prev = pick_prev("ozkaynak")
    mcap = price * shares if shares else None
    da = T("amortisman")
    ebitda = ebit + da if ebit is not None and da is not None else None
    ev = mcap + debt - cash if mcap else None
    interest = T("faiz_gideri")
    tax, pretax = T("vergi"), T("vergi_oncesi")
    tax_rate = min(max(tax / pretax, 0.0), 0.35) if tax and pretax and pretax > 0 else 0.21
    # Invested capital without most of the cash; a cash-rich company would otherwise show a four-digit ROIC.
    invested = max(debt + (equity or 0) - cash, 0.5 * (debt + (equity or 0)))
    out.update(piyasa_degeri=round(mcap) if mcap else None, nakit=cash, borc=debt, net_nakit=cash - debt,
               ozkaynak=equity, favok_ttm=ebitda,
               faiz_karsilama=round(ebit / interest, 1) if ebit is not None and interest and interest > 0 else None,
               roe_yuzde=_pct(ni, (equity + eq_prev) / 2 if equity and eq_prev else equity) if ni is not None and equity and equity > 0 else None,
               roic_yuzde=_pct(ebit * (1 - tax_rate), invested) if ebit is not None and invested > 0 else None,
               fk=round(mcap / ni, 1) if mcap and ni and ni > 0 else None,
               fd_favok=round(ev / ebitda, 1) if ev and ebitda and ebitda > 0 else None,
               fd_satis=round(ev / rev, 2) if ev and rev else None,
               fcf_verimi_yuzde=_pct(fcf, mcap),
               hissedar_getirisi_yuzde=_pct((divs or 0) + (buyback or 0), mcap) if mcap else None,
               net_geri_alim_verimi_yuzde=_pct((buyback or 0) - (sbc or 0), mcap) if mcap else None,
               rule_of_40=round((out["ciro_buyume_yuzde"] or 0) + (out["fcf_marj_yuzde"] or 0), 1)
               if out["ciro_buyume_yuzde"] is not None and out["fcf_marj_yuzde"] is not None else None)
    if out.get("hisse_sayisi_yillik_degisim_yuzde") is not None and out["fk"]:
        pass
    inv, rec = b["stok"], b["alacak"]
    out["stok_buyume_yuzde"] = _g(pick("stok"), pick_prev("stok")) if inv else None
    out["alacak_buyume_yuzde"] = _g(pick("alacak"), pick_prev("alacak")) if rec else None
    if y:
        out["analist"] = y
        fwd = (y.get("tahminler") or {}).get("+1y") or (y.get("tahminler") or {}).get("0y") or {}
        out["ileri_fk"] = y.get("ileri_fk") or (round(price / fwd["eps_tahmin"], 1) if fwd.get("eps_tahmin") else None)
        growth = (fwd.get("buyume_tahmini") or 0) * 100
        out["peg"] = y.get("peg") or (round(out["ileri_fk"] / growth, 2) if out["ileri_fk"] and growth > 0 else None)
    out.update(flags(out))
    return out


def flags(f: dict) -> dict:
    """Warning list (thesis weakening) and the 'patlama adayı' checklist."""
    warn, good = [], []
    seq = f.get("ceyreklik_ciro_buyume_yuzde") or []
    y = f.get("analist") or {}
    est = (y.get("tahminler") or {}).get("0y") or {}
    nxt = (y.get("tahminler") or {}).get("+1y") or {}
    surprises = [s for s in (y.get("surprizler") or []) if s.get("surpriz_yuzde") is not None]
    m_now, m_prev = f.get("faaliyet_marj_yuzde"), f.get("faaliyet_marj_gecen_yil_yuzde")
    if f.get("ivme") == "YAVAŞLIYOR":
        warn.append(f"ciro büyümesi yavaşlıyor ({' → '.join(f'%{x:+.0f}' for x in seq if x is not None)})")
    if f.get("ivme") == "HIZLANIYOR":
        good.append("ciro büyümesi hızlanıyor")
    if surprises and surprises[-1]["surpriz_yuzde"] < 0:
        warn.append(f"son çeyrek EPS beklentinin altında (%{surprises[-1]['surpriz_yuzde']:+.1f})")
    if surprises and surprises[-1]["surpriz_yuzde"] > 0:
        good.append(f"son çeyrek EPS beklentiyi geçti (%{surprises[-1]['surpriz_yuzde']:+.1f})")
    rev30 = nxt.get("revizyon_30g_yuzde") if nxt.get("revizyon_30g_yuzde") is not None else est.get("revizyon_30g_yuzde")
    if rev30 is not None and rev30 <= -2:
        warn.append(f"analist EPS tahminleri düşüyor (30 günde %{rev30:+.1f})")
    if rev30 is not None and rev30 >= 2:
        good.append(f"analist EPS tahminleri yükseliyor (30 günde %{rev30:+.1f})")
    if m_now is not None and m_prev is not None:
        if m_now < m_prev - 2:
            warn.append(f"faaliyet marjı daralıyor (%{m_prev} → %{m_now})")
        elif m_now > m_prev + 1:
            good.append(f"faaliyet marjı genişliyor (%{m_prev} → %{m_now})")
    sbc = f.get("sbc_ciro_yuzde")
    if sbc is not None and sbc > 15:
        warn.append(f"hisse bazlı ücret cironun %{sbc}'i (yüksek seyreltme maliyeti)")
    dil = f.get("hisse_sayisi_yillik_degisim_yuzde")
    if dil is not None and dil > 2:
        warn.append(f"hisse sayısı yılda %{dil:+.1f} artıyor (seyreltme)")
    if dil is not None and dil <= 0:
        good.append(f"seyreltme yok (hisse sayısı %{dil:+.1f})")
    ig, rg = f.get("stok_buyume_yuzde"), f.get("ciro_buyume_yuzde")
    if ig is not None and rg is not None and ig > rg + 20:
        warn.append(f"stoklar (%{ig:+.0f}) satıştan (%{rg:+.0f}) hızlı büyüyor")
    if f.get("fcf_buyume_yuzde") is not None and f["fcf_buyume_yuzde"] < -20:
        warn.append(f"serbest nakit akışı düşüyor (%{f['fcf_buyume_yuzde']:+.0f})")
    if (f.get("fcf_ttm") or 0) > 0 and (f.get("fcf_net_kar") or 0) >= 0.8:
        good.append("güçlü serbest nakit akışı (net kârın büyük kısmı nakde dönüyor)")
    peg, fpe = f.get("peg"), f.get("ileri_fk")
    if (peg is not None and 0 < peg < 1.5) or (fpe is not None and 0 < fpe < 20):
        good.append(f"makul ileri değerleme (ileri F/K {round(fpe, 1) if fpe else '—'}, PEG {peg})")
    return {"uyarilar": warn, "olumlular": good}


def technical_flags(f: dict, tech: dict) -> None:
    rs = (tech.get("rs_spy") or {}).get("3a")
    if rs is not None and rs < -5:
        f["uyarilar"].append(f"S&P 500'e göre zayıf (3 ay {rs:+.1f} puan)")
    if rs is not None and rs > 0 and (tech.get("rs_sektor_6a") or 0) >= 0:
        f["olumlular"].append("endekse ve sektörüne göre güçlü (göreceli güç)")
    if tech.get("hizalama", "").startswith("fiyat <") or (tech.get("sma200") and tech.get("kapanis") and tech["kapanis"] < tech["sma200"]):
        f["uyarilar"].append("fiyat 200 günlük ortalamanın altında")
    if tech.get("zirveye_uzaklik_yuzde") is not None and tech["zirveye_uzaklik_yuzde"] >= -5:
        f["olumlular"].append("52 haftalık zirveye yakın (momentum)")
    st = tech.get("stage") or {}
    if st.get("taban_kirilimi"):
        f["olumlular"].append("hacimli taban kırılımı (haftalık)")
    if tech.get("volatilite_daralmasi"):
        f["olumlular"].append("volatilite daralması (geri çekilmeler küçülüyor)")


def score(f: dict, tech: dict) -> dict:
    """100-point quality score. Moat /10 and catalysts /10 are proxies (gross margin, beat streak), guidance is
    not available for free. Never a probability."""
    p: dict[str, tuple[float, float]] = {}
    gm = f.get("brut_marj_yuzde")
    p["iş kalitesi (brüt marj vekili)"] = (8 if gm and gm > 60 else 6 if gm and gm > 40 else 4 if gm and gm > 20 else 2, 10)
    g = f.get("ciro_buyume_yuzde")
    eg = f.get("eps_buyume_yuzde")
    gs = (9 if g and g > 25 else 7 if g and g > 12 else 4 if g and g > 4 else 1) + (6 if eg and eg > 20 else 4 if eg and eg > 8 else 1)
    p["büyüme (ciro+EPS)"] = (min(gs, 15), 15)
    y = f.get("analist") or {}
    nxt = (y.get("tahminler") or {}).get("+1y") or (y.get("tahminler") or {}).get("0y") or {}
    r30, r90 = nxt.get("revizyon_30g_yuzde"), nxt.get("revizyon_90g_yuzde")
    if r30 is not None or r90 is not None:
        v = max(r30 or 0, r90 or 0) if (r30 or 0) >= 0 and (r90 or 0) >= 0 else min(r30 or 0, r90 or 0)
        p["tahmin revizyonu"] = (10 if v > 5 else 8 if v > 2 else 5 if v > -2 else 2, 10)
    roic, roe = f.get("roic_yuzde"), f.get("roe_yuzde")
    p["kârlılık/ROIC"] = (10 if roic and roic > 20 else 7 if roic and roic > 12 else 4 if roic and roic > 6 else 1 if roic is not None else (5 if roe and roe > 15 else 2), 10)
    fcf, conv = f.get("fcf_ttm"), f.get("fcf_net_kar")
    p["nakit akışı"] = (10 if fcf and fcf > 0 and conv and conv >= 0.9 else 7 if fcf and fcf > 0 else 2, 10)
    nc, ic = f.get("net_nakit"), f.get("faiz_karsilama")
    bank = "Bank" in ((f.get("analist") or {}).get("endustri") or "")
    if bank:  # deposits are a bank's raw material: net cash / interest cover mean nothing here
        p["bilanço (banka: değerlendirme dışı)"] = (3, 5)
        roe = f.get("roe_yuzde")
        p["kârlılık/ROIC"] = (10 if roe and roe > 15 else 6 if roe and roe > 10 else 2, 10)
    else:
        p["bilanço"] = (5 if nc is not None and nc > 0 else 4 if ic and ic > 10 else 2 if ic and ic > 4 else 0, 5)
    fpe, peg, evs = f.get("ileri_fk"), f.get("peg"), f.get("fd_satis")
    if fpe or peg:
        v = 15 if peg and 0 < peg < 1 else 11 if (peg and peg < 1.6) or (fpe and fpe < 18) else 7 if fpe and fpe < 30 else 3
    else:
        v = 8 if evs and evs < 3 else 4 if evs and evs < 8 else 2
    p["değerleme"] = (v, 15)
    beats = [s["surpriz_yuzde"] for s in (y.get("surprizler") or []) if s.get("surpriz_yuzde") is not None]
    if beats:
        p["katalizör (bilanço sürprizi vekili)"] = (10 if all(b > 0 for b in beats[-4:]) else 6 if beats[-1] > 0 else 2, 10)
    rs = (tech.get("rs_spy") or {}).get("6a")
    st = (tech.get("stage") or {}).get("stage")
    t = (5 if rs and rs > 10 else 3 if rs and rs > 0 else 1) + {2: 5, 1: 3, 3: 1, 4: 0}.get(st, 2)
    p["teknik/göreceli güç"] = (t, 10)
    dil, nb = f.get("hisse_sayisi_yillik_degisim_yuzde"), f.get("net_geri_alim_verimi_yuzde")
    p["hissedar uyumu"] = (5 if (dil is not None and dil <= 0) and (nb or 0) > 0 else 3 if dil is not None and dil <= 1 else 1, 5)
    got, mx = sum(a for a, _ in p.values()), sum(b for _, b in p.values())
    total = round(got / mx * 100)
    val = p["değerleme"][0]
    n_good, n_warn = len(f["olumlular"]), len(f["uyarilar"])
    if n_warn >= 4:
        status = "TEZ ZAYIFLIYOR"
    elif total >= 75 and val >= 11 and st in (1, 2):
        status = "BİRİKTİRME BÖLGESİ"
    elif total >= 75 and val < 8:
        status = "KALİTELİ AMA DEĞERLEME GERGİN"
    elif n_good >= 7 and st == 2:
        status = "MOMENTUM KIRILIM İZLEME"
    elif f.get("ivme") == "HIZLANIYOR":
        status = "TEMEL MOMENTUM İYİLEŞİYOR"
    elif total >= 60:
        status = "YÜKSEK KALİTE İZLEME LİSTESİ" if val >= 8 else "DAHA İYİ DEĞERLEME BEKLE"
    else:
        status = "TEMEL TEYİT BEKLE"
    return {"skor": total, "durum": status, "parcalar": {k: f"{a:.0f}/{b:.0f}" for k, (a, b) in p.items()},
            "patlama_listesi": f"{n_good}/11 olumlu", "not": f"kalite skoru, yükselme olasılığı DEĞİL ({mx:.0f} puan üzerinden"
            + ("; iş kalitesi ve katalizör vekil ölçü, yönetim beklentisi (guidance) ücretsiz veride yok)")}


async def report(t: str) -> dict:
    t = us.ticker(t)
    async with httpx.AsyncClient() as client:
        facts = await sec_facts(client, t)
        price = await us.last_price(client, t)
        try:
            y = await yahoo_summary(client, t)
        except Exception as e:
            log.warning("Yahoo summary %s failed: %s", t, e)
            y = None
        d = market.add_indicators(await us.fetch(client, t, "1d"))
        w = market.add_indicators(await us.fetch(client, t, "1wk", bulk=True))
        mth = market.add_indicators(await us.fetch(client, t, "1mo", bulk=True))
        spy = await us.fetch(client, "SPY", "1d", bulk=True)
        qqq = await us.fetch(client, "QQQ", "1d", bulk=True)
        etf = us.SECTOR_ETF.get((y or {}).get("sektor"))
        if (y or {}).get("endustri") and "Semiconductor" in y["endustri"]:
            etf = "SOXX"
        sector = await us.fetch(client, etf, "1d", bulk=True) if etf else None
    f = compute(facts, price, y)
    tech = us.technicals(d, w, mth, spy, qqq, sector)
    tech["sektor_etf"] = etf
    technical_flags(f, tech)
    f["teknik"] = tech
    f["puan"] = score(f, tech)
    f["hisse"] = t
    if y and y.get("sonraki_bilanco"):
        days = (date.fromisoformat(y["sonraki_bilanco"]) - us.now_ny().date()).days
        f["bilancoya_gun"] = days
        if 0 <= days <= config.US_EARNINGS_BLOCK_DAYS:
            f["uyarilar"].append(f"bilanço {days} gün sonra: boşluk (gap) riski, yeni giriş bekle")
    f["kaynak"] = "SEC EDGAR (10-K/10-Q) + Yahoo (analist tahminleri, sürprizler) + " + ("Tiingo" if config.TIINGO_API_KEY else "Yahoo") + " fiyat"
    return f


def _m(x) -> str:
    if x is None:
        return "—"
    a = abs(x)
    return f"{x / 1e12:,.2f} T$" if a >= 1e12 else f"{x / 1e9:,.1f} mr$" if a >= 1e9 else f"{x / 1e6:,.0f} mn$"


def _v(x, s: str = "") -> str:
    return "—" if x is None else f"{x:g}{s}"


def text(f: dict) -> str:
    y = f.get("analist") or {}
    t = f["teknik"]
    s = f["puan"]
    nxt = (y.get("tahminler") or {}).get("+1y") or {}
    cur = (y.get("tahminler") or {}).get("0y") or {}
    sur = [s_ for s_ in y.get("surprizler", []) if s_.get("surpriz_yuzde") is not None]
    lines = [f"🇺🇸 {f['hisse']} — {y.get('sektor') or ''} / {y.get('endustri') or ''} · son çeyrek {f['son_ceyrek']}",
             f"Fiyat {f['fiyat']:g} $ · piyasa değeri {_m(f.get('piyasa_degeri'))}",
             f"Büyüme: ciro TTM {_m(f.get('ciro_ttm'))} (%{_v(f.get('ciro_buyume_yuzde'))}, 3y CAGR %{_v(f.get('ciro_cagr_3y_yuzde'))}) · "
             f"çeyrekler {' → '.join(f'%{x:+.0f}' for x in f.get('ceyreklik_ciro_buyume_yuzde', []) if x is not None)} → {f.get('ivme', '?')}",
             f"EPS TTM {_v(f.get('eps_ttm'))} (%{_v(f.get('eps_buyume_yuzde'))}) · tahmin bu yıl {_v(cur.get('eps_tahmin'))}, gelecek yıl {_v(nxt.get('eps_tahmin'))} "
             f"(revizyon 30g %{_v(nxt.get('revizyon_30g_yuzde'))}, 90g %{_v(nxt.get('revizyon_90g_yuzde'))}; ↑{_v(nxt.get('yukari_30g'))} ↓{_v(nxt.get('asagi_30g'))})",
             "Sürprizler: " + (" · ".join(f"{x['ceyrek']} %{x['surpriz_yuzde']:+.1f}" for x in sur[-4:]) or "—")
             + (f" · sonraki bilanço {y.get('sonraki_bilanco')} ({f.get('bilancoya_gun')} gün)" if y.get("sonraki_bilanco") else ""),
             f"Marjlar: brüt %{_v(f.get('brut_marj_yuzde'))} · faaliyet %{_v(f.get('faaliyet_marj_yuzde'))} (geçen yıl %{_v(f.get('faaliyet_marj_gecen_yil_yuzde'))}) · "
             f"net %{_v(f.get('net_marj_yuzde'))} · FCF %{_v(f.get('fcf_marj_yuzde'))} · Rule of 40 {_v(f.get('rule_of_40'))}",
             f"Nakit: FCF {_m(f.get('fcf_ttm'))} (FCF/net kâr {_v(f.get('fcf_net_kar'))}) · SBC cironun %{_v(f.get('sbc_ciro_yuzde'))} · "
             f"hisse sayısı %{_v(f.get('hisse_sayisi_yillik_degisim_yuzde'))} · geri alım {_m(f.get('geri_alim_ttm'))} · hissedar getirisi %{_v(f.get('hissedar_getirisi_yuzde'))}",
             f"Getiri: ROE %{_v(f.get('roe_yuzde'))} · ROIC %{_v(f.get('roic_yuzde'))} · net nakit {_m(f.get('net_nakit'))} · faiz karşılama {_v(f.get('faiz_karsilama'))}",
             f"Değerleme: F/K {_v(f.get('fk'))} · ileri F/K {_v(round(f['ileri_fk'], 1) if f.get('ileri_fk') else None)} · PEG {_v(f.get('peg'))} · "
             f"FD/FAVÖK {_v(f.get('fd_favok'))} · FD/Satış {_v(f.get('fd_satis'))} · FCF verimi %{_v(f.get('fcf_verimi_yuzde'))}",
             f"Piyasa: açığa satış %{_v(round(y['aciga_satis_yuzde'] * 100, 1) if y.get('aciga_satis_yuzde') is not None else None)} · "
             f"insider 6a net %{_v(round(y['insider_net_6a'] * 100, 2) if y.get('insider_net_6a') is not None else None)} · "
             f"kurumsal %{_v(round(y['kurumsal_yuzde'] * 100) if y.get('kurumsal_yuzde') is not None else None)} · "
             f"analist hedefi {_v(y.get('hedef_fiyat_ort'))} $ ({_v(y.get('analist_sayisi'))} analist)",
             f"Teknik: {', '.join(f'{k} {v}' for k, v in t['trend'].items())} · {t['hizalama']} · zirveye %{t['zirveye_uzaklik_yuzde']} · "
             f"RS SPY 3a/6a/12a {t['rs_spy'].get('3a')}/{t['rs_spy'].get('6a')}/{t['rs_spy'].get('12a')} · sektör ({t.get('sektor_etf') or '—'}) 6a {t.get('rs_sektor_6a')}",
             f"Stage: {(t.get('stage') or {}).get('aciklama', '—')}" + (" · volatilite daralması" if t.get("volatilite_daralmasi") else ""),
             "✅ " + " · ".join(f["olumlular"]) if f["olumlular"] else "✅ —",
             "⚠️ " + " · ".join(f["uyarilar"]) if f["uyarilar"] else "⚠️ uyarı yok",
             "", f"📊 SKOR {s['skor']}/100 → {s['durum']} · patlama listesi {s['patlama_listesi']}",
             " · ".join(f"{k} {v}" for k, v in s["parcalar"].items()), s["not"]]
    return "\n".join(lines)

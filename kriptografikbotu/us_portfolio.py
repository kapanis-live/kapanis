"""The US holdings as one book: what they have in common. "Seven stocks" is not diversification if five of them rise
and fall on the same story.

From one year of daily closes: weights, sector and theme exposure, how tightly the holdings move together, beta to
SPY and QQQ, and four what-if scenarios (SPY -10 %, QQQ -10 %, 10-year yield +0.50 points, VIX to 30).
Scenarios are single-factor estimates from the past year's daily co-movement: a ruler, not a forecast. A stock's
sensitivity changes over time and the factors move together in a real sell-off, so the scenarios do not add up.

Themes are fixed lists below (a stock can sit in several); sectors come from Yahoo's company profile.
Decision support only: nothing here suggests a trade.
"""
import asyncio
import logging
from datetime import datetime

import httpx
import numpy as np
import pandas as pd

import alerts_store
import positions
import us
import us_fund

log = logging.getLogger(__name__)

WINDOW = 252
MIN_DAYS = 60          # a holding with fewer common sessions than this gets no beta / correlation
THEMES = {
    "Mega teknoloji": set("AAPL MSFT GOOGL GOOG AMZN META NVDA TSLA".split()),
    "Yarı iletken": set("NVDA AMD AVGO TSM MU ASML LRCX KLAC AMAT INTC QCOM TXN ARM MRVL".split()),
    "Yapay zekâ (çip, bulut, yazılım)": set("NVDA AMD AVGO TSM MU ASML MSFT GOOGL GOOG AMZN META ORCL PLTR ANET CRWD PANW NOW".split()),
    "Yapay zekâ enerjisi / altyapı": set("CEG VST GEV ETN NEE DLR EQIX PWR".split()),
    "Banka / finans": set("JPM BAC WFC C GS MS BLK SCHW AXP V MA".split()),
    "Savunmacı (temel tüketim, sağlık)": set("COST WMT PG KO PEP MCD LLY ABBV JNJ MRK UNH PFE".split()),
}
SCENARIOS = (("SPY", "S&P 500 %10 düşerse"), ("QQQ", "Nasdaq-100 %10 düşerse"), ("^TNX", "10 yıllık faiz 0,50 puan artarsa"),
             ("^VIX", "VIX 30'a çıkarsa"))


def _beta(y: pd.Series, x: pd.Series) -> float | None:
    j = pd.concat([y, x], axis=1).dropna()
    if len(j) < MIN_DAYS or float(j.iloc[:, 1].var()) == 0:
        return None
    return float(j.iloc[:, 0].cov(j.iloc[:, 1]) / j.iloc[:, 1].var())


def analyze(values: dict[str, float], closes: dict[str, pd.Series], sectors: dict[str, str | None],
            factors: dict[str, pd.Series]) -> dict:
    """values: ticker -> USD value. closes: ticker -> daily closes (indexed by day). factors: SPY, QQQ, ^TNX, ^VIX
    closes. Pure."""
    total = sum(values.values())
    w = {t: v / total for t, v in values.items()}
    rets = {t: closes[t].tail(WINDOW + 1).pct_change().dropna() for t in values if t in closes and len(closes[t]) > MIN_DAYS}
    by_sector: dict[str, float] = {}
    for t, x in w.items():
        by_sector[sectors.get(t) or "bilinmiyor"] = by_sector.get(sectors.get(t) or "bilinmiyor", 0.0) + x
    themes = {name: {"agirlik_yuzde": round(sum(w[t] for t in w if t in members) * 100, 1), "hisseler": sorted(t for t in w if t in members)}
              for name, members in THEMES.items()}
    themes = {k: v for k, v in themes.items() if v["hisseler"]}
    pairs = []
    names = sorted(rets)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            j = pd.concat([rets[a], rets[b]], axis=1).dropna()
            if len(j) >= MIN_DAYS:
                pairs.append((float(j.iloc[:, 0].corr(j.iloc[:, 1])), a, b))
    fr = {"SPY": factors["SPY"].pct_change(), "QQQ": factors["QQQ"].pct_change(),
          "^TNX": factors["^TNX"].diff(),                       # change of the yield in percentage points
          "^VIX": np.log(factors["^VIX"]).diff()}
    vix_now, tnx_now = float(factors["^VIX"].iloc[-1]), float(factors["^TNX"].iloc[-1])
    shock = {"SPY": -0.10, "QQQ": -0.10, "^TNX": 0.50, "^VIX": float(np.log(30 / vix_now)) if vix_now < 30 else 0.0}
    betas = {t: {k: _beta(rets[t], fr[k].tail(WINDOW)) for k in fr} for t in rets}
    covered = sum(w[t] for t in rets)
    scen = []
    for key, label in SCENARIOS:
        have = [t for t in rets if betas[t][key] is not None]
        move = sum(w[t] * betas[t][key] * shock[key] for t in have)
        scen.append({"senaryo": label, "portfoy_yuzde": round(move * 100, 1), "tutar_usd": round(move * total, 2),
                     "en_cok_etkilenen": sorted(((round(betas[t][key] * shock[key] * 100, 1), t) for t in have))[:3]})
    beta_p = {k: (round(sum(w[t] * betas[t][k] for t in rets if betas[t][k] is not None), 2) if rets else None) for k in ("SPY", "QQQ")}
    top = max(by_sector.items(), key=lambda kv: kv[1])
    notes = []
    if max(w.values()) > 0.30:
        t = max(w, key=w.get)
        notes.append(f"{t} portföyün %{w[t] * 100:.0f}'i: tek hisse riski yüksek.")
    if top[1] > 0.50 and top[0] != "bilinmiyor":
        notes.append(f"{top[0]} sektörü portföyün %{top[1] * 100:.0f}'i.")
    for name, th in themes.items():
        if th["agirlik_yuzde"] >= 50 and len(th["hisseler"]) > 1:
            notes.append(f"'{name}' temasında %{th['agirlik_yuzde']:g} ({', '.join(th['hisseler'])}): bu hisseler aynı habere birlikte tepki verir.")
    if pairs and float(np.mean([p[0] for p in pairs])) > 0.6:
        notes.append("Hisseler birbirine çok bağlı hareket ediyor: çeşitlendirme göründüğünden az.")
    return {"toplam_usd": round(total, 2), "agirlik_yuzde": {t: round(x * 100, 1) for t, x in sorted(w.items(), key=lambda kv: -kv[1])},
            "sektor_yuzde": {k: round(v * 100, 1) for k, v in sorted(by_sector.items(), key=lambda kv: -kv[1])},
            "tema": themes,
            "korelasyon": {"ortalama": round(float(np.mean([p[0] for p in pairs])), 2) if pairs else None,
                           "en_bagli": [{"cift": f"{a}–{b}", "korelasyon": round(c, 2)} for c, a, b in sorted(pairs, reverse=True)[:3]],
                           "en_bagimsiz": [{"cift": f"{a}–{b}", "korelasyon": round(c, 2)} for c, a, b in sorted(pairs)[:2]]},
            "beta": beta_p, "senaryolar": scen, "dikkat": notes,
            "kapsam_yuzde": round(covered * 100, 1), "vix": round(vix_now, 1), "tnx": round(tnx_now, 2)}


async def report(holdings: dict[str, float] | None = None) -> dict | None:
    """holdings: ticker -> quantity; default: the open US positions. None when there is nothing to analyse."""
    if holdings is None:
        holdings = {}
        for p in positions.open_positions():
            if p.get("piyasa") == "ABD":
                holdings[us.ticker(p["symbol"])] = holdings.get(us.ticker(p["symbol"]), 0.0) + float(p["adet"])
    if not holdings:
        return None
    slots = asyncio.Semaphore(4)
    async with httpx.AsyncClient() as client:
        async def frame(sym):
            async with slots:
                d = await us.fetch(client, sym, "1d", bulk=True)
            return pd.Series(d.close.values, index=pd.to_datetime(d.open_time, unit="ms").dt.normalize())

        async def sector(sym):
            try:
                async with slots:
                    return (await us_fund.yahoo_summary(client, sym)).get("sektor")
            except Exception as e:
                log.info("Sector for %s failed: %s", sym, str(e)[:80])
                return None
        syms = list(holdings)
        series = await asyncio.gather(*[frame(s) for s in syms + ["SPY", "QQQ", "^TNX", "^VIX"]], return_exceptions=True)
        secs = await asyncio.gather(*[sector(s) for s in syms])
    closes = {s: x for s, x in zip(syms, series) if isinstance(x, pd.Series)}
    factors = {s: x for s, x in zip(["SPY", "QQQ", "^TNX", "^VIX"], series[len(syms):]) if isinstance(x, pd.Series)}
    if len(factors) < 4:
        raise RuntimeError("endeks / faiz / VIX verisi alınamadı")
    values = {s: holdings[s] * float(closes[s].iloc[-1]) for s in syms if s in closes}
    if not values:
        raise RuntimeError("hisselerin fiyatı alınamadı")
    out = analyze(values, closes, dict(zip(syms, secs)), factors)
    out["fiyat_alinamayan"] = [s for s in syms if s not in closes]
    out["kaynaklar"] = [{"veri": "günlük kapanışlar (1 yıl), SPY, QQQ, 10Y faiz, VIX", "kaynak": "Yahoo Finance",
                         "tarih": f"son gün {factors['SPY'].index[-1].date()}"},
                        {"veri": "sektör", "kaynak": "Yahoo Finance şirket profili", "tarih": "6 saatlik önbellek"},
                        {"veri": "temalar", "kaynak": "koddaki sabit listeler (us_portfolio.THEMES)", "tarih": "elle güncellenir"}]
    out["uretildi"] = alerts_store.now_tr().isoformat(timespec="seconds")
    return out


def text(r: dict, code: str = "tr") -> str:
    if code == "en":
        return text_en(r)
    lines = [f"🇺🇸 ABD PORTFÖYÜ — {r['toplam_usd']:,.0f} USD · {len(r['agirlik_yuzde'])} hisse",
             "Ağırlık: " + " · ".join(f"{t} %{x:g}" for t, x in r["agirlik_yuzde"].items()),
             "Sektör: " + " · ".join(f"{k} %{v:g}" for k, v in r["sektor_yuzde"].items()), "Tema (bir hisse birden çok temada olabilir):"]
    lines += [f"· {k}: %{v['agirlik_yuzde']:g} ({', '.join(v['hisseler'])})" for k, v in r["tema"].items()] or ["· tanımlı temalarda hisse yok"]
    c = r["korelasyon"]
    if c["ortalama"] is not None:
        lines.append(f"Birlikte hareket (1 yıl, günlük): ortalama korelasyon {c['ortalama']:g} · en bağlı "
                     + ", ".join(f"{x['cift']} {x['korelasyon']:g}" for x in c["en_bagli"])
                     + (" · en bağımsız " + ", ".join(f"{x['cift']} {x['korelasyon']:g}" for x in c["en_bagimsiz"]) if c["en_bagimsiz"] else ""))
    lines.append(f"Beta: SPY'ye {r['beta']['SPY']} · QQQ'ya {r['beta']['QQQ']} (1 = endeks kadar oynar)")
    lines += ["", f"Senaryolar (tek etkenli, geçmiş 1 yılın birlikte hareketinden; VIX şimdi {r['vix']:g}, 10Y %{r['tnx']:g}):"]
    for s in r["senaryolar"]:
        worst = ", ".join(f"{t} %{m:+g}" for m, t in s["en_cok_etkilenen"])
        lines.append(f"· {s['senaryo']}: portföy %{s['portfoy_yuzde']:+g} ({s['tutar_usd']:+,.0f} USD)" + (f" · en çok: {worst}" if worst else ""))
    lines += ["", *(f"⚠️ {n}" for n in r["dikkat"])] if r["dikkat"] else []
    if r.get("fiyat_alinamayan"):
        lines.append("Fiyatı alınamayan: " + ", ".join(r["fiyat_alinamayan"]))
    if r["kapsam_yuzde"] < 99.9:
        lines.append(f"Beta ve senaryolar portföyün %{r['kapsam_yuzde']:g}'ini kapsıyor (kalanların geçmişi 60 günden kısa).")
    lines += ["", "Kaynaklar:", *(f"· {x['veri']}: {x['kaynak']} — {x['tarih']}" for x in r["kaynaklar"]),
              "Cetvel, tahmin değil: gerçek bir satışta etkenler birlikte hareket eder ve duyarlılıklar değişir. Öneri içermez."]
    return "\n".join(lines)


NAMES_EN = {"Mega teknoloji": "Mega tech", "Yarı iletken": "Semiconductors", "Yapay zekâ (çip, bulut, yazılım)": "AI (chips, cloud, software)",
            "Yapay zekâ enerjisi / altyapı": "AI energy / infrastructure", "Banka / finans": "Banks / finance",
            "Savunmacı (temel tüketim, sağlık)": "Defensive (staples, health care)", "S&P 500 %10 düşerse": "If the S&P 500 falls 10%",
            "Nasdaq-100 %10 düşerse": "If the Nasdaq-100 falls 10%", "10 yıllık faiz 0,50 puan artarsa": "If the 10-year yield rises 0.50 points",
            "VIX 30'a çıkarsa": "If the VIX rises to 30"}


def text_en(r: dict) -> str:
    """The same report in English. Theme and scenario names are translated; concentration notes stay as written."""
    N = lambda k: NAMES_EN.get(k, k)
    lines = [f"🇺🇸 US PORTFOLIO — {r['toplam_usd']:,.0f} USD · {len(r['agirlik_yuzde'])} stocks",
             "Weights: " + " · ".join(f"{t} {x:g}%" for t, x in r["agirlik_yuzde"].items()),
             "Sectors: " + " · ".join(f"{k} {v:g}%" for k, v in r["sektor_yuzde"].items()), "Themes (a stock can be in more than one):"]
    lines += [f"· {N(k)}: {v['agirlik_yuzde']:g}% ({', '.join(v['hisseler'])})" for k, v in r["tema"].items()] or ["· no stock in the defined themes"]
    c = r["korelasyon"]
    if c["ortalama"] is not None:
        lines.append(f"Co-movement (1 year, daily): average correlation {c['ortalama']:g} · most linked "
                     + ", ".join(f"{x['cift']} {x['korelasyon']:g}" for x in c["en_bagli"])
                     + (" · most independent " + ", ".join(f"{x['cift']} {x['korelasyon']:g}" for x in c["en_bagimsiz"]) if c["en_bagimsiz"] else ""))
    lines.append(f"Beta: {r['beta']['SPY']} to SPY · {r['beta']['QQQ']} to QQQ (1 = moves as much as the index)")
    lines += ["", f"Scenarios (single factor, from the co-movement of the last year; VIX now {r['vix']:g}, 10Y {r['tnx']:g}%):"]
    for s in r["senaryolar"]:
        worst = ", ".join(f"{t} {m:+g}%" for m, t in s["en_cok_etkilenen"])
        lines.append(f"· {N(s['senaryo'])}: portfolio {s['portfoy_yuzde']:+g}% ({s['tutar_usd']:+,.0f} USD)" + (f" · most affected: {worst}" if worst else ""))
    lines += ["", *(f"⚠️ {n}" for n in r["dikkat"])] if r["dikkat"] else []
    if r.get("fiyat_alinamayan"):
        lines.append("No price for: " + ", ".join(r["fiyat_alinamayan"]))
    if r["kapsam_yuzde"] < 99.9:
        lines.append(f"Beta and scenarios cover {r['kapsam_yuzde']:g}% of the portfolio (the rest have less than 60 days of history).")
    lines += ["", "Sources:", *(f"· {x['veri']}: {x['kaynak']} — {x['tarih']}" for x in r["kaynaklar"]),
              "A ruler, not a forecast: in a real sell-off the factors move together and the sensitivities change. It contains no suggestion."]
    return "\n".join(lines)

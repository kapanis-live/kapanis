"""Risk budget: "how much should I buy?" answered with arithmetic, not prediction. Plus the market regime label.

Size = (portfolio value × risk %) × volatility factor × correlation factor × concentration factor ÷ distance to stop.
- volatility factor: the asset's ATR% now vs its own 1-year median ATR%; more nervous than usual → smaller (0.5–1.0)
- correlation factor: highest 90-day correlation with a position you already hold; 0.5 → 1.0, 1.0 → 0.5
- concentration factor: 0.5 if the asset is already more than 20 % of the portfolio
- cap: one position never exceeds 25 % of the portfolio; BIST in whole lots
Every factor is shown with its reason. Nothing here predicts price.
"""
import statistics

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import chart_data
import insights

MAX_POSITION_PCT = 25.0
HEAVY_PCT = 20.0


class SizeBody(BaseModel):
    piyasa: str
    kod: str
    stop: float | None = None
    risk_yuzde: float | None = None   # default: the portfolio's risk target (1 %)


def atr_pcts(candles: list[dict]) -> list[float]:
    out, prev, atr = [], None, None
    for c in candles:
        tr = c["h"] - c["l"] if prev is None else max(c["h"] - c["l"], abs(c["h"] - prev), abs(c["l"] - prev))
        atr = tr if atr is None else atr + (tr - atr) / 14
        out.append(atr / c["c"])
        prev = c["c"]
    return out


def regime(candles: list[dict], sma50: list, sma200: list) -> str:
    """Same labels as research/regime.py (without ADX): PANIK, YUKSEK_VOL, TREND_UP, TREND_DOWN, YATAY."""
    if len(candles) < 120 or not sma200 or sma200[-1] is None:
        return "?"
    c = candles[-1]["c"]
    ap = atr_pcts(candles)
    rank = sum(1 for x in ap[-100:] if x <= ap[-1]) / len(ap[-100:])
    r20 = c / candles[-21]["c"] - 1
    if r20 <= -0.15 or (rank >= 0.9 and c < (sma50[-1] or c)):
        return "PANIK"
    if rank >= 0.8:
        return "YUKSEK_VOL"
    if c > sma200[-1] and (sma50[-1] or 0) > sma200[-1]:
        return "TREND_UP"
    if c < sma200[-1] and (sma50[-1] or 0) < sma200[-1]:
        return "TREND_DOWN"
    return "YATAY"


REGIME_TEXT = {"TREND_UP": "yükseliş trendi", "TREND_DOWN": "düşüş trendi", "YATAY": "yatay / kararsız",
               "YUKSEK_VOL": "oynaklık yüksek", "PANIK": "panik / sert düşüş", "?": "veri yetersiz"}


def build_router(get_db, current_user) -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.get("/market/regime")
    async def market_regime(_: dict = Depends(current_user)):
        out = []
        for kod, mkt, name in (("BTC", "KRIPTO", "Kripto (BTC)"), ("XU100", "BIST", "BIST 100"), ("SPY", "ABD", "ABD (S&P 500)")):
            try:
                d = await chart_data.chart(kod, "1d", mkt)
                closed = insights.daily_closes(d, mkt)
                n = len(closed)
                lab = regime(d["candles"][:n], (d.get("sma50") or [])[:n], (d.get("sma200") or [])[:n])
            except Exception:
                lab = "?"
            out.append({"piyasa": name, "rejim": lab, "aciklama": REGIME_TEXT[lab]})
        return {"rejimler": out, "not": "Bilgi amaçlı piyasa durumu (kapanmış günlük mumlardan). Strateji seçmek için kullanılmaz: "
                                        "rejime göre strateji seçmenin işe yaradığı henüz kanıtlanmadı."}

    @r.post("/risk/size")
    async def size(body: SizeBody, user: dict = Depends(current_user)):
        mkt = body.piyasa.upper()
        kod = (body.kod or "").strip().upper().removesuffix(".IS").removesuffix("/USDT")
        if mkt not in ("KRIPTO", "BIST", "ABD") or not kod:
            raise HTTPException(status_code=400, detail="Piyasa ve kod gerekli.")
        pf = await get_db().portfolios.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
        risk_pct = body.risk_yuzde if body.risk_yuzde is not None else float(pf.get("risk_target_pct") or 1.0)
        if not 0.1 <= risk_pct <= 5:
            raise HTTPException(status_code=400, detail="Risk yüzdesi 0,1 ile 5 arasında olmalı.")
        try:
            doc = await chart_data.chart(kod, "1d", mkt)
        except Exception:
            raise HTTPException(status_code=404, detail=f"{kod} {mkt} piyasasında bulunamadı.")
        closes = insights.daily_closes(doc, mkt)
        candles = doc["candles"][:len(closes)]
        if len(candles) < 60:
            raise HTTPException(status_code=400, detail="Yeterli günlük geçmiş yok.")
        price = candles[-1]["c"]
        ap = atr_pcts(candles)
        atr = ap[-1] * price
        stop = body.stop if body.stop is not None else round(price - 2 * atr, 8)
        if not 0 < stop < price:
            raise HTTPException(status_code=400, detail="Stop son kapanışın altında ve sıfırdan büyük olmalı.")
        usdtry = await insights_last(doc_symbol="USDTRY=X")
        to_tl = 1.0 if mkt == "BIST" else (usdtry or 0)
        if not to_tl:
            raise HTTPException(status_code=502, detail="USD/TRY alınamadı, biraz sonra tekrar dene.")

        # portfolio value in TL (open positions at last close + cash)
        value, weights, series = 0.0, {}, {}
        for p in pf.get("positions", []):
            if p.get("durum") != "acik":
                continue
            try:
                d = await chart_data.chart(p["kod"], "1d", p["piyasa"])
            except Exception:
                continue
            cl = insights.daily_closes(d, p["piyasa"])
            if not cl:
                continue
            v = p["adet"] * cl[-1][1] * (1.0 if p.get("para") == "TL" else (usdtry or 0))
            value += v
            weights[(p["piyasa"], p["kod"])] = weights.get((p["piyasa"], p["kod"]), 0) + v
            series[(p["piyasa"], p["kod"])] = cl
        cash = pf.get("cash_balance") or {}
        value += float(cash.get("TL") or 0) + float(cash.get("USD") or 0) * (usdtry or 0)
        if value <= 0:
            raise HTTPException(status_code=400, detail="Portföy değeri sıfır: önce nakit ya da pozisyon ekle (Portföyüm).")

        lines, factor = [], 1.0
        base = value * risk_pct / 100
        lines.append(f"Normal risk bütçesi: portföy ≈ ₺{value:,.0f} × %{risk_pct:g} = ₺{base:,.0f}")
        med = statistics.median(ap[-365:])
        f_vol = max(0.5, min(1.0, med / ap[-1])) if ap[-1] > 0 else 1.0
        factor *= f_vol
        lines.append(f"Oynaklık ×{f_vol:.2f}: günlük ATR %{ap[-1] * 100:.1f}, son 1 yıl ortancası %{med * 100:.1f}"
                     + (" (her zamankinden hareketli)" if f_vol < 1 else ""))
        corr_best, corr_with = None, None
        for key, cl in series.items():
            if key == (mkt, kod):
                continue
            c = insights.correlation(closes, cl)
            if c is not None and (corr_best is None or c > corr_best):
                corr_best, corr_with = c, key[1]
        f_corr = 1.0 if corr_best is None or corr_best <= 0.5 else max(0.5, 1 - (corr_best - 0.5))
        factor *= f_corr
        lines.append(f"Korelasyon ×{f_corr:.2f}: " + (f"{corr_with} ile 90 günlük korelasyon {corr_best:.2f}" if corr_best is not None
                                                     else "elindekilerle ölçülecek ortak geçmiş yok"))
        held = weights.get((mkt, kod), 0) / value * 100
        f_conc = 0.5 if held > HEAVY_PCT else 1.0
        factor *= f_conc
        lines.append(f"Yoğunlaşma ×{f_conc:.2f}: {kod} şu an portföyün %{held:.0f}'i")
        budget = base * factor
        per_unit_tl = (price - stop) * to_tl
        qty = budget / per_unit_tl
        cap_qty = (value * MAX_POSITION_PCT / 100 - weights.get((mkt, kod), 0)) / (price * to_tl)
        capped = qty > cap_qty
        qty = max(0.0, min(qty, cap_qty))
        if mkt == "BIST":
            qty = float(int(qty))
        lines.append(f"Son risk bütçesi: ₺{budget:,.0f} · stop mesafesi {price - stop:.6g} ({(1 - stop / price) * 100:.1f}%)")
        if capped:
            lines.append(f"Tek pozisyon portföyün %{MAX_POSITION_PCT:g}'ini geçmesin diye sınırlandı.")
        return {"kod": kod, "piyasa": mkt, "fiyat": price, "stop": stop, "stop_kaynagi": "senin" if body.stop is not None else "2 × ATR",
                "adet": round(qty, 6), "tutar": round(qty * price, 2), "para": "TL" if mkt == "BIST" else "USD",
                "risk_tl": round(qty * per_unit_tl, 2), "carpan": round(factor, 2), "satirlar": lines,
                "not": "Bu bir risk hesabıdır, alım önerisi değildir: stop kırılırsa kaybın yaklaşık risk tutarı kadar olur "
                       "(boşluklu açılışta daha fazla olabilir)."}

    async def insights_last(doc_symbol: str):
        try:
            cl = insights.daily_closes(await chart_data.chart(doc_symbol, "1d", "ABD"), "ABD")
            return cl[-1][1] if cl else None
        except Exception:
            return None

    return r

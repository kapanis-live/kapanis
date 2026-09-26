"""Price-structure engine, computed in code from CLOSED candles (the AI only explains the results).

Order of thought (the "decision engine"):
regime -> higher-timeframe structure -> key levels -> liquidity -> volume -> momentum -> derivatives
-> setup/trigger -> invalidation -> risk/reward -> confluence score.

- Swings: pivot highs/lows (left/right bars). Labels HH/HL/LH/LL against the previous swing of the same kind.
- Structure: HH+HL = uptrend, LH+LL = downtrend, otherwise mixed. BOS = close beyond the last swing in the
  trend's direction. CHoCH = close beyond the last HL (uptrend) / LH (downtrend): an EARLY warning, not a
  confirmed reversal.
- Regime: strong/normal up or down trend, range, compression (Bollinger width in its bottom 20%),
  expansion (ATR well above its average).
- Liquidity: previous day/week high-low, equal highs/lows (stop pools), sweeps (wick through a level,
  close back on the other side = failed breakout / reclaim).
- Volume profile (POC/VAH/VAL) from candles, volume spread evenly over each candle's range.
- Momentum: RSI side of 50, MACD(12,26,9) histogram, regular and hidden RSI divergence.
- Confluence score /100 = setup QUALITY, never a win probability.
Spot only: a bearish reading means "don't buy / reduce", never "short".
"""
import numpy as np
import pandas as pd


def _nan(x) -> bool:
    return x is None or x != x


def _r(x, digits: int = 6):
    return None if _nan(x) else float(f"{float(x):.{digits}g}")


def add_extra(df: pd.DataFrame) -> pd.DataFrame:
    """MACD(12,26,9) and Bollinger(20,2) width; added next to market.add_indicators columns."""
    c = df["close"]
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_sinyal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_sinyal"]
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    df["bb_ust"], df["bb_alt"] = mid + 2 * sd, mid - 2 * sd
    df["bb_genislik"] = (df["bb_ust"] - df["bb_alt"]) / mid
    return df


def swings(df: pd.DataFrame, left: int = 3, right: int = 3) -> list[dict]:
    """Confirmed pivot highs/lows, oldest first, labeled HH/LH (highs) and HL/LL (lows)."""
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    out, last_h, last_l = [], None, None
    for i in range(left, len(df) - right):
        if h[i] == h[i - left:i + right + 1].max():
            label = None if last_h is None else ("HH" if h[i] > last_h else "LH")
            out.append({"i": i, "tur": "tepe", "fiyat": float(h[i]), "etiket": label})
            last_h = h[i]
        if l[i] == l[i - left:i + right + 1].min():
            label = None if last_l is None else ("HL" if l[i] > last_l else "LL")
            out.append({"i": i, "tur": "dip", "fiyat": float(l[i]), "etiket": label})
            last_l = l[i]
    return out


def structure(df: pd.DataFrame, left: int = 3, right: int = 3) -> dict:
    """Trend from the last swing labels, plus BOS / CHoCH on the last close."""
    sw = swings(df, left, right)
    highs = [s for s in sw if s["tur"] == "tepe"]
    lows = [s for s in sw if s["tur"] == "dip"]
    if len(highs) < 2 or len(lows) < 2:
        return {"trend": "belirsiz", "not": "yeterli swing yok"}
    hl, ll = highs[-1]["etiket"], lows[-1]["etiket"]
    trend = "yükseliş" if (hl, ll) == ("HH", "HL") else "düşüş" if (hl, ll) == ("LH", "LL") else "karışık/yatay"
    close = float(df["close"].iloc[-1])
    last_high, last_low = highs[-1]["fiyat"], lows[-1]["fiyat"]
    out = {"trend": trend, "son_tepe": _r(last_high), "son_tepe_etiket": hl, "son_dip": _r(last_low),
           "son_dip_etiket": ll, "son_swingler": [f"{s['etiket'] or '-'} {_r(s['fiyat'])}" for s in sw[-6:]],
           "bos": None, "choch": None}
    if trend == "yükseliş":
        if close > last_high:
            out["bos"] = f"yükseliş BOS: kapanış {_r(close)} son tepe {_r(last_high)} üstünde"
        if close < last_low:
            out["choch"] = f"düşüş CHoCH ihtimali: kapanış son HL {_r(last_low)} altında (erken uyarı, teyit yok)"
    elif trend == "düşüş":
        if close < last_low:
            out["bos"] = f"düşüş BOS: kapanış {_r(close)} son dip {_r(last_low)} altında"
        if close > last_high:
            out["choch"] = f"yükseliş CHoCH ihtimali: kapanış son LH {_r(last_high)} üstünde (erken uyarı, teyit yok)"
    else:
        if close > last_high:
            out["bos"] = f"yatay yapıdan yukarı kırılım: kapanış son tepe {_r(last_high)} üstünde"
        elif close < last_low:
            out["bos"] = f"yatay yapıdan aşağı kırılım: kapanış son dip {_r(last_low)} altında"
    return out


def regime(df: pd.DataFrame, st: dict | None = None) -> dict:
    """Market regime label with its reasons."""
    st = st or structure(df)
    last = df.iloc[-1]
    close = float(last["close"])
    reasons = []
    width = df["bb_genislik"].dropna().tail(120) if "bb_genislik" in df else pd.Series(dtype=float)
    squeeze = len(width) >= 40 and width.iloc[-1] <= width.quantile(0.2)
    atr = df["atr14"].dropna()
    expansion = len(atr) >= 50 and atr.iloc[-1] >= 1.5 * atr.tail(50).mean()
    aligned_up = all(not _nan(last.get(k)) for k in ("sma20", "sma50", "sma200")) and close > last["sma20"] > last["sma50"] > last["sma200"]
    aligned_dn = all(not _nan(last.get(k)) for k in ("sma20", "sma50", "sma200")) and close < last["sma20"] < last["sma50"] < last["sma200"]
    if st["trend"] == "yükseliş":
        label = "güçlü yükseliş trendi" if aligned_up else "yükseliş trendi"
        reasons.append("HH + HL")
    elif st["trend"] == "düşüş":
        label = "güçlü düşüş trendi" if aligned_dn else "düşüş trendi"
        reasons.append("LH + LL")
    else:
        label = "yatay (range)"
        reasons.append("swingler karışık")
    if aligned_up:
        reasons.append("fiyat > SMA20 > SMA50 > SMA200")
    if aligned_dn:
        reasons.append("fiyat < SMA20 < SMA50 < SMA200")
    if squeeze:
        label = "sıkışma" if label == "yatay (range)" else f"{label} + sıkışma"
        reasons.append("Bollinger genişliği son 120 mumun en dar %20'sinde")
    if expansion:
        label = f"{label} + volatilite genişlemesi"
        reasons.append("ATR ortalamasının 1.5 katı")
    if st.get("choch"):
        label = f"{label} (geçiş ihtimali)"
        reasons.append("CHoCH uyarısı")
    return {"rejim": label, "nedenler": reasons}


def _levels(daily: pd.DataFrame | None, weekly: pd.DataFrame | None) -> dict:
    out = {}
    if daily is not None and len(daily) >= 2:
        out["onceki_gun_tepe"], out["onceki_gun_dip"] = float(daily["high"].iloc[-1]), float(daily["low"].iloc[-1])
    if weekly is not None and len(weekly) >= 2:
        out["onceki_hafta_tepe"], out["onceki_hafta_dip"] = float(weekly["high"].iloc[-1]), float(weekly["low"].iloc[-1])
    return out


def liquidity(df: pd.DataFrame, daily: pd.DataFrame | None, weekly: pd.DataFrame | None, lookback: int = 3) -> dict:
    """Obvious stop pools and whether the last candles swept one of them."""
    atr = float(df["atr14"].iloc[-1]) if not _nan(df["atr14"].iloc[-1]) else float(df["close"].iloc[-1]) * 0.01
    levels = _levels(daily, weekly)
    sw = swings(df)
    highs = [s["fiyat"] for s in sw if s["tur"] == "tepe"][-8:]
    lows = [s["fiyat"] for s in sw if s["tur"] == "dip"][-8:]
    eq_highs = sorted({round(a, 8) for i, a in enumerate(highs) for b in highs[i + 1:] if abs(a - b) <= 0.15 * atr})
    eq_lows = sorted({round(a, 8) for i, a in enumerate(lows) for b in lows[i + 1:] if abs(a - b) <= 0.15 * atr})
    named = dict(levels)
    if eq_highs:
        named["esit_tepeler"] = max(eq_highs)
    if eq_lows:
        named["esit_dipler"] = min(eq_lows)
    sweeps = []
    for _, row in df.tail(lookback).iterrows():
        for name, lvl in named.items():
            if row["high"] > lvl and row["close"] < lvl:
                sweeps.append(f"{name} {_r(lvl)} üstten süpürüldü, altında kapandı (başarısız kırılım / satış likiditesi)")
            if row["low"] < lvl and row["close"] > lvl:
                sweeps.append(f"{name} {_r(lvl)} alttan süpürüldü, üstünde kapandı (reclaim / alış lehine)")
    close = float(df["close"].iloc[-1])
    return {"seviyeler": {k: _r(v) for k, v in named.items()},
            "ustteki_likidite": _r(min((v for v in named.values() if v > close), default=None) or np.nan),
            "alttaki_likidite": _r(max((v for v in named.values() if v < close), default=None) or np.nan),
            "supurme": list(dict.fromkeys(sweeps))[:4]}


def volume_profile(df: pd.DataFrame, bins: int = 40) -> dict | None:
    """POC / value area (70%) over the given candles; each candle's volume spread over its high-low range."""
    if len(df) < 20:
        return None
    lo, hi = float(df["low"].min()), float(df["high"].max())
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    vol = np.zeros(bins)
    for h, l, v in zip(df["high"].to_numpy(), df["low"].to_numpy(), df["volume"].to_numpy()):
        a, b = np.searchsorted(edges, l, side="right") - 1, np.searchsorted(edges, h, side="left")
        a, b = max(a, 0), min(max(b, a + 1), bins)
        vol[a:b] += v / (b - a)
    poc = int(vol.argmax())
    lo_i = hi_i = poc
    total, acc = vol.sum(), vol[poc]
    while acc < 0.7 * total and (lo_i > 0 or hi_i < bins - 1):
        down = vol[lo_i - 1] if lo_i > 0 else -1
        up = vol[hi_i + 1] if hi_i < bins - 1 else -1
        if up >= down:
            hi_i += 1
            acc += vol[hi_i]
        else:
            lo_i -= 1
            acc += vol[lo_i]
    mid = (edges[:-1] + edges[1:]) / 2
    close = float(df["close"].iloc[-1])
    vah, val = float(edges[hi_i + 1]), float(edges[lo_i])
    where = "değer alanının üstünde" if close > vah else "değer alanının altında" if close < val else "değer alanı içinde"
    return {"poc": _r(mid[poc]), "vah": _r(vah), "val": _r(val), "fiyat_konumu": where, "mum": len(df)}


def divergence(df: pd.DataFrame) -> str | None:
    """Regular / hidden RSI divergence on the last two swing highs or lows."""
    sw = swings(df)
    rsi = df["rsi14"].to_numpy()
    highs = [s for s in sw if s["tur"] == "tepe"][-2:]
    lows = [s for s in sw if s["tur"] == "dip"][-2:]
    if len(highs) == 2 and not np.isnan(rsi[highs[0]["i"]]) and not np.isnan(rsi[highs[1]["i"]]):
        a, b = highs
        if b["fiyat"] > a["fiyat"] and rsi[b["i"]] < rsi[a["i"]] - 2:
            return "negatif uyumsuzluk: fiyat HH, RSI düşük tepe — momentum zayıflıyor (dönüş garantisi değil)"
        if b["fiyat"] < a["fiyat"] and rsi[b["i"]] > rsi[a["i"]] + 2:
            return "gizli negatif uyumsuzluk: fiyat LH, RSI yüksek tepe — düşüş devam ihtimali"
    if len(lows) == 2 and not np.isnan(rsi[lows[0]["i"]]) and not np.isnan(rsi[lows[1]["i"]]):
        a, b = lows
        if b["fiyat"] < a["fiyat"] and rsi[b["i"]] > rsi[a["i"]] + 2:
            return "pozitif uyumsuzluk: fiyat LL, RSI yüksek dip — satış momentumu zayıflıyor"
        if b["fiyat"] > a["fiyat"] and rsi[b["i"]] < rsi[a["i"]] - 2:
            return "gizli pozitif uyumsuzluk: fiyat HL, RSI düşük dip — yükseliş devam ihtimali"
    return None


def momentum(df: pd.DataFrame) -> dict:
    last, prev = df.iloc[-1], df.iloc[-2]
    rsi = _r(last["rsi14"], 4)
    hist, hist_prev = last.get("macd_hist"), prev.get("macd_hist")
    macd = None
    if not _nan(hist) and not _nan(hist_prev):
        macd = ("MACD pozitif, histogram artıyor" if hist > 0 and hist > hist_prev else
                "MACD pozitif, histogram azalıyor" if hist > 0 else
                "MACD negatif, histogram toparlanıyor" if hist > hist_prev else "MACD negatif, histogram düşüyor")
    return {"rsi": rsi, "rsi_taraf": None if rsi is None else ("50 üstü (alıcı ağırlıklı)" if rsi > 50 else "50 altı"),
            "macd": macd, "uyumsuzluk": divergence(df)}


def confluence(*, htf: list[str], level_ok: bool | None, sweep_bull: bool, sweep_bear: bool, volume_ratio: float | None,
               mom: dict, deriv: dict | None, trigger: bool | None, rr: float | None) -> dict:
    """Setup quality /100 (HTF 20, level 15, liquidity 15, volume 10, momentum 10, derivatives 10, trigger 10, R/R 10).
    Parts that can't be judged (no plan -> no trigger/R/R) are left out and the score is scaled to the rest."""
    parts: dict[str, tuple[float, float]] = {}
    up = sum(t == "yükseliş" for t in htf)
    down = sum(t == "düşüş" for t in htf)
    parts["HTF yapı"] = (20 * (up / len(htf)) if htf and not down else 20 * max(up - down, 0) / max(len(htf), 1), 20)
    if level_ok is not None:
        parts["seviye"] = (15 if level_ok else 4, 15)
    parts["likidite"] = (15 if sweep_bull else 2 if sweep_bear else 8, 15)
    if volume_ratio is not None:
        parts["hacim"] = (10 if volume_ratio >= 1.5 else 7 if volume_ratio >= 1.0 else 3, 10)
    m = 0
    if mom.get("rsi") is not None and mom["rsi"] > 50:
        m += 4
    if mom.get("macd") and mom["macd"].startswith("MACD pozitif"):
        m += 3 if "artıyor" in mom["macd"] else 2
    u = mom.get("uyumsuzluk") or ""
    if u.startswith(("pozitif", "gizli pozitif")):
        m += 3
    if u.startswith(("negatif", "gizli negatif")):
        m -= 3
    parts["momentum"] = (max(min(m, 10), 0), 10)
    if deriv and "hata" not in deriv:
        d = 5
        hint = deriv.get("yorum_ipucu", "")
        if "çok yüksek" in hint:
            d = 2
        oi = deriv.get("acik_pozisyon_24s_degisim_yuzde")
        if oi is not None and oi > 0:
            d += 3
        tb = deriv.get("alim_satim_orani_24s")
        if tb is not None and tb > 1.0:
            d += 2
        parts["türev"] = (min(d, 10), 10)
    if trigger is not None:
        parts["tetik"] = (10 if trigger else 0, 10)
    if rr is not None:
        parts["R/R"] = (10 if rr >= 2 else 7 if rr >= 1.5 else 4 if rr >= 1 else 0, 10)
    got, maxi = sum(p[0] for p in parts.values()), sum(p[1] for p in parts.values())
    score = round(got / maxi * 100) if maxi else None
    return {"skor": score, "parcalar": {k: f"{v[0]:.0f}/{v[1]:.0f}" for k, v in parts.items()},
            "not": "setup kalite skoru, kazanma olasılığı DEĞİL" + ("" if maxi == 100 else f" (değerlendirilebilen {maxi:.0f} puan üzerinden ölçeklendi)")}


def stage(weekly: pd.DataFrame) -> dict | None:
    """Weinstein stage from weekly closes and the 30-week average (for medium/long-term BIST)."""
    if len(weekly) < 40:
        return None
    c = weekly["close"]
    ma = c.rolling(30).mean()
    slope = (ma.iloc[-1] / ma.iloc[-6] - 1) * 100
    close = float(c.iloc[-1])
    above = close > ma.iloc[-1]
    rng = weekly.tail(26)
    width = (rng["high"].max() / rng["low"].min() - 1) * 100
    if above and slope > 1:
        s, txt = 2, "Stage 2 — yükseliş (30h ortalama üstünde ve yükseliyor)"
    elif not above and slope < -1:
        s, txt = 4, "Stage 4 — düşüş (30h ortalama altında ve düşüyor): biriktirme için erken"
    elif above:
        s, txt = 3 if c.tail(52).max() > close * 1.15 else 1, "yatay; tepe sonrası ise Stage 3 (dağıtım), dip sonrası Stage 1 (taban)"
    else:
        s, txt = 1, "Stage 1 — taban oluşumu ihtimali (30h ortalama yatay)"
    base_high = float(rng["high"].iloc[:-1].max())
    breakout = close > base_high and weekly["volume"].iloc[-1] > weekly["volume"].tail(20).mean() * 1.3
    return {"stage": s, "aciklama": txt, "sma30h": _r(ma.iloc[-1]), "sma30h_egim_yuzde": round(float(slope), 2),
            "taban_26h_genislik_yuzde": round(float(width), 1),
            "taban_kirilimi": "26 haftalık tabanın üstünde hacimli haftalık kapanış" if breakout else None}


def analyze(frames: dict[str, pd.DataFrame], deriv: dict | None = None, plan: dict | None = None,
            entry_tf: str = "15m", htf_list: tuple[str, ...] = ("1d", "4h")) -> dict:
    """Full reading for one asset. frames: timeframe -> df with market.add_indicators columns."""
    for df in frames.values():
        if len(df) and "macd" not in df:
            add_extra(df)
    tf_struct = {tf: structure(df) for tf, df in frames.items() if len(df) >= 30}
    entry = frames[entry_tf]
    daily = frames.get("1d")
    weekly = frames.get("1w") if "1w" in frames else frames.get("1wk")
    reg = regime(frames[htf_list[-1]], tf_struct.get(htf_list[-1], {"trend": "belirsiz"})) if htf_list[-1] in frames else None
    liq = liquidity(entry, daily.iloc[:-1] if daily is not None and len(daily) > 2 else daily,
                    weekly.iloc[:-1] if weekly is not None and len(weekly) > 2 else weekly)
    vp_src = frames.get("1h", entry)
    vp = volume_profile(vp_src.tail(168))
    mom = momentum(entry)
    last = entry.iloc[-1]
    vol_ratio = float(last["volume"] / last["vol_avg20"]) if not _nan(last["vol_avg20"]) and last["vol_avg20"] else None
    trigger = rr = level_ok = None
    if plan and plan.get("tetik") is not None:
        trigger = float(last["close"]) > plan["tetik"]
        level_ok = trigger
        if plan.get("iptal") is not None and plan.get("hedef") is not None and last["close"] > plan["iptal"]:
            rr = (plan["hedef"] - last["close"]) / (last["close"] - plan["iptal"])
    sweep_bull = any("alttan süpürüldü" in s for s in liq["supurme"])
    sweep_bear = any("üstten süpürüldü" in s for s in liq["supurme"])
    conf = confluence(htf=[tf_struct[t]["trend"] for t in htf_list if t in tf_struct], level_ok=level_ok,
                      sweep_bull=sweep_bull, sweep_bear=sweep_bear, volume_ratio=vol_ratio, mom=mom,
                      deriv=deriv, trigger=trigger, rr=rr)
    bb = entry["bb_genislik"].dropna().tail(120)
    return {
        "rejim": reg,
        "yapi": {tf: {k: v for k, v in s.items() if k != "son_swingler"} | {"swingler": s.get("son_swingler")}
                 for tf, s in tf_struct.items()},
        "likidite": liq,
        "hacim_profili_7g_1s": vp,
        "momentum": mom,
        "bollinger": None if len(bb) < 40 else {"genislik": _r(bb.iloc[-1], 4),
                                                  "yuzdelik": round(float((bb <= bb.iloc[-1]).mean() * 100)),
                                                  "sikisma": bool(bb.iloc[-1] <= bb.quantile(0.2))},
        "konfluens": conf,
    }

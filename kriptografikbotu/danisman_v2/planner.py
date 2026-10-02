"""Order planner: the stop-limit BUY plan, computed from a MarketSnapshot. Deterministic; no model writes a price here.

    build_buy_plan(snapshot dict) -> {"status", "result", "setup", "plan", "withheld_plan", "blocks", "waits", ...}

Setups: BREAKOUT (a resting stop-limit one tick above a resistance, or a confirmed close just above it), RETEST (the
price came back to the broken level and a closed 15m candle held it) and RECLAIM (a failed breakout taken back; watch
only, it collects paper results first). None of them is a tested edge: the 15m breakout rule lost about 0.21R a trade
in the history test and the 2023-2025 intraday lab found no setup that held in both periods. Every plan carries
evidence_status RESEARCH_UNPROVEN. Nothing is ever sent to an exchange.
"""
from __future__ import annotations

import math

from . import config as cfg
from .snapshot import DOWNS, floor_tick, next_tick

EVIDENCE_STATUS = "RESEARCH_UNPROVEN"
GROUPS = ("READY_TO_WATCH", "WAIT_FOR_BREAKOUT", "WAIT_FOR_RETEST", "RECLAIM_WATCH", "PULLBACK_SETUP", "BLOCKED_SETUP",
          "NO_SETUP", "AVOID")
STATUS_TR = {"BUY_SETUP": "ALIM KURULUMU", "WAIT_FOR_BREAKOUT": "BEKLE — kırılım bekleniyor",
             "WAIT_FOR_RETEST": "BEKLE — geri test bekleniyor", "RECLAIM_WATCH": "İZLE — geri alış (araştırma)",
             "PULLBACK_SETUP": "İZLE — düzeltme kurulumu", "BLOCKED_SETUP": "ENGELLİ — kurulum var, filtre izin vermiyor",
             "NO_SETUP": "KURULUM YOK", "AVOID": "UZAK DUR"}
BLOCK_TR = {
    "DATA_STALE": "Veri eski: son kapanan 15m mum beklenenden geride",
    "DATA_ERROR": "Borsa emir kuralları (tick, minimum tutar) ya da göstergeler alınamadı",
    "INSUFFICIENT_HISTORY": "4h geçmişi yetersiz: trend filtresi çalışmıyor",
    "TREND_1H_DOWN": "1h ana yön aşağı: yükseliş kurulumu aranmaz",
    "4H_STRONG_DOWN": "4h güçlü düşüşte",
    "HTF_STRONG_DOWNTREND": "Günlük trend güçlü düşüşte",
    "BTC_MARKET_RISK": "BTC 1h ve 4h güçlü düşüşte: altcoin alımı engelli",
    "MACRO_EVENT_BLOCK": "Yüksek etkili makro veri çok yakın",
    "NO_VALID_STOP": "Geçerli bir teknik stop yok",
    "PORTFOLIO_CONCENTRATION_HARD_LIMIT": "Birlikte hareket eden varlıkların payı yapılandırılmış politika sınırında",
    "MAX_EXPOSURE_REACHED": "Portföydeki pay yapılandırılmış politika sınırına ulaştı",
}
WAIT_TR = {
    "NO_CHASE": "Fiyat tetikten uzaklaştı: kovalanmaz",
    "FAILED_BREAKOUT_NOT_RECLAIMED": "Sahte kırılım: seviye geri alınmadı",
    "RETEST_NOT_REACHED": "Fiyat geri test bölgesine dönmedi",
    "RETEST_NOT_CONFIRMED": "Geri test bölgesinde kapanış teyidi yok",
    "RECLAIM_NOT_HELD": "Geri alış henüz tutunmadı",
    "RECLAIM_RESEARCH_ONLY": "Geri alış kurulumu izleme aşamasında: paper sonuç topluyor",
    "PULLBACK_RESEARCH_ONLY": "Düzeltme kurulumu V2'de üretim kurulumu değil",
    "NO_LEVEL": "Yakında planlanabilir bir direnç yok",
}


def _item(code: str, table: dict, detail: str = "") -> dict:
    return {"code": code, "text": table[code] + (f" ({detail})" if detail else "")}


def portfolio_warnings(p: dict) -> list[dict]:
    """Exposure warnings: by share of the portfolio, never by a fixed number of coins."""
    out = []

    def near(value, limit):
        return value is not None and limit > 0 and value >= cfg.EXPOSURE_WARN_SHARE * limit

    if near(p.get("portfolio_alt_exposure"), cfg.MAX_ALT_EXPOSURE_PCT):
        out.append({"code": "HIGH_ALT_EXPOSURE", "text": f"Altcoin payı %{p['portfolio_alt_exposure']:g} "
                                                         f"(sınır %{cfg.MAX_ALT_EXPOSURE_PCT:g})"})
    if near(p.get("portfolio_meme_exposure"), cfg.MAX_MEME_EXPOSURE_PCT):
        out.append({"code": "HIGH_MEME_EXPOSURE", "text": f"Memecoin payı %{p['portfolio_meme_exposure']:g} "
                                                          f"(sınır %{cfg.MAX_MEME_EXPOSURE_PCT:g})"})
    if len(p.get("correlation_group") or []) >= 2:
        out.append({"code": "SAME_THEME_CONCENTRATION",
                    "text": "Portföydeki " + ", ".join(p["correlation_group"]) + " ile birlikte hareket ediyor"})
    if (p.get("positions") or 0) >= cfg.MANY_POSITIONS_WARN:
        out.append({"code": "TOO_MANY_POSITIONS", "text": f"{p['positions']} açık kripto pozisyonu var"})
    return out


def technical_stop(entry: float, candidates: list[tuple[float | None, str]], atr15: float, atr1h: float, tick: float) -> dict | None:
    """The stop from the nearest structural level under the entry that leaves the trade room to breathe.

    stop = level - STRUCTURAL_STOP_ATR1H_BUFFER x ATR(1h); the level itself is the technical invalidation. A level
    whose stop would sit closer than MIN_STOP_ATR15 x ATR(15m) is skipped for the next one down. When every level is
    that close the lowest one is used and the plan is marked STOP_TOO_TIGHT. None when there is no level at all:
    there is never a fixed-percentage stop."""
    pad, room = cfg.STRUCTURAL_STOP_ATR1H_BUFFER * atr1h, cfg.MIN_STOP_ATR15 * atr15
    seen, usable = set(), []
    for lvl, name in sorted(((x, n) for x, n in candidates if x is not None and x == x and 0 < x < entry), key=lambda t: -t[0]):
        if round(lvl, 12) not in seen:
            seen.add(round(lvl, 12))
            usable.append((lvl, name))
    if not usable:
        return None
    chosen = next(((lvl, name) for lvl, name in usable if entry - (lvl - pad) >= room), None)
    lvl, name = chosen or usable[-1]
    stop = floor_tick(lvl - pad, tick)
    out = {"technical_stop": stop, "technical_invalidation": floor_tick(lvl, tick),
           "source": f"{name} − {cfg.STRUCTURAL_STOP_ATR1H_BUFFER:g} ATR(1h)",
           "distance_pct": round((entry - stop) / entry * 100, 2), "distance_atr15": round((entry - stop) / atr15, 2),
           "too_tight": chosen is None, "skipped": None}
    if usable[0] != (lvl, name):
        near = usable[0]
        out["skipped"] = {"level": near[0], "name": near[1], "distance_atr15": round((entry - (near[0] - pad)) / atr15, 2)}
    return out


def order_prices(level_high: float, atr15: float, tick: float) -> tuple[float, float, float]:
    """(trigger, limit, execution band). Trigger: the first tick above the level, no bigger buffer. Limit: the trigger
    plus max(EXECUTION_MIN_TICKS ticks, EXECUTION_ATR15_BUFFER x ATR15), at most MAX_EXECUTION_BUFFER_PCT of the trigger."""
    trigger = next_tick(level_high, tick)
    band = min(max(cfg.EXECUTION_MIN_TICKS * tick, cfg.EXECUTION_ATR15_BUFFER * atr15), trigger * cfg.MAX_EXECUTION_BUFFER_PCT / 100)
    limit = max(floor_tick(trigger + band, tick), next_tick(trigger, tick))
    return trigger, limit, round(limit - trigger, 12)


def take_profit(entry: float, risk: float, resistances: list[dict], atr1h: float, above: float) -> dict:
    """The first confirmed resistance above the entry that is not inside normal movement; FALLBACK_TP_R x risk when
    there is none (a research fallback, said so). Never a fixed percentage."""
    for z in resistances:
        if z["low"] > above and z["low"] - entry >= cfg.MIN_TP_ATR1H * atr1h:
            return {"price": z["low"], "source": "STRUCTURAL_RESISTANCE", "zone": [z["low"], z["high"]],
                    "rr": round((z["low"] - entry) / risk, 2), "research_fallback": False}
    return {"price": entry + cfg.FALLBACK_TP_R * risk, "source": "FALLBACK_2_5R", "zone": None, "rr": cfg.FALLBACK_TP_R,
            "research_fallback": True}


def position_size(s: dict, entry: float, stop: float) -> dict:
    """Notional from the risk budget, then cut down by every limit. {"position": {...} | None, "note": code | None,
    "block": code | None}. The smallest of: risk budget / stop distance, the new-position cap, the room left under
    each exposure limit, the cash."""
    p, ex = s["portfolio"], s["execution"]
    pv = p.get("portfolio_value")
    if s["quote_asset"] == "BTC":
        return {"position": None, "note": "QUOTE_BTC_NO_SIZING", "block": None}
    if not pv:
        return {"position": None, "note": "PORTFOLIO_REQUIRED_FOR_SIZING", "block": None}
    risk_budget = pv * cfg.RISK_PER_TRADE_PCT / 100

    def held(key):
        return (p.get(key) or 0.0) / 100 * pv

    caps = {"RISK_BUDGET": risk_budget / ((entry - stop) / entry), "MAX_NEW_POSITION": pv * cfg.MAX_NEW_POSITION_PCT / 100}
    if p["asset_class"] == "ALT":
        caps["MAX_ALT_EXPOSURE"] = pv * cfg.MAX_ALT_EXPOSURE_PCT / 100 - held("portfolio_alt_exposure")
    if p["asset_class"] == "MEME":
        caps["MAX_MEME_EXPOSURE"] = pv * cfg.MAX_MEME_EXPOSURE_PCT / 100 - held("portfolio_meme_exposure")
    if p.get("total_known"):
        caps["MAX_TOTAL_CRYPTO_EXPOSURE"] = pv * cfg.MAX_TOTAL_CRYPTO_EXPOSURE_PCT / 100 - held("portfolio_crypto_exposure")
    if p.get("correlation_group"):
        caps["MAX_CORRELATED_EXPOSURE"] = pv * cfg.MAX_CORRELATED_EXPOSURE_PCT / 100 - held("portfolio_correlated_exposure")
    if p.get("available_cash") is not None:
        caps["AVAILABLE_CASH"] = p["available_cash"]
    by = min(caps, key=caps.get)
    notional = caps[by]
    base = {"portfolio_value": pv, "risk_budget": round(risk_budget, 2), "risk_based_notional": round(caps["RISK_BUDGET"], 2),
            "max_new_position_notional": round(caps["MAX_NEW_POSITION"], 2), "limited_by": by, "quote": s["quote_asset"],
            # an exposure limit is the admin's configured policy; the risk budget and the cash are not
            "limit_basis": "CONFIGURED_POLICY" if f"{by}_PCT" in cfg.POLICY_LIMITS else None}
    if notional <= 0:
        if by == "AVAILABLE_CASH":
            return {"position": None, "note": "NO_AVAILABLE_CASH", "block": None, "limits": base}
        code = "PORTFOLIO_CONCENTRATION_HARD_LIMIT" if by == "MAX_CORRELATED_EXPOSURE" else "MAX_EXPOSURE_REACHED"
        return {"position": None, "note": by, "block": code, "limits": base}
    step = ex.get("step_size") or 0
    qty = notional / entry
    if step:
        qty = math.floor(qty / step + 1e-9) * step
    notional = qty * entry
    if notional < (ex.get("min_notional") or 0) or qty < (ex.get("min_qty") or 0) or qty <= 0:
        return {"position": None, "note": "BELOW_EXCHANGE_MINIMUM", "block": None, "limits": base}
    return {"position": {**base, "suggested_notional": round(notional, 2), "quantity": round(qty, 10),
                         "loss_at_stop": round(qty * (entry - stop), 2),
                         "portfolio_share_pct": round(notional / pv * 100, 2),
                         "risk_of_portfolio_pct": round(qty * (entry - stop) / pv * 100, 3)}, "note": None, "block": None}


def _plan(s: dict, setup: str, kind: str, level_zone: list[float], trigger_from: float,
          candidates: list) -> tuple[dict | None, list[dict], list[dict]]:
    """One order plan: (plan | None, blocks, warnings)."""
    ex, st, f = s["execution"], s["structure"], s["timeframes"]
    tick = ex["tick_size"]
    atr15, atr1h = f["15m"]["indicators"]["atr14"], f["1h"]["indicators"]["atr14"]
    trigger, limit, band = order_prices(trigger_from, atr15, tick)
    blocks, warnings = [], []
    stop = technical_stop(trigger, candidates, atr15, atr1h, tick)
    if stop is None:
        return None, [_item("NO_VALID_STOP", BLOCK_TR, "girişin altında teknik seviye yok")], warnings
    if stop["distance_pct"] > cfg.MAX_STOP_DISTANCE_PCT:
        return None, [_item("NO_VALID_STOP", BLOCK_TR, f"en yakın yapısal stop %{stop['distance_pct']:g} uzakta")], warnings
    if stop["too_tight"]:
        warnings.append({"code": "STOP_TOO_TIGHT", "text": f"Stop girişe {stop['distance_atr15']:g} ATR(15m): en az "
                                                           f"{cfg.MIN_STOP_ATR15:g} tercih edilir; altında başka teknik seviye yok"})
    elif stop["skipped"]:
        k = stop["skipped"]
        warnings.append({"code": "STOP_TOO_TIGHT", "text": f"En yakın seviye ({k['name']}) girişe {k['distance_atr15']:g} "
                                                           "ATR(15m): normal oynaklığın içinde; stop bir sonraki seviyeye alındı"})
    risk = trigger - stop["technical_stop"]
    tp = take_profit(trigger, risk, st["resistances"], atr1h, limit)
    size = position_size(s, trigger, stop["technical_stop"])
    if size["block"]:
        blocks.append(_item(size["block"], BLOCK_TR, size["note"]))
    price = s["current_price"]
    plan = {"type": "STOP_LIMIT", "setup": setup, "kind": kind, "evidence_status": EVIDENCE_STATUS,
            "resistance": level_zone, "trigger": trigger, "limit": limit, "execution_band": band,
            "technical_stop": stop["technical_stop"], "technical_invalidation": stop["technical_invalidation"],
            "stop_source": stop["source"], "stop_distance_pct": stop["distance_pct"],
            "stop_distance_atr15": stop["distance_atr15"], "risk_per_unit": round(risk, 12),
            "initial_risk_pct": round(risk / trigger * 100, 2),
            "take_profit_reference": tp["price"], "take_profit_source": tp["source"], "take_profit_zone": tp["zone"],
            "rr_to_take_profit": tp["rr"], "take_profit_is_research_fallback": tp["research_fallback"],
            "trailing_reference_3atr": cfg.TRAIL_REFERENCE_ATR1H * atr1h,
            "position": size["position"], "position_note": size["note"],
            "already_above_trigger": bool(price >= trigger), "above_limit": bool(price > limit),
            "distance_to_trigger_atr15": round((price - trigger) / atr15, 2), "order_sent": False}
    if plan["above_limit"]:
        warnings.append({"code": "ABOVE_LIMIT", "text": "Fiyat limitin üstünde: emir ancak fiyat limite gerilerse dolar; "
                                                        "limitin üstünden alınmaz"})
    return plan, blocks, warnings


def _retest_wait(s: dict, rt: dict, candidates: list) -> dict | None:
    """What a retest entry would look like before it exists: the zone, the level a 15m candle has to close above and
    the stop under the zone. Not an order: nothing is bought until the confirming candle has closed. Kept so that the
    panel can show the wait and the paper log can follow it."""
    ex, f = s["execution"], s["timeframes"]
    atr15, atr1h = f["15m"]["indicators"]["atr14"], f["1h"]["indicators"]["atr14"]
    top = rt["broken_resistance"]
    stop = technical_stop(top, candidates, atr15, atr1h, ex["tick_size"])
    if stop is None:
        return None
    return {"type": "RETEST_WAIT", "setup": "RETEST", "kind": "RETEST_PENDING", "evidence_status": EVIDENCE_STATUS,
            "broken_resistance": top, "retest_zone": [rt["zone_low"], rt["zone_high"]], "confirmation_price": top,
            "confirmation_rule": f"bir 15m mum bölgeye girip {top:g} üstünde kapanmalı; tetik o mumun tepesi + 1 tick",
            "technical_stop": stop["technical_stop"], "technical_invalidation": stop["technical_invalidation"],
            "stop_source": stop["source"], "stop_distance_pct": stop["distance_pct"],
            "stop_distance_atr15": stop["distance_atr15"], "order_sent": False}


def build_buy_plan(s: dict) -> dict:
    """The deterministic verdict for a NEW position. s: MarketSnapshot.data()."""
    st, f, p, btc, macro = s["structure"], s["timeframes"], s["portfolio"], s["btc"], s.get("macro") or {}
    blocks, waits, warnings, evidence = [], [], portfolio_warnings(p), []
    i15, i1 = f["15m"]["indicators"], f["1h"]["indicators"]
    usable = bool(s["execution"] and s["execution"].get("tick_size") and i15 and i1 and i15.get("atr14") and i1.get("atr14"))
    if s.get("stale"):
        blocks.append(_item("DATA_STALE", BLOCK_TR, f"{s['data_age_seconds'] // 60} dk"))
    if not usable:
        blocks.append(_item("DATA_ERROR", BLOCK_TR))
    if "4h" in s["insufficient_history"]:
        blocks.append(_item("INSUFFICIENT_HISTORY", BLOCK_TR))
    h1, h4, d1 = st["trend_1h"], st["trend_4h"], st["trend_1d"]
    if h1 in DOWNS:
        blocks.append(_item("TREND_1H_DOWN", BLOCK_TR))
    if h4 == "STRONG_DOWN":
        blocks.append(_item("4H_STRONG_DOWN", BLOCK_TR))
    if d1 == "STRONG_DOWN":
        blocks.append(_item("HTF_STRONG_DOWNTREND", BLOCK_TR))
    if btc.get("applies") and btc["regime"] == "RISK_OFF":
        blocks.append(_item("BTC_MARKET_RISK", BLOCK_TR))
    elif btc.get("applies") and btc["regime"] == "CAUTION":
        warnings.append({"code": "BTC_CAUTION", "text": f"BTC 1h {btc['trend_1h']}, 4h {btc['trend_4h']}: temkinli"})
    if macro.get("block_new_entry"):
        blocks.append(_item("MACRO_EVENT_BLOCK", BLOCK_TR, macro.get("next_high_impact_event") or ""))
    elif macro.get("caution"):
        warnings.append({"code": "HIGH_IMPACT_EVENT_WINDOW", "text": "Yüksek etkili makro veri yakın: "
                                                                     + (macro.get("next_high_impact_event") or "")})
    if h4 in DOWNS and h4 != "STRONG_DOWN":
        warnings.append({"code": "HTF_DOWNTREND", "text": "4h düşüş trendinde: 15m/1h kırılımı güvenilir sayılmaz"})
    for tf in ("15m", "1h", "4h", "1d"):
        evidence.append(f"{tf} trend: {f[tf]['trend']}")

    status, setup, plan, retest_view, next_review, pending = "NO_SETUP", "NONE", None, None, None, None
    if usable:
        tick = s["execution"]["tick_size"]
        atr15, atr1h = i15["atr14"], i1["atr14"]
        price, close15 = s["current_price"], s["last_closed_15m"]
        chase = cfg.NO_CHASE_ATR15 * atr15
        supports = [(z["low"], f"{z['low']:g}-{z['high']:g} desteği") for z in st["supports"]]
        swing = [(st.get("swing_low_1h"), "son 1h swing dip")]
        if st["confirmed_breakout"]:
            rt, rc, bo = st["retest"], st["reclaim"], st["breakout"]
            top, zone = st["broken_resistance"], bo["zone"]
            q = bo.get("candle") or {}
            evidence.append(f"{top:g} direnci {bo['bars_ago']} mum önce 15m kapanışla kırıldı (hacim {q.get('volume_ratio')}x, "
                            f"gövde {q.get('body_atr')} ATR, üst fitil oranı {q.get('upper_wick_ratio')}); hacim şart değil, bilgi")
            retest_view = {**rt, "current_distance_atr15": rt["distance_atr15"]}
            conf = rt["confirmation"]
            if rc:
                setup, status = "RECLAIM", "RECLAIM_WATCH"
                evidence.append(f"{top:g} seviyesi önce kaybedildi ({rc['failed_at']}), sonra kapanışla geri alındı; "
                                f"{rc['held_bars']} mumdur üstünde")
                if rc["confirmed"]:
                    plan, b, w = _plan(s, "RECLAIM", "RECLAIM_HELD", zone, rc["hold_high"],
                                       [(rc["hold_low"], "geri alış dibi"), (zone[0], "geri alınan bölge"), *swing, *supports])
                    blocks += b
                    warnings += w
                    waits.append(_item("RECLAIM_RESEARCH_ONLY", WAIT_TR))
                    next_review = f"{rc['hold_high']:g} üstünde 15m kapanış ya da {top:g} altına dönüş"
                else:
                    waits.append(_item("RECLAIM_NOT_HELD", WAIT_TR, f"{rc['held_bars']}/{cfg.RECLAIM_HOLD_BARS} mum"))
                    next_review = f"{top:g} üstünde {cfg.RECLAIM_HOLD_BARS} kapanmış 15m mum"
            elif conf and conf["bars_ago"] <= cfg.RETEST_CONFIRM_MAX_BARS:
                setup = "RETEST"
                trigger = next_tick(conf["high"], tick)
                evidence.append(f"Fiyat {rt['zone_low']:g}-{rt['zone_high']:g} geri test bölgesine döndü; {conf['time']} mumu "
                                f"{top:g} üstünde kapandı")
                if price - trigger > chase:
                    status = "WAIT_FOR_RETEST"
                    waits.append(_item("NO_CHASE", WAIT_TR, f"teyit mumunun tepesinden {(price - trigger) / atr15:.1f} ATR(15m) yukarıda"))
                    pending = _retest_wait(s, rt, [(zone[0], "kırılan bölge"), *swing, *supports])
                    next_review = f"fiyat yeniden {rt['zone_low']:g}-{rt['zone_high']:g} bölgesine dönerse"
                else:
                    status = "BUY_SETUP"
                    plan, b, w = _plan(s, "RETEST", "RETEST_CONFIRMED", zone, conf["high"],
                                       [(rt["structure_low"], "geri test dibi"), (zone[0], "kırılan bölge"), *swing, *supports])
                    blocks += b
                    warnings += w
                    next_review = f"tetik {trigger:g}; {rt['zone_low']:g} altında 15m kapanış kurulumu bozar"
            else:
                setup = "BREAKOUT"
                trigger = next_tick(top, tick)
                if price - trigger > chase:
                    setup, status = "RETEST", "WAIT_FOR_RETEST"
                    waits.append(_item("NO_CHASE", WAIT_TR, f"tetikten {(price - trigger) / atr15:.1f} ATR(15m) yukarıda"))
                    waits.append(_item("RETEST_NOT_CONFIRMED" if rt["entered_zone"] else "RETEST_NOT_REACHED", WAIT_TR))
                    pending = _retest_wait(s, rt, [(zone[0], "kırılan bölge"), *swing, *supports])
                    next_review = (f"bir 15m mum {rt['zone_low']:g}-{rt['zone_high']:g} bölgesine girip {top:g} üstünde kapanırsa")
                else:
                    status = "BUY_SETUP"
                    plan, b, w = _plan(s, "BREAKOUT", "BREAKOUT_CONFIRMED", zone, top, [(zone[0], "kırılan bölge"), *swing, *supports])
                    blocks += b
                    warnings += w
                    next_review = f"{zone[0]:g} altında 15m kapanış kırılımı geri alır"
        elif st["failed_breakout"]:
            setup, status = "RECLAIM", "RECLAIM_WATCH"
            lvl = st["control_level"]
            waits.append(_item("FAILED_BREAKOUT_NOT_RECLAIMED", WAIT_TR, f"{lvl:g}"))
            evidence.append(f"{lvl:g} üstünde 15m kapanış geldi, fiyat geri altına döndü: sahte kırılım")
            next_review = f"{lvl:g} üstünde yeniden 15m kapanış ve {cfg.RECLAIM_HOLD_BARS} mum tutunma"
        else:
            r = st["nearest_resistance"]
            if r and r["low"] - close15 <= cfg.PLAN_RANGE_ATR1H * atr1h:
                setup, status = "BREAKOUT", "WAIT_FOR_BREAKOUT"
                trigger = next_tick(r["high"], tick)
                evidence.append(f"{r['low']:g}-{r['high']:g} direnci {r['touch_count']} temas ({'+'.join(r['timeframe'])}); "
                                "kapanış teyidi yok" + ("; açık mum direncin üstünde ama kapanmadı" if st["open_candle_above"] else ""))
                if r["touch_count"] < 2:
                    warnings.append({"code": "SINGLE_TOUCH", "text": "Direnç tek temasa dayanıyor"})
                if price - trigger > chase:
                    waits.append(_item("NO_CHASE", WAIT_TR, "açık mum tetiğin çok üstünde; kapanış ve geri test beklenir"))
                    next_review = f"{r['high']:g} üstünde 15m kapanış, ardından geri test"
                else:
                    plan, b, w = _plan(s, "BREAKOUT", "BREAKOUT_PENDING", [r["low"], r["high"]], r["high"], [*swing, *supports])
                    blocks += b
                    warnings += w
                    next_review = f"{r['high']:g} direnç testi"
            else:
                pull = (s.get("v1_reference") or {}).get("pullback")
                if pull:
                    setup, status = "PULLBACK", "PULLBACK_SETUP"
                    waits.append(_item("PULLBACK_RESEARCH_ONLY", WAIT_TR))
                    next_review = f"{pull['entry_zone_low']:g}-{pull['entry_zone_high']:g} bölgesinde 15m dönüş"
                else:
                    waits.append(_item("NO_LEVEL", WAIT_TR))
                    next_review = (f"{r['low']:g} direncine yaklaşınca" if r else "yeni bir direnç oluşunca")

    underlying = status
    withheld = pending                          # a retest that is still awaited: its zone and stop, not an order
    if status == "RECLAIM_WATCH" and plan:      # a reclaim is watched, never offered: its levels are kept for the paper log
        withheld, plan = plan, None
    if blocks:
        if underlying in ("BUY_SETUP", "WAIT_FOR_BREAKOUT", "WAIT_FOR_RETEST", "RECLAIM_WATCH", "PULLBACK_SETUP"):
            status, withheld, plan = "BLOCKED_SETUP", plan or withheld, None
        else:
            status = "AVOID" if any(b["code"] in ("TREND_1H_DOWN", "4H_STRONG_DOWN", "HTF_STRONG_DOWNTREND") for b in blocks) else "NO_SETUP"
    result = ("BLOCKED_SETUP" if status == "BLOCKED_SETUP" else "BUY_SETUP" if plan else
              "WAIT" if status in ("WAIT_FOR_BREAKOUT", "WAIT_FOR_RETEST", "RECLAIM_WATCH", "PULLBACK_SETUP") else "NO_SETUP")
    group = "READY_TO_WATCH" if status == "BUY_SETUP" else status
    return {"status": status, "status_tr": STATUS_TR[status], "result": result, "setup": setup, "group": group,
            "underlying_status": underlying if status == "BLOCKED_SETUP" else None,
            "evidence_status": EVIDENCE_STATUS, "actionable": plan is not None, "plan": plan, "withheld_plan": withheld,
            "retest": retest_view, "blocks": blocks, "waits": waits, "warnings": warnings, "evidence": evidence,
            "why_not": [x["text"] for x in blocks + waits] if not plan else [], "next_review": next_review,
            "order_sent": False}

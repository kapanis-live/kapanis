"""SAT = position protection, not a market sell: take profit, stop loss, invalidation, current R, what to watch next.

    build_protection_plan(snapshot dict, state, manual_stop=None) -> {"action", "state", "current_R", "stop_loss", ...}

The trade's unit is R: the distance from the entry to the FIRST stop. The stop is not dragged up just to be above
the cost:

    INITIAL      below +1R        the initial structural stop stays where it is
    PROFIT_1R    from +1R         break-even plus fees, only if the price still has room above it
    PROFIT_2R    from +2R         a confirmed 15m higher low, or the 1h support, minus an ATR buffer
    TRENDING     +2R, structure   the same candidates; the position runs while the structure holds
    PROTECT      weakness         15m turned down, 1h closed under its SMA20, or a resistance rejected the price
    EXITED       stop seen        a closed 15m candle traded at or under the stop

The stop only moves up (monotonic): a stop that reached 100 is never 95 on the next run, unless the user overrides it
by hand. RSI alone never sells, and a single average cross never does either. No order is sent.
"""
from __future__ import annotations

from . import config as cfg
from .planner import portfolio_warnings, technical_stop
from .snapshot import DOWNS, UPS, floor_tick

STATES = ("INITIAL", "PROFIT_1R", "PROFIT_2R", "TRENDING", "PROTECT", "EXITED")
ACTION_TR = {"HOLD": "TUT", "PROTECT": "KORU — stopu gözden geçir", "REDUCE": "RİSKİ AZALT", "EXIT": "ÇIK — yapı bozuldu",
             "EXITED": "STOP GÖRÜLDÜ"}
EXIT_TR = {"STOP_HIT": "Kapanmış 15m mum stop seviyesinde ya da altında işlem gördü",
           "STOP_BREACHED": "Fiyat stop seviyesinin altında",
           "STRUCTURAL_INVALIDATION": "Teknik geçersizlik seviyesinin altında 15m kapanış",
           "HTF_REVERSAL": "4h trend güçlü düşüşe döndü", "MAJOR_SUPPORT_LOST": "Ana destek 1h kapanışla kaybedildi",
           "FAILED_BREAKOUT_NO_RECLAIM": "Girilen kırılım başarısız oldu, seviye geri alınmadı",
           "PORTFOLIO_RISK_HARD_LIMIT": "Portföydeki pay sınırı aşıldı"}


def build_protection_plan(s: dict, state: dict | None = None, manual_stop: float | None = None) -> dict:
    """s: MarketSnapshot.data() with a position in s["portfolio"]. state: what an earlier run stored for this position
    ({"entry_price", "initial_stop", "initial_risk", "last_stop", "invalidation", ...}) or None. Returns the plan and
    "new_state" to store. Deterministic for the same snapshot and state."""
    p, st, f = s["portfolio"], s["structure"], s["timeframes"]
    if not p.get("holding_exists") or not p.get("entry_price"):
        return {"action": None, "error": "NO_POSITION", "text": "Bu coinde kayıtlı pozisyon (giriş fiyatı) yok", "order_sent": False}
    i15, i1 = f["15m"]["indicators"], f["1h"]["indicators"]
    atr15, atr1h = i15["atr14"], i1["atr14"]
    tick = (s.get("execution") or {}).get("tick_size") or 10 ** -8
    price, close15, entry = s["current_price"], s["last_closed_15m"], float(p["entry_price"])
    state = dict(state or {})
    if state.get("entry_price") and abs(state["entry_price"] - entry) > 1e-12:
        state = {}                       # the position was re-entered at another price: the old trade's R is gone
    warnings, reasons, exits = portfolio_warnings(p), [], []

    # --- R: the distance to the first stop
    initial_stop = state.get("initial_stop") or p.get("initial_stop")
    assumed = bool(state.get("initial_stop_assumed")) if state.get("initial_stop") else False
    if not initial_stop or initial_stop >= entry:
        initial_stop = floor_tick(entry - cfg.INITIAL_RISK_FALLBACK_ATR1H * atr1h, tick)
        assumed = True
    if assumed:
        warnings.append({"code": "ESTIMATED_R",
                         "text": f"İlk stop kayıtlı değil: R, {cfg.INITIAL_RISK_FALLBACK_ATR1H:g} ATR(1h) varsayımıyla hesaplanan bir "
                                 "TAHMİNDİR, gerçek R değildir. Gerçek ilk stopunu girersen R ona göre hesaplanır."})
    risk = entry - initial_stop
    r_now = (price - entry) / risk
    room = cfg.MIN_STOP_ATR15 * atr15

    # --- stop candidates, by how far the trade has gone
    # an assumed first stop that the price is already at or under is no stop: it gives R its unit and nothing else
    candidates = [] if assumed and price - initial_stop < room else [(initial_stop, "INITIAL_STRUCTURAL_STOP")]
    be = entry * (1 + 2 * cfg.FEE_PCT / 100)
    if r_now >= cfg.BREAKEVEN_R:
        if price - be >= room:
            candidates.append((floor_tick(be, tick), "BREAK_EVEN_PLUS_FEES"))
        else:
            warnings.append({"code": "BREAK_EVEN_SKIPPED", "text": "Başa baş stopu uygulanmadı: fiyata "
                                                                   f"{cfg.MIN_STOP_ATR15:g} ATR(15m)'den yakın kalırdı"})
    if r_now >= cfg.PROFIT_LOCK_R:
        hl = st.get("higher_low_15m")
        if hl:
            candidates.append((floor_tick(hl["price"] - cfg.HIGHER_LOW_ATR15_BUFFER * atr15, tick), "CONFIRMED_HIGHER_LOW"))
        sup = st.get("nearest_support")
        if sup and "1h" in sup["timeframe"]:
            candidates.append((floor_tick(sup["low"] - cfg.STRUCTURAL_STOP_ATR1H_BUFFER * atr1h, tick), "STRUCTURAL_SUPPORT_1H"))
    fits = [(lvl, src) for lvl, src in candidates if price - lvl >= room or src == "INITIAL_STRUCTURAL_STOP"]
    stop, source = max(fits, key=lambda x: x[0]) if fits else (None, "NONE")
    previous = state.get("last_stop")
    if manual_stop is not None:
        stop, source = float(manual_stop), "MANUAL_OVERRIDE"
        reasons.append("Stop elle girildi: monoton kural bu çalıştırmada uygulanmadı")
    elif previous is not None and (stop is None or previous > stop):
        stop, source = float(previous), state.get("last_stop_source") or "PREVIOUS_STOP"     # never moved down
    elif stop is None:
        # the first stop was never recorded and nothing was stored yet: the structure as it stands today gives the
        # level instead (R keeps its assumed unit, said above); from then on it only moves up like any other stop
        now = technical_stop(price, [(z["low"], "destek") for z in st["supports"]] + [(st.get("swing_low_1h"), "1h swing dip")],
                             atr15, atr1h, tick)
        stop, source = (now["technical_stop"], "CURRENT_STRUCTURE") if now else (None, "NONE")
        reasons.append("İlk stop kayıtlı değil ve fiyat varsayılan stopun altında: stop bugünkü yapıdan alındı" if now else
                       "İlk stop kayıtlı değil ve fiyatın altında teknik seviye yok: stop üretilemedi")
    breathing = None if stop is None else (price - stop) / atr15
    if breathing is not None and breathing <= 0:
        exits.append("STOP_BREACHED")
    elif breathing is not None and breathing < cfg.MIN_STOP_ATR15:
        warnings.append({"code": "STOP_TOO_TIGHT", "text": f"Stop fiyata {breathing:.2f} ATR(15m): normal oynaklık içinde "
                                                           f"(en az {cfg.MIN_STOP_ATR15:g} tercih edilir)"})

    # --- invalidation: the level whose loss breaks the structure (not the same thing as the stop)
    sup = st.get("nearest_support")
    invalidation = sup["low"] if sup else st.get("swing_low_1h")
    if invalidation is None or invalidation > price:
        invalidation = initial_stop

    # --- reasons to leave
    # closed 15m candles since the stop was stored (candle = [close time, open, high, low, close, volume])
    since = state.get("market_timestamp") or ""
    if previous is not None and any(c[3] <= previous for c in f["15m"]["candles"] if c[0] > since):
        exits.append("STOP_HIT")
    if state.get("invalidation") is not None and close15 < state["invalidation"]:
        exits.append("STRUCTURAL_INVALIDATION")
    if st["trend_4h"] == "STRONG_DOWN":
        exits.append("HTF_REVERSAL")
    if st.get("lost_support"):
        exits.append("MAJOR_SUPPORT_LOST")
    level = st.get("control_level")
    if st["failed_breakout"] and level and level <= entry <= level + atr1h:      # the position was bought on that breakout
        exits.append("FAILED_BREAKOUT_NO_RECLAIM")
    over = [k for k, lim in (("portfolio_meme_exposure", cfg.MAX_MEME_EXPOSURE_PCT), ("portfolio_alt_exposure", cfg.MAX_ALT_EXPOSURE_PCT))
            if (p.get(k) or 0) > lim and p["asset_class"] in k.upper()]
    reduce = bool(over)

    # --- weakness that does not end the trade by itself
    weak = []
    if st["trend_15m"] in DOWNS:
        weak.append("15m yapı aşağı döndü")
    if i1.get("sma20") and i1["close"] < i1["sma20"]:
        weak.append("1h kapanış SMA20 altında")
    if st.get("rejection"):
        weak.append("Son 15m mum dirençten uzun üst fitille döndü")

    # --- take profit: structure first, the R fallback only when the sky is clear
    tp = {"price": None, "source": "NONE", "zone": None, "research_fallback": False}
    for z in st["resistances"]:
        if z["low"] - price >= cfg.MIN_TP_ATR1H * atr1h:
            tp = {"price": z["low"], "source": "STRUCTURAL_RESISTANCE", "zone": [z["low"], z["high"]], "research_fallback": False}
            break
    else:
        fallback = entry + cfg.FALLBACK_TP_R * risk
        if fallback - price >= cfg.MIN_TP_ATR1H * atr1h:
            tp = {"price": fallback, "source": "FALLBACK_2_5R", "zone": None, "research_fallback": True}

    trending = r_now >= cfg.PROFIT_LOCK_R and st["trend_1h"] in UPS and st.get("higher_low_15m") is not None and not weak
    if "STOP_HIT" in exits:
        pos_state, action = "EXITED", "EXITED"
    elif exits:
        pos_state, action = "PROTECT", "EXIT"
    elif reduce:
        pos_state, action = "PROTECT", "REDUCE"
        exits.append("PORTFOLIO_RISK_HARD_LIMIT")
    elif weak and r_now > 0:
        pos_state, action = "PROTECT", "PROTECT"
    else:
        pos_state = ("TRENDING" if trending else "PROFIT_2R" if r_now >= cfg.PROFIT_LOCK_R else
                     "PROFIT_1R" if r_now >= cfg.BREAKEVEN_R else "INITIAL")
        action = "HOLD"
    reasons += weak
    if pos_state == "INITIAL":
        reasons.append(f"+{cfg.BREAKEVEN_R:g}R öncesi: ilk yapısal stop korunur, başa başa çekilmez")
    if source == "CONFIRMED_HIGHER_LOW":
        reasons.append("Stop teyitli 15m yükselen dibin altında")
    if tp["price"] is not None and tp["price"] < entry:
        reasons.append("Hedef girişin altında: kâr seviyesi değil, zararı azaltma seviyesi")
    if tp["research_fallback"]:
        reasons.append(f"Üstte geçerli direnç yok: hedef {cfg.FALLBACK_TP_R:g}R (araştırma varsayımı, test edilmiş hedef değil)")
    next_r = cfg.BREAKEVEN_R if r_now < cfg.BREAKEVEN_R else cfg.PROFIT_LOCK_R if r_now < cfg.PROFIT_LOCK_R else None
    watch = [f"{invalidation:g} altında 15m kapanış (geçersizlik)"]
    if tp["price"]:
        watch.append(f"{tp['price']:g} hedef bölgesi")
    if next_r:
        watch.append(f"+{next_r:g}R = {entry + next_r * risk:g}")
    new_state = {"symbol": s["symbol"], "entry_price": entry, "initial_stop": initial_stop, "initial_stop_assumed": assumed,
                 "initial_stop_source": "ASSUMED_ATR" if assumed else state.get("initial_stop_source") or p.get("initial_stop_source") or "RECORDED",
                 "initial_risk": risk, "last_stop": stop, "last_stop_source": source, "invalidation": invalidation,
                 "state": pos_state, "max_R": round(max(r_now, state.get("max_R") or r_now), 3),
                 "market_timestamp": s["market_timestamp"]}
    return {"symbol": s["symbol"], "pair": s["pair"], "action": action, "action_tr": ACTION_TR[action], "state": pos_state,
            "current_price": price, "entry_price": entry, "quantity": p.get("quantity"),
            "initial_stop": initial_stop, "initial_stop_assumed": assumed, "initial_risk": round(risk, 12),
            "initial_stop_source": "ASSUMED_ATR" if assumed else state.get("initial_stop_source") or p.get("initial_stop_source") or "RECORDED",
            # R measured from an assumed first stop is an estimate and is shown as one ("~1.3R (estimated)")
            "current_R": round(r_now, 2), "current_R_estimated": assumed, "r_basis": "ESTIMATED_R" if assumed else "RECORDED_INITIAL_STOP",
            "unrealized_pnl_pct": p.get("unrealized_pnl_pct"),
            "stop_loss": stop, "stop_source": source, "previous_stop": previous,
            "technical_invalidation": invalidation, "break_even_level": floor_tick(be, tick),
            "breathing_room_atr15": None if breathing is None else round(breathing, 2),
            "take_profit": tp["price"], "take_profit_source": tp["source"], "take_profit_zone": tp["zone"],
            "trailing_reference_3atr": floor_tick(price - cfg.TRAIL_REFERENCE_ATR1H * atr1h, tick),
            "trailing_note": "3 ATR günlük testte en iyisiydi; 15m/1h için doğrulanmadı: yalnız referans",
            "exit_reasons": [{"code": c, "text": EXIT_TR[c]} for c in exits], "reasons": reasons, "warnings": warnings,
            "next_review": "; ".join(watch), "new_state": new_state, "order_sent": False}

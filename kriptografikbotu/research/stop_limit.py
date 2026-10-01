"""Order planning: the execution and risk layer that sits on top of the 0/1 strategies. RESEARCH, not wired to the bot.

    STRATEGY    "should a trade be looked for here?"   research/strategies.py, unchanged; passed in as information
    SETUP       "where is resistance / support?"       clusters_at(), swing_low_at(), score_at()
    ENTRY       "at which price should it trigger?"    entry_order()
    RISK        "where is the stop, how much to buy?"  stop_level(), targets(), position_size()
    MANAGEMENT  "trailing stop / targets / exit"       trailing()

build_plan() chains the layers into a TradePlan, format_plan() prints it. Every function uses only bars up to the
last CLOSED one; swings are confirmed K bars later, so a level never depends on a bar that had not happened yet.
The same functions are used by the history test (stop_limit_bt.py), so what is shown is what was tested.

    python research/stop_limit.py BTC            # crypto, daily bars, live data
    python research/stop_limit.py THYAO BIST 250000
    python research/stop_limit.py NVDA ABD
    python research/stop_limit.py SOL KRIPTO 1000 --secilen   # the development-chosen parameters instead of the defaults
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from types import SimpleNamespace

import numpy as np
import pandas as pd

K = 3                    # a swing high needs K lower highs on both sides: it is known K bars after it happened
LOOKBACK = 250           # bars searched for resistance
SWING_LOW_LOOKBACK = 60
CLUSTER_ATR = 0.5        # levels closer than this (in ATR) are one resistance
CLUSTER_PCT = 0.003      # ...or closer than this share of the price, whichever is wider
MAX_CLUSTERS = 8
MIN_STRUCT_ATR = 1.0     # a structural stop closer than this is inside normal noise
MAX_STRUCT_ATR = 3.0     # ...and farther than this is not "the nearest invalidation" any more
ATR_STOP = 1.5           # fallback stop when no structural level fits
MIN_RR = 1.5             # below this: no order
GOOD_RR = 2.0            # preferred
# ATR multiple of the trailing stop by benchmark regime (low, high); PANIK = no new position
REGIME_TRAIL = {"TREND_UP": (2.0, 2.5), "YATAY": (1.3, 1.8), "YUKSEK_VOL": (2.5, 3.0), "TREND_DOWN": (1.3, 1.8)}
TRAIL_UNKNOWN = (1.3, 1.8)   # regime unknown or PANIK while already holding: the tight band
MAJORS = {"BTC", "ETH"}


@dataclass(frozen=True)
class Params:
    pct_buffer: float            # breakout buffer, share of the resistance
    atr_buffer: float            # breakout buffer, x ATR14 (the larger of the two is used)
    limit_cap: float             # the limit may be at most this share above the trigger
    max_risk_pct: float          # entry-to-stop distance above this share of the entry: no order
    limit_pct: float = 0.0015
    limit_atr: float = 0.08
    stop_mode: str = "kombine"   # atr1 | atr1.5 | atr2 | swing | swing_tampon | kombine
    stop_atr_pad: float = 0.15   # stop sits this many ATR below the structural level
    trail: float | str = "rejim"  # ATR multiple, or "rejim" = REGIME_TRAIL by the benchmark's regime
    min_rr: float = MIN_RR
    min_score: int = 4           # breakout score 0-3: no order
    require_two_touches: bool = False  # True: no order on a single-touch resistance
    tp_mode: str = "iz"          # "iz": trailing stop only | "yarim": sell half at TP1, trail the rest
    entry_mode: str = "stop_limit"  # "kapanis": buy the close of the day that closed above the resistance (comparison)


DEFAULTS = {
    "KRIPTO": Params(pct_buffer=0.0015, atr_buffer=0.10, limit_cap=0.0040, max_risk_pct=0.12),
    "BIST": Params(pct_buffer=0.0010, atr_buffer=0.08, limit_cap=0.0025, max_risk_pct=0.08),
    "ABD": Params(pct_buffer=0.0010, atr_buffer=0.08, limit_cap=0.0025, max_risk_pct=0.08),
}
# What the development period preferred over the defaults above (stop_limit_bt.py, 2026-10-01; one dimension at a
# time, the locked year never consulted). Status RESEARCH in both markets: it beat its random twin in development,
# not in the validation year, so nothing here is a recommendation. ABD was not tested.
DEV_CHOSEN = {
    "KRIPTO": replace(DEFAULTS["KRIPTO"], pct_buffer=0.0, atr_buffer=0.0, stop_mode="atr2", trail=3.0, min_rr=0.0),
    "BIST": replace(DEFAULTS["BIST"], atr_buffer=0.0, trail=3.0, min_rr=0.0, min_score=-99),
}


@dataclass
class TradePlan:
    symbol: str
    decision: str

    current_price: float

    resistance: float | None
    stop_trigger: float | None
    limit_price: float | None

    initial_stop: float | None
    invalidation: float | None

    tp1: float | None
    tp2: float | None

    risk_reward_tp1: float | None
    risk_reward_tp2: float | None

    trailing_stop_percent: float | None
    trailing_stop_atr: float | None

    atr14: float | None
    rsi14: float | None

    breakout_score: int
    confidence: str

    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # extras (not in the minimal schema)
    market: str = "KRIPTO"
    regime: str | None = None
    resistance_touches: int | None = None
    r_levels: dict | None = None            # {"1R": .., "2R": .., "3R": ..}
    position: dict | None = None            # position_size() result when a portfolio size is given
    strategy_position: int | None = None    # the 0/1 strategy's own decision, shown, never overridden

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------- data ----------------
def prepare(df: pd.DataFrame, bench: pd.DataFrame | None = None) -> SimpleNamespace:
    """OHLCV frame (t in ms, o h l c v; closed bars only) -> arrays with the indicators every layer needs.

    bench: the benchmark's frame with columns day, c, sma50, ret63 and (optional) regime; mapped by calendar day.
    """
    o, h, l, c, v = (df[k].astype(float) for k in ("o", "h", "l", "c", "v"))
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    d = c.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(), (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    day = pd.to_datetime(df.t, unit="ms").dt.normalize()
    win = 2 * K + 1
    b = SimpleNamespace(
        n=len(df), day=day.values, o=o.values, h=h.values, l=l.values, c=c.values, v=v.values,
        atr=tr.ewm(alpha=1 / 14, adjust=False).mean().values,
        sma20=c.rolling(20).mean().values, sma50=c.rolling(50).mean().values, sma200=c.rolling(200).mean().values,
        rsi=(100 - 100 / (1 + up / dn)).values,
        vma20=v.rolling(20).mean().values, vma5=v.rolling(5).mean().values,
        ret63=(c / c.shift(63) - 1).values,
        hi10=h.rolling(10).max().values, lo10=l.rolling(10).min().values,
        # confirmed swings: bar j is a swing high if its high is the highest of j-K..j+K (usable from bar j+K on)
        ph_idx=np.flatnonzero((h == h.rolling(win, center=True).max()).values),
        pl_idx=np.flatnonzero((l == l.rolling(win, center=True).min()).values),
    )
    if bench is not None:
        bb = bench.set_index("day")
        b.bench_ret63 = day.map(bb.ret63).values.astype(float)
        b.bench_up = day.map((bb.c > bb.sma50).astype(float).where(bb.sma50.notna())).values.astype(float)  # 1 / 0 / NaN
        b.regime = day.map(bb.regime).fillna("?").values if "regime" in bb else np.full(b.n, "?", dtype=object)
    else:
        b.bench_ret63 = np.full(b.n, np.nan)
        b.bench_up = np.full(b.n, np.nan)
        b.regime = np.full(b.n, "?", dtype=object)
    return b


# ---------------- SETUP ----------------
def clusters_at(b, i: int) -> list[tuple[float, int, int]]:
    """Resistance clusters at or above the close of bar i, nearest first: (level, touches, last touch bar).

    Candidates: confirmed swing highs of the last LOOKBACK bars, the 20-bar high (Donchian upper band) and the
    SMA20/50/200 when they are above the price. Candidates within max(0.5 ATR, 0.3 %) are one resistance; its level
    is the top of the cluster (a breakout has to clear every touch) and its touches are the distinct sources.
    """
    c, atr = b.c[i], b.atr[i]
    if not atr > 0:
        return []
    a = np.searchsorted(b.ph_idx, max(0, i - LOOKBACK))
    z = np.searchsorted(b.ph_idx, i - K, side="right")
    cand = [(b.h[j], int(j)) for j in b.ph_idx[a:z] if b.h[j] >= c]
    d0 = max(0, i - 19)
    jm = d0 + int(np.argmax(b.h[d0:i + 1]))
    cand.append((b.h[jm], jm))
    for lvl, tag in ((b.sma20[i], -1), (b.sma50[i], -2), (b.sma200[i], -3)):
        if lvl > c:   # False for NaN
            cand.append((lvl, tag))
    cand.sort()
    tol = max(CLUSTER_ATR * atr, CLUSTER_PCT * c)
    out, base = [], None
    for lvl, src in cand:
        if base is None or lvl - base > tol:
            out.append([lvl, {src}])
            base = lvl
        else:
            out[-1][0] = lvl
            out[-1][1].add(src)
    return [(float(lvl), len(s), max(s)) for lvl, s in out[:MAX_CLUSTERS]]


def main_resistance(clusters: list, require_two: bool = False) -> int | None:
    """Index of the main resistance: the nearest cluster with at least 2 touches; a single touch only as a fallback."""
    for k, (_, touches, _) in enumerate(clusters):
        if touches >= 2:
            return k
    return None if require_two or not clusters else 0


def swing_low_at(b, i: int) -> float:
    """The most recent confirmed swing low below the close of bar i (NaN if none in the lookback)."""
    a = np.searchsorted(b.pl_idx, max(0, i - SWING_LOW_LOOKBACK))
    z = np.searchsorted(b.pl_idx, i - K, side="right")
    for j in b.pl_idx[a:z][::-1]:
        if b.l[j] < b.c[i]:
            return float(b.l[j])
    return math.nan


def score_at(b, i: int, res: float, last_touch: int, detail: bool = True) -> tuple[int, list[str], list[str]]:
    """Breakout quality at the close of bar i, before the breakout: +10 .. -6. Information, never a strategy decision."""
    c, atr = b.c[i], b.atr[i]
    plus, minus, s = [], [], 0

    def add(ok, pts, text, bucket):
        nonlocal s
        if ok:
            s += pts
            if detail:
                bucket.append(text)

    rsi, v = b.rsi[i], b.v[i]
    add(c > b.sma20[i], 1, "fiyat SMA20 üstünde", plus)
    add(c > b.sma50[i], 1, "fiyat SMA50 üstünde", plus)
    add(c > b.sma200[i], 1, "fiyat SMA200 üstünde", plus)
    add(b.sma20[i] > b.sma50[i], 1, "SMA20 > SMA50", plus)
    add(50 <= rsi <= 70, 1, f"RSI {rsi:.0f} (50-70 arası)", plus)
    add(v > b.vma20[i], 1, "son hacim 20 günlük ortalamanın üstünde", plus)
    add(v > 1.5 * b.vma20[i], 1, "hacim ortalamanın 1,5 katından fazla", plus)
    add(b.hi10[i] - b.lo10[i] <= 3 * atr and res - c <= 1.5 * atr, 1, "direnç altında sıkışma (10 mum, dar aralık)", plus)
    add(b.ret63[i] > b.bench_ret63[i], 1, "3 aylık getiri endeksten güçlü", plus)
    add(b.bench_up[i] == 1.0, 1, "endeks/BTC 50 günlük ortalamasının üstünde", plus)
    add(rsi > 75, -1, f"RSI {rsi:.0f} > 75 (ısınmış)", minus)
    if last_touch >= 0:
        rng = b.h[last_touch] - b.l[last_touch]
        wick = b.h[last_touch] - max(b.o[last_touch], b.c[last_touch])
        add(rng > 0 and wick >= 0.6 * rng, -1, "dirence son dokunan mumda uzun üst fitil (satış baskısı)", minus)
    add(b.vma5[i] < 0.8 * b.vma20[i], -1, "hacim düşüyor (5 günlük ortalama 20 günlüğün %80'inin altında)", minus)
    add(c < b.sma200[i], -1, "fiyat SMA200 altında", minus)
    add(b.regime[i] == "PANIK", -2, "piyasa PANİK rejiminde", minus)
    return s, plus, minus


def confidence(score: int) -> str:
    return "ZAYIF (emir verme / bekle)" if score <= 3 else "NORMAL" if score <= 6 else "GÜÇLÜ KIRILIM ADAYI"


# ---------------- ENTRY ----------------
def entry_order(res, atr, p: Params):
    """Stop-limit BUY above the resistance: (trigger, limit). Works on numbers and on arrays."""
    trigger = res + np.maximum(res * p.pct_buffer, atr * p.atr_buffer)
    limit = trigger + np.maximum(trigger * p.limit_pct, atr * p.limit_atr)
    return trigger, np.minimum(limit, trigger * (1 + p.limit_cap))


# ---------------- RISK ----------------
def stop_level(entry: float, atr: float, swing_low: float, sma20: float, sma50: float, p: Params):
    """(stop, invalidation level, text) or None when the mode has no level. Never a fixed percentage."""
    m = p.stop_mode
    if m.startswith("atr"):
        k = float(m[3:])
        return entry - k * atr, entry - k * atr, f"{k:g} ATR"
    if m in ("swing", "swing_tampon"):
        if not swing_low < entry:
            return None
        pad = p.stop_atr_pad * atr if m == "swing_tampon" else 0.0
        return swing_low - pad, swing_low, "son swing dip" + (f" − {p.stop_atr_pad:g} ATR" if pad else "")
    # kombine: the nearest structural level that is neither inside the noise nor far away, padded by ATR;
    # the 1.5 ATR stop when no level fits
    best = None
    for lvl, name in ((swing_low, "son swing dip"), (sma20, "SMA20"), (sma50, "SMA50")):
        if MIN_STRUCT_ATR * atr <= entry - lvl <= MAX_STRUCT_ATR * atr and (best is None or lvl > best[0]):
            best = (lvl, name)
    if best:
        return best[0] - p.stop_atr_pad * atr, best[0], f"{best[1]} − {p.stop_atr_pad:g} ATR"
    return entry - ATR_STOP * atr, entry - ATR_STOP * atr, f"{ATR_STOP:g} ATR (1-3 ATR arasında yapısal seviye yok)"


def targets(entry: float, stop: float, clusters: list, above: float):
    """(tp1, tp2, rr1, rr2, technical) from the resistances above `above`; R multiples when the sky is clear."""
    risk = entry - stop
    ups = [x for x in clusters if x[0] > above]
    strong = [x for x in ups if x[1] >= 2]
    if not ups:
        return entry + 2 * risk, entry + 3 * risk, None, None, False
    tp1 = (strong or ups)[0][0]
    higher = [x for x in ups if x[0] > tp1]
    tp2 = ([x for x in higher if x[1] >= 2] or higher or [(max(entry + 3 * risk, tp1 + risk),)])[0][0]
    return tp1, tp2, (tp1 - entry) / risk, (tp2 - entry) / risk, True


def trail_band(regime: str) -> tuple[float, float]:
    return REGIME_TRAIL.get(regime, TRAIL_UNKNOWN)


def trailing(regime: str, atr: float, price: float, p: Params) -> tuple[float, float]:
    """(ATR multiple, distance as % of the price) of the trailing stop."""
    mult = float(p.trail) if p.trail != "rejim" else sum(trail_band(regime)) / 2
    return mult, mult * atr / price * 100


def position_size(portfolio: float, entry: float, stop: float, market: str, symbol: str, atr_pct: float,
                  risk_pct: float = 0.005) -> dict:
    """Money to put in so that a stop costs risk_pct of the portfolio; capped at 20 % (volatile altcoins 10-15 %)."""
    cap = 0.20
    if market == "KRIPTO" and symbol.upper() not in MAJORS:
        cap = 0.10 if atr_pct >= 0.06 else 0.15 if atr_pct >= 0.04 else 0.20
    risk_amount = portfolio * risk_pct
    wanted = risk_amount / ((entry - stop) / entry)
    amount = min(wanted, portfolio * cap)
    qty = amount / entry
    if market != "KRIPTO":
        qty = math.floor(qty)
        amount = qty * entry
    return {"tutar": round(amount, 2), "adet": qty, "portfoy_payi_%": round(amount / portfolio * 100, 1),
            "risk_tutari": round(amount * (entry - stop) / entry, 2), "risk_%": risk_pct * 100,
            "sinir_%": cap * 100, "sinira_takildi": wanted > portfolio * cap}


# ---------------- plan ----------------
def _f(x: float | None) -> str:
    if x is None or x != x:
        return "—"
    a = abs(x)
    return f"{x:,.0f}" if a >= 10000 else f"{x:,.2f}" if a >= 1 else f"{x:.6g}"


def build_plan(df: pd.DataFrame, market: str, symbol: str, bench: pd.DataFrame | None = None,
               params: Params | None = None, current_price: float | None = None, portfolio: float | None = None,
               risk_pct: float = 0.005, strategy_position: int | None = None) -> TradePlan:
    """The order plan at the last bar of df (closed bars only)."""
    p = params or DEFAULTS[market]
    b = prepare(df, bench)
    i = b.n - 1
    price = float(current_price if current_price is not None else b.c[i])
    atr, rsi, regime = float(b.atr[i]), float(b.rsi[i]), str(b.regime[i])
    reasons, warnings = [], []
    clusters = clusters_at(b, i)
    m = main_resistance(clusters, p.require_two_touches)
    base = dict(symbol=symbol, current_price=price, atr14=atr, rsi14=round(rsi, 1), market=market, regime=regime,
                strategy_position=strategy_position)
    if strategy_position is not None:
        reasons.append(f"Strateji katmanı: {'içeride (1)' if strategy_position else 'dışarıda (0)'}; bu plan o kararı değiştirmez")
    if m is None or b.n < 60:
        return TradePlan(decision="BEKLE — geçerli direnç bulunamadı", resistance=None, stop_trigger=None, limit_price=None,
                         initial_stop=None, invalidation=None, tp1=None, tp2=None, risk_reward_tp1=None,
                         risk_reward_tp2=None, trailing_stop_percent=None, trailing_stop_atr=None, breakout_score=0,
                         confidence=confidence(0), reasons=reasons,
                         warnings=["En az 2 temaslı direnç yok" if clusters else "Yeterli veri yok"], **base)
    res, touches, last_touch = clusters[m]
    score, plus, minus = score_at(b, i, res, last_touch)
    trigger, limit = (float(x) for x in entry_order(res, atr, p))
    st = stop_level(trigger, atr, swing_low_at(b, i), b.sma20[i], b.sma50[i], p)
    stop, invalid, stop_text = st if st else (None, None, "")
    tp1 = tp2 = rr1 = rr2 = None
    technical = False
    if stop is not None:
        tp1, tp2, rr1, rr2, technical = targets(trigger, stop, clusters, limit)
    t_mult, t_pct = trailing(regime, atr, price, p)
    lo, hi = trail_band(regime)

    reasons.append(f"{_f(res)} en yakın geçerli direnç ({touches} temas" + (", tek temas: zayıf" if touches < 2 else "") + ")")
    reasons.append(f"Tetik direncin %{(trigger / res - 1) * 100:.2f} üstünde: tampon = max(direnç × %{p.pct_buffer * 100:g}, "
                   f"{p.atr_buffer:g} × ATR {_f(atr)})")
    reasons.append(f"Limit tetiğin %{(limit / trigger - 1) * 100:.2f} üstünde (en fazla %{p.limit_cap * 100:g})")
    if stop is not None:
        reasons.append(f"Zarar durdur: {stop_text}; girişe uzaklık %{(trigger - stop) / trigger * 100:.1f} "
                       f"({(trigger - stop) / atr:.1f} ATR)")
        risk = trigger - stop
        r_levels = {f"{k}R": trigger + k * risk for k in (1, 2, 3)}
        if technical:
            reasons.append(f"TP1 {_f(tp1)} = {rr1:.1f}R, TP2 {_f(tp2)} = {rr2:.1f}R "
                           f"(1R {_f(r_levels['1R'])} · 2R {_f(r_levels['2R'])} · 3R {_f(r_levels['3R'])})")
        else:
            reasons.append("Üstte teknik direnç yok: hedefler 2R ve 3R")
    else:
        r_levels = None
    reasons += [f"+ {x}" for x in plus]
    reasons.append(f"İz süren stop {t_mult:g} ATR = %{t_pct:.1f} (rejim {regime}: {lo:g}-{hi:g} ATR)"
                   if p.trail == "rejim" else f"İz süren stop {t_mult:g} ATR = %{t_pct:.1f}")
    reasons.append("Hacim teyidi kırılım günü belli olur: kırılım mumunun hacmi ortalamanın üstünde değilse temkinli ol")
    warnings += [f"− {x}" for x in minus]
    warnings.append(f"Kırılımdan sonra {_f(res)} altında günlük kapanış: kırılım başarısız (erken uyarı)")
    if touches < 2:
        warnings.append("Direnç tek temasa dayanıyor (20 günlük zirve); kümelenme yok")

    if regime == "PANIK":
        decision = "YENİ POZİSYON AÇMA — piyasa PANİK rejiminde"
    elif score <= 3:
        decision = f"EMİR VERME / BEKLE — kırılım skoru {score}/10"
    elif stop is None:
        decision = "EMİR ÖNERİLMEZ — stop için teknik seviye yok"
    elif (trigger - stop) / trigger > p.max_risk_pct:
        decision = (f"EMİR ÖNERİLMEZ — giriş-stop mesafesi %{(trigger - stop) / trigger * 100:.1f}, "
                    f"sınır %{p.max_risk_pct * 100:g}")
    elif rr1 is not None and rr1 < p.min_rr:
        decision = f"R/R YETERSİZ — EMİR ÖNERİLMEZ (TP1 için {rr1:.2f}, en az {p.min_rr:g})"
    elif price >= trigger:
        decision = f"BEKLE — fiyat tetiği ({_f(trigger)}) geçmiş; kovalamak yok, yeni kurulum bekle"
    else:
        decision = f"STOP-LIMIT ALIŞ — {_f(res)} direnci kırılmadığı sürece BEKLE"
        if rr1 is not None and rr1 < GOOD_RR:
            warnings.append(f"R/R {rr1:.2f}: tercih edilen {GOOD_RR:g}'nin altında (ilk direnç girişe yakın)")
    pos = None
    if portfolio and stop is not None and decision.startswith("STOP-LIMIT"):
        pos = position_size(portfolio, trigger, stop, market, symbol, atr / price, risk_pct)
    return TradePlan(decision=decision, resistance=res, stop_trigger=trigger, limit_price=limit, initial_stop=stop,
                     invalidation=invalid, tp1=tp1, tp2=tp2,
                     risk_reward_tp1=None if rr1 is None else round(rr1, 2),
                     risk_reward_tp2=None if rr2 is None else round(rr2, 2),
                     trailing_stop_percent=round(t_pct, 2), trailing_stop_atr=t_mult, breakout_score=score,
                     confidence=confidence(score), reasons=reasons, warnings=warnings, resistance_touches=touches,
                     r_levels=r_levels, position=pos, **base)


def format_plan(t: TradePlan) -> str:
    cur = {"KRIPTO": "USDT", "BIST": "TL", "ABD": "USD"}[t.market]
    rr = (f"{t.risk_reward_tp1:.1f} / {t.risk_reward_tp2:.1f}" if t.risk_reward_tp1 is not None
          else "üstte direnç yok (hedefler 2R / 3R)")
    lines = [f"{t.symbol} ({t.market}, günlük mum) — durum: ARAŞTIRMA",
             f"Mevcut: {_f(t.current_price)} {cur}", "",
             "STOP-LIMIT ALIŞ", f"Tetik: {_f(t.stop_trigger)}", f"Limit: {_f(t.limit_price)}", "",
             f"Direnç: {_f(t.resistance)}" + (f" ({t.resistance_touches} temas)" if t.resistance_touches else ""),
             f"Zarar durdur: {_f(t.initial_stop)}", f"Teknik geçersizlik: {_f(t.invalidation)}",
             f"TP1: {_f(t.tp1)}", f"TP2: {_f(t.tp2)}", f"R/R: {rr}",
             f"İz süren stop: %{t.trailing_stop_percent:g} ({t.trailing_stop_atr:g} ATR)" if t.trailing_stop_percent else
             "İz süren stop: —",
             f"ATR14: {_f(t.atr14)} · RSI14: {t.rsi14:g} · rejim: {t.regime}",
             f"Breakout skoru: {t.breakout_score}/10 — {t.confidence}", "", f"Karar: {t.decision}"]
    if t.position:
        s = t.position
        lines.append(f"Pozisyon: {_f(s['tutar'])} {cur} ≈ {s['adet']:.6g} adet (portföy payı %{s['portfoy_payi_%']:g}; "
                     f"stop olursa kayıp {_f(s['risk_tutari'])} {cur})"
                     + (f" — %{s['sinir_%']:g} sınırına takıldı" if s["sinira_takildi"] else ""))
    lines += ["", "Gerekçe:", *[f"- {x}" for x in t.reasons]]
    if t.warnings:
        lines += ["", "Uyarılar:", *[f"- {x}" for x in t.warnings]]
    return "\n".join(lines)


# ---------------- command line (live data) ----------------
def _live(symbol: str, market: str):
    """Fresh daily bars for one asset and its benchmark (closed bars only), with the benchmark's regime."""
    import pathlib
    import sys
    import time

    import httpx
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import engine
    import regime

    def binance(coin):
        r = httpx.get("https://data-api.binance.vision/api/v3/klines",
                      params={"symbol": coin + "USDT", "interval": "1d", "limit": 600}, timeout=30)
        r.raise_for_status()
        d = pd.DataFrame({"t": [int(x[0]) for x in r.json()], **{k: [float(x[n]) for x in r.json()]
                                                                  for k, n in (("o", 1), ("h", 2), ("l", 3), ("c", 4), ("v", 7))}})
        return d[d.t + 86_400_000 <= time.time() * 1000].reset_index(drop=True)

    def yahoo(sym):
        r = httpx.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", params={"interval": "1d", "range": "3y"},
                      headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        d = pd.DataFrame({"t": [x * 1000 for x in res["timestamp"]], "o": q["open"], "h": q["high"], "l": q["low"],
                          "c": q["close"], "v": q["volume"]})
        return d.dropna().reset_index(drop=True).iloc[:-1]   # today's candle may still be forming

    if market == "KRIPTO":
        df, bench = binance(symbol), binance("BTC")
    elif market == "BIST":
        df, bench = yahoo(f"{symbol}.IS"), yahoo("XU100.IS")
    else:
        df, bench = yahoo(symbol), yahoo("^GSPC")
    return df, regime.label(engine.indicators(bench))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    sym = (args[0] if args else "BTC").upper()
    mkt = (args[1] if len(args) > 1 else "KRIPTO").upper()
    pf = float(args[2]) if len(args) > 2 else None
    frame, bench_frame = _live(sym, mkt)
    chosen = DEV_CHOSEN.get(mkt) if "--secilen" in sys.argv else None
    print(format_plan(build_plan(frame, mkt, sym, bench_frame, params=chosen, portfolio=pf)))

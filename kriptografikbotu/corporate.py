"""BIST corporate actions and real-return helpers.

Corporate actions (Yahoo chart "events", free):
- Bedelsiz / split: Yahoo adjusts past prices overnight, so a 1:2 bonus issue looks like a 50% crash to
  the exit engine, stops and alarms. apply_splits() rescales every open position (adet up, cost/stop/
  target down), active alarms and plans for splits that happened after the position was opened.
- Temettü: dividends paid while a position was held are counted as (gross) income; last year's
  dividend dates give a rough "expected around" hint. Yahoo has no future dividend dates: KAP decides.
Real return:
- Dollar-based: TL values converted with USD/TRY on the opening day and today (Yahoo USDTRY=X).
- Inflation-based: TÜFE index from TCMB EVDS (free key, EVDS_API_KEY in .env). Without a key the
  inflation column stays empty instead of guessing.
"""
import json
import logging
import time
from datetime import date, datetime, timedelta

import httpx

import alerts_store
import bist
import config
import conversation_store as store
import positions
from macro import TR

log = logging.getLogger(__name__)

EVENTS_TTL = 6 * 3600
CPI_TTL = 24 * 3600
CPI_FILE = config.DATA_DIR / "cpi_cache.json"
EVDS_URL = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
_events: dict[str, tuple[float, dict]] = {}


# --- corporate actions ----------------------------------------------------------------------------

async def events(client: httpx.AsyncClient, symbol: str) -> dict:
    """{"bolunmeler": [{tarih, ms, oran, metin}], "temettuler": [{tarih, ms, tutar}]} for the last 2 years.
    oran > 1 means more shares (bedelsiz 1:1 -> 2.0). Dividend amounts are per current (split-adjusted) share."""
    sym = bist.yahoo_symbol(symbol)
    hit = _events.get(sym)
    if hit and time.time() - hit[0] < EVENTS_TTL:
        return hit[1]
    r = await client.get(bist.YAHOO + sym, params={"interval": "1d", "range": "2y", "events": "div,split"},
                         headers=bist.HEADERS, timeout=20)
    bist._check(r, sym)
    res = (r.json().get("chart") or {}).get("result") or [{}]
    ev = res[0].get("events") or {}
    out = {"bolunmeler": [], "temettuler": []}
    for k, v in (ev.get("splits") or {}).items():
        num, den = v.get("numerator"), v.get("denominator")
        if num and den and num != den:
            out["bolunmeler"].append({"tarih": _day(k), "ms": int(k) * 1000, "oran": num / den,
                                      "metin": v.get("splitRatio", f"{num}:{den}")})
    for k, v in (ev.get("dividends") or {}).items():
        if v.get("amount"):
            out["temettuler"].append({"tarih": _day(k), "ms": int(k) * 1000, "tutar": float(v["amount"])})
    for key in out:
        out[key].sort(key=lambda e: e["ms"])
    _events[sym] = (time.time(), out)
    return out


def _day(ts) -> str:
    return datetime.fromtimestamp(int(ts), TR).date().isoformat()


def _opened_ms(pos: dict) -> int:
    return int(datetime.fromisoformat(pos["acilis"]).timestamp() * 1000)


def split_changes(pos: dict, split: dict) -> dict:
    """New adet/price levels for one position after a split with ratio `oran` (pure, testable)."""
    r = split["oran"]
    ch = {"adet": pos["adet"] * r, "giris": pos["giris"] / r}
    for k in ("stop", "stop_ilk", "hedef"):
        if pos.get(k) is not None:
            ch[k] = pos[k] / r
    if pos.get("son_cikis", {}).get("stop_onerisi"):
        ch["son_cikis"] = {**pos["son_cikis"], "stop_onerisi": pos["son_cikis"]["stop_onerisi"] / r}
    return ch


async def apply_splits() -> list[str]:
    """Rescale open BIST positions, active alarms and plans for new splits. Returns user messages."""
    items = positions.load()
    open_bist = [p for p in items if p["durum"] == "acik" and p.get("piyasa") == "BIST"]
    if not open_bist:
        return []
    messages, done_symbols = [], {}
    async with httpx.AsyncClient() as client:
        for sym in {p["symbol"] for p in open_bist}:
            try:
                done_symbols[sym] = (await events(client, sym))["bolunmeler"]
            except Exception as e:
                log.warning("Corporate events failed for %s: %s", sym, e)
    now_ms = time.time() * 1000
    for p in open_bist:
        for s in done_symbols.get(p["symbol"], []):
            key = s["tarih"]
            if s["ms"] > now_ms or s["ms"] <= _opened_ms(p) or key in p.get("bolunmeler", []):
                continue
            before = f"{p['adet']:g} adet @ {p['giris']:g}"
            p.update(split_changes(p, s))
            p.setdefault("bolunmeler", []).append(key)
            messages.append(
                f"✂️ {bist.ticker(p['symbol'])} bölünme/bedelsiz ({s['metin']}, {s['tarih']}): pozisyon #{p['id']} "
                f"{before} → {p['adet']:g} adet @ {p['giris']:.4g}"
                + (f", stop {p['stop']:.4g}" if p.get("stop") is not None else "")
                + (f", hedef {p['hedef']:.4g}" if p.get("hedef") is not None else "")
                + ".\nFiyattaki düşüş bundan: SAT sinyali değil. Adedi aracı kurumdaki adetle karşılaştır; "
                  f"farklıysa /duzelt {p['id']} adet=N")
            _rescale_alarms_and_plans(p["symbol"], s)
    if messages:
        positions.save(items)
    return messages


def _rescale_alarms_and_plans(symbol: str, split: dict):
    r = split["oran"]
    tag = f"bolunme {split['tarih']}"
    alerts = alerts_store.load_alerts()
    for pair, lst in alerts.items():
        if bist.yahoo_symbol(pair) != bist.yahoo_symbol(symbol):
            continue
        for a in lst:
            if a["durum"] in alerts_store.ACTIVE_STATES and tag not in a.get("duzeltmeler", []):
                for k in ("tetik", "iptal", "hedef"):
                    if a.get(k) is not None:
                        a[k] = a[k] / r
                a.setdefault("duzeltmeler", []).append(tag)
    alerts_store.save_alerts(alerts)
    state = store.load_state()
    plan = state["planlar"].get(bist.yahoo_symbol(symbol))
    if plan and tag not in plan.get("duzeltmeler", []):
        for k in ("tetik", "teyit", "iptal", "hedef"):
            if plan.get(k) is not None:
                plan[k] = plan[k] / r
        plan.setdefault("duzeltmeler", []).append(tag)
        store.save_state(state)


def dividends_received(pos: dict, ev: dict) -> list[dict]:
    """Dividends whose ex-date fell while the position was held (gross, per current adet)."""
    start = _opened_ms(pos)
    end = int(datetime.fromisoformat(pos["kapanis_zamani"]).timestamp() * 1000) if pos.get("kapanis_zamani") else None
    return [{**d, "toplam": d["tutar"] * pos["adet"]} for d in ev["temettuler"]
            if d["ms"] > start and (end is None or d["ms"] <= end) and d["ms"] <= time.time() * 1000]


def dividend_outlook(ev: dict, price: float | None, today: date | None = None) -> dict:
    """Trailing 12-month dividends, yield, and last year's dates in the coming 4 months as a hint."""
    today = today or datetime.now(TR).date()
    year_ago = (today - timedelta(days=365)).isoformat()
    last12 = [d for d in ev["temettuler"] if d["tarih"] > year_ago]
    total = sum(d["tutar"] for d in last12)
    hint = [d for d in ev["temettuler"]
            if (today - timedelta(days=365)).isoformat() < d["tarih"] <= (today - timedelta(days=245)).isoformat()]
    return {"son12ay": last12, "son12ay_toplam": round(total, 4),
            "verim_yuzde": round(total / price * 100, 2) if price and total else None,
            "gecen_yil_ayni_donem": [{"tarih": d["tarih"], "tutar": d["tutar"],
                                      "tahmini": (date.fromisoformat(d["tarih"]) + timedelta(days=365)).isoformat()}
                                     for d in hint]}


async def new_dividend_notices() -> list[str]:
    """One message per dividend that went ex for a held position since the last check."""
    items = positions.load()
    open_bist = [p for p in items if p["durum"] == "acik" and p.get("piyasa") == "BIST"]
    msgs = []
    async with httpx.AsyncClient() as client:
        for p in open_bist:
            try:
                ev = await events(client, p["symbol"])
            except Exception as e:
                log.warning("Dividend check failed for %s: %s", p["symbol"], e)
                continue
            for d in dividends_received(p, ev):
                if d["tarih"] in p.get("temettuler", []):
                    continue
                p.setdefault("temettuler", []).append(d["tarih"])
                msgs.append(f"💰 {bist.ticker(p['symbol'])} temettü ({d['tarih']}): hisse başı {d['tutar']:.4g} TL × "
                            f"{p['adet']:g} adet = {d['toplam']:,.2f} TL brüt (stopaj öncesi), pozisyon #{p['id']}.\n"
                            "Hak kullanım günü fiyat temettü kadar düşük açılır: bu düşüş SAT sinyali değil.")
    if msgs:
        positions.save(items)
    return msgs


# --- dollar and inflation based return ------------------------------------------------------------

async def usdtry_series(client: httpx.AsyncClient) -> dict[str, float]:
    """Daily USD/TRY closes by ISO date (2 years), plus today's live rate under "son"."""
    df = await bist.fetch(client, bist.FX, "1d")
    out = {datetime.fromtimestamp(int(t) / 1000, TR).date().isoformat(): float(c)
           for t, c in zip(df.open_time, df.close)}
    try:
        out["son"] = await bist.last_price(client, bist.FX)
    except Exception:
        out["son"] = float(df.close.iloc[-1]) if not df.empty else None
    return out


def rate_on(series: dict[str, float], day: str) -> float | None:
    """Last close on or before `day`."""
    days = [d for d in series if d != "son" and d <= day]
    return series[max(days)] if days else None


async def cpi_series(client: httpx.AsyncClient) -> dict[str, float] | None:
    """Monthly TÜFE index {"2026-08": value} from EVDS, cached for a day. None without EVDS_API_KEY."""
    key = getattr(config, "EVDS_API_KEY", "")
    if not key:
        return None
    try:
        cached = json.loads(CPI_FILE.read_text(encoding="utf-8"))
        if time.time() - cached["zaman"] < CPI_TTL:
            return cached["seri"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        cached = None
    code = config.EVDS_CPI_SERIES
    start = (datetime.now(TR) - timedelta(days=3 * 365)).strftime("01-%m-%Y")
    end = datetime.now(TR).strftime("%d-%m-%Y")
    try:
        r = await client.get(f"{EVDS_URL}series={code}&startDate={start}&endDate={end}&type=json",
                             headers={"key": key}, timeout=20)
        r.raise_for_status()
        field = code.replace(".", "_")
        seri = {}
        for row in r.json().get("items", []):
            y, m = str(row.get("Tarih", "")).split("-")[:2]
            if row.get(field) not in (None, ""):
                seri[f"{int(y):04d}-{int(m):02d}"] = float(row[field])
        if not seri:
            raise ValueError(f"{code} boş döndü")
        CPI_FILE.write_text(json.dumps({"zaman": time.time(), "seri": seri}), encoding="utf-8")
        return seri
    except Exception as e:
        log.warning("EVDS CPI fetch failed: %s", e)
        return cached["seri"] if cached else None


def inflation_since(cpi: dict[str, float] | None, opened: str) -> tuple[float | None, str | None]:
    """Cumulative TÜFE change from the opening month to the latest published month (fraction)."""
    if not cpi:
        return None, None
    month = opened[:7]
    last = max(cpi)
    base = cpi.get(month) or cpi.get(max((m for m in cpi if m <= month), default=""), None)
    if base is None or month > last:
        return 0.0, last  # opened after the last published month: no measured inflation yet
    return cpi[last] / base - 1, last


def real_returns(pos_rows: list[dict], fx: dict[str, float] | None, cpi: dict[str, float] | None) -> dict:
    """pos_rows: [{acilis, maliyet (cost in own currency), deger (value now), para}] for one asset or market.
    Returns TL, USD and inflation-adjusted returns (percent) for the group."""
    cost_tl = cost_usd = value_tl = value_usd = real_cost_tl = 0.0
    fx_now = (fx or {}).get("son")
    ok_fx, ok_cpi = bool(fx and fx_now), cpi is not None
    last_month = None
    for r in pos_rows:
        day = r["acilis"][:10]
        fx_then = rate_on(fx, day) if fx else None
        if fx_then is None:
            ok_fx = False
        if r["para"] == "TL":
            ctl, vtl = r["maliyet"], r["deger"]
            cusd, vusd = (ctl / fx_then if fx_then else 0), (vtl / fx_now if fx_now else 0)
        else:
            cusd, vusd = r["maliyet"], r["deger"]
            ctl, vtl = (cusd * fx_then if fx_then else 0), (vusd * fx_now if fx_now else 0)
        infl, last_month = inflation_since(cpi, day)
        if infl is None:
            ok_cpi = False
        cost_tl, cost_usd, value_tl, value_usd = cost_tl + ctl, cost_usd + cusd, value_tl + vtl, value_usd + vusd
        real_cost_tl += ctl * (1 + (infl or 0))
    pct = lambda v, c: round((v / c - 1) * 100, 2) if c else None
    return {"tl_yuzde": pct(value_tl, cost_tl) if ok_fx else None,
            "usd_yuzde": pct(value_usd, cost_usd) if ok_fx else None,
            "reel_yuzde": pct(value_tl, real_cost_tl) if ok_fx and ok_cpi else None,
            "tufe_son_ay": last_month}

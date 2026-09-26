"""Macro layer: FRED (liquidity, dollar, rates, credit, VIX, release calendar),
BLS (CPI, payrolls, unemployment, wages), CFTC (CME bitcoin/ether positioning).

Everything numeric is computed here in code. The LLM only gets the digested summary.
"""
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

import config

log = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")
TR = ZoneInfo("Europe/Istanbul")

FRED_URL = "https://api.stlouisfed.org/fred"
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
CFTC_TFF_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"

FRED_SERIES = {
    "WALCL": "Fed bilançosu",
    "WTREGEN": "Hazine hesabı (TGA)",
    "RRPONTSYD": "Ters repo (RRP)",
    "DTWEXBGS": "Geniş dolar endeksi",
    "DGS2": "ABD 2Y faiz",
    "DGS10": "ABD 10Y faiz",
    "T10Y2Y": "10Y-2Y eğri",
    "DFII10": "10Y reel faiz",
    "BAMLH0A0HYM2": "HY kredi spreadi",
    "VIXCLS": "VIX",
    "DFEDTARU": "Fed faiz üst bandı",
}

BLS_SERIES = {
    "CUUR0000SA0": "cpi_nsa",
    "CUUR0000SA0L1E": "core_nsa",
    "CUSR0000SA0": "cpi_sa",
    "CUSR0000SA0L1E": "core_sa",
    "CES0000000001": "nfp",
    "LNS14000000": "issizlik",
    "CES0500000003": "saatlik_ucret",
}

CFTC_MARKETS = {"BTC": "133741", "ETH": "146021"}

# FRED release name -> (short label, release time in New York). Matched by name at runtime.
RELEASES = {
    "Consumer Price Index": ("CPI", "08:30"),
    "Employment Situation": ("NFP (tarım dışı istihdam)", "08:30"),
    "Personal Income and Outlays": ("PCE", "08:30"),
    "Producer Price Index": ("PPI", "08:30"),
    "Gross Domestic Product": ("GDP", "08:30"),
    "Job Openings and Labor Turnover Survey": ("JOLTS", "10:00"),
}
BLS_RELEASES = {"CPI", "NFP (tarım dışı istihdam)"}

# FOMC decision days (second day of each meeting), 14:00 New York. Source: federalreserve.gov
FOMC_DATES = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29",
              "2026-09-16", "2026-10-28", "2026-12-09",
              "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28",
              "2027-09-15", "2027-10-27", "2027-12-08"]

TTL = {"fred": 3 * 3600, "bls": 6 * 3600, "cftc": 6 * 3600, "takvim": 12 * 3600}


# --- cache -------------------------------------------------------------------

def _load_cache() -> dict:
    try:
        return json.loads(config.MACRO_CACHE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict):
    tmp = config.MACRO_CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, config.MACRO_CACHE_FILE)


# Sources whose last refresh failed and are being served from an expired cache entry.
_stale: set[str] = set()


def stale_sources() -> list[str]:
    return sorted(_stale)


async def _cached(name: str, fetch, force: bool = False):
    cache = _load_cache()
    entry = cache.get(name)
    if not force and entry and time.time() - entry["ts"] < TTL[name]:
        return entry["data"]
    try:
        data = await fetch()
    except Exception as e:
        log.warning("Macro source %s failed: %s", name, e)
        _stale.add(name)
        # Old data is still shown, but callers that gate decisions see it as not current.
        return entry["data"] if entry else {"hata": str(e)}
    _stale.discard(name)
    cache = _load_cache()
    cache[name] = {"ts": time.time(), "data": data}
    _save_cache(cache)
    return data


def _r(x, n=2):
    return None if x is None else round(x, n)


# --- FRED --------------------------------------------------------------------

async def _fred_get(client, path: str, **params) -> dict:
    params |= {"api_key": config.FRED_API_KEY, "file_type": "json"}
    r = await client.get(f"{FRED_URL}/{path}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


async def _fred_series(client, series_id: str) -> list[tuple[date, float]]:
    start = (date.today() - timedelta(days=400)).isoformat()
    data = await _fred_get(client, "series/observations", series_id=series_id, observation_start=start)
    return [(date.fromisoformat(o["date"]), float(o["value"]))
            for o in data["observations"] if o["value"] not in (".", "")]


async def _fred_units_to_millions(client, series_id: str) -> float:
    units = (await _fred_get(client, "series", series_id=series_id))["seriess"][0]["units"].lower()
    if "trillion" in units:
        return 1e6
    if "billion" in units:
        return 1e3
    return 1.0


def _value_days_ago(obs: list[tuple[date, float]], days: int) -> float | None:
    target = obs[-1][0] - timedelta(days=days)
    older = [v for d, v in obs if d <= target]
    return older[-1] if older else None


def _pct_change(obs, days):
    old = _value_days_ago(obs, days)
    return (obs[-1][1] / old - 1) * 100 if old else None


def _diff(obs, days):
    old = _value_days_ago(obs, days)
    return obs[-1][1] - old if old is not None else None


def _percentile(values: list[float], x: float) -> float:
    return sum(v <= x for v in values) / len(values) * 100


async def fetch_fred() -> dict:
    if not config.FRED_API_KEY:
        return {"hata": "FRED_API_KEY yok"}
    async with httpx.AsyncClient() as client:
        obs = {sid: await _fred_series(client, sid) for sid in FRED_SERIES}

        # Net liquidity = Fed balance sheet - TGA - RRP, all in USD billions, weekly (Wednesday) grid.
        scale = {sid: await _fred_units_to_millions(client, sid) for sid in ("WALCL", "WTREGEN", "RRPONTSYD")}

    def at(sid, d):
        older = [v for od, v in obs[sid] if od <= d]
        return older[-1] * scale[sid] / 1e3 if older else None

    liq = []
    for d, _ in obs["WALCL"]:
        parts = [at(s, d) for s in ("WALCL", "WTREGEN", "RRPONTSYD")]
        if None not in parts:
            liq.append((d, parts[0] - parts[1] - parts[2]))

    out = {"net_likidite_milyar_usd": {
        "son": _r(liq[-1][1], 0), "tarih": liq[-1][0].isoformat(),
        "4h_degisim_yuzde": _r(_pct_change(liq, 28)), "13h_degisim_yuzde": _r(_pct_change(liq, 91)),
    }} if liq else {}

    for sid, label in FRED_SERIES.items():
        if sid in ("WALCL", "WTREGEN", "RRPONTSYD") or not obs[sid]:
            continue
        o = obs[sid]
        item = {"ad": label, "son": _r(o[-1][1], 3), "tarih": o[-1][0].isoformat()}
        if sid == "DTWEXBGS":
            item["4h_degisim_yuzde"] = _r(_pct_change(o, 28))
        else:
            item["4h_degisim"] = _r(_diff(o, 28), 3)
        if sid == "VIXCLS":
            item["1y_yuzdelik"] = _r(_percentile([v for _, v in o[-252:]], o[-1][1]), 0)
        out[sid] = item
    return out


def regime(fred: dict) -> dict:
    """Deterministic risk-on / risk-off score from -5 to +5. Describes the wind, not a forecast."""
    comps = {}

    def score(name, value, pos_if, neg_if):
        if value is None:
            return
        comps[name] = 1 if pos_if(value) else -1 if neg_if(value) else 0

    score("likidite", fred.get("net_likidite_milyar_usd", {}).get("4h_degisim_yuzde"),
          lambda v: v > 1, lambda v: v < -1)
    score("dolar", fred.get("DTWEXBGS", {}).get("4h_degisim_yuzde"),
          lambda v: v < -1, lambda v: v > 1)
    score("kredi_spreadi", fred.get("BAMLH0A0HYM2", {}).get("4h_degisim"),
          lambda v: v < -0.15, lambda v: v > 0.15)
    score("vix", fred.get("VIXCLS", {}).get("son"),
          lambda v: v < 16, lambda v: v > 25)
    score("reel_faiz", fred.get("DFII10", {}).get("4h_degisim"),
          lambda v: v < -0.15, lambda v: v > 0.15)

    total = sum(comps.values())
    label = "RİSK-ON (makro rüzgar arkada)" if total >= 2 else \
            "RİSK-OFF (makro rüzgar karşıda)" if total <= -2 else "NÖTR"
    return {"skor": total, "etiket": label, "bilesenler": comps, "bilesen_sayisi": len(comps)}


# --- BLS ---------------------------------------------------------------------

async def fetch_bls() -> dict:
    year = date.today().year
    body = {"seriesid": list(BLS_SERIES), "startyear": str(year - 2), "endyear": str(year)}
    if config.BLS_API_KEY:
        body["registrationkey"] = config.BLS_API_KEY
    async with httpx.AsyncClient() as client:
        r = await client.post(BLS_URL, json=body, timeout=30)
        r.raise_for_status()
        payload = r.json()
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS: {payload.get('message')}")

    s = {}
    for series in payload["Results"]["series"]:
        # Monthly points keyed by (year, month). Missing months (e.g. Oct 2025 shutdown) stay missing.
        s[BLS_SERIES[series["seriesID"]]] = {
            (int(p["year"]), int(p["period"][1:])): float(p["value"])
            for p in series["data"] if p["period"].startswith("M") and p["period"] != "M13"
            and p["value"] not in ("-", "")
        }

    def latest(key):
        return max(s[key]) if s.get(key) else None

    def shift(ym, months):
        y, m = ym
        m -= months
        while m <= 0:
            m += 12
            y -= 1
        return (y, m)

    def yoy(key, ym):
        cur, old = s[key].get(ym), s[key].get(shift(ym, 12))
        return (cur / old - 1) * 100 if cur and old else None

    def mom(key, ym):
        cur, old = s[key].get(ym), s[key].get(shift(ym, 1))
        return (cur / old - 1) * 100 if cur and old else None

    def ann3(key, ym):
        cur, old = s[key].get(ym), s[key].get(shift(ym, 3))
        return ((cur / old) ** 4 - 1) * 100 if cur and old else None

    out = {}
    ym = latest("cpi_nsa")
    if ym:
        out["enflasyon"] = {
            "donem": f"{ym[0]}-{ym[1]:02d}",
            "cpi_yillik": _r(yoy("cpi_nsa", ym)), "core_yillik": _r(yoy("core_nsa", ym)),
            "cpi_aylik": _r(mom("cpi_sa", ym)), "core_aylik": _r(mom("core_sa", ym)),
            "core_3ay_yilliklandirilmis": _r(ann3("core_sa", ym)),
            "core_aylik_son3": [_r(mom("core_sa", shift(ym, i))) for i in range(3)],
        }
        c3, cy = out["enflasyon"]["core_3ay_yilliklandirilmis"], out["enflasyon"]["core_yillik"]
        if c3 is not None and cy is not None:
            out["enflasyon"]["trend"] = "soğuyor" if c3 < cy - 0.2 else "ısınıyor" if c3 > cy + 0.2 else "yatay"

    ym = latest("nfp")
    if ym:
        def nfp_change(i):
            cur, old = s["nfp"].get(shift(ym, i)), s["nfp"].get(shift(ym, i + 1))
            return cur - old if cur is not None and old is not None else None

        changes = [nfp_change(i) for i in range(3)]
        out["istihdam"] = {
            "donem": f"{ym[0]}-{ym[1]:02d}",
            "nfp_degisim_bin_son3": [_r(c, 0) for c in changes],
            "issizlik": s["issizlik"].get(ym),
            "issizlik_3ay_once": s["issizlik"].get(shift(ym, 3)),
            "saatlik_ucret_yillik": _r(yoy("saatlik_ucret", ym)),
        }
    return out


# --- CFTC --------------------------------------------------------------------

async def fetch_cftc() -> dict:
    headers = {"X-App-Token": config.CFTC_APP_TOKEN} if config.CFTC_APP_TOKEN else {}
    out = {}
    async with httpx.AsyncClient() as client:
        for coin, code in CFTC_MARKETS.items():
            r = await client.get(CFTC_TFF_URL, headers=headers, timeout=30, params={
                "cftc_contract_market_code": code,
                "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": 52})
            r.raise_for_status()
            rows = r.json()
            if not rows:
                continue

            def net(row, group):
                return int(row[f"{group}_positions_long{'_all' if group == 'dealer' else ''}"]) - \
                       int(row[f"{group}_positions_short{'_all' if group == 'dealer' else ''}"])

            last, prev = rows[0], rows[1] if len(rows) > 1 else rows[0]
            lev_hist = [net(x, "lev_money") for x in rows]
            am_hist = [net(x, "asset_mgr") for x in rows]
            out[coin] = {
                "rapor_tarihi": last["report_date_as_yyyy_mm_dd"][:10],
                "kontrat": last["market_and_exchange_names"],
                "acik_pozisyon": int(last["open_interest_all"]),
                "acik_pozisyon_haftalik_degisim": int(last["change_in_open_interest_all"]),
                "kaldiracli_fon_net": lev_hist[0],
                "kaldiracli_fon_net_haftalik_degisim": lev_hist[0] - net(prev, "lev_money"),
                "kaldiracli_fon_net_52h_yuzdelik": _r(_percentile(lev_hist, lev_hist[0]), 0),
                "varlik_yoneticisi_net": am_hist[0],
                "varlik_yoneticisi_net_haftalik_degisim": am_hist[0] - net(prev, "asset_mgr"),
                "varlik_yoneticisi_net_52h_yuzdelik": _r(_percentile(am_hist, am_hist[0]), 0),
                "dealer_net": net(last, "dealer"),
            }
    return out


# --- calendar ----------------------------------------------------------------

def _tr_time(day: str, ny_time: str) -> str:
    h, m = map(int, ny_time.split(":"))
    ny = datetime.fromisoformat(day).replace(hour=h, minute=m, tzinfo=NY)
    return ny.astimezone(TR).isoformat()


async def fetch_calendar() -> list[dict]:
    today = date.today().isoformat()
    events = [{"olay": "FOMC faiz kararı", "tr_zaman": _tr_time(d, "14:00")}
              for d in FOMC_DATES if d >= today]
    if config.FRED_API_KEY:
        async with httpx.AsyncClient() as client:
            releases = (await _fred_get(client, "releases", limit=1000))["releases"]
            ids = {r["name"]: r["id"] for r in releases if r["name"] in RELEASES}
            for name, rid in ids.items():
                label, ny_time = RELEASES[name]
                data = await _fred_get(client, "release/dates", release_id=rid, realtime_start=today,
                                       include_release_dates_with_no_data="true", limit=10)
                events += [{"olay": label, "tr_zaman": _tr_time(d["date"], ny_time)}
                           for d in data["release_dates"] if d["date"] >= today]
    events.sort(key=lambda e: e["tr_zaman"])
    return events[:40]


def upcoming(events: list[dict], hours: float) -> list[dict]:
    now = datetime.now(TR)
    out = []
    for e in events:
        t = datetime.fromisoformat(e["tr_zaman"])
        delta = (t - now).total_seconds() / 3600
        if -1 <= delta <= hours:
            out.append({**e, "kalan_saat": round(delta, 1)})
    return out


# --- public API --------------------------------------------------------------

async def summary(force: bool = False) -> dict:
    fred = await _cached("fred", fetch_fred, force)
    bls = await _cached("bls", fetch_bls, force)
    cftc = await _cached("cftc", fetch_cftc, force)
    events = await calendar(force)
    return {
        "rejim": regime(fred) if "hata" not in fred else {"hata": fred["hata"]},
        "fred": fred,
        "bls": bls,
        "cftc_cme": cftc,
        "olay_riski_48s": upcoming(events, 48),
        # Sources that failed to refresh and are served from an expired cache: not current.
        "guncel_degil": stale_sources(),
        "zaman_tr": datetime.now(TR).strftime("%Y-%m-%d %H:%M"),
    }


async def refresh_bls() -> dict:
    return await _cached("bls", fetch_bls, force=True)


async def calendar(force: bool = False, strict: bool = False) -> list[dict]:
    """Upcoming events. strict=True raises instead of returning [] when the calendar failed,
    so callers that gate entries can't mistake "unknown" for "no events"."""
    cal = await _cached("takvim", fetch_calendar, force)
    if isinstance(cal, list) and not (strict and "takvim" in _stale):
        return cal
    if strict and "takvim" in _stale:
        raise RuntimeError("calendar refresh failed; cached copy is expired")
    if strict:
        raise RuntimeError(f"calendar unavailable: {cal.get('hata') if isinstance(cal, dict) else cal}")
    return []


def _fmt_list(xs):
    return ", ".join("?" if x is None else f"{x:g}" for x in xs)


def dashboard(m: dict) -> str:
    """Plain-text Telegram dashboard, no LLM involved."""
    lines = []
    rj = m["rejim"]
    if "hata" in rj:
        lines.append(f"REJİM: hesaplanamadı ({rj['hata']})")
    else:
        comps = " ".join(f"{k}{'+' if v > 0 else '-' if v < 0 else '0'}" for k, v in rj["bilesenler"].items())
        lines.append(f"REJİM: {rj['etiket']}  skor {rj['skor']:+d}/{rj['bilesen_sayisi']}\n  {comps}")

    f = m["fred"]
    if "hata" not in f:
        liq = f.get("net_likidite_milyar_usd")
        if liq:
            lines.append(f"\nNet likidite: {liq['son']:,.0f} mlr $ (4h {liq['4h_degisim_yuzde']:+}%, 13h {liq['13h_degisim_yuzde']:+}%)")
        for sid in ("DTWEXBGS", "DGS2", "DGS10", "T10Y2Y", "DFII10", "BAMLH0A0HYM2", "VIXCLS", "DFEDTARU"):
            it = f.get(sid)
            if not it:
                continue
            chg = it.get("4h_degisim_yuzde")
            chg_txt = f"4h {chg:+}%" if chg is not None else \
                f"4h {it['4h_degisim']:+}" if it.get("4h_degisim") is not None else ""
            lines.append(f"{it['ad']}: {it['son']:g} {chg_txt}")

    b = m["bls"]
    if "enflasyon" in b:
        e = b["enflasyon"]
        lines.append(f"\nCPI ({e['donem']}): yıllık {e['cpi_yillik']}%, core {e['core_yillik']}% | "
                     f"core aylık son3: {_fmt_list(e['core_aylik_son3'])} | 3a yıllık {e['core_3ay_yilliklandirilmis']}% → {e.get('trend', '?')}")
    if "istihdam" in b:
        i = b["istihdam"]
        lines.append(f"İstihdam ({i['donem']}): NFP son3 (bin): {_fmt_list(i['nfp_degisim_bin_son3'])} | "
                     f"işsizlik {i['issizlik']}% (3a önce {i['issizlik_3ay_once']}%) | ücret yıllık {i['saatlik_ucret_yillik']}%")
    if "hata" in b:
        lines.append(f"\nBLS: {b['hata']}")

    for coin, c in (m["cftc_cme"] or {}).items():
        if coin == "hata":
            lines.append(f"\nCFTC: {c}")
            continue
        lines.append(f"\nCOT {coin} CME ({c['rapor_tarihi']}): OI {c['acik_pozisyon']:,} ({c['acik_pozisyon_haftalik_degisim']:+,})\n"
                     f"  kaldıraçlı fon net {c['kaldiracli_fon_net']:+,} ({c['kaldiracli_fon_net_haftalik_degisim']:+,}), 52h yüzdelik {c['kaldiracli_fon_net_52h_yuzdelik']:g}\n"
                     f"  varlık yöneticisi net {c['varlik_yoneticisi_net']:+,} ({c['varlik_yoneticisi_net_haftalik_degisim']:+,}), 52h yüzdelik {c['varlik_yoneticisi_net_52h_yuzdelik']:g}")

    ev = m["olay_riski_48s"]
    lines.append("\nOLAY RİSKİ (48 saat): " + ("yok" if not ev else ""))
    for e in ev:
        t = datetime.fromisoformat(e["tr_zaman"]).strftime("%d.%m %H:%M")
        lines.append(f"  {t} TR  {e['olay']}  ({e['kalan_saat']:+g} saat)")
    return "\n".join(lines)


def calendar_text(events: list[dict], days: int = 14) -> str:
    items = upcoming(events, days * 24)
    if not items:
        return "Önümüzdeki günlerde takvimde önemli veri yok."
    return "\n".join(f"{datetime.fromisoformat(e['tr_zaman']).strftime('%a %d.%m %H:%M')} TR  {e['olay']}"
                     for e in items)

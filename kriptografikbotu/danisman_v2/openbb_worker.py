"""OpenBB reader: runs in a Python that has `openbb` installed and prints one JSON object. Nothing else imports it.

    <openbb python> openbb_worker.py calendar|macro|cross_asset|health
    <openbb python> openbb_worker.py serve [port]      the same sections over HTTP (GET /calendar ...), for a worker
                                                       container next to the site; standard library only

OpenBB needs a newer FastAPI than the site's backend, so it lives in its own virtual environment and is called as a
separate process (see macro.py). Every field carries its source; a call that fails is listed under "unavailable"
with the reason. Nothing is made up when a provider gives nothing. Written for OpenBB 5 (provider-first routers:
obb.nasdaq, obb.federal_reserve, obb.oecd, obb.bls, obb.cboe).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import warnings

warnings.filterwarnings("ignore")


def _rows(result) -> list[dict]:
    rows = result.results if hasattr(result, "results") else result
    return [r.model_dump() if hasattr(r, "model_dump") else dict(r) for r in (rows or [])]


def _try(out: dict, key: str, source: str, fn):
    """Run one provider call; record the value with its source, or why it is unavailable."""
    try:
        value = fn()
        if value in (None, [], {}):
            raise ValueError("boş cevap")
        out["data"][key] = value
        out["sources"].append({"field": key, "source": source})
    except Exception as e:      # one provider failing must not take the others down
        out["unavailable"].append({"field": key, "source": source, "reason": f"{type(e).__name__}: {str(e)[:160]}"})


def _last(rows: list[dict], *fields: str, scale: float = 1.0) -> dict | None:
    """The newest row's fields, in percent. scale=100 for providers that report a fraction (0.0529 -> 5.29)."""
    rows = [r for r in rows if any(r.get(f) is not None for f in fields)]
    if not rows:
        return None
    r = max(rows, key=lambda x: str(x.get("date")))
    return {"date": str(r.get("date"))[:10], "unit": "percent",
            **{f: None if r.get(f) is None else round(r[f] * scale, 3) for f in fields}}


def _change(rows: list[dict], field: str = "close") -> dict | None:
    """Last value and its change from the previous row and from the first row of the window."""
    rows = sorted((r for r in rows if r.get(field) is not None), key=lambda x: str(x.get("date")))
    if len(rows) < 2:
        return None
    last, prev, first = rows[-1][field], rows[-2][field], rows[0][field]
    return {"date": str(rows[-1].get("date"))[:10], "last": last, "change_1d_pct": round((last / prev - 1) * 100, 2),
            "change_window_pct": round((last / first - 1) * 100, 2), "window_days": len(rows)}


def calendar(obb) -> dict:
    """Economic events from now on (UTC). No provider says how important an event is: `importance` stays empty."""
    out = {"data": {}, "sources": [], "unavailable": []}
    today = dt.datetime.now(dt.timezone.utc).date()
    span = dict(start_date=today.isoformat(), end_date=(today + dt.timedelta(days=7)).isoformat())

    def nasdaq():
        rows = _rows(obb.nasdaq.economy.calendar(**span))
        return [{"time": str(r.get("date")), "timezone": "America/New_York", "country": r.get("country"), "event": r.get("event"),
                 "importance": r.get("importance"), "consensus": r.get("consensus"), "previous": r.get("previous"),
                 "actual": r.get("actual"), "source": "OpenBB · Nasdaq economic calendar"} for r in rows]

    def bls():
        rows = _rows(obb.bls.calendar(start_date=today.isoformat(), end_date=(today + dt.timedelta(days=30)).isoformat()))
        return [{"time": str(r.get("date")), "timezone": "America/New_York", "country": "United States", "event": r.get("event"),
                 "importance": r.get("importance"), "period": r.get("period"), "source": "OpenBB · BLS release calendar"}
                for r in rows]

    def fed():
        rows = _rows(obb.federal_reserve.release_calendar(start_date=today.isoformat(),
                                                          end_date=(today + dt.timedelta(days=14)).isoformat()))
        return [{"time": f"{r.get('date')} {r.get('time') or ''}".strip(), "timezone": "America/New_York",
                 "country": "United States", "event": r.get("title"), "importance": None, "event_type": r.get("event_type"),
                 "source": "OpenBB · Federal Reserve release calendar"} for r in rows]

    _try(out, "economic_calendar", "OpenBB · Nasdaq economic calendar", nasdaq)
    _try(out, "bls_release_calendar", "OpenBB · BLS release calendar", bls)
    _try(out, "fed_release_calendar", "OpenBB · Federal Reserve release calendar", fed)
    return out


def macro(obb) -> dict:
    """Rates, inflation, employment: slow series, read at most every half hour."""
    out = {"data": {}, "sources": [], "unavailable": []}
    today = dt.date.today()
    ago = lambda n: (today - dt.timedelta(days=n)).isoformat()
    _try(out, "treasury_rates", "OpenBB · Federal Reserve H.15",
         lambda: _last(_rows(obb.federal_reserve.treasury_rates(start_date=ago(14))), "month_3", "year_2", "year_10", "year_30", scale=100))
    _try(out, "effective_fed_funds_rate", "OpenBB · New York Fed EFFR",
         lambda: _last(_rows(obb.federal_reserve.ny.effr())[-10:], "rate", "target_range_lower", "target_range_upper", scale=100))
    _try(out, "policy_rate_oecd", "OpenBB · OECD short-term interest rate",
         lambda: _last(_rows(obb.oecd.country_interest_rates(country="united_states", start_date=ago(500))), "value", scale=100))
    _try(out, "cpi_yoy", "OpenBB · OECD CPI (year over year)",
         lambda: _last(_rows(obb.oecd.cpi(country="united_states", start_date=ago(500))), "value", scale=100))
    _try(out, "inflation_expectations", "OpenBB · Federal Reserve inflation expectations",
         lambda: _last(_rows(obb.federal_reserve.inflation_expectations())[-8:], "infcpi1yr", "infcpi10yr"))
    _try(out, "unemployment_rate", "OpenBB · OECD unemployment rate",
         lambda: _last(_rows(obb.oecd.unemployment(country="united_states", start_date=ago(500))), "value", scale=100))
    _try(out, "unemployment_rate_bls", "OpenBB · BLS employment situation",
         lambda: _last(_rows(obb.bls.employment_situation.civilian_unemployment_rate())[-6:], "total"))
    return out


def cross_asset(obb) -> dict:
    """US equity indices and volatility: daily closes (not intraday; the crypto candles come from Binance)."""
    out = {"data": {}, "sources": [], "unavailable": []}
    start = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    _try(out, "sp500", "OpenBB · Cboe index (SPX)", lambda: _change(_rows(obb.cboe.index.historical("SPX", start_date=start))))
    _try(out, "vix", "OpenBB · Cboe index (VIX)", lambda: _change(_rows(obb.cboe.index.historical("VIX", start_date=start))))
    _try(out, "nasdaq100", "OpenBB · Nasdaq index (NDX)", lambda: _change(_rows(obb.nasdaq.index.historical("NDX", start_date=start))))
    _try(out, "us_market_status", "OpenBB · Nasdaq market status",
         lambda: {k: _rows(obb.nasdaq.markets.status())[0].get(k) for k in ("status", "indicator", "next_trade_date")})
    return out


def crypto_reference(obb) -> dict:
    """A second, daily BTC price to cross-check the exchange feed. Never used for a level."""
    out = {"data": {}, "sources": [], "unavailable": []}
    start = (dt.date.today() - dt.timedelta(days=10)).isoformat()
    _try(out, "btc_daily", "OpenBB · Nasdaq crypto (daily)", lambda: _change(_rows(obb.nasdaq.crypto.historical("BTC", start_date=start))))
    return out


SECTIONS = {"calendar": calendar, "macro": macro, "cross_asset": cross_asset, "crypto_reference": crypto_reference}


def collect(section: str) -> dict:
    """One section as a dict. Raises when OpenBB itself cannot be imported."""
    from openbb import obb
    if section == "health":
        return {"data": {"openbb": "ok", "routers": sorted(a for a in dir(obb) if not a.startswith("_"))[:60]},
                "sources": [], "unavailable": []}
    return SECTIONS[section](obb)


def serve(port: int) -> None:
    """A tiny HTTP front for a separate worker container: GET /<section> -> the section's JSON. Internal network only
    (no auth): it must never be published to the internet."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            name = self.path.strip("/").split("?")[0]
            if name not in SECTIONS and name != "health":
                self.send_response(404)
                self.end_headers()
                return
            try:
                body = collect(name)
            except Exception as e:
                body = {"error": f"{type(e).__name__}: {str(e)[:300]}"}
            raw = json.dumps(body, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):       # quiet: the caller logs what it needs
            pass

    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "health"
    if name == "serve":
        serve(int(sys.argv[2]) if len(sys.argv) > 2 else 8010)
        sys.exit(0)
    try:
        result = collect(name)
    except Exception as e:
        result = {"error": f"{type(e).__name__}: {str(e)[:300]}"}
    # the last line is the answer; OpenBB itself may print while it builds its package on the first import
    print("\n@@OPENBB@@" + json.dumps(result, default=str))

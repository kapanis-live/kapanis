"""OpenBB adapter and the MacroSnapshot. Macro is a risk filter for new entries; it is never a buy signal.

    Binance  -> crypto candles and prices (danisman.py). OpenBB never replaces it.
    OpenBB   -> economic calendar, rates, inflation, employment, US equity context.

OpenBB cannot be installed next to the site's backend (it needs a newer FastAPI), so it runs in its own Python:
OPENBB_PYTHON points at that interpreter and each read is a short-lived process (openbb_worker.py), or OPENBB_URL
points at a small worker service (`openbb_worker.py serve`) on the internal network. When both are empty and
`openbb` happens to be importable here, it is used in-process. With neither, or when a read fails,
macro_status is DEGRADED / UNAVAILABLE and the technical advisor carries on: nothing is invented to fill the gap.
Reads are cached (calendar 15 min, macro 30 min, cross-asset 5 min): a coin analysis never waits for a fresh read
when a recent one exists, and a failed refresh keeps the last value, marked stale.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from . import config as cfg

WORKER = pathlib.Path(__file__).with_name("openbb_worker.py")
MARK = "@@OPENBB@@"
TTL = {"calendar": "CALENDAR_CACHE_SECONDS", "macro": "MACRO_CACHE_SECONDS", "cross_asset": "CROSS_ASSET_CACHE_SECONDS",
       "crypto_reference": "CROSS_ASSET_CACHE_SECONDS", "health": "CROSS_ASSET_CACHE_SECONDS"}
HIGH_WORDS = ("high", "3")           # what a provider's own importance field would say; none of the free ones fill it


class OpenBBUnavailable(Exception):
    pass


def _event_time(text: str, zone: str) -> datetime | None:
    """A provider's local event time as UTC. None when it has no clock time (a date-only release)."""
    text = (text or "").strip()
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})(?::\d{2})?\s*([ap])?\.?m?\.?", text, re.IGNORECASE)
    if not m:
        return None
    hour = int(m.group(2))
    if m.group(4):
        hour = hour % 12 + (12 if m.group(4).lower() == "p" else 0)
    local = datetime.fromisoformat(m.group(1)).replace(hour=hour, minute=int(m.group(3)), tzinfo=ZoneInfo(zone))
    return local.astimezone(timezone.utc)


def classify_events(rows: list[dict], now: datetime) -> list[dict]:
    """Upcoming events of the configured countries, soonest first, each with `high_impact`:
    True / False when the provider rated it or the admin's keyword list decides, None when nobody says."""
    countries = {c.lower() for c in cfg.MACRO_COUNTRIES}
    words = [w.lower() for w in cfg.MACRO_HIGH_IMPACT_KEYWORDS]
    out, seen = [], set()
    for r in rows:
        when = _event_time(r.get("time"), r.get("timezone") or "UTC")
        if when is None or when < now - timedelta(minutes=5) or (r.get("country") or "").lower() not in countries:
            continue
        key = ((r.get("event") or "").lower(), when)
        if key in seen:
            continue
        seen.add(key)
        rated = r.get("importance")
        high = (str(rated).lower() in HIGH_WORDS) if rated not in (None, "") else \
            (any(w in key[0] for w in words) if words else None)
        out.append({"time_utc": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "minutes_from_now": int((when - now).total_seconds() // 60),
                    "country": r.get("country"), "event": r.get("event"), "consensus": r.get("consensus"),
                    "previous": r.get("previous"), "actual": r.get("actual"), "provider_importance": rated,
                    "high_impact": high, "impact_basis": "provider" if rated not in (None, "") else
                    "admin keyword list" if words else None, "source": r.get("source")})
    return sorted(out, key=lambda e: e["minutes_from_now"])


class OpenBBService:
    """All OpenBB reads go through here. runner: async section -> dict, instead of OpenBB (tests)."""

    def __init__(self, python: str | None = None, runner=None, url: str | None = None):
        self.python = python if python is not None else os.getenv("OPENBB_PYTHON", "")
        self.url = (url if url is not None else os.getenv("OPENBB_URL", "")).rstrip("/")   # a separate OpenBB worker service
        self.runner = runner
        self._cache: dict[str, tuple[float, dict]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def mode(self) -> str:
        if self.runner:
            return "injected"
        if self.url:
            return "http"
        if self.python:
            return "subprocess" if pathlib.Path(self.python).exists() else "missing_python"
        return "in_process" if importlib.util.find_spec("openbb") else "not_installed"

    def _run_process(self, section: str) -> dict:
        res = subprocess.run([self.python, str(WORKER), section], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=cfg.OPENBB_TIMEOUT_SECONDS,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        line = next((x for x in reversed(res.stdout.splitlines()) if x.startswith(MARK)), None)
        if line is None:
            raise OpenBBUnavailable(f"OpenBB süreci cevap vermedi (çıkış {res.returncode}): {res.stderr.strip()[-200:]}")
        return json.loads(line[len(MARK):])

    async def _read(self, section: str) -> dict:
        mode = self.mode()
        if mode == "injected":
            out = await self.runner(section)
        elif mode == "http":             # openbb_worker.py serve, on the internal network
            async with httpx.AsyncClient(timeout=cfg.OPENBB_TIMEOUT_SECONDS) as client:
                r = await client.get(f"{self.url}/{section}")
            if r.status_code != 200:
                raise OpenBBUnavailable(f"OpenBB servisi HTTP {r.status_code}")
            out = r.json()
        elif mode == "subprocess":
            out = await asyncio.to_thread(self._run_process, section)
        elif mode == "in_process":
            from . import openbb_worker
            out = await asyncio.to_thread(openbb_worker.collect, section)
        else:
            raise OpenBBUnavailable("OpenBB kurulu değil (OPENBB_PYTHON boş ve bu ortamda openbb yok)" if mode == "not_installed"
                                    else f"OPENBB_PYTHON bulunamadı: {self.python}")
        if "error" in out:
            raise OpenBBUnavailable(out["error"])
        return out

    async def section(self, name: str) -> dict:
        """{"data", "sources", "unavailable", "fetched_at", "stale", "error"}: cached, never raises."""
        ttl = getattr(cfg, TTL[name])
        hit = self._cache.get(name)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        async with self._locks.setdefault(name, asyncio.Lock()):
            hit = self._cache.get(name)
            if hit and time.monotonic() - hit[0] < ttl:
                return hit[1]
            try:
                out = await asyncio.wait_for(self._read(name), cfg.OPENBB_TIMEOUT_SECONDS + 5)
                value = {**out, "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "stale": False, "error": None}
                self._cache[name] = (time.monotonic(), value)
                return value
            except Exception as e:
                reason = str(e)[:240] or type(e).__name__
                if hit:      # keep what we had, say that it is old; try again after a short while, not on every call
                    value = {**hit[1], "stale": True, "error": reason}
                    self._cache[name] = (time.monotonic() - ttl + min(ttl, 60), value)
                    return value
                value = {"data": {}, "sources": [], "unavailable": [], "fetched_at": None, "stale": False, "error": reason}
                self._cache[name] = (time.monotonic() - ttl + min(ttl, 60), value)
                return value

    async def get_economic_calendar(self) -> dict:
        return await self.section("calendar")

    async def get_cross_asset_snapshot(self) -> dict:
        return await self.section("cross_asset")

    async def get_crypto_reference_data(self) -> dict:
        return await self.section("crypto_reference")

    async def healthcheck(self) -> dict:
        mode = self.mode()
        if mode in ("not_installed", "missing_python"):
            return {"status": "UNAVAILABLE", "mode": mode, "detail": "OpenBB kurulu değil; makro alanı DEGRADED çalışır"}
        got = await self.section("health")
        return {"status": "OK" if not got["error"] else "UNAVAILABLE", "mode": mode, "detail": got["error"],
                "routers": (got["data"] or {}).get("routers")}

    async def get_macro_snapshot(self, now: datetime | None = None) -> dict:
        """The MacroSnapshot. Sections are read together; each one that fails only empties its own fields."""
        now = now or datetime.now(timezone.utc)
        cal, mac, cross = await asyncio.gather(self.section("calendar"), self.section("macro"), self.section("cross_asset"))
        parts = {"calendar": cal, "macro": mac, "cross_asset": cross}
        rows = [e for key in ("economic_calendar", "bls_release_calendar", "fed_release_calendar") for e in (cal["data"].get(key) or [])]
        events = classify_events(rows, now)
        rated = [e for e in events if e["high_impact"] is not None]
        high = [e for e in events if e["high_impact"]]
        nxt = high[0] if high else None

        def within(minutes):
            return None if not rated else bool(nxt and nxt["minutes_from_now"] <= minutes)

        m, x = mac["data"], cross["data"]
        failed = [k for k, v in parts.items() if v["error"] and not v["data"]]
        partly = failed or any(v["error"] or v["unavailable"] for v in parts.values())
        status = "UNAVAILABLE" if len(failed) == len(parts) else "DEGRADED" if partly else "OK"
        ctx = []
        if x.get("vix"):
            ctx.append(f"VIX {x['vix']['last']:g} ({x['vix']['change_1d_pct']:+.2f}% günlük)")
        if x.get("sp500"):
            ctx.append(f"S&P 500 {x['sp500']['change_1d_pct']:+.2f}% günlük, {x['sp500']['change_window_pct']:+.2f}% son "
                       f"{x['sp500']['window_days']} işlem günü")
        if (m.get("treasury_rates") or {}).get("year_10") is not None:
            ctx.append(f"ABD 10Y %{m['treasury_rates']['year_10']:.2f}")
        snap = {
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "macro_status": status, "openbb_mode": self.mode(),
            "economic_events": events[:25],
            "high_impact_event_within_2h": within(120), "high_impact_event_within_6h": within(360),
            "next_high_impact_event": None if not nxt else f"{nxt['event']} ({nxt['minutes_from_now']} dk sonra)",
            "minutes_to_next_high_impact": None if not nxt else nxt["minutes_from_now"],
            "caution": bool(nxt and nxt["minutes_from_now"] <= cfg.MACRO_CAUTION_MINUTES),
            "block_new_entry": bool(nxt and cfg.MACRO_BLOCK_MINUTES and nxt["minutes_from_now"] <= cfg.MACRO_BLOCK_MINUTES),
            "impact_basis": ("sağlayıcı önem alanı / yönetici anahtar kelime listesi" if rated else
                             "bilinmiyor: takvim sağlayıcıları önem derecesi vermiyor ve ADVISOR_MACRO_HIGH_IMPACT_KEYWORDS boş"),
            "rates": {k: m[k] for k in ("treasury_rates", "effective_fed_funds_rate", "policy_rate_oecd") if k in m},
            "inflation": {k: m[k] for k in ("cpi_yoy", "inflation_expectations") if k in m},
            "employment": {k: m[k] for k in ("unemployment_rate", "unemployment_rate_bls") if k in m},
            "equity_market": {k: x[k] for k in ("sp500", "nasdaq100", "vix", "us_market_status") if k in x},
            "risk_context": " · ".join(ctx),
            "sources": [s for v in parts.values() for s in v["sources"]],
            "stale_fields": [k for k, v in parts.items() if v["stale"]],
            "unavailable_fields": [u for v in parts.values() for u in v["unavailable"]] + [
                {"field": k, "source": "OpenBB", "reason": v["error"]} for k, v in parts.items() if v["error"] and not v["data"]],
            "fetched_at": {k: v["fetched_at"] for k, v in parts.items()},
        }
        body = {k: v for k, v in snap.items() if k != "generated_at"}
        snap["macro_snapshot_hash"] = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]
        return snap


def degraded(reason: str) -> dict:
    """The MacroSnapshot when macro was not read at all (e.g. a scan that skips it, or OpenBB switched off)."""
    return {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "macro_status": "UNAVAILABLE",
            "economic_events": [], "high_impact_event_within_2h": None, "high_impact_event_within_6h": None,
            "next_high_impact_event": None, "minutes_to_next_high_impact": None, "caution": False, "block_new_entry": False,
            "impact_basis": None, "rates": {}, "inflation": {}, "employment": {}, "equity_market": {}, "risk_context": "",
            "sources": [], "stale_fields": [], "unavailable_fields": [{"field": "macro", "source": "OpenBB", "reason": reason}],
            "macro_snapshot_hash": None}

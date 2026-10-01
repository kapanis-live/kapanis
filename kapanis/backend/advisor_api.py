"""Kripto Danışman over HTTP: the bot's danisman.py (same code, loaded from the bot folder next to this project).

GET  /api/advisor/opportunities the scan: the most traded pairs through the same analysis, at most 10 setups
                               (?portfolio_usdt=287&holdings=BTC,ETH&limit=60); {"scan": {...}, "text": "..."}
GET  /api/advisor/{symbol}     the report for one coin (optional ?portfolio_usdt=287)
POST /api/advisor/analyze      {"symbol": "HYPE", "portfolio_usdt": 287, "position_usdt": 35, "average_price": 91.05,
                                "holdings": ["BTC", "ETH"]}
Both return {"report": {...}, "text": "..."}: the JSON report and the same report as Turkish text.

Decision support only: nothing here places an order. Like /danis and /firsat in Telegram, every report leaves a
record in the advisor's paper log (research; data_origin LIVE), which no decision reads back. Owner only for now, because the advisor's
intraday rules are not history-tested (see kriptografikbotu/research/README.md); candles come from Binance, so calls
are rate-limited per user and the fetched candles are shared for 45 seconds.
"""
import importlib.util
import re
import sys
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import limits

BOT_DIR = Path(__file__).resolve().parents[2] / "kriptografikbotu"   # same layout on the PC and in the image
ADVISOR_PER_MINUTE = 10
SCAN_PER_MINUTE = 3            # one scan is ~250 exchange requests
CACHE_SECONDS = 45
SCAN_CACHE_SECONDS = 180
MAX_SCAN = 150
_cache: dict[tuple, tuple[float, dict]] = {}
_scans: dict[tuple, tuple[float, dict]] = {}


def engine():
    """danisman.py (and its paper log), loaded by path so the bot's other modules never shadow this project's."""
    for name in ("danisman", "danisman_paper"):
        if name in sys.modules:
            continue
        path = BOT_DIR / f"{name}.py"
        if not path.exists():
            if name == "danisman":
                raise HTTPException(status_code=503, detail="Danışman bu sunucuda kurulu değil.")
            continue                   # no paper log here: reports still work, they are just not recorded
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        except ImportError as e:   # e.g. pandas missing in a bare web environment
            sys.modules.pop(name, None)
            if name == "danisman":
                raise HTTPException(status_code=503, detail=f"Danışman yüklenemedi: {e}")
    return sys.modules["danisman"]


class AnalyzeBody(BaseModel):
    symbol: str
    portfolio_usdt: Optional[float] = None
    position_usdt: Optional[float] = None
    average_price: Optional[float] = None
    holdings: list[str] = []


def _symbol(raw: str) -> str:
    s = (raw or "").strip().upper().replace("/", "").removesuffix("USDT")
    if not re.fullmatch(r"[A-Z0-9]{2,12}", s):
        raise HTTPException(status_code=400, detail="Geçerli bir coin kodu yaz (ör. BTC, HYPE).")
    return s


def _positive(v, name: str):
    if v is not None and not v > 0:
        raise HTTPException(status_code=400, detail=f"{name} sıfırdan büyük olmalı.")
    return v


async def run(symbol: str, portfolio: Optional[float], position: Optional[float], average: Optional[float],
              holdings: list[str]) -> dict:
    d = engine()
    if (position is None) != (average is None):
        raise HTTPException(status_code=400, detail="Pozisyon için position_usdt ve average_price birlikte verilir.")
    others = sorted({_symbol(h) for h in holdings[:8]} - {symbol})
    key = (symbol, tuple(others))
    hit = _cache.get(key)
    try:
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            data = hit[1]
        else:
            data = await d.fetch(symbol, others)
            _cache[key] = (time.monotonic(), data)
            for k in [k for k, v in _cache.items() if time.monotonic() - v[0] > CACHE_SECONDS]:
                _cache.pop(k, None)
        report = d.analyze(data, portfolio, position, average)
        d.paper_log([report], "api")           # research record; never breaks or changes the report
    except d.NoPair:
        raise HTTPException(status_code=404, detail=f"{symbol}: Binance'te USDT/USDC/FDUSD/BTC paritesi yok.")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Borsa verisi alınamadı: {str(e)[:120]}")
    return {"report": report, "text": d.format_report(report)}


def build_router(current_user, require_owner=None) -> APIRouter:
    r = APIRouter(prefix="/api")
    who = require_owner or current_user

    @r.get("/advisor/opportunities")          # declared before /advisor/{symbol}, or it would be read as a coin
    async def opportunities(portfolio_usdt: Optional[float] = None, holdings: str = "", limit: Optional[int] = None,
                            user: dict = Depends(who)):
        d = engine()
        _positive(portfolio_usdt, "Portföy")
        if limit is not None and not 5 <= limit <= MAX_SCAN:
            raise HTTPException(status_code=400, detail=f"limit 5 ile {MAX_SCAN} arasında olmalı.")
        held = sorted({_symbol(h) for h in holdings.split(",") if h.strip()})[:8]
        key = (portfolio_usdt, tuple(held), limit or d.SCAN_LIMIT)
        hit = _scans.get(key)
        if not (hit and time.monotonic() - hit[0] < SCAN_CACHE_SECONDS):
            limits.check_user(user["id"], "advisor-scan", SCAN_PER_MINUTE)
            try:
                hit = (time.monotonic(), await d.scan(portfolio_usdt, held, limit or d.SCAN_LIMIT, paper="api-tara"))
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Tarama yapılamadı: {str(e)[:120]}")
            _scans.clear()                     # one result is enough to keep; it is tens of kilobytes
            _scans[key] = hit
        return {"scan": hit[1], "text": d.format_scan(hit[1])}

    @r.get("/advisor/{symbol}")
    async def advisor(symbol: str, portfolio_usdt: Optional[float] = None, user: dict = Depends(who)):
        limits.check_user(user["id"], "advisor", ADVISOR_PER_MINUTE)
        return await run(_symbol(symbol), _positive(portfolio_usdt, "Portföy"), None, None, [])

    @r.post("/advisor/analyze")
    async def analyze(body: AnalyzeBody, user: dict = Depends(who)):
        limits.check_user(user["id"], "advisor", ADVISOR_PER_MINUTE)
        return await run(_symbol(body.symbol), _positive(body.portfolio_usdt, "Portföy"),
                         _positive(body.position_usdt, "Pozisyon"), _positive(body.average_price, "Ortalama fiyat"),
                         body.holdings)

    return r

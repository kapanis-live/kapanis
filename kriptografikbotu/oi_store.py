"""Open-interest history, kept for research. Binance serves only the last 30 days of hourly open interest, so a
rule built on its rate of change cannot be tested on history until the history is collected. This module only
collects: nothing reads these files for a decision.

One CSV per symbol in backups/oi/ (the folder that survives a redeploy): open time (ms), contracts, value in USD.
"""
import asyncio
import logging

import httpx

import config
import db_backup

log = logging.getLogger(__name__)

DIR = db_backup.BACKUP_DIR / "oi"
FAPI = "https://fapi.binance.com"
PARALLEL = 4
LIMIT = 500      # hours per request (the API's maximum); the job runs far more often than that


def _last(path) -> int:
    try:
        with open(path, "rb") as f:
            tail = f.read()[-200:].decode().strip().splitlines()
        return int(tail[-1].split(",")[0]) if tail else 0
    except (FileNotFoundError, ValueError, IndexError):
        return 0


def merge(path, rows: list[dict]) -> int:
    """Append the rows newer than the file's last one. Returns how many were added."""
    last = _last(path)
    new = sorted((r for r in rows if int(r["timestamp"]) > last), key=lambda r: int(r["timestamp"]))
    if new:
        with open(path, "a", encoding="utf-8") as f:
            f.writelines(f"{int(r['timestamp'])},{r['sumOpenInterest']},{r['sumOpenInterestValue']}\n" for r in new)
    return len(new)


async def symbols(client) -> list[str]:
    try:
        import danisman
        return [coin + "USDT" for coin, _ in await danisman.universe(client, 60)]
    except Exception as e:
        log.warning("OI store: universe failed (%s), using the watch list", e)
        return [c + "USDT" for c in config.WATCHLIST]


async def collect() -> dict:
    DIR.mkdir(parents=True, exist_ok=True)
    slots = asyncio.Semaphore(PARALLEL)
    added, missing = 0, 0
    async with httpx.AsyncClient() as client:
        async def one(sym):
            async with slots:
                r = await client.get(FAPI + "/futures/data/openInterestHist",
                                     params={"symbol": sym, "period": "1h", "limit": LIMIT}, timeout=20)
            if r.status_code != 200:
                return None                      # no perpetual for this coin
            return merge(DIR / f"{sym}.csv", r.json())
        for got in await asyncio.gather(*[one(s) for s in await symbols(client)], return_exceptions=True):
            if isinstance(got, int):
                added += got
            else:
                missing += 1
    return {"eklenen_satir": added, "veri_yok": missing}

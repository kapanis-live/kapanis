"""BIST 100 quality/momentum snapshot for saved user strategies.

Universe is the exchange's current XU100 constituent file. Missing fundamentals are
excluded and counted; a missing value never silently passes a rule.
"""
import asyncio
import csv
import io
import time
from datetime import datetime, timezone

import httpx

import bist
import fundamentals

UNIVERSE_URL = "https://www.borsaistanbul.com/datum/hisse_endeks_ds.csv"
_snapshot = None
_snapshot_at = 0.0
_lock = asyncio.Lock()


async def universe(client):
    response = await client.get(UNIVERSE_URL, timeout=25)
    response.raise_for_status()
    text = response.content.decode("utf-8-sig").replace("\r\r\n", "\n")
    rows = csv.reader(io.StringIO(text), delimiter=";")
    codes = sorted({row[0][:-2] for row in rows if len(row) >= 6 and row[2] == "XU100" and row[0].endswith(".E")})
    if len(codes) != 100:
        raise RuntimeError(f"BIST 100 bileşen listesi doğrulanamadı ({len(codes)} kod).")
    return codes


def quality(fundamental):
    parts = fundamental.get("puan", {}).get("parcalar") or {}
    names = ("kârlılık/ROE", "finansal kalite", "bilanço", "nakit akışı")
    got = maximum = 0.0
    for name in names:
        try:
            value, total = map(float, parts[name].split("/"))
        except (KeyError, ValueError, TypeError):
            continue
        got += value
        maximum += total
    return round(got / maximum * 100, 1) if maximum else None


async def _one(code, sem, index_return):
    async with sem:
        try:
            f = await fundamentals.report(code)
            async with httpx.AsyncClient() as client:
                daily = await bist.fetch(client, code, "1d")
            if len(daily) < 64:
                return None
            start, end = float(daily.close.iloc[-64]), float(daily.close.iloc[-1])
            if start <= 0:
                return None
            relative = round(((end / start) / (1 + index_return) - 1) * 100, 2)
            return {"kod": code, "fk": f.get("fk"), "kalite": quality(f), "momentum_goreli": relative,
                    "fiyat": f.get("fiyat"), "veri_tarihi": datetime.fromtimestamp(int(daily.open_time.iloc[-1]) / 1000,
                                                               timezone.utc).date().isoformat(),
                    "bilanco_donemi": f.get("son_donem")}
        except Exception:
            return None


async def snapshot(progress=None):
    """progress(done, total): optional async callback while the 100 companies are fetched (first run is slow)."""
    global _snapshot, _snapshot_at
    if _snapshot and time.time() - _snapshot_at < 24 * 3600:
        return _snapshot
    async with _lock:
        if _snapshot and time.time() - _snapshot_at < 24 * 3600:
            return _snapshot
        async with httpx.AsyncClient() as client:
            codes = await universe(client)
            index = await bist.fetch(client, bist.INDEX, "1d")
        if len(index) < 64:
            raise RuntimeError("BIST 100 endeksinin 3 aylık kapanışı alınamadı.")
        index_return = float(index.close.iloc[-1]) / float(index.close.iloc[-64]) - 1
        sem = asyncio.Semaphore(4)
        done = 0

        async def tracked(code):
            nonlocal done
            row = await _one(code, sem, index_return)
            done += 1
            if progress and done % 10 == 0:
                try:
                    await progress(done, len(codes))
                except Exception:
                    pass  # a failed status edit never stops the scan
            return row
        rows = await asyncio.gather(*(tracked(code) for code in codes))
        valid = [row for row in rows if row and row["kalite"] is not None]
        if len(valid) < 60:
            raise RuntimeError(f"Yeterli güvenilir bilanço verisi yok ({len(valid)}/100); sıralama yapılmadı.")
        _snapshot = {"rows": valid, "universe_count": len(codes), "excluded": len(codes) - len(valid),
                     "calculated_at": datetime.now(timezone.utc).isoformat(), "source": UNIVERSE_URL,
                     "xu100": round(float(index.close.iloc[-1]), 2),
                     "xu100_tarih": datetime.fromtimestamp(int(index.open_time.iloc[-1]) / 1000, timezone.utc).date().isoformat()}
        _snapshot_at = time.time()
        return _snapshot


def eliminated(data, rules) -> dict:
    """Pure: how many companies each rule removed (a company can fail several; missing F/K fails the F/K rule)."""
    rows = data["rows"]
    out = {"veri_eksik": data.get("excluded", 0)}
    if rules.get("fk_max") is not None:
        out["fk"] = sum(1 for r in rows if not (r["fk"] is not None and 0 < r["fk"] < rules["fk_max"]))
    if rules.get("momentum_min") is not None:
        out["momentum"] = sum(1 for r in rows if r["momentum_goreli"] < rules["momentum_min"])
    if rules.get("quality_min") is not None:
        out["kalite"] = sum(1 for r in rows if r["kalite"] < rules["quality_min"])
    return out


def rank(data, rules):
    """Apply exact filters, then equal-weight percentile rank on quality and relative momentum."""
    rows = [r for r in data["rows"] if
            (rules.get("fk_max") is None or (r["fk"] is not None and 0 < r["fk"] < rules["fk_max"])) and
            (rules.get("momentum_min") is None or r["momentum_goreli"] >= rules["momentum_min"]) and
            (rules.get("quality_min") is None or r["kalite"] >= rules["quality_min"])]
    if not rows:
        return []
    quality_order = sorted(rows, key=lambda r: r["kalite"])
    momentum_order = sorted(rows, key=lambda r: r["momentum_goreli"])
    qrank = {r["kod"]: i / max(1, len(rows) - 1) for i, r in enumerate(quality_order)}
    mrank = {r["kod"]: i / max(1, len(rows) - 1) for i, r in enumerate(momentum_order)}
    scored = [{**r, "birlesik_skor": round(100 * (qrank[r["kod"]] + mrank[r["kod"]]) / 2, 1)} for r in rows]
    return sorted(scored, key=lambda r: (-r["birlesik_skor"], r["kod"]))

"""Earnings release times of US companies, from the official record: every earnings release is an 8-K with item 2.02,
and SEC EDGAR keeps each one's acceptance time. Free, complete, and not an estimate.

Used as CONTEXT only (how the stock reacted to its last report; when the next one is likely). The history test of an
earnings-drift rule failed (research/pead_lab.py): a good reaction was followed by nothing beyond the market's drift.
"""
import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import config
import us

CACHE_DIR = config.DATA_DIR / "abd_temel"
TTL = 12 * 3600


def ny_time(t: str) -> datetime:
    """The submissions API's acceptanceDateTime is not UTC and not New York time: it runs ahead of New York by twice
    New York's UTC offset (Apple's 16:30 release reads 00:30 in summer and 02:30 in winter; JPMorgan's 06:30 reads
    14:30 / 16:30). Undo that. Returns New York wall-clock time (naive)."""
    shown = datetime.fromisoformat(t[:19])
    summer = shown - timedelta(hours=8)
    return summer if summer.replace(tzinfo=us.NY).utcoffset() == timedelta(hours=-4) else shown - timedelta(hours=10)


async def releases(client, t: str, cache: Path | None = None, since: str = "2015-01-01", ttl: float = TTL) -> list[str]:
    """Acceptance times of the company's earnings 8-Ks as the API gives them (see ny_time), oldest first."""
    t = us.ticker(t)
    folder = cache or CACHE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{t}_8k.json"
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
        if time.time() - doc["zaman"] < ttl:
            return doc["veri"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        pass
    if us.cik(t) is None:
        await us.is_us_ticker(client, t)   # loads the ticker -> CIK map
    cik = us.cik(t)
    if not cik:
        return []
    head = {"User-Agent": config.SEC_USER_AGENT}
    r = await client.get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", headers=head, timeout=30)
    r.raise_for_status()
    doc = r.json()["filings"]
    parts = [doc["recent"]]
    for extra in doc.get("files", []):
        if extra.get("filingTo", "9999") >= since:
            await asyncio.sleep(0.15)                      # SEC fair-access limit: 10 requests a second
            e = await client.get("https://data.sec.gov/submissions/" + extra["name"], headers=head, timeout=30)
            e.raise_for_status()
            parts.append(e.json())
    out = sorted({x[:19] for p in parts for form, items, x in zip(p["form"], p["items"], p["acceptanceDateTime"])
                  if form == "8-K" and "2.02" in (items or "")})
    f.write_text(json.dumps({"zaman": time.time(), "veri": out}), encoding="utf-8")
    return out


def last_reaction(d, spy, times: list[str]) -> dict | None:
    """How the stock closed on the first session after its last earnings release, against SPY. d, spy: daily frames
    with open_time (ms) and close. Pure."""
    if not times or d is None or len(d) < 3:
        return None
    days = [datetime.fromtimestamp(int(x) / 1000, us.NY).date() for x in d.open_time]
    spy_by_day = {datetime.fromtimestamp(int(x) / 1000, us.NY).date(): float(c) for x, c in zip(spy.open_time, spy.close)}
    for t in reversed(times):
        w = ny_time(t)
        after_close = (w.hour, w.minute) >= us.CLOSE
        i = next((k for k, day in enumerate(days) if (day > w.date() if after_close else day >= w.date())), None)
        if i is None or i == 0:
            continue                                        # the reaction session has not closed yet, or no bar before it
        move = float(d.close.iloc[i]) / float(d.close.iloc[i - 1]) - 1
        s0, s1 = spy_by_day.get(days[i - 1]), spy_by_day.get(days[i])
        rel = move - (s1 / s0 - 1) if s0 and s1 else None
        since = float(d.close.iloc[-1]) / float(d.close.iloc[i]) - 1
        return {"aciklama": w.strftime("%Y-%m-%d %H:%M") + " New York", "tepki_gunu": days[i].isoformat(),
                "tepki_yuzde": round(move * 100, 1), "spy_gore_yuzde": None if rel is None else round(rel * 100, 1),
                "o_gunden_beri_yuzde": round(since * 100, 1), "seans_once": len(d) - 1 - i}
    return None


def expected_next(times: list[str], today=None) -> str | None:
    """A rough next date when the company has not announced one: the last release plus the usual gap between its
    releases. Marked as an estimate wherever it is shown."""
    if len(times) < 5:
        return None
    days = [ny_time(t).date() for t in times[-9:]]
    gaps = sorted((b - a).days for a, b in zip(days, days[1:]) if 60 <= (b - a).days <= 120)
    if not gaps:
        return None
    nxt = days[-1] + timedelta(days=gaps[len(gaps) // 2])
    today = today or us.now_ny().date()
    return nxt.isoformat() if nxt >= today else None

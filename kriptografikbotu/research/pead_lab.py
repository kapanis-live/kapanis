"""Post-earnings drift on US stocks: after a strong reaction to an earnings release, does the stock keep going?
Writes pead_results.json; touches nothing else.

Why this form: analyst-surprise history is not available for free (Yahoo serves four quarters). The release DATE is:
every earnings release is an 8-K with item 2.02, and SEC EDGAR keeps the acceptance time of each one. The market's
own reaction is the surprise measure (the "earnings announcement return" of the literature).

Event: an 8-K item 2.02 of a company in today's S&P 100 (us.SP100; no delisted names, a known bias).
Reaction day: the filing's day when it was accepted before 16:00 New York time, else the next trading day.
Reaction: that day's close-to-close return minus SPY's.
Rule, fixed before any result was seen: reaction >= +2 % -> hold for 40 trading days from that close. A later
qualifying release restarts the 40 days. Costs 0.1 % per side. Everything else is engine.py's standard: buy & hold,
random timing with the same time in the market, yearly folds, the last 365 days locked.
Also reported, as context and not as candidates: +5 % / 40 days, +2 % / 20 days, and the mirror (reaction <= -2 %),
which should do WORSE than random if the drift is real.

    python research/pead_lab.py
"""
import asyncio
import json
import pathlib
import sys
from datetime import datetime, timedelta

import httpx
import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import config  # noqa: E402
import engine  # noqa: E402
import regime  # noqa: E402
import us  # noqa: E402

SEC_CACHE = HERE / "kl" / "sec_8k"
VARIANTS = {"PEAD +%2 / 40 gun (on kayitli kural)": (0.02, 40, 1), "PEAD +%5 / 40 gun": (0.05, 40, 1),
            "PEAD +%2 / 20 gun": (0.02, 20, 1), "AYNA -%2 / 40 gun": (0.02, 40, -1)}


async def releases(client, sym: str) -> list[str]:
    """Acceptance times of the company's earnings 8-Ks as the API gives them (see ny_time), oldest first."""
    f = SEC_CACHE / f"{sym}.json"
    if f.exists():
        return json.loads(f.read_text())
    cik = us.cik(sym)
    if not cik:
        return []
    head = {"User-Agent": config.SEC_USER_AGENT}
    r = await client.get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", headers=head, timeout=30)
    r.raise_for_status()
    doc = r.json()["filings"]
    parts = [doc["recent"]]
    for extra in doc.get("files", []):
        if extra.get("filingTo", "9999") >= "2015-01-01":
            await asyncio.sleep(0.15)                      # SEC fair-access limit: 10 requests a second
            e = await client.get("https://data.sec.gov/submissions/" + extra["name"], headers=head, timeout=30)
            e.raise_for_status()
            parts.append(e.json())
    out = sorted({t[:19] for p in parts for form, items, t in zip(p["form"], p["items"], p["acceptanceDateTime"])
                  if form == "8-K" and "2.02" in (items or "")})
    f.write_text(json.dumps(out))
    await asyncio.sleep(0.15)
    return out


def ny_time(t: str) -> datetime:
    """The submissions API's acceptanceDateTime is not UTC and not New York time: it runs ahead of New York by twice
    New York's UTC offset (Apple's 16:30 release reads 00:30 in summer and 02:30 in winter; JPMorgan's 06:30 reads
    14:30 / 16:30). Undo that."""
    shown = datetime.fromisoformat(t)
    summer = shown - timedelta(hours=8)
    return summer if summer.replace(tzinfo=us.NY).utcoffset() == timedelta(hours=-4) else shown - timedelta(hours=10)


def reaction_rows(df: pd.DataFrame, times: list[str]) -> list[int]:
    """Row of the first close that follows each release."""
    days = df.day.dt.date.values
    rows = []
    for t in times:
        w = ny_time(t)
        day = w.date()
        i = int(np.searchsorted(days, day, side="left" if (w.hour, w.minute) < (16, 0) else "right"))
        if 0 < i < len(df):
            rows.append(i)
    return sorted(set(rows))


def make(threshold: float, hold: int, sign: int):
    def strategy(df):
        pos = np.zeros(len(df))
        c, b = df.c.values, df.bench_c.values
        for i in df.attrs.get("releases", []):
            if not (b[i - 1] > 0 and b[i] > 0):
                continue
            react = (c[i] / c[i - 1] - 1) - (b[i] / b[i - 1] - 1)
            if sign * react >= threshold:
                pos[i:i + hold] = 1
        return pos
    return strategy


async def load() -> list[pd.DataFrame]:
    SEC_CACHE.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient() as client:
        await us.is_us_ticker(client, "AAPL")                 # loads the ticker -> CIK map
        bench = regime.label(engine.indicators(await engine.yahoo_daily(client, "SPY")))
        frames = []
        for sym in us.SP100:
            try:
                df = await engine.yahoo_daily(client, sym.replace(".", "-"))
                times = await releases(client, sym)
            except Exception as e:
                print("skip", sym, str(e)[:60], flush=True)
                continue
            if len(df) <= engine.WARMUP + 120 or not times:
                continue
            df = engine.attach_benchmark(engine.indicators(df), bench)
            df["bench_c"] = df.day.map(bench.set_index("day").c)
            df.attrs["releases"] = reaction_rows(df, times)
            df.attrs["sym"] = sym
            frames.append(df)
    return frames


def main() -> dict:
    frames = asyncio.run(load())
    per_year = np.mean([len(f.attrs["releases"]) / (len(f) / 252) for f in frames])
    out = {"veri": {"hisse": len(frames), "hisse_basina_yillik_bilanco": round(float(per_year), 2)}, "sonuc": {}}
    for name, (thr, hold, sign) in VARIANTS.items():
        out["sonuc"][name] = engine.evaluate(frames, make(thr, hold, sign), "ABD")
    return out


if __name__ == "__main__":
    res = main()
    (HERE / "pead_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(res["veri"])
    for k, r in res["sonuc"].items():
        d, h = r["donemler"].get("gelistirme", {}), r["donemler"].get("kilitli_son_12_ay", {})
        print(f"{k:38s} {r['karar']:10s} yil {r['rastgeleyi_gecen_yil']} | gel {d.get('kural_yillik_%')}/{d.get('rastgele_%')} "
              f"(%{d.get('rastgeleyi_gecen_varlik_%')}) al-tut {d.get('al_tut_%')} piyasada %{d.get('piyasada_%')} | kilit "
              f"{h.get('kural_yillik_%')}/{h.get('rastgele_%')} (%{h.get('rastgeleyi_gecen_varlik_%')}) | {r['islemler_gelistirme']}", flush=True)
        print("     yillar:", {y: (t["kural_yillik_%"], t["rastgele_%"]) for y, t in r["donemler"].items() if y.isdigit()})

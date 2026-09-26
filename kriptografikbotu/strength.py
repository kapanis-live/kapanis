"""BIST weekly strength ranking and sector rotation (medium/long-term). Code only, no AI.

For every validated BIST name (universe.bist_names, ~200) on WEEKLY closes:
- relative strength vs BIST 100 over 13 and 26 weeks (percentage points)
- weekly trend: close above weekly SMA20, SMA20 above SMA50
- distance to the 52-week high (near the high = strong)
- volume: last 4 weeks vs the 20-week average
Score = weighted percentile ranks (RS13 35%, RS26 25%, 52w-high proximity 20%, volume 10%) + trend points (10%).
Sectors: average RS13 of their names (risk.SECTORS), compared with last week's run (data/strength.json).
"""
import asyncio
import json
import logging
import time

import httpx
import pandas as pd

import bist
import config
import market
import risk
import universe

log = logging.getLogger(__name__)

FILE = config.DATA_DIR / "strength.json"


def metrics(w: pd.DataFrame, idx: pd.DataFrame) -> dict | None:
    """Weekly metrics for one stock. Pure."""
    if len(w) < 30 or len(idx) < 27:
        return None
    last = w.iloc[-1]
    close = float(last.close)

    def rs(n):
        if len(w) <= n:
            return None
        return ((close / float(w.close.iloc[-n - 1])) - (float(idx.close.iloc[-1]) / float(idx.close.iloc[-n - 1]))) * 100

    high52 = float(w.close.tail(52).max())
    vol4 = float(w.volume.tail(4).mean())
    vol20 = float(w.volume.tail(20).mean())
    sma20, sma50 = last.get("sma20"), last.get("sma50")
    trend = int(sma20 == sma20 and close > sma20) + int(sma20 == sma20 and sma50 == sma50 and sma20 > sma50)
    return {"kapanis": close, "rs13": rs(13), "rs26": rs(26), "tepe_uzaklik": (close / high52 - 1) * 100,
            "hacim": vol4 / vol20 if vol20 else None, "trend": trend,
            "hafta_degisim": (close / float(w.close.iloc[-2]) - 1) * 100}


def rank(rows: dict[str, dict]) -> list[dict]:
    """Composite score from percentile ranks. Pure."""
    df = pd.DataFrame.from_dict(rows, orient="index").dropna(subset=["rs13", "rs26"])
    if df.empty:
        return []
    pct = lambda col: df[col].rank(pct=True).fillna(0.5)
    df["skor"] = (0.35 * pct("rs13") + 0.25 * pct("rs26") + 0.20 * pct("tepe_uzaklik")
                  + 0.10 * pct("hacim") + 0.10 * df["trend"] / 2) * 100
    df = df.sort_values("skor", ascending=False)
    return [{"hisse": t, **{k: (None if v != v else round(float(v), 2)) for k, v in r.items()}} for t, r in df.iterrows()]


def sectors(ranked: list[dict]) -> list[dict]:
    groups: dict[str, list[float]] = {}
    for r in ranked:
        s = risk.SECTORS.get(r["hisse"])
        if s:
            groups.setdefault(s, []).append(r["rs13"])
    out = [{"sektor": s, "rs13": round(sum(v) / len(v), 2), "n": len(v)} for s, v in groups.items() if len(v) >= 2]
    return sorted(out, key=lambda x: -x["rs13"])


async def run() -> dict:
    names = universe.bist_names()
    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient() as client:
        idx = await bist.fetch(client, bist.INDEX, "1wk")

        async def one(t):
            async with sem:
                try:
                    w = market.add_indicators(await bist.fetch(client, t, "1wk"))
                    return t, metrics(w, idx)
                except Exception as e:
                    log.debug("Strength fetch %s failed: %s", t, e)
                    return t, None

        results = await asyncio.gather(*(one(t) for t in names))
    rows = {t: m for t, m in results if m}
    ranked = rank(rows)
    prev = load()
    prev_rank = {r["hisse"]: i + 1 for i, r in enumerate(prev.get("sirali", []))}
    prev_sector = {s["sektor"]: s["rs13"] for s in prev.get("sektorler", [])}
    for i, r in enumerate(ranked):
        r["sira"] = i + 1
        r["onceki_sira"] = prev_rank.get(r["hisse"])
    secs = sectors(ranked)
    for s in secs:
        s["onceki"] = prev_sector.get(s["sektor"])
    out = {"zaman": time.time(), "taranan": len(names), "gecerli": len(rows), "sirali": ranked, "sektorler": secs}
    FILE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def text(res: dict, top: int = 10) -> str:
    ranked = res.get("sirali", [])
    if not ranked:
        return "Güç sıralaması hesaplanamadı (veri yok)."
    lines = [f"💪 BIST HAFTALIK GÜÇ SIRALAMASI — {res['gecerli']} hisse (orta/uzun vade, haftalık kapanış)"]
    for r in ranked[:top]:
        move = ""
        if r.get("onceki_sira"):
            d = r["onceki_sira"] - r["sira"]
            move = f" ({'▲' if d > 0 else '▼' if d < 0 else '='}{abs(d) if d else ''})"
        lines.append(f"{r['sira']:>2}. {r['hisse']}{move} skor {r['skor']:.0f} · 13h endekse göre {r['rs13']:+.1f} puan · "
                     f"zirveye {r['tepe_uzaklik']:+.1f}% · hafta {r['hafta_degisim']:+.1f}% · trend {'✅' * int(r['trend'] or 0) or '—'}")
    secs = res.get("sektorler", [])
    if secs:
        fmt = lambda s: (f"{s['sektor']} {s['rs13']:+.1f}"
                         + (f" ({'↑' if s['rs13'] > s['onceki'] else '↓'})" if s.get("onceki") is not None else ""))
        lines += ["", "🔄 SEKTÖR ROTASYONU (13 haftalık ortalama güç, geçen haftaya göre)",
                  "Güçlü: " + " · ".join(fmt(s) for s in secs[:3]),
                  "Zayıf: " + " · ".join(fmt(s) for s in secs[-3:][::-1])]
    lines.append("\nBu bir sıralama, AL sinyali değil. Giriş için hisse planı ve günlük kapanış teyidi gerekir.")
    return "\n".join(lines)

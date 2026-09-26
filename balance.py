"""Balances and profit/loss, kept separate per market: BIST (TL), crypto (USDT), gold/FX (TL).

Each market has its own cash, entered by the user (/bakiye nakit 5000 tl -> BIST, /bakiye nakit 120 usdt
-> crypto). Buys and sells do not move cash automatically: the bot never sees the brokerage account.
Profit/loss per market:
- today    = open positions' change since the previous close + P/L realized today
- week     = open positions' change over 7 days (from the buy price if bought later) + realized in 7 days
- all time = open positions' value − cost + every realized P/L
- winners / losers split the same all-time numbers by sign.
"""
from datetime import datetime, timedelta

import alerts_store
import positions

MARKETS = {"BIST": ("🇹🇷 BIST", "TL"), "KRIPTO": ("🪙 Kripto", "USDT"), "ABD": ("🇺🇸 ABD", "USD"),
           "DIGER": ("🥇 Altın/Döviz", "TL")}
CASH_MARKET = {"TL": "BIST", "USD": "KRIPTO"}  # which market a typed cash amount belongs to


def cash() -> dict[str, float]:
    return alerts_store.load_settings().get("nakit_piyasa", {})


def set_cash(market: str, amount: float):
    s = alerts_store.load_settings()
    s.setdefault("nakit_piyasa", {})[market] = amount
    alerts_store.save_settings(s)


def _mkt(p: dict) -> str:
    return p.get("piyasa") or "KRIPTO"


def realized(since: str | None = None) -> dict[str, list[float]]:
    """P/L of each closed record per market, optionally only those closed since an ISO time."""
    out: dict[str, list[float]] = {}
    for p in positions.load():
        if p["durum"] != "kapali" or p.get("kapanis_fiyat") is None:
            continue
        if since and (p.get("kapanis_zamani") or "") < since:
            continue
        out.setdefault(_mkt(p), []).append((p["kapanis_fiyat"] - p["giris"]) * p["adet"])
    return out


def summarize(groups: list[dict], week_start_prices: dict[str, float | None], now: datetime | None = None) -> dict:
    """groups: collect_portfolio() rows (piyasa, symbol, deger, maliyet, gun_tutar, fiyat, poz).
    week_start_prices: symbol -> close 7 days ago (None if unknown)."""
    now = now or alerts_store.now_tr()
    week_ago = now - timedelta(days=7)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    res: dict[str, dict] = {}

    def row(mkt):
        return res.setdefault(mkt, {"varlik": 0.0, "maliyet": 0.0, "bugun": 0.0, "hafta": 0.0, "acik": 0.0,
                                    "gerceklesen": 0.0, "kar": 0.0, "zarar": 0.0})

    for g in groups:
        r = row(g["piyasa"])
        r["varlik"] += g["deger"]
        r["maliyet"] += g["maliyet"]
        r["bugun"] += g.get("gun_tutar") or 0.0
        unreal = g["deger"] - g["maliyet"]
        r["acik"] += unreal
        r["kar" if unreal >= 0 else "zarar"] += unreal
        start = week_start_prices.get(g["symbol"])
        for p in g["poz"]:
            opened = datetime.fromisoformat(p["acilis"])
            ref = p["giris"] if opened >= week_ago or start is None else start
            r["hafta"] += p["adet"] * (g["fiyat"] - ref)
    for mkt, items in realized().items():
        r = row(mkt)
        for v in items:
            r["gerceklesen"] += v
            r["kar" if v >= 0 else "zarar"] += v
    for mkt, items in realized(today.isoformat()).items():
        row(mkt)["bugun"] += sum(items)
    for mkt, items in realized(week_ago.isoformat()).items():
        row(mkt)["hafta"] += sum(items)
    for r in res.values():
        r["toplam"] = r["acik"] + r["gerceklesen"]
        for k in list(r):
            r[k] = round(r[k], 2)
    return res


def text(res: dict, cash_: dict[str, float], only: str | None = None) -> str:
    def sign(v: float) -> str:
        return f"{'🟢' if v > 0 else '🔴' if v < 0 else '⚪'} {v:+,.2f}"

    lines = [f"💰 BAKİYE — {alerts_store.now_tr().strftime('%d.%m %H:%M')} (her piyasa ayrı)"]
    empty = {"varlik": 0.0, "bugun": 0.0, "hafta": 0.0, "toplam": 0.0, "kar": 0.0, "zarar": 0.0,
             "acik": 0.0, "gerceklesen": 0.0, "maliyet": 0.0}
    for mkt, (title, unit) in MARKETS.items():
        if only and mkt != only:
            continue
        r, c = res.get(mkt), cash_.get(mkt, 0.0)
        if not r and not c:
            continue
        r = r or empty
        lines += ["", title,
                  f"Bakiye {r['varlik'] + c:,.2f} {unit} = varlık {r['varlik']:,.2f}"
                  + (f" + nakit {c:,.2f}" if mkt != "DIGER" else ""),
                  f"Bugün {sign(r['bugun'])} · Bu hafta {sign(r['hafta'])} · Toplam {sign(r['toplam'])} {unit}",
                  f"Toplam kâr +{r['kar']:,.2f} · toplam zarar {r['zarar']:,.2f} "
                  f"(açık {r['acik']:+,.2f}, gerçekleşen {r['gerceklesen']:+,.2f})"]
        if r["maliyet"]:
            lines.append(f"Yatırılan (açık) {r['maliyet']:,.2f} {unit} → %{(r['varlik'] / r['maliyet'] - 1) * 100:+.2f}")
    if len(lines) == 1:
        lines.append("\nBu piyasada varlık ya da nakit yok.")
    missing = [m for m in ("BIST", "KRIPTO") if m not in cash_ and (not only or m == only)]
    if missing:
        lines.append("\nNakit: " + " · ".join("/bakiye nakit 5000 tl (BIST)" if m == "BIST" else "/bakiye nakit 120 usdt (kripto)"
                                                for m in missing))
    lines.append("Bugün: kapanıştan beri değişim + bugün satılanlar. Hafta: son 7 gün. Nakit alım/satımda "
                 "kendiliğinden değişmez. Tek piyasa: /bakiye bist · /bakiye kripto · /bakiye abd · ABD nakdi: /bakiye nakit abd 1000")
    return "\n".join(lines)

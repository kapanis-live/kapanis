"""'Portföyümdeki ASTOR çok arttı, ne yapayım?' — a concrete plan for one holding, computed in code.

All buys of the asset are combined (average cost, earliest date, highest stop). exits.analyze gives the verdict
(TUT / KISMİ SAT / SAT), the resistance above and a stop that only moves up. From that this module builds a
staged plan with quantities: what to sell now, what to sell at the next resistance, where the rest's stop goes.
The language model only explains the plan; it never changes the numbers.
"""
import httpx

import bist
import exits
import market
import positions
import us

BIG_GAIN_PCT = 20.0  # above this, even a TUT gets a profit-protection ladder


def holdings(code: str) -> list[dict]:
    """Open positions of one asset, matched by ticker ('ASTOR', 'AVAX', 'AVAX/USDT', 'ASTOR.IS')."""
    c = code.upper().removesuffix(".IS").removesuffix("/USDT")
    out = []
    for p in positions.open_positions():
        names = {p["pair"].upper(), p["pair"].split("/")[0].upper(), p["symbol"].upper()}
        if p.get("piyasa") == "BIST":
            names.add(bist.ticker(p["symbol"]).upper())
        if p.get("piyasa") == "ABD":
            names.add(us.ticker(p["symbol"]).upper())
        if c in names:
            out.append(p)
    return out


def combine(items: list[dict]) -> dict:
    qty = sum(p["adet"] for p in items)
    cost = sum(p["adet"] * p["giris"] for p in items)
    stops = [p["stop"] for p in items if p.get("stop") is not None]
    first = min(items, key=lambda p: p["acilis"])
    return {**first, "adet": qty, "giris": cost / qty, "stop": max(stops) if stops else None,
            "stop_ilk": None, "ids": [p["id"] for p in items]}


def _lots(pos: dict, qty: float) -> float:
    return float(int(qty)) if pos.get("piyasa") == "BIST" else round(qty, 6)


def plan(pos: dict, a: dict) -> list[str]:
    """Staged plan lines with quantities (pure: pos = combined holding, a = exits.analyze result)."""
    q, gain = pos["adet"], a["kar_yuzde"]
    stop = a["stop_onerisi"]["seviye"] if a["stop_onerisi"] else pos.get("stop")
    lines = []
    if a["karar"] == "SAT":
        lines.append(f"1) Şimdi: hepsini sat ({_lots(pos, q):g} adet) — kural çıkışı, sebep yukarıda.")
        return lines
    if a["karar"] == "KISMİ SAT":
        now = _lots(pos, q / 2)
        lines.append(f"1) Şimdi: yarısını sat ({now:g} adet), kârın bir kısmını cebe koy.")
        rest = q - now
    elif gain >= BIG_GAIN_PCT:
        now = _lots(pos, q / 3)
        lines.append(f"1) Kâr büyük (%{gain:.0f}) ama çıkış işareti yok: istersen üçte birini sat ({now:g} adet), "
                     "istemezsen hepsini tut ama stopu mutlaka yukarı taşı.")
        rest = q - now
    else:
        lines.append("1) Şimdi: tut. Çıkış işareti yok; satmak için bir sebep oluşmadı.")
        rest = q
    if a.get("trend_cikis"):
        lines.append(f"2) Test edilmiş çıkış: günlük kapanış {a['trend_cikis']:.6g} (son 10 günün dibi, her gün güncellenir) "
                     f"altına inerse kalanı sat ({_lots(pos, rest):g} adet). Direnç bölgelerine göre satma: geçmiş testte işe yaramadı.")
    if stop is not None:
        lines.append(f"3) Kalanın stopu: {stop:.6g} ({(stop / a['fiyat'] - 1) * 100:+.1f}%) — kapanışla; yalnız yukarı çekilir. "
                     "Borsada/aracıda stop emri kullanıyorsan biraz altına koy.")
    else:
        lines.append("3) Stop yok: kârı korumak için bir stop belirle (ör. son dip ya da maliyet).")
    lines.append("4) Fiyat yükselmeye devam ederse: her yeni tepe kapanışta stop da yükselir (iz süren stop, 3×ATR).")
    return lines


async def advise(code: str) -> tuple[str, dict] | None:
    """Plain text plan + data for the model. None if the asset is not held."""
    items = holdings(code)
    if not items:
        return None
    pos = combine(items)
    async with httpx.AsyncClient() as client:
        sig, htf, tf = await exits.frames(client, pos)
        if pos.get("piyasa") == "BIST":
            price = await bist.last_price(client, pos["symbol"])
        elif pos.get("piyasa") == "ABD":
            price = await us.last_price(client, pos["symbol"])
        else:
            price = await market.last_price(client, pos["symbol"])
    if len(sig) < 30:
        return None
    a = exits.analyze(pos, sig, htf, tf, price)
    head = exits.text({**pos, "id": "+".join(map(str, pos["ids"]))}, a)
    steps = plan(pos, a)
    text = head + "\n\n📋 PLAN\n" + "\n".join(steps)
    data = {"pozisyon": {"kod": code.upper(), "piyasa": pos.get("piyasa", "KRIPTO"), "adet": pos["adet"],
                         "ortalama_maliyet": round(pos["giris"], 6), "alis_sayisi": len(items), "ilk_alis": pos["acilis"][:10],
                         "stop": pos.get("stop")},
            "kod_karari": {k: a.get(k) for k in ("karar", "sinyaller", "stop_onerisi", "kar_yuzde", "R", "rsi",
                                                 "zaman_dilimi", "fiyat", "trend_cikis")},
            "kod_plani": steps}
    return text, data

"""BIST end-of-day report (18:45 TR on trading days, or /gunsonu). Code only, no DeepSeek.

For every BIST stock the user holds, lists in /plan, or has a plan for: the final daily close, change,
volume vs. its 20-day average, position vs. SMA20/50, RSI, nearest support/resistance zones and the
plan levels for tomorrow. Plus the BIST 100 gate and USD/TRY.
"""
import logging

import httpx

import alerts_store
import bist
import conversation_store as store
import market
import positions

log = logging.getLogger(__name__)


def tickers() -> list[str]:
    keys = [p["symbol"] for p in positions.open_positions() if p.get("piyasa") == "BIST"]
    keys += [k for k in (alerts_store.load_settings().get("plan_listesi") or []) if k.endswith(".IS")]
    keys += [k for k in store.load_state()["planlar"] if k.endswith(".IS")]
    return list(dict.fromkeys(bist.yahoo_symbol(k) for k in keys))


def _g(x) -> str:
    return "—" if x is None or x != x else f"{x:.4g}"


async def stock_line(client: httpx.AsyncClient, sym: str) -> str:
    d = market.add_indicators(await bist.fetch(client, sym, "1d"))
    w = market.add_indicators(await bist.fetch(client, sym, "1wk"))
    if len(d) < 2:
        return f"{bist.ticker(sym)}: veri yok"
    last, prev = d.iloc[-1], d.iloc[-2]
    close = float(last.close)
    chg = (close / float(prev.close) - 1) * 100
    vol = f"hacim x{last.volume / last.vol_avg20:.1f}" if last.vol_avg20 == last.vol_avg20 and last.vol_avg20 else "hacim ?"
    trend = []
    for name, col in (("SMA20", "sma20"), ("SMA50", "sma50")):
        v = last[col]
        if v == v:
            trend.append(f"{name} {'üstü' if close > v else 'altı'}")
    atr = float(last.atr14) if last.atr14 == last.atr14 else close * 0.03
    z = market.sr_zones(d, w, close, atr, top=1)
    sup = z["destekler"][0] if z["destekler"] else None
    res = z["direncler"][0] if z["direncler"] else None
    lines = [f"{'🟢' if chg > 0 else '🔴' if chg < 0 else '⚪'} {bist.ticker(sym)} {close:g} ({chg:+.2f}%) · {vol} · "
             f"{', '.join(trend)} · RSI {_g(float(last.rsi14))}",
             f"   destek {_g(sup['alt'])}–{_g(sup['ust'])}" if sup else "   destek: yapısal bölge yok",
             ]
    lines[-1] += f" · direnç {_g(res['alt'])}–{_g(res['ust'])}" if res else " · direnç: yapısal bölge yok"
    p = store.load_state()["planlar"].get(sym)
    if p:
        t, i, h = p.get("tetik"), p.get("iptal"), p.get("hedef")
        state = ("iptal altında kapandı, plan bozuk" if i is not None and close < i else
                 "tetik üstünde kapandı, yarın 1s teyit aranır" if t is not None and close > t else "tetik bekleniyor")
        lines.append(f"   plan: tetik {_g(t)} · iptal {_g(i)} · hedef {_g(h)} → {state}")
    held = [x for x in positions.open_positions() if x["symbol"] == sym]
    if held:
        qty = sum(x["adet"] for x in held)
        cost = sum(x["adet"] * x["giris"] for x in held)
        stop = min((x["stop"] for x in held if x.get("stop") is not None), default=None)
        lines.append(f"   pozisyon: {qty:.0f} adet · ort. {cost / qty:.4g} · toplam %{(close / (cost / qty) - 1) * 100:+.2f}"
                     + (f" · stop {stop:g}" + (" ⚠️ stop altında kapandı" if close < stop else "") if stop else ""))
    return "\n".join(lines)


async def report() -> str | None:
    syms = tickers()
    if not syms:
        return None
    lines = [f"🌆 BIST GÜN SONU — {alerts_store.now_tr().strftime('%d.%m')}"]
    async with httpx.AsyncClient() as client:
        try:
            g = await bist.index_gate(client)
            lines.append(f"BIST 100 {g['xu100_kapanis']} · kapı {g['durum']} · USD/TRY {g.get('usdtry')}"
                         + (f" (5g %{g['usdtry_5g_yuzde']:+.2f})" if g.get("usdtry_5g_yuzde") is not None else ""))
        except Exception as e:
            lines.append(f"BIST 100 alınamadı ({str(e)[:50]})")
        for sym in syms[:15]:
            try:
                lines.append("\n" + await stock_line(client, sym))
            except Exception as e:
                log.warning("EOD line failed for %s: %s", sym, e)
                lines.append(f"\n{bist.ticker(sym)}: veri alınamadı")
    lines.append("\nGünlük kapanışlar kesin (18:30 sonrası). Yarın giriş yalnız 1 saatlik kapanış teyidiyle.")
    return "\n".join(lines)

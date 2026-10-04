"""Watchlist scanner: finds setups by itself, so the user doesn't have to ask first.

Setup (close-only, computed in code): a 15m candle CLOSES above a 4h/1d resistance zone that the
previous candle closed below, with volume above its 20-candle average, above the 15m SMA50, and
not stretched far past the level. The scanner then writes an automatic plan whose confirmation
is the NEXT candle; watcher.py checks that candle and runs the shared decision gate, which sends
"🟢 ŞİMDİ AL" only if every rule passes. No DeepSeek call happens here.
"""
import logging
import time

import httpx

import alerts_store
import broker
import config
import conversation_store as store
import market
import positions

log = logging.getLogger(__name__)

COOLDOWN_SECONDS = 4 * 3600       # one candidate per coin per 4 hours
AUTO_PLAN_TTL_SECONDS = 6 * 3600  # automatic plans that never produced a position expire
MAX_STRETCH_ATR = 1.5             # close further than this many 15m ATRs above the level = chasing
ZONE_CACHE_SECONDS = 3600
_zone_frames: dict[str, tuple[float, object, object]] = {}


def enabled() -> bool:
    return alerts_store.load_settings().get("tarayici", True)


def set_enabled(on: bool):
    s = alerts_store.load_settings()
    s["tarayici"] = on
    alerts_store.save_settings(s)


async def _htf(client: httpx.AsyncClient, symbol: str):
    """4h and 1d frames for zone detection, cached an hour (zones move slowly)."""
    hit = _zone_frames.get(symbol)
    if hit and time.time() - hit[0] < ZONE_CACHE_SECONDS:
        return hit[1], hit[2]
    df4h = market.add_indicators(await market.fetch_klines(client, symbol, "4h"))
    df1d = market.add_indicators(await market.fetch_klines(client, symbol, "1d"))
    _zone_frames[symbol] = (time.time(), df4h, df1d)
    return df4h, df1d


def expire_auto_plans() -> list[str]:
    """Drop automatic plans older than the TTL that never turned into a position."""
    state = store.load_state()
    now = time.time()
    dropped = [c for c, p in state["planlar"].items()
               if p.get("otomatik") and not p.get("pozisyon") and now - p.get("guncelleme", now) > AUTO_PLAN_TTL_SECONDS]
    for c in dropped:
        del state["planlar"][c]
    if dropped:
        store.save_state(state)
    return dropped


async def scan() -> list[dict]:
    """Return new candidates; each one has already been saved as an automatic plan."""
    state = store.load_state()
    s = alerts_store.load_settings()
    last_seen = s.setdefault("tarayici_son", {})
    held = {p["pair"].split("/")[0] for p in positions.open_positions() if p.get("piyasa", "KRIPTO") == "KRIPTO"}
    found = []
    no_broker = broker.blocked() - held
    async with httpx.AsyncClient() as client:
        for coin in config.WATCHLIST:
            if coin in no_broker:
                continue
            if coin in state["planlar"] or coin in held or time.time() - last_seen.get(coin, 0) < COOLDOWN_SECONDS:
                continue
            symbol = coin + config.QUOTE
            try:
                df = market.add_indicators(await market.fetch_klines(client, symbol, "15m"))
                df4h, df1d = await _htf(client, symbol)
            except Exception as e:
                log.warning("Scanner fetch failed for %s: %s", coin, e)
                continue
            if len(df) < 60 or df4h.empty:
                continue
            prev, last = df.iloc[-2], df.iloc[-1]
            atr4h = float(df4h.atr14.iloc[-1])
            zones = market.sr_zones(df4h, df1d, float(prev.close), atr4h, top=2)
            if not zones["direncler"]:
                continue
            zone = zones["direncler"][0]
            level = zone["ust"]
            atr15 = last.atr14
            vol_ok = last.vol_avg20 == last.vol_avg20 and last.vol_avg20 and last.volume > last.vol_avg20
            if not (prev.close <= level < last.close):
                continue
            if not vol_ok or not (last.sma50 == last.sma50 and last.close > last.sma50):
                continue
            if atr15 == atr15 and atr15 and last.close - level > MAX_STRETCH_ATR * atr15:
                log.info("Scanner: %s broke %s but is stretched (chasing), skipped", coin, level)
                continue

            stop = zone["alt"] - 0.25 * atr4h
            nxt = zones["direncler"][1] if len(zones["direncler"]) > 1 else None
            target = nxt["orta"] if nxt else level + 2 * atr4h
            # Next resistance caps the move; skip candidates whose R/R could never pass the gate.
            if (target - last.close) / (last.close - stop) < 1.0:
                log.info("Scanner: %s broke %s but R/R to next resistance < 1, skipped", coin, level)
                continue
            plan = {
                "tetik": level, "teyit": level, "iptal": round(stop, 8), "hedef": round(target, 8),
                "not": (f"Tarayıcı: 4h/1d direnç {zone['alt']:.6g}–{zone['ust']:.6g} ({zone['dokunma']} dokunma) "
                        f"hacimle kapanışla kırıldı" + ("" if nxt else "; üstte yapısal direnç yok, hedef 2×ATR(4h)")),
                "otomatik": True, "pozisyon": False, "guncelleme": int(time.time()),
                "son_mum": int(last.open_time), "bekleyen_teyit": int(last.open_time),
            }
            state = store.load_state()
            if coin in state["planlar"]:
                continue
            state["planlar"][coin] = plan
            store.save_state(state)
            last_seen[coin] = time.time()
            found.append({"coin": coin, "kapanis": float(last.close), "hacim_orani": float(last.volume / last.vol_avg20),
                          **plan, "dokunma": zone["dokunma"]})
    alerts_store.save_settings(s)
    return found

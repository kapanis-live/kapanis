"""Every 15 min: check closed 15m candles against saved plan levels.

Hard events (close through tetik / iptal, teyit result, hedef hit) are detected
in code and always escalate. Soft "approaching a level" cases go to local qwen
first; only a yes from qwen escalates to DeepSeek.
"""
import logging
import time

import httpx

import config
import conversation_store as store
import llm
import market
import bist
import gate
import macro
import positions

log = logging.getLogger(__name__)


def _fmt(x):
    return f"{x:.6g}"


def detect_event(plan: dict, prev, last) -> str | None:
    """Return a description of a hard event on the last closed candle, or None."""
    tetik, teyit, iptal, hedef = (plan.get(k) for k in ("tetik", "teyit", "iptal", "hedef"))
    close, vol_ratio = last.close, last.volume / last.vol_avg20 if last.vol_avg20 else None
    vol_txt = f"hacim/ort20 = {vol_ratio:.2f}" if vol_ratio is not None else "hacim ortalaması yok"

    if plan.get("bekleyen_teyit") == int(prev.open_time) and teyit is not None:
        ok = close >= teyit
        return (f"Teyit mumu kapandı: {_fmt(close)}. Teyit seviyesi {_fmt(teyit)} "
                f"{'korundu' if ok else 'altında kapanış, teyit BOZULDU'}. {vol_txt}.")
    if iptal is not None and prev.close >= iptal > close:
        return f"15dk mum {_fmt(close)} ile İPTAL seviyesi {_fmt(iptal)} altında kapandı. {vol_txt}."
    if tetik is not None and prev.close <= tetik < close:
        return f"15dk mum {_fmt(close)} ile TETİK seviyesi {_fmt(tetik)} üstünde kapandı. {vol_txt}. Sonraki mum teyit mumu."
    if hedef is not None and prev.close < hedef <= close:  # close only; a wick through the target doesn't count
        return f"15dk mum {_fmt(close)} ile HEDEF {_fmt(hedef)} üstünde kapandı."
    return None


def near_level(plan: dict, last) -> bool:
    if not last.atr14 or last.atr14 != last.atr14:  # None or NaN
        return False
    zone = config.PROXIMITY_ATR * last.atr14
    return any(plan.get(k) is not None and abs(last.close - plan[k]) <= zone for k in ("tetik", "iptal"))


def proximity_facts(plan: dict, df) -> dict:
    """Pre-digest the numbers so the small local model only has to judge, not calculate."""
    last, back = df.iloc[-1], df.iloc[-4]
    facts = {
        "son_4_mum_fiyat_degisimi_yuzde": round((last.close / back.close - 1) * 100, 2),
        "son_mum_hacim_ortalamaya_orani": round(last.volume / last.vol_avg20, 2) if last.vol_avg20 else None,
        "rsi_simdi": round(last.rsi14, 1),
        "rsi_4_mum_once": round(back.rsi14, 1),
    }
    for key in ("tetik", "iptal"):
        if plan.get(key) is not None:
            facts[f"{key}_seviyesine_uzaklik_atr"] = round((plan[key] - last.close) / last.atr14, 2)
    return facts


def rule_should_alert(facts: dict) -> tuple[bool, str]:
    """Same rule as QWEN_PROMPT, in code."""
    change = facts["son_4_mum_fiyat_degisimi_yuzde"]
    vol = facts["son_mum_hacim_ortalamaya_orani"] or 0
    rsi_move = facts["rsi_simdi"] - facts["rsi_4_mum_once"]
    near_tetik = abs(facts.get("tetik_seviyesine_uzaklik_atr", 99)) <= config.PROXIMITY_ATR
    near_iptal = abs(facts.get("iptal_seviyesine_uzaklik_atr", 99)) <= config.PROXIMITY_ATR
    if near_tetik and change >= 0.3 and (vol > 1 or rsi_move >= 3):
        return True, f"tetiğe doğru yükseliş %{change}, hacim x{vol}, RSI {rsi_move:+.1f}"
    if near_iptal and change <= -0.3 and (vol > 1 or rsi_move <= -3):
        return True, f"iptale doğru düşüş %{change}, hacim x{vol}, RSI {rsi_move:+.1f}"
    return False, "yatay veya zayıf hareket"


async def buy_checklist(client: httpx.AsyncClient, coin: str, plan: dict, trigger_candle, last) -> dict:
    """ŞİMDİ AL check after a held confirmation candle: the shared decision gate, with the
    trigger candle's volume and the confirmation candle's close."""
    avg = trigger_candle.vol_avg20
    volume_ok = bool(avg == avg and avg and trigger_candle.volume > avg)
    g = await gate.evaluate(client, pair=f"{coin}/{config.QUOTE}", direction="ABOVE", entry=float(last.close),
                            iptal=plan.get("iptal"), hedef=plan.get("hedef"), timeframe="15m",
                            candle=last, volume_ok=volume_ok)
    return {**g, "close": g["giris"]}


async def check_plans() -> list[tuple[str, str, bool, dict | None]]:
    """Return (coin, alert text, is_close_event, buy_check) for cases that need a DeepSeek analysis.

    is_close_event False means a soft "approaching" pre-alert, which quiet hours may suppress.
    buy_check is set after a confirmation candle held: the "ŞİMDİ AL" checklist.
    """
    state = store.load_state()
    alerts = []
    async with httpx.AsyncClient() as client:
        for coin, plan in state["planlar"].items():
            if coin.upper().endswith((".IS", ".US")):  # BIST / US plans are followed in bist_signals / us_signals
                continue
            if plan.get("alarm_id"):  # the websocket alarm engine watches this plan
                continue
            try:
                df = market.add_indicators(await market.fetch_klines(client, coin + config.QUOTE, "15m"))
            except Exception as e:
                log.warning("Kline fetch failed for %s: %s", coin, e)
                continue
            if len(df) < 2:
                continue
            prev, last = df.iloc[-2], df.iloc[-1]
            candle = int(last.open_time)
            if plan.get("son_mum") == candle:
                continue
            plan["son_mum"] = candle

            event = detect_event(plan, prev, last)
            if event and "TETİK" in event:
                plan["bekleyen_teyit"] = candle
            elif event and "Teyit mumu" in event:
                plan.pop("bekleyen_teyit", None)

            if event:
                buy = None
                if "Teyit mumu" in event and "korundu" in event:
                    buy = await buy_checklist(client, coin, plan, prev, last)
                alerts.append((coin, event, True, buy))
                continue

            if near_level(plan, last) and time.time() - plan.get("son_yakinlik", 0) > config.PROXIMITY_COOLDOWN:
                plan["son_yakinlik"] = int(time.time())
                facts = proximity_facts(plan, df)
                if config.PREFILTER == "qwen":
                    verdict = await llm.qwen_should_alert(coin, facts)
                else:
                    verdict = rule_should_alert(facts)
                if verdict and verdict[0]:
                    alerts.append((coin, f"Fiyat ({_fmt(last.close)}) plan seviyesine yaklaşıyor. Ön filtre: {verdict[1]}", False, None))

    # Reload before saving: a user command may have changed plans while we awaited.
    fresh = store.load_state()
    for coin, plan in state["planlar"].items():
        if coin in fresh["planlar"]:
            for key in ("son_mum", "son_yakinlik", "bekleyen_teyit"):
                if key in plan:
                    fresh["planlar"][coin][key] = plan[key]
                else:
                    fresh["planlar"][coin].pop(key, None)
    store.save_state(fresh)
    return alerts


async def check_positions() -> list[tuple[str, dict, float]]:
    """Return (kind, position, close) for stop / target closes on open positions.

    Alerts once per crossing: the flag resets only when price closes back on the safe side.
    """
    events = []
    async with httpx.AsyncClient() as client:
        for pos in positions.open_positions():
            if pos.get("piyasa") == "DIGER" or (pos["stop"] is None and pos["hedef"] is None):
                continue  # nothing to check (gold/FX savings, holdings without levels)
            try:
                if pos.get("piyasa") == "ABD":
                    import us
                    df = await us.fetch(client, pos["symbol"], "1d")
                elif pos.get("piyasa") == "BIST":
                    # Medium/long-term: a BIST stop or target counts on the DAILY close, not an hourly one.
                    df = await bist.fetch(client, pos["symbol"], "1d")
                else:
                    df = await market.fetch_klines(client, pos["symbol"], pos["timeframe"], limit=3)
            except Exception as e:
                log.warning("Position check failed for %s: %s", pos["pair"], e)
                continue
            if df.empty:
                continue
            last = df.iloc[-1]
            candle = int(last.open_time)
            if pos.get("son_kontrol_mum") == candle:
                continue
            changes = {"son_kontrol_mum": candle}
            close = float(last.close)
            below_stop = pos["stop"] is not None and close < pos["stop"]
            at_target = pos["hedef"] is not None and close >= pos["hedef"]
            if below_stop and not pos.get("stop_uyarildi"):
                events.append(("stop", pos, close))
            if at_target and not pos.get("hedef_uyarildi"):
                events.append(("hedef", pos, close))
            changes["stop_uyarildi"] = below_stop
            changes["hedef_uyarildi"] = at_target
            positions.update(pos["id"], **changes)
    return events

"""Close-only price alerts driven by Binance kline websocket.

Only a closed candle ("x": true) is ever evaluated, and only its CLOSE price.
Intra-candle high/low never triggers anything.
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Awaitable, Callable

import httpx
from websockets.asyncio.client import connect

import alerts_store as store
import config
import market

log = logging.getLogger(__name__)

TriggerCallback = Callable[[str, dict, "object", dict, list[str]], Awaitable[None]]
NoticeCallback = Callable[[str, dict, str], Awaitable[None]]


def _fmt(x) -> str:
    return f"{x:.6g}"


def crossed(direction: str, close: float, level: float) -> bool:
    return close > level if direction == "ABOVE" else close < level


def warnings_for(alert: dict, row) -> list[str]:
    out = []
    if alert.get("hacim_sart"):
        avg = row.vol_avg20
        if avg != avg or not avg:  # NaN or 0
            out.append("hacim teyidi yok, doğrulanamadı (Volume MA20 hesaplanamadı)")
        elif row.volume <= avg:
            out.append(f"hacim teyidi yok, doğrulanamadı (hacim {_fmt(row.volume)} ≤ MA20 {_fmt(avg)})")
    atr = row.atr14
    if alert.get("iptal") is not None and atr == atr and atr:
        dist = abs(alert["tetik"] - alert["iptal"])
        if dist < atr:
            out.append(f"gürültüye takılma riski yüksek (tetik-iptal {_fmt(dist)} < 1×ATR {_fmt(atr)})")
    return out


class AlertEngine:
    def __init__(self, on_trigger: TriggerCallback, on_notice: NoticeCallback):
        self.on_trigger = on_trigger
        self.on_notice = on_notice
        self._changed = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()
        self._state_lock = asyncio.Lock()

    def refresh(self):
        """Call after alerts.json changes so the websocket resubscribes."""
        self._changed.set()

    async def run(self):
        url_index = 0
        while True:
            wanted = sorted(store.streams())
            self._changed.clear()
            if not wanted:
                await self._changed.wait()
                continue
            names = "/".join(f"{s.lower()}@kline_{tf}" for s, tf in wanted)
            url = config.BINANCE_WS_URLS[url_index % len(config.BINANCE_WS_URLS)] + names
            try:
                async with connect(url, ping_interval=20, ping_timeout=20) as ws:
                    log.info("Websocket connected: %s", names)
                    closer = asyncio.create_task(self._close_on_change(ws))
                    try:
                        async for raw in ws:
                            k = json.loads(raw)["data"]["k"]
                            if k["x"]:  # closed candles only
                                self._spawn(self._on_close(k))
                    finally:
                        closer.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("Websocket error (%s), reconnecting in 5 s", e)
                url_index += 1
                await asyncio.sleep(5)

    async def _close_on_change(self, ws):
        await self._changed.wait()
        await ws.close()

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task):
        self._tasks.discard(task)
        if not task.cancelled() and task.exception():
            log.error("Alert close handling failed (the Telegram message may be missing)", exc_info=task.exception())

    async def _closed_frame(self, symbol: str, tf: str, open_time: int):
        """REST candles up to and including the websocket's closed candle."""
        async with httpx.AsyncClient() as client:
            for _ in range(4):
                df = market.add_indicators(await market.fetch_klines(client, symbol, tf))
                if not df.empty and int(df.iloc[-1].open_time) == open_time:
                    return df
                await asyncio.sleep(2)
        log.warning("REST has no closed candle %s %s %s yet; using latest available", symbol, tf, open_time)
        return df

    async def _on_close(self, k: dict):
        symbol, tf, close = k["s"], k["i"], float(k["c"])
        try:
            df = await self._closed_frame(symbol, tf, int(k["t"]))
        except Exception:
            log.exception("Kline fetch failed for %s %s", symbol, tf)
            return
        row = df.iloc[-1]
        now = store.now_tr()

        fired, notices = [], []
        async with self._state_lock:
            alerts = store.load_alerts()
            for pair, items in alerts.items():
                if store.pair_to_symbol(pair) != symbol:
                    continue
                for a in items:
                    if a["timeframe"] != tf or a["durum"] not in store.ACTIVE_STATES:
                        continue
                    direction = a["yon"]

                    # After a trigger: track iptal / hedef on closes.
                    if a["tetikler"]:
                        if a.get("iptal") is not None and crossed("BELOW" if direction == "ABOVE" else "ABOVE",
                                                                  close, a["iptal"]):
                            a["durum"], a["iptal_nedeni"] = "iptal", "kapanis"
                            notices.append((pair, dict(a), f"❌ {pair} #{a['id']}: {tf} mum {_fmt(close)} ile "
                                                           f"İPTAL {_fmt(a['iptal'])} ötesinde kapandı. Alarm iptal."))
                            continue
                        if a.get("hedef") is not None and (close >= a["hedef"] if direction == "ABOVE"
                                                           else close <= a["hedef"]):
                            a["durum"] = "pasif"
                            notices.append((pair, dict(a), f"🎯 {pair} #{a['id']}: {tf} mum {_fmt(close)} ile "
                                                           f"HEDEF {_fmt(a['hedef'])} kapanışla görüldü. Alarm pasif."))
                            continue

                    if a["durum"] == "tetiklendi":
                        cooldown = store.parse_duration(a["cooldown"])
                        last = datetime.fromisoformat(a["son_tetik_zamani"])
                        if now - last < cooldown:
                            continue
                        a["durum"] = "aktif"

                    if crossed(direction, close, a["tetik"]):
                        a["durum"] = "tetiklendi"
                        a["son_tetik_zamani"] = now.isoformat()
                        a["tetikler"].append(now.isoformat())
                        fired.append((pair, dict(a), warnings_for(a, row)))
            store.save_alerts(alerts)

        if notices:  # iptal/pasif alerts leave the stream set
            self.refresh()
        for pair, a, text in notices:
            log.info(text)
            await self.on_notice(pair, a, text)
        candle = {"kapanis": close, "hacim": float(k["v"]), "acilis_zamani": int(k["t"])}
        for pair, a, warns in fired:
            log.info("Alert fired %s #%s close=%s warnings=%s", pair, a["id"], close, warns)
            await self.on_trigger(pair, a, df, candle, warns)

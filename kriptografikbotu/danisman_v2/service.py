"""Kripto Danışman V2: one call from "BTC, AL PLANI" to the answer. Decision support only; no order is ever sent.

    Binance candles -> MarketSnapshot -> rule engine (planner / protection) -> three AI analysts -> consensus -> plan

    analyze(symbol, portfolio, ...)   one coin: the snapshot, the engine's result, the verdicts, the consensus and,
                                      when everything agrees, the stop-limit plan; for a held coin the protection plan
    scan(portfolio, ...)              the most traded pairs through the rule engine (no AI calls), grouped and ordered

The exact prices are the rule engine's. The analysts only decide, together with the engine's own blocks, whether a
plan is released (consensus.py). Every run is logged to the paper log; its outcome never feeds back into a rule.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

import httpx

import danisman as d

from . import agents, config as cfg, consensus, macro as macro_mod, planner, protection, research, snapshot as snap_mod

FILTER_SECONDS = 6 * 3600
_filters: dict[str, tuple[float, dict]] = {}
SCAN_ORDER = {"READY_TO_WATCH": 0, "WAIT_FOR_RETEST": 1, "RECLAIM_WATCH": 2, "WAIT_FOR_BREAKOUT": 3, "PULLBACK_SETUP": 4,
              "BLOCKED_SETUP": 5, "NO_SETUP": 6, "AVOID": 7}
ORDER_TR = ["uygulanabilir tam kurulum", "geri test planı tam", "geri alış izlemesi", "kırılım planı (bekleyen emir)",
            "eksik kurulum", "engelli kurulum", "kurulum yok", "uzak dur"]


def versions() -> dict:
    return {"advisor_version": cfg.ADVISOR_VERSION, "ruleset_hash": research.ruleset_hash(), **d.code_version()}


# ---------------- exchange order rules ----------------
def parse_filters(info: dict) -> dict | None:
    """One symbol of exchangeInfo -> tick_size, step_size, min_qty, min_notional."""
    f = {x["filterType"]: x for x in info.get("filters") or []}
    try:
        notional = f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}
        out = {"tick_size": float(f["PRICE_FILTER"]["tickSize"]), "step_size": float(f["LOT_SIZE"]["stepSize"]),
               "min_qty": float(f["LOT_SIZE"]["minQty"]), "min_notional": float(notional.get("minNotional") or 0.0)}
    except (KeyError, ValueError, TypeError):
        return None
    return out if out["tick_size"] > 0 else None


async def exchange_filters(client: httpx.AsyncClient, pairs: list[str]) -> dict[str, dict]:
    """Order rules of the pairs, kept for FILTER_SECONDS. A pair whose rules cannot be read is simply missing
    (the planner then refuses to price an order: DATA_ERROR)."""
    now = time.monotonic()
    need = [p for p in pairs if p not in _filters or now - _filters[p][0] > FILTER_SECONDS]
    for k in range(0, len(need), 40):
        chunk = need[k:k + 40]
        try:
            info = await d._get_json(client, "/api/v3/exchangeInfo",
                                     {"symbols": json.dumps(chunk, separators=(",", ":"))}, timeout=30)
        except Exception:
            continue
        for row in info.get("symbols") or []:
            parsed = parse_filters(row)
            if parsed:
                _filters[row["symbol"]] = (now, parsed)
    return {p: _filters[p][1] for p in pairs if p in _filters}


# ---------------- one coin ----------------
def _v1_reference(data: dict, portfolio_value, asof_ms) -> dict | None:
    try:
        r = d.analyze(data, portfolio_value, asof_ms=asof_ms)
    except Exception:
        return None
    return {"decision": r["decision"], "scenario": r["scenario"], "setup_id": r["setup_id"], "reason_code": r["reason_code"],
            "pullback": r["pullback"], "ruleset_hash": d.ruleset_hash()}


def with_position(portfolio: dict | None, symbol: str, position: dict | None) -> dict | None:
    """The portfolio with one position written in by hand (the admin typed the entry instead of the bot knowing it)."""
    if not position:
        return portfolio
    p = dict(portfolio or {})
    rest = [h for h in p.get("holdings") or [] if h["symbol"].upper() != symbol]
    p["holdings"] = rest + [{"symbol": symbol, "quantity": position.get("quantity"), "entry_price": position["entry_price"],
                             "initial_stop": position.get("initial_stop"), "stop": position.get("stop"), "value": None,
                             "initial_stop_source": position.get("initial_stop_source"),
                             "opened_at": position.get("opened_at")}]
    return p


async def analyze(symbol: str, portfolio: dict | None = None, *, position: dict | None = None, state: dict | None = None,
                  manual_stop: float | None = None, macro=None, clients: dict | None = None, with_ai: bool = True,
                  source: str = "api", data: dict | None = None, asof_ms: int | None = None, log_paper: bool = True) -> dict:
    """One full run.

    portfolio: see snapshot.portfolio_facts. position: {"entry_price", "quantity", "initial_stop"} typed by the admin.
    state: what was stored for this position by an earlier run. macro: an OpenBBService, a ready MacroSnapshot dict,
    or None (macro is then NOT_REQUESTED). clients: agents.build_clients() result. data: fetched candles instead of
    the network (tests, replays); it must carry data["filters"]."""
    started = time.monotonic()
    symbol = symbol.upper().replace("/", "").removesuffix("USDT") or "BTC"
    portfolio = with_position(portfolio, symbol, position)
    timing = {}

    async def market():
        t = time.monotonic()
        if data is not None:
            return data
        held = [h["symbol"] for h in (portfolio or {}).get("holdings") or []]
        async with httpx.AsyncClient() as client:
            got = await d.fetch(symbol, held, client=client)
            got["filters"] = (await exchange_filters(client, [got["pair"]])).get(got["pair"])
        timing["market_ms"] = int((time.monotonic() - t) * 1000)
        return got

    async def macro_snapshot():
        t = time.monotonic()
        if macro is None or isinstance(macro, dict):
            return macro
        try:     # the read itself is not cancelled: it goes on and fills the cache for the next analysis
            out = await asyncio.wait_for(asyncio.shield(asyncio.ensure_future(macro.get_macro_snapshot())), cfg.MACRO_WAIT_SECONDS)
        except asyncio.TimeoutError:
            out = macro_mod.degraded(f"makro {cfg.MACRO_WAIT_SECONDS:g} sn içinde gelmedi; okuma arka planda sürüyor")
        except Exception as e:           # macro can never take the technical report down
            out = macro_mod.degraded(str(e)[:200])
        timing["macro_ms"] = int((time.monotonic() - t) * 1000)
        return out

    raw, macro_snap = await asyncio.gather(market(), macro_snapshot())
    frozen = snap_mod.build(raw, portfolio, macro_snap, asof_ms=asof_ms,
                            v1_reference=_v1_reference(raw, (portfolio or {}).get("value"), asof_ms))
    s = frozen.data()
    engine = planner.build_buy_plan(s)
    holding = s["portfolio"]["holding_exists"]
    sell = protection.build_protection_plan(s, state, manual_stop) if holding else None
    verdicts = None
    if with_ai:
        t = time.monotonic()
        verdicts = await agents.run_agents(clients if clients is not None else agents.build_clients(), s, engine, sell)
        timing["agents_ms"] = int((time.monotonic() - t) * 1000)
    cons = consensus.decide(verdicts, engine)
    buy_plan = engine["plan"] if cons["plan_released"] else None
    final = sell["action"] if sell and not sell.get("error") else cons["final"]
    timing["total_ms"] = int((time.monotonic() - started) * 1000)
    run = {
        "symbol": s["symbol"], "pair": s["pair"], "mode": "POSITION" if holding else "NEW",
        "market_timestamp": s["market_timestamp"], "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshot_hash": frozen.hash, "macro_snapshot_hash": (s.get("macro") or {}).get("macro_snapshot_hash"), **versions(),
        "final": final, "engine": {k: v for k, v in engine.items() if k != "plan"},
        "agents": verdicts, "consensus": cons,
        "buy_plan": buy_plan,
        # the engine's levels when the committee (or a missing analyst) did not release them: information, not an order plan
        "unreleased_plan": None if buy_plan else engine["plan"],
        "sell_plan": sell,
        "why_not_trade": [] if buy_plan else (engine["why_not"] + cons["reasons"]),
        "models": None if not verdicts else {r: {"provider": v.get("provider"), "model": v.get("model")} for r, v in verdicts.items()},
        "latency": {**timing, **({r.lower() + "_ai_ms": v.get("latency_ms") for r, v in verdicts.items()} if verdicts else {})},
        "snapshot": s, "order_sent": False, "auto_trading": False,
    }
    run["text"] = format_run(run)
    if log_paper:
        run["paper_logged"] = research.log_runs([research.paper_row(s, engine, cons, source)])
    return run


def audit_doc(run: dict, admin_user_hash: str | None) -> dict:
    """The run as it is stored in advisor_consensus_runs: the decision and its provenance, without the candles."""
    cons, agents_ = run["consensus"], run["agents"] or {}
    return {"symbol": run["symbol"], "pair": run["pair"], "mode": run["mode"], "market_timestamp": run["market_timestamp"],
            "generated_at": run["generated_at"], "snapshot_hash": run["snapshot_hash"],
            "technical_verdict": cons["technical_verdict"], "risk_verdict": cons["risk_verdict"],
            "regime_verdict": cons["regime_verdict"], "final_consensus": cons["consensus"], "final": run["final"],
            "plan_released": cons["plan_released"], "consensus_reasons": cons["reasons"],
            "engine_status": run["engine"]["status"], "engine_setup": run["engine"]["setup"],
            "engine_blocks": [b["code"] for b in run["engine"]["blocks"]],
            "agents": {r: {k: v.get(k) for k in ("status", "verdict", "confidence", "reason", "error", "attempts")}
                       for r, v in agents_.items()},
            "buy_plan": run["buy_plan"], "unreleased_plan": run["unreleased_plan"],
            "sell_plan": None if not run["sell_plan"] else {k: v for k, v in run["sell_plan"].items() if k != "new_state"},
            "models": run["models"], "latency": run["latency"], "macro_snapshot_hash": run["macro_snapshot_hash"],
            "ruleset_hash": run["ruleset_hash"], "advisor_version": run["advisor_version"], "git_commit": run["git_commit"],
            "working_tree_dirty": run["working_tree_dirty"], "admin_user_hash": admin_user_hash, "order_sent": False}


def format_run(run: dict) -> str:
    """The short answer, as text."""
    s, p = run["snapshot"], d._p
    st = s["structure"]
    arrow = {"STRONG_UP": "↑↑", "UP": "↑", "RANGE": "→", "DOWN": "↓", "STRONG_DOWN": "↓↓", "INSUFFICIENT_HISTORY": "?"}
    quote = s["quote_asset"]
    lines = [f"{s['symbol']}/{quote}", "", f"Final: {run['final']}",
             "Trend: " + " · ".join(f"{tf} {arrow[s['timeframes'][tf]['trend']]}" for tf in d.TFS),
             f"BTC rejimi: {s['btc']['regime']}", f"Makro: {(s.get('macro') or {}).get('macro_status')}"
             + (" · temkin" if (s.get("macro") or {}).get("caution") else "")]
    if st["nearest_resistance"]:
        lines.append(f"Direnç: {p(st['nearest_resistance']['low'])}-{p(st['nearest_resistance']['high'])}")
    if st["nearest_support"]:
        lines.append(f"Destek: {p(st['nearest_support']['low'])}-{p(st['nearest_support']['high'])}")
    plan = run["buy_plan"]
    if plan:
        lines += ["", f"AL planı ({plan['setup']}, kanıt durumu: araştırma):", f"Stop (tetik) {p(plan['trigger'])}",
                  f"Limit {p(plan['limit'])}", f"İlk teknik stop {p(plan['technical_stop'])}",
                  f"Geçersizlik {p(plan['technical_invalidation'])}"]
        pos = plan["position"]
        lines.append(f"Pozisyon: {pos['suggested_notional']:g} {quote}" if pos else f"Pozisyon: — ({plan['position_note']})")
    elif run["mode"] == "NEW":
        lines += ["", "AL planı yok.", "Sebep:"] + [f"- {x}" for x in run["why_not_trade"][:6]]
    sell = run["sell_plan"]
    if sell and not sell.get("error"):
        lines += ["", f"POZİSYON KORUMA: {sell['action_tr']} [{sell['state']}]",
                  f"Giriş {p(sell['entry_price'])} · şimdi {p(sell['current_price'])} · "
                  + (f"~{sell['current_R']:+g}R (tahmini: ilk stop kayıtlı değil)" if sell["current_R_estimated"] else f"{sell['current_R']:+g}R"),
                  f"Kâr al: {p(sell['take_profit']) if sell['take_profit'] else '—'} ({sell['take_profit_source']})",
                  f"Zarar durdur: {p(sell['stop_loss'])} ({sell['stop_source']})",
                  f"Geçersizlik: {p(sell['technical_invalidation'])} · nefes payı {sell['breathing_room_atr15']:g} ATR(15m)"]
    lines += ["", "Not: Emir gönderilmedi."]
    return "\n".join(lines)


# ---------------- scan ----------------
def scan_row(s: dict, engine: dict, held: bool) -> dict:
    plan = engine["plan"] or engine["withheld_plan"] or {}
    st, i1, i15 = s["structure"], s["timeframes"]["1h"]["indicators"] or {}, s["timeframes"]["15m"]["indicators"] or {}
    return {"symbol": s["symbol"], "pair": s["pair"], "current_price": s["current_price"], "status": engine["status"],
            "status_tr": engine["status_tr"], "group": engine["group"], "setup": engine["setup"],
            "underlying_status": engine.get("underlying_status"), "actionable": engine["actionable"],
            "trend_15m": st["trend_15m"], "trend_1h": st["trend_1h"], "trend_4h": st["trend_4h"], "trend_1d": st["trend_1d"],
            "nearest_resistance": st["nearest_resistance"] and [st["nearest_resistance"]["low"], st["nearest_resistance"]["high"]],
            "nearest_support": st["nearest_support"] and [st["nearest_support"]["low"], st["nearest_support"]["high"]],
            "plan_type": plan.get("type"), "trigger": plan.get("trigger"), "limit": plan.get("limit"),
            "technical_stop": plan.get("technical_stop"), "technical_invalidation": plan.get("technical_invalidation"),
            "stop_distance_pct": plan.get("stop_distance_pct"), "stop_distance_atr15": plan.get("stop_distance_atr15"),
            "take_profit_reference": plan.get("take_profit_reference"), "take_profit_source": plan.get("take_profit_source"),
            "retest_zone": plan.get("retest_zone") or st.get("retest_zone"),
            "distance_to_trigger_atr15": plan.get("distance_to_trigger_atr15"),
            "rsi_1h": i1.get("rsi14"), "atr_1h": i1.get("atr14"), "volume_ratio_15m": i15.get("volume_ratio"),
            "blocks": [b["code"] for b in engine["blocks"]], "waits": [w["code"] for w in engine["waits"]],
            "warnings": [w["code"] for w in engine["warnings"]],
            "why_not": engine["why_not"][:3], "next_review": engine["next_review"], "held": held,
            "evidence_status": engine["evidence_status"],
            "consensus": "NOT_REQUESTED",       # a scan asks no model: analyze the coin to get the committee's answer
            "market_timestamp": s["market_timestamp"]}


def rank(row: dict, order: int) -> tuple[tuple, list[str]]:
    """Explainable order, no combined score: the kind of setup first, then how close the trigger is, then how many
    warnings it carries, then the traded volume (the scan's own order)."""
    tier = SCAN_ORDER[row["group"]]
    if row["group"] == "WAIT_FOR_RETEST" and row["plan_type"] != "RETEST_WAIT":
        tier = 4                                  # a retest wait without a complete stop is an incomplete setup
    dist = row["distance_to_trigger_atr15"]
    far = 999.0 if dist is None else abs(dist)
    words = [ORDER_TR[tier], "tetik uzaklığı belirsiz" if dist is None else f"tetiğe {far:g} ATR(15m)",
             f"{len(row['warnings'])} uyarı"]
    return (tier, far, len(row["warnings"]), order), words


async def scan(portfolio: dict | None = None, limit: int = d.SCAN_LIMIT, macro=None, symbols: list | None = None,
               fetcher=None, asof_ms: int | None = None, paper: str | None = None) -> dict:
    """The most traded pairs (and the holdings) through the rule engine. No AI call is made here: every row says
    consensus NOT_REQUESTED, and a plan shown in a scan is the engine's candidate, not a released plan.
    fetcher: async coin -> fetch() data with data["filters"], instead of the network (tests, replays)."""
    held = [h["symbol"].upper() for h in (portfolio or {}).get("holdings") or []]
    client = None
    macro_snap = macro if macro is None or isinstance(macro, dict) else await macro.get_macro_snapshot()
    try:
        if fetcher is None:
            client = httpx.AsyncClient()
            pairs = [(x, None) if isinstance(x, str) else tuple(x) for x in symbols] if symbols else await d.universe(client, limit)
            quote = dict(pairs)
            b = await asyncio.gather(*[d._klines(client, "BTCUSDT", tf) for tf in ("15m", "1h", "4h")])
            btc = {"15m": b[0], "1h": b[1], "4h": b[2]}

            async def fetcher(coin):
                q = quote.get(coin)
                got = await d.fetch(coin, client=client, btc=btc, quotes=(q,) if q else d.SCAN_QUOTES)
                got["filters"] = (await exchange_filters(client, [got["pair"]])).get(got["pair"])
                return got
            coins = [c for c, _ in pairs]
            await exchange_filters(client, [c + q for c, q in pairs if q])          # one request for all of them
        else:
            coins = [x if isinstance(x, str) else x[0] for x in symbols or []]
        coins = list(dict.fromkeys(held + [c.upper() for c in coins]))
        gate = asyncio.Semaphore(d.SCAN_PARALLEL)

        async def one(coin):
            async with gate:
                try:
                    return coin, await fetcher(coin), None
                except Exception as e:
                    return coin, None, e
        got = await asyncio.gather(*[one(c) for c in coins])
    finally:
        if client is not None:
            await client.aclose()
    # exposure limits apply in a scan too; correlation needs each holding's candles and is left to the single analysis
    rows, failed, papers = [], [], []
    for order, (coin, data, err) in enumerate(got):
        if err is None:
            try:
                s = snap_mod.build(data, portfolio, macro_snap, asof_ms=asof_ms).data()
                engine = planner.build_buy_plan(s)
                row = scan_row(s, engine, coin in held)
                row["rank_key"], row["rank_reasons"] = rank(row, order)
                rows.append(row)
                papers.append(research.paper_row(s, engine, None, paper or "v2-scan"))
                continue
            except ValueError as e:
                err = e
        failed.append({"symbol": coin, "group": "NO_SETUP", "held": coin in held,
                       "reason": "veri yetersiz" if isinstance(err, ValueError) else "borsa verisi alınamadı"})
    rows.sort(key=lambda r: r.pop("rank_key"))
    out = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "market_timestamp": rows[0]["market_timestamp"] if rows else None, "scanned": len(rows) + len(failed),
           "groups": {g: [r["symbol"] for r in rows if r["group"] == g] for g in planner.GROUPS},
           "results": rows, "failed": failed, "ranking": ORDER_TR,
           "macro_status": None if not macro_snap else macro_snap.get("macro_status"),
           "note": "Tarama yapay zekâ çağırmaz: satırlardaki seviyeler kural motorunun adayıdır, onaylı plan değildir. "
                   "Bir coini ANALİZ ET ile konsensüsten geçir.", **versions(), "order_sent": False}
    if paper:
        out["paper_logged"] = research.log_runs(papers)
    return out

"""Kripto Danışman V2 over HTTP, admin only. The engine is the bot's danisman_v2 package (loaded from the bot folder).

GET  /api/admin/advisor/health             versions, ruleset, thresholds, which analysts and OpenBB are configured
POST /api/admin/advisor/analyze            {"symbol": "BTC"}: snapshot, rule engine, three AI analysts, consensus, plans
POST /api/admin/advisor/buy-plan           the same run, answered as "is there a stop-limit buy plan?"
POST /api/admin/advisor/sell-plan          position protection: take profit, stop, invalidation, current R
POST /api/admin/advisor/scan               the most traded pairs through the rule engine (no AI call)
GET  /api/admin/advisor/macro              the OpenBB MacroSnapshot
GET  /api/admin/advisor/paper-stats        exit styles and whipsaw statistics from the paper log
GET  /api/admin/advisor/consensus-history  the stored runs

Who may call: the session is verified on the server (Clerk token or the legacy cookie) and the user document comes from
the database. The caller must be the owner and, when ADMIN_EMAILS is set, that verified e-mail must be in the list.
Nothing the browser sends (an e-mail, a role, an isAdmin flag, a header) takes part in that decision.

No endpoint places an order, and no response carries an API key: the AI and OpenBB keys are read from this
process's environment and used only for the outgoing calls.
"""
import asyncio
import hashlib
import importlib
import importlib.util
import os
import sys
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import advisor_api
import identity
import limits

ANALYZE_PER_MINUTE = 6            # each run calls three models
SCAN_PER_MINUTE = 2
HISTORY_LIMIT = 100
CRYPTO_QUOTES = ("USDT", "USDC", "FDUSD")
_openbb = None


def engine():
    """danisman_v2.service, loaded by path next to danisman.py (which it imports)."""
    advisor_api.engine()
    if "danisman_v2" not in sys.modules:
        pkg = advisor_api.BOT_DIR / "danisman_v2"
        if not (pkg / "__init__.py").exists():
            raise HTTPException(status_code=503, detail="Danışman V2 bu sunucuda kurulu değil.")
        spec = importlib.util.spec_from_file_location("danisman_v2", pkg / "__init__.py", submodule_search_locations=[str(pkg)])
        module = importlib.util.module_from_spec(spec)
        sys.modules["danisman_v2"] = module
        try:
            spec.loader.exec_module(module)
            importlib.import_module("danisman_v2.service")
        except Exception as e:
            for name in [n for n in sys.modules if n == "danisman_v2" or n.startswith("danisman_v2.")]:
                sys.modules.pop(name, None)
            raise HTTPException(status_code=503, detail=f"Danışman V2 yüklenemedi: {str(e)[:120]}")
    return importlib.import_module("danisman_v2.service")


def openbb():
    """One OpenBBService for the process: its cache is what keeps a coin analysis from re-reading the calendar."""
    global _openbb
    if _openbb is None:
        _openbb = importlib.import_module("danisman_v2.macro").OpenBBService()
    return _openbb


def ai_clients() -> dict:
    return importlib.import_module("danisman_v2.agents").build_clients()


def admin_emails() -> set[str]:
    return {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}


def is_admin(user: dict) -> bool:
    """The owner, and on the ADMIN_EMAILS list when there is one. user: the database document of a verified session."""
    if not identity.is_owner(user):
        return False
    if user.get("clerk_id") and not user.get("email_verified"):
        return False
    allowed = admin_emails()
    return not allowed or (user.get("email") or "").lower() in allowed


def user_hash(user: dict) -> str:
    return hashlib.sha256(f"{user.get('id')}|{(user.get('email') or '').lower()}".encode()).hexdigest()[:16]


class AnalyzeBody(BaseModel):
    symbol: str
    portfolio_usdt: Optional[float] = None     # typed portfolio size; replaces the bot's own portfolio for this run
    use_portfolio: bool = True                 # read the owner's holdings (the bot's portfolio)
    entry_price: Optional[float] = None        # a position typed by hand
    quantity: Optional[float] = None
    initial_stop: Optional[float] = None
    manual_stop: Optional[float] = None        # overrides the "stop only moves up" rule for this run
    with_ai: bool = True


class ScanBody(BaseModel):
    limit: Optional[int] = None
    portfolio_usdt: Optional[float] = None
    use_portfolio: bool = True


def _positive(v, name: str):
    if v is not None and not v > 0:
        raise HTTPException(status_code=400, detail=f"{name} sıfırdan büyük olmalı.")
    return v


async def portfolio_context(db, typed_value: float | None, use_portfolio: bool) -> dict | None:
    """The owner's portfolio as the risk rules need it, from the bot's last push (extras). Everything in USD.
    value covers every market and the cash only when the TL holdings could be converted (total_known)."""
    doc = (await db.extras.find_one({"id": "extras"}, {"_id": 0, "portfoy": 1, "usdtry": 1, "nakit": 1})) if use_portfolio else None
    rows = (doc or {}).get("portfoy") or []
    usdtry, cash = (doc or {}).get("usdtry"), (doc or {}).get("nakit") or {}
    holdings = []
    for g in rows:
        if g.get("piyasa") != "KRIPTO" or not g.get("adet"):
            continue
        lots = g.get("pozlar") or []
        one = lots[0] if len(lots) == 1 else {}          # several buys of one coin: the first stop of the whole is not known
        holdings.append({"symbol": str(g["ad"]).split("/")[0].upper(), "value": g.get("deger"), "quantity": g["adet"],
                         "entry_price": g["maliyet"] / g["adet"] if g.get("maliyet") else None,
                         "initial_stop": one.get("stop_ilk"), "stop": one.get("stop"),
                         "opened_at": min((x.get("acilis") for x in lots if x.get("acilis")), default=None)})
    if typed_value:
        return {"value": float(typed_value), "cash": None, "total_known": False, "holdings": holdings}
    if not doc:
        return None
    usd = sum(g.get("deger") or 0 for g in rows if g.get("para") != "TL") + (cash.get("KRIPTO") or 0) + (cash.get("ABD") or 0)
    tl = sum(g.get("deger") or 0 for g in rows if g.get("para") == "TL") + (cash.get("BIST") or 0)
    known = bool(usdtry) or not tl
    total = usd + (tl / usdtry if usdtry and tl else 0.0)
    return {"value": total or None, "cash": cash.get("KRIPTO"), "total_known": known and bool(total), "holdings": holdings}


def matches_plan(entry, plan: dict) -> bool:
    """Was this position bought on that plan? Its entry lies between the plan's trigger and limit, give or take
    PLAN_ENTRY_MATCH_PCT, and above the plan's stop."""
    if not entry:
        return False
    tol = importlib.import_module("danisman_v2.config").PLAN_ENTRY_MATCH_PCT / 100
    return plan["technical_stop"] < entry and plan["trigger"] * (1 - tol) <= entry <= plan["limit"] * (1 + tol)


def _slim(run: dict) -> dict:
    """The run for the browser: the candle tails stay on the server (the analysts read them; the panel does not draw them)."""
    out = dict(run)
    snap = dict(out["snapshot"])
    snap["timeframes"] = {tf: {k: v for k, v in f.items() if k != "candles"} for tf, f in snap["timeframes"].items()}
    out["snapshot"] = snap
    return out


def build_router(get_db, current_user) -> APIRouter:
    r = APIRouter(prefix="/api/admin/advisor")

    async def require_admin(user: dict = Depends(current_user)) -> dict:
        if not is_admin(user):
            raise HTTPException(status_code=403, detail="Bu bölüm yalnız yöneticiye açık.")
        return user

    async def execute(body: AnalyzeBody, user: dict, source: str) -> dict:
        svc = engine()
        symbol = advisor_api._symbol(body.symbol)
        for name, v in (("Portföy", body.portfolio_usdt), ("Giriş fiyatı", body.entry_price), ("Adet", body.quantity),
                        ("İlk stop", body.initial_stop), ("Stop", body.manual_stop)):
            _positive(v, name)
        if body.initial_stop and body.entry_price and body.initial_stop >= body.entry_price:
            raise HTTPException(status_code=400, detail="İlk stop giriş fiyatının altında olmalı.")
        limits.check_user(user["id"], "advisor-v2", ANALYZE_PER_MINUTE)
        db = get_db()
        portfolio = await portfolio_context(db, body.portfolio_usdt, body.use_portfolio)
        position = None if not body.entry_price else {"entry_price": body.entry_price, "quantity": body.quantity,
                                                      "initial_stop": body.initial_stop}
        state = await db.advisor_positions.find_one({"symbol": symbol}, {"_id": 0})
        if not state:       # a position that is the fill of the last released plan takes that plan's stop as its first stop
            plan = await db.advisor_plans.find_one({"symbol": symbol}, {"_id": 0})
            held = position or next((h for h in (portfolio or {}).get("holdings") or [] if h["symbol"] == symbol), None)
            if plan and held and not held.get("initial_stop") and matches_plan(held.get("entry_price"), plan):
                held.update(initial_stop=plan["technical_stop"], initial_stop_source="V2_PLAN")
        d = svc.d
        try:
            run = await svc.analyze(symbol, portfolio, position=position, state=state, manual_stop=body.manual_stop,
                                    macro=openbb(), clients=ai_clients() if body.with_ai else None, with_ai=body.with_ai,
                                    source=source)
        except d.NoPair:
            raise HTTPException(status_code=404, detail=f"{symbol}: Binance'te USDT/USDC/FDUSD/BTC paritesi yok.")
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Borsa verisi alınamadı: {str(e)[:120]}")
        await db.advisor_consensus_runs.insert_one(svc.audit_doc(run, user_hash(user)))
        if run["buy_plan"]:      # remembered so that the trade's R can later be measured from its real first stop
            p = run["buy_plan"]
            await db.advisor_plans.update_one({"symbol": symbol}, {"$set": {
                "symbol": symbol, "trigger": p["trigger"], "limit": p["limit"], "technical_stop": p["technical_stop"],
                "technical_invalidation": p["technical_invalidation"], "setup": p["setup"], "generated_at": run["generated_at"],
                "snapshot_hash": run["snapshot_hash"], "ruleset_hash": run["ruleset_hash"]}}, upsert=True)
        sell = run["sell_plan"]
        if sell and sell.get("new_state"):
            await db.advisor_positions.update_one(
                {"symbol": symbol}, {"$set": {**sell["new_state"], "updated_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
        return _slim(run)

    @r.get("/health")
    async def health(deep: bool = False, user: dict = Depends(require_admin)):
        svc = engine()
        cfg = importlib.import_module("danisman_v2.config")
        agents = importlib.import_module("danisman_v2.agents")
        ob = openbb()
        clients = ai_clients()
        allowed = admin_emails()
        return {"status": "ok", **svc.versions(), "thresholds": cfg.public(), "policy": cfg.policy(), "timeouts": cfg.timeouts(),
                "analysts": agents.describe(clients),               # provider and model names only, never a key
                "analysts_configured": all(c is not None for c in clients.values()),
                "model_diversity": agents.diversity(clients),       # three roles; how many different models stand behind them
                # configured or not, never the value
                "providers_configured": {name.lower(): bool(os.environ.get(f"{name}_API_KEY"))
                                         for name in ("DEEPSEEK", "NVIDIA", "KIMI", "GLM", "OPENAI")},
                "openbb": await ob.healthcheck() if deep else {"mode": ob.mode()},
                "admin_list_set": bool(allowed),
                # this session, as the server sees it (no e-mail is returned)
                "session": {"role": user.get("role"), "email_verified": bool(user.get("email_verified")),
                            "on_admin_list": (user.get("email") or "").lower() in allowed if allowed else None,
                            "auth": "clerk" if user.get("clerk_id") else "legacy"},
                "auto_trading": False, "orders_sent": 0}

    @r.post("/analyze")
    async def analyze(body: AnalyzeBody, user: dict = Depends(require_admin)):
        return await execute(body, user, "v2-analyze")

    @r.post("/buy-plan")
    async def buy_plan(body: AnalyzeBody, user: dict = Depends(require_admin)):
        run = await execute(body, user, "v2-buy")
        return {"symbol": run["symbol"], "final": run["final"], "buy_result": run["engine"]["result"],
                "buy_plan": run["buy_plan"], "unreleased_plan": run["unreleased_plan"], "retest": run["engine"]["retest"],
                "why_not_trade": run["why_not_trade"], "consensus": run["consensus"], "run": run}

    @r.post("/sell-plan")
    async def sell_plan(body: AnalyzeBody, user: dict = Depends(require_admin)):
        run = await execute(body, user, "v2-sell")
        if not run["sell_plan"] or run["sell_plan"].get("error"):
            raise HTTPException(status_code=400, detail="Bu coinde kayıtlı pozisyon yok. Giriş fiyatını (ve varsa ilk stopu) yaz.")
        return {"symbol": run["symbol"], "final": run["final"], "sell_plan": run["sell_plan"], "consensus": run["consensus"], "run": run}

    @r.post("/scan")
    async def scan(body: ScanBody, user: dict = Depends(require_admin)):
        svc = engine()
        d = svc.d
        _positive(body.portfolio_usdt, "Portföy")
        if body.limit is not None and not 5 <= body.limit <= advisor_api.MAX_SCAN:
            raise HTTPException(status_code=400, detail=f"limit 5 ile {advisor_api.MAX_SCAN} arasında olmalı.")
        limits.check_user(user["id"], "advisor-v2-scan", SCAN_PER_MINUTE)
        portfolio = await portfolio_context(get_db(), body.portfolio_usdt, body.use_portfolio)
        try:
            return await svc.scan(portfolio, body.limit or d.SCAN_LIMIT, macro=openbb(), paper="v2-scan")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Tarama yapılamadı: {str(e)[:120]}")

    @r.get("/macro")
    async def macro(user: dict = Depends(require_admin)):
        engine()
        return await openbb().get_macro_snapshot()

    @r.get("/paper-stats")
    async def paper_stats(origin: str = "LIVE", all_versions: bool = False, virtual: bool = False,
                          user: dict = Depends(require_admin)):
        engine()
        if origin.upper() not in ("LIVE", "REPLAY", "TEST", "ALL"):
            raise HTTPException(status_code=400, detail="origin LIVE, REPLAY, TEST ya da ALL olmalı.")
        research = importlib.import_module("danisman_v2.research")
        paper = sys.modules.get("danisman_paper")
        if paper is None:
            raise HTTPException(status_code=503, detail="Paper log bu sunucuda yok.")
        rows = await asyncio.to_thread(lambda: paper.store().all())
        current = research.ruleset_hash()
        mine = [x for x in rows if x.get("engine") == "v2"]
        return {"ruleset_hash": current, "exit_styles": research.stats(rows, origin, None if all_versions else current, virtual),
                # the first tracker's own table (trigger rate, 1R, 24 h) for the V2 records
                "setups": paper.stats(mine, None, origin.upper(), None if all_versions else current),
                "note": "Yalnız ölçüm: hiçbir eşik bu sayılara göre değişmez. Yetersiz örnek INCONCLUSIVE olarak gösterilir."}

    @r.get("/consensus-history")
    async def history(symbol: Optional[str] = None, limit: int = 30, user: dict = Depends(require_admin)):
        q = {"symbol": advisor_api._symbol(symbol)} if symbol else {}
        return await get_db().advisor_consensus_runs.find(q, {"_id": 0}).sort("generated_at", -1).to_list(max(1, min(limit, HISTORY_LIMIT)))

    @r.get("/portfolio")
    async def portfolio(user: dict = Depends(require_admin)):
        """What the risk rules see: the holdings, their class and the exposure shares, with the stored trade states."""
        engine()
        snap = importlib.import_module("danisman_v2.snapshot")
        planner = importlib.import_module("danisman_v2.planner")
        cfg = importlib.import_module("danisman_v2.config")
        db = get_db()
        ctx = await portfolio_context(db, None, True)
        facts = snap.portfolio_facts("", 0.0, ctx, {}) if ctx else None
        states = await db.advisor_positions.find({}, {"_id": 0}).to_list(200)
        return {"portfolio": facts, "warnings": planner.portfolio_warnings(facts) if facts else [],
                "limits": {k: getattr(cfg, k) for k in ("RISK_PER_TRADE_PCT", "MAX_NEW_POSITION_PCT", *cfg.POLICY_LIMITS)},
                "policy": cfg.policy(),            # the exposure limits are the admin's configured policy, not a test result
                "position_states": states}

    return r

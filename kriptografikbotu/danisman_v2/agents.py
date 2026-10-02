"""The three AI analysts: three independent ROLES. They read the same snapshot and each answers with one small JSON
verdict. Three roles are not three models: by default all of them run on one model (see DEFAULTS and diversity()).

    TECHNICAL   is the setup a good one?            BUY / WAIT / HOLD / PROTECT / EXIT / AVOID
    RISK        can the portfolio carry it?         APPROVE / WAIT / REJECT / REDUCE_RISK
    REGIME      why should we NOT take it?          ALLOW / CAUTION / BLOCK

A model explains and argues. It never sets a price: trigger, limit, stop, target and size come from planner.py and
protection.py, and consensus.py (plain rules) decides whether the plan is released. An answer that is not valid JSON
in the expected shape is asked for once more and then counts as FAILED; a failed analyst means no BUY.

Provider independent: any OpenAI-compatible chat endpoint. Per role: <ROLE>_AI_PROVIDER, <ROLE>_AI_MODEL and,
optionally, <ROLE>_AI_BASE_URL / <ROLE>_AI_API_KEY. Keys stay on the server; no verdict or error text carries one.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time

import httpx

from . import config as cfg

ROLES = ("TECHNICAL", "RISK", "REGIME")
PROVIDERS = {"deepseek": ("https://api.deepseek.com", ("DEEPSEEK_API_KEY",)),
             "nvidia": ("https://integrate.api.nvidia.com/v1", ("NVIDIA_API_KEY",)),
             "openai": ("https://api.openai.com/v1", ("OPENAI_API_KEY",)),
             "custom": ("", ("ADVISOR_AI_API_KEY",))}
# One fast model for all three roles by default: three separate calls, three different briefs, none sees another's
# answer. Measured on 2026-10-02 with the bot's own keys: DeepSeek answered in about 11 s; the NVIDIA-hosted Kimi K3
# and GLM 5.3 did not answer within 330 s. To put another model on a role: <ROLE>_AI_PROVIDER / <ROLE>_AI_MODEL.
DEFAULTS = {"TECHNICAL": ("deepseek", "deepseek-flash"), "RISK": ("deepseek", "deepseek-flash"), "REGIME": ("deepseek", "deepseek-flash")}
VERDICTS = {"TECHNICAL": ("BUY", "WAIT", "HOLD", "PROTECT", "EXIT", "AVOID"), "RISK": ("APPROVE", "WAIT", "REJECT", "REDUCE_RISK"),
            "REGIME": ("ALLOW", "CAUTION", "BLOCK")}
SETUPS = ("BREAKOUT", "RETEST", "RECLAIM", "PULLBACK", "NONE")
LISTS = {"TECHNICAL": ("evidence", "counter_evidence", "levels_to_watch"), "RISK": ("risk_flags", "portfolio_flags", "execution_flags"),
         "REGIME": ("macro_risks", "market_risks", "data_quality_flags")}

RESEARCH_FACTS = """What this project's own history tests found. Treat these as facts; never describe any setup here as a proven,
profitable strategy:
- The 15m breakout rule showed no positive edge in the history test: about -0.21R per trade.
- The daily stop-limit engine is still at the research stage.
- Stop-limit entry versus buying the confirmed close: no clear advantage either way.
- A bigger breakout buffer made results worse.
- A 3 ATR trailing stop did best on DAILY bars. That is not evidence for 15m / 1h.
- A hard "R/R >= 1.5" filter did not improve results.
- Selling a fixed part at a first target did not improve results.
- The breakout score did not separate good from bad breakouts in crypto.
- A 2023-2025 intraday lab (15m / 1h / 4h; breakout-retest, liquidity sweep, failed-breakout reclaim, VWAP reclaim,
  rotation, compression) found no setup with a positive mean R in both the development and the validation period.
- The locked last year of data must not be used to re-tune anything.
- A few whipsawed stops on BNB / BTC / ETH are a hypothesis about stop distance, not a proof."""

COMMON = """You are one of three independent analysts on an investment committee for a crypto spot advisor. You see one frozen
market snapshot (JSON): closed candles of 15m / 1h / 4h / 1d with indicators, confirmed swings, support and resistance
zones, the breakout / retest / reclaim state, the BTC regime, the portfolio, the macro snapshot, and under "engine" what
the deterministic rule engine concluded. You do not see the other analysts.

Rules:
- Use only what is in the snapshot. If something is missing or stale, say so in your flags; do not fill gaps.
- Only CLOSED candles confirm anything. `current_price` may come from an open candle and confirms nothing.
- You do not set order prices. Trigger, limit, stop, target and size are computed by code and cannot be changed by
  you. Judge whether the setup and the plan make sense.
- RSI alone is never a reason to buy or sell. One moving-average cross alone is never a trade decision.
- No order is ever sent; this is decision support for one person.
- Answer with ONE JSON object and nothing else: no prose before or after it, no markdown. Write the text fields
  ("reason" and the list items) in Turkish, short and concrete, citing levels and candles from the snapshot.

"""

ROLE_PROMPT = {
    "TECHNICAL": """Your role: professional multi-timeframe technical analyst. Assess the quality of the technical setup from price
action, market structure, support / resistance, breakout / retest / reclaim, SMA20/50/200, VWAP, RSI, volume and ATR.
If the portfolio already holds the coin, judge the position (HOLD / PROTECT / EXIT); otherwise a new entry.
JSON: {"role": "TECHNICAL", "verdict": "BUY"|"WAIT"|"HOLD"|"PROTECT"|"EXIT"|"AVOID",
"setup": "BREAKOUT"|"RETEST"|"RECLAIM"|"PULLBACK"|"NONE", "confidence": 0.0-1.0, "evidence": [], "counter_evidence": [],
"levels_to_watch": [], "reason": ""}""",
    "RISK": """Your role: professional portfolio risk manager and execution trader. Assess ATR and stop distance, whipsaw risk,
position sizing, chasing (NO_CHASE), liquidity, portfolio concentration and correlation, meme exposure, execution
spread and reward-to-risk. APPROVE only when you would sign off the plan as it stands.
JSON: {"role": "RISK", "verdict": "APPROVE"|"WAIT"|"REJECT"|"REDUCE_RISK", "confidence": 0.0-1.0, "risk_flags": [],
"portfolio_flags": [], "execution_flags": [], "reason": ""}""",
    "REGIME": """Your role: adversarial investment-committee analyst. Your job is to find why we should NOT enter: the BTC regime, the
4h / 1d trend, the macro snapshot and upcoming economic events, the equity and cross-asset context, failed breakouts,
data quality. BLOCK only for a concrete reason that is in the snapshot; CAUTION when the risk is real but not decisive.
JSON: {"role": "REGIME", "verdict": "ALLOW"|"CAUTION"|"BLOCK", "confidence": 0.0-1.0, "macro_risks": [], "market_risks": [],
"data_quality_flags": [], "reason": ""}""",
}


def system_prompt(role: str) -> str:
    return COMMON + RESEARCH_FACTS + "\n\n" + ROLE_PROMPT[role]


def ai_payload(snapshot: dict, engine: dict | None, protection: dict | None) -> str:
    """What every analyst reads: the snapshot and the rule engine's own conclusion, as compact JSON."""
    plan = (engine or {}).get("plan") or (engine or {}).get("withheld_plan")
    view = {**snapshot, "engine": None if not engine else {
        "status": engine["status"], "setup": engine["setup"], "evidence_status": engine["evidence_status"],
        "blocks": engine["blocks"], "waits": engine["waits"], "warnings": engine["warnings"], "evidence": engine["evidence"],
        "retest": engine.get("retest"), "plan_computed_by_code": plan,
        "plan_note": "levels are final and computed by code; they are shown so that you can judge them"},
        "position_plan_computed_by_code": None if not protection or protection.get("error") else
        {k: v for k, v in protection.items() if k != "new_state"}}
    return json.dumps(view, ensure_ascii=False, separators=(",", ":"), default=str)


def parse_verdict(role: str, text: str) -> dict:
    """The model's answer as a validated verdict. Raises ValueError when it is not the JSON that was asked for."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("JSON nesnesi yok")
    try:
        obj = json.JSONDecoder().raw_decode(m.group(0))[0]
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON okunamadı: {e.msg}")
    if not isinstance(obj, dict):
        raise ValueError("JSON nesnesi değil")
    if str(obj.get("role", role)).upper() != role:
        raise ValueError("rol uyuşmuyor")
    verdict = str(obj.get("verdict", "")).upper()
    if verdict not in VERDICTS[role]:
        raise ValueError(f"geçersiz verdict: {str(obj.get('verdict'))[:30]}")
    try:
        confidence = float(obj.get("confidence"))
    except (TypeError, ValueError):
        raise ValueError("confidence sayı değil")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence 0-1 dışında")
    out = {"role": role, "verdict": verdict, "confidence": round(confidence, 2), "reason": str(obj.get("reason") or "")[:900]}
    if role == "TECHNICAL":
        setup = str(obj.get("setup", "NONE")).upper()
        if setup not in SETUPS:
            raise ValueError(f"geçersiz setup: {setup[:30]}")
        out["setup"] = setup
    for key in LISTS[role]:
        value = obj.get(key, [])
        if not isinstance(value, list):
            raise ValueError(f"{key} liste değil")
        out[key] = [str(x)[:300] for x in value[:10]]
    return out


async def _http_post(url: str, headers: dict, body: dict, timeout: float) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, headers=headers, json=body)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")      # the body may echo the request: never passed on
        return r.json()


class AdvisorAIClient:
    """One analyst's model. post: async (url, headers, body, timeout) -> response dict, instead of the network (tests)."""

    def __init__(self, provider: str, model: str, api_key: str, base_url: str, timeout: float | None = None, post=None):
        self.provider, self.model, self._key, self.base_url = provider, model, api_key, base_url.rstrip("/")
        self.timeout = cfg.AI_TIMEOUT_SECONDS if timeout is None else timeout
        self._post = post or _http_post

    async def analyze(self, role: str, market_snapshot: dict, macro_snapshot: dict | None = None,
                      engine: dict | None = None, protection: dict | None = None) -> dict:
        """AgentVerdict: {"role", "status": "OK" | "FAILED", "verdict", ..., "model", "latency_ms", "attempts", "error"}."""
        snap = market_snapshot if macro_snapshot is None else {**market_snapshot, "macro": macro_snapshot}
        messages = [{"role": "system", "content": system_prompt(role)},
                    {"role": "user", "content": ai_payload(snap, engine, protection)}]
        base = {"role": role, "provider": self.provider, "model": self.model}
        started, error, usage = time.monotonic(), None, None
        for attempt in range(1, cfg.AI_MAX_RETRIES + 2):
            try:
                resp = await asyncio.wait_for(self._post(
                    f"{self.base_url}/chat/completions", {"Authorization": f"Bearer {self._key}"},
                    {"model": self.model, "messages": messages, "max_tokens": cfg.AI_MAX_TOKENS}, self.timeout), self.timeout)
                if not isinstance(resp, dict):
                    raise ValueError("cevap JSON nesnesi değil")
                usage = resp.get("usage")
                verdict = parse_verdict(role, ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
                return {**base, **verdict, "status": "OK", "attempts": attempt, "error": None,
                        "latency_ms": int((time.monotonic() - started) * 1000),
                        "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens")} if isinstance(usage, dict) else None}
            except ValueError as e:
                error = f"INVALID_JSON: {e}"
                messages = messages[:2] + [{"role": "user", "content": "Yalnız istenen tek JSON nesnesini yaz; başka hiçbir şey yazma."}]
            except (asyncio.TimeoutError, httpx.TimeoutException):
                error = "TIMEOUT"
            except Exception as e:
                error = f"PROVIDER_ERROR: {type(e).__name__}: {str(e)[:80]}"
        return {**base, "status": "FAILED", "verdict": None, "confidence": None, "reason": "", "attempts": cfg.AI_MAX_RETRIES + 1,
                "error": error, "latency_ms": int((time.monotonic() - started) * 1000), "usage": None}


def build_clients(env=None, post=None) -> dict:
    """role -> AdvisorAIClient, or None when that role has no key. Reads only the environment of this process."""
    env = os.environ if env is None else env
    out = {}
    for role in ROLES:
        provider = (env.get(f"{role}_AI_PROVIDER") or DEFAULTS[role][0]).lower()
        base, key_names = PROVIDERS.get(provider, PROVIDERS["custom"])
        model = env.get(f"{role}_AI_MODEL") or (DEFAULTS[role][1] if provider == DEFAULTS[role][0] else "")
        base = env.get(f"{role}_AI_BASE_URL") or base or env.get("ADVISOR_AI_BASE_URL", "")
        if provider == "nvidia":      # the bot's own names: one NVIDIA key, or a separate key per hosted model
            first = "KIMI_API_KEY" if "kimi" in model.lower() else "GLM_API_KEY" if "glm" in model.lower() else "NVIDIA_API_KEY"
            key_names = (first, "NVIDIA_API_KEY", "KIMI_API_KEY", "GLM_API_KEY")
        key = env.get(f"{role}_AI_API_KEY") or next((env[k] for k in key_names if env.get(k)), "")
        out[role] = AdvisorAIClient(provider, model, key, base, post=post) if key and base and model else None
    return out


def describe(clients: dict) -> dict:
    """What is configured, for the health endpoint. Never a key."""
    return {role: None if c is None else {"provider": c.provider, "model": c.model} for role, c in clients.items()}


async def run_agents(clients: dict, snapshot: dict, engine: dict | None, protection: dict | None) -> dict:
    """All three at once; none sees another's answer. A role without a client is FAILED / NOT_CONFIGURED."""
    async def one(role):
        client = clients.get(role)
        if client is None:
            return {"role": role, "status": "FAILED", "verdict": None, "confidence": None, "reason": "", "provider": None,
                    "model": None, "attempts": 0, "error": "NOT_CONFIGURED", "latency_ms": 0, "usage": None}
        return await client.analyze(role, snapshot, None, engine, protection)
    tasks = {r: asyncio.ensure_future(one(r)) for r in ROLES}
    await asyncio.wait(tasks.values(), timeout=cfg.AI_TOTAL_TIMEOUT_SECONDS)      # the hard limit for all three together
    out = {}
    for role, task in tasks.items():
        if task.done() and not task.cancelled() and task.exception() is None:
            out[role] = task.result()
            continue
        task.cancel()
        client = clients.get(role)
        out[role] = {"role": role, "status": "FAILED", "verdict": None, "confidence": None, "reason": "",
                     "provider": getattr(client, "provider", None), "model": getattr(client, "model", None), "attempts": 1,
                     "error": "TIMEOUT_TOTAL" if not task.done() else "PROVIDER_ERROR", "usage": None,
                     "latency_ms": int(cfg.AI_TOTAL_TIMEOUT_SECONDS * 1000)}
    return out


def diversity(clients: dict) -> dict:
    """How many DIFFERENT models stand behind the three roles. Three roles on one model are three independent
    analyses, not a three-model consensus, and the panel says so."""
    models = sorted({f"{c.provider}/{c.model}" for c in clients.values() if c is not None})
    return {"roles": len(ROLES), "configured_roles": sum(c is not None for c in clients.values()),
            "distinct_models": len(models), "models": models, "model_diversity": len(models) > 1}

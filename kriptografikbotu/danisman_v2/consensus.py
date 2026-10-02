"""Consensus: plain rules over the three verdicts and the rule engine's own result. No model decides here.

A buy plan is released only when
    the rule engine itself has a complete, unblocked plan      (a model cannot create a setup)
    TECHNICAL == BUY  and  RISK == APPROVE  and  REGIME != BLOCK
and all three analysts answered. Risk and Regime are vetoes: two votes for BUY never outweigh them.

    any analyst missing / failed      DEGRADED_CONSENSUS    no buy
    REGIME == BLOCK                   BLOCKED_SETUP
    RISK == REJECT                    NO_TRADE
    TECHNICAL or RISK == WAIT         WAIT
    TECHNICAL BUY vs RISK REDUCE_RISK, or TECHNICAL AVOID / EXIT vs RISK APPROVE
                                      CONSENSUS_DISAGREEMENT   treated as WAIT
"""
from __future__ import annotations

OUTCOMES = ("BUY", "WAIT", "NO_TRADE", "BLOCKED_SETUP", "DEGRADED_CONSENSUS", "CONSENSUS_DISAGREEMENT")
TR = {"BUY": "AL planı onaylandı", "WAIT": "BEKLE", "NO_TRADE": "İŞLEM YOK", "BLOCKED_SETUP": "ENGELLİ",
      "DEGRADED_CONSENSUS": "EKSİK KONSENSÜS — AL yok", "CONSENSUS_DISAGREEMENT": "GÖRÜŞ AYRILIĞI — BEKLE"}


def decide(verdicts: dict | None, engine: dict) -> dict:
    """verdicts: {"TECHNICAL": AgentVerdict, "RISK": ..., "REGIME": ...} or None when the analysts were not asked.
    engine: planner.build_buy_plan() result. Returns {"consensus", "plan_released", "final", "reasons", ...}."""
    v = verdicts or {}
    got = {r: (v.get(r) or {}) for r in ("TECHNICAL", "RISK", "REGIME")}
    failed = [r for r, a in got.items() if a.get("status") != "OK"]
    t, k, g = (got[r].get("verdict") for r in ("TECHNICAL", "RISK", "REGIME"))
    reasons = []
    if failed:
        outcome = "DEGRADED_CONSENSUS"
        reasons.append("Cevap vermeyen analist: " + ", ".join(f"{r} ({got[r].get('error') or 'çağrılmadı'})" for r in failed))
    elif g == "BLOCK":
        outcome = "BLOCKED_SETUP"
        reasons.append("Rejim analisti engelledi (veto)")
    elif k == "REJECT":
        outcome = "NO_TRADE"
        reasons.append("Risk analisti reddetti (veto)")
    elif (t == "BUY" and k == "REDUCE_RISK") or (t in ("AVOID", "EXIT") and k == "APPROVE"):
        outcome = "CONSENSUS_DISAGREEMENT"
        reasons.append(f"Teknik {t}, risk {k}: görüşler çelişiyor")
    elif t == "BUY" and k == "APPROVE":
        outcome = "BUY"
    else:
        outcome = "WAIT"
        reasons.append(f"Teknik {t}, risk {k}, rejim {g}")
    released = outcome == "BUY" and bool(engine.get("actionable"))
    if outcome == "BUY" and not released:
        reasons.append(f"Analistler olumlu ama kural motorunda uygulanabilir plan yok ({engine['status']}): plan üretilmez")
    if g == "CAUTION" and outcome == "BUY":
        reasons.append("Rejim analisti temkinli: plan geçerli, uyarı notu eklendi")
    # what the user sees: the engine's own status unless the committee holds a real plan back
    if released:
        final = engine["status"]
    elif engine.get("actionable"):
        final = outcome if outcome != "BUY" else engine["status"]
    else:
        final = engine["status"]
    return {"consensus": outcome, "consensus_tr": TR[outcome], "plan_released": released, "final": final,
            "technical_verdict": t, "risk_verdict": k, "regime_verdict": g, "failed_agents": failed, "reasons": reasons}

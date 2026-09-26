"""Model scorecard: how often each AI model's call was right, judged later by closes.

Sources: council votes on ŞİMDİ AL signals (decision["konsey"]) and the model that wrote an alarm's
analysis (decision["model"] + decision["karar"]). Outcome is the close-based result stored on the decision
(hedef / stop). AL is right when the target came first; BEKLE/PAS is right when the stop came first.
Open or undecided signals are not counted.
"""
import llm
import positions

MIN_SAMPLE = 10


def calls(decisions: list[dict]) -> list[tuple[str, str, str]]:
    """(model, karar, outcome) for every judged call. Pure."""
    out = []
    for d in decisions:
        res = (d.get("sonuc") or {}).get("sonuc")
        if res not in ("hedef", "stop"):
            continue
        for model, v in (d.get("konsey") or {}).items():
            out.append((model, v["karar"], res))
        if d.get("model") and d.get("karar") in ("AL", "BEKLE", "PAS"):
            out.append((d["model"], d["karar"], res))
    return out


def scorecard(decisions: list[dict]) -> dict[str, dict]:
    table: dict[str, dict] = {}
    for model, karar, res in calls(decisions):
        r = table.setdefault(model, {"n": 0, "dogru": 0, "al": 0, "al_dogru": 0})
        right = (karar == "AL") == (res == "hedef")
        r["n"] += 1
        r["dogru"] += right
        if karar == "AL":
            r["al"] += 1
            r["al_dogru"] += res == "hedef"
    for r in table.values():
        r["isabet"] = round(r["dogru"] / r["n"] * 100) if r["n"] else None
        r["al_isabet"] = round(r["al_dogru"] / r["al"] * 100) if r["al"] else None
    return table


def text(decisions: list[dict] | None = None) -> str:
    decisions = positions.load_decisions() if decisions is None else decisions
    table = scorecard(decisions)
    lines = ["🧠 MODEL KARNESİ (kapanışla sonuçlanan kararlar: AL→hedef, BEKLE/PAS→stop doğru sayılır)"]
    if not table:
        return lines[0] + "\nHenüz sonuçlanmış model kararı yok. Konsey oyları ve alarm yorumları biriktikçe dolar."
    for model, r in sorted(table.items(), key=lambda kv: -(kv[1]["isabet"] or 0)):
        lines.append(f"{llm.MODEL_NAMES.get(model, model)}: {r['n']} karar, isabet %{r['isabet']}"
                     + (f" · AL dediğinde hedef %{r['al_isabet']} ({r['al']})" if r["al"] else ""))
    if any(r["n"] < MIN_SAMPLE for r in table.values()):
        lines.append(f"({MIN_SAMPLE} karardan az olan satırlar tesadüf olabilir.)")
    return "\n".join(lines)

"""DeepSeek spend tracking: one JSON line per API call in data/usage.jsonl."""
import json
import os
from datetime import datetime, timedelta, timezone

import config
from macro import TR


def is_peak(when_utc: datetime) -> bool:
    return when_utc.weekday() < 5 and (1 <= when_utc.hour < 4 or 6 <= when_utc.hour < 10)


def record(hit: int, miss: int, out: int, label: str, model: str = "deepseek"):
    now = datetime.now(timezone.utc)
    tier = "peak" if is_peak(now) else "offpeak"
    p = {"kimi": config.KIMI_PRICES, "glm": config.GLM_PRICES}.get(model) or config.DEEPSEEK_PRICES[tier]
    usd = (hit * p["hit"] + miss * p["miss"] + out * p["out"]) / 1e6
    row = {"utc": now.isoformat(timespec="seconds"), "tarife": tier, "hit": hit, "miss": miss,
           "out": out, "usd": round(usd, 6), "etiket": label[:40], "model": model}
    with open(config.USAGE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


_cache: tuple = (None, [])   # (file size and change time, parsed rows)


def _rows() -> list[dict]:
    """Every logged call. The file is parsed again only after it changed: the panel sync asks every minute."""
    global _cache
    try:
        st = os.stat(config.USAGE_FILE)
    except FileNotFoundError:
        return []
    key = (st.st_size, st.st_mtime_ns)
    if _cache[0] != key:
        with open(config.USAGE_FILE, encoding="utf-8") as f:
            _cache = (key, [json.loads(line) for line in f if line.strip()])
    return list(_cache[1])


def summary_text() -> str:
    rows = _rows()
    now = datetime.now(TR)
    periods = {"Bugün": now.replace(hour=0, minute=0, second=0, microsecond=0),
               "Son 7 gün": now - timedelta(days=7),
               "Bu ay": now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)}
    lines = [f"💸 Yapay zekâ harcaması (kur {config.USD_TRY:g} TL) — DeepSeek ({config.DEEPSEEK_MODEL}) + Kimi K3 + GLM 5.3 (NVIDIA)"]
    for name, since in periods.items():
        sel = [r for r in rows if datetime.fromisoformat(r["utc"]) >= since]
        usd = sum(r["usd"] for r in sel)
        if not sel:
            lines.append(f"\n{name}: çağrı yok")
            continue
        hit, miss, out = (sum(r[k] for r in sel) for k in ("hit", "miss", "out"))
        peak = sum(r["tarife"] == "peak" for r in sel)
        nv = {m: [r for r in sel if r.get("model") == m] for m in ("kimi", "glm")}
        lines.append(f"\n{name}: {len(sel)} çağrı → {usd * config.USD_TRY:.2f} TL (${usd:.3f})\n"
                     f"  analiz başı ort {usd / len(sel) * config.USD_TRY:.2f} TL | "
                     f"yoğun saatte {peak}/{len(sel)}\n"
                     f"  token: önbellek {hit:,} | önbelleksiz {miss:,} | output {out:,}\n"
                     f"  model: DeepSeek {len(sel) - len(nv['kimi']) - len(nv['glm'])} · Kimi K3 {len(nv['kimi'])} · "
                     f"GLM 5.3 {len(nv['glm'])} (NVIDIA ${sum(r['usd'] for r in nv['kimi'] + nv['glm']):.3f})")
    month = [r for r in rows if datetime.fromisoformat(r["utc"]) >= periods["Bu ay"]]
    if month:
        # Average over days actually tracked, so a mid-month start doesn't dilute the estimate.
        first = max(periods["Bu ay"], datetime.fromisoformat(month[0]["utc"]).astimezone(TR))
        days = max((now - first).days + 1, 1)
        lines.append(f"\nAy sonu tahmini: ~{sum(r['usd'] for r in month) / days * 30 * config.USD_TRY:.0f} TL")
    lines.append("\nYoğun saat (2× fiyat): hafta içi TR 04:00-07:00 ve 09:00-13:00.")
    return "\n".join(lines)

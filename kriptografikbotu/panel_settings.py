"""Bot parameters the owner can change from the panel's Settings card ("Düzenle").

Each entry: key, label, where the value lives (config attribute or settings.json key), type and allowed range.
Changed config values are stored in settings.json ("panel_ayarlari") and applied on top of config.py at startup
and right after a change (apply()). The time zone is not editable.
"""
import config

# key: (label, target, type, min, max, options)
# target "cfg:NAME" = config attribute, "set:NAME" = settings.json key
SPEC = {
    "kisa_butce": ("Kısa vadeli bütçe (USD)", "set:kisa_butce_usd", float, 1, 10_000_000, None),
    "ilk_kademe": ("Varsayılan ilk kademe (USD)", "cfg:DEFAULT_TRANCHE_USD", float, 1, 1_000_000, None),
    "toplam_kademe": ("Açık ilk kademeler toplamı (USD)", "cfg:TOTAL_FIRST_TRANCHE_USD", float, 1, 10_000_000, None),
    "bist_butce": ("BIST bütçesi (TL)", "set:bist_budget_tl", int, 1, 1_000_000_000, None),
    "bist_kademe": ("BIST ilk kademe (%)", "cfg:BIST_FIRST_TRANCHE_PCT", float, 1, 100, None),
    "bist_rr": ("BIST net R/R", "cfg:BIST_MIN_RR", float, 0.5, 10, None),
    "bist_risk": ("BIST azami stop riski (%)", "cfg:BIST_MAX_RISK_PCT", float, 0.1, 20, None),
    "min_rr": ("Minimum R/R", "cfg:MIN_RR", float, 0.5, 10, None),
    "min_rr_off": ("Minimum R/R (RİSK-OFF)", "cfg:MIN_RR_RISK_OFF", float, 0.5, 10, None),
    "on_filtre": ("Ön filtre", "cfg:PREFILTER", str, None, None, ["kod", "qwen"]),
    "brif": ("Sabah brifi (SS:DD)", "cfg:BRIEF_TIME", str, None, None, None),
    "ai_mod": ("Analiz modeli", "set:ai_mod", str, None, None, ["sira", "deepseek", "kimi", "glm"]),
}


def _settings():
    import alerts_store
    return alerts_store.load_settings()


def apply():
    """Put stored overrides onto config (called at startup and after each change)."""
    stored = _settings().get("panel_ayarlari") or {}
    for key, value in stored.items():
        spec = SPEC.get(key)
        if not spec or not spec[1].startswith("cfg:"):
            continue
        name = spec[1][4:]
        if name == "BRIEF_TIME":
            h, m = value.split(":")
            config.BRIEF_HOUR, config.BRIEF_MINUTE = int(h), int(m)
        else:
            setattr(config, name, value)


def current(key: str):
    target = SPEC[key][1]
    if target.startswith("set:"):
        v = _settings().get(target[4:])
        return 100 if v is None and key == "kisa_butce" else v
    name = target[4:]
    if name == "BRIEF_TIME":
        return f"{config.BRIEF_HOUR:02d}:{config.BRIEF_MINUTE:02d}"
    return getattr(config, name, None)


def parse(key: str, raw) -> object:
    """Validated value, or ValueError with a Turkish message."""
    label, target, typ, lo, hi, options = SPEC[key]
    if options:
        v = str(raw).strip().lower()
        if v not in options:
            raise ValueError(f"{label}: {', '.join(options)} olmalı")
        return v
    if target == "cfg:BRIEF_TIME":
        v = str(raw).strip().replace(".", ":")
        try:
            h, m = (int(x) for x in v.split(":"))
        except ValueError:
            raise ValueError(f"{label}: SS:DD biçiminde yaz (ör. 08:30)")
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError(f"{label}: geçersiz saat")
        return f"{h:02d}:{m:02d}"
    try:
        v = typ(float(str(raw).replace(",", ".")))
    except ValueError:
        raise ValueError(f"{label}: sayı olmalı")
    if not lo <= v <= hi:
        raise ValueError(f"{label}: {lo:g} ile {hi:g} arasında olmalı")
    return v


def save(values: dict) -> list[str]:
    """Validate everything first, then store. Returns what changed."""
    import alerts_store
    parsed = {k: parse(k, v) for k, v in values.items() if k in SPEC and v not in (None, "")}
    s = alerts_store.load_settings()
    stored = s.get("panel_ayarlari") or {}
    done = []
    for k, v in parsed.items():
        target = SPEC[k][1]
        if target.startswith("set:"):
            s[target[4:]] = v
        else:
            stored[k] = v
        done.append(f"{SPEC[k][0]} = {v}")
    s["panel_ayarlari"] = stored
    alerts_store.save_settings(s)
    apply()
    return done

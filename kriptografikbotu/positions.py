"""Open/closed positions and the alert decision journal (positions.json, decisions.json)."""
import alerts_store
import config
from alerts_store import _load, _save, now_tr


# --- positions ---------------------------------------------------------------

def load() -> list[dict]:
    return _load(config.POSITIONS_FILE, [])


def save(items: list[dict]):
    _save(config.POSITIONS_FILE, items)


def get(pos_id: int) -> dict | None:
    return next((p for p in load() if p["id"] == pos_id), None)


def open_positions() -> list[dict]:
    return [p for p in load() if p["durum"] == "acik"]


def is_trade(p: dict) -> bool:
    """Short-term trades use the tranche caps and the discipline shield. Long-term holdings don't:
    accumulation-plan buys (birikim) and holdings imported into the portfolio (kaynak "portföy")."""
    return not p.get("birikim") and p.get("kaynak") != "portföy"


def open_position(pair: str, entry: float, usd: float, stop: float | None, target: float | None,
                  timeframe: str = "15m", source: str = "elle", decision_id: int | None = None,
                  market_name: str = "KRIPTO", symbol: str | None = None) -> dict:
    """usd is the position's amount in its own currency: USD for crypto, TL for BIST (market_name)."""
    items = load()
    pos = {"id": max((p["id"] for p in items), default=0) + 1, "pair": pair,
           "symbol": symbol or alerts_store.pair_to_symbol(pair), "giris": entry, "miktar_usd": usd,
           "piyasa": market_name, "para": "TL" if market_name == "BIST" else "USD",
           "adet": usd / entry, "stop": stop, "stop_ilk": stop, "hedef": target, "timeframe": timeframe,
           "kaynak": source, "karar_id": decision_id, "durum": "acik", "acilis": now_tr().isoformat(),
           "kapanis_fiyat": None, "kapanis_zamani": None, "neden": None, "kural_ihlali": [],
           "son_uyari_mum": None}
    items.append(pos)
    save(items)
    return pos


def update(pos_id: int, **changes) -> tuple[dict | None, str | None]:
    """Apply changes. Enforces the goalpost rule: an open position's stop can't move down."""
    items = load()
    pos = next((p for p in items if p["id"] == pos_id), None)
    if not pos:
        return None, "pozisyon bulunamadı"
    new_stop = changes.get("stop")
    if pos["durum"] == "acik" and new_stop is not None and pos["stop"] is not None and new_stop < pos["stop"]:
        # The attempt itself is a discipline event: it shows up in /rapor and the weekly summary.
        pos["kural_ihlali"].append({"zaman": now_tr().isoformat(), "tur": "stop_asagi",
                                    "not": f"stopu aşağı çekme denemesi ({pos['stop']:g} → {new_stop:g}), reddedildi"})
        save(items)
        return pos, f"goalpost yasağı: stop {pos['stop']:g} altına çekilemez (deneme kural ihlali olarak kaydedildi)"
    if "giris" in changes or "miktar_usd" in changes:
        entry = changes.get("giris", pos["giris"])
        usd = changes.get("miktar_usd", pos["miktar_usd"])
        pos["adet"] = usd / entry
    if "stop" in changes and pos["stop_ilk"] is None:
        pos["stop_ilk"] = changes["stop"]
    pos.update(changes)
    save(items)
    return pos, None


def delete_position(pos_id: int) -> dict | None:
    """Remove a record that should never have existed (e.g. "Aldım" pressed without buying).
    Unlike a sell it leaves no trade behind: no P/L, no journal, no discipline streak. The decision
    it came from goes back to "no action" and the plan loses its position flag."""
    items = load()
    pos = next((p for p in items if p["id"] == pos_id), None)
    if not pos:
        return None
    save([p for p in items if p["id"] != pos_id])
    if pos.get("karar_id"):
        update_decision(pos["karar_id"], aksiyon=None)
    import conversation_store
    state = conversation_store.load_state()
    key = pos["symbol"] if pos.get("piyasa") == "BIST" else pos["pair"].split("/")[0]
    if state["planlar"].get(key, {}).get("pozisyon") and not any(
            p["durum"] == "acik" and p["symbol"] == pos["symbol"] for p in load()):
        state["planlar"][key]["pozisyon"] = False
        conversation_store.save_state(state)
    return pos


def close_position(pos_id: int, price: float, reason: str, when: str | None = None) -> dict | None:
    """when: ISO time the user actually sold (default now), so an older sale is recorded on its real day."""
    items = load()
    pos = next((p for p in items if p["id"] == pos_id and p["durum"] == "acik"), None)
    if not pos:
        return None
    pos.update(durum="kapali", kapanis_fiyat=price, kapanis_zamani=when or now_tr().isoformat(), neden=reason)
    save(items)
    return pos


def partial_close(pos_id: int, qty: float, price: float, reason: str,
                  when: str | None = None) -> tuple[dict | None, dict | None]:
    """Sell part of an open position. The sold part becomes its own closed record (so reports count
    the realized P/L), and the open position keeps the rest with the same entry, stop and target."""
    items = load()
    pos = next((p for p in items if p["id"] == pos_id and p["durum"] == "acik"), None)
    if not pos or qty <= 0:
        return None, None
    when = when or now_tr().isoformat()
    if qty >= pos["adet"] - 1e-12:
        pos.update(durum="kapali", kapanis_fiyat=price, kapanis_zamani=when, neden=reason)
        save(items)
        return pos, None
    share = qty / pos["adet"]
    part = {**pos, "id": max(p["id"] for p in items) + 1, "adet": qty, "miktar_usd": pos["miktar_usd"] * share,
            "durum": "kapali", "kapanis_fiyat": price, "kapanis_zamani": when,
            "neden": reason, "kaynak": f"kısmi satış #{pos_id}", "kural_ihlali": []}
    pos["adet"] -= qty
    pos["miktar_usd"] *= 1 - share
    pos.setdefault("kismi_satislar", []).append({"zaman": part["kapanis_zamani"], "adet": qty, "fiyat": price,
                                                 "kayit": part["id"]})
    items.append(part)
    save(items)
    return part, pos


def tranche_usd(pair: str, risk_off: bool, volume_ok: bool,
                exchange_min_usd: float = 0.0, greed: str | None = None) -> tuple[float, list[str]]:
    """First-tranche size, decided in code (never by the LLM).

    Normal 25 USD; 15 USD in RİSK-OFF or without volume confirmation. Every open position,
    same pair included, counts toward the shared first-tranche cap (correlated coins are one
    trade). Below the practical floor (10 USD, or the pair's exchange minimum if higher) the
    answer is 0 — the cap is never exceeded to reach a valid order size.
    """
    usd = float(config.DEFAULT_TRANCHE_USD)
    notes = []
    if risk_off:
        usd = min(usd, config.REDUCED_TRANCHE_USD)
        notes.append("RİSK-OFF (veya makro doğrulanamadı)")
    if not volume_ok:
        usd = min(usd, config.REDUCED_TRANCHE_USD)
        notes.append("hacim teyidi yok")
    if greed:  # extreme greed: same size as a missing confirmation
        usd = min(usd, config.REDUCED_TRANCHE_USD)
        notes.append(greed)
    # Crypto cap only counts crypto; BIST has its own TL budget (bist.tranche_tl).
    open_usd = sum(p["miktar_usd"] for p in open_positions() if p.get("piyasa", "KRIPTO") == "KRIPTO" and is_trade(p))
    room = config.TOTAL_FIRST_TRANCHE_USD - open_usd
    if room < usd:
        usd = max(room, 0.0)
        notes.append(f"açık pozisyonlar {open_usd:g} USD: korelasyon limiti {config.TOTAL_FIRST_TRANCHE_USD} USD")
    floor = max(config.MIN_TRANCHE_USD, exchange_min_usd)
    if 0 < usd < floor:
        notes.append(f"kalan {usd:g} USD alt sınırın ({floor:g} USD) altında: limit dolu, pas")
        usd = 0.0
    elif usd <= 0 and not any("korelasyon" in n for n in notes):
        notes.append("limit dolu, pas")
    return round(usd, 2), notes


def pnl(pos: dict, price: float) -> dict:
    usd = (price - pos["giris"]) * pos["adet"]
    risk = pos["giris"] - pos["stop_ilk"] if pos.get("stop_ilk") else None
    return {"pnl_usd": round(usd, 2), "pnl_yuzde": round((price / pos["giris"] - 1) * 100, 2),
            "R": round((price - pos["giris"]) / risk, 2) if risk and risk > 0 else None}


def add_violation(pos_id: int, text: str, kind: str = "diger"):
    items = load()
    for p in items:
        if p["id"] == pos_id:
            p["kural_ihlali"].append({"zaman": now_tr().isoformat(), "tur": kind, "not": text})
    save(items)


def save_last_backtest(result: dict):
    _save(config.DATA_DIR / "last_backtest.json", result)


def load_last_backtest() -> dict | None:
    return _load(config.DATA_DIR / "last_backtest.json", None)


# --- decision journal --------------------------------------------------------

def load_decisions() -> list[dict]:
    return _load(config.DECISIONS_FILE, [])


def log_decision(d: dict) -> dict:
    items = load_decisions()
    d = {"id": max((x["id"] for x in items), default=0) + 1, "zaman": now_tr().isoformat(),
         "aksiyon": None, **d}
    items.append(d)
    _save(config.DECISIONS_FILE, items)
    return d


def set_decision_action(dec_id: int, action: str):
    items = load_decisions()
    for d in items:
        if d["id"] == dec_id:
            d["aksiyon"] = action
    _save(config.DECISIONS_FILE, items)


def update_decision(dec_id: int, **fields):
    items = load_decisions()
    for d in items:
        if d["id"] == dec_id:
            d.update(fields)
    _save(config.DECISIONS_FILE, items)


def get_decision(dec_id: int) -> dict | None:
    return next((d for d in load_decisions() if d["id"] == dec_id), None)

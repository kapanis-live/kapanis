"""Accumulation plans (birikim): a fixed amount into one asset every month.

The bot never buys: on the plan's day it sends a reminder with today's price and quantity, and records
the buy only when the user presses "Aldım". Buys are positions with birikim=True: long-term holdings
that don't use the short-term tranche caps, the discipline shield or TUT/SAT exit alerts.
Extra-tranche hint (once a month): price DCA_DIP_PCT below the plan's average cost, or
DCA_DRAWDOWN_PCT below the 30-day high.
"""
from datetime import date

import alerts_store
import bist
import config
import positions


def plans() -> list[dict]:
    return alerts_store.load_settings().get("birikim", [])


def save_plans(items: list[dict]):
    s = alerts_store.load_settings()
    s["birikim"] = items
    alerts_store.save_settings(s)


def add_plan(asset: str, market: str, symbol: str, pair: str, amount: float, day: int) -> dict:
    items = plans()
    p = {"id": max((x["id"] for x in items), default=0) + 1, "varlik": asset, "piyasa": market, "symbol": symbol,
         "pair": pair, "tutar": amount, "para": "TL" if market == "BIST" else "USD", "gun": day,  # ABD and crypto: USD
         "son_hatirlatma": None, "son_ekstra": None, "olusturma": alerts_store.now_tr().isoformat()}
    items.append(p)
    save_plans(items)
    return p


def remove_plan(plan_id: int) -> bool:
    items = plans()
    left = [p for p in items if p["id"] != plan_id]
    save_plans(left)
    return len(left) < len(items)


def mark(plan_id: int, **fields):
    items = plans()
    for p in items:
        if p["id"] == plan_id:
            p.update(fields)
    save_plans(items)


def due(plan: dict, today: date, trading_day: bool) -> bool:
    """Remind once a month, on the plan's day or the first possible day after it (bot was off,
    weekend or BIST holiday). Pure."""
    month = today.strftime("%Y-%m")
    if (plan.get("son_hatirlatma") or "")[:7] == month:
        return False
    if plan["piyasa"] == "BIST" and not trading_day:
        return False
    return today.day >= min(plan["gun"], 28)


def quantity(plan: dict, price: float) -> float:
    if plan["piyasa"] == "BIST":
        return float(int(plan["tutar"] // price))
    return round(plan["tutar"] / price, 8)


def holdings(plan: dict) -> dict:
    """Open accumulation buys of this plan: quantity, cost, average."""
    rows = [p for p in positions.open_positions() if p.get("birikim") == plan["id"]]
    qty = sum(p["adet"] for p in rows)
    cost = sum(p["adet"] * p["giris"] for p in rows)
    return {"alim": len(rows), "adet": qty, "maliyet": cost, "ortalama": cost / qty if qty else None}


def dip_reason(plan: dict, price: float, high30: float | None) -> str | None:
    """Why an extra tranche makes sense now, or None. Pure."""
    avg = holdings(plan)["ortalama"]
    if avg and price <= avg * (1 - config.DCA_DIP_PCT / 100):
        return f"fiyat ortalama maliyetinin (%{(price / avg - 1) * 100:+.1f}) altında"
    if high30 and price <= high30 * (1 - config.DCA_DRAWDOWN_PCT / 100):
        return f"30 günlük tepeden %{(price / high30 - 1) * 100:+.1f} düşmüş"
    return None


def record_buy(plan: dict, price: float, qty: float, extra: bool = False) -> dict:
    pos = positions.open_position(plan["pair"], price, qty * price, None, None,
                                  "1d", source=f"birikim #{plan['id']}" + (" ekstra" if extra else ""),
                                  market_name=plan["piyasa"], symbol=plan["symbol"])
    positions.update(pos["id"], birikim=plan["id"], adet=qty)
    return positions.get(pos["id"])


def label(plan: dict) -> str:
    flag = "🇹🇷" if plan["piyasa"] == "BIST" else "🪙"
    return f"{flag} #{plan['id']} {plan['varlik']}: her ayın {plan['gun']}'i {plan['tutar']:,.2f} {plan['para']}"


def asset_name(plan: dict) -> str:
    return bist.ticker(plan["symbol"]) if plan["piyasa"] == "BIST" else plan["varlik"]


def label_dict(plan: dict) -> dict:
    return {"id": plan["id"], "varlik": asset_name(plan), "piyasa": plan["piyasa"], "tutar": plan["tutar"],
            "para": plan["para"], "gun": plan["gun"]}

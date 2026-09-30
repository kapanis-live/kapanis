"""Turn of the month (tested rule, see kriptografikbotu/research): hold on the last 2 and first 3 trading days.

BIST trading days skip weekends and official full-day holidays (half days count as trading days).
Crypto trades every day. Religious holidays for 2027 are not in the list yet: windows are marked
"takvim_eksik" then, so the page can say so.
"""
import datetime as dt

TR = dt.timezone(dt.timedelta(hours=3))
BIST_CLOSED = {
    # 2026 (Borsa İstanbul calendar)
    "2026-01-01", "2026-03-20", "2026-04-23", "2026-05-01", "2026-05-19", "2026-05-27", "2026-05-28",
    "2026-05-29", "2026-07-15", "2026-10-29",
    # 2027 fixed national holidays only
    "2027-01-01", "2027-04-23", "2027-05-19", "2027-07-15", "2027-08-30", "2027-10-29",
}
KNOWN_UNTIL = {"BIST": dt.date(2026, 12, 31)}


def trading(day: dt.date, market: str) -> bool:
    if market != "BIST":
        return True
    return day.weekday() < 5 and day.isoformat() not in BIST_CLOSED


def month_days(year: int, month: int, market: str) -> list[dt.date]:
    d = dt.date(year, month, 1)
    out = []
    while d.month == month:
        if trading(d, market):
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def _win(y: int, m: int, market: str) -> list[dt.date]:
    """Window that turns month m of year y into the next: its last 2 and the next month's first 3 trading days."""
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return month_days(y, m, market)[-2:] + month_days(ny, nm, market)[:3]


def window(market: str, today: dt.date | None = None) -> dict:
    """The current or next window, plus whether today is its first day or the first day after the previous one."""
    today = today or dt.datetime.now(TR).date()
    months = []
    for k in (-1, 0, 1):
        mm = today.month + k
        yy = today.year + (mm - 1) // 12
        months.append((yy, (mm - 1) % 12 + 1))
    wins = [_win(y, m, market) for y, m in months]
    idx = next(i for i, w in enumerate(wins) if w[-1] >= today)
    days = wins[idx]
    prev_exit = _next_trading(wins[idx - 1][-1], market) if idx > 0 else None
    return {"piyasa": market, "gunler": [d.isoformat() for d in days], "icinde": days[0] <= today <= days[-1],
            "basliyor_bugun": today == days[0], "bitti_bugun": prev_exit == today,
            "cikis_gunu": _next_trading(days[-1], market).isoformat(),
            "takvim_eksik": market == "BIST" and days[-1] > KNOWN_UNTIL["BIST"]}


def _next_trading(day: dt.date, market: str) -> dt.date:
    d = day + dt.timedelta(days=1)
    while not trading(d, market):
        d += dt.timedelta(days=1)
    return d

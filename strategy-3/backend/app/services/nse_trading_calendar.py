"""NSE/BSE equity trading holidays — for expiry session preponement."""

from __future__ import annotations

from datetime import datetime, timedelta

# Official NSE/BSE closures (equity + equity derivatives). Extend per year as needed.
_NSE_BSE_HOLIDAYS: frozenset[str] = frozenset(
    {
        # 2025
        "2025-01-26",
        "2025-02-19",
        "2025-03-14",
        "2025-03-31",
        "2025-04-10",
        "2025-04-14",
        "2025-04-18",
        "2025-05-01",
        "2025-08-15",
        "2025-08-27",
        "2025-10-02",
        "2025-10-21",
        "2025-10-22",
        "2025-11-05",
        "2025-12-25",
        # 2026
        "2026-01-15",
        "2026-01-26",
        "2026-03-03",
        "2026-03-26",
        "2026-03-31",
        "2026-04-03",
        "2026-04-14",
        "2026-05-01",
        "2026-05-28",  # Bakri Id — May weekly expiry session was 27 May
        "2026-06-26",
        "2026-09-14",
        "2026-10-02",
        "2026-10-20",
        "2026-11-10",
        "2026-11-24",
        "2026-12-25",
        # 2027 (partial — extend when calendar published)
        "2027-01-26",
        "2027-03-22",
        "2027-03-26",
        "2027-08-15",
        "2027-10-02",
        "2027-12-25",
    }
)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def is_trading_day(date_str: str) -> bool:
    """True if date is a weekday and not an NSE/BSE equity holiday."""
    try:
        dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
    except ValueError:
        return False
    if dt.weekday() >= 5:
        return False
    return _iso(dt) not in _NSE_BSE_HOLIDAYS


def resolve_session_expiry_date(contract_expiry: str) -> str:
    """
    Last trading session on or before contract expiry.
    When Thursday expiry is a holiday, session is the prior trading day (e.g. Wed 27 May 2026).
    """
    dt = datetime.strptime(contract_expiry.strip()[:10], "%Y-%m-%d")
    while not is_trading_day(_iso(dt)):
        dt -= timedelta(days=1)
    return _iso(dt)


def previous_trading_day(date_str: str) -> str:
    dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d") - timedelta(days=1)
    while not is_trading_day(_iso(dt)):
        dt -= timedelta(days=1)
    return _iso(dt)

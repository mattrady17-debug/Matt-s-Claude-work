"""US/Eastern time logic and NYSE holiday calendar.

GitHub Actions cron runs on UTC, cannot follow US daylight-saving changes,
and fires late — often by hours — on its shared best-effort scheduler. So
instead of gating on a wall-clock window, every scheduled firing evaluates
the most recent trading day whose after-hours session (20:00 ET) is over,
and a per-day sent marker in the state file guarantees exactly one email per
trading day however many firings arrive and however late they are.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import holidays

EASTERN = ZoneInfo("America/New_York")


def now_eastern() -> datetime:
    return datetime.now(tz=EASTERN)


def nyse_holidays(year: int) -> set[date]:
    cal = holidays.financial_holidays("NYSE", years=[year, year + 1])
    return set(cal.keys())


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in nyse_holidays(d.year)


def latest_completed_trading_day(now: datetime) -> date:
    """The most recent trading day whose after-hours session (20:00 ET) is over."""
    from datetime import timedelta

    d = now.date()
    if not (is_trading_day(d) and now.hour >= 20):
        d -= timedelta(days=1)
        while not is_trading_day(d):
            d -= timedelta(days=1)
    return d


def daily_email_marker(d: date) -> str:
    """State-file key recording that the daily email for `d` was sent."""
    return f"daily-email:{d.isoformat()}"

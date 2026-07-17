"""US/Eastern time gate and NYSE holiday calendar.

GitHub Actions cron runs on UTC and cannot follow US daylight-saving changes,
so the workflow fires two candidate crons and this module decides whether a
given firing is the real 20:00-21:00 ET window on a trading day. With two
crons an hour apart, exactly one lands inside the window year-round.
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


def in_run_window(now: datetime) -> bool:
    """True only during 20:00-20:59 ET, after the after-hours session closes."""
    return now.hour == 20


def should_run(now: datetime | None = None) -> tuple[bool, str]:
    now = now or now_eastern()
    if not is_trading_day(now.date()):
        return False, f"{now.date()} is not a US trading day (weekend or NYSE holiday)"
    if not in_run_window(now):
        return False, f"{now:%H:%M} ET is outside the 20:00-20:59 ET run window"
    return True, "trading day, inside run window"

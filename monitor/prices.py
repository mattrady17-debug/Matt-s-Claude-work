"""Price data via yfinance: prior close, regular-session close, after-hours close."""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time

import yfinance as yf

from .market_calendar import EASTERN

log = logging.getLogger(__name__)

REGULAR_CLOSE = time(16, 0)
AFTER_HOURS_CLOSE = time(20, 0)


@dataclass
class PriceCheck:
    ticker: str
    trade_date: date
    prior_close: float
    regular_close: float | None
    after_hours_close: float | None

    def regular_move_pct(self) -> float | None:
        if self.regular_close is None:
            return None
        return (self.regular_close / self.prior_close - 1.0) * 100.0

    def after_hours_move_pct(self) -> float | None:
        if self.after_hours_close is None:
            return None
        return (self.after_hours_close / self.prior_close - 1.0) * 100.0

    def triggered(self, threshold_pct: float) -> bool:
        return any(
            abs(m) > threshold_pct
            for m in (self.regular_move_pct(), self.after_hours_move_pct())
            if m is not None
        )


def fetch_price_check(ticker: str, trade_date: date) -> PriceCheck | None:
    """Build a PriceCheck for `trade_date` (the US trading day being evaluated)."""
    tk = yf.Ticker(ticker)

    daily = tk.history(period="10d", interval="1d", auto_adjust=False)
    if daily.empty:
        log.warning("%s: no daily price data", ticker)
        return None
    daily = daily[daily.index.date <= trade_date]
    if daily.empty or daily.index[-1].date() != trade_date:
        log.warning("%s: no regular-session bar for %s", ticker, trade_date)
        return None
    if len(daily) < 2:
        log.warning("%s: no prior close available", ticker)
        return None
    regular_close = float(daily["Close"].iloc[-1])
    prior_close = float(daily["Close"].iloc[-2])

    after_hours_close = None
    try:
        intraday = tk.history(period="2d", interval="1m", prepost=True, auto_adjust=False)
        if not intraday.empty:
            idx = intraday.index.tz_convert(EASTERN)
            mask = [
                ts.date() == trade_date and REGULAR_CLOSE < ts.time() <= AFTER_HOURS_CLOSE
                for ts in idx
            ]
            ah = intraday[mask]
            if not ah.empty:
                after_hours_close = float(ah["Close"].iloc[-1])
    except Exception:
        log.exception("%s: after-hours fetch failed; continuing without it", ticker)

    return PriceCheck(
        ticker=ticker,
        trade_date=trade_date,
        prior_close=prior_close,
        regular_close=regular_close,
        after_hours_close=after_hours_close,
    )

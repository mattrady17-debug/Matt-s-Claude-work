"""Price data: yfinance (prior close, regular close, after-hours close) with
retries, plus a Stooq fallback for daily closes when Yahoo rate-limits.

Yahoo aggressively throttles shared IPs like GitHub Actions runners, so every
Yahoo call is retried with backoff, and if Yahoo stays unavailable the daily
closes come from Stooq (free CSV endpoint). Stooq has no after-hours data, so
in fallback mode only the regular-session comparison is possible.
"""

import csv
import io
import logging
import time as time_mod
from dataclasses import dataclass
from datetime import date, datetime, time

import requests
import yfinance as yf

from .market_calendar import EASTERN

log = logging.getLogger(__name__)

REGULAR_CLOSE = time(16, 0)
AFTER_HOURS_CLOSE = time(20, 0)

YAHOO_RETRIES = 3
YAHOO_BACKOFF_SECONDS = (15, 45)  # waits between attempts


def _with_retries(fn, label: str):
    for attempt in range(YAHOO_RETRIES):
        try:
            return fn()
        except Exception as exc:
            if attempt == YAHOO_RETRIES - 1:
                log.warning("%s: giving up after %d attempts (%s)", label, YAHOO_RETRIES, exc)
                raise
            wait = YAHOO_BACKOFF_SECONDS[min(attempt, len(YAHOO_BACKOFF_SECONDS) - 1)]
            log.info("%s: attempt %d failed (%s); retrying in %ds", label, attempt + 1, exc, wait)
            time_mod.sleep(wait)


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


def fetch_stooq_closes(ticker: str, trade_date: date) -> tuple[float, float] | None:
    """(prior_close, regular_close) from Stooq's free daily CSV, or None."""
    url = f"https://stooq.com/q/d/l/?s={ticker.lower()}.us&i=d"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    rows = [r for r in csv.DictReader(io.StringIO(resp.text)) if r.get("Close")]
    rows = [r for r in rows if date.fromisoformat(r["Date"]) <= trade_date]
    if len(rows) < 2 or date.fromisoformat(rows[-1]["Date"]) != trade_date:
        return None
    return float(rows[-2]["Close"]), float(rows[-1]["Close"])


def fetch_price_check(ticker: str, trade_date: date) -> PriceCheck | None:
    """Build a PriceCheck for `trade_date` (the US trading day being evaluated)."""
    tk = yf.Ticker(ticker)

    prior_close = regular_close = None
    try:
        daily = _with_retries(
            lambda: tk.history(period="10d", interval="1d", auto_adjust=False),
            f"{ticker} daily history",
        )
        if daily is not None and not daily.empty:
            daily = daily[daily.index.date <= trade_date]
            if not daily.empty and daily.index[-1].date() == trade_date and len(daily) >= 2:
                regular_close = float(daily["Close"].iloc[-1])
                prior_close = float(daily["Close"].iloc[-2])
    except Exception:
        pass

    if prior_close is None:
        log.warning("%s: Yahoo daily data unavailable; trying Stooq fallback", ticker)
        try:
            closes = fetch_stooq_closes(ticker, trade_date)
        except Exception:
            log.exception("%s: Stooq fallback failed", ticker)
            closes = None
        if closes is None:
            log.warning("%s: no usable daily price data for %s", ticker, trade_date)
            return None
        prior_close, regular_close = closes

    after_hours_close = None
    try:
        intraday = _with_retries(
            lambda: tk.history(period="2d", interval="1m", prepost=True, auto_adjust=False),
            f"{ticker} intraday history",
        )
        if intraday is not None and not intraday.empty:
            idx = intraday.index.tz_convert(EASTERN)
            mask = [
                ts.date() == trade_date and REGULAR_CLOSE < ts.time() <= AFTER_HOURS_CLOSE
                for ts in idx
            ]
            ah = intraday[mask]
            if not ah.empty:
                after_hours_close = float(ah["Close"].iloc[-1])
    except Exception:
        log.warning("%s: after-hours data unavailable; continuing without it", ticker)

    return PriceCheck(
        ticker=ticker,
        trade_date=trade_date,
        prior_close=prior_close,
        regular_close=regular_close,
        after_hours_close=after_hours_close,
    )

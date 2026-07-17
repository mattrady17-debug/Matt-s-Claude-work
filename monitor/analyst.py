"""Analyst reaction data (ratings, target changes, consensus) via yfinance.

This feeds the AI commentary step with factual data from Yahoo Finance's
aggregated analyst records so the summary is grounded, not speculative.
"""

import logging
from datetime import date, timedelta

import yfinance as yf

log = logging.getLogger(__name__)


def fetch_analyst_snapshot(ticker: str, trade_date: date, lookback_days: int = 7) -> dict:
    """Recent rating actions, price targets, and consensus for one ticker."""
    snapshot: dict = {"ticker": ticker, "recent_rating_actions": [], "price_targets": None,
                      "recommendation_summary": None}
    tk = yf.Ticker(ticker)
    since = trade_date - timedelta(days=lookback_days)

    try:
        ud = tk.upgrades_downgrades
        if ud is not None and not ud.empty:
            recent = ud[ud.index.date >= since]
            for ts, row in recent.head(15).iterrows():
                snapshot["recent_rating_actions"].append({
                    "date": str(ts.date()),
                    "firm": str(row.get("Firm", "")),
                    "action": str(row.get("Action", "")),
                    "from_grade": str(row.get("FromGrade", "")),
                    "to_grade": str(row.get("ToGrade", "")),
                })
    except Exception:
        log.exception("%s: upgrades/downgrades fetch failed", ticker)

    try:
        pt = tk.analyst_price_targets
        if pt:
            snapshot["price_targets"] = {
                k: pt.get(k) for k in ("low", "high", "mean", "median", "current")
            }
    except Exception:
        log.exception("%s: price target fetch failed", ticker)

    try:
        rec = tk.recommendations_summary
        if rec is not None and not rec.empty:
            row = rec.iloc[0]
            snapshot["recommendation_summary"] = {
                k: int(row[k]) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")
                if k in row
            }
    except Exception:
        log.exception("%s: recommendation summary fetch failed", ticker)

    return snapshot

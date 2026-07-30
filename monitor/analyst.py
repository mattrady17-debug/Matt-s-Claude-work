"""Analyst reaction data (ratings, target changes, consensus) via yfinance.

This feeds the AI commentary step with factual data from Yahoo Finance's
aggregated analyst records so the summary is grounded, not speculative.
"""

import logging
from datetime import date, timedelta

import yfinance as yf

log = logging.getLogger(__name__)


def fetch_market_context(trade_date: date) -> dict | None:
    """Same-day S&P 500 move, to distinguish stock-specific from market-wide moves."""
    try:
        hist = yf.Ticker("^GSPC").history(period="10d", interval="1d", auto_adjust=False)
        hist = hist[hist.index.date <= trade_date]
        if len(hist) >= 2 and hist.index[-1].date() == trade_date:
            prev, last = float(hist["Close"].iloc[-2]), float(hist["Close"].iloc[-1])
            return {"index": "S&P 500", "date": trade_date.isoformat(),
                    "move_pct": round((last / prev - 1) * 100, 2)}
    except Exception:
        log.exception("market context fetch failed")
    return None


def fetch_analyst_snapshot(ticker: str, trade_date: date, lookback_days: int = 7) -> dict:
    """Rating actions, price targets, consensus, news headlines and earnings
    dates for one ticker - the grounding material for the AI commentary."""
    snapshot: dict = {"ticker": ticker, "recent_rating_actions": [], "price_targets": None,
                      "recommendation_summary": None, "recent_news_headlines": [],
                      "earnings_dates": None}
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

    try:
        for item in (tk.news or [])[:10]:
            content = item.get("content", item)
            title = content.get("title")
            if not title:
                continue
            provider = content.get("provider") or {}
            snapshot["recent_news_headlines"].append({
                "title": title,
                "publisher": provider.get("displayName") or content.get("publisher", ""),
                "published": content.get("pubDate") or content.get("displayTime", ""),
                "summary": (content.get("summary") or "")[:300],
            })
    except Exception:
        log.exception("%s: news fetch failed", ticker)

    try:
        ed = tk.earnings_dates
        if ed is not None and not ed.empty:
            snapshot["earnings_dates"] = [str(ts.date()) for ts in ed.index[:4]]
    except Exception:
        log.exception("%s: earnings dates fetch failed", ticker)

    return snapshot

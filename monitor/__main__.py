"""Daily US stock market monitor.

Usage:
  python -m monitor                      # scheduled mode: send once per trading day
  python -m monitor --dry-run --force    # print the email, send nothing
  python -m monitor --force              # send even if today's email already went out
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from . import ai, announcements, emailer, market_calendar, prices, report
from .analyst import fetch_analyst_snapshot
from .config import ROOT, load_config
from .state import State

log = logging.getLogger("monitor")


def evaluate(cfg, trade_date: date, state: State) -> tuple[str, str, list[str]]:
    """Run all checks. Returns (subject, body, newly_alerted_event_ids)."""
    events: list[report.Event] = []
    new_event_ids: list[str] = []
    triggered_tickers: list[str] = []

    # 1. Price moves ---------------------------------------------------------
    checks: dict[str, prices.PriceCheck] = {}
    failed_tickers: list[str] = []
    for ticker in cfg.tickers:
        check = None
        try:
            check = prices.fetch_price_check(ticker, trade_date)
        except Exception:
            log.exception("%s: price check failed", ticker)
        if check:
            checks[ticker] = check
        else:
            failed_tickers.append(ticker)

    for ticker, check in checks.items():
        event_id = f"{ticker}:price:{trade_date.isoformat()}"
        if check.triggered(cfg.price_move_threshold_pct) and not state.already_alerted(event_id):
            events.append(report.Event(ticker, "Price Move", report.price_move_facts(check)))
            new_event_ids.append(event_id)
            triggered_tickers.append(ticker)

    # 2. Issuer announcements ------------------------------------------------
    candidates = [
        a
        for a in announcements.gather_announcements(
            cfg.tickers, trade_date, cfg.sec_user_agent, cfg.press_release_feeds
        )
        if not state.already_alerted(a.event_id)
    ]

    # 3. Single AI call: filter announcements + write analyst commentary -----
    prelim_tickers = triggered_tickers + [
        a.ticker for a in candidates if a.ticker not in triggered_tickers
    ]
    snapshots = [fetch_analyst_snapshot(t, trade_date) for t in dict.fromkeys(prelim_tickers)]
    ai_out = ai.run_ai_step(
        cfg.anthropic_model,
        [
            {
                "event_id": a.event_id,
                "ticker": a.ticker,
                "source": a.source,
                "kind": a.kind,
                "title": a.title,
                "published_et": a.published_et.isoformat(),
            }
            for a in candidates
        ],
        prelim_tickers,
        snapshots,
    )

    verdicts = {v["event_id"]: v for v in ai_out.get("announcements", [])}
    by_id = {a.event_id: a for a in candidates}
    for event_id, verdict in verdicts.items():
        a = by_id.get(event_id)
        if a is None or not verdict.get("keep"):
            continue
        events.append(
            report.Event(
                a.ticker,
                "Issuer Announcement",
                report.announcement_facts(a, verdict.get("factual_description", a.title)),
                url=a.url,
            )
        )
        new_event_ids.append(event_id)

    commentary = {c["ticker"]: c["text"] for c in ai_out.get("commentary", [])}

    # 4. Compose -------------------------------------------------------------
    if not events:
        subject = f"Stock monitor {trade_date.isoformat()}: no trigger events"
        if failed_tickers:
            subject += " (data issues)"
        body = report.no_trigger_body(trade_date, failed_tickers)
    else:
        tickers = ", ".join(dict.fromkeys(e.ticker for e in events))
        subject = f"Stock monitor {trade_date.isoformat()}: ALERT - {tickers}"
        body = report.trigger_body(trade_date, events, commentary, failed_tickers)
    return subject, body, new_event_ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the email instead of sending it")
    parser.add_argument("--force", action="store_true",
                        help="run even if the daily email was already sent")
    parser.add_argument("--date", help="evaluate a specific date (YYYY-MM-DD), implies --force")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    now_et = market_calendar.now_eastern()
    cfg = load_config()
    state = State(Path(ROOT) / "state" / "state.json")

    # GitHub cron fires late (often by hours), so never gate on the clock:
    # always evaluate the most recent trading day whose after-hours session
    # has completed, and let the sent-marker below guarantee one email/day.
    if args.date:
        trade_date = date.fromisoformat(args.date)
    else:
        trade_date = market_calendar.latest_completed_trading_day(now_et)
    log.info("Evaluating trading day %s (now %s ET)", trade_date, f"{now_et:%Y-%m-%d %H:%M}")

    marker = market_calendar.daily_email_marker(trade_date)
    if not args.force and not args.date:
        if state.already_alerted(marker):
            log.info("Daily email for %s already sent; nothing to do", trade_date)
            return 0

    subject, body, new_event_ids = evaluate(cfg, trade_date, state)
    emailer.deliver(subject, body, cfg.from_email, cfg.recipient_email, dry_run=args.dry_run)

    if not args.dry_run:
        state.record(marker, trade_date)
        for event_id in new_event_ids:
            state.record(event_id, trade_date)
        state.prune(trade_date)
        state.save()
        log.info("State saved (%d new events recorded)", len(new_event_ids))
    else:
        log.info("Dry run: state not updated (%d events would be recorded)", len(new_event_ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())

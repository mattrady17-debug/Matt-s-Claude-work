"""Build the daily email body (plain text)."""

from dataclasses import dataclass
from datetime import date

from .announcements import Announcement
from .prices import PriceCheck


@dataclass
class Event:
    ticker: str
    trigger_type: str          # "Price Move" or "Issuer Announcement"
    facts: str                 # quantified move / factual description
    url: str | None = None


def no_trigger_body(trade_date: date) -> str:
    return (
        f"US Trading Date: {trade_date.isoformat()}\n"
        "Status: No qualifying trigger events today.\n"
        "All monitored securities evaluated successfully.\n"
    )


def price_move_facts(check: PriceCheck) -> str:
    parts = [f"Prior close {check.prior_close:.2f}."]
    reg = check.regular_move_pct()
    if reg is not None:
        parts.append(
            f"Regular-session close {check.regular_close:.2f} ({reg:+.2f}%)."
        )
    ah = check.after_hours_move_pct()
    if ah is not None:
        parts.append(
            f"After-hours close {check.after_hours_close:.2f} ({ah:+.2f}% vs prior close)."
        )
    return " ".join(parts)


def announcement_facts(a: Announcement, description: str) -> str:
    return (
        f"{description} "
        f"[{a.source}, {a.kind}, published {a.published_et:%Y-%m-%d %H:%M} ET]"
    )


def trigger_body(
    trade_date: date,
    events: list[Event],
    commentary: dict[str, str],
) -> str:
    lines = [
        f"US Trading Date: {trade_date.isoformat()}",
        f"Status: {len(events)} qualifying trigger event(s).",
        "",
    ]
    for e in events:
        lines += [
            "=" * 60,
            f"Ticker: {e.ticker}",
            f"Trigger type: {e.trigger_type}",
            f"US trading date: {trade_date.isoformat()}",
            "",
            "Issuer facts:",
            f"  {e.facts}",
        ]
        if e.url:
            lines.append(f"  Source: {e.url}")
        lines.append("")

    tickers_in_order: list[str] = []
    for e in events:
        if e.ticker not in tickers_in_order:
            tickers_in_order.append(e.ticker)
    lines += ["=" * 60, "ANALYST COMMENTARY", "-" * 60]
    for t in tickers_in_order:
        lines += [f"{t}:", f"  {commentary.get(t, 'No commentary available.')}", ""]
    return "\n".join(lines) + "\n"

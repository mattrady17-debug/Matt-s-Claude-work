"""Offline tests exercising the full pipeline with fixture data.

Network calls (Yahoo, SEC, Anthropic, Resend) are stubbed so these run
anywhere. Live-data verification happens via the workflow_dispatch dry run
in GitHub Actions.
"""

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import monitor.__main__ as main_mod
from monitor import market_calendar, report
from monitor.announcements import Announcement
from monitor.config import load_config
from monitor.prices import PriceCheck
from monitor.state import State

ET = ZoneInfo("America/New_York")


# --- market calendar ---------------------------------------------------------

def test_gate_accepts_2030_et_on_trading_day():
    ok, _ = market_calendar.should_run(datetime(2026, 7, 16, 20, 30, tzinfo=ET))
    assert ok

def test_gate_rejects_1930_et():
    ok, reason = market_calendar.should_run(datetime(2026, 7, 16, 19, 30, tzinfo=ET))
    assert not ok and "window" in reason

def test_gate_rejects_weekend_and_holiday():
    assert not market_calendar.should_run(datetime(2026, 7, 18, 20, 30, tzinfo=ET))[0]  # Sat
    assert not market_calendar.should_run(datetime(2026, 7, 3, 20, 30, tzinfo=ET))[0]   # July 4th observed

def test_dst_pair_selects_exactly_one_cron_per_day():
    # 00:30 UTC and 01:30 UTC firings on a summer and a winter trading day
    for d in (date(2026, 7, 16), date(2026, 1, 15)):
        accepted = 0
        for utc_hour in (0, 1):
            fire = datetime(d.year, d.month, d.day + 1, utc_hour, 30, tzinfo=ZoneInfo("UTC"))
            now_et = fire.astimezone(ET)
            if market_calendar.should_run(now_et)[0]:
                accepted += 1
        assert accepted == 1, f"{d}: expected exactly one accepted firing"


# --- price trigger logic -----------------------------------------------------

def make_check(prior=100.0, reg=None, ah=None):
    return PriceCheck("TEST", date(2026, 7, 16), prior, reg, ah)

def test_price_trigger_regular_session():
    assert make_check(reg=106.0).triggered(5.0)          # +6%
    assert make_check(reg=94.0).triggered(5.0)           # -6%
    assert not make_check(reg=104.9).triggered(5.0)      # +4.9%

def test_price_trigger_after_hours_only():
    assert make_check(reg=101.0, ah=106.5).triggered(5.0)
    assert not make_check(reg=101.0, ah=104.0).triggered(5.0)


# --- state / anti-duplication ------------------------------------------------

def test_state_roundtrip_and_dedupe(tmp_path):
    p = tmp_path / "state.json"
    s = State(p)
    assert not s.already_alerted("AMZN:price:2026-07-16")
    s.record("AMZN:price:2026-07-16", date(2026, 7, 16))
    s.save()
    s2 = State(p)
    assert s2.already_alerted("AMZN:price:2026-07-16")


# --- report formats ----------------------------------------------------------

def test_no_trigger_body_exact_format():
    assert report.no_trigger_body(date(2026, 7, 16)) == (
        "US Trading Date: 2026-07-16\n"
        "Status: No qualifying trigger events today.\n"
        "All monitored securities evaluated successfully.\n"
    )

def test_no_trigger_body_reports_data_issues_honestly():
    body = report.no_trigger_body(date(2026, 7, 16), ["FANUY", "TDY"])
    assert "WARNING: price data could not be retrieved for: FANUY, TDY" in body
    assert "evaluated successfully" not in body


def test_trigger_body_contains_required_fields():
    events = [
        report.Event("AMZN", "Price Move", "Prior close 100.00. Regular-session close 106.00 (+6.00%)."),
        report.Event("VRTX", "Issuer Announcement", "8-K: earnings release. [SEC EDGAR]", url="https://sec.gov/x"),
    ]
    body = report.trigger_body(date(2026, 7, 16), events, {"AMZN": "No recent analyst activity.", "VRTX": "Two firms raised targets."})
    for needle in ("US Trading Date: 2026-07-16", "Ticker: AMZN", "Trigger type: Price Move",
                   "Ticker: VRTX", "Trigger type: Issuer Announcement", "ANALYST COMMENTARY",
                   "Two firms raised targets."):
        assert needle in body, needle


# --- end-to-end with stubbed data sources ------------------------------------

def test_full_pipeline_trigger_and_dedupe(monkeypatch, tmp_path, capsys):
    cfg = load_config()
    trade_date = date(2026, 7, 16)

    def fake_price(ticker, d):
        if ticker == "AMZN":
            return PriceCheck(ticker, d, 100.0, 107.5, 108.0)
        return PriceCheck(ticker, d, 100.0, 100.5, None)

    ann = Announcement(
        ticker="VRTX", source="SEC EDGAR", kind="8-K",
        title="8-K: Results of Operations and Financial Condition",
        published_et=datetime(2026, 7, 16, 16, 5, tzinfo=ET),
        url="https://www.sec.gov/Archives/x", event_id="VRTX:edgar:0001-26-000001",
    )

    monkeypatch.setattr(main_mod.prices, "fetch_price_check", fake_price)
    monkeypatch.setattr(main_mod.announcements, "gather_announcements",
                        lambda *a, **k: [ann])
    monkeypatch.setattr(main_mod, "fetch_analyst_snapshot",
                        lambda t, d: {"ticker": t, "recent_rating_actions": []})

    state = State(tmp_path / "state.json")
    subject, body, new_ids = main_mod.evaluate(cfg, trade_date, state)

    assert "ALERT" in subject and "AMZN" in subject and "VRTX" in subject
    assert "Trigger type: Price Move" in body
    assert "Trigger type: Issuer Announcement" in body
    assert "+7.50%" in body and "+8.00%" in body
    assert set(new_ids) == {"AMZN:price:2026-07-16", "VRTX:edgar:0001-26-000001"}

    # Record and re-run: nothing should re-trigger for the same events.
    for eid in new_ids:
        state.record(eid, trade_date)
    subject2, body2, new_ids2 = main_mod.evaluate(cfg, trade_date, state)
    assert new_ids2 == []
    assert "No qualifying trigger events today." in body2


def test_full_pipeline_no_trigger(monkeypatch, tmp_path):
    cfg = load_config()
    trade_date = date(2026, 7, 16)
    monkeypatch.setattr(main_mod.prices, "fetch_price_check",
                        lambda t, d: PriceCheck(t, d, 100.0, 101.0, 100.8))
    monkeypatch.setattr(main_mod.announcements, "gather_announcements", lambda *a, **k: [])
    state = State(tmp_path / "state.json")
    subject, body, new_ids = main_mod.evaluate(cfg, trade_date, state)
    assert new_ids == []
    assert body == report.no_trigger_body(trade_date)
    assert "no trigger" in subject

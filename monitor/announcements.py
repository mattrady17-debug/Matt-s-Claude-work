"""Issuer announcements: SEC EDGAR filings and company press-release RSS feeds.

Only announcements published 09:30-20:00 ET on the evaluated trading day are
candidates. A later AI step filters out anything on the exclusion list
(analyst notes, media recaps, etc.); this module only gathers primary-source
items, so most of what it returns already qualifies.
"""

import email.utils
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time

import requests

from .market_calendar import EASTERN

log = logging.getLogger(__name__)

WINDOW_START = time(9, 30)
WINDOW_END = time(20, 0)

# Filing forms that can carry material issuer news. Routine ownership and
# registration paperwork (forms 3/4/5, 144, S-8, 13G/13D amendments) is
# excluded outright.
MATERIAL_FORMS = {
    "8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A",
    "6-K", "6-K/A", "20-F", "20-F/A", "425", "DEF 14A", "DEFA14A",
}

CIK_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


@dataclass
class Announcement:
    ticker: str
    source: str        # "SEC EDGAR" or "Press release (RSS)"
    kind: str          # form type or "Press release"
    title: str
    published_et: datetime
    url: str
    event_id: str      # stable id for anti-duplication


def _in_window(dt_et: datetime, trade_date: date) -> bool:
    return dt_et.date() == trade_date and WINDOW_START <= dt_et.time() <= WINDOW_END


def load_cik_map(user_agent: str) -> dict[str, int]:
    """Ticker -> CIK for all SEC registrants. Tickers absent here (e.g. many
    unsponsored ADRs like FANUY) simply have no EDGAR coverage."""
    resp = requests.get(CIK_MAP_URL, headers={"User-Agent": user_agent}, timeout=30)
    resp.raise_for_status()
    return {row["ticker"].upper(): int(row["cik_str"]) for row in resp.json().values()}


def fetch_edgar_filings(
    ticker: str, cik: int, trade_date: date, user_agent: str
) -> list[Announcement]:
    url = SUBMISSIONS_URL.format(cik=cik)
    resp = requests.get(url, headers={"User-Agent": user_agent}, timeout=30)
    resp.raise_for_status()
    recent = resp.json().get("filings", {}).get("recent", {})

    out: list[Announcement] = []
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    accepted = recent.get("acceptanceDateTime", [])
    docs = recent.get("primaryDocument", [])
    descs = recent.get("primaryDocDescription", [])
    for i, form in enumerate(forms):
        if form not in MATERIAL_FORMS:
            continue
        try:
            accepted_dt = datetime.fromisoformat(accepted[i].replace("Z", "+00:00"))
        except (ValueError, IndexError):
            continue
        accepted_et = accepted_dt.astimezone(EASTERN)
        if not _in_window(accepted_et, trade_date):
            continue
        accession = accessions[i]
        doc = docs[i] if i < len(docs) else ""
        desc = descs[i] if i < len(descs) and descs[i] else form
        filing_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/"
            f"{accession.replace('-', '')}/{doc}"
        )
        out.append(
            Announcement(
                ticker=ticker,
                source="SEC EDGAR",
                kind=form,
                title=f"{form}: {desc}",
                published_et=accepted_et,
                url=filing_url,
                event_id=f"{ticker}:edgar:{accession}",
            )
        )
    return out


def fetch_rss_items(ticker: str, feed_url: str, trade_date: date, user_agent: str) -> list[Announcement]:
    resp = requests.get(feed_url, headers={"User-Agent": user_agent}, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    out: list[Announcement] = []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = root.findall(".//item") or root.findall(".//atom:entry", ns)
    for item in items:
        title = (item.findtext("title") or item.findtext("atom:title", namespaces=ns) or "").strip()
        link = item.findtext("link") or ""
        if not link:
            link_el = item.find("atom:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
        pub = (
            item.findtext("pubDate")
            or item.findtext("atom:published", namespaces=ns)
            or item.findtext("atom:updated", namespaces=ns)
        )
        if not pub or not title:
            continue
        try:
            pub_dt = email.utils.parsedate_to_datetime(pub)
        except (TypeError, ValueError):
            try:
                pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            except ValueError:
                continue
        if pub_dt.tzinfo is None:
            continue
        pub_et = pub_dt.astimezone(EASTERN)
        if not _in_window(pub_et, trade_date):
            continue
        out.append(
            Announcement(
                ticker=ticker,
                source="Press release (RSS)",
                kind="Press release",
                title=title,
                published_et=pub_et,
                url=link,
                event_id=f"{ticker}:rss:{link or title}",
            )
        )
    return out


def gather_announcements(
    tickers: list[str],
    trade_date: date,
    user_agent: str,
    press_release_feeds: dict[str, list[str]],
) -> list[Announcement]:
    try:
        cik_map = load_cik_map(user_agent)
    except Exception:
        log.exception("Could not load SEC ticker->CIK map; skipping EDGAR checks")
        cik_map = {}

    out: list[Announcement] = []
    for ticker in tickers:
        cik = cik_map.get(ticker)
        if cik:
            try:
                out.extend(fetch_edgar_filings(ticker, cik, trade_date, user_agent))
            except Exception:
                log.exception("%s: EDGAR fetch failed", ticker)
        for feed_url in press_release_feeds.get(ticker, []):
            try:
                out.extend(fetch_rss_items(ticker, feed_url, trade_date, user_agent))
            except Exception:
                log.exception("%s: RSS fetch failed (%s)", ticker, feed_url)
    return out

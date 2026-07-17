"""One Claude call per run, doing exactly two jobs:

1. Filter candidate announcements against the exclusion list (analyst notes,
   broker commentary, target/ratings changes, media summaries, recaps,
   follow-up reporting are NOT primary issuer announcements).
2. Write the factual analyst-commentary section for each triggered ticker,
   grounded strictly in the analyst data provided.

If no ANTHROPIC_API_KEY is configured (e.g. local dry runs), the step degrades
gracefully: announcements are kept as pre-filtered and commentary is a notice.
"""

import json
import logging
import os

log = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "properties": {
        "announcements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                    "keep": {"type": "boolean"},
                    "reason": {"type": "string"},
                    "factual_description": {"type": "string"},
                },
                "required": ["event_id", "keep", "reason", "factual_description"],
                "additionalProperties": False,
            },
        },
        "commentary": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["ticker", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["announcements", "commentary"],
    "additionalProperties": False,
}

SYSTEM = """You assist a daily stock-market monitor. You have two jobs and only two.

JOB 1 - Filter announcements. Keep an item only if it is a NEW primary
issuer-released material announcement: an earnings release, an SEC filing,
a mandatory regulatory disclosure, or an official company press release.
Exclude: analyst notes, broker commentary, target price changes, ratings
changes, media summaries, market recaps, commentary about previous events,
and follow-up reporting. For each kept item write a one-sentence factual
description with no speculation.

JOB 2 - Analyst commentary. For each ticker listed under "triggered_tickers",
write a short paragraph summarising post-event analyst reaction ONLY:
ratings actions, price-target changes, and consensus themes, drawn strictly
from the analyst data provided. Name firms where the data includes them.
No speculation, no predictions, no advice. If the data shows no recent
analyst activity, say exactly that."""


def run_ai_step(
    model: str,
    candidate_announcements: list[dict],
    triggered_tickers: list[str],
    analyst_snapshots: list[dict],
) -> dict:
    """Returns {"announcements": [...], "commentary": [...]} per SCHEMA."""
    fallback = {
        "announcements": [
            {
                "event_id": a["event_id"],
                "keep": True,
                "reason": "AI filter unavailable; kept by pre-filter",
                "factual_description": a["title"],
            }
            for a in candidate_announcements
        ],
        "commentary": [
            {
                "ticker": t,
                "text": "Analyst commentary unavailable (Anthropic API key not configured).",
            }
            for t in triggered_tickers
        ],
    }

    if not candidate_announcements and not triggered_tickers:
        return {"announcements": [], "commentary": []}
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY not set; skipping AI step")
        return fallback

    import anthropic

    payload = {
        "candidate_announcements": candidate_announcements,
        "triggered_tickers": triggered_tickers,
        "analyst_data": analyst_snapshots,
    }
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=4000,
            system=SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
        )
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)
    except Exception:
        log.exception("AI step failed; using fallback output")
        return fallback

"""Send the daily email via Resend, or print it in dry-run mode."""

import logging
import os

import requests

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


def deliver(subject: str, body: str, from_email: str, to_email: str, dry_run: bool) -> None:
    if dry_run:
        print("=" * 70)
        print("DRY RUN - the following email would be sent (nothing was sent)")
        print(f"From:    {from_email}")
        print(f"To:      {to_email}")
        print(f"Subject: {subject}")
        print("-" * 70)
        print(body)
        print("=" * 70)
        return

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not set; cannot send email")

    resp = requests.post(
        RESEND_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"from": from_email, "to": [to_email], "subject": subject, "text": body},
        timeout=30,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Resend API error {resp.status_code}: {resp.text}")
    log.info("Email sent: %s", resp.json().get("id"))

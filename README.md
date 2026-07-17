# Daily US Stock Market Monitor

A small Python program, run by GitHub Actions each US trading day after the
after-hours session closes (~20:30 New York time). It checks a list of tickers
for two kinds of trigger and sends exactly one email per day via
[Resend](https://resend.com):

1. **Price move** — the regular-session close *or* the after-hours close moved
   more than ±5% versus the prior regular-session close.
2. **Issuer announcement** — a new primary, issuer-released material
   announcement published 09:30–20:00 ET that day: earnings releases, SEC
   filings, mandatory regulatory disclosures, official company press releases.
   Analyst notes, ratings/target changes, media recaps and follow-up reporting
   never trigger.

On quiet days it still sends a short "no qualifying trigger events" email, so
silence always means "something is broken", never "nothing happened".

## How it works

| Piece | Implementation |
|---|---|
| Prices | [yfinance](https://github.com/ranaroussi/yfinance) (free Yahoo Finance data) |
| Announcements | SEC EDGAR submissions API + optional company press-release RSS feeds |
| AI step | One call per run to Claude Haiku (`claude-haiku-4-5`): filters announcements against the exclusion list and writes the analyst-commentary summary from yfinance analyst data. Costs roughly $1–3/month. |
| Email | Resend (free tier: 100 emails/day) |
| Schedule | GitHub Actions cron. Cron is UTC, so two entries fire (00:30 and 01:30 UTC) and the program's own New York clock accepts exactly one — the one inside 20:00–20:59 ET — so daylight-saving changes never break the schedule. Weekends and NYSE holidays are skipped in code. |
| Anti-duplication | `state/state.json` records every event already alerted on; the workflow commits it back after each real run. The same filing or same-day price move never alerts twice; a fresh >5% move on a later trading day is a new trigger. |

## Changing the ticker list

Edit `tickers.txt` — one ticker per line, `#` for comments — and commit. That's
it. Note: tickers that aren't SEC registrants (e.g. the ADR FANUY) get no
EDGAR coverage; add a press-release RSS feed for them in `config.yaml` under
`press_release_feeds`.

## Other settings

All in `config.yaml`: recipient address, sender address, the ±% threshold,
per-ticker RSS feeds, and the Claude model.

## Running locally

```bash
pip install -r requirements.txt
python -m monitor --dry-run --force          # print today's email, send nothing
python -m monitor --dry-run --date 2026-07-15  # evaluate a specific past day
python -m pytest tests/                      # offline test suite
```

`--dry-run` prints the exact email instead of sending and never touches the
state file. Without `ANTHROPIC_API_KEY` set, the AI step is skipped gracefully.

## Setting up your own copy

1. **Repo** — fork or copy this repository (keep it private). Put your tickers
   in `tickers.txt` and your email address in `config.yaml`.
2. **Resend** — create a free account at resend.com, create an API key. The
   default `onboarding@resend.dev` sender works without any domain setup but
   can only deliver to your own Resend account email; verify a domain to send
   anywhere.
3. **Anthropic** — create an API key at platform.claude.com (a few dollars of
   credit lasts months at Haiku prices).
4. **Secrets** — in the GitHub repo: Settings → Secrets and variables →
   Actions → New repository secret. Add `RESEND_API_KEY` and
   `ANTHROPIC_API_KEY`.
5. **Test** — Actions tab → "Daily stock monitor" → Run workflow with
   *Dry run = true*. Read the printed email in the log. Then run once with
   *Dry run = false* to send a real test email.
6. **Go live** — uncomment the `schedule:` block in
   `.github/workflows/daily-monitor.yml` and commit to the default branch.

## Manual runs

Actions → "Daily stock monitor" → Run workflow. *Dry run = true* prints the
email into the workflow log; *false* actually sends it and updates the state
file. Both skip the time-of-day gate so you can test at any hour.

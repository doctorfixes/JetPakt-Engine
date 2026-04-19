# JetPakt CLI

Deterministic, offline-testable ops CLI for the Denver leadgen pipeline. The CLI never calls external APIs — it emits JSON **plan files** the main agent applies via connectors (Google Sheets, Outlook).

## Usage

```bash
cd /home/user/workspace/denver_leadgen
./jetpakt status
./jetpakt smoke output/outreach/<wave_dir> [--mapping <mapping.json>]
./jetpakt prep-sync <wave_dir> --mapping <mapping.json>       # -> sync_plan.json
./jetpakt stage-outlook <wave_dir> --mapping <mapping.json>   # -> outlook_plan.json
./jetpakt plan <wave_dir> --mapping <mapping.json>            # both plans
./jetpakt wave <wave_dir> --mapping <mapping.json>            # plan + apply summary

./jetpakt inbox-plan --prospects <prospects.json> [--out <path>] [--lookback-days 3]
./jetpakt inbox-apply --prospects <prospects.json> --hits <hits.json> [--out <path>]
```

## Mapping schema

One JSON object per wave, keyed by `business_name` (as it appears in `manifest.json`):

```json
{
  "3 Sons Italian Restaurant and Bar": {
    "prospect_id": "arvada_3_sons_italian",
    "pillar": "Service",
    "case_id": "I08",
    "next_action_due": "2026-04-21",
    "email": "info@3sonsitalian.com",
    "legal_severity": "NONE"
  }
}
```

`legal_severity = "HIGH"` triggers an extra smoke gate requiring an HB25 1090 / service-charge disclosure note in the body.

## Plan files

- **`sync_plan.json`** — Prospect row updates + Outreach Log appends. Agent applies via `google_sheets__pipedream`.
- **`outlook_plan.json`** — One `draft_email` action per draft (with `to`, `subject`, plain-text `body`, and `idempotency_key`). Agent applies via `outlook.draft_email`.
- **`inbox_query_plan.json`** — List of Outlook `search_email` queries (one `from:@<domain>` per prospect + one generic bounce probe). Agent runs each query, normalizes hits into the `Hit` schema, and feeds the list to `inbox-apply`.
- **`inbox_apply_plan.json`** — Sheet actions derived from classified hits: Prospects stage flips (`Replied` / `Disqualified`), Outreach Log inbound appends, and Suppression tab appends for bounces and unsubscribes.

### Idempotency

Every Outlook action carries `idempotency_key = outlook_draft::<prospect_id>::<subject_hash8>`. The agent should check for an existing Outreach Log row with `log_id` matching the prospect_id + wave_name + date before re-appending. Outlook has no `list_drafts` tool today, so Outlook-side dedupe is manual.

## Smoke gates (all must PASS before plans emit)

1. subject not empty
2. subject <= 45 chars
3. body excludes `denver` and food-poisoning tokens
4. no em/en-dash in author copy (verbatim quotes exempt)
5. Parker postal address present
6. single Ryan signature block
7. verbatim quote block present
8. no `scrape` / `crawl` language
9. `gojetpakt.com` present
10. **LEGAL-HIGH only**: service-charge disclosure / HB25 1090 note present

## Architecture

```
draft.md   --->  smoke gates  --->  sync_plan.json    --->  Sheets connector
    |                           \                                 
manifest.json --- mapping.json -->  outlook_plan.json --->  Outlook connector
```

The CLI is pure Python with zero external dependencies. Plans are JSON so they can be diffed in git, inspected before apply, and re-applied idempotently.

## Inbox scan (reply + bounce cron)

`inbox-plan` and `inbox-apply` split the reply/bounce scan into two offline steps so the agent's only connector calls are the actual Outlook queries and Sheet writes.

```
prospects.json --> inbox-plan  --> inbox_query_plan.json
                                       |
                       agent runs outlook.search_email per query
                                       v
                                  hits.json (normalized)
                                       |
prospects.json + hits.json --> inbox-apply --> inbox_apply_plan.json
                                       |
                       agent applies via google_sheets connector
```

Classification (in `inbox.py`) is deterministic:

- **bounce** — sender is `mailer-daemon`/`postmaster`, or subject contains `undeliverable`; prospect recovered by scanning body for a known domain.
- **unsubscribe** — sender domain matches a prospect AND body contains an opt-out token (`remove me`, `unsubscribe`, `not interested`, ...).
- **reply** — sender domain matches a prospect, no opt-out tokens. Sentiment is a crude keyword classifier (flag-for-review, not perfect).
- **ignore** — sender does not match any prospect domain.

### Hit schema (what the cron feeds to `inbox-apply`)

```json
[
  {
    "message_id": "...",
    "from_email": "kay@schoolhousearvada.com",
    "from_name": "Kay",
    "subject": "Re: proposal",
    "received_at": "2026-04-18T15:01:00Z",
    "body_preview": "Please remove me from your list.",
    "to_list": ["gojetpakt.us@outlook.com"]
  }
]
```

### Suppression tab

Unsubscribes append one row with `type=email` (single address suppressed); bounces append one row with `type=domain` (the whole domain is suppressed). Schema: `email_or_domain, type, reason, prospect_id, suppressed_at, source`.

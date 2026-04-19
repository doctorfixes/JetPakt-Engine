# JetPakt daily inbox scan — cron task

**Schedule:** `0 8 * * *` UTC (= 1am MST / 2am MDT daily)
**Background:** true (no conversation context needed)
**Exact:** true (runs on the hour)

## Task description (self-contained — paste into `schedule_cron`)

---

You are running the JetPakt daily inbox scan. Your job is to check the `gojetpakt.us@outlook.com` inbox for replies and bounces from the prospect roster in the CRM Master Sheet, then update the Sheet and send a notification if any new replies were found.

### Sheet + roster

- Sheet ID: `1L2NqIcZeG_SMqoL_L3YN_IlqiVkMWy4SyBsu2Sa07yI`
- Tabs (worksheetIds): `Prospects=2139708364`, `Outreach Log=250333527`, `Suppression=1712783155`
- Prospects schema (26 columns A..Z): `prospect_id, business_name, category, neighborhood, city, state, rating, review_count, peer_gap, rating_12mo_delta, priority_tier, dominant_pillar, ros_case_id, legal_flag_severity, google_url, yelp_url, website, owner_name, owner_email, source, stage, stage_entered_at, next_action_due, notes, created_at, updated_at`
- Outreach Log schema (16 columns A..P): `log_id, prospect_id, direction, channel, touch_type, template_version, subject, body_excerpt, draft_file, pillar, case_id, sent_at, reply_received_at, reply_sentiment, result, created_at`
- Suppression schema (6 columns A..F): `email_or_domain, type, reason, prospect_id, suppressed_at, source`

### Steps

1. **Pull roster.** Call `google_sheets-read-rows` with `spreadsheetId=1L2NqIcZeG_SMqoL_L3YN_IlqiVkMWy4SyBsu2Sa07yI`, `sheetName=Prospects`, `hasHeaders=true`. Keep only rows where `stage` is `Drafted`, `Sent`, or `Replied` AND `owner_email` is non-empty. For each, capture `{prospect_id, business_name, owner_email, stage, legal_flag_severity}`.

2. **Build query plan (offline).** Write the roster to `/home/user/workspace/cron_tracking/{cron_id}/prospects.json` as a JSON list of `{prospect_id, business_name, owner_email, stage, legal_severity}` (rename `legal_flag_severity` to `legal_severity`). Then run:
   ```bash
   cd /home/user/workspace/denver_leadgen && ./jetpakt inbox-plan \
     --prospects /home/user/workspace/cron_tracking/{cron_id}/prospects.json \
     --out /home/user/workspace/cron_tracking/{cron_id}/inbox_query_plan.json
   ```

3. **Run Outlook queries.** Read `inbox_query_plan.json`. For each query object, call the `outlook` connector tool `search_email` with the `query` string and a limit of ~25. You can use `from:@<domain>` for the reply probes and the combined postmaster/undeliverable string for the bounce probe. Restrict to the last 3 days if the connector supports a date range (use `received_after=<3 days ago ISO>`).

4. **Normalize hits.** For each raw hit from Outlook, emit an object matching this schema:
   ```json
   {
     "message_id": "<id>",
     "from_email": "<sender address>",
     "from_name": "<sender name>",
     "subject": "<subject>",
     "received_at": "<ISO 8601>",
     "body_preview": "<first ~500 chars of body>",
     "to_list": ["<address>", "..."]
   }
   ```
   Deduplicate by `message_id`. Save all hits to `/home/user/workspace/cron_tracking/{cron_id}/hits.json` as a JSON list.

5. **Classify + build apply plan (offline).** Run:
   ```bash
   cd /home/user/workspace/denver_leadgen && ./jetpakt inbox-apply \
     --prospects /home/user/workspace/cron_tracking/{cron_id}/prospects.json \
     --hits /home/user/workspace/cron_tracking/{cron_id}/hits.json \
     --out /home/user/workspace/cron_tracking/{cron_id}/inbox_apply_plan.json
   ```

6. **Apply Sheet writes.** Read `inbox_apply_plan.json`. For each:
   - **`outreach_log_appends`**: Call `google_sheets-add-multiple-rows` with `spreadsheetId` and `sheetName="Outreach Log"`, and `rows` as a stringified JSON array of arrays. Each inner array must follow the Outreach Log column order (16 cols A..P). Convert the `row_object` to a positional array using the schema above.
   - **`prospect_updates`**: For each update, first call `google_sheets-find-row` with `spreadsheetId`, `sheetName="Prospects"`, `column="A"`, `value=<prospect_id>` to get the row number N. Then read that row (A{N}:Z{N}) via `google_sheets-read-rows` with `hasHeaders=false` to get the current 26 cells. Mutate in Python: set col U (index 20) to the new `stage`, col X (index 23) to `existing_notes + "; " + notes_append` (skip the "; " if existing is blank), col Z (index 25) to `updated_at`. Then call `google_sheets-update-multiple-rows` with `range=f"A{N}:Z{N}"` and `rows=json.dumps([updated_26_cells])`.
   - **`suppression_appends`**: Call `google_sheets-add-multiple-rows` with `sheetName="Suppression"` and positional arrays matching the 6-col schema.

7. **Notify.** If `summary.replies > 0` OR `summary.unsubscribes > 0`, call `send_notification` with:
   - `title`: `"JetPakt: {replies} reply / {unsubscribes} unsub / {bounces} bounce"`
   - `body`: one line per classified hit — `"{business_name}: {kind} ({sentiment}) — {subject}"`. Include a link to the Sheet at the bottom: `https://docs.google.com/spreadsheets/d/1L2NqIcZeG_SMqoL_L3YN_IlqiVkMWy4SyBsu2Sa07yI/edit`.
   - `schedule_description`: `"Daily · 1am MST"`
   - `url`: the Sheet URL.

   If `summary.replies == 0 AND summary.unsubscribes == 0 AND summary.bounces == 0`: end silently (no notification).

   If only bounces were found (no replies, no unsubs): send a notification only if this is the first bounce for that domain (check `inbox_apply_plan.json` — if `suppression_appends` is non-empty, notify).

### Failure handling

- If any connector call fails with auth errors or returns `requires_auth=true`, do NOT retry repeatedly. Write a one-line failure log to `/home/user/workspace/cron_tracking/{cron_id}/failure.log` and end the run.
- If the roster is empty (no Drafted/Sent/Replied prospects with emails), end silently.
- If `inbox-plan` or `inbox-apply` returns non-zero exit code, write the stderr to `failure.log` and end.

### Files produced per run

All under `/home/user/workspace/cron_tracking/{cron_id}/`:
- `prospects.json` — roster snapshot
- `inbox_query_plan.json` — Outlook queries
- `hits.json` — normalized Outlook hits
- `inbox_apply_plan.json` — Sheet actions (this is the auditable record of what was applied)
- `failure.log` (only on error)

### Constraints

- Never send a reply or new email. This task is read + classify + record only.
- Never call `delete_*` or modify the inbox itself.
- Stage transitions allowed: `Drafted|Sent → Replied` on reply, `Drafted|Sent|Replied → Disqualified` on unsubscribe or bounce. Never downgrade a prospect that is already `Disqualified`.


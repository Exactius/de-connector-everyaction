---
name: ea-manual-backfill
description: Recover a missed EveryAction (EA) daily contribution export for a partner (whitestork by default) end to end, driving the operator's logged-in Chrome with browser-use. Use it whenever the EA email did not arrive, the whitestork_pipeline_daily task extract_ea_contribution failed with "No messages found" / HTTP 404, bronze.every_action_contribution_report is stale, an EA scheduled report shows "Failed", or someone asks to backfill, re-export, re-upload or reschedule the EveryAction contribution report — even if they only say "the EA data is missing" or "whitestork donations are stale". Covers diagnosis, EA export, CSV validation against the previous bronze batch, dry-run in the internal scratch dataset, append to the partner bronze table, post-upload checks, schedule recreation and the dbt hand-off. Do not use it for the email-path service itself (Cloud Run deploys, code changes) or for Scenario B full-history replacement.
---

# EA manual backfill (Scenario A of the manual CSV walkthrough)

This skill is the executable form of
[`manual_processing/MANUAL_EA_CSV_WALKTHROUGH.md`](../../../manual_processing/MANUAL_EA_CSV_WALKTHROUGH.md),
Scenario A. It exists because an EA scheduled report that fails is **dead, not delayed**: EA never
retries it and never runs it the next day. Every few weeks someone has to export the report by hand,
push it into bronze and recreate the schedule. The human runbook stays the reference; this skill makes
the run reproducible by anyone on the team and adds the checks that the runbook leaves implicit.

The operator (the human running this) keeps three things that cannot and should not be automated:
their EA login in Chrome, the go/no-go before writing to the partner's BigQuery, and the click on
EA's "Schedule" button. Everything else is scripted here.

## Read this first

- **Prerequisites** are in [references/prerequisites.md](references/prerequisites.md): gcloud login + ADC,
  the service's Python env, `browser-use`, Chrome remote debugging, and the Claude Code permission rule
  for `browser-use`. Run the checks at the top of that file before anything else; half of the failed
  runs are a missing prerequisite, not a bug.
- **Partner parameters** are in the table below. Everything partner-specific is an environment
  variable or a script argument; nothing is hard-coded in the scripts.
- **The EA UI map** ([references/ea-ui-map.md](references/ea-ui-map.md)) documents every URL, element
  id and behaviour the browser scripts rely on. When a browser script fails, that file is where to look
  before editing the script.
- **Why the CSV path differs from the email path** and what the dbt lineage tolerates:
  [references/csv-vs-email-path.md](references/csv-vs-email-path.md). Read it before promising
  "identical data" to anyone.

## Partner parameters

| Variable | whitestork | How to find it for another partner |
| --- | --- | --- |
| `PARTNER` | `whitestork` | key of `PARTNER_CONFIGS` in `src/core/process_every_action_data.py` |
| `BQ_PROJECT` | `ex-whitestork` | `project_id` of the caller task in `Airflow_dags_v2` (`dags/<partner>/daily/v1/pipeline/tasks/ingestion/ea.yaml`) |
| `BQ_DATASET` / `BQ_TABLE` | `bronze` / `every_action_contribution_report` | same yaml |
| `EA_COMMITTEE` | `Operation White Stork` | the committee shown on EA's "Select User" page after login |
| `EA_TEMPLATE_NAME` | `Exactius_Contribution_Report - whitestork` | the `email_name_search_key` subject in `PARTNER_CONFIGS`, minus the `EveryAction Scheduled Report - ` prefix |
| `EA_TEMPLATE_URL` | `https://app.everyaction.com/ReportViewer.aspx?ReportId=EID1B&TemplateId=EID1A871K` | Report Manager → Saved Templates → link of the template row |
| `EA_SCHEDULE_URL` | `https://app.everyaction.com/ReportScheduleDetails.aspx?TemplateId=96417` | Report Viewer → Report Actions → Schedule, copy the URL |
| `EA_RECIPIENTS` | `data.analysis@exacti.us, ian.s@exacti.us, nelson@exacti.us` | `data.analysis@exacti.us` is what the service reads; the rest is courtesy |
| `DBT_MODEL` | `every_action_contribution_report` in `whitestork_DBT_V2` | the silver model reading the bronze source |
| `DAG_ID` | `whitestork_pipeline_daily` | the DAG whose dbt tasks the operator reruns at the end |

The email subject is the contract: the service's Gmail search is
`subject:"EveryAction Scheduled Report - <EA_TEMPLATE_NAME>"`, and EA builds the subject from the
schedule's "Schedule Name/Email Subject" field. A typo there silently breaks tomorrow's ingestion.

## Workflow

Treat the numbered steps as gates: each one prints facts the next one depends on, and three of them
stop for the operator. Run scripts from the repo root with the variables exported in the shell.

```bash
export PARTNER=whitestork BQ_PROJECT=ex-whitestork BQ_DATASET=bronze BQ_TABLE=every_action_contribution_report
export EA_COMMITTEE="Operation White Stork" EA_TEMPLATE_NAME="Exactius_Contribution_Report - whitestork"
export EA_TEMPLATE_URL="https://app.everyaction.com/ReportViewer.aspx?ReportId=EID1B&TemplateId=EID1A871K"
export EA_SCHEDULE_URL="https://app.everyaction.com/ReportScheduleDetails.aspx?TemplateId=96417"
export EA_RECIPIENTS="data.analysis@exacti.us, ian.s@exacti.us, nelson@exacti.us"
export WORK=/tmp/ea-backfill-$(date +%Y%m%d) && mkdir -p "$WORK"
```

### 1. Confirm the gap (read-only)

```bash
bash .claude/skills/ea-manual-backfill/scripts/bronze_status.sh "$BQ_PROJECT" "$BQ_DATASET" "$BQ_TABLE"
```

It prints the last ingestion timestamp, rows per `date_received` for the last 14 days, and rows per
ingestion day. A healthy table shows one batch per day at the DAG hour (11:30 UTC for whitestork) and
the last `date_received` equal to yesterday or today. The gap is real when the last batch is older
than today's DAG run.

Cross-check the cause so you fix the right thing:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="ea-email-service" AND timestamp>="'$(date -u -v-1d +%Y-%m-%dT00:00:00Z)'"' \
  --project peppy-castle-368715 --limit 40 --format='value(timestamp,httpRequest.status,textPayload)' | grep -E "No messages found|POST /process"
```

`No messages found matching the search criteria` + `404` means EA did not send the email. Anything
else (token refresh error, 500, BigQuery error) is a service problem and this skill is the wrong tool.
If a Gmail tool is available, a search on the subject for the last 3 days settles it in one call.

Then look at EA's schedule list, which usually tells the whole story:

```bash
EA_TEMPLATE_NAME="$EA_TEMPLATE_NAME" browser-use < .claude/skills/ea-manual-backfill/scripts/ea_scheduled_status.py
```

Expect a row `Scheduled by … on <date> · Failed` for the current schedule. Several `Failed` rows for
the same template are normal history: each one is a previous manual recreation.

### 2. Export the report from EA (browser)

Precondition: Chrome is open, the operator is logged in to EA, remote debugging is enabled
(prerequisites). The script opens the saved template in its Report Viewer, checks the applied filters,
triggers `Export As → CSV`, waits for the asynchronous export in "My Export Files", and downloads the
zip into `$WORK/download/`.

```bash
mkdir -p "$WORK/download"
EA_TEMPLATE_URL="$EA_TEMPLATE_URL" EA_COMMITTEE="$EA_COMMITTEE" EA_DOWNLOAD_DIR="$WORK/download" \
  browser-use < .claude/skills/ea-manual-backfill/scripts/ea_export.py
```

The script prints `FILTERS: …` (expect `Date Received: 1/1/<yy> - 12/31/<yy>`, i.e. the same YTD
scope as the daily email: the scheduled report and the saved template share the filters) and ends with
`DOWNLOADED: <path>.zip`. It stops with `LOGIN_REQUIRED` or `SELECT_COMMITTEE_REQUIRED` when the
session is not where it expects; fix that in Chrome and rerun. Exports of ~80 000 rows take about a
minute; the script polls for up to 10 minutes.

```bash
cd "$WORK/download" && unzip -o -q *.zip && ls -la && cd -
```

The CSV is UTF-16 with a first line `SEP=,`; the service handles both, the validation script too.

### 3. Validate before writing anything

Export the previous bronze batch and compare the CSV against it:

```bash
bash .claude/skills/ea-manual-backfill/scripts/export_batch_keys.sh "$BQ_PROJECT" "$BQ_DATASET" "$BQ_TABLE" "$WORK/previous_batch.csv"
.venv/bin/python -I .claude/skills/ea-manual-backfill/scripts/validate_csv.py \
  --csv "$WORK"/download/ContributionReport-*.csv --previous "$WORK/previous_batch.csv"
```

The report answers the questions the operator will ask: scope (min/max date, rows), malformed lines
(the service repairs rows whose free-text field carries an unquoted comma; the script counts them so
you can check `recovered_rows` later), per-day rows and amounts versus the previous batch, ids missing
from the CSV (must be 0), new ids per day (should be exactly the missing days), and status changes
(`Pending → Settled` is normal settlement). The script exits non-zero when an invariant breaks; do not
upload a CSV that fails it.

Because the daily export is YTD, **the next successful email re-covers every day of the year**. A
manual upload only buys the current day. If nobody needs today's silver today, the honest option is
to skip the upload, recreate the schedule (step 6) and let tomorrow's email heal the gap. Say so to
the operator and let them choose; the dry-run and the upload are the expensive part.

### 4. Dry-run through the real service into the internal scratch dataset

The service has two code paths (email and CSV) that do not produce identical rows. The dry-run shows
exactly what will land, without touching the partner project:

```bash
bash .claude/skills/ea-manual-backfill/scripts/upload_csv.sh "$WORK"/download/ContributionReport-*.csv \
  "$PARTNER" peppy-castle-368715 ex_elt_testing "canary_ea_${PARTNER}_manual"
bash .claude/skills/ea-manual-backfill/scripts/compare_scratch_to_bronze.sh \
  "peppy-castle-368715.ex_elt_testing.canary_ea_${PARTNER}_manual" "$BQ_PROJECT" "$BQ_DATASET" "$BQ_TABLE"
```

Expect: `rows == CSV rows`, `recovered_rows == malformed lines from step 3`, `skipped_rows == 0`,
schema equal to bronze except `fb_phone`, and the per-column diff pattern described in
[csv-vs-email-path.md](references/csv-vs-email-path.md) (`amount`, `form_id`, `time_created`,
`first_contribution_date` formats; `'nan'` strings for empties; name and phone hashes). A diff on
`contribution_id`, `date_received`, `vanid`, `email`, `utm_*` or `facebook_adid` is **not** expected
and means the CSV is not the same report.

Drop the canary when done: `bq rm -f -t peppy-castle-368715:ex_elt_testing.canary_ea_${PARTNER}_manual`.

### 5. Append to the partner bronze table — operator go required

Stop and show the operator: the gap (step 1), the validation summary (step 3), the dry-run result
(step 4), and the exact target `BQ_PROJECT.BQ_DATASET.BQ_TABLE`. The write goes to a partner's
production dataset; it needs an explicit yes.

```bash
bash .claude/skills/ea-manual-backfill/scripts/upload_csv.sh "$WORK"/download/ContributionReport-*.csv \
  "$PARTNER" "$BQ_PROJECT" "$BQ_DATASET" "$BQ_TABLE"
bash .claude/skills/ea-manual-backfill/scripts/verify_after_upload.sh "$BQ_PROJECT" "$BQ_DATASET" "$BQ_TABLE" <rows reported by the service>
```

`upload_csv.sh` always sends `"write_mode": "append"`. The service's default is `replace`, which
drops and recreates the table; the script exists so that nobody types that payload by hand.
`verify_after_upload.sh` checks the row delta, `null` ingestion timestamps (must be 0), and the per-day
rows of the new batch for the last three days.

### 6. Recreate the EA schedule — operator click required

Run the form filler without confirmation first. It opens the schedule page, fills recipients,
subject, Daily, start = tomorrow, end = December 31 of the current year, and prints every value it
reads back from the page, plus EA's own summary line ("Your report will be delivered daily, starting
on …"). Show that to the operator.

```bash
EA_SCHEDULE_URL="$EA_SCHEDULE_URL" EA_RECIPIENTS="$EA_RECIPIENTS" EA_SUBJECT="$EA_TEMPLATE_NAME" \
  EA_CONFIRM=0 browser-use < .claude/skills/ea-manual-backfill/scripts/ea_schedule.py
```

With the operator's yes, rerun with `EA_CONFIRM=1`: the script clicks "Schedule", then opens the
Scheduled Templates list and prints the row for the template. Expect
`Scheduled by <user> on <today> · Next Send Date: <tomorrow> · Daily`.

### 7. Hand off the dbt run and close

Do not run dbt from this skill. The repo-pinned way is the Airflow DAG: tell the operator to rerun
**only the dbt tasks** of `DAG_ID` (rerunning `extract_ea_contribution` would 404 again because the
email still does not exist). If they prefer a local run, the walkthrough's A3 command applies, with
a profile that targets `prod_silver` via OAuth.

After the dbt run, confirm silver:

```bash
bash .claude/skills/ea-manual-backfill/scripts/silver_status.sh "$BQ_PROJECT" prod_silver "$DBT_MODEL"
```

Close with a short written record: dates covered, rows appended, ingestion timestamp, schedule next
send date, and the link to the EA schedule history (how many `Failed` rows). That record is what the
next person needs when the schedule dies again.

## Known failure modes

| Symptom | Cause | What to do |
| --- | --- | --- |
| `browser-use` prints `permission-blocked` or `daemon didn't come up` | Chrome remote debugging not enabled, or the "Allow remote debugging?" popup was not clicked while the command waited | prerequisites.md, section Chrome |
| `SELECT_COMMITTEE_REQUIRED` | EA login landed on the committee picker | set `EA_COMMITTEE` (the script clicks it) or pick it in Chrome |
| `FILTERS:` shows a date range that is not the YTD | the saved template was edited | stop; the export would not match the daily email scope |
| Export stuck `In Progress` > 10 min | EA export queue | wait and rerun step 2; EA keeps the file in My Export Files until 11:59 PM ET |
| `validate_csv.py` reports ids missing from the CSV | wrong template or wrong committee | do not upload |
| Service answers `skipped_rows > 0` | rows the repair logic could not realign | reconcile those `Contribution ID`s by hand before relying on the batch |
| `No module named pandas` | the service venv is missing | prerequisites.md, section Python |
| EA form ids changed (`#targetEmails` etc. not found) | EA UI update | fix the selector in `scripts/ea_schedule.py`, update ea-ui-map.md in the same change |

## Scope boundaries

- Scenario B (full historical replacement into a staging table) is a different, more dangerous
  procedure: follow the walkthrough by hand.
- The recurring-commitment report (`<partner>_recurring`) uses another transformer and target; this
  skill's validation assumes the contribution report columns.
- The durable fix (stop depending on a hand-recreated EA email schedule) is tracked outside this
  skill; candidates are the EA API `changedEntityExportJobs` with `resourceType: Contributions`
  (90-day window, different columns) and a detection alert when no email arrived by 08:00 UTC.

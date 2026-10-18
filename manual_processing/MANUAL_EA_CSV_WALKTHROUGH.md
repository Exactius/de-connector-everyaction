# Manual EA CSV Upload - Walkthrough Guide

## How to use this

> **Agent-driven version:** the Claude Code skill in [`.claude/skills/ea-manual-backfill/`](../.claude/skills/ea-manual-backfill/SKILL.md)
> runs Scenario A end to end (EA export through your logged-in Chrome, CSV validation against the previous bronze batch,
> dry-run in the internal scratch dataset, append, post-upload checks, schedule recreation). This document stays the
> human reference for both scenarios.

This guide covers two scenarios for manually uploading EveryAction (EA) contribution data:

- **Scenario A: Failed email export** — The automated email export failed or was missed. You have a CSV export covering the missing date range and need to append it to the existing data.
- **Scenario B: Full historical data replacement** — Data was retroactively changed in EA. You have a full historical re-export and need to replace all existing data after validation.

## Prerequisites

- Python environment with dependencies installed
- Access to the BigQuery project (e.g., `ex-whitestork`)
- VPN access to EveryAction — some networks require it to load the EA site
- The CSV file downloaded from EveryAction

> **Note:** When `write_mode=append` is used, the service automatically adds an `ingestion_timestamp` column (UTC now) to every row. The dbt model uses this to dedupe overlapping `date_received` partitions, so the newly uploaded rows always take precedence.

## Common Steps (both scenarios)

### Step 1: Download the CSV from EveryAction

1. Log into the EveryAction website
2. Navigate to the Export/Reports
3. Export/Download the CSV file
   - Note the filename (e.g., `ContributionReport-5674596795.csv`)

### Step 2: Place the CSV file in the service

The service reads CSV files from the `test_data/` directory.

```bash
cp ~/Downloads/ContributionReport-XXXXXXX.csv test_data/
```

### Step 3: Run the EA Email service locally

```bash
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8080
```

```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080
```

---

## Scenario A: Failed Email Export

Use this when the automated pipeline failed and you just need to backfill the missing data. The new rows are appended directly to the production bronze table.

### A1: Upload the CSV (append to production table)

Open a new Terminal tab or window.

```bash
curl -X POST "http://localhost:8080/process" \
  -H "Content-Type: application/json" \
  -d '{
    "partner": "whitestork",
    "project_id": "ex-whitestork",
    "dataset": "bronze",
    "table_name": "every_action_contribution_report",
    "source_type": "csv",
    "csv_filename": "ContributionReport-XXXXXXX.csv",
    "write_mode": "append"
  }'
```

**Expected response:**

```json
{"status": "success", "message": "Successfully processed and uploaded N rows"}
```

> **Note:** The response also reports `recovered_rows`/`recovered_contribution_ids` (rows that had unquoted commas in a free-text field and were automatically repaired) and `skipped_rows`/`skipped_details` (rows that couldn't be safely parsed). If `skipped_rows` is greater than 0, reconcile those Contribution IDs manually — they were not uploaded.

You can now stop the local service (Ctrl+C).

### A2: Verify the upload in BigQuery

```sql
SELECT COUNT(1) AS row_count,
  COUNTIF(ingestion_timestamp IS NULL) AS null_ts,
  MIN(ingestion_timestamp) AS min_ts,
  MAX(ingestion_timestamp) AS max_ts,
  MIN(date_received) AS min_date,
  MAX(date_received) AS max_date
FROM `ex-whitestork.bronze.every_action_contribution_report`;
```

Confirm: `null_ts` is 0, `max_ts` is roughly "now" (your upload time), and the row count jumped by the number reported by the curl response.

### A3: Run the dbt model

The `every_action_contribution_report` dbt model uses `insert_overwrite` partitioned by `date_received`, and deduplicates by picking only rows with the latest `ingestion_timestamp` per date. This means the new data will automatically take precedence for any overlapping dates.

```bash
cd ../whitestork_DBT_V2
dbt run --select every_action_contribution_report --target prod
```

> **Note:** No model changes are needed — the data goes directly into the table the model already reads from.

### A4: Verify downstream

```sql
SELECT COUNT(1) as row_count, MIN(date_received) as min_date,
  MAX(date_received) as max_date
FROM `ex-whitestork.prod_silver.every_action_contribution_report`
```

### A5: Reschedule the report in EveryAction

> **Important:** Failed reports are **not** automatically retried the next day, you need to re-create the scheduled report.

1. In EveryAction, go to **Reporting → Report Manager → Saved Templates**.
2. Locate the template that drives the automated export. Usually this is `Exactius_Contribution_Report - whitestork`. If you're unsure which template to use, sort by **Last Run** date and pick the most recent one.
3. Open the template, then click **Report Actions → Schedule**.
4. Configure the schedule using the settings shown in [`New Scheduled Report config.png`](./New%20Scheduled%20Report%20config.png), adjust the secondary email as appropriate.
5. Click **Schedule** to save.

The next day's export should now run automatically.

---

## Scenario B: Full Historical Data Replacement

Use this when data was retroactively changed in EA and you need to replace all existing data. The data is uploaded to a separate staging table, validated with stakeholders, and then swapped into production.

### B1: Upload the CSV (to a staging table)

Open a new Terminal tab or window.

```bash
curl -X POST "http://localhost:8080/process" \
  -H "Content-Type: application/json" \
  -d '{
    "partner": "whitestork",
    "project_id": "ex-whitestork",
    "dataset": "bronze",
    "table_name": "ea_manual_upload",
    "source_type": "csv",
    "csv_filename": "ContributionReport-XXXXXXX.csv",
    "write_mode": "append"
  }'
```

**Expected response:**

```json
{"status": "success", "message": "Successfully processed and uploaded N rows"}
```

You can now stop the local service (Ctrl+C).

> **Multiple uploads:** If you need to upload multiple CSV files (e.g., split exports) to the same staging table, each batch will get its own `ingestion_timestamp` automatically, so dedup still works correctly.

### B2: Verify the upload in BigQuery

```sql
SELECT COUNT(1) as row_count, MIN(date_received) as min_date,
  MAX(date_received) as max_date
FROM `ex-whitestork.bronze.ea_manual_upload`
```

### B3: Point the dbt model to the staging table and validate

Create a branch in the dbt repo and update the model source:

In `models/sources.yml`, add under the `bronze` source:

```yaml
- name: ea_manual_upload
  description: Manually uploaded EveryAction contribution report for historical data validation
```

In `models/silver/blended/every_action_contribution_report.sql`, change:

```sql
FROM {{ source('bronze', 'every_action_contribution_report') }}
```

To:

```sql
FROM {{ source('bronze', 'ea_manual_upload') }}
```

Run the model with `--full-refresh` against dev to validate:

```bash
cd ../whitestork_DBT_V2
dbt run --select every_action_contribution_report --full-refresh --target dev
```

Rebuild any downstream models that depend on `every_action_contribution_report` (e.g., `blended_raw`) and validate with stakeholders.

### B4: Replace the production table

Once validated, replace the production bronze table:

```sql
CREATE OR REPLACE TABLE `ex-whitestork.bronze.every_action_contribution_report`
AS SELECT * FROM `ex-whitestork.bronze.ea_manual_upload`;
```

### B5: Revert the dbt model and run in prod

Revert the model changes so it reads from the production table again:

```bash
cd ../whitestork_DBT_V2
git checkout models/silver/blended/every_action_contribution_report.sql
git checkout models/sources.yml
```

Run the model with `--full-refresh` in prod:

```bash
dbt run --select every_action_contribution_report --full-refresh --target prod
```

### B6: Verify downstream

```sql
SELECT COUNT(1) as row_count, MIN(date_received) as min_date,
  MAX(date_received) as max_date
FROM `ex-whitestork.prod_silver.every_action_contribution_report`
```

---

## Quick Reference

### Scenario A (failed export backfill)

```bash
# 1. Copy CSV to service
cp ~/Downloads/ContributionReport-XXXXXXX.csv test_data/

# 2. Start service
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8080

# 3. Upload (new terminal) — append directly to production table
curl -X POST "http://localhost:8080/process" \
  -H "Content-Type: application/json" \
  -d '{
    "partner": "whitestork",
    "project_id": "ex-whitestork",
    "dataset": "bronze",
    "table_name": "every_action_contribution_report",
    "source_type": "csv",
    "csv_filename": "ContributionReport-XXXXXXX.csv",
    "write_mode": "append"
  }'

# 4. Run dbt model
cd ../whitestork_DBT_V2
dbt run --select every_action_contribution_report --target prod

# 5. Reschedule the report in EA (Reporting -> Report Manager -> Saved Templates
#    -> pick template by Last Run -> Report Actions -> Schedule -> configure per
#    manual_processing/New Scheduled Report config.png -> Schedule)
```

### Scenario B (full historical replacement)

```bash
# 1. Copy CSV to service
cp ~/Downloads/ContributionReport-XXXXXXX.csv test_data/

# 2. Start service
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8080

# 3. Upload (new terminal) — to staging table
curl -X POST "http://localhost:8080/process" \
  -H "Content-Type: application/json" \
  -d '{
    "partner": "whitestork",
    "project_id": "ex-whitestork",
    "dataset": "bronze",
    "table_name": "ea_manual_upload",
    "source_type": "csv",
    "csv_filename": "ContributionReport-XXXXXXX.csv",
    "write_mode": "append"
  }'

# 4. Update dbt model source to ea_manual_upload (in a branch)
# 5. Run dbt in dev with --full-refresh, validate with stakeholders
# 6. Replace production table, revert model, run --full-refresh in prod
```

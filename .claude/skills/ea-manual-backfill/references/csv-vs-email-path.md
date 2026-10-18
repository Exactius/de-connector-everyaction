# CSV path vs email path — what changes in bronze, and what the lineage tolerates

`POST /process` has two code paths in `src/core/process_every_action_data.py`: `source_type: email`
(the daily DAG) and `source_type: csv` (manual uploads). They share the column mapping but not the
transformation details. A manual upload therefore does not reproduce the email rows byte for byte.
Measured on 2026-10-18 (whitestork, 78 389 shared `contribution_id`s):

| Column(s) | CSV path | Email path | Downstream effect |
| --- | --- | --- | --- |
| empty values in `mailing_city`, `mailing_state`, `mailing_zip`, `mailing_country`, `channel`, `card_type`, `recurring_commitment_id`, `digital_utm_*` | literal string `nan` (pandas `astype(str)` on NaN) | `''` | `blended_raw` nulls `'nan'` on `utm_*`; `facebook_ftd`/`facebook_rd` guard `facebook_adid != 'nan'` but pass `mailing_*` through `COALESCE(x, '')`, so a CSV batch sends `city='nan'` until the next email batch |
| `first_name`, `last_name` | `Contact Name` split on `", "` (Last, First), then sha256 of `lower().strip()` | split on `" "`, sha256 of the raw token (so the hash of `Doe,` with the comma) | hashes differ for every row; `audiences/*` models export them, no join depends on them |
| `phone` | `''` when empty, else sha256 of `lower().strip()` | sha256 of the raw value, including sha256(`nan`) for empties | `audiences/*` override `phone` with `''`; no effect |
| `amount`, `remaining_amount`, `covered_costs_amount` | `67.3100` | `67.31` | `SAFE_CAST(... AS FLOAT64)` everywhere; no effect |
| `form_id` | `1636890` | `1636890.0` | not cast downstream; string comparison would differ |
| `time_created` | `2026-10-17 01:02:00` | `10/17/2026 1:02:00 AM` | not read by the silver model |
| `first_contribution_date` | `06/21/2025` | `6/21/2025 11:21:00 AM` | not read by the silver model |
| `date_received` | `10/17/2026` (converted with `strftime('%m/%d/%Y')`) | `10/17/2026` | identical; the silver model parses `%m/%d/%Y` |
| `fb_phone` | absent | present | bronze has the column; CSV rows leave it NULL; silver does not read it |
| `email_name_search_key` | `direct_upload_<ts>` | the Gmail query | lets you tell the paths apart in bronze |

Identical on both paths: `contribution_id`, `vanid`, `date_received`, `email` (hash), `utm_adid`,
`utm_campaign`, `utm_medium`, `utm_source`, `facebook_adid`, `online_reference_number`, `status`,
`form_name`, `source_code`, `designation`, `payment_method`.

## How the silver model absorbs a manual batch

`whitestork_DBT_V2/models/silver/blended/every_action_contribution_report.sql`:

- incremental, `insert_overwrite`, partitioned by `date_received` (DAY);
- keeps, per `contribution_id`, the row with the greatest `ingestion_timestamp`;
- filters `date_received != 'nan'` (a trace of earlier CSV uploads).

Consequences:

1. A manual CSV batch has the newest `ingestion_timestamp`, so after the dbt run **every 2026 row** in
   silver comes from the CSV path, not only the missing days.
2. The next email batch (YTD again) has a newer timestamp still, so the day after, every row is back
   on the email path. The divergence lasts one day when the schedule is recreated the same day.
3. The YTD scope is also why a manual upload is optional: if the schedule is recreated today, tomorrow's
   email fills the gap by itself.

Bronze history shows the CSV path was used on 6 days between 2026-06-01 and 2026-09-21 before this was
written down; nothing downstream broke, which is consistent with the table above.

## If you need the two paths to converge

Unify them in the service (one transformer for both inputs): fill NaN with `''` before `astype(str)`,
split `Contact Name` the same way, hash with the same normalisation, format `time_created` and
`first_contribution_date` identically. Any such change is a contract change for the Airflow caller
and for the silver model; follow the repo's change process and prove it with a dry-run in
`peppy-castle-368715.ex_elt_testing` plus `compare_scratch_to_bronze.sh` before merging.

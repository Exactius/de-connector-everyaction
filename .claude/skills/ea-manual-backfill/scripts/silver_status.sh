#!/usr/bin/env bash
# Rows per day in the silver model for the last 5 days, to confirm the dbt rerun picked up the backfill.
# Usage: silver_status.sh <bq_project> <silver_dataset> <model_table>
set -euo pipefail

PROJECT="${1:?bq project}"; DATASET="${2:?silver dataset}"; TABLE="${3:?model table}"
FQ="\`${PROJECT}.${DATASET}.${TABLE}\`"

bq query --use_legacy_sql=false --format=pretty --project_id="${PROJECT}" "
SELECT (SELECT COUNT(1) FROM ${FQ}) AS row_count, (SELECT MIN(date_received) FROM ${FQ}) AS min_date, (SELECT MAX(date_received) FROM ${FQ}) AS max_date"

bq query --use_legacy_sql=false --format=pretty --project_id="${PROJECT}" "
SELECT date_received, COUNT(1) AS rows_silver, ROUND(SUM(SAFE_CAST(amount AS FLOAT64)), 2) AS amount
FROM ${FQ}
WHERE date_received >= DATE_SUB(CURRENT_DATE(), INTERVAL 5 DAY)
GROUP BY 1 ORDER BY 1"

#!/usr/bin/env bash
# Post-upload checks on the bronze table: null timestamps, newest batch size and its last three days.
# Usage: verify_after_upload.sh <bq_project> <dataset> <table> [expected_rows_in_new_batch]
set -euo pipefail

PROJECT="${1:?bq project}"; DATASET="${2:?dataset}"; TABLE="${3:?table}"; EXPECTED="${4:-}"
FQ="\`${PROJECT}.${DATASET}.${TABLE}\`"

bq query --use_legacy_sql=false --format=pretty --project_id="${PROJECT}" "
WITH latest AS (SELECT MAX(ingestion_timestamp) AS ts FROM ${FQ})
SELECT (SELECT COUNT(1) FROM ${FQ}) AS row_count,
  (SELECT COUNTIF(ingestion_timestamp IS NULL) FROM ${FQ}) AS null_ingestion_ts,
  (SELECT ts FROM latest) AS newest_batch_utc,
  (SELECT COUNT(1) FROM ${FQ} WHERE ingestion_timestamp = (SELECT ts FROM latest)) AS newest_batch_rows,
  (SELECT ANY_VALUE(email_name_search_key) FROM ${FQ} WHERE ingestion_timestamp = (SELECT ts FROM latest)) AS newest_batch_key"

echo "== newest batch, last 3 date_received days =="
bq query --use_legacy_sql=false --format=pretty --project_id="${PROJECT}" "
SELECT date_received, COUNT(1) AS rows_in_batch, ROUND(SUM(SAFE_CAST(amount AS FLOAT64)), 2) AS amount
FROM ${FQ}
WHERE ingestion_timestamp = (SELECT MAX(ingestion_timestamp) FROM ${FQ})
  AND SAFE.PARSE_DATE('%m/%d/%Y', date_received) >= DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
GROUP BY 1 ORDER BY SAFE.PARSE_DATE('%m/%d/%Y', date_received)"

if [ -n "${EXPECTED}" ]; then
  ACTUAL=$(bq query --use_legacy_sql=false --format=csv --project_id="${PROJECT}" "
    SELECT COUNT(1) FROM ${FQ} WHERE ingestion_timestamp = (SELECT MAX(ingestion_timestamp) FROM ${FQ})" | tail -1)
  if [ "${ACTUAL}" = "${EXPECTED}" ]; then echo "newest batch rows = ${EXPECTED} (matches the service response)"; else echo "MISMATCH: newest batch has ${ACTUAL} rows, service reported ${EXPECTED}"; exit 1; fi
fi

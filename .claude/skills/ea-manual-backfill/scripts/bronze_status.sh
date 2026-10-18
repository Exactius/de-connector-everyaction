#!/usr/bin/env bash
# Coverage of an EveryAction bronze table: last ingestion, rows per date_received, rows per ingestion day.
# Usage: bronze_status.sh <bq_project> <dataset> <table> [days=14]
set -euo pipefail

PROJECT="${1:?bq project}"; DATASET="${2:?dataset}"; TABLE="${3:?table}"; DAYS="${4:-14}"
FQ="\`${PROJECT}.${DATASET}.${TABLE}\`"

echo "== ${PROJECT}.${DATASET}.${TABLE} =="
bq query --use_legacy_sql=false --format=pretty --project_id="${PROJECT}" "
SELECT COUNT(1) AS row_count,
  MIN(SAFE.PARSE_DATE('%m/%d/%Y', date_received)) AS min_date_received,
  MAX(SAFE.PARSE_DATE('%m/%d/%Y', date_received)) AS max_date_received,
  MAX(ingestion_timestamp) AS last_ingestion_utc,
  COUNTIF(ingestion_timestamp IS NULL) AS null_ingestion_ts
FROM ${FQ}"

echo "== rows per date_received, last ${DAYS} days (all batches) =="
bq query --use_legacy_sql=false --format=pretty --project_id="${PROJECT}" "
SELECT SAFE.PARSE_DATE('%m/%d/%Y', date_received) AS date_received, COUNT(1) AS rows_all_batches,
  MAX(ingestion_timestamp) AS last_ingested
FROM ${FQ}
WHERE SAFE.PARSE_DATE('%m/%d/%Y', date_received) >= DATE_SUB(CURRENT_DATE(), INTERVAL ${DAYS} DAY)
GROUP BY 1 ORDER BY 1"

echo "== batches per ingestion day, last ${DAYS} days (one YTD batch per day expected) =="
bq query --use_legacy_sql=false --format=pretty --project_id="${PROJECT}" "
SELECT DATE(ingestion_timestamp) AS ingest_day, COUNT(1) AS rows_ingested,
  MAX(SAFE.PARSE_DATE('%m/%d/%Y', date_received)) AS max_date_received,
  CASE WHEN LOGICAL_OR(email_name_search_key LIKE 'direct_upload_%' OR email_name_search_key LIKE 'csv_upload_%') THEN 'csv_path' ELSE 'email_path' END AS path
FROM ${FQ}
WHERE ingestion_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL ${DAYS} DAY)
GROUP BY 1 ORDER BY 1"

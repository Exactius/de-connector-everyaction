#!/usr/bin/env bash
# Export the latest bronze batch (contribution_id, date, amount, status) to a CSV for validate_csv.py.
# Usage: export_batch_keys.sh <bq_project> <dataset> <table> <out.csv>
set -euo pipefail

PROJECT="${1:?bq project}"; DATASET="${2:?dataset}"; TABLE="${3:?table}"; OUT="${4:?output csv}"
FQ="\`${PROJECT}.${DATASET}.${TABLE}\`"

bq query --use_legacy_sql=false --format=csv --max_rows=5000000 --project_id="${PROJECT}" "
SELECT contribution_id, SAFE.PARSE_DATE('%m/%d/%Y', date_received) AS d,
  SAFE_CAST(amount AS FLOAT64) AS amount, status, ingestion_timestamp
FROM ${FQ}
WHERE ingestion_timestamp = (SELECT MAX(ingestion_timestamp) FROM ${FQ})" > "${OUT}"

ROWS=$(( $(wc -l < "${OUT}") - 1 ))
TS=$(tail -1 "${OUT}" | awk -F, '{print $5}')
echo "previous batch: ${ROWS} rows, ingestion ${TS} -> ${OUT}"

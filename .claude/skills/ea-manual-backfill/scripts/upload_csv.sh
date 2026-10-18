#!/usr/bin/env bash
# Push a CSV through the local service with write_mode=append (never replace).
# Usage: upload_csv.sh <csv_path> <partner> <bq_project> <dataset> <table> [port=8080]
# Starts the service from the repo venv if nothing listens on the port, and stops it afterwards.
set -euo pipefail

CSV_PATH="${1:?csv path}"; PARTNER="${2:?partner}"; PROJECT="${3:?bq project}"
DATASET="${4:?dataset}"; TABLE="${5:?table}"; PORT="${6:-8080}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "${REPO_ROOT}"
[ -x .venv/bin/python ] || { echo "missing ${REPO_ROOT}/.venv — see references/prerequisites.md"; exit 2; }

CSV_NAME="$(basename "${CSV_PATH}")"
mkdir -p test_data
cp -f "${CSV_PATH}" "test_data/${CSV_NAME}"

STARTED=0
if ! lsof -ti:"${PORT}" >/dev/null 2>&1; then
  LOG="$(mktemp -t ea-service-XXXX.log)"
  .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port "${PORT}" > "${LOG}" 2>&1 &
  SERVICE_PID=$!
  STARTED=1
  for _ in $(seq 1 30); do
    curl -s -o /dev/null "http://127.0.0.1:${PORT}/docs" && break
    sleep 1
  done
  curl -s -o /dev/null "http://127.0.0.1:${PORT}/docs" || { echo "service did not start, log: ${LOG}"; kill "${SERVICE_PID}" 2>/dev/null; exit 3; }
  echo "service started (pid ${SERVICE_PID}, log ${LOG})"
fi

echo "POST /process -> ${PROJECT}.${DATASET}.${TABLE} (partner=${PARTNER}, csv=${CSV_NAME}, write_mode=append)"
PAYLOAD=$(printf '{"partner":"%s","project_id":"%s","dataset":"%s","table_name":"%s","source_type":"csv","csv_filename":"%s","write_mode":"append"}' \
  "${PARTNER}" "${PROJECT}" "${DATASET}" "${TABLE}" "${CSV_NAME}")
RESPONSE=$(curl -s -X POST "http://127.0.0.1:${PORT}/process" -H "Content-Type: application/json" -d "${PAYLOAD}")
echo "${RESPONSE}" | python3 -c '
import json, sys
try:
    body = json.load(sys.stdin)
except json.JSONDecodeError:
    print("non-JSON response:", sys.stdin.read()[:500]); sys.exit(4)
recovered = body.pop("recovered_contribution_ids", [])
print(json.dumps(body, indent=2))
print("recovered ids:", len(recovered))
if body.get("status") != "success":
    sys.exit(5)
if body.get("skipped_rows", 0):
    print("WARNING: skipped_rows > 0 — reconcile skipped_details by hand")
'
STATUS=$?

if [ "${STARTED}" = "1" ]; then
  kill "${SERVICE_PID}" 2>/dev/null || true
  echo "service stopped"
fi
exit "${STATUS}"

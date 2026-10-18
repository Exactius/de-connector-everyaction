#!/usr/bin/env bash
# Compare a dry-run table (scratch) with the latest bronze batch: schema, then per-column diffs on shared ids.
# Usage: compare_scratch_to_bronze.sh <scratch_project.dataset.table> <bq_project> <dataset> <table>
set -euo pipefail

SCRATCH="${1:?scratch table project.dataset.table}"; PROJECT="${2:?bq project}"; DATASET="${3:?dataset}"; TABLE="${4:?table}"
BRONZE="${PROJECT}.${DATASET}.${TABLE}"
SCRATCH_PROJECT="${SCRATCH%%.*}"

echo "== schema: ${SCRATCH} vs ${BRONZE} =="
python3 - "${SCRATCH}" "${BRONZE}" <<'PY'
import json, subprocess, sys
def schema(table):
    out = subprocess.run(["bq", "show", "--format=json", table.replace(".", ":", 1)], capture_output=True, text=True, check=True).stdout
    return {f["name"]: f["type"] for f in json.loads(out)["schema"]["fields"]}
scratch, bronze = schema(sys.argv[1]), schema(sys.argv[2])
print("only in scratch:", sorted(set(scratch) - set(bronze)) or "none")
print("only in bronze:", sorted(set(bronze) - set(scratch)) or "none (fb_phone expected here)")
print("type differences:", {k: (scratch[k], bronze[k]) for k in set(scratch) & set(bronze) if scratch[k] != bronze[k]} or "none")
PY

echo "== per-column diff on shared contribution_id (scratch vs latest bronze batch) =="
python3 - "${SCRATCH}" "${BRONZE}" "${SCRATCH_PROJECT}" <<'PY'
import json, subprocess, sys
scratch, bronze, project = sys.argv[1:4]
columns = ("vanid date_received amount source_code designation payment_method remaining_amount financial_batch card_type "
           "covered_costs covered_costs_amount first_contribution_date form_id form_name is_recurring_commitment "
           "recurring_commitment_id mailing_city mailing_country mailing_state online_reference_number status "
           "total_number_of_contributions email phone first_name last_name utm_adid utm_campaign utm_medium utm_source "
           "digital_utm_campaign digital_utm_medium digital_utm_source facebook_adid mailing_zip time_created channel").split()
selects = ", ".join(f"COUNTIF(IFNULL(CAST(s.{c} AS STRING),'<null>') != IFNULL(CAST(b.{c} AS STRING),'<null>')) AS {c}" for c in columns)
query = f"""WITH b AS (SELECT * FROM `{bronze}` WHERE ingestion_timestamp = (SELECT MAX(ingestion_timestamp) FROM `{bronze}`)),
s AS (SELECT * FROM `{scratch}`)
SELECT COUNT(1) AS shared_ids, (SELECT COUNT(1) FROM s) AS scratch_rows, {selects} FROM s JOIN b USING (contribution_id)"""
out = subprocess.run(["bq", "query", "--use_legacy_sql=false", "--format=json", f"--project_id={project}", query], capture_output=True, text=True)
if out.returncode:
    print(out.stderr[:1000]); sys.exit(1)
row = json.loads(out.stdout)[0]
print(f"scratch rows: {row['scratch_rows']} | shared ids with bronze batch: {row['shared_ids']}")
diffs = {k: int(v) for k, v in row.items() if k not in ("shared_ids", "scratch_rows") and int(v)}
identical = [c for c in columns if c not in diffs]
print("identical columns:", ", ".join(identical) or "none")
print("columns with differences (count of shared rows):")
for col, count in sorted(diffs.items(), key=lambda kv: -kv[1]):
    print(f"  {col:34s} {count}")
unexpected = [c for c in ("date_received", "vanid", "email", "utm_campaign", "utm_source", "utm_medium", "utm_adid", "facebook_adid", "online_reference_number") if c in diffs]
print("UNEXPECTED differences:", unexpected or "none (format-only differences are documented in references/csv-vs-email-path.md)")
sys.exit(1 if unexpected else 0)
PY

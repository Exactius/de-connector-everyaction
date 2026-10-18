"""Validate an EveryAction contribution CSV export against the previous bronze batch before uploading it."""

import argparse
import sys

import pandas as pd

ID_COLUMN = "Contribution ID"
DATE_COLUMN = "Date Received"
AMOUNT_COLUMN = "Amount"
STATUS_COLUMN = "Status"
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y")
RECENT_DAYS = 12


def detect_encoding(path: str) -> tuple[str, int]:
    """Return the encoding and the number of header lines to skip (the EA export starts with SEP=,)."""
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            with open(path, "r", encoding=encoding) as handle:
                first_line = handle.readline().strip()
            skip_rows = 1 if first_line.startswith("SEP=") else 0
            return encoding, skip_rows
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"cannot decode {path} as utf-8 or utf-16")


def read_export(path: str) -> tuple[pd.DataFrame, list[list[str]]]:
    """Read the export as strings, collecting the lines pandas cannot align (the service repairs those)."""
    encoding, skip_rows = detect_encoding(path)
    bad_lines: list[list[str]] = []
    frame = pd.read_csv(
        path,
        encoding=encoding,
        skiprows=skip_rows,
        dtype=str,
        engine="python",
        quoting=1,
        on_bad_lines=lambda line: bad_lines.append(line),
    )
    frame.columns = frame.columns.str.strip()
    print(f"encoding: {encoding} | header lines skipped: {skip_rows} | columns: {len(frame.columns)}")
    return frame, bad_lines


def parse_dates(raw: pd.Series) -> pd.Series:
    """Parse the date column with the first format that fits every value."""
    for date_format in DATE_FORMATS:
        parsed = pd.to_datetime(raw, format=date_format, errors="coerce")
        if parsed.notna().all():
            print(f"date format: {date_format}")
            return parsed
    parsed = pd.to_datetime(raw, errors="coerce")
    print(f"date format: mixed, unparsed values: {int(parsed.isna().sum())}")
    return parsed


def build_keys(frame: pd.DataFrame) -> pd.DataFrame:
    """Reduce the export to the comparison keys."""
    dates = parse_dates(raw=frame[DATE_COLUMN])
    keys = pd.DataFrame(
        {
            "contribution_id": frame[ID_COLUMN].astype(str).str.strip(),
            "d": dates.dt.strftime("%Y-%m-%d"),
            "amount": pd.to_numeric(frame[AMOUNT_COLUMN], errors="coerce"),
            "status": frame[STATUS_COLUMN],
        }
    )
    return keys


def report_scope(keys: pd.DataFrame, bad_lines: list[list[str]]) -> list[str]:
    """Print the scope of the export and return the invariant violations found."""
    problems: list[str] = []
    print(f"\nrows parsed: {len(keys)} | malformed lines (service repairs these): {len(bad_lines)} | total: {len(keys) + len(bad_lines)}")
    print(f"date_received min/max: {keys['d'].min()} / {keys['d'].max()}")
    print(f"status: {keys['status'].value_counts().to_dict()}")
    unparsed = int(keys["d"].isna().sum())
    empty_ids = int((keys["contribution_id"] == "") .sum() + keys["contribution_id"].isna().sum())
    duplicates = int(keys["contribution_id"].duplicated().sum())
    empty_amounts = int(keys["amount"].isna().sum())
    print(f"unparsed dates: {unparsed} | empty ids: {empty_ids} | duplicate ids: {duplicates} | empty amounts: {empty_amounts}")
    if unparsed:
        problems.append(f"{unparsed} rows with an unparsable {DATE_COLUMN}")
    if empty_ids:
        problems.append(f"{empty_ids} rows without {ID_COLUMN}")
    if duplicates:
        problems.append(f"{duplicates} duplicate {ID_COLUMN}")
    if bad_lines:
        sample = [(line[0], line[3], line[4]) for line in bad_lines[:10]]
        print(f"malformed lines (id, date, amount), first 10: {sample}")
    return problems


def compare_with_previous(keys: pd.DataFrame, previous: pd.DataFrame, bad_ids: set[str]) -> list[str]:
    """Compare per-day volumes, id sets and status changes with the previous bronze batch."""
    problems: list[str] = []
    previous = previous.copy()
    previous["contribution_id"] = previous["contribution_id"].astype(str).str.strip()
    print(f"\nprevious batch: {len(previous)} rows | date min/max: {previous['d'].min()} / {previous['d'].max()} | ingestion: {previous['ingestion_timestamp'].iloc[0] if len(previous) else 'n/a'}")

    csv_days = keys.groupby("d").agg(rows_csv=("contribution_id", "count"), amount_csv=("amount", "sum"))
    bq_days = previous.groupby("d").agg(rows_bq=("contribution_id", "count"), amount_bq=("amount", "sum"))
    per_day = csv_days.join(bq_days, how="outer").fillna(0)
    per_day["rows_diff"] = per_day["rows_csv"] - per_day["rows_bq"]
    per_day["amount_diff"] = (per_day["amount_csv"] - per_day["amount_bq"]).round(2)
    print(f"\nper day, last {RECENT_DAYS} days (CSV vs previous batch):")
    print(per_day.tail(RECENT_DAYS).round(2).to_string())

    ids_csv = set(keys["contribution_id"]) | bad_ids
    ids_bq = set(previous["contribution_id"])
    missing = ids_bq - ids_csv
    new_ids = ids_csv - ids_bq
    print(f"\nids in previous batch missing from CSV: {len(missing)} | new ids in CSV: {len(new_ids)}")
    if missing:
        sample = previous[previous["contribution_id"].isin(missing)].groupby(["d", "status"]).size().to_dict()
        print(f"missing ids by day/status: {sample}")
        problems.append(f"{len(missing)} contribution ids of the previous batch are absent from the CSV (wrong template, committee or filters?)")
    new_by_day = keys[keys["contribution_id"].isin(new_ids)].groupby("d").size().to_dict()
    print(f"new ids by day: {new_by_day}")

    merged = keys.merge(previous, on="contribution_id", suffixes=("_csv", "_bq"))
    changed = merged[(merged["amount_csv"].round(2) != merged["amount_bq"].round(2)) | (merged["status_csv"] != merged["status_bq"])]
    print(f"shared ids: {len(merged)} | amount or status changed: {len(changed)}")
    if len(changed):
        print(f"status transitions: {changed.groupby(['status_bq', 'status_csv']).size().to_dict()}")
        amount_changed = int((merged["amount_csv"].round(2) != merged["amount_bq"].round(2)).sum())
        print(f"amount changed on shared ids: {amount_changed}")
    return problems


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="EA export CSV (utf-16 or utf-8, SEP= line tolerated)")
    parser.add_argument("--previous", help="CSV from export_batch_keys.sh (contribution_id,d,amount,status,ingestion_timestamp)")
    args = parser.parse_args()

    frame, bad_lines = read_export(path=args.csv)
    keys = build_keys(frame=frame)
    problems = report_scope(keys=keys, bad_lines=bad_lines)
    if args.previous:
        previous = pd.read_csv(args.previous, dtype={"contribution_id": str})
        bad_ids = {line[0] for line in bad_lines if line}
        problems.extend(compare_with_previous(keys=keys, previous=previous, bad_ids=bad_ids))

    print("\nRESULT:", "OK" if not problems else "FAIL")
    for problem in problems:
        print(f" - {problem}")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()

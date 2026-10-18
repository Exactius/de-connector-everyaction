# List the EA "Scheduled Templates" rows for a template (diagnosis before, proof after).
# Run:  EA_TEMPLATE_NAME="Exactius_Contribution_Report - whitestork" [EA_COMMITTEE="Operation White Stork"] \
#         browser-use < .claude/skills/ea-manual-backfill/scripts/ea_scheduled_status.py
import os

SKILL_SCRIPTS = os.path.join(os.getcwd(), ".claude", "skills", "ea-manual-backfill", "scripts")
exec(open(os.path.join(SKILL_SCRIPTS, "ea_common.py")).read())

TEMPLATE_NAME = os.environ["EA_TEMPLATE_NAME"]
COMMITTEE = os.environ.get("EA_COMMITTEE")

goto_url("https://app.everyaction.com/ReportManager.aspx")
settle()
ensure_ea_session(committee=COMMITTEE)
if "ReportManager" not in current_url():
    goto_url("https://app.everyaction.com/ReportManager.aspx")
    settle()
click_report_manager_tab(text="Scheduled Templates")
settle(seconds=5)
if "scheduledReports" not in current_url():
    print(f"could not open the Scheduled Templates tab (url {current_url()}); see references/ea-ui-map.md")
    raise SystemExit(4)
rows = table_rows(filter_text=TEMPLATE_NAME)
print(f"scheduled templates matching {TEMPLATE_NAME!r}: {len(rows)}")
for row in rows:
    print("  " + row)
failed = sum("Failed" in row for row in rows)
live = [row for row in rows if "Next Send Date" in row]
print(f"failed: {failed} | with a next send date: {len(live)}")
for row in live:
    print("LIVE: " + row)

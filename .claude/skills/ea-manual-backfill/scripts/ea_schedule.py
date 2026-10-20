# Fill (and, with EA_CONFIRM=1, submit) the "New Scheduled Report" form of a saved template.
# Run:  EA_SCHEDULE_URL="https://app.everyaction.com/ReportScheduleDetails.aspx?TemplateId=96417" \
#       EA_RECIPIENTS="data.analysis@exacti.us, ian.s@exacti.us" EA_SUBJECT="Exactius_Contribution_Report - whitestork" \
#       [EA_START=MM/DD/YYYY] [EA_END=MM/DD/YYYY] [EA_COMMITTEE=...] EA_CONFIRM=0|1 \
#         browser-use < .claude/skills/ea-manual-backfill/scripts/ea_schedule.py
import datetime
import os
import time

SKILL_SCRIPTS = os.path.join(os.getcwd(), ".claude", "skills", "ea-manual-backfill", "scripts")
exec(open(os.path.join(SKILL_SCRIPTS, "ea_common.py")).read())

SCHEDULE_URL = os.environ["EA_SCHEDULE_URL"]
RECIPIENTS = os.environ["EA_RECIPIENTS"]
SUBJECT = os.environ["EA_SUBJECT"]
COMMITTEE = os.environ.get("EA_COMMITTEE")
CONFIRM = os.environ.get("EA_CONFIRM", "0") == "1"
TODAY = datetime.date.today()
START = os.environ.get("EA_START") or (TODAY + datetime.timedelta(days=1)).strftime("%m/%d/%Y")
END = os.environ.get("EA_END") or TODAY.replace(month=12, day=31).strftime("%m/%d/%Y")
FIELDS = ("#targetEmails", "#scheduleName", "#scheduleDescription", "#StartDate", "#EndDate")

goto_url(SCHEDULE_URL)
settle(seconds=5)
ensure_ea_session(committee=COMMITTEE)
if "ReportScheduleDetails" not in current_url():
    goto_url(SCHEDULE_URL)
    settle(seconds=5)
if center_of(selector="#scheduleButton") is None:
    print("schedule form not found; see references/ea-ui-map.md (New Scheduled Report form)")
    raise SystemExit(4)

type_into(selector="#targetEmails", text=RECIPIENTS)
type_into(selector="#scheduleName", text=SUBJECT)
js(
    "(() => { const s = document.querySelector('#RecurrenceType'); const m = s.getAttribute('ng-model');"
    " const sc = window.angular && angular.element(s).scope();"
    " if (sc && m) { sc.$apply(function(){ sc.$eval(m + \" = 'Daily'\"); }); return 'angular:' + sc.$eval(m); }"
    " const o = Array.from(s.options).find(o => /daily/i.test(o.text)); s.value = o.value;"
    " s.dispatchEvent(new Event('change', {bubbles: true})); return 'dom:' + s.value; })()"
)
time.sleep(0.5)
type_into(selector="#StartDate", text=START)
type_into(selector="#EndDate", text=END)
js("document.body.click()")
time.sleep(1)

frequency = js("document.querySelector('#RecurrenceType').selectedOptions[0].text")
contact_records = js("(document.body.innerText.match(/Contact Records[^\\n]*\\n([^\\n]*)/) || ['', '?'])[1]")
ea_summary = js("(document.body.innerText.match(/Your report will be delivered[^\\n]*/) || ['none'])[0]")
print("FORM VALUES (read back from the page):")
for field in FIELDS:
    print(f"  {field:22s} = {input_value(selector=field)!r}")
print(f"  {'#RecurrenceType':22s} = {frequency!r}")
print(f"  {'contact records':22s} = {contact_records!r}")
print(f"  {'EA summary':22s} = {ea_summary!r}")

if "daily" not in frequency.lower() or "delivered daily" not in ea_summary.lower():
    print(f"FREQUENCY NOT DAILY: select={frequency!r} summary={ea_summary!r} (Angular model did not commit to Daily)")
    raise SystemExit(5)

checks = {
    "#targetEmails": RECIPIENTS,
    "#scheduleName": SUBJECT,
    "#StartDate": START,
    "#EndDate": END,
}
mismatch = {field: (input_value(selector=field), expected) for field, expected in checks.items() if input_value(selector=field) != expected}
if mismatch:
    print(f"MISMATCH between intended and page values: {mismatch}")
    raise SystemExit(5)

if not CONFIRM:
    print("NOT SUBMITTED (EA_CONFIRM=0). Show the values to the operator; rerun with EA_CONFIRM=1 to click Schedule.")
    raise SystemExit(0)

click_selector(selector="#scheduleButton")
settle(seconds=5)
print(f"after submit: {current_url()}")
goto_url("https://app.everyaction.com/ReportManager.aspx")
settle()
click_report_manager_tab(text="Scheduled Templates")
settle(seconds=5)
rows = [row for row in table_rows(filter_text=SUBJECT) if "Next Send Date" in row]
if rows:
    print("SCHEDULED: " + rows[0][:220])
else:
    print("no live schedule row found for the subject; check Scheduled Templates in EA by hand")
    raise SystemExit(6)

# Export a saved EA report template as CSV and download the zip.
# Run:  EA_TEMPLATE_URL="https://app.everyaction.com/ReportViewer.aspx?ReportId=...&TemplateId=..." \
#       EA_DOWNLOAD_DIR=/tmp/ea-backfill/download [EA_COMMITTEE="Operation White Stork"] [EA_EXPORT_TIMEOUT_MIN=10] \
#         browser-use < .claude/skills/ea-manual-backfill/scripts/ea_export.py
import glob
import os
import re
import time

SKILL_SCRIPTS = os.path.join(os.getcwd(), ".claude", "skills", "ea-manual-backfill", "scripts")
exec(open(os.path.join(SKILL_SCRIPTS, "ea_common.py")).read())

TEMPLATE_URL = os.environ["EA_TEMPLATE_URL"]
DOWNLOAD_DIR = os.path.abspath(os.environ["EA_DOWNLOAD_DIR"])
COMMITTEE = os.environ.get("EA_COMMITTEE")
TIMEOUT_MINUTES = int(os.environ.get("EA_EXPORT_TIMEOUT_MIN", "10"))
EXPORT_LIST_URL = "https://app.everyaction.com/ExportList.aspx"
DOWNLOAD_URL = "https://app.everyaction.com/ExportFileDownloadHandler.ashx?exportFileId={export_id}"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def export_ids_on_list() -> set[str]:
    """exportFileIds currently listed in My Export Files."""
    hrefs = js("Array.from(document.querySelectorAll('table a')).map(a => a.href)")
    ids = {match.group(1) for href in hrefs for match in [re.search(r"ExportFileID=(\d+)", href, re.I)] if match}
    return ids


goto_url(EXPORT_LIST_URL)
settle()
ensure_ea_session(committee=COMMITTEE)
if "ExportList" not in current_url():
    goto_url(EXPORT_LIST_URL)
    settle()
known_ids = export_ids_on_list()
print(f"exports already listed: {len(known_ids)}")

goto_url(TEMPLATE_URL)
settle(seconds=6)
text = body_text()
title = page_info()["title"]
filters = re.search(r"Applied Filters.*?\n(.*?)\n", text)
summary = re.search(r"Number/Count\n(.*?)\n", text)
print(f"TEMPLATE: {title}")
print(f"FILTERS: {filters.group(1) if filters else 'not found'}")
print(f"COUNT: {summary.group(1) if summary else 'not found'}")

opened = js("(() => { const b = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Export As')); if (!b) return false; b.click(); return true; })()")
if not opened:
    print("Export As button not found; see references/ea-ui-map.md (Report Viewer)")
    raise SystemExit(4)
time.sleep(1.5)
js("document.querySelector('#export-report-action-csv').click()")
time.sleep(4)
modal = js(
    "Array.from(document.querySelectorAll('[role=dialog], .modal')).filter(e => e.offsetParent !== null)"
    ".map(e => e.innerText.replace(/\\s+/g, ' ').slice(0, 200)).join(' || ')"
)
print(f"EXPORT_MODAL: {modal[:160] if modal else 'none'}")
if "Export in Progress" not in modal:
    print("export did not start; see references/ea-ui-map.md (Report Viewer)")
    raise SystemExit(4)
js("Array.from(document.querySelectorAll('button, a')).filter(e => e.textContent.trim() === 'Close' && e.offsetParent !== null).forEach(e => e.click())")

deadline = time.time() + TIMEOUT_MINUTES * 60
new_id = None
while time.time() < deadline:
    goto_url(EXPORT_LIST_URL)
    settle(seconds=3)
    candidates = export_ids_on_list() - known_ids
    download_hrefs = js("Array.from(document.querySelectorAll('table a')).filter(a => a.textContent.trim() === 'Download File').map(a => a.href).join(' ')")
    new_id = next((candidate for candidate in candidates if candidate in download_hrefs), None)
    if new_id:
        break
    rows = table_rows(filter_text="In Progress")
    status = rows[0] if rows else None
    print(f"waiting: {status[:120] if status else 'no export row yet'}")
    time.sleep(30)

if not new_id:
    print(f"export not ready after {TIMEOUT_MINUTES} min; rerun later, EA keeps the file until 11:59 PM ET")
    raise SystemExit(5)
row = next((row for row in table_rows() if new_id in row or "Download File" in row), "")
print(f"READY: {row[:200]}")

cdp("Browser.setDownloadBehavior", behavior="allow", downloadPath=DOWNLOAD_DIR, eventsEnabled=True)
before = set(glob.glob(os.path.join(DOWNLOAD_DIR, "*.zip")))
js("window.location.href = " + repr(DOWNLOAD_URL.format(export_id=new_id)))
for _ in range(60):
    time.sleep(2)
    zips = set(glob.glob(os.path.join(DOWNLOAD_DIR, "*.zip"))) - before
    partial = glob.glob(os.path.join(DOWNLOAD_DIR, "*.crdownload"))
    if zips and not partial:
        path = zips.pop()
        print(f"DOWNLOADED: {path} ({os.path.getsize(path)} bytes)")
        break
else:
    print(f"download did not complete in {DOWNLOAD_DIR}; open {DOWNLOAD_URL.format(export_id=new_id)} in Chrome by hand")
    raise SystemExit(6)

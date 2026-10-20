# EveryAction UI map (as observed 2026-10-18)

Everything the browser scripts rely on. When a script breaks, compare the page against this map and
update both in the same change.

## Session and committee

| Page | URL | Notes |
| --- | --- | --- |
| Login (Bonterra universal login, Auth0) | `https://auth.bonterra.network/u/login/identifier?state=…` then `…/u/login/password?state=…` | two steps: `input[name=username]` (email) + `button[name=action]` ("Next"), then `input[name=password]` + `button[name=action]`. Submit with a DOM `.click()` on the button (coordinate clicks are dropped on a hidden tab). `scripts/ea_login.py` does this with the Secret Manager JSON; without it, scripts stop with `LOGIN_REQUIRED` and a human logs in |
| Logout | `https://app.everyaction.com/Login.aspx?mode=logout&newURL=1` | user menu → `#user-dropdown-option-log-out` |
| Select User (committee) | `https://app.everyaction.com/SelectCommittee.aspx` | one link per committee, e.g. `OperationWhiteStork-ram (Operation White Stork)`, `href="javascript:void(0)"`; click the link, then `input[type=submit][value=Next]` (`#ctl01_ContentPlaceHolderVANPage_ButtonContinue`, a submit input, not a button) |
| Home | `https://app.everyaction.com/MyHomepage.aspx?HasCommittee=1#/` | reached after committee selection |

EA keeps the session for hours; the committee selection is per browser session.

## Report Manager

| Page | URL | Notes |
| --- | --- | --- |
| Report Manager | `https://app.everyaction.com/ReportManager.aspx` | Angular app; the left tabs are `li`/`div` elements, not links |
| Saved Templates | `…/ReportManager.aspx#/mySavedTemplates` | table `Report Name | Last Run | Type`; each row has the template link + `Edit` + `Delete Report Template` buttons |
| Scheduled Templates | reached by clicking the tab, URL becomes `…#/scheduledReports` | navigating to the hash directly does **not** render the tab, and a coordinate click on the tab is ignored; call `.click()` on the `li.filter-row` whose text is `Scheduled Templates` (`click_report_manager_tab` in `ea_common.py`) |
| Scheduled Templates table | columns `Schedule Name | Status | Frequency | Recipients | Report Name | Type` | Status cell is `Next Send Date: <date>`, `Failed` or `Expired` |

Template link format: `https://app.everyaction.com/ReportViewer.aspx?ReportId=<id>&TemplateId=<id>`.

## Report Viewer (a saved template)

| Element | Selector | Notes |
| --- | --- | --- |
| Applied filters | text `Applied Filters … Contact Records:All ContactsDate Received:1/1/26 - 12/31/26` | read from `document.body.innerText`; the saved template and the scheduled report share them |
| Report summary | `First Date Received`, `Last Date Received`, `Number/Count` | useful sanity numbers (`79.5K` on 2026-10-18) |
| Export menu | `button` with text `Export As...` | opens a dropdown |
| CSV export | `#export-report-action-csv` (an `a` with `href="javascript:void(0)"`) | hidden until the dropdown is open; open the menu with a DOM `.click()` on the button, then `.click()` the anchor (coordinate clicks are dropped while the tab is hidden) |
| Export modal | `[role=dialog]` with text `Export in Progress … My Export Files … available for download until 11:59 PM (ET) today` | close with the `Close` button |
| Report Actions menu | `button` with text `Report Actions` | items: `Save Changes`, `Save As`, `Schedule` (`#schedule-report-action`), `Send to My List`, `Bulk Edit` |
| Schedule | clicking `#schedule-report-action` navigates to `ReportScheduleDetails.aspx?TemplateId=<numeric id>` | the numeric id differs from the `EID…` id of the viewer URL |

The export is **asynchronous**. Nothing downloads from the viewer.

## My Export Files

| Element | Selector / URL | Notes |
| --- | --- | --- |
| List | `https://app.everyaction.com/ExportList.aspx` | ASP.NET grid `table tr`; columns `Export File | Exported | List Size | Record Count | Export Description | Download Link` |
| In progress | row text contains `In Progress`, record count `0` | poll every 30 s |
| Ready | row has a link `Download File` → `https://app.everyaction.com/ExportFileDownloadHandler.ashx?exportFileId=<id>` and `Send via SFTP` | record count appears (`79,542`) |
| File | `ContributionReport-<exportFileId>.zip` containing `ContributionReport-<exportFileId>.csv` | CSV is UTF-16 LE with BOM, first line `SEP=,`, then the header |

Download in the harness: `cdp("Browser.setDownloadBehavior", behavior="allow", downloadPath=…)` then
navigate to the download URL; the file lands in `downloadPath` with its original name.

## New Scheduled Report form (`ReportScheduleDetails.aspx?TemplateId=…`)

| Field | Selector | Default on open | Set to |
| --- | --- | --- | --- |
| Contact Records | `#contactRecords` (select2) | `All Contacts` | leave |
| Users | select2 `#s2id_autogen1` | the logged-in user | leave (harmless extra recipient) |
| Additional Recipients | `#targetEmails` | empty | comma-separated emails; `data.analysis@exacti.us` is the one the service reads |
| Schedule Name/Email Subject | `#scheduleName` | empty, required | exactly the template name; EA prefixes `EveryAction Scheduled Report - ` |
| Schedule Description | `#scheduleDescription` | empty | leave |
| Frequency | `#RecurrenceType` (`select`, options `string:Daily`, `string:Weekly`, `string:Monthly`, `string:TwiceMonthly`, `string:Quarterly`, `string:FiscalQuarterly`); `ng-model` `scheduleSettingsCtrl.model.recurrence.recurrenceType` | opens showing Daily but the bound model defaults to `Monthly`; a DOM `value`+`change` does not stick (Angular re-renders the select back to the model on `$digest`) | assign the `ng-model` inside `$apply` (`angular.element(s).scope().$apply(() => sc.$eval(m + " = 'Daily'"))`), then verify the summary line reads `delivered daily` before submitting |
| Start Date | `#StartDate` (text + datepicker) | tomorrow | tomorrow (`MM/DD/YYYY`) |
| End Date | `#EndDate` | tomorrow | `12/31/<year>` |
| Summary line | text `Your report will be delivered daily, starting on <weekday, Month D, YYYY>` | | read back as proof |
| Buttons | `#cancelButton`, `#scheduleButton` | | the click navigates back to the viewer; the schedule appears in Scheduled Templates |

Inputs are Angular-bound: set them by focusing the element and typing (CDP `Input.insertText`
after select-all/delete), then Tab out, so the model updates. Setting `.value` from JavaScript does
not update the bound model. When the EA tab is not the visible tab in Chrome
(`document.visibilityState === 'hidden'`), a coordinate click no longer focuses the input; wrap the
typing in `Emulation.setFocusEmulationEnabled` (done by `type_into` in `ea_common.py`), which is
why the scripts work while the operator looks at another tab.

## Observed schedule history for whitestork (2026-10-18)

Schedules of `Exactius_Contribution_Report - whitestork` created on 2026-03-22, 05-18, 06-29, 07-13,
07-16 (×2), 09-21: all `Failed`. New one created 2026-10-18, next send 2026-10-19. The cause of the
`Failed` status is not shown anywhere in the UI.

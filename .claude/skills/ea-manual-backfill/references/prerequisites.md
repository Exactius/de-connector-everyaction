# Prerequisites

Run these checks before the workflow. Each block says what "good" looks like.

## 1. Google Cloud: user login and Application Default Credentials

```bash
gcloud auth list --filter=status:ACTIVE --format='value(account)'      # your @exacti.us account
gcloud auth application-default print-access-token >/dev/null && echo "ADC OK"
bq query --use_legacy_sql=false 'SELECT 1'                             # bq works
```

Both logins matter. `bq` and `gcloud` use the user login; the local service uses ADC for Secret
Manager (`projects/815522637671/secrets/gmail_secret`, read even in CSV mode) and for BigQuery.
If either fails:

```bash
gcloud auth login
gcloud auth application-default login
```

Access needed: read/write on the partner's bronze dataset (e.g. `ex-whitestork.bronze`), read/write on
`peppy-castle-368715.ex_elt_testing`, `secretmanager.secretAccessor` on project `815522637671`.

## 2. Python environment of the service

The upload goes through the service running locally (`main.py`, FastAPI on port 8080). From the repo
root:

```bash
python3 --version                      # 3.11 works; the Dockerfile uses 3.10
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -c "import main; print('service imports OK')"
```

`uv` is faster if installed: `uv venv --python 3.11 .venv && uv pip install -r requirements.txt --python .venv/bin/python`.
The validation script reuses this venv for pandas.

## 3. browser-use (CLI) and Chrome

The skill drives the operator's own Chrome, logged in to EveryAction. No EA password is stored
anywhere, which is the point.

```bash
browser-use --version                  # 0.1.x; install: uv tool install "browser-use[cli]"  (or pipx)
browser-use doctor                     # "chrome running" + "daemon alive" once connected
```

One-time setup in Google Chrome (not Arc, not Safari: the harness attaches to Chrome's DevTools port):

1. Open `chrome://inspect/#remote-debugging` and tick **Allow remote debugging for this browser instance**.
2. Log in to `https://app.everyaction.com` in that same Chrome and pick the partner committee.
3. Run any `browser-use` command (the skill's step 1 script is fine). Chrome shows a popup
   **Allow remote debugging?** → click **Allow** while the command is still waiting. If the command
   times out first, just rerun it and click faster. `browser-use mac-approve` can click it for you only
   if your terminal app has Accessibility permission in System Settings.

Check the connection:

```bash
browser-use <<'PY'
print([t.get("url") for t in list_tabs()])
PY
```

Expect a list with an `app.everyaction.com` URL. `permission-blocked` means the popup was not
accepted; `DevToolsActivePort not found` means step 1 was not done in the Chrome that is running.

The harness runs Python snippets with helpers pre-imported (`list_tabs`, `goto_url`, `wait_for_load`,
`js`, `click_at_xy`, `cdp`, `page_info`). The skill's scripts are such snippets, fed on stdin
(`browser-use < script.py`); parameters come from environment variables.

## 4. Claude Code permission

In auto mode Claude Code's classifier refuses to launch `browser-use` by itself. Add the allow rule
once (`/permissions` → Allow):

```
Bash(browser-use:*)
```

Without it the operator has to run every browser command with the `!` prefix and paste the output.

## 5. Where things are

| Thing | Path |
| --- | --- |
| Service repo | `~/Repositories/Exactius/de-connector-everyaction` (this repo) |
| Caller DAG | `~/Repositories/Exactius/Airflow_dags_v2/dags/<partner>/daily/v1/pipeline/tasks/ingestion/ea.yaml` |
| dbt repo (whitestork) | `~/Repositories/Exactius/whitestork_DBT_V2`, model `models/silver/blended/every_action_contribution_report.sql` |
| Cloud Run service | `ea-email-service` (europe-west2, project `peppy-castle-368715`) |
| Human runbook | `manual_processing/MANUAL_EA_CSV_WALKTHROUGH.md` |

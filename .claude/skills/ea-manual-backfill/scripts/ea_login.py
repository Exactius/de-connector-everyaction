# Log in to EveryAction in the attached Chrome with the credentials stored in Secret Manager, then select the committee.
# Run:  [EA_LOGIN_SECRET=ea-login-whitestork] [EA_SECRET_PROJECT=peppy-castle-368715] \
#         browser-use < .claude/skills/ea-manual-backfill/scripts/ea_login.py
# The secret is read inside this process and typed into the Bonterra login form; nothing from it is printed.
import json
import os
import subprocess
import time

SKILL_SCRIPTS = os.path.join(os.getcwd(), ".claude", "skills", "ea-manual-backfill", "scripts")
exec(open(os.path.join(SKILL_SCRIPTS, "ea_common.py")).read())

SECRET_NAME = os.environ.get("EA_LOGIN_SECRET", "ea-login-whitestork")
SECRET_PROJECT = os.environ.get("EA_SECRET_PROJECT", "peppy-castle-368715")
LOGIN_HOST = "auth.bonterra.network"
EA_HOME = "https://app.everyaction.com/"


def read_login_secret() -> dict:
    """Fetch the login JSON from Secret Manager (username, password, committee, login_url)."""
    raw = subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest", f"--secret={SECRET_NAME}", f"--project={SECRET_PROJECT}"],
        capture_output=True, text=True, check=True,
    ).stdout
    secret = json.loads(raw)
    for key in ("username", "password"):
        if not secret.get(key) or secret[key] == "REPLACE_ME_IN_CONSOLE":
            print(f"secret {SECRET_NAME} has no usable {key}")
            raise SystemExit(2)
    return secret


def on_login_host() -> bool:
    """True while the Bonterra universal login is showing."""
    return LOGIN_HOST in current_url()


def submit_step(field_selector: str, value: str, step_name: str) -> None:
    """Type a value into the current login step and press its Next/Continue button."""
    if center_of(selector=field_selector) is None:
        print(f"{step_name}: field {field_selector} not visible on {current_url()}; see references/ea-ui-map.md (Login)")
        raise SystemExit(4)
    type_into(selector=field_selector, text=value)
    js("document.querySelector('button[name=action]').click()")
    wait_for_load()
    time.sleep(5)


cdp("Emulation.setFocusEmulationEnabled", enabled=True)
goto_url(EA_HOME)
settle(seconds=5)
if not on_login_host() and EA_HOST in current_url():
    print("already logged in")
else:
    secret = read_login_secret()
    if not on_login_host():
        print(f"unexpected page {current_url()}; expected the {LOGIN_HOST} login")
        raise SystemExit(3)
    submit_step(field_selector="input[name=username]", value=secret["username"], step_name="email step")
    if on_login_host() and center_of(selector="input[name=password]") is not None:
        submit_step(field_selector="input[name=password]", value=secret["password"], step_name="password step")
    error = js("(document.body.innerText.match(/(Wrong|incorrect|invalid|verification|code)[^\\n]*/i) || [''])[0]")
    if on_login_host():
        print(f"still on the login host after submitting: {current_url()} | page says: {error[:120] or 'nothing'}")
        raise SystemExit(5)
    print("login submitted")

ensure_ea_session(committee=os.environ.get("EA_COMMITTEE") or read_login_secret().get("committee"))
goto_url("https://app.everyaction.com/MyHomepage.aspx?HasCommittee=1#/")
settle()
who = js("(document.body.innerText.match(/\\n([^\\n]+)\\n(Operation [^\\n]+|[A-Z][^\\n]{3,40})\\nAsk AI/) || [])")
print(f"LOGGED_IN: {current_url()} | header: {who[1] if who and len(who) > 2 else '?'} / {who[2] if who and len(who) > 2 else '?'}")

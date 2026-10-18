# Shared helpers for the EA browser scripts. Not run on its own: each script inlines it with
#   exec(open(<this file>).read())
# because browser-use executes the stdin snippet with its helpers (js, cdp, goto_url, ...) pre-imported
# and no import path for sibling files.
import os
import time

EA_HOST = "app.everyaction.com"
SETTLE_SECONDS = 4


def settle(seconds: float = SETTLE_SECONDS) -> None:
    """Wait for the Angular page to finish rendering after a navigation or a click."""
    wait_for_load()
    time.sleep(seconds)


def current_url() -> str:
    """URL of the attached tab."""
    url = page_info()["url"]
    return url


def center_of(selector: str) -> list | None:
    """Viewport center of the first element matching a CSS selector, or None when absent or hidden."""
    result = js(
        "(() => { const e = document.querySelector(" + repr(selector) + "); if (!e || e.offsetParent === null) return null;"
        " e.scrollIntoView({block: 'center'}); const b = e.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()"
    )
    return result


def center_of_text(text: str, tags: str = "button, a, li, div, span") -> list | None:
    """Viewport center of the first visible element whose trimmed text equals the given text."""
    result = js(
        "(() => { const els = Array.from(document.querySelectorAll(" + repr(tags) + "))"
        ".filter(e => e.offsetParent !== null && e.textContent.trim() === " + repr(text) + ");"
        " const e = els.find(x => x.children.length === 0) || els[0]; if (!e) return null;"
        " e.scrollIntoView({block: 'center'}); const b = e.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; })()"
    )
    return result


def click_selector(selector: str) -> None:
    """Click an element by selector, by coordinates (works through Angular handlers)."""
    point = center_of(selector=selector)
    if point is None:
        raise RuntimeError(f"element not visible: {selector}")
    click_at_xy(point[0], point[1])


def click_text(text: str, tags: str = "button, a, li, div, span") -> None:
    """Click the visible element whose text equals the given text."""
    point = center_of_text(text=text, tags=tags)
    if point is None:
        raise RuntimeError(f"element with text not visible: {text!r}")
    click_at_xy(point[0], point[1])


def click_report_manager_tab(text: str) -> None:
    """Switch a Report Manager left tab (li.filter-row); these only react to a DOM click, not to coordinates."""
    clicked = js(
        "(() => { const e = Array.from(document.querySelectorAll('li.filter-row'))"
        ".find(e => e.textContent.trim() === " + repr(text) + "); if (!e) return false; e.click(); return true; })()"
    )
    if not clicked:
        click_text(text=text)


def type_into(selector: str, text: str) -> None:
    """Replace the content of an Angular-bound input by real keystrokes, then Tab out so the model updates."""
    cdp("Emulation.setFocusEmulationEnabled", enabled=True)
    try:
        click_selector(selector=selector)
        time.sleep(0.4)
        focused = js("document.activeElement && ('#' + document.activeElement.id)")
        if focused != selector:
            js("document.querySelector(" + repr(selector) + ").focus()")
            time.sleep(0.2)
        cdp("Input.dispatchKeyEvent", type="keyDown", key="a", code="KeyA", modifiers=4, commands=["selectAll"])
        cdp("Input.dispatchKeyEvent", type="keyUp", key="a", code="KeyA", modifiers=4)
        cdp("Input.dispatchKeyEvent", type="keyDown", key="Delete", code="Delete")
        cdp("Input.dispatchKeyEvent", type="keyUp", key="Delete", code="Delete")
        cdp("Input.insertText", text=text)
        time.sleep(0.3)
        cdp("Input.dispatchKeyEvent", type="keyDown", key="Tab", code="Tab")
        cdp("Input.dispatchKeyEvent", type="keyUp", key="Tab", code="Tab")
        time.sleep(0.4)
    finally:
        cdp("Emulation.setFocusEmulationEnabled", enabled=False)


def input_value(selector: str) -> str:
    """Current value of an input or textarea."""
    value = js("(() => { const e = document.querySelector(" + repr(selector) + "); return e ? e.value : null; })()")
    return value


def body_text(limit: int = 4000) -> str:
    """Visible page text, collapsed."""
    text = js("document.body.innerText.replace(/\\n{2,}/g, '\\n').slice(0, " + str(limit) + ")")
    return text


def table_rows(filter_text: str | None = None) -> list[str]:
    """Visible table rows as collapsed text, optionally only those containing filter_text."""
    rows = js(
        "Array.from(document.querySelectorAll('table tr, [role=row]'))"
        ".map(r => r.innerText.replace(/\\s+/g, ' ').trim()).filter(t => t)"
    )
    if filter_text:
        rows = [row for row in rows if filter_text in row]
    return rows


def ensure_ea_session(committee: str | None) -> None:
    """Stop on the login page; select the committee when EA asks for it; keep input working while the tab is hidden."""
    cdp("Emulation.setFocusEmulationEnabled", enabled=True)
    url = current_url()
    if EA_HOST not in url:
        print(f"LOGIN_REQUIRED: current url {url}. Log in to https://{EA_HOST} in this Chrome and rerun.")
        raise SystemExit(2)
    if "SelectCommittee" not in url:
        return
    links = js(
        "Array.from(document.querySelectorAll('a')).filter(a => a.getAttribute('href') === 'javascript:void(0)')"
        ".map(a => a.textContent.trim()).filter(t => t)"
    )
    if not committee:
        print(f"SELECT_COMMITTEE_REQUIRED: set EA_COMMITTEE to one of {links}")
        raise SystemExit(3)
    match = next((link for link in links if committee.lower() in link.lower()), None)
    if match is None:
        print(f"SELECT_COMMITTEE_REQUIRED: {committee!r} not among {links}")
        raise SystemExit(3)
    click_text(text=match, tags="a")
    time.sleep(1)
    click_text(text="Next", tags="button")
    settle()
    print(f"committee selected: {match}")

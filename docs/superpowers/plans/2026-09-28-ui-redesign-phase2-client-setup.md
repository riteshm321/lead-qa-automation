# UI Redesign Phase 2: Client Setup Restructure + Shared Visual Components Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the minimal shared visual components deferred from Phase 1 (status chips, empty state, shared error/warning rendering), with Client Setup as their first real caller, and restructure Client Setup into one consistent Basics / Delivery / Checks tab layout with an always-visible configuration summary strip.

**Architecture:** A new `core/ui_components.py` holds the status-chip and empty-state helpers. `core/branding.py` is page setup only (`configure_page()`), so it's the wrong home for in-page components. `core/errors.py` already owns user-facing error rendering (`render_error`), so the new generic `render_problem` goes there and `render_error` calls it. `pages/1_Client_Setup.py` keeps its exact execution order. The restructure mostly changes which tab each existing block is written into. Streamlit tab containers are created up front and can be written to in any order, so code that reads `accumulated_path` in the Leadcap tab still runs after it's defined.

**Tech Stack:** Python, Streamlit 1.61.1 (`st.badge` / `:color-badge[...]` markdown, `st.tabs`, Material Symbols `:material/name:`, no new dependency), pytest + `streamlit.testing.v1.AppTest`.

## Global Constraints

- **HIGH-RISK TASK WARNING (Task 4):** same caution as Phase 1's Task 7 (Run Check). `pages/1_Client_Setup.py` is about 1,600 lines. `tests/test_client_setup_page.py` has about 39 tests and must pass with **zero edits to existing tests**. If an existing test needs changing to pass, stop: the restructure has broken a real behaviour. Don't patch around it in the test.
- **Keep every widget label, key, default value and save behaviour exactly as it is.** Tests look widgets up by label (`next(t for t in at.text_input if t.label == "Client name")`) or by key. Only these may change:
  - which tab a block renders in;
  - section headings (`st.subheader` / `st.markdown("**...**")`);
  - disabled/empty captions (Task 6);
  - the wording of validation messages. Task 6 appends a suggestion, but every existing message text stays as a substring.
- **The New/Edit "Mode" radio must stay above the tabs.** Client Mode's radio is also labeled `"Mode"`. Nine tests do `next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client")`, which relies on the New/Edit radio being first in the element tree.
- **Don't reorder executable code except where a step says so.** Moving a block to another tab should only change a `with tab_x:` line or turn a `st.divider()` + bold heading into a new card opener at the same indentation. After each page task, `git diff -w pages/1_Client_Setup.py` must show only those structural lines.
- Don't change `core/` business logic, profile JSON shape, or `ClientProfile`.
- Run `python -m pytest tests/test_client_setup_page.py -q` after every page task. Run `python -m pytest -q` before calling the plan done.
- Direct commits to `master`, one commit per task.

---

### Task 1: Status chip helpers (`core/ui_components.py`)

**Files:**
- Create: `core/ui_components.py`
- Test: `tests/test_ui_components.py` (new)

**Interfaces:**
- `ChipState = Literal["on", "off", "configured", "needs_setup"]`
- `chip_markdown(state: ChipState, label: str = "") -> str`: returns a `:color-badge[...]` markdown snippet. This is the same markup `st.badge` produces, so it can also be used inside tab labels and inline rows.
- `chip_state(enabled: bool, needs_setup: bool = False) -> ChipState`: a pure mapping used by the summary strip.
- `render_status_strip(items: list[tuple[str, ChipState]]) -> None`: renders every chip on one line in one `st.markdown` element. Separate `st.badge` calls would stack vertically, one element each.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ui_components.py
from streamlit.testing.v1 import AppTest

from core.ui_components import chip_markdown, chip_state


def test_chip_markdown_uses_spec_glyphs_and_colors():
    assert chip_markdown("on") == ":green-badge[● On]"
    assert chip_markdown("off") == ":gray-badge[○ Off]"
    assert chip_markdown("configured") == ":blue-badge[✓ Configured]"
    assert chip_markdown("needs_setup") == ":orange-badge[⚠ Needs setup]"


def test_chip_markdown_prefixes_a_label():
    assert chip_markdown("on", "Leadcap") == ":green-badge[Leadcap ● On]"


def test_chip_state_mapping():
    assert chip_state(False) == "off"
    assert chip_state(False, needs_setup=True) == "off"
    assert chip_state(True) == "on"
    assert chip_state(True, needs_setup=True) == "needs_setup"


def test_render_status_strip_renders_one_markdown_row():
    def _app():
        from core.ui_components import render_status_strip
        render_status_strip([("Leadcap", "on"), ("TAL", "needs_setup"), ("Exclusion", "off")])

    at = AppTest.from_function(_app)
    at.run()
    assert not at.exception
    assert len(at.markdown) == 1
    value = at.markdown[0].value
    assert ":green-badge[Leadcap ● On]" in value
    assert ":orange-badge[TAL ⚠ Needs setup]" in value
    assert ":gray-badge[Exclusion ○ Off]" in value
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_ui_components.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.ui_components'`.

- [ ] **Step 3: Implement**

```python
# core/ui_components.py
"""Small shared in-page visual components (status chips, empty states).

Page chrome (logo, login gate, sidebar) lives in core/branding.py; user-facing
error/warning rendering lives in core/errors.py. This module is for the
card-level building blocks from the UI redesign spec (section 1).
"""
from typing import Literal

import streamlit as st

ChipState = Literal["on", "off", "configured", "needs_setup"]

# (text, st.badge color). Glyphs match the design spec's section 1 exactly.
_CHIPS: dict[str, tuple[str, str]] = {
    "on": ("● On", "green"),
    "off": ("○ Off", "gray"),
    "configured": ("✓ Configured", "blue"),
    "needs_setup": ("⚠ Needs setup", "orange"),
}


def chip_markdown(state: ChipState, label: str = "") -> str:
    """Markdown for one status chip -- the same `:color-badge[...]` markup
    st.badge renders, returned as a string so it can also go inside a tab
    label or a single-line row of several chips."""
    text, color = _CHIPS[state]
    body = f"{label} {text}" if label else text
    return f":{color}-badge[{body}]"


def chip_state(enabled: bool, needs_setup: bool = False) -> ChipState:
    """A feature that's off is just "off", even if it would need setup were
    it on; an enabled feature missing required config is "needs_setup"."""
    if not enabled:
        return "off"
    return "needs_setup" if needs_setup else "on"


def render_status_strip(items: list[tuple[str, ChipState]]) -> None:
    """One row of labeled chips, in a single markdown element."""
    st.markdown("&nbsp; ".join(chip_markdown(state, label) for label, state in items))
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_ui_components.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add core/ui_components.py tests/test_ui_components.py
git commit -m "Add shared status chip helpers in core/ui_components.py"
```

---

### Task 2: Empty-state helper

**Files:**
- Modify: `core/ui_components.py`
- Test: `tests/test_ui_components.py`

**Interfaces:**
- `render_empty_state(message: str, hint: str = "", icon: str = "inbox") -> None`: renders one `st.caption` in the form `:material/<icon>: <message> — <hint>`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_ui_components.py`)

```python
def test_render_empty_state_with_hint():
    def _app():
        from core.ui_components import render_empty_state
        render_empty_state("No TAL sources configured yet.", "Click **➕ Add TAL Source** below.")

    at = AppTest.from_function(_app)
    at.run()
    assert not at.exception
    assert at.caption[0].value == ":material/inbox: No TAL sources configured yet. — Click **➕ Add TAL Source** below."


def test_render_empty_state_without_hint_and_custom_icon():
    def _app():
        from core.ui_components import render_empty_state
        render_empty_state("TAL check is off.", icon="toggle_off")

    at = AppTest.from_function(_app)
    at.run()
    assert at.caption[0].value == ":material/toggle_off: TAL check is off."
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_ui_components.py -q -k empty_state`
Expected: FAIL. The app raises `ImportError: cannot import name 'render_empty_state'`, so `at.exception` is truthy.

- [ ] **Step 3: Implement** (append to `core/ui_components.py`)

```python
def render_empty_state(message: str, hint: str = "", icon: str = "inbox") -> None:
    """Icon + one short line on what's missing + (optionally) where to fix
    it -- instead of rendering nothing or a bare caption (spec section 2)."""
    text = f":material/{icon}: {message}"
    if hint:
        text += f" — {hint}"
    st.caption(text)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_ui_components.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add core/ui_components.py tests/test_ui_components.py
git commit -m "Add shared empty-state helper"
```

---

### Task 3: Shared error/warning helper (`render_problem` in `core/errors.py`)

**Files:**
- Modify: `core/errors.py`
- Test: `tests/test_errors.py`

**Interfaces:**
- `render_problem(message: str, suggestion: str = "", level: Literal["error", "warning"] = "error") -> None`
- `render_error(exc)` keeps its signature and logging, and now calls `render_problem(message, fix)`. The only visible change: the `⚠️ ` text prefix becomes a proper Material `icon=`. `grep -rn "⚠️" tests/` currently has no hits against `render_error` output. Re-run that grep in Step 1 to confirm.

- [ ] **Step 1: Write the failing test** (append to `tests/test_errors.py`). First run `grep -rn "⚠️" tests/`. If any hit asserts on `render_error` output, stop and flag it.

```python
from streamlit.testing.v1 import AppTest


def test_render_problem_error_with_suggestion():
    def _app():
        from core.errors import render_problem
        render_problem("Client name is required.", "Enter a name in Basics → Client name.")

    at = AppTest.from_function(_app)
    at.run()
    assert not at.exception
    assert at.error[0].value == "Client name is required.\n\n**Suggested fix:** Enter a name in Basics → Client name."
    assert at.error[0].icon == ":material/error:"


def test_render_problem_warning_without_suggestion():
    def _app():
        from core.errors import render_problem
        render_problem("TAL is enabled but no sources are configured.", level="warning")

    at = AppTest.from_function(_app)
    at.run()
    assert at.warning[0].value == "TAL is enabled but no sources are configured."
    assert at.warning[0].icon == ":material/warning:"
    assert len(at.error) == 0


def test_render_error_routes_through_render_problem():
    def _app():
        from core.errors import render_error
        render_error(PermissionError("[Errno 13] Permission denied: 'x.xlsx'"))

    at = AppTest.from_function(_app)
    at.run()
    assert "couldn't be opened" in at.error[0].value
    assert "**Suggested fix:**" in at.error[0].value
    assert at.error[0].icon == ":material/error:"
```

(If `Alert.icon` isn't exposed by this AppTest version, drop only the `.icon` assertions and note it in the commit. The `.value` assertions carry the behaviour.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_errors.py -q`
Expected: the 3 new tests fail (`ImportError` for `render_problem`; `icon` mismatch for `render_error`). Existing tests pass.

- [ ] **Step 3: Implement.** Replace `render_error`'s last four lines and add `render_problem` above it:

```python
from typing import Literal

ProblemLevel = Literal["error", "warning"]


def render_problem(message: str, suggestion: str = "", level: ProblemLevel = "error") -> None:
    """The one shared way to show a user-facing error/warning: icon +
    message + (when there's an obvious next step) a one-line suggestion.
    Pages call this instead of ad hoc st.error/st.warning so every problem
    looks and reads the same everywhere (UI redesign spec, section 2)."""
    body = f"{message}\n\n**Suggested fix:** {suggestion}" if suggestion else message
    if level == "warning":
        st.warning(body, icon=":material/warning:")
    else:
        st.error(body, icon=":material/error:")
```

and in `render_error`:

```python
    get_logger().exception("Handled error shown to user: %s", exc, exc_info=exc)
    message, fix = friendly_error(exc)
    render_problem(message, fix)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_errors.py tests/test_client_setup_page.py tests/test_run_check_page.py -q`
Expected: all pass. `render_error` is called from many pages, so the two page suites double as regression checks.

- [ ] **Step 5: Commit**

```bash
git add core/errors.py tests/test_errors.py
git commit -m "Add shared render_problem error/warning helper; route render_error through it"
```

---

### Task 4: Client Setup — consolidate into Basics / Delivery / Checks tabs (HIGH RISK)

**Files:**
- Modify: `pages/1_Client_Setup.py`
- Test: `tests/test_client_setup_page.py` (append new tests only; existing tests untouched)

**Target layout:**

| Top tab | Cards (in render order) |
|---|---|
| `:material/badge: Basics` | Client (name, group) · Reference Files · Jira · File Collation |
| `:material/send: Delivery` | Client Mode (+ Lead Template) · Google Sheets · Box Tracker · Convertr · Enhancio · Integrate |
| `:material/checklist: Checks` | nested tabs: Leadcap · Exclusion · TAL · Suppression · Dedupe · Complex Account · Duplicate |

Box Tracker, Convertr, Enhancio and Integrate go in Delivery. The spec's section 4 doesn't mention them, but they are all "where valid leads go" destinations. Today they sit inside the Complex Account card. File Collation isn't in the spec either; it stays in Basics.

**Interfaces:** no new functions. The nested check tabs keep the existing variable names (`tab_leadcap, tab_exclusion, tab_tal, tab_suppression, tab_dedupe, tab_complex`), plus a new `tab_duplicate`, so every existing `with tab_leadcap:` line stays as it is.

- [ ] **Step 1: Pre-flight collision check (no code yet).** Run:

```bash
grep -n 'label == "\(Name\|Sheet\|File path\|Tab (sheet) name\|Domain column\|Mode\)"' tests/test_client_setup_page.py
grep -n '"Name"\|"Sheet"\|"File path"\|"Tab (sheet) name"\|"Domain column"' pages/1_Client_Setup.py
```

For each generic label used by a test, confirm it's only rendered in the section that test targets under that test's own setup. Under the new order, Delivery widgets render before Checks widgets. Watch for a Lead Template tab row or a Box Tracker field sharing `"Sheet"`, `"File path"` or `"Name"` with an Exclusion source row in `test_exclusion_source_accepts_a_csv_file_and_reads_its_columns_and_saves`. If a real collision is visible only in that test's setup, stop and flag it. Don't rename widgets.

- [ ] **Step 2: Write the failing tests** (append)

```python
def _tab(at, suffix):
    return next(t for t in at.tabs if t.label.endswith(suffix))


def test_client_setup_has_basics_delivery_checks_tabs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    labels = {t.label for t in at.tabs}
    assert {":material/badge: Basics", ":material/send: Delivery", ":material/checklist: Checks"} <= labels
    for check in ("Leadcap", "Exclusion", "TAL", "Suppression", "Dedupe", "Complex Account", "Duplicate"):
        assert any(label.startswith(check) for label in labels), check


def test_sections_live_in_their_new_tabs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    basics, delivery, checks = _tab(at, "Basics"), _tab(at, "Delivery"), _tab(at, "Checks")

    assert any(t.label == "Client name" for t in basics.text_input)
    assert any(t.label == "Jira ticket key or link (optional)" for t in basics.text_input)
    assert any(c.label == "Enable file collation for this client" for c in basics.checkbox)

    assert any(r.label == "Mode" for r in delivery.radio)
    delivery_boxes = {c.label for c in delivery.checkbox}
    assert "This client delivers leads to Google Sheets" in delivery_boxes
    assert "This client uploads to Convertr" in delivery_boxes
    assert "This client uses a Box Tracker" in delivery_boxes

    check_boxes = {c.label for c in checks.checkbox}
    assert "Enable Duplicate check" in check_boxes
    assert "This is a complex account" in check_boxes
    assert "This client uploads to Convertr" not in check_boxes


def test_new_edit_mode_radio_stays_above_the_tabs(tmp_path, monkeypatch):
    # Nine existing tests pick the FIRST radio labeled "Mode" to mean the
    # New/Edit radio; Client Mode's radio shares that label.
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    first_mode = next(r for r in at.radio if r.label == "Mode")
    assert "Edit existing client" in first_mode.options
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_client_setup_page.py -q -k "tabs or new_tabs or above_the_tabs"`
Expected: the first two fail (no `Basics`-suffixed `:material/` tab / `StopIteration`). The third passes already; it's a guard.

- [ ] **Step 4: Implement, one structural edit at a time**

4a. Replace the existing `client_name = ...` / `client_group_input = ...` / `st.divider()` / `tab_basics, ... = st.tabs([...])` block with the lines below. The `profile_identity` reset block above it stays where it is. The two text inputs get 8 more spaces of indentation and are otherwise unchanged.

```python
tab_basics, tab_delivery, tab_checks = st.tabs([
    ":material/badge: Basics", ":material/send: Delivery", ":material/checklist: Checks",
])
with tab_checks:
    tab_leadcap, tab_exclusion, tab_tal, tab_suppression, tab_dedupe, tab_complex, tab_duplicate = st.tabs([
        "Leadcap", "Exclusion", "TAL", "Suppression", "Dedupe", "Complex Account", "Duplicate",
    ])

with tab_basics:
    with st.container(border=True):
        st.subheader(":material/person: Client")
        client_name = st.text_input("Client name", value=profile.name if profile else "")
        client_group_input = st.text_input(
            "Client group (optional)",
            value=profile.client_group if profile else "",
            key="client_group_input",
            help="Groups this profile with other regional profiles for the same brand (e.g. \"Autodesk APAC\" and "
                 "\"Autodesk EMEA\" both set this to \"Autodesk\") so the client picker offers them as one group "
                 "instead of two unrelated entries. Leave blank if this client isn't split by region.",
        )
```

(The existing `with tab_basics:` line opening Reference Files follows directly. A second `with tab_basics:` on the same tab is fine; content appends in order.)

4b. **Jira gets its own card.** Cut the whole `col_jira_ticket, col_jira_reporter = st.columns(2)` block (both columns, both text inputs, unchanged) out of the Reference Files card. Paste it straight after the Reference Files card's last line (the `st.caption("Enter a valid Accumulated Report path...")`), under a new opener at the same 4-space level as the other cards in `tab_basics`:

```python
    with st.container(border=True):
        st.subheader(":material/confirmation_number: Jira")
        col_jira_ticket, col_jira_reporter = st.columns(2)
        # ... pasted block unchanged ...
```

This is the only execution-order move in the task. It's safe because neither Jira variable is read until the Save button.

4c. **Client Mode moves to Delivery.** Directly above `    with st.container(border=True):` / `        st.subheader("Client Mode")`, insert at column 0:

```python
with tab_delivery:
```

(No re-indenting: the card is already at 4 spaces.)

4d. **Google Sheets gets its own Delivery card.** Replace these two lines (8-space indent, inside the Client Mode card):

```python
        st.divider()
        st.markdown("**Google Sheets Lead Delivery (optional)**")
```

with the lines below. The rest of the Google Sheets code is already at 8 spaces and stays as it is.

```python
with tab_delivery:
    with st.container(border=True):
        st.subheader("Google Sheets Lead Delivery (optional)")
```

4e. **Duplicate moves to its own check tab.** Directly above `    with st.container(border=True):` / `        st.subheader("Duplicate Check")`, insert at column 0 `with tab_duplicate:`.

4f. **The upload destinations move out of the Complex Account card.** In the `with tab_complex:` card, make the same kind of replacement for each of the four `st.divider()` + `st.markdown("**<Name> (optional)**")` pairs:

```python
with tab_delivery:
    with st.container(border=True):
        st.subheader("<Name> (optional)")
```

`<Name>` is Box Tracker, Convertr Upload, Enhancio Upload and Integrate Upload in turn. Their bodies are already at 8 spaces and need no change.

4g. Change the Dedupe card's `st.subheader("Dedupe List")` to stay as it is. The tab label is now `"Dedupe"`, and Duplicate has its own tab.

- [ ] **Step 5: Verify the diff is purely structural**

Run: `git diff -w pages/1_Client_Setup.py`
Expected, and nothing else:
- the `st.tabs` block;
- the Client card opener;
- the Jira cut/paste and its opener;
- 2 `with tab_delivery:`/`with tab_duplicate:` single-line inserts;
- 5 divider/markdown→card-opener swaps.

- [ ] **Step 6: Run to verify everything passes**

Run: `python -m pytest tests/test_client_setup_page.py -q`
Expected: all ~39 existing tests plus the 3 new ones pass, **with no edits to existing tests**. If any existing test fails, use `superpowers:systematic-debugging`. Likely causes: a generic-label collision (Step 1), or a nested-tab limitation. If nested `st.tabs` turn out not to be supported, fall back to one bordered card per check stacked inside `tab_checks`. That changes the chip location in Task 5, so flag it before continuing.

Run: `python -m pytest -q`
Expected: full suite green.

- [ ] **Step 7: Manual smoke check.** Run `streamlit run Summary.py`, open Client Setup, and click through every tab and nested check tab for both a new and an existing client. Also check the dark theme.

- [ ] **Step 8: Commit**

```bash
git add pages/1_Client_Setup.py tests/test_client_setup_page.py
git commit -m "Restructure Client Setup into Basics / Delivery / Checks tabs"
```

---

### Task 5: Summary strip, "configured" tab chips, save spinner

**Files:**
- Modify: `pages/1_Client_Setup.py`
- Test: `tests/test_client_setup_page.py`

**Semantics:**
- **Summary strip:** live. It reflects the current widget values on every rerun. It's written into an `st.container()` slot created *above* the tabs and filled *after* all tab code has run, so every `*_enabled` variable exists by then.
- **Check tab-label chip:** reflects the **saved** profile. Tab labels are fixed when `st.tabs` is called, which is before the checkboxes inside them exist. So the label reads "✓ Configured" when the loaded profile has that check on, and new clients show no chips. Put this in a code comment so nobody "fixes" it into a live value.
- **Save spinner:** wraps `save_profile` and the Convertr credential save (spec section 2 loading feedback, deferred from Phase 1).
- **The `Enabled checks: ...` caption above Save is removed**; the strip replaces it. No Client Setup test asserts on it. The `"Enabled checks"` assertion in `tests/test_run_check_page.py` is about Run Check's own caption and is unaffected.

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_summary_strip_reflects_live_checkbox_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    strip = next(m for m in at.markdown if "badge[Leadcap" in m.value)
    assert ":gray-badge[Duplicate ○ Off]" in strip.value

    next(c for c in at.checkbox if c.label == "Enable Duplicate check").check().run()
    next(c for c in at.checkbox if c.label == "Enable Exclusion check").check().run()
    strip = next(m for m in at.markdown if "badge[Leadcap" in m.value)
    assert ":green-badge[Duplicate ● On]" in strip.value
    assert ":orange-badge[Exclusion ⚠ Needs setup]" in strip.value  # enabled, no sources


def test_check_tab_label_shows_configured_chip_for_saved_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, get_clients_dir
    from core.models import ClientProfile, DuplicateConfig
    from core.profile_store import save_profile
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_profile(ClientProfile(name="Dup Client", accumulated_report_path="a.xlsx",
                               duplicate=DuplicateConfig(enabled=True)), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(r for r in at.radio if r.label == "Mode").set_value("Edit existing client").run()
    next(s for s in at.selectbox if s.label == "Client").set_value("Dup Client").run()
    assert not at.exception
    labels = [t.label for t in at.tabs]
    assert "Duplicate :blue-badge[✓ Configured]" in labels
    assert "Leadcap" in labels  # off in the saved profile -> no chip
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_client_setup_page.py -q -k "summary_strip or configured_chip"`
Expected: FAIL with `StopIteration` (no strip) and an assertion error on the labels.

- [ ] **Step 3: Implement**

Add the import `from core.ui_components import chip_markdown, chip_state, render_status_strip`.

Add a helper above the top-level page code:

```python
def _check_tab_label(title: str, configured: bool) -> str:
    # Reflects the SAVED profile, not live widget state: tab labels are fixed
    # when st.tabs() is called, before the checkboxes inside them exist.
    # The summary strip above the tabs is the live view.
    return f"{title} {chip_markdown('configured')}" if configured else title
```

Directly above the top-level `st.tabs` call, add:

```python
_summary_strip_slot = st.container()
```

Replace the nested check `st.tabs([...])` list with:

```python
    tab_leadcap, tab_exclusion, tab_tal, tab_suppression, tab_dedupe, tab_complex, tab_duplicate = st.tabs([
        _check_tab_label("Leadcap", bool(profile and profile.leadcap.enabled)),
        _check_tab_label("Exclusion", bool(profile and profile.exclusion.enabled)),
        _check_tab_label("TAL", bool(profile and profile.tal.enabled)),
        _check_tab_label("Suppression", bool(profile and profile.suppression.enabled)),
        _check_tab_label("Dedupe", bool(profile and profile.dedupe_list.enabled)),
        _check_tab_label("Complex Account", bool(profile and profile.complex_account.enabled)),
        _check_tab_label("Duplicate", bool(profile and profile.duplicate.enabled)),
    ])
```

Replace the `_enabled_summary = ...` / `st.caption(f"Enabled checks: ...")` block (after the final `st.divider()`) with:

```python
with _summary_strip_slot:
    render_status_strip([
        ("Leadcap", chip_state(leadcap_enabled, needs_setup=bool(leadcap_segmented and leadcap_blank_cap_segments))),
        ("Exclusion", chip_state(exclusion_enabled, needs_setup=not exclusion_sources_result)),
        ("TAL", chip_state(tal_enabled, needs_setup=not tal_sources_result)),
        ("Suppression", chip_state(suppression_enabled, needs_setup=not suppression_sources_result)),
        ("Dedupe", chip_state(dedupe_enabled, needs_setup=not dedupe_sources_result)),
        ("Complex Account", chip_state(complex_account_enabled)),
        ("Duplicate", chip_state(duplicate_enabled)),
        ("Google Sheets", chip_state(gs_enabled, needs_setup=not gs_tabs)),
        ("Box Tracker", chip_state(box_tracker_enabled)),
        ("Convertr", chip_state(convertr_enabled, needs_setup=not convertr_campaigns)),
        ("Enhancio", chip_state(enhancio_enabled, needs_setup=not enhancio_allocations)),
        ("Integrate", chip_state(integrate_enabled, needs_setup=not integrate_sid)),
    ])
```

(Before relying on them, confirm each of these variables is pre-initialised on every code path. They should be, because the Save button's `ClientProfile(...)` call already reads all of them unconditionally.)

Wrap the save:

```python
        with st.spinner("Saving client profile..."):
            saved_path = save_profile(new_profile, get_clients_dir())
            if convertr_enabled and (convertr_account_username or convertr_account_password):
                save_convertr_account_credentials(
                    client_name, convertr_account_username, convertr_account_password)
        st.toast(f"Saved profile to {saved_path}", icon="✅")
```

(The spinner has no dedicated assertion because AppTest can't observe a spinner that finishes within one run. The ~20 existing save tests check that it doesn't change save behaviour.)

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_client_setup_page.py -q`
Expected: all pass. If a tab label renders the badge markup literally in the manual smoke check, fall back to a plain-text suffix: `f"{title} ✓"` in `_check_tab_label`, with the test updated to match. Record the fallback in the commit message.

- [ ] **Step 5: Commit**

```bash
git add pages/1_Client_Setup.py tests/test_client_setup_page.py
git commit -m "Add Client Setup summary strip, configured tab chips, and save spinner"
```

---

### Task 6: Move Client Setup's ad hoc messages to the shared helpers

**Files:**
- Modify: `pages/1_Client_Setup.py`
- Test: `tests/test_client_setup_page.py`

**Scope:**
- Save validation errors.
- The profile-load error.
- The four "enabled but no sources" warnings.
- The empty-sources caption in `_render_sources_section`.
- The disabled captions for the six checks that have one.

**Out of scope, left as they are:**
- Convertr/Enhancio/Integrate test-connection errors (`st.error(f"❌ {exc}")`) and the field-mapping line-count error. Tests assert their exact text, and they belong to the Phase 4 sweep.
- The per-destination "... is disabled for this client." captions. `"No Enhancio Client ID configured"` is asserted as a caption, so don't touch that one.

**Rule:** every existing message string stays as a substring of the new `.value`, because tests do `"can't contain" in e.value`.

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_blank_client_name_error_carries_a_suggestion(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    err = next(e for e in at.error if "Client name is required." in e.value)
    assert "**Suggested fix:**" in err.value and "Basics" in err.value


def test_enabled_check_with_no_sources_warns_with_a_next_step(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(c for c in at.checkbox if c.label == "Enable TAL check").check().run()
    warn = next(w for w in at.warning if "TAL is enabled but no sources are configured" in w.value)
    assert "Add TAL Source" in warn.value
    assert any(c.value.startswith(":material/inbox: No TAL sources configured yet") for c in at.caption)


def test_disabled_check_shows_an_empty_state_pointing_at_its_toggle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert any(c.value.startswith(":material/toggle_off: Exclusion check is off.")
               and "Enable Exclusion check" in c.value for c in at.caption)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_client_setup_page.py -q -k "suggestion or next_step or empty_state"`
Expected: 3 failures (no suggestion text, no `:material/` prefix).

- [ ] **Step 3: Implement**

Change the import to `from core.errors import render_error, render_problem` and add `render_empty_state` to the `core.ui_components` import.

In `_render_sources_section`:

```python
    if not st.session_state[section_key]:
        render_empty_state(f"No {label} sources configured yet.",
                           f"Click **➕ Add {label} Source** below to create one.")
```

Each "enabled but no sources" warning, shown here for TAL; do the same for Exclusion, Suppression, and Dedupe list (label `"Dedupe List"` for the button):

```python
                render_problem("TAL is enabled but no sources are configured — this check will do nothing.",
                               "Click **➕ Add TAL Source** above, or untick **Enable TAL check**.",
                               level="warning")
```

Each check's disabled caption, shown here for Exclusion. TAL, Suppression and Dedupe get the same treatment with their own checkbox label. Where Complex Account's caption is `"Complex Account rules are disabled for this client."`, use toggle `"This is a complex account"`:

```python
            render_empty_state("Exclusion check is off.", "Tick **Enable Exclusion check** above to configure it.",
                               icon="toggle_off")
```

Save validation, keeping each original message verbatim:

```python
    if not client_name:
        render_problem("Client name is required.", "Enter one in **Basics → Client name**.")
    elif _client_name_invalid_chars or ".." in client_name:
        render_problem("Client name can't contain a slash, a backslash, or \"..\" — these would break "
                       "how the profile is saved to disk.", "Remove those characters from **Basics → Client name**.")
    elif leadcap_enabled and leadcap_segmented and leadcap_blank_cap_segments:
        render_problem("Leadcap segments are missing a cap: " + ", ".join(leadcap_blank_cap_segments) + ".",
                       "Open **Checks → Leadcap** and fill in a cap for every segment (required after using "
                       "'Detect CIDs from Accumulated Report', which leaves caps blank).")
    elif lead_template_multi_tab and _blank_tab_count:
        render_problem(f"{_blank_tab_count} Lead Template tab(s) are missing a sheet name.",
                       "Open **Delivery → Client Mode** and pick a sheet for every tab.")
    elif _name_error:
        render_problem(_name_error, "Give every source in that check a non-empty, unique name.")
```

Profile-load failure, keeping the `st.stop()`:

```python
        render_problem(f"Could not load the profile for '{selected_name}' — it may be in an older format, or the "
                       f"file may have been mid-write on another machine. (Technical detail: {exc})",
                       "Try again in a moment. If it keeps happening, delete and re-create it in Client Setup.")
        st.stop()
```

Then run `grep -n "st.error\|st.warning" pages/1_Client_Setup.py`. Everything left should be on the out-of-scope list above.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_client_setup_page.py -q` then `python -m pytest -q`
Expected: all green, no existing test edited.

- [ ] **Step 5: Commit**

```bash
git add pages/1_Client_Setup.py tests/test_client_setup_page.py
git commit -m "Route Client Setup errors, warnings, and empty states through shared helpers"
```

---

## Self-Review Notes

- **Spec coverage:**
  - §1 status chips: Task 1.
  - §2 empty states: Task 2 (used in Task 6).
  - §2 errors/warnings: Task 3 (used in Task 6).
  - §2 save-action spinner: Task 5.
  - §4 tab consolidation: Task 4.
  - §4 check-tab chips and summary strip: Task 5.
  - §1 cards with icon + title: every section in Task 4 becomes its own `st.container(border=True)` + `st.subheader`. Material icons appear on the new card titles. Swapping the remaining emoji in Client Setup's existing buttons and subheaders (e.g. `📂 Browse...`, `💾 Save`, `🗑️ Remove`) is left for later on purpose: `"Save Client Profile" in b.label` is substring-safe, but other tests match exact labels like `"➕ Add Exclusion Source"`.
  - Loading states beyond Save: not needed on this page, since Convertr/Enhancio calls already have spinners.
- **Departures from the spec:**
  - Box Tracker, Convertr, Enhancio and Integrate go in Delivery, and File Collation stays in Basics. The spec doesn't mention any of them. They sit in the Complex Account card today, which was a bigger inconsistency than the one the spec describes.
  - Check tab chips show *saved* state. Streamlit can't relabel a tab after its contents render. The strip shows live state.
- **Placeholder scan:** every step has real code or an exact command. The only conditional wording is the three flagged fallbacks: `Alert.icon`, nested tabs, and badge markup in tab labels. Each has a concrete alternative.
- **Type consistency:**
  - `ChipState` values (`"on"`, `"off"`, `"configured"`, `"needs_setup"`) match across `chip_markdown`, `chip_state`, `render_status_strip` and every Task 5 call.
  - `render_problem(message, suggestion="", level="error")` matches between Task 3 and every Task 6 call site.
  - `render_empty_state(message, hint="", icon="inbox")` matches between Task 2 and Task 6.
- **Test preservation strategy:** layout-only changes are safe because every existing test looks widgets up by label or key, never by position. The only position-dependent behaviour is "first radio labeled Mode", which Task 4 guards with a test. Generic-label collisions are pre-checked in Task 4 Step 1. The rule is the same as Phase 1's: if an existing test has to change, the design is wrong, not the test.

### Critical Files for Implementation
- `pages/1_Client_Setup.py`
- `tests/test_client_setup_page.py`
- `core/errors.py`
- `core/ui_components.py` (new)
- `tests/test_ui_components.py` (new)

Three things can only be confirmed by running the code, each with a fallback named in its own task step:
- whether AppTest exposes an alert's `.icon` (Task 3);
- whether nested `st.tabs` are supported (Task 4);
- whether a tab label renders badge markup or shows it as literal text (Task 5).

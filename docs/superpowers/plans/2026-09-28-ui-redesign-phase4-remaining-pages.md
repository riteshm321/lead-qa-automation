# UI Redesign Phase 4: Remaining Pages Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the foundation elements from Phases 1-3 to the 7 remaining pages: Settings, Activity Log, Box Tracker, Fuzzy Match, Convertr, Enhancio and Integrate (spec §Rollout item 4). The elements are:
- Material Symbols instead of in-page emoji;
- icon-titled bordered cards;
- status chips where they help;
- `render_empty_state` instead of bare "nothing here" captions;
- `render_problem` instead of ad hoc `st.error`/`st.warning`.

This plan also finishes the Client Setup message sweep that Phase 2's Task 6 deferred to "the Phase 4 sweep".

**Architecture:**
- **One new shared helper.** `setup_state` goes in `core/ui_components.py`: a config item is "configured" or, when missing, "needs setup" (required) or "off" (optional). Four pages use it.
- **Otherwise, only existing components.** Everything else reuses what's already shipped: `render_status_strip`, `render_empty_state` and `render_metric_cards` in `core/ui_components.py`, and `render_problem` in `core/errors.py`.
- **One regression guard.** A new source-scan test, `tests/test_page_icons.py`, stops a swept page from being re-emoji'd.
- **Visual changes only.** No business logic, write path, widget label or widget key changes, apart from the three emoji-only label edits listed in Global Constraints.
- **No restructuring.** No new tabs, steppers or other layouts. Existing numbered sections become bordered cards; nothing else moves.

**Tech Stack:** Python and Streamlit 1.61.1, with no new dependency. It uses:
- `st.expander(..., icon=)`, `st.button(..., icon=)`, `st.download_button(..., icon=)`;
- `st.metric(icon=, border=True)` via `render_metric_cards`;
- `:color-badge[...]` markdown via `render_status_strip`;
- `:material/name:`.

Tests use pytest + `streamlit.testing.v1.AppTest`.

## Global Constraints

- **Baseline is `master` at `771422f`.** Line numbers below are "currently line N" at that commit. Every edit is anchored on the quoted text, not the number.
- **Existing tests must not change.** Each page's own test file is the backward-compatibility proof. If an existing test needs editing to pass, the change is wrong: stop and flag it. Don't patch the test.
- **Widget labels and keys stay byte-identical.**
  - Add icons with the `icon=` parameter. It doesn't change `.label`.
  - Only three labels change, and only by dropping a leading emoji. No test matches any of them by label (checked in each task's pre-flight):

    | Page | Old label | New label | Tests find it by |
    |---|---|---|---|
    | Settings | `"📂 Browse..."` | `"Browse..."` | `key="clients_dir_browse"` |
    | Convertr/Enhancio | `f"📋 Post to {key}"` | `f"Post to {key}"` | `key="convertr_jira_post"` / `key="enhancio_jira_post"` |
    | Convertr/Enhancio | `"⬇️ Download these leads (.xlsx)"` | `"Download these leads (.xlsx)"` | `key` |

  - The upload pages' metric labels (`"✅ Uploaded"` etc.) also lose their emoji. They're display labels, not widgets, and no test asserts on them.
- **These emoji stay, and `tests/test_page_icons.py` allows exactly them:**
  - Result-column cell values (`"✅ Lead ID ..."`, `"❌ ..."`, `"⏭️ Skipped ..."`) and the `.str.startswith("✅"/"❌"/"⏭️")` counts over them. They're data inside `st.dataframe`, where Material shorthand doesn't render, and tests assert the prefixes.
  - The `f"📋 Preview leads to send ..."` expander label in `pages/7_Convertr.py` and `pages/8_Enhancio.py`. `tests/test_convertr_page.py:206` and `tests/test_enhancio_page.py:492` match it with `.startswith("📋 Preview leads to send")`.
- **Message rule** (same as Phase 2 Task 6):
  - Every existing error/warning/caption text stays a substring of the new `.value`.
  - Suggestions are only ever *appended* through `render_problem`'s `suggestion`.
  - The one allowed text change is dropping a *decorative* emoji: a leading `"⚠️ "`/`"❌ "` (the shared helper's `icon=` replaces it) or a mid-sentence `"⚙️ "`/`"🔗 "` that referred to the pre-Phase-1 sidebar icons.
  - One deliberate exception: the Jira-account message on Convertr and Enhancio points at the wrong page. It's corrected in Tasks 5 and 6, and no test pins it.
- **Cards:** a bordered `st.container(border=True)` whose first line is `st.subheader(":material/<icon>: <existing title>")`. Wrap a page's *existing* numbered sections. Don't invent new groupings. Settings already uses one expander per settings group, so it gets no extra wrapper.
- **Order of edits inside a task:**
  1. First, every text-anchored edit, done at the file's *current* indentation, exactly as shown.
  2. Last, the task's card-wrap script, which re-indents each section body by 4 spaces.
  3. Then run `git diff -w <page>`. It must show only the listed text changes plus the card-opener lines. `-w` hides the re-indentation.
- **Out of scope, left alone on purpose:**
  - `core/toast.py`'s `icon="✅"` (pinned by `tests/test_toast.py:27`);
  - `core/branding.py`'s sidebar `👤`/`💼`/`⚠️` captions (page chrome, Phase 1's area);
  - `Summary.py`;
  - Run Check;
  - Client Setup's emoji *button labels*, several of which are exact-text-tested (e.g. `"➕ Add Exclusion Source"`);
  - every `st.info`/`st.success` call. `render_problem` is error/warning only. The one exception is Enhancio's "No leads in the Accumulated Report between ..." `st.info`, which becomes an empty state in Task 6.
- **Business logic:** don't change `core/` logic, profile JSON or any write path. The only `core/` edit is the additive `setup_state` in Task 1.
- **Test runs:** run the page's own test file and `tests/test_page_icons.py` after each task. Run `python -m pytest -q` before calling the plan done.
- Direct commits to `master`, one commit per task.

---

### Task 1: `setup_state` chip helper (`core/ui_components.py`)

**Files:**
- Modify: `core/ui_components.py`
- Test: `tests/test_ui_components.py`

**Interfaces:**
- `setup_state(configured: bool, required: bool = True) -> ChipState`
  - Returns `"configured"` when `configured` is true.
  - Otherwise returns `"needs_setup"` if `required`, else `"off"`.
  - It's the credential/config counterpart to `chip_state`, which describes an on/off *feature*. Settings, Convertr, Enhancio and Integrate all build their strips from it.

- [ ] **Step 1: Write the failing test** (append to `tests/test_ui_components.py`)

```python
def test_setup_state_mapping():
    from core.ui_components import setup_state
    assert setup_state(True) == "configured"
    assert setup_state(True, required=False) == "configured"
    assert setup_state(False) == "needs_setup"
    assert setup_state(False, required=False) == "off"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_ui_components.py -q -k setup_state`
Expected: FAIL with `ImportError: cannot import name 'setup_state'`.

- [ ] **Step 3: Implement** (in `core/ui_components.py`, directly below `chip_state`)

```python
def setup_state(configured: bool, required: bool = True) -> ChipState:
    """A credential/config item (not an on/off feature -- see chip_state):
    "configured" when it's set; when it's missing, "needs_setup" if the page
    can't do its job without it, or just "off" if it's optional."""
    if configured:
        return "configured"
    return "needs_setup" if required else "off"
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_ui_components.py -q`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add core/ui_components.py tests/test_ui_components.py
git commit -m "Add shared setup_state chip helper for configured/needs-setup items"
```

---

### Task 2: Settings (`pages/3_Settings.py`)

**Files:**
- Modify: `pages/3_Settings.py`
- Create: `tests/test_page_icons.py`
- Test: `tests/test_settings_page.py` (append only)

**Scope:**
- **Emoji:** the title, 7 expander labels, the Browse button, and two "🔗 X page" captions.
- **Status strip:** one strip under the page caption showing which credentials are set.
- **Errors/warnings:** 4 `st.error` calls and 1 `st.warning` go through `render_problem`.
- **Empty state:** the Time Saved caption uses `render_empty_state`.
- **No cards.** Each group already sits in its own expander.

- [ ] **Step 1: Pre-flight (no code yet).** Run:

```bash
grep -n "at\.\(error\|warning\|caption\|expander\|title\|markdown\)\|len(at\.\|b.label ==\|in b.label" tests/test_settings_page.py
```

Expected hits, and what each one pins:
- lines 107-108 and 124-125: `len(at.error) == 1` plus the substrings `"required"`/`"OneDrive"`. The new code must still emit exactly one error.
- line 249: markdown `"test-admin"` + `"2 process"`.
- lines 250-251: captions `"1 Lead QA, 1 Complex Account"` / `"Activity Log"`.
- line 294: warning containing `"Remove"` + `"bob"`.
- lines 172 and 182: button labels `"Save Integrate credentials"` / `"Save Google Sheets key path"`, which stay unchanged.

Nothing may assert on the title, the expander labels, or `"📂 Browse..."`. If anything does, stop and flag it.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_page_icons.py`:

```python
"""Source-level guard: swept pages carry no decorative emoji.

Streamlit silently renders an unknown :material/name: as a blank gap, and
AppTest can't see most icons, so a plain source scan is the regression
check that a later edit doesn't quietly re-emoji a page -- same approach as
tests/test_branding.py's sidebar-nav check."""
import re
from pathlib import Path

import pytest

_PAGES_DIR = Path(__file__).resolve().parent.parent / "pages"

# Pictographs, misc symbols/dingbats, and U+FE0F (the variation selector
# that turns a text glyph like "ℹ" into an emoji "ℹ️"). Deliberately NOT the
# arrows block: "→" is ordinary punctuation in this app's copy.
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿️]")

# Emoji that are data or exact-text-tested, not decoration:
# - Result-column cells on the upload pages, and the .str.startswith(...)
#   counts over them: Material shorthand doesn't render inside st.dataframe,
#   and tests assert the ✅/❌/⏭️ prefixes.
# - The "📋 Preview leads to send" expander label, which
#   tests/test_convertr_page.py and tests/test_enhancio_page.py match with
#   .startswith("📋 Preview leads to send").
_ALLOWED_LINE = re.compile(r'"Result"|\.str\.startswith\(|📋 Preview leads to send')

SWEPT_PAGES = [
    "3_Settings.py",
]


@pytest.mark.parametrize("page", SWEPT_PAGES)
def test_swept_page_has_no_decorative_emoji(page):
    lines = (_PAGES_DIR / page).read_text(encoding="utf-8").splitlines()
    offenders = [
        f"{page}:{n}: {line.strip()}"
        for n, line in enumerate(lines, start=1)
        if _EMOJI.search(line) and not _ALLOWED_LINE.search(line)
    ]
    assert offenders == []
```

Append to `tests/test_settings_page.py`:

```python
def test_settings_uses_material_icons_instead_of_emoji(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert at.title[0].value == ":material/settings: Settings"
    assert {e.label: e.icon for e in at.expander} == {
        "Shared team data location": ":material/folder_shared:",
        "Jira account (private to this machine)": ":material/key:",
        "Enhancio Client ID (private to this machine)": ":material/key:",
        "Integrate API credentials (private to this machine)": ":material/key:",
        "Google Sheets service account (private to this machine)": ":material/key:",
        "Manage user accounts (admin only)": ":material/manage_accounts:",
        "Time saved tracking (admin only)": ":material/timer:",
    }
    browse = at.button(key="clients_dir_browse")
    assert browse.label == "Browse..."
    assert browse.proto.icon == ":material/folder_open:"


def test_settings_status_strip_shows_what_is_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_enhancio_client_id
    save_enhancio_client_id("CID123")

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    strip = next(m.value for m in at.markdown if "badge[Shared folder" in m.value)
    assert ":orange-badge[Shared folder ⚠ Needs setup]" in strip  # required, not set yet
    assert ":blue-badge[Enhancio ✓ Configured]" in strip
    assert ":gray-badge[Jira ○ Off]" in strip  # optional, not set
    assert ":gray-badge[Integrate ○ Off]" in strip
    assert ":gray-badge[Google Sheets ○ Off]" in strip


def test_settings_problems_and_empty_states_use_the_shared_helpers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert any(c.value.startswith(":material/timer: No client processes completed yet.") for c in at.caption)

    at.button(key="clients_dir_save").click().run()
    assert not at.exception
    assert len(at.error) == 1
    assert at.error[0].icon == ":material/error:"
    assert "A shared team data folder is required" in at.error[0].value
    assert "**Suggested fix:**" in at.error[0].value
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_page_icons.py tests/test_settings_page.py -q -k "emoji or material or status_strip or shared_helpers"`
Expected: 4 failures.
- The guard lists 13 offending lines.
- The title is `"⚙️ Settings"`.
- `StopIteration` is raised for the strip.
- The caption has no `:material/timer:` prefix.

- [ ] **Step 4: Implement** (text-anchored edits; there's no card script on this page)

4a. Imports. After `from core.branding import configure_page`, add:

```python
from core.errors import render_problem
```

After `from core.toast import queue_toast_before_rerun, show_pending_toast`, add:

```python
from core.ui_components import render_empty_state, render_status_strip, setup_state
```

4b. Title plus strip. Replace

```python
st.title("⚙️ Settings")
st.caption("App-wide settings, set up once — not tied to any specific client.")
```

with

```python
st.title(":material/settings: Settings")
st.caption("App-wide settings, set up once — not tied to any specific client.")
# Saved state, not live input -- every Save button on this page reruns, so
# this row catches up the moment anything below is saved.
_jira_now = get_jira_settings()
_integrate_key_now, _integrate_secret_now = get_integrate_credentials()
render_status_strip([
    ("Shared folder", setup_state(bool(get_shared_root_dir()))),
    ("Jira", setup_state(all(_jira_now.values()), required=False)),
    ("Enhancio", setup_state(bool(get_enhancio_client_id()), required=False)),
    ("Integrate", setup_state(bool(_integrate_key_now and _integrate_secret_now), required=False)),
    ("Google Sheets", setup_state(bool(get_google_sheets_key_path()), required=False)),
])
```

4c. Expanders. Replace each opener line: move the emoji into `icon=` and keep the rest of the label verbatim.

| Currently line | Before | After |
|---|---|---|
| 24 | `with st.expander("⚙️ Shared team data location", expanded=False):` | `with st.expander("Shared team data location", expanded=False, icon=":material/folder_shared:"):` |
| 90 | `with st.expander("🔑 Jira account (private to this machine)", expanded=False):` | `with st.expander("Jira account (private to this machine)", expanded=False, icon=":material/key:"):` |
| 110 | `with st.expander("🔑 Enhancio Client ID (private to this machine)", expanded=False):` | `with st.expander("Enhancio Client ID (private to this machine)", expanded=False, icon=":material/key:"):` |
| 127 | `with st.expander("🔑 Integrate API credentials (private to this machine)", expanded=False):` | `with st.expander("Integrate API credentials (private to this machine)", expanded=False, icon=":material/key:"):` |
| 144 | `with st.expander("🔑 Google Sheets service account (private to this machine)", expanded=False):` | `with st.expander("Google Sheets service account (private to this machine)", expanded=False, icon=":material/key:"):` |
| 160 | `    with st.expander("👤 Manage user accounts (admin only)", expanded=False):` | `    with st.expander("Manage user accounts (admin only)", expanded=False, icon=":material/manage_accounts:"):` |
| 232 | `    with st.expander("⏱️ Time saved tracking (admin only)", expanded=False):` | `    with st.expander("Time saved tracking (admin only)", expanded=False, icon=":material/timer:"):` |

4d. Browse button (line 55):

```python
        if st.button("📂 Browse...", key="clients_dir_browse", use_container_width=True):
```
→
```python
        if st.button("Browse...", key="clients_dir_browse", icon=":material/folder_open:", use_container_width=True):
```

4e. Remove the stale nav-emoji references in two captions:
- Line 112: `"Used by the 🔗 Enhancio page and by Client Setup's ...` → `"Used by the **Enhancio** page and by Client Setup's ...`
- Line 129: `"Used by the 🔗 Integrate page. One shared API Key/Secret ...` → `"Used by the **Integrate** page. One shared API Key/Secret ...`

The rest of each string stays as it is.

4f. Shared-folder save errors (lines 67-74):

```python
        if not new_root:
            st.error("A shared team data folder is required — this can no longer be left blank.")
        elif not is_onedrive_synced_path(new_root):
            st.error(
                "That folder doesn't look like it's inside a OneDrive-synced folder on this machine. "
                "Pick a folder inside your synced OneDrive (or a synced SharePoint team library) so "
                "your colleagues can access the same data."
            )
```
→
```python
        if not new_root:
            render_problem("A shared team data folder is required — this can no longer be left blank.",
                           "Click **Browse...** and pick a folder inside your synced OneDrive.")
        elif not is_onedrive_synced_path(new_root):
            # Kept verbatim with no separate suggestion -- the message already ends with the fix.
            render_problem(
                "That folder doesn't look like it's inside a OneDrive-synced folder on this machine. "
                "Pick a folder inside your synced OneDrive (or a synced SharePoint team library) so "
                "your colleagues can access the same data."
            )
```

4g. Add-account errors (lines 176-179):

```python
            if not _new_username or not _new_password:
                st.error("Username and password are required.")
            elif _new_username in load_users():
                st.error("That username already exists.")
```
→
```python
            if not _new_username or not _new_password:
                render_problem("Username and password are required.",
                               "Fill in both fields above, then click **Add account** again.")
            elif _new_username in load_users():
                render_problem("That username already exists.",
                               "Pick a different username, or edit that account under **Existing accounts** below.")
```

4h. Remove-confirmation warning (line 202):

```python
                    st.warning(f"⚠️ Remove **{_username}**'s account? This can't be undone.")
```
→
```python
                    render_problem(f"Remove **{_username}**'s account? This can't be undone.", level="warning")
```

4i. Time-saved empty state (line 242):

```python
            st.caption("No client processes completed yet.")
```
→
```python
            render_empty_state("No client processes completed yet.",
                               "Every successful Finalize/Confirm & Write on Run Check is counted here.",
                               icon="timer")
```

- [ ] **Step 5: Verify the diff**

Run: `git diff -w pages/3_Settings.py`
Expected, and nothing else:
- 2 import lines;
- the title and strip block;
- 7 expander openers;
- the Browse line;
- 2 caption lines;
- 4 `render_problem` error call sites and 1 warning;
- 1 `render_empty_state`.

Then run `grep -n "st\.error\|st\.warning" pages/3_Settings.py`. Expected: no output.

- [ ] **Step 6: Run to verify everything passes**

Run: `python -m pytest tests/test_settings_page.py tests/test_page_icons.py -q`
Expected: 17 + 1 passed, **with no edits to existing tests**.

- [ ] **Step 7: Manual smoke check.** Run `streamlit run Summary.py` and open Settings. Check:
- every expander shows a real line icon, not a blank gap (a blank means a mistyped `:material/` name);
- the strip renders as coloured pills;
- after saving a Jira account, the Jira pill turns blue;
- the dark theme looks right.

- [ ] **Step 8: Commit**

```bash
git add pages/3_Settings.py tests/test_settings_page.py tests/test_page_icons.py
git commit -m "Apply Material icons, a credentials status strip, and shared problem/empty-state helpers to Settings"
```

---

### Task 3: Activity Log and Fuzzy Match (two small pages)

**Files:**
- Modify: `pages/4_Activity_Log.py`, `pages/6_Fuzzy_Match.py`
- Test: `tests/test_activity_log_page.py`, `tests/test_fuzzy_match_page.py` (append only), `tests/test_page_icons.py`

**Scope:**
- **Activity Log:**
  - the title emoji;
  - the non-admin warning goes through `render_problem`;
  - two empty-state captions;
  - "Process log" and "Per-user totals" become cards. The `st.divider()` between them goes, because the card borders separate them.
- **Fuzzy Match:**
  - the title emoji;
  - the column pickers and Run button become one "Compare columns" card;
  - a new empty state when no file is uploaded yet (the page renders nothing below the uploader today).
- **No status chips.** Neither page has configurable state to summarise.

- [ ] **Step 1: Pre-flight.** Run:

```bash
grep -n "at\.\|len(" tests/test_activity_log_page.py tests/test_fuzzy_match_page.py
```

Expected pins:
- `at.selectbox[0]` and `at.dataframe[0]` are positional. Add no selectbox or dataframe before them.
- `len(at.warning) == 1` and `len(at.dataframe) == 0` for a non-admin.
- The caption substring `"No client processes completed yet"`.
- `not any("**bob**" in m.value for m in at.markdown)`. Add no markdown containing a bold username.
- `at.file_uploader[0]`.

- [ ] **Step 2: Write the failing tests**

In `tests/test_page_icons.py`, extend the list to:

```python
SWEPT_PAGES = [
    "3_Settings.py",
    "4_Activity_Log.py",
    "6_Fuzzy_Match.py",
]
```

Append to `tests/test_activity_log_page.py`:

```python
def test_activity_log_title_icon_and_empty_state(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert at.title[0].value == ":material/bar_chart: Activity Log"
    assert any(c.value.startswith(":material/history: No client processes completed yet.") for c in at.caption)


def test_activity_log_sections_are_icon_titled_cards(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    from core.activity_tracker import record_process_completed
    record_process_completed("alice", "Acme", 3.0, is_complex_account=False)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert [s.value for s in at.subheader] == [
        ":material/list_alt: Process log", ":material/groups: Per-user totals"]


def test_non_admin_warning_uses_the_shared_problem_helper(tmp_path, monkeypatch):
    from core import auth_gate
    monkeypatch.setattr(
        auth_gate, "require_login",
        lambda: {"username": "regular-user", "is_admin": False, "role": ""},
    )
    _configure_shared_root(tmp_path, monkeypatch)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert at.warning[0].icon == ":material/warning:"
    assert "This page is only available to admins." in at.warning[0].value
    assert "**Suggested fix:**" in at.warning[0].value
```

Append to `tests/test_fuzzy_match_page.py`. Add `import pandas as pd` to its imports.

```python
def test_fuzzy_match_title_icon_and_empty_state(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert at.title[0].value == ":material/search: Fuzzy Match"
    assert any(c.value == ":material/upload_file: No file uploaded yet. — Upload an .xlsx or .csv above "
               "to compare two of its columns." for c in at.caption)


def test_uploaded_file_shows_column_pickers_in_an_icon_titled_card(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    csv_bytes = pd.DataFrame([{"Job Title": "CTO", "LinkedIn Job Title": "Chief Technology Officer"}]).to_csv(
        index=False).encode("utf-8")
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.get("file_uploader")[0].set_value(("titles.csv", csv_bytes, "text/csv")).run()
    assert not at.exception
    assert ":material/compare_arrows: Compare columns" in [s.value for s in at.subheader]
    assert not any("No file uploaded yet" in c.value for c in at.caption)
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_page_icons.py tests/test_activity_log_page.py tests/test_fuzzy_match_page.py -q`
Expected failures:
- 2 guard cases;
- 3 Activity Log tests (emoji title, plain subheaders, no suggestion);
- 2 Fuzzy Match tests (emoji title, no empty-state caption, no subheader).

The 5 existing tests pass.

- [ ] **Step 4: Implement**

4a. Replace `pages/4_Activity_Log.py` in full. Everything from `_usernames = ...` through the `_rows.append(...)` loop is unchanged. The only other changes are the title, the helper calls and the two cards.

```python
import pandas as pd
import streamlit as st

from core.activity_tracker import load_all_activity, get_user_stats, format_minutes
from core.branding import configure_page
from core.errors import render_problem
from core.ui_components import render_empty_state

_current_user = configure_page("Activity Log")
st.title(":material/bar_chart: Activity Log")

if not _current_user["is_admin"]:
    render_problem("This page is only available to admins.",
                   "Ask an admin to open it for you.", level="warning")
    st.stop()

st.caption(
    "Every completed client process (Finalize/Confirm & Write), across every user, with the real "
    "measured automated time -- the same data behind the sidebar's Time Saved card."
)

_activity = load_all_activity()
if not _activity:
    render_empty_state("No client processes completed yet.",
                       "Every successful Finalize/Confirm & Write on Run Check is logged here.", icon="history")
    st.stop()

_usernames = sorted(_activity.keys())
_selected_user = st.selectbox("Filter by user", ["All users"] + _usernames)

_rows = []
for _username, _record in _activity.items():
    if _selected_user != "All users" and _username != _selected_user:
        continue
    for _entry in _record.get("log", []):
        _timestamp = _entry.get("timestamp", "")
        _date, _, _time = _timestamp.partition("T")
        _automated = _entry.get("automated_minutes", 0.0)
        _manual = _entry.get("manual_minutes", 0.0)
        _rows.append({
            "User": _username,
            "Client": _entry.get("client", "—"),
            "Date": _date or "—",
            "Time": _time or "—",
            "Automated": format_minutes(_automated),
            "Manual": format_minutes(_manual),
            "Saved": format_minutes(_manual - _automated),
            "Complex Account": "Yes" if _entry.get("is_complex_account") else "",
            "_sort_key": _timestamp,
        })

with st.container(border=True):
    st.subheader(":material/list_alt: Process log")
    if not _rows:
        render_empty_state(
            "No logged processes yet for this filter.",
            "Processes completed before per-client logging existed won't have individual entries here "
            "(see the per-user totals below instead).",
            icon="filter_list_off",
        )
    else:
        _log_df = pd.DataFrame(sorted(_rows, key=lambda r: r["_sort_key"], reverse=True)).drop(columns=["_sort_key"])
        st.dataframe(_log_df, hide_index=True, width="stretch")

with st.container(border=True):
    st.subheader(":material/groups: Per-user totals")
    for _username, _record in sorted(_activity.items()):
        if _selected_user != "All users" and _username != _selected_user:
            continue
        _stats = get_user_stats(_record)
        _count = _record.get("process_count", 0)
        st.markdown(
            f"**{_username}** — {_count} process(es), {format_minutes(_stats['total_saved_minutes'])} saved "
            f"(last: {_record.get('last_updated', '—')})"
        )
        st.caption(
            f"Avg {format_minutes(_stats['avg_automated_minutes'])}/process · "
            f"{_stats['plain_count']} Lead QA, {_stats['complex_account_count']} Complex Account · "
            f"{_stats['distinct_clients']} distinct client(s)"
        )
```

4b. Replace `pages/6_Fuzzy_Match.py` in full. The comparison logic, the `st.success` text and the download button are unchanged.

```python
# pages/6_Fuzzy_Match.py
import tempfile
from pathlib import Path

import streamlit as st

from core.branding import configure_page
from core.errors import render_error
from core.excel_io import read_leadfile
from core.fuzzy_match import compare_columns, apply_match_column_colors, MATCH_COLUMN
from core.ui_components import render_empty_state

_current_user = configure_page("Fuzzy Match")
st.title(":material/search: Fuzzy Match")
st.caption(
    "Scores how closely two columns in the same file match (e.g. the leadfile's own Job Title "
    "against a LinkedIn-derived Job Title), so you can review weak matches before sending the file "
    "to the client. Not tied to a specific client — usable for anyone."
)

uploaded = st.file_uploader("File to check", type=["xlsx", "csv"])

if uploaded:
    try:
        df = read_leadfile(uploaded)
    except Exception as exc:
        render_error(exc)
        st.stop()

    with st.container(border=True):
        st.subheader(":material/compare_arrows: Compare columns")
        headers = list(df.columns)
        col_a, col_b = st.columns(2)
        column_a = col_a.selectbox("Column A (e.g. Job Title)", headers, index=0)
        column_b = col_b.selectbox("Column B (e.g. LinkedIn Job Title)", headers, index=min(1, len(headers) - 1))

        if st.button("Run comparison", type="primary"):
            result_df = compare_columns(df, column_a, column_b)

            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = str(Path(tmp_dir) / "fuzzy_match_output.xlsx")
                result_df.to_excel(tmp_path, index=False)
                apply_match_column_colors(tmp_path)
                output_bytes = Path(tmp_path).read_bytes()

            st.session_state["fuzzy_match_output"] = output_bytes
            st.success(f"Compared {len(result_df)} row(s). Green ≥90%, yellow ≥75%, red below.")
            st.dataframe(result_df[[column_a, column_b, MATCH_COLUMN]], hide_index=True)
else:
    render_empty_state("No file uploaded yet.", "Upload an .xlsx or .csv above to compare two of its columns.",
                       icon="upload_file")

if st.session_state.get("fuzzy_match_output"):
    st.download_button(
        "Download result",
        data=st.session_state["fuzzy_match_output"],
        file_name="fuzzy_match_output.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
```

- [ ] **Step 5: Verify the diffs**

Run: `git diff -w pages/4_Activity_Log.py pages/6_Fuzzy_Match.py`
Expected, and nothing else:
- **Activity Log:** 2 imports, the title, the `render_problem` call, 2 `render_empty_state` calls, 2 card openers with icon subheaders, and the removed `st.divider()`/plain `st.subheader` lines.
- **Fuzzy Match:** 1 import, the title, 1 card opener with its subheader, and the `else:` empty state.

- [ ] **Step 6: Run to verify everything passes**

Run: `python -m pytest tests/test_activity_log_page.py tests/test_fuzzy_match_page.py tests/test_page_icons.py -q`
Expected: 7 + 3 + 3 passed, with no edits to existing tests.

- [ ] **Step 7: Manual smoke check.** Open both pages in light and dark theme. Check:
- the icons render;
- both Activity Log cards are bordered;
- the Fuzzy Match card appears after uploading a real `.xlsx`.

- [ ] **Step 8: Commit**

```bash
git add pages/4_Activity_Log.py pages/6_Fuzzy_Match.py tests/test_activity_log_page.py tests/test_fuzzy_match_page.py tests/test_page_icons.py
git commit -m "Apply Material icons, cards, and shared empty/problem helpers to Activity Log and Fuzzy Match"
```

---

### Task 4: Box Tracker (`pages/5_Box_Tracker.py`)

**Files:**
- Modify: `pages/5_Box_Tracker.py`
- Test: `tests/test_box_tracker_page.py` (append only), `tests/test_page_icons.py`

**Scope:**
- **Emoji:** the title, 3 `ℹ️ How this works` expanders, the `✋` expander, and 4 `⚠️`-prefixed warnings.
- **Cards:** the 3 numbered steps each become an icon-titled card.
- **Errors/warnings:** 10 `st.warning` calls and 1 `st.error` go through `render_problem`.
- **Empty states:** 3 captions use `render_empty_state`.
- **No status chips.** The page already hard-stops when the client isn't set up, so there's nothing left to summarise.

- [ ] **Step 1: Pre-flight.** Run:

```bash
grep -n "at\.\(error\|warning\|caption\|expander\|subheader\|title\)\|len(at\." tests/test_box_tracker_page.py
```

Expected pins, all substring checks:
- `"118741"` + `"short"` in a warning;
- no `"shortfall"`/`"short by"` warning for an uncapped campaign;
- `"118741"` in a warning (missing template);
- `"Extra Client Tracking Column"` in a warning;
- `"lead1@x.com"` in an error.

There are no count or positional assertions on alerts, captions, expanders or subheaders. Checkbox labels (`"Mark ..."`, `"Clear ..."`, `"Reject ..."`), button labels and keys aren't touched.

- [ ] **Step 2: Write the failing tests**

Add `"5_Box_Tracker.py",` to `SWEPT_PAGES` in `tests/test_page_icons.py`.

Append to `tests/test_box_tracker_page.py`:

```python
def test_box_tracker_steps_are_icon_titled_cards_with_shared_empty_states(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    # One already-finished lead: not blank, not sent, not cleared -- so all
    # three step lists are empty and each shows its empty state.
    _make_accumulated(acc_path, [
        {"Email": "done@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741",
         "Status": "Accepted - Uploaded 01-Sep"},
    ])
    _make_mirror(mirror_path)
    _save_profile(acc_path, mirror_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert at.title[0].value == ":material/inventory_2: Box Tracker"
    assert [s.value for s in at.subheader] == [
        ":material/outgoing_mail: 1. Send leads for approval",
        ":material/edit_document: 2. Write cleared leads to the Lead Template",
        ":material/fact_check: 3. Reconcile portal upload status",
    ]
    expanders = [(e.label, e.icon) for e in at.expander]
    assert expanders.count(("How this works", ":material/info:")) == 3
    assert ("Or: I already added these leads to the real Approval Sheet myself", ":material/back_hand:") in expanders
    captions = [c.value for c in at.caption]
    assert any(c.startswith(":material/task_alt: No blank-Status leads available to mark.") for c in captions)
    assert any(c.startswith(':material/inbox: No leads currently marked "Sent for Approval" or') for c in captions)
    assert any(c.startswith(':material/inbox: No leads currently marked "Cleared for Upload".') for c in captions)


def test_missing_rejection_reason_error_uses_the_shared_problem_helper(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "lead1@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741",
         "Status": "Cleared for Upload - 07-Sep"},
    ])
    _make_mirror(mirror_path)
    _save_profile(acc_path, mirror_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(cb for cb in at.checkbox if cb.label == "Reject lead1@x.com").set_value(True).run()
    at.button(key="reconcile_upload_button").click().run()
    assert not at.exception
    err = next(e for e in at.error if "lead1@x.com" in e.value)
    assert err.icon == ":material/error:"
    assert "**Suggested fix:**" in err.value


def test_unfilled_column_warning_uses_the_shared_helper_not_an_emoji_prefix(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "lead1@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741",
         "Status": "Cleared for Upload - 07-Sep"},
    ])
    _make_mirror(mirror_path)
    wb = openpyxl.load_workbook(mirror_path)
    ws = wb["Response Details"]
    ws.cell(row=2, column=ws.max_column + 1, value="Extra Client Tracking Column")
    wb.save(mirror_path)
    _save_profile(acc_path, mirror_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.button(key="reconcile_upload_button").click().run()
    assert not at.exception
    warn = next(w for w in at.warning if "Extra Client Tracking Column" in w.value)
    assert warn.icon == ":material/warning:"
    assert not warn.value.startswith("⚠️")
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_page_icons.py tests/test_box_tracker_page.py -q -k "emoji or icon_titled or shared_problem or shared_helper"`
Expected: 4 failures (the guard lists 10 lines; the emoji title; no suggestion; the `⚠️` prefix).

- [ ] **Step 4: Implement.** Do these text-anchored edits first, then run the card script.

4a. Imports. Change `from core.errors import render_error` to `from core.errors import render_error, render_problem`. After `from core.profile_store import list_profile_names, load_profile`, add `from core.ui_components import render_empty_state`.

4b. Title (line 24): `st.title("📦 Box Tracker")` → `st.title(":material/inventory_2: Box Tracker")`.

4c. Setup guards (lines 91 and 97):

```python
    st.warning(f"Client \"{_IBM_APAC_CLIENT_NAME}\" isn't set up yet. Set it up on the Client Setup page first.")
```
→
```python
    render_problem(f"Client \"{_IBM_APAC_CLIENT_NAME}\" isn't set up yet. Set it up on the Client Setup page first.",
                   level="warning")
```
and
```python
    st.warning("Box Tracker isn't enabled for this client yet. Enable it on the Client Setup page first.")
```
→
```python
    render_problem("Box Tracker isn't enabled for this client yet. Enable it on the Client Setup page first.",
                   "Tick **This client uses a Box Tracker** under Client Setup → Delivery.", level="warning")
```

4d. Expanders. All three occurrences of `with st.expander("ℹ️ How this works"):` (lines 126, 277 and 417) become `with st.expander("How this works", icon=":material/info:"):`. Line 226 becomes:

```python
with st.expander("Or: I already added these leads to the real Approval Sheet myself", icon=":material/back_hand:"):
```

4e. Step 1 messages:

```python
                st.warning("No blank-Status leads matched any mapped CID with a known Pacing Diff — nothing to send.")
```
→
```python
                render_problem("No blank-Status leads matched any mapped CID with a known Pacing Diff — nothing to send.",
                               "Check the CID → campaign mapping under Client Setup → Delivery → Box Tracker covers "
                               "these leads' CIDs.", level="warning")
```

```python
                st.warning(
                    f"⚠️ The {_APPROVAL_SHEET_TAB} tab has column(s) this tool doesn't fill in and left blank: "
                    f"{', '.join(sorted(_approval_unmatched))}. If that's unexpected, the mirror workbook's real "
                    "header text may not match what this page writes."
                )
```
→
```python
                render_problem(
                    f"The {_APPROVAL_SHEET_TAB} tab has column(s) this tool doesn't fill in and left blank: "
                    f"{', '.join(sorted(_approval_unmatched))}. If that's unexpected, the mirror workbook's real "
                    "header text may not match what this page writes.",
                    level="warning",
                )
```

```python
                    st.warning(f"CID {cid} was short by {amount} lead(s) — sent all that were available.")
```
→
```python
                    render_problem(f"CID {cid} was short by {amount} lead(s) — sent all that were available.",
                                   level="warning")
```

```python
        st.caption("No blank-Status leads available to mark.")
```
→
```python
        render_empty_state("No blank-Status leads available to mark.",
                           "Every lead in the Accumulated Report already has a Status.", icon="task_alt")
```

```python
                st.warning("No leads checked — nothing to mark.")
```
→
```python
                render_problem("No leads checked — nothing to mark.", "Tick at least one **Mark ...** box above first.",
                               level="warning")
```

4f. Step 2 messages:

```python
if _awaiting_clearance_df.empty:
    st.caption(f"No leads currently marked \"{_SENT_STATUS_PREFIX}\" or \"{_MANUAL_STATUS_PREFIX}\".")
else:
    st.warning(
        "⚠️ **Any existing leads already in the target Lead Template file are wiped first** — new "
        "leads always start fresh at row 2. Previously this was only mentioned inside the collapsed "
        "\"How this works\" panel above, easy to miss before a destructive write."
    )
```
→
```python
if _awaiting_clearance_df.empty:
    render_empty_state(f"No leads currently marked \"{_SENT_STATUS_PREFIX}\" or \"{_MANUAL_STATUS_PREFIX}\".",
                       "Send leads in step 1, or mark ones you added yourself, first.")
else:
    render_problem(
        "**Any existing leads already in the target Lead Template file are wiped first** — new "
        "leads always start fresh at row 2. Previously this was only mentioned inside the collapsed "
        "\"How this works\" panel above, easy to miss before a destructive write.",
        level="warning",
    )
```

```python
                    st.warning("No leads checked — nothing to write.")
```
→
```python
                    render_problem("No leads checked — nothing to write.",
                                   "Tick at least one **Clear ...** box above first.", level="warning")
```

```python
                    st.warning(
                        "⚠️ These Lead Template columns had no matching Accumulated Report column and were left "
                        f"blank: {', '.join(sorted(unmatched_headers))}. If that data does exist under a different "
                        "column name, rename it (or the Lead Template's header) to something closer and re-run."
                    )
                if missing_template_cids:
                    st.warning(
                        f"No Lead Template path configured for CID(s): {', '.join(sorted(missing_template_cids))} "
                        "— those leads were left with their current Status and not written anywhere. "
                        "Add their template path in Client Setup and try again."
                    )
```
→
```python
                    render_problem(
                        "These Lead Template columns had no matching Accumulated Report column and were left "
                        f"blank: {', '.join(sorted(unmatched_headers))}. If that data does exist under a different "
                        "column name, rename it (or the Lead Template's header) to something closer and re-run.",
                        level="warning",
                    )
                if missing_template_cids:
                    render_problem(
                        f"No Lead Template path configured for CID(s): {', '.join(sorted(missing_template_cids))} "
                        "— those leads were left with their current Status and not written anywhere. "
                        "Add their template path in Client Setup and try again.",
                        level="warning",
                    )
```

4g. Step 3 messages:

```python
    st.caption(f"No leads currently marked \"{_CLEARED_STATUS_PREFIX}\".")
```
→
```python
    render_empty_state(f"No leads currently marked \"{_CLEARED_STATUS_PREFIX}\".",
                       "Write cleared leads to the Lead Template in step 2 first.")
```

```python
                    st.error(f"Missing rejection reason for: {', '.join(_missing_labels)}")
```
→
```python
                    render_problem(f"Missing rejection reason for: {', '.join(_missing_labels)}",
                                   "Type a reason next to every lead you ticked as rejected, then reconcile again.")
```

```python
                    st.warning(
                        f"⚠️ The {_RESPONSE_DETAILS_TAB} tab has column(s) this tool doesn't fill in and left "
                        f"blank: {', '.join(sorted(_response_unmatched))}. If that's unexpected, the mirror "
                        "workbook's real header text may not match what this page writes."
                    )
```
→
```python
                    render_problem(
                        f"The {_RESPONSE_DETAILS_TAB} tab has column(s) this tool doesn't fill in and left "
                        f"blank: {', '.join(sorted(_response_unmatched))}. If that's unexpected, the mirror "
                        "workbook's real header text may not match what this page writes.",
                        level="warning",
                    )
```

4h. Card-wrap script (run last, from the repo root):

```bash
python - <<'EOF'
from pathlib import Path

PATH = Path("pages/5_Box_Tracker.py")
# (exact current top-level heading line, new heading text), top to bottom.
# Each card runs from its heading -- plus the st.divider() directly above it,
# if any, which the card border replaces -- to just before the next card's
# opener, or to end of file.
CARDS = [
    ('st.subheader("1. Send leads for approval")', ":material/outgoing_mail: 1. Send leads for approval"),
    ('st.subheader("2. Write cleared leads to the Lead Template")',
     ":material/edit_document: 2. Write cleared leads to the Lead Template"),
    ('st.subheader("3. Reconcile portal upload status")', ":material/fact_check: 3. Reconcile portal upload status"),
]

lines = PATH.read_text(encoding="utf-8").split("\n")
heads = [lines.index(old) for old, _ in CARDS]  # ValueError => a heading drifted; stop and re-read the file
starts = [h - 1 if lines[h - 1] == "st.divider()" else h for h in heads]
for n in reversed(range(len(CARDS))):
    end = starts[n + 1] if n + 1 < len(CARDS) else len(lines)
    body = ["    " + line if line.strip() else line for line in lines[heads[n] + 1:end]]
    lines[starts[n]:end] = ["with st.container(border=True):", f'    st.subheader("{CARDS[n][1]}")'] + body
PATH.write_text("\n".join(lines), encoding="utf-8")
EOF
```

- [ ] **Step 5: Verify the diff**

Run: `git diff -w pages/5_Box_Tracker.py`
Expected, and nothing else:
- 2 import lines and the title;
- the 2 setup-guard `render_problem` calls;
- 4 expander openers;
- every message call site listed in 4e-4g;
- 3 card openers, each replacing a plain `st.subheader(...)` (with an optional `st.divider()` directly above it) with a `with st.container(border=True):` block.

Then run `grep -n "st\.error\|st\.warning" pages/5_Box_Tracker.py`. Expected: no output.

- [ ] **Step 6: Run to verify everything passes**

Run: `python -m pytest tests/test_box_tracker_page.py tests/test_page_icons.py -q`
Expected: all existing tests plus the 3 new ones pass, **with no edits to existing tests**.

- [ ] **Step 7: Manual smoke check.** Open Box Tracker for a configured IBM APAC client. Check all three cards render bordered with icons, every expander shows a real icon, and the dark theme looks right.

- [ ] **Step 8: Commit**

```bash
git add pages/5_Box_Tracker.py tests/test_box_tracker_page.py tests/test_page_icons.py
git commit -m "Apply Material icons, icon-titled cards, and shared problem/empty-state helpers to Box Tracker"
```

---

### Task 5: Convertr (`pages/7_Convertr.py`)

**Files:**
- Modify: `pages/7_Convertr.py`
- Test: `tests/test_convertr_page.py` (append only), `tests/test_page_icons.py`

**Scope:**
- **Emoji:** the title, the Jira post button, and the download button label (both dropped per Global Constraints' label table).
- **Status strip:** whether this client's Convertr account credentials are saved and whether it has a Jira ticket — rendered right after the client picker, before step 1.
- **Cards:** the 3 numbered/titled sections (upload, reconcile, Post to Jira) each become an icon-titled card. The upload-results metric row (currently 3 bare `st.metric`s) moves to `render_metric_cards` and stays inside card 1.
- **Errors/warnings:** every `st.error`/`st.warning` on this page goes through `render_problem`, EXCEPT the two exact-text-tested items already in `SWEPT_PAGES`'s allow-list (none apply here — Convertr's own preview-expander label and Result-cell values are the only allowed emoji, per Global Constraints).
- **Jira-account message correction:** it currently says "in Client Setup"; the account actually lives on Settings (see Global Constraints' "one deliberate exception").

- [ ] **Step 1: Pre-flight.** Run:

```bash
grep -n "at\.\(error\|warning\|caption\|info\|metric\|expander\|title\|subheader\|markdown\|download_button\|toast\)\|\.label ==\|startswith(" tests/test_convertr_page.py
```

Expected pins:
- `.startswith("📋 Preview leads to send")`, which is kept (allow-listed);
- Result `.str.startswith("✅"/"❌"/"⏭️")` counts, which are kept (allow-listed data);
- warning substrings `"No client has Convertr enabled"` and `"already uploaded to Convertr before"`;
- error substrings `"leadfile column mapping for Convertr"`, `"CID column"`, `"Convertr account username/password"`;
- caption `"No new decided leads"` / `"No Jira ticket configured"`;
- the `convertr_jira_post`, `convertr_preview_download`, `convertr_upload_file`, `convertr_reupload_duplicates`, `convertr_jira_message`, `convertr_jira_attachment` keys, all untouched;
- no count or positional assertion on `at.metric`, `at.subheader`, or `at.markdown` (so the strip and metric-card changes are safe).

- [ ] **Step 2: Write the failing tests**

Add `"7_Convertr.py",` to `SWEPT_PAGES` in `tests/test_page_icons.py`.

Append to `tests/test_convertr_page.py`:

```python
def test_convertr_status_strip_shows_credentials_and_jira_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_app_settings, save_convertr_account_credentials
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _save_profile()  # enterprise + campaign mapping saved; no account credentials, no Jira ticket

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    strip = next(m.value for m in at.markdown if "badge[Account credentials" in m.value)
    assert ":orange-badge[Account credentials ⚠ Needs setup]" in strip
    assert ":gray-badge[Jira ticket ○ Off]" in strip

    save_convertr_account_credentials(client_name, "me@x.com", "hunter2")
    at.run()
    strip = next(m.value for m in at.markdown if "badge[Account credentials" in m.value)
    assert ":blue-badge[Account credentials ✓ Configured]" in strip


def test_convertr_sections_are_icon_titled_cards_and_icons_replace_emoji(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save_profile(jira_ticket_key="PROJ-1234")

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert at.title[0].value == ":material/link: Convertr"
    assert [s.value for s in at.subheader] == [
        ":material/upload: 1. Upload leads to Convertr",
        ":material/sync: 2. Reconcile accepted/rejected leads",
        ":material/forum: Post to Jira",
    ]
    post = at.button(key="convertr_jira_post")
    assert post.label == "Post to PROJ-1234"
    assert post.proto.icon == ":material/send:"


def test_convertr_upload_summary_uses_icon_metric_cards(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save_profile()

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["convertr_upload_results"] = pd.DataFrame([
        {"CID": "44709", "Email": "a@x.com", "Result": "✅ Lead ID 1"},
        {"CID": "44709", "Email": "b@x.com", "Result": "❌ Convertr returned 400: bad email"},
        {"CID": "44709", "Email": "c@x.com", "Result": "⏭️ Skipped (already uploaded previously)"},
    ])
    at.run()
    assert not at.exception
    assert [m.label for m in at.metric] == ["Uploaded", "Failed", "Skipped"]
    assert [m.value for m in at.metric] == ["1", "1", "1"]
    assert [m.proto.icon for m in at.metric] == [
        ":material/check_circle:", ":material/error:", ":material/skip_next:"]


def test_convertr_download_button_and_no_credentials_error_use_icons(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save_profile()

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    leads_csv = tmp_path / "leads.csv"
    pd.DataFrame([{"Email": "a@x.com", "First Name": "A", "Last Name": "One", "Company": "Acme",
                   "CID": "44709"}]).to_csv(leads_csv, index=False)
    with open(leads_csv, "rb") as f:
        at.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
    assert not at.exception
    download = next(d for d in at.download_button if d.key == "convertr_preview_download")
    assert download.proto.label == "Download these leads (.xlsx)"
    assert download.proto.icon == ":material/download:"

    at.button("Upload to Convertr").click().run()
    assert not at.exception
    err = next(e for e in at.error if "Convertr account username/password" in e.value)
    assert err.icon == ":material/error:"
    assert not err.value.startswith("❌")
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_page_icons.py tests/test_convertr_page.py -q -k "emoji or strip or icon_titled or metric_cards or use_icons"`
Expected: 5 failures (the guard lists the offending lines; no strip found; plain-text subheaders; no `icon`/`show_border` on the metrics; the `❌`-prefixed error and the old `⬇️` label).

- [ ] **Step 4: Implement.** Do these text-anchored edits first, then run the card script (4k).

4a. Imports. Change `from core.errors import render_error` to `from core.errors import render_error, render_problem`. After `from core.profile_store import list_profile_names, load_profile`, add:

```python
from core.ui_components import render_metric_cards, render_status_strip, setup_state
```

4b. Title (line 28): `st.title("🔗 Convertr")` → `st.title(":material/link: Convertr")`.

4c. No-client warning (line 73):

```python
    st.warning("No client has Convertr enabled yet. Set it up on the Client Setup page first.")
```
→
```python
    render_problem("No client has Convertr enabled yet. Set it up on the Client Setup page first.",
                   "Tick **This client uploads to Convertr** under Client Setup → Delivery.", level="warning")
```

4d. Status strip. Directly after `_leadfile_mapping = resolve_field_mapping(_convertr.leadfile_field_mapping, profile.field_mapping)` and before the existing `st.divider()` / `st.subheader("1. Upload leads to Convertr")` pair, insert:

```python
# What this client still needs before steps 1-2 can run -- readable at a
# glance instead of discovered from an error after clicking Upload.
_convertr_creds_now = get_convertr_account_credentials(client_name)
render_status_strip([
    ("Account credentials", setup_state(bool(_convertr_creds_now["username"] and _convertr_creds_now["password"]))),
    ("Jira ticket", setup_state(bool(profile.jira_ticket_key), required=False)),
])
```

4e. Leadfile-mapping and CID checks (lines 110-117):

```python
    if not _leadfile_mapping:
        st.error(
            "This client has no leadfile column mapping for Convertr yet — set one under Client Setup's "
            "Convertr section (Email/First Name/Last Name/Company/CID columns)."
        )
        st.stop()
    cid_column = _leadfile_mapping.cid
    if not cid_column or cid_column not in leads_df.columns:
        st.error(f"This client's CID column (\"{cid_column}\") isn't in the uploaded file.")
        st.stop()
```
→
```python
    if not _leadfile_mapping:
        render_problem(
            "This client has no leadfile column mapping for Convertr yet — set one under Client Setup's "
            "Convertr section (Email/First Name/Last Name/Company/CID columns)."
        )
        st.stop()
    cid_column = _leadfile_mapping.cid
    if not cid_column or cid_column not in leads_df.columns:
        render_problem(f"This client's CID column (\"{cid_column}\") isn't in the uploaded file.",
                       "Check you uploaded the right file, or fix the CID column under Client Setup → "
                       "Delivery → Convertr Upload.")
        st.stop()
```

4f. Duplicate warning (line 128):

```python
        st.warning(f"{len(_dup_preview_df)} lead(s) in this file were already uploaded to Convertr before.")
```
→
```python
        render_problem(f"{len(_dup_preview_df)} lead(s) in this file were already uploaded to Convertr before.",
                       level="warning")
```

4g. Download button (lines 209-214). Change the label and add an icon; the rest is unchanged:

```python
            st.download_button(
                "⬇️ Download these leads (.xlsx)",
                dataframe_to_excel_bytes(_preview_combined, sheet_name="Leads to send"),
                file_name=f"convertr_preview_{client_name}.xlsx",
                key="convertr_preview_download",
            )
```
→
```python
            st.download_button(
                "Download these leads (.xlsx)",
                dataframe_to_excel_bytes(_preview_combined, sheet_name="Leads to send"),
                file_name=f"convertr_preview_{client_name}.xlsx",
                key="convertr_preview_download",
                icon=":material/download:",
            )
```

4h. Missing-credentials errors (lines 219 and 322 — both occurrences, upload and reconcile):

```python
            st.error("Save this client's Convertr account username/password on Client Setup first.")
```
→
```python
            render_problem("Save this client's Convertr account username/password on Client Setup first.",
                           "It's under **Client Setup → Delivery → Convertr Upload**.")
```

4i. Metrics (lines 303-306):

```python
    _sum_col1, _sum_col2, _sum_col3 = st.columns(3)
    _sum_col1.metric("✅ Uploaded", _ok)
    _sum_col2.metric("❌ Failed", _failed)
    _sum_col3.metric("⏭️ Skipped", _skipped)
```
→
```python
    render_metric_cards([
        ("Uploaded", _ok, "check_circle"),
        ("Failed", _failed, "error"),
        ("Skipped", _skipped, "skip_next"),
    ])
```

4j. Pending-lead-fetch warning (lines 362-365):

```python
        st.warning(
            f"{len(_lead_fetch_errors)} pending lead(s) couldn't be checked this sync and will be "
            "retried next time: " + "; ".join(_lead_fetch_errors)
        )
```
→
```python
        render_problem(
            f"{len(_lead_fetch_errors)} pending lead(s) couldn't be checked this sync and will be "
            "retried next time: " + "; ".join(_lead_fetch_errors),
            level="warning",
        )
```

4k. Write-to-Accumulated mapping error (lines 393-396):

```python
            st.error(
                "This client has no leadfile column mapping for Convertr yet — set one under Client "
                "Setup's Convertr section (Email/First Name/Last Name/Company/CID columns)."
            )
```
→
```python
            render_problem(
                "This client has no leadfile column mapping for Convertr yet — set one under Client "
                "Setup's Convertr section (Email/First Name/Last Name/Company/CID columns)."
            )
```

4l. Post to Jira block (lines 443-496). Four edits, in order:

The no-Jira-ticket caption (line 444) stays exactly as it is — no test pins it, and it's already plain text with no emoji, so it's left alone.

The Post button (line 469):

```python
    if st.button(f"📋 Post to {jira_client.extract_ticket_key(profile.jira_ticket_key)}", key="convertr_jira_post"):
```
→
```python
    if st.button(f"Post to {jira_client.extract_ticket_key(profile.jira_ticket_key)}", key="convertr_jira_post",
                 icon=":material/send:"):
```

The Jira-account message (line 472) — the "one deliberate exception" from Global Constraints, corrected to point at the right page:

```python
            st.error("Set up your Jira account (site URL, email, API token) in Client Setup first.")
```
→
```python
            render_problem("Set up your Jira account (site URL, email, API token) on the Settings page first.",
                           "It's under **Settings → Jira account (private to this machine)**.")
```

The post-failure error (line 496):

```python
            except JiraError as exc:
                st.error(f"Failed to post to Jira: {exc}")
```
→
```python
            except JiraError as exc:
                render_problem(f"Failed to post to Jira: {exc}",
                               "Nothing else was affected — click **Post to ...** again once this is fixed.")
```

4m. Card-wrap script (run last, from the repo root):

```bash
python - <<'EOF'
from pathlib import Path

PATH = Path("pages/7_Convertr.py")
CARDS = [
    ('st.subheader("1. Upload leads to Convertr")', ":material/upload: 1. Upload leads to Convertr"),
    ('st.subheader("2. Reconcile accepted/rejected leads")', ":material/sync: 2. Reconcile accepted/rejected leads"),
    ('st.subheader("Post to Jira")', ":material/forum: Post to Jira"),
]

lines = PATH.read_text(encoding="utf-8").split("\n")
heads = [lines.index(old) for old, _ in CARDS]  # ValueError => a heading drifted; stop and re-read the file
starts = [h - 1 if lines[h - 1] == "st.divider()" else h for h in heads]
for n in reversed(range(len(CARDS))):
    end = starts[n + 1] if n + 1 < len(CARDS) else len(lines)
    body = ["    " + line if line.strip() else line for line in lines[heads[n] + 1:end]]
    lines[starts[n]:end] = ["with st.container(border=True):", f'    st.subheader("{CARDS[n][1]}")'] + body
PATH.write_text("\n".join(lines), encoding="utf-8")
EOF
```

Card 1 includes the results metrics and table. They belong to step 1.

- [ ] **Step 5: Verify the diff**

Run: `git diff -w pages/7_Convertr.py`
Expected, and nothing else:
- 2 import lines and the title;
- the strip block;
- the 4c-4l call sites;
- the metric block;
- 3 card openers, each replacing a `st.divider()` + subheader pair.

No change is allowed inside `_plan_sends`, the upload loop, reconcile, or `append_leads`/`remove_*` calls.

Then run `grep -n "st\.error\|st\.warning" pages/7_Convertr.py`. Expected: no output.

- [ ] **Step 6: Run to verify everything passes**

Run: `python -m pytest tests/test_convertr_page.py tests/test_page_icons.py -q`
Expected: 16 + 5 passed, with no edits to existing tests. Pay particular attention to:
- `test_preview_shows_leads_to_send_without_calling_the_api` (the `📋` label is kept);
- `test_switching_client_after_fetch_does_not_write_the_other_clients_leads`;
- `test_jira_section_posts_a_summary_after_reconcile`.

- [ ] **Step 7: Manual smoke check.** Using a Convertr client, check:
- the strip reflects a saved and an unsaved login;
- the three bordered cards render;
- the metric cards show icons after a test-mode upload;
- the Post button shows the send icon;
- the dark theme looks right.

- [ ] **Step 8: Commit**

```bash
git add pages/7_Convertr.py tests/test_convertr_page.py tests/test_page_icons.py
git commit -m "Give Convertr a setup status strip, icon-titled cards, metric cards, and shared problem/empty-state helpers"
```

---

### Task 6: Enhancio (`pages/8_Enhancio.py`)

**Files:**
- Modify: `pages/8_Enhancio.py`
- Test: `tests/test_enhancio_page.py` (append only), `tests/test_page_icons.py`

**Scope:** the same treatment as Task 5, applied to Enhancio's own messages. The one addition: the date-range "no leads" `st.info` becomes an empty state, since it's a "nothing to show" message, not a status.

- [ ] **Step 1: Pre-flight.** Run:

```bash
grep -n "at\.\(error\|warning\|caption\|info\|metric\|expander\|title\|subheader\|markdown\|download_button\|toast\)\|\.label ==\|startswith(" tests/test_enhancio_page.py
```

Expected pins:
- `.startswith("📋 Preview leads to send")` (line 492), which is kept;
- Result `.str.startswith("✅"/"❌"/"⏭️")` counts, which are kept;
- warning substrings `"No client has Enhancio enabled"` and `"Duplicate lead within the campaign allocation"`;
- info `"1 newly accepted"`;
- caption substrings `"No new decided leads"` and `"No Jira ticket configured"`;
- toast substrings;
- the `enhancio_lead_source`, `enhancio_range_start`/`_end` and `enhancio_jira_post` keys, all untouched;
- `at.get("file_uploader")[0]`, which is positional.

Nothing may assert `at.info` for "No leads in the Accumulated Report between". If something does, keep that one as `st.info` and flag it.

- [ ] **Step 2: Write the failing tests**

Add `"8_Enhancio.py",` to `SWEPT_PAGES`.

Append to `tests/test_enhancio_page.py`:

```python
def test_enhancio_status_strip_shows_what_this_client_still_needs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated(acc_path)
    _save_profile(acc_path)  # allocations + field mapping; no Client ID saved, no Jira ticket

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    strip = next(m.value for m in at.markdown if "badge[Allocations" in m.value)
    assert ":blue-badge[Allocations ✓ Configured]" in strip
    assert ":blue-badge[Field mapping ✓ Configured]" in strip
    assert ":orange-badge[Enhancio Client ID ⚠ Needs setup]" in strip
    assert ":gray-badge[Jira ticket ○ Off]" in strip


def test_enhancio_sections_are_icon_titled_cards_and_icons_replace_emoji(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated(acc_path)
    _save_profile(acc_path, jira_ticket_key="PROJ-1234")

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert at.title[0].value == ":material/link: Enhancio"
    assert [s.value for s in at.subheader] == [
        ":material/upload: 1. Upload leads to Enhancio",
        ":material/sync: 2. Reconcile accepted/rejected leads",
        ":material/forum: Post to Jira",
    ]
    post = at.button(key="enhancio_jira_post")
    assert post.label == "Post to PROJ-1234"
    assert post.proto.icon == ":material/send:"


def test_enhancio_upload_summary_uses_icon_metric_cards(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated(acc_path)
    _save_profile(acc_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["enhancio_upload_results"] = pd.DataFrame([
        {"CID": "120022", "Email": "a@x.com", "Result": "✅ Lead ID 1 (Submitted)"},
        {"CID": "120022", "Email": "b@x.com", "Result": "❌ Not accepted by Enhancio (see batch error reasons above)"},
        {"CID": "120028", "Email": "c@x.com", "Result": "⏭️ Skipped (already uploaded to this allocation previously)"},
    ])
    at.run()
    assert not at.exception
    assert [m.label for m in at.metric] == ["Uploaded", "Failed", "Skipped"]
    assert [m.value for m in at.metric] == ["1", "1", "1"]
    assert [m.proto.icon for m in at.metric] == [
        ":material/check_circle:", ":material/error:", ":material/skip_next:"]


def test_enhancio_empty_date_range_and_preview_download_use_icons(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _make_accumulated(acc_path)  # header row only -- no leads on any date
    _save_profile(acc_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert any(c.value.startswith(":material/confirmation_number: No Jira ticket configured") for c in at.caption)

    at.radio(key="enhancio_lead_source").set_value("Pull from Accumulated Report by date range").run()
    assert not at.exception
    assert any(c.value.startswith(":material/event_busy: No leads in the Accumulated Report between")
               for c in at.caption)

    at.radio(key="enhancio_lead_source").set_value("Upload a file").run()
    leads_csv = tmp_path / "leads.csv"
    pd.DataFrame([{"CID": "120022", "Email": "a@x.com", "First Name": "A", "Last Name": "One",
                   "Company": "Acme"}]).to_csv(leads_csv, index=False)
    with open(leads_csv, "rb") as f:
        at.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
    assert not at.exception
    download = next(d for d in at.download_button if d.key == "enhancio_preview_download")
    assert download.proto.label == "Download these leads (.xlsx)"
    assert download.proto.icon == ":material/download:"
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_page_icons.py tests/test_enhancio_page.py -q -k "emoji or strip or icon_titled or metric_cards or use_icons"`
Expected: 5 failures.

- [ ] **Step 4: Implement.** Do these text-anchored edits first, then run the card script.

4a. Imports. Change `from core.errors import render_error` to `from core.errors import render_error, render_problem`. After `from core.toast import queue_toast_before_rerun, show_pending_toast`, add:

```python
from core.ui_components import render_empty_state, render_metric_cards, render_status_strip, setup_state
```

4b. Title (line 36): `st.title("🔗 Enhancio")` → `st.title(":material/link: Enhancio")`.

4c. No-client warning (line 90):

```python
    st.warning("No client has Enhancio enabled yet. Set it up on the Client Setup page first.")
```
→
```python
    render_problem("No client has Enhancio enabled yet. Set it up on the Client Setup page first.",
                   "Tick **This client uploads to Enhancio** under Client Setup → Delivery.", level="warning")
```

4d. Status strip. Directly after `_ACCUMULATED_STATUS_COLUMN = "Status"` (line 98), insert:

```python
# What this client still needs before steps 1-2 can run -- readable at a
# glance instead of discovered from an error after clicking Upload.
render_status_strip([
    ("Allocations", setup_state(bool(_enhancio.allocations))),
    ("Field mapping", setup_state(bool(_enhancio.field_mapping))),
    ("Enhancio Client ID", setup_state(bool(get_enhancio_client_id()))),
    ("Jira ticket", setup_state(bool(profile.jira_ticket_key), required=False)),
])
```

4e. `_get_token` (line 104):

```python
        st.error("No Enhancio Client ID configured — set one on the Settings page first.")
```
→
```python
        render_problem("No Enhancio Client ID configured — set one on the Settings page first.",
                       "It's under **Settings → Enhancio Client ID (private to this machine)**.")
```

4f. Date-range checks (lines 150, 158, 168 and 173):

```python
        st.error("This client has no Accumulated Report configured on Client Setup — set one first.")
```
→
```python
        render_problem("This client has no Accumulated Report configured on Client Setup — set one first.",
                       "It's under **Client Setup → Basics → Reference Files**.")
```

```python
        st.error("\"From date\" must not be after \"To date\".")
```
→
```python
        render_problem("\"From date\" must not be after \"To date\".",
                       "Pick a **From date** on or before the **To date**.")
```

```python
        st.error(f"The Accumulated Report has no \"{_ACCUMULATED_DATE_COLUMN}\" column to filter by.")
```
→
```python
        render_problem(f"The Accumulated Report has no \"{_ACCUMULATED_DATE_COLUMN}\" column to filter by.",
                       "Use **Upload a file** instead, or add a Date column to the Accumulated tab.")
```

```python
        st.info(f"No leads in the Accumulated Report between {_range_start} and {_range_end}.")
```
→
```python
        render_empty_state(f"No leads in the Accumulated Report between {_range_start} and {_range_end}.",
                           "Widen the date range above.", icon="event_busy")
```

4g. Leadfile checks:
- The no-mapping `st.error(` (lines 192-195) becomes `render_problem(`, with both string lines verbatim.
- The CID check (line 199):

```python
        st.error(f"This client's CID column (\"{cid_column}\") isn't in the uploaded file.")
```
→
```python
        render_problem(f"This client's CID column (\"{cid_column}\") isn't in the uploaded file.",
                       "Check you uploaded the right file, or fix the CID column under Client Setup → "
                       "Delivery → Enhancio Upload.")
```

- The duplicate warning (line 273):

```python
        st.warning(f"{_dup_preview_count} lead(s) in this file were already uploaded to their allocation before.")
```
→
```python
        render_problem(f"{_dup_preview_count} lead(s) in this file were already uploaded to their allocation before.",
                       level="warning")
```

4h. Preview body (lines 369-382). The `📋` expander label stays.

```python
        if not _preview_send_by_allocation:
            st.caption("Nothing would be sent — every lead is either already uploaded or unmapped.")
```
→
```python
        if not _preview_send_by_allocation:
            render_empty_state("Nothing would be sent — every lead is either already uploaded or unmapped.",
                               icon="block")
```

In the `st.download_button(` call, change `"⬇️ Download these leads (.xlsx)",` to `"Download these leads (.xlsx)",` and add `icon=":material/download:",` after `key="enhancio_preview_download",`.

4i. Upload-loop warnings. The partial-failure warning (lines 455-459) and the batch-errors warning (lines 481-485): replace `st.warning(` with `render_problem(`, keep every string line verbatim, and add `level="warning",` before the closing paren. For the batch-errors warning, the arguments are one concatenated expression, so it becomes:

```python
                render_problem(
                    f"Allocation {allocation_uid}: Enhancio reported {len(_distinct_batch_errors)} distinct "
                    f"error reason(s) for leads it did not accept in this batch: "
                    + "; ".join(_distinct_batch_errors),
                    level="warning",
                )
```

4j. Metrics (lines 543-546): the same replacement as Task 5 step 4i, byte-for-byte.

4k. Reconcile:

```python
        st.error(f"Error fetching lead status: {exc}")
```
→
```python
        render_problem(f"Error fetching lead status: {exc}",
                       "Nothing was written — click **Fetch decisions from Enhancio** again in a moment.")
```

- The no-mapping `st.error(` in "Write to Accumulated & Refund" (lines 612-615) becomes `render_problem(`, with the strings verbatim.
- Line 660: the same replacement as Convertr Task 5's `No new decided leads` caption, if present verbatim — Enhancio's own caption reads `st.caption("No new decided leads since the last sync.")` and is left alone (no test pins it, but it's already plain text with no emoji or error semantics; only convert it if it's actually an `st.warning`/`st.error` call — confirm against the file before editing).

4l. Post to Jira: the same four edits as Task 5 step 4l, with `key="enhancio_jira_post"` in place of `key="convertr_jira_post"`:
- the Jira caption stays as-is (same reasoning as Task 5);
- the Post button gets `icon=":material/send:"` and drops the `📋` prefix;
- the Jira-account message is corrected to point at **Settings → Enhancio Client ID (private to this machine)**... actually the Jira-account message here is about the **Jira account**, not the Enhancio Client ID — correct it to point at **Settings → Jira account (private to this machine)**, same text as Convertr's;
- the post-failure message gets the same appended suggestion as Convertr's.

4m. Card-wrap script (run last). It's the same script as Task 5 step 4m with these two definitions:

```python
PATH = Path("pages/8_Enhancio.py")
CARDS = [
    ('st.subheader("1. Upload leads to Enhancio")', ":material/upload: 1. Upload leads to Enhancio"),
    ('st.subheader("2. Reconcile accepted/rejected leads")', ":material/sync: 2. Reconcile accepted/rejected leads"),
    ('st.subheader("Post to Jira")', ":material/forum: Post to Jira"),
]
```

Paste the full script from Task 5 step 4m with those two definitions swapped in. The rest stays identical.

- [ ] **Step 5: Verify the diff**

Run: `git diff -w pages/8_Enhancio.py`
Expected: only the listed call sites, the strip, the metric block and 3 card openers. The micro_audience/asset_title/Industry override blocks, `_plan_sends`, the import loop and reconcile logic must be untouched.

Then run `grep -n "st\.error\|st\.warning\|st\.info(f\"No leads" pages/8_Enhancio.py`. Expected: no output. The `"newly accepted"` `st.info` stays.

- [ ] **Step 6: Run to verify everything passes**

Run: `python -m pytest tests/test_enhancio_page.py tests/test_page_icons.py -q`
Expected: 29 + 6 passed, with no edits to existing tests.

- [ ] **Step 7: Manual smoke check.** Check both lead-source modes, the preview download, the reset expander inside card 1, the metric cards after a test-mode upload, and the dark theme.

- [ ] **Step 8: Commit**

```bash
git add pages/8_Enhancio.py tests/test_enhancio_page.py tests/test_page_icons.py
git commit -m "Give Enhancio a setup status strip, icon-titled cards, metric cards, and shared problem/empty-state helpers"
```

---

### Task 7: Integrate (`pages/9_Integrate.py`)

**Files:**
- Modify: `pages/9_Integrate.py`
- Test: `tests/test_integrate_page.py` (append only), `tests/test_page_icons.py`

**Scope:**
- **Emoji:** the title, the `⚙️` in the credentials error, and the 3 metrics.
- **Status strip:** the strip renders **before** the credential/SID hard-stops, so a half-configured client sees everything it's missing at once.
- **Card:** one "Upload leads to Integrate" card, matching step 1 on its sibling pages. It's a single-flow page, so there's no reconcile or Jira card.
- **Errors/warnings:** every `st.error`/`st.warning` goes through `render_problem`.

- [ ] **Step 1: Pre-flight.** Run:

```bash
grep -n "at\.\|\.label ==" tests/test_integrate_page.py
```

Expected pins:
- warning substrings `"No client has Integrate enabled"` and `"already uploaded"`;
- error substrings `"Integrate API Key/Secret"` and `"Last"`;
- results `str.contains("No email value")`;
- the button label `"Upload to Integrate"`;
- the `integrate_test_mode` key;
- `at.get("file_uploader")[0]`, which is positional.

- [ ] **Step 2: Write the failing tests**

Add `"9_Integrate.py",` to `SWEPT_PAGES`. The list now holds all 7 pages.

Append to `tests/test_integrate_page.py`:

```python
def test_integrate_status_strip_shows_everything_missing_before_the_hard_stop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _save_profile()  # SID + field mapping + QA mapping; no API credentials saved

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    strip = next(m.value for m in at.markdown if "badge[API credentials" in m.value)
    assert ":orange-badge[API credentials ⚠ Needs setup]" in strip
    assert ":blue-badge[Source ID ✓ Configured]" in strip
    assert ":blue-badge[Field mapping ✓ Configured]" in strip
    assert ":blue-badge[Leadfile mapping ✓ Configured]" in strip
    err = next(e for e in at.error if "Integrate API Key/Secret" in e.value)
    assert err.icon == ":material/error:"
    assert "⚙️" not in err.value


def test_integrate_upload_is_an_icon_titled_card(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_integrate_credentials("key123", "secret456")
    _save_profile()

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert at.title[0].value == ":material/link: Integrate"
    assert [s.value for s in at.subheader] == [":material/upload: Upload leads to Integrate"]


def test_integrate_upload_summary_uses_icon_metric_cards(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_integrate_credentials("key123", "secret456")
    _save_profile()

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["integrate_upload_results"] = pd.DataFrame([
        {"Email": "a@x.com", "Result": "✅ Lead ID lead-1"},
        {"Email": "", "Result": "❌ No email value for this row"},
        {"Email": "c@x.com", "Result": "⏭️ Skipped (already uploaded previously)"},
    ])
    at.run()
    assert not at.exception
    assert [m.label for m in at.metric] == ["Uploaded", "Failed", "Skipped"]
    assert [m.value for m in at.metric] == ["1", "1", "1"]
    assert [m.proto.icon for m in at.metric] == [
        ":material/check_circle:", ":material/error:", ":material/skip_next:"]
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_page_icons.py tests/test_integrate_page.py -q -k "emoji or strip or icon_titled or metric_cards"`
Expected: 4 failures.

- [ ] **Step 4: Implement.** Do these text-anchored edits first, then run the card script.

4a. Imports. Change `from core.errors import render_error` to `from core.errors import render_error, render_problem`. After `from core.profile_store import list_profile_names, load_profile`, add:

```python
from core.ui_components import render_metric_cards, render_status_strip, setup_state
```

4b. Title (line 25): `st.title("🔗 Integrate")` → `st.title(":material/link: Integrate")`.

4c. No-client warning (line 61):

```python
    st.warning("No client has Integrate enabled yet. Set it up on the Client Setup page first.")
```
→
```python
    render_problem("No client has Integrate enabled yet. Set it up on the Client Setup page first.",
                   "Tick **This client uploads to Integrate** under Client Setup → Delivery.", level="warning")
```

4d. Strip and hard-stops (lines 69-75):

```python
_api_key, _api_secret = get_integrate_credentials()
if not _api_key or not _api_secret:
    st.error("Set the Integrate API Key/Secret on the ⚙️ Settings page first.")
    st.stop()
if not _integrate.sid:
    st.error("This client has no Integrate Source ID (SID) saved — set one on Client Setup.")
    st.stop()
```
→
```python
_api_key, _api_secret = get_integrate_credentials()
# Rendered before the hard-stops below, so a half-configured client sees
# everything it's missing at once rather than one error per fix-and-reload.
render_status_strip([
    ("API credentials", setup_state(bool(_api_key and _api_secret))),
    ("Source ID", setup_state(bool(_integrate.sid))),
    ("Field mapping", setup_state(bool(_integrate.field_mapping))),
    ("Leadfile mapping", setup_state(bool(_leadfile_mapping and _leadfile_mapping.email))),
])
if not _api_key or not _api_secret:
    render_problem("Set the Integrate API Key/Secret on the Settings page first.",
                   "It's under **Settings → Integrate API credentials (private to this machine)**.")
    st.stop()
if not _integrate.sid:
    render_problem("This client has no Integrate Source ID (SID) saved — set one on Client Setup.",
                   "It's under **Client Setup → Delivery → Integrate Upload**.")
    st.stop()
```

4e. Card heading. Insert one line directly above the `st.caption(` that begins `"Uploads a client-verified leadfile straight to this client's Integrate Source.`:

```python
st.subheader("Upload leads to Integrate")
```

4f. Upload-file checks:
- The no-mapping `st.error(` (lines 97-100) becomes `render_problem(`, with both string lines verbatim.
- The Email-column check (line 104):

```python
        st.error(f"This client's Email column (\"{email_column}\") isn't in the uploaded file.")
```
→
```python
        render_problem(f"This client's Email column (\"{email_column}\") isn't in the uploaded file.",
                       "Check you uploaded the right file, or fix the Email column under Client Setup → "
                       "Delivery → Integrate Upload.")
```

- The duplicate warning (line 110):

```python
        st.warning(f"{len(_dup_df)} lead(s) in this file were already uploaded to Integrate before — skipped.")
```
→
```python
        render_problem(f"{len(_dup_df)} lead(s) in this file were already uploaded to Integrate before — skipped.",
                       level="warning")
```

- The no-field-mapping `st.error(` (lines 116-119) becomes `render_problem(`, with the strings verbatim.
- The missing-columns error (lines 131-134):

```python
        st.error(
            "This client's Integrate field mapping references column(s) not present in the uploaded "
            "file: " + ", ".join(_missing_mapped_columns)
        )
```
→
```python
        render_problem(
            "This client's Integrate field mapping references column(s) not present in the uploaded "
            "file: " + ", ".join(_missing_mapped_columns),
            "Rename the file's columns to match, or update the Integrate field mapping under Client Setup → "
            "Delivery → Integrate Upload.",
        )
```

4g. Metrics (lines 195-198): the same replacement as Task 5 step 4i, byte-for-byte.

4h. Card-wrap script (run last). It's the same script as Task 5 step 4m with:

```python
PATH = Path("pages/9_Integrate.py")
CARDS = [
    ('st.subheader("Upload leads to Integrate")', ":material/upload: Upload leads to Integrate"),
]
```

There's one card from the heading to the end of the file. No `st.divider()` sits above it, so only the heading line is replaced.

- [ ] **Step 5: Verify the diff**

Run: `git diff -w pages/9_Integrate.py`
Expected: only the call sites above, the strip block, the metric block and the card opener. `_nan_safe_cell`, the per-lead submit loop and `save_uploaded_emails` must be untouched.

Then run `grep -n "st\.error\|st\.warning" pages/9_Integrate.py`. Expected: no output.

- [ ] **Step 6: Run to verify everything passes**

Run: `python -m pytest tests/test_integrate_page.py tests/test_page_icons.py -q`
Expected: 12 + 7 passed, with no edits to existing tests.

- [ ] **Step 7: Manual smoke check.** Check a client with no credentials (strip plus one error), then with credentials (card, upload, metric cards), in the dark theme.

- [ ] **Step 8: Commit**

```bash
git add pages/9_Integrate.py tests/test_integrate_page.py tests/test_page_icons.py
git commit -m "Give Integrate a setup status strip, an icon-titled upload card, metric cards, and shared problem helpers"
```

---

### Task 8: Client Setup, finishing Phase 2's deferred message sweep (`pages/1_Client_Setup.py`)

**Why this is here:** Phase 2 Task 6 deferred these to "the Phase 4 sweep". They all live in Client Setup's Delivery tab and `_render_paired_field_mapping`, not on the Convertr/Enhancio/Integrate pages:
- the Convertr/Enhancio/Integrate test-connection errors (`st.error(f"❌ {exc}")`);
- the field-mapping line-count error;
- the per-destination "... is disabled for this client." captions, plus the "No Enhancio Client ID configured" caption.

This task also converts the `st.error`/`st.warning` calls Phase 2 left behind (the accumulated-headers read error, the multi-tab warning, and the adjacent test-connection warnings) and removes the six stale `⚙️ Settings page` references. After this task, Client Setup has **zero** ad hoc `st.error`/`st.warning` calls.

**Out of scope (unchanged):** every emoji **button label** (`➕ Add Tab`, `📂 Browse...`, etc., some exact-text-tested); the `st.success(f"✅ ...")` field listings (success, not error/warning); and `st.info`. Client Setup isn't added to `SWEPT_PAGES`, because its button labels still carry emoji.

**Files:**
- Modify: `pages/1_Client_Setup.py`
- Test: `tests/test_client_setup_page.py` (append only)

- [ ] **Step 1: Pre-flight.** Run:

```bash
grep -n "at\.\(error\|warning\|caption\|success\)" tests/test_client_setup_page.py
grep -n "st\.error\|st\.warning\|Settings page\|is disabled for this client\|📭" pages/1_Client_Setup.py
```

Expected test pins:
- the error substrings `"can't contain"`, `"don't have the same number of lines"`, `"First Name"`+`"NO mapping entry"` and `"Client name is required."`;
- the success `"mapped from leadfile column \"Email\""`;
- the warnings `"emial"` and `"TAL is enabled but no sources are configured"`;
- the captions `"No Enhancio Client ID configured"`, `"Allowed values: All"`, and Phase 2's two `:material/` captions.

Read the actual grep output for `pages/1_Client_Setup.py` before editing — this file has moved since Phase 2 (it's already at 47+ tests from Tasks 4-6 of that plan), so re-confirm every line number below against the current file rather than trusting it blindly.

- [ ] **Step 2: Write the failing tests** (append to `tests/test_client_setup_page.py`)

```python
def test_field_mapping_line_count_error_uses_the_shared_problem_helper(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(c for c in at.checkbox if c.label == "This client uploads to Enhancio").set_value(True).run()
    at.text_area(key="enhancio_field_map_cols_input").set_value("Email\nFirst Name").run()
    at.text_area(key="enhancio_field_map_targets_input").set_value("Email Address").run()
    err = next(e for e in at.error if "don't have the same number of lines" in e.value)
    assert err.icon == ":material/error:"
    assert "**Suggested fix:**" in err.value


def test_enhancio_connection_failure_keeps_the_error_text_via_the_shared_helper(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import save_enhancio_client_id
    from core.enhancio_client import EnhancioError
    save_enhancio_client_id("CID123")

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(c for c in at.checkbox if c.label == "This client uploads to Enhancio").set_value(True).run()
    with patch("core.enhancio_client.get_access_token",
               side_effect=EnhancioError("Enhancio returned 401: bad client id")):
        next(b for b in at.button if b.label == "Fetch allocations from Enhancio").click().run()
    assert not at.exception
    err = next(e for e in at.error if "Enhancio returned 401: bad client id" in e.value)
    assert not err.value.startswith("❌")
    assert err.icon == ":material/error:"
    assert "**Suggested fix:**" in err.value


def test_convertr_test_connection_failure_keeps_the_error_text_via_the_shared_helper(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.convertr_client import ConvertrError

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(c for c in at.checkbox if c.label == "This client uploads to Convertr").set_value(True).run()
    next(t for t in at.text_input if t.label.startswith("Convertr enterprise subdomain")).set_value(
        "amazonbusiness").run()
    at.text_area(key="convertr_campaigns_input").set_value("120022,44709").run()
    at.text_input(key="convertr_account_username").set_value("me@x.com").run()
    at.text_input(key="convertr_account_password").set_value("hunter2").run()
    with patch("core.convertr_client.login", side_effect=ConvertrError("Convertr returned 401: bad login")):
        at.button(key="convertr_test_44709").click().run()
    assert not at.exception
    err = next(e for e in at.error if "Convertr returned 401: bad login" in e.value)
    assert not err.value.startswith("❌")
    assert err.icon == ":material/error:"


def test_disabled_delivery_destinations_show_empty_states_pointing_at_their_toggle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    captions = [c.value for c in at.caption]
    for message, toggle in [
        ("Google Sheets delivery is disabled for this client.", "This client delivers leads to Google Sheets"),
        ("Box Tracker is disabled for this client.", "This client uses a Box Tracker"),
        ("Convertr upload is disabled for this client.", "This client uploads to Convertr"),
        ("Enhancio upload is disabled for this client.", "This client uploads to Enhancio"),
        ("Integrate upload is disabled for this client.", "This client uploads to Integrate"),
    ]:
        assert any(c.startswith(f":material/toggle_off: {message}") and toggle in c for c in captions), message
    assert not any("⚙️" in c for c in captions)  # stale pre-Phase-1 nav-icon references are gone

    next(c for c in at.checkbox if c.label == "This client uploads to Enhancio").set_value(True).run()
    assert any(c.value.startswith(":material/key_off: No Enhancio Client ID configured yet.") for c in at.caption)
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_client_setup_page.py -q -k "shared_problem_helper or via_the_shared_helper or point"`
Expected: 4 failures (no suggestion; the `❌` prefix; no `:material/toggle_off:`).

- [ ] **Step 4: Implement** (text-anchored edits; no card changes, since Phase 2 already built the cards)

4a. Imports. `from core.errors import render_error, render_problem` and the `render_empty_state` import already exist from Phase 2. Nothing to add.

4b. Stale `⚙️ Settings page` references. Grep the current file for `⚙️` first (the pre-flight in Step 1 already does this) and replace `⚙️ Settings page` with `**Settings** page` in every string literal it appears in. The rest of each string stays verbatim. Expect roughly 4-6 occurrences, in the shared-root caption near the top of the file, the Google Sheets section, and the Convertr/Enhancio/Integrate credential captions. The other two references (the "No Enhancio Client ID configured" caption and the Convertr `❌ {exc}` errors) are replaced in 4e and 4g/4h below, not here.

4c. Lead Template tabs empty state (in `_render_lead_template_tabs`):

```python
        st.caption("📭 No tabs configured yet — click **➕ Add Tab** below to create one.")
```
→
```python
        render_empty_state("No tabs configured yet.", "Click **➕ Add Tab** below to create one.")
```
The `➕ Add Tab` stays: it's the button's own exact label.

4d. Field-mapping line-count error (in `_render_paired_field_mapping`):

```python
        st.error(
            f"Leadfile columns ({len(_cols)} line(s)) and {target_name} field names ({len(_targets)} "
            "line(s)) don't have the same number of lines — line N in one box has to be line N's match "
            "in the other. Keeping the previously saved mapping until these line up."
        )
```
→
```python
        render_problem(
            f"Leadfile columns ({len(_cols)} line(s)) and {target_name} field names ({len(_targets)} "
            "line(s)) don't have the same number of lines — line N in one box has to be line N's match "
            "in the other. Keeping the previously saved mapping until these line up.",
            "Add or delete lines in one of the two boxes until both have the same count.",
        )
```

4e. Reference Files and Delivery:

```python
                st.error(f"Couldn't read '{accumulated_path}' [{accumulated_tab_name}]: {accumulated_headers_error}")
```
→
```python
                render_problem(f"Couldn't read '{accumulated_path}' [{accumulated_tab_name}]: {accumulated_headers_error}",
                               "Check the Accumulated Report path and tab name above.")
```

```python
                    st.warning("Multi-tab is enabled but no tabs are configured — "
                               "no leads will be pasted into the Lead Template.")
```
→
```python
                    render_problem("Multi-tab is enabled but no tabs are configured — "
                                   "no leads will be pasted into the Lead Template.",
                                   "Click **➕ Add Tab** above, or untick **Route different CIDs to different "
                                   "tabs and/or separate files**.", level="warning")
```

```python
                st.caption("No Google Sheets service account key configured yet — set one on the ⚙️ Settings page.")
```
→
```python
                render_empty_state("No Google Sheets service account key configured yet.",
                                   "Set one on the **Settings** page.", icon="key_off")
```

4f. Disabled-destination captions. Each is indented to match its surrounding block (read the current file to confirm the exact indent before editing):

| Before | After |
|---|---|
| `st.caption("Google Sheets delivery is disabled for this client.")` | `render_empty_state("Google Sheets delivery is disabled for this client.", "Tick **This client delivers leads to Google Sheets** above to configure it.", icon="toggle_off")` |
| `st.caption("Box Tracker is disabled for this client.")` | `render_empty_state("Box Tracker is disabled for this client.", "Tick **This client uses a Box Tracker** above to configure it.", icon="toggle_off")` |
| `st.caption("Convertr upload is disabled for this client.")` | `render_empty_state("Convertr upload is disabled for this client.", "Tick **This client uploads to Convertr** above to configure it.", icon="toggle_off")` |
| `st.caption("Enhancio upload is disabled for this client.")` | `render_empty_state("Enhancio upload is disabled for this client.", "Tick **This client uploads to Enhancio** above to configure it.", icon="toggle_off")` |
| `st.caption("Integrate upload is disabled for this client.")` | `render_empty_state("Integrate upload is disabled for this client.", "Tick **This client uploads to Integrate** above to configure it.", icon="toggle_off")` |

Wrap each after-line to stay under the file's line length, as the earlier `render_empty_state` calls in this file do.

4g. Convertr test connection:

```python
                        st.warning("Enter the enterprise subdomain and account login first.")
```
→
```python
                        render_problem("Enter the enterprise subdomain and account login first.",
                                       "Fill in the enterprise subdomain, Convertr username and Convertr password above.",
                                       level="warning")
```

```python
                                st.warning("Connected, but Convertr returned no forms for this campaign.")
```
→
```python
                                render_problem("Connected, but Convertr returned no forms for this campaign.",
                                               "Check the Campaign ID (SID) in the mapping above belongs to this "
                                               "Publisher account.", level="warning")
```

```python
                            st.error(f"❌ {exc}")
```
(the one in the `except ConvertrError` block) →
```python
                            render_problem(f"Couldn't connect to Convertr: {exc}",
                                           "Check the enterprise subdomain, username and password above, then try again.")
```

4h. Enhancio lookup and test:

```python
                st.caption("No Enhancio Client ID configured yet — set one on the ⚙️ Settings page to "
                           "enable the lookup/test buttons below.")
```
→
```python
                render_empty_state("No Enhancio Client ID configured yet.",
                                   "Set one on the **Settings** page to enable the lookup/test buttons below.",
                                   icon="key_off")
```

```python
                            st.warning("Connected, but Enhancio returned no allocations for this account.")
```
→
```python
                            render_problem("Connected, but Enhancio returned no allocations for this account.",
                                           "Check the Client ID on the **Settings** page is this org's Connected App.",
                                           level="warning")
```

The `except EnhancioError` in "Fetch allocations" changes from

```python
                        st.error(f"❌ {exc}")
```
to
```python
                        render_problem(f"Couldn't connect to Enhancio: {exc}",
                                       "Check the Enhancio Client ID on the **Settings** page, then try again.")
```

```python
                                st.warning("Connected, but Enhancio returned no fields for this allocation.")
```
→
```python
                                render_problem("Connected, but Enhancio returned no fields for this allocation.",
                                               "Check the allocationUid in the mapping above.", level="warning")
```

```python
                                st.error(
                                    "❌ These mandatory fields have NO mapping entry pointing to them at all "
                                    "-- Enhancio will reject every lead sent to this allocation until each has "
                                    "one: " + "; ".join(f'\"{f}\"' for f in _unmapped_mandatory)
                                )
```
→
```python
                                render_problem(
                                    "These mandatory fields have NO mapping entry pointing to them at all "
                                    "-- Enhancio will reject every lead sent to this allocation until each has "
                                    "one: " + "; ".join(f'\"{f}\"' for f in _unmapped_mandatory),
                                    "Add a line for each to the Enhancio field mapping above — leadfile column on "
                                    "the left, this exact field label on the right.",
                                )
```

The `except EnhancioError` in "Test connection" changes from

```python
                            st.error(f"❌ {exc}")
```
to
```python
                            render_problem(f"Couldn't connect to Enhancio: {exc}",
                                           "Check the Enhancio Client ID on the **Settings** page, then try again.")
```

4i. Integrate attribute warning:

```python
                st.warning(
                    "These Integrate field mapping target(s) aren't one of Integrate's known attribute "
                    "names, double-check for a typo: " + ", ".join(_integrate_invalid_targets)
                )
```
→
```python
                render_problem(
                    "These Integrate field mapping target(s) aren't one of Integrate's known attribute "
                    "names, double-check for a typo: " + ", ".join(_integrate_invalid_targets),
                    "Fix the spelling if it's a typo; a genuinely new Integrate attribute can be saved as-is.",
                    level="warning",
                )
```

- [ ] **Step 5: Verify the diff**

Run: `git diff -w pages/1_Client_Setup.py`
Expected: only the 4b-4i lines. There are no tab, card, label, key or save-logic changes.

Then run `grep -n "st\.error\|st\.warning\|⚙️" pages/1_Client_Setup.py`. Expected: no output.

- [ ] **Step 6: Run to verify everything passes**

Run: `python -m pytest tests/test_client_setup_page.py -q`
Expected: all existing tests plus the 4 new ones pass, with no edits to existing tests. Pay particular attention to these four:
- `test_field_mapping_mismatched_line_counts_shows_error_and_keeps_existing_mapping`;
- `test_enhancio_test_connection_flags_a_mandatory_field_with_no_mapping`;
- `test_enhancio_fetch_allocations_button_shows_client_id_prompt_when_unset`;
- `test_invalid_integrate_target_attribute_warns_but_still_saves`.

- [ ] **Step 7: Manual smoke check.** In Client Setup → Delivery, with every destination off, check that each card shows its `toggle_off` empty state. Then enable Enhancio with no Client ID, and trigger a line-count mismatch. Check light and dark themes.

- [ ] **Step 8: Commit**

```bash
git add pages/1_Client_Setup.py tests/test_client_setup_page.py
git commit -m "Finish Client Setup's deferred sweep: route test-connection/mapping errors and disabled states through shared helpers"
```

---

### Task 9: Final sweep verification (no new code)

- [ ] **Step 1: No ad hoc alerts remain.** Run:

```bash
grep -n "st\.error(\|st\.warning(" pages/1_Client_Setup.py pages/3_Settings.py pages/4_Activity_Log.py pages/5_Box_Tracker.py pages/6_Fuzzy_Match.py pages/7_Convertr.py pages/8_Enhancio.py pages/9_Integrate.py
```

Expected: no output. Run Check (`pages/2_Run_Check.py`) is excluded on purpose (see Global Constraints).

- [ ] **Step 2: Guard test covers all 7 pages.** Run `python -m pytest tests/test_page_icons.py -v`. Expected: 7 parametrized cases pass: `3_Settings.py`, `4_Activity_Log.py`, `5_Box_Tracker.py`, `6_Fuzzy_Match.py`, `7_Convertr.py`, `8_Enhancio.py` and `9_Integrate.py`.

- [ ] **Step 3: Full suite.** Run `python -m pytest -q`. Expected: all green (except the 2 pre-existing, unrelated `tests/test_end_to_end_basware.py` errors), and the only test-file changes are appends plus the new `tests/test_page_icons.py`. Confirm with:

```bash
git diff 771422f --stat -- tests/
git diff 771422f -- tests/ | grep "^-[^-]"
```

The second command must print nothing: no existing test line was removed or edited.

- [ ] **Step 4: Icon render check.** Run `streamlit run Summary.py` and visit all 7 pages plus Client Setup → Delivery, in light and dark theme. Streamlit renders a mistyped `:material/name:` as a blank gap without an error, so look for any blank icon slot. Names used in this plan:
  - `settings`, `folder_shared`, `folder_open`, `key`, `key_off`, `manage_accounts`, `timer`
  - `bar_chart`, `history`, `list_alt`, `groups`, `filter_list_off`
  - `search`, `compare_arrows`, `upload_file`
  - `inventory_2`, `info`, `back_hand`, `outgoing_mail`, `edit_document`, `fact_check`, `task_alt`, `inbox`
  - `link`, `upload`, `sync`, `forum`, `send`, `download`, `block`, `confirmation_number`, `event_busy`
  - `check_circle`, `error`, `skip_next`, `toggle_off`

  Fix any blank icon against fonts.google.com/icons and commit the fix separately.

---

## Self-Review Notes

- **Spec coverage (§Rollout item 4, applying §1-§2 to the remaining pages):**

  | Element | Where |
  |---|---|
  | §1 icons | Tasks 2-7, each an in-page emoji → Material swap. Sidebar nav was already done in Phase 1. Locked in by `tests/test_page_icons.py` plus per-page AppTest assertions on the title, expander `.icon` and button `proto.icon`. |
  | §1 cards | Existing numbered sections become icon-titled bordered cards: Box Tracker (3), Convertr (3), Enhancio (3), Integrate (1), Activity Log (2), Fuzzy Match (1). Settings is skipped because each group is already its own expander. |
  | §1 status chips | Settings (credentials), Convertr, Enhancio and Integrate (per-client setup), all via the one new `setup_state`. Activity Log, Fuzzy Match and Box Tracker have no configuration to summarise, so they get none. |
  | §2 empty states | Every bare "nothing here" caption on the 7 pages, plus Client Setup's disabled/unconfigured captions. |
  | §2 errors/warnings | Every `st.error`/`st.warning` on the 7 pages plus Client Setup (Task 9 Step 1 greps for zero). |
  | §2 loading | Nothing new. Every slow call on these pages already has `st.spinner`/`st.progress`. |
  | Phase 2's deferred items | Task 8, the exact list from Phase 2 Task 6's "Out of scope", every original message kept as a substring. |

- **Departures from or interpretations of the spec, and the brief:**
  - The deferred Phase 2 messages are in Client Setup, not the upload pages. Task 8 targets Client Setup. The brief's "Convertr/Enhancio/Integrate" refers to those destinations' Client Setup sections.
  - The upload pages' metric rows now use `render_metric_cards` (Tasks 5-7). These pages already show a 3-metric row; the only emoji-free way to keep their icons is `icon=`, and the shared component is exactly `st.metric(icon=, border=True)`. **Veto option:** if the border isn't wanted, use `col.metric(label, value, icon=f":material/{icon}:")` in the existing `st.columns(3)` instead. The tests need only drop the `show_border` assertion.
  - The Jira-account message on Convertr and Enhancio is reworded. It pointed users at Client Setup, but the account lives on Settings.
  - Enhancio's "No leads in the Accumulated Report between ..." changes from `st.info` to an empty state. It's a "nothing to show" message; no test pins it as info.
- **Known leftovers, flagged and not done** (each needs an existing test edited, or is outside this phase):
  - Result-cell emoji and the `📋 Preview leads to send` label (exact-text-tested).
  - The `core/toast.py` toast icon (`tests/test_toast.py:27`).
  - The `core/branding.py` sidebar emoji.
  - Client Setup and Run Check emoji button labels (several exact-text-tested, e.g. `"➕ Add Exclusion Source"`, `"⬇️ Download"`).
  - `Summary.py`'s in-page emoji (`✅` title; the stale "🗂️ Client Setup or ▶️ Run Check" text).
  - **Spec gap:** §2's Home-page dashboard was never scheduled in any phase (Phases 1-4 all skip it). It needs its own follow-up if still wanted.
- **Placeholder scan:** every step has real before/after code or an exact command. Task 6 step 4m and Task 7 step 4h reuse Task 5 step 4m's script verbatim with the two definitions written out. Every "same replacement as Task N" points at a fully written block with only the named substitution.
- **Type consistency:**
  - `setup_state(configured: bool, required: bool = True) -> ChipState` (Task 1) is always called with `bool(...)`/`all(...)`. It feeds `render_status_strip(list[tuple[str, ChipState]])`.
  - Its outputs `"configured"`/`"needs_setup"`/`"off"` render as `:blue-badge[… ✓ Configured]`/`:orange-badge[… ⚠ Needs setup]`/`:gray-badge[… ○ Off]` via the shipped `chip_markdown`. The tests assert exactly those strings.
  - `render_metric_cards(list[tuple[str, int, str]])` gets `int(...)` counts.
  - `render_empty_state(message, hint="", icon="inbox")` and `render_problem(message, suggestion="", level=...)` match the shipped signatures in `core/ui_components.py` and `core/errors.py`.
- **Test preservation strategy:**
  - Each task's pre-flight greps list what the page's tests pin: substrings, counts, positional indices (`at.selectbox[0]`, `at.dataframe[0]`, `at.get("file_uploader")[0]`), labels and keys. Every edit leaves those untouched.
  - Labels change only where a test finds the widget by key.
  - Messages keep their text as a substring.
  - No widget is added before a positionally-indexed one.
  - Card wrapping only re-indents, which `git diff -w` verifies, so it can't change behaviour.
  - Task 9 Step 3 checks mechanically that no existing test line was edited.
  - Same rule as Phases 1-3: if an existing test has to change, the change is wrong, not the test.

### Critical Files for Implementation
- `pages/7_Convertr.py`
- `pages/8_Enhancio.py`
- `pages/5_Box_Tracker.py`
- `pages/1_Client_Setup.py`
- `core/ui_components.py` and the new `tests/test_page_icons.py`

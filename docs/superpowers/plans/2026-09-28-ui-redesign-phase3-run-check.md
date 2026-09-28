# UI Redesign Phase 3: Run Check Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Run Check's existing 3-step flow easy to see (spec section 5):
- A real visual stepper replaces the emoji-in-columns step indicator.
- Leads In / Valid / Refunded / Needs Review become bordered, icon-labelled metric cards.
- The Needs Review table gets per-row decisions next to the existing bulk select-and-act flow, which stays unchanged.

**Architecture:**
- Two new shared components go in `core/ui_components.py`, next to Phase 2's chips: `stepper_markdown`/`render_stepper` and `render_metric_cards`.
- The code that moves a lead out of Needs Review into valid or refund lives inline in the page today. It moves into a new pure module, `core/review_actions.py`, so the existing bulk buttons and the new row-decision button share one implementation and can be unit tested. The page file starts with a digit, so it can't be imported.
- `pages/2_Run_Check.py` keeps its execution order. Only three blocks change:
  - the step-indicator loop, currently lines 204-211;
  - the four `st.metric` calls, currently lines 501-505;
  - the Needs Review table and buttons, currently lines 585-663.

**Tech Stack:** Python, Streamlit 1.61.1. It uses:
- `st.metric(..., icon=, border=True)`;
- `:color-badge[:material/icon: ...]` markdown;
- `st.column_config.SelectboxColumn`;
- no new dependency.

Tests use pytest + `streamlit.testing.v1.AppTest`.

## Global Constraints

- **HIGH-RISK WARNING (Tasks 4 and 5).** This needs the same care as Phase 1's Task 7 and Phase 2's Task 4.
  - `pages/2_Run_Check.py` is about 1,200 lines and drives real writes: Accumulated Report, Refund tab, Lead Template, Google Sheets, the Convertr/Enhancio hand-off, and Jira.
  - `tests/test_run_check_page.py` has 44 tests, more than any other page. It must pass with **zero edits to existing tests**.
  - If an existing test needs changing to pass, stop. The change has broken real behaviour, so don't patch around it in the test.
- **Visual/UX only.** Per the spec, don't change:
  - `run_pipeline`, `apply_refund_overrides`, `_finalize_write`, `_finalize_jira_summary`, or any write path, file format, or `core/` check module;
  - the Complex Account fill/confirm flow;
  - the Post to Jira panel body.
- **Don't touch the client picker.** Leave lines 78-91 alone: the `render_client_picker(get_clients_dir(), key_prefix="run_check")` call and the Clear button. `test_client_picker_groups_regional_profiles_on_run_check` and `test_client_picker_still_selects_ungrouped_clients_by_exact_name_on_run_check` are the regression checks that it still works.
- **Existing assertions this plan must keep passing.** Found by reading the test file:
  1. `test_review_download_button_and_refund_download_button_present` checks three things:
     - `all(d.label == "⬇️ Download" for d in at.download_button)`, so **add no new download button**;
     - no expander labelled `"Excel row..."`;
     - no button with key `approve_1`.

     The per-lead expander with its own Approve/Refund buttons was **removed on purpose** in commit `3da390b` ("Drop redundant per-lead review detail view"). Row-level controls in this plan are therefore **not** per-row buttons. They are an inline **Action** column inside the existing `st.data_editor`, plus one Apply button.
  2. `test_review_bulk_approve_selected_leads` patches `streamlit.data_editor` to return a table with **no `Action` column**. The page must treat a missing `Action` column as "no row decisions" (`edited_review_table.get("Action", [])`). Keys `review_bulk_approve`, `review_bulk_refund`, `review_select_all`, `review_clear_all` and `review_download_button` stay as they are.
  3. `test_completed_checks_status_shown_for_enabled_checks_only` checks that exactly **one** `st.caption` contains `"completed"`. The stepper and metric cards must not add a caption, and must never use the word "completed". The stepper is one `st.markdown` that uses "Run Check"/"Review & Finalize"/"Post to Jira" only.
  4. `test_enabled_checks_caption_includes_lead_template_mapping` and every `"Finalize"` / `"Run Check"` / `"Select all as valid"` button-label lookup stay untouched. None of those lines are in scope.
  5. **No existing test asserts on the current step indicator** (`✅`/`**➡️`/`⚪` markdown, `st.columns` count) or on `at.metric`. Confirmed by grep; re-run it in Task 4 Step 1. Both are pure visual replacements. Metric **labels** stay byte-identical anyway, as a precaution.
- **Test-harness trap:** `patch("streamlit.data_editor", return_value=X)` replaces **both** the Refund and the Needs Review editors. A new test that ends with refund rows, for example after a "Mark as refund", must use a `side_effect` that returns the prepared table only for the review editor (the one with a `Select` column) and passes every other table through. See `_review_only_editor` in Task 5.
- Don't reorder executable code except where a step says so. After each page task, `git diff -w pages/2_Run_Check.py` must show only the lines the task lists.
- Run `python -m pytest tests/test_run_check_page.py -q` after every page task. Run `python -m pytest -q` before calling the plan done.
- Direct commits to `master`, one commit per task.

---

### Task 1: Stepper component (`core/ui_components.py`)

**Files:**
- Modify: `core/ui_components.py`
- Test: `tests/test_ui_components.py`

**Interfaces:**
- `StepState = Literal["done", "current", "todo"]`
- `step_state(step_num: int, current: int) -> StepState`: a step before `current` is `"done"`, the step equal to `current` is `"current"`, and later steps are `"todo"`.
- `stepper_markdown(steps: list[str], current: int) -> str`: one badge per step, `:{color}-badge[:material/{icon}: {n}. {label}]`, joined by ` :material/chevron_right: `. `current` is 1-based. A `current` larger than `len(steps)` marks every step done, with no crash.
- `render_stepper(steps: list[str], current: int) -> None`: a single `st.markdown` element.

| State | Icon | Colour |
|---|---|---|
| done | `check_circle` | green |
| current | `arrow_circle_right` | blue |
| todo | `radio_button_unchecked` | gray |

- [ ] **Step 1: Write the failing tests** (append to `tests/test_ui_components.py`)

```python
def test_step_state_mapping():
    from core.ui_components import step_state
    assert step_state(1, 2) == "done"
    assert step_state(2, 2) == "current"
    assert step_state(3, 2) == "todo"


def test_stepper_markdown_marks_done_current_and_upcoming_steps():
    from core.ui_components import stepper_markdown
    assert stepper_markdown(["Run Check", "Review & Finalize", "Post to Jira"], 2) == (
        ":green-badge[:material/check_circle: 1. Run Check]"
        " :material/chevron_right: "
        ":blue-badge[:material/arrow_circle_right: 2. Review & Finalize]"
        " :material/chevron_right: "
        ":gray-badge[:material/radio_button_unchecked: 3. Post to Jira]"
    )


def test_stepper_markdown_past_the_last_step_marks_everything_done():
    from core.ui_components import stepper_markdown
    value = stepper_markdown(["Run Check", "Review & Finalize"], 3)
    assert "blue-badge" not in value and "gray-badge" not in value
    assert value.count(":green-badge[") == 2


def test_render_stepper_renders_one_markdown_element():
    def _app():
        from core.ui_components import render_stepper
        render_stepper(["Run Check", "Review & Finalize"], 1)

    at = AppTest.from_function(_app)
    at.run()
    assert not at.exception
    assert len(at.markdown) == 1
    assert at.markdown[0].value.startswith(":blue-badge[:material/arrow_circle_right: 1. Run Check]")
    assert len(at.caption) == 0  # never a caption -- see Run Check's "completed" caption test
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_ui_components.py -q -k "step"`
Expected: 4 failures. They raise `ImportError: cannot import name 'step_state'` / `'stepper_markdown'`, and the AppTest one fails with a truthy `at.exception`.

- [ ] **Step 3: Implement** (append to `core/ui_components.py`)

```python
StepState = Literal["done", "current", "todo"]

# (Material icon name, st.badge colour) per step state.
_STEPS: dict[str, tuple[str, str]] = {
    "done": ("check_circle", "green"),
    "current": ("arrow_circle_right", "blue"),
    "todo": ("radio_button_unchecked", "gray"),
}


def step_state(step_num: int, current: int) -> StepState:
    if step_num < current:
        return "done"
    return "current" if step_num == current else "todo"


def stepper_markdown(steps: list[str], current: int) -> str:
    """One row of numbered step badges (1-based `current`), joined by a
    chevron -- a real visual stepper instead of plain text with a coloured
    circle (UI redesign spec, section 5)."""
    parts = []
    for num, label in enumerate(steps, start=1):
        icon, color = _STEPS[step_state(num, current)]
        parts.append(f":{color}-badge[:material/{icon}: {num}. {label}]")
    return " :material/chevron_right: ".join(parts)


def render_stepper(steps: list[str], current: int) -> None:
    st.markdown(stepper_markdown(steps, current))
```

Also update the module docstring's first line to: `"""Small shared in-page visual components (status chips, empty states, stepper, metric cards).`

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_ui_components.py -q`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add core/ui_components.py tests/test_ui_components.py
git commit -m "Add shared stepper component in core/ui_components.py"
```

---

### Task 2: Metric-card component (`core/ui_components.py`)

**Files:**
- Modify: `core/ui_components.py`
- Test: `tests/test_ui_components.py`

**Interfaces:**
- `render_metric_cards(items: list[tuple[str, int, str]]) -> None`. Each item is `(label, value, material_icon_name)`. It renders one column per item, each holding `st.metric(label, value, icon=f":material/{icon}:", border=True)`. The label is passed through unchanged, so callers keep their exact existing labels.

- [ ] **Step 1: Write the failing test** (append)

```python
def test_render_metric_cards_renders_bordered_icon_metrics_in_order():
    def _app():
        from core.ui_components import render_metric_cards
        render_metric_cards([("Leads In", 3, "group"), ("Valid", 1, "check_circle")])

    at = AppTest.from_function(_app)
    at.run()
    assert not at.exception
    assert [m.label for m in at.metric] == ["Leads In", "Valid"]
    assert [m.value for m in at.metric] == ["3", "1"]
    assert [m.proto.icon for m in at.metric] == [":material/group:", ":material/check_circle:"]
    assert all(m.proto.show_border for m in at.metric)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_ui_components.py -q -k metric_cards`
Expected: FAIL. The app raises `ImportError: cannot import name 'render_metric_cards'`.

- [ ] **Step 3: Implement** (append)

```python
def render_metric_cards(items: list[tuple[str, int, str]]) -> None:
    """A row of bordered metric cards, one per (label, value, icon) --
    instead of bare numbers (UI redesign spec, section 5). `icon` is a
    Material Symbols name, e.g. "check_circle"."""
    for col, (label, value, icon) in zip(st.columns(len(items)), items):
        col.metric(label, value, icon=f":material/{icon}:", border=True)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_ui_components.py -q`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add core/ui_components.py tests/test_ui_components.py
git commit -m "Add shared metric-card component"
```

---

### Task 3: Needs Review action helpers (`core/review_actions.py`)

**Files:**
- Create: `core/review_actions.py`
- Test: `tests/test_review_actions.py` (new)

**Why a new module:** Run Check's bulk buttons mutate `PipelineResult` inline today. The new row-decision button needs exactly the same moves. Pulling them into one pure module keeps the two paths identical and makes them unit-testable. This isn't check logic: `run_pipeline` and every `core/checks/*` module are untouched. The two mutation functions are copied **verbatim** from `pages/2_Run_Check.py` lines 648-650 and 658-660.

**Interfaces:**
- `REVIEW_ACTION_APPROVE = "Approve as valid"`, `REVIEW_ACTION_REFUND = "Mark as refund"`, and `REVIEW_ACTIONS = (REVIEW_ACTION_APPROVE, REVIEW_ACTION_REFUND)`.
- `approve_review_leads(result: PipelineResult, indices: Iterable[int]) -> None`: for each idx, `result.valid_indices.append(idx)`, then `del result.review_reasons[idx]`.
- `refund_review_leads(result: PipelineResult, indices: Iterable[int]) -> None`: for each idx, `result.refund_reasons[idx] = "; ".join(str(d) for d in result.review_reasons[idx])`, then `del result.review_reasons[idx]`.
- `split_row_actions(indices: Sequence[int], actions: Iterable[object]) -> tuple[list[int], list[int]]`: pairs indices with the edited Action cells and returns `(approve_indices, refund_indices)`. Anything that isn't one of the two exact strings counts as "no decision". That includes `None`, `NaN`, `pd.NA` (what a pandas `"string"` column holds) and unknown text. The check is `isinstance(action, str)`, because `pd.NA == "x"` is ambiguous and `bool(pd.NA)` raises.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_review_actions.py
import math

import pandas as pd

from core.check_result import ReviewDetail
from core.pipeline import PipelineResult
from core.review_actions import (
    REVIEW_ACTION_APPROVE, REVIEW_ACTION_REFUND, REVIEW_ACTIONS,
    approve_review_leads, refund_review_leads, split_row_actions,
)


def _result():
    return PipelineResult(valid_indices=[5], refund_reasons={}, review_reasons={
        0: [ReviewDetail(check="Duplicate", message="reason a")],
        1: [ReviewDetail(check="Duplicate", message="reason b"), ReviewDetail(check="TAL", message="fuzzy")],
    })


def test_action_labels():
    assert REVIEW_ACTIONS == ("Approve as valid", "Mark as refund")


def test_approve_review_leads_moves_to_valid_in_order():
    result = _result()
    approve_review_leads(result, [1, 0])
    assert result.valid_indices == [5, 1, 0]
    assert result.review_reasons == {}
    assert result.refund_reasons == {}


def test_refund_review_leads_joins_every_detail_as_the_reason():
    result = _result()
    refund_review_leads(result, [1])
    assert result.refund_reasons == {1: "Duplicate - reason b; TAL - fuzzy"}
    assert list(result.review_reasons) == [0]
    assert result.valid_indices == [5]


def test_empty_indices_are_a_no_op():
    result = _result()
    approve_review_leads(result, [])
    refund_review_leads(result, [])
    assert list(result.review_reasons) == [0, 1]


def test_split_row_actions_ignores_blank_and_unknown_cells():
    approve, refund = split_row_actions(
        [10, 11, 12, 13, 14, 15],
        [REVIEW_ACTION_APPROVE, None, REVIEW_ACTION_REFUND, pd.NA, math.nan, "something else"],
    )
    assert approve == [10]
    assert refund == [12]


def test_split_row_actions_accepts_a_pandas_string_series():
    actions = pd.Series([REVIEW_ACTION_REFUND, None], dtype="string")
    assert split_row_actions([3, 4], actions) == ([], [3])


def test_split_row_actions_with_no_action_column_means_no_decisions():
    assert split_row_actions([0, 1], []) == ([], [])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_review_actions.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'core.review_actions'`.

- [ ] **Step 3: Implement**

```python
# core/review_actions.py
"""Moves Needs Review leads to valid or refund -- shared by Run Check's
bulk select-and-act buttons and its per-row Action column so the two can
never disagree. Page-level review resolution only; no check logic lives
here (see core/pipeline.py / core/checks/)."""
from collections.abc import Iterable, Sequence

from core.pipeline import PipelineResult

REVIEW_ACTION_APPROVE = "Approve as valid"
REVIEW_ACTION_REFUND = "Mark as refund"
REVIEW_ACTIONS = (REVIEW_ACTION_APPROVE, REVIEW_ACTION_REFUND)


def approve_review_leads(result: PipelineResult, indices: Iterable[int]) -> None:
    for idx in indices:
        result.valid_indices.append(idx)
        del result.review_reasons[idx]


def refund_review_leads(result: PipelineResult, indices: Iterable[int]) -> None:
    for idx in indices:
        result.refund_reasons[idx] = "; ".join(str(d) for d in result.review_reasons[idx])
        del result.review_reasons[idx]


def split_row_actions(indices: Sequence[int], actions: Iterable[object]) -> tuple[list[int], list[int]]:
    """(approve_indices, refund_indices) from the Needs Review table's
    edited Action cells, paired positionally with `indices`. A blank cell
    comes back from st.data_editor as None/NaN/pd.NA -- anything that isn't
    exactly one of REVIEW_ACTIONS means "no decision for this row"."""
    approve: list[int] = []
    refund: list[int] = []
    for idx, action in zip(indices, actions):
        if not isinstance(action, str):
            continue
        if action == REVIEW_ACTION_APPROVE:
            approve.append(idx)
        elif action == REVIEW_ACTION_REFUND:
            refund.append(idx)
    return approve, refund
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_review_actions.py -q`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add core/review_actions.py tests/test_review_actions.py
git commit -m "Add shared Needs Review action helpers in core/review_actions.py"
```

---

### Task 4: Run Check — visual stepper and metric cards (HIGH RISK)

**Files:**
- Modify: `pages/2_Run_Check.py`
- Test: `tests/test_run_check_page.py` (append new tests only)

**Interfaces:** consumes `render_stepper` (Task 1) and `render_metric_cards` (Task 2). The step computation (`_step_current`, `_step_pending_summary`, `_step_labels`, currently lines 195-203) stays **byte-identical**. Only how it's rendered changes.

- [ ] **Step 1: Pre-flight check (no code yet).** Run:

```bash
grep -n '➡️\|⚪\|at\.metric\|at\.columns\|at\.markdown' tests/test_run_check_page.py
grep -n '"completed"\|completed" in' tests/test_run_check_page.py
```

Expected:
- The first grep has no hits. Nothing asserts on the old step indicator or on metrics.
- The second grep hits only `test_completed_checks_status_shown_for_enabled_checks_only`, which counts captions containing "completed".

If the first grep has any hit, stop and flag it. That test pins the current implementation, and the plan needs revisiting.

- [ ] **Step 2: Write the failing tests** (append to `tests/test_run_check_page.py`)

```python
def _stepper(at):
    return next(m.value for m in at.markdown if "Review & Finalize" in m.value)


def test_stepper_shows_run_check_as_current_before_any_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    save_profile(ClientProfile(name="Test Client", accumulated_report_path=acc_path, field_mapping=fm),
                 get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert _stepper(at) == (
        ":blue-badge[:material/arrow_circle_right: 1. Run Check]"
        " :material/chevron_right: "
        ":gray-badge[:material/radio_button_unchecked: 2. Review & Finalize]"
    )  # no Jira ticket key -> no "Post to Jira" step
    # The old emoji-in-columns indicator is gone.
    assert not any(m.value.startswith(("✅ 1.", "**➡️", "⚪")) for m in at.markdown)


def test_stepper_shows_review_as_current_with_a_result_and_jira_step_upcoming(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    save_profile(ClientProfile(name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
                               jira_ticket_key="PROJ-1234"), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "1"},
    ])
    at.session_state["run_result"] = PipelineResult(valid_indices=[0], refund_reasons={})
    at.session_state["run_result_for"] = "Test Client"
    at.run()
    assert not at.exception
    stepper = _stepper(at)
    assert ":green-badge[:material/check_circle: 1. Run Check]" in stepper
    assert ":blue-badge[:material/arrow_circle_right: 2. Review & Finalize]" in stepper
    assert ":gray-badge[:material/radio_button_unchecked: 3. Post to Jira]" in stepper


def test_stepper_shows_post_to_jira_as_current_after_finalize(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    save_profile(ClientProfile(name="Test Client", accumulated_report_path=acc_path, field_mapping=fm,
                               jira_ticket_key="PROJ-1234"), get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "1"},
    ])
    at.session_state["run_result"] = PipelineResult(valid_indices=[0], refund_reasons={})
    at.session_state["run_result_for"] = "Test Client"
    at.run()
    next(b for b in at.button if b.label == "Finalize").click().run()
    assert not at.exception
    stepper = _stepper(at)
    assert ":green-badge[:material/check_circle: 1. Run Check]" in stepper
    assert ":green-badge[:material/check_circle: 2. Review & Finalize]" in stepper
    assert ":blue-badge[:material/arrow_circle_right: 3. Post to Jira]" in stepper


def test_summary_shows_four_bordered_metric_cards(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    save_profile(ClientProfile(name="Test Client", accumulated_report_path=acc_path, field_mapping=fm),
                 get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "1"},
        {"Email_Address": "b@x.com", "First_Name": "B", "Last_Name": "Two", "Company_Name": "Y", "CID": "1"},
        {"Email_Address": "c@x.com", "First_Name": "C", "Last_Name": "Three", "Company_Name": "Z", "CID": "1"},
    ])
    at.session_state["run_result"] = PipelineResult(
        valid_indices=[0], refund_reasons={1: "Duplicate - exact email"},
        review_reasons={2: [ReviewDetail(check="Duplicate", message="reason c")]},
    )
    at.session_state["run_result_for"] = "Test Client"
    at.run()
    assert not at.exception

    cards = [m for m in at.metric if m.label in {"Leads In", "Valid", "Refunded", "Needs Review"}]
    assert [m.label for m in cards] == ["Leads In", "Valid", "Refunded", "Needs Review"]
    assert [m.value for m in cards] == ["3", "1", "1", "1"]
    assert [m.proto.icon for m in cards] == [
        ":material/group:", ":material/check_circle:", ":material/undo:", ":material/flag:"]
    assert all(m.proto.show_border for m in cards)
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_run_check_page.py -q -k "stepper or metric_cards"`
Expected: 4 failures. There's no `Review & Finalize` markdown containing badge markup (the old one is `⚪ 2. Review & Finalize`, so the equality/`in` checks fail), and there's no `icon`/`show_border` on the metrics.

- [ ] **Step 4: Implement**

4a. Add the import next to the other `core` imports, alphabetically after `core.toast`:

```python
from core.ui_components import render_metric_cards, render_stepper
```

4b. Replace the rendering loop (current lines 204-211):

```python
_step_cols = st.columns(len(_step_labels))
for _step_num, (_step_col, _step_label) in enumerate(zip(_step_cols, _step_labels), start=1):
    if _step_num < _step_current:
        _step_col.markdown(f"✅ {_step_num}. {_step_label}")
    elif _step_num == _step_current:
        _step_col.markdown(f"**➡️ {_step_num}. {_step_label}**")
    else:
        _step_col.markdown(f"⚪ {_step_num}. {_step_label}")
```

with:

```python
render_stepper(_step_labels, _step_current)
```

The comment block above `_step_current` ("A lightweight progress indicator, not a tracked workflow state...") and the `st.divider()` below stay as they are.

4c. Replace the four metric lines (current lines 501-505):

```python
    _summary_col_in, _summary_col_valid, _summary_col_refund, _summary_col_review = st.columns(4)
    _summary_col_in.metric("Leads In", len(new_leads))
    _summary_col_valid.metric("Valid", len(result.valid_indices))
    _summary_col_refund.metric("Refunded", len(result.refund_reasons))
    _summary_col_review.metric("Needs Review", len(result.review_reasons))
```

with:

```python
    render_metric_cards([
        ("Leads In", len(new_leads), "group"),
        ("Valid", len(result.valid_indices), "check_circle"),
        ("Refunded", len(result.refund_reasons), "undo"),
        ("Needs Review", len(result.review_reasons), "flag"),
    ])
```

`st.subheader("Summary")` above it and the `_completed_checks` caption below it stay as they are.

- [ ] **Step 5: Verify the diff is purely presentational**

Run: `git diff -w pages/2_Run_Check.py`
Expected, and nothing else:
- one added import line;
- the 8-line stepper loop replaced by one `render_stepper(...)` line;
- the 5 metric lines replaced by the 6-line `render_metric_cards([...])` call.

- [ ] **Step 6: Run to verify everything passes**

Run: `python -m pytest tests/test_run_check_page.py -q`
Expected: all 44 existing tests plus the 4 new ones pass, **with no edits to existing tests**. Pay particular attention to `test_completed_checks_status_shown_for_enabled_checks_only` and both client-picker tests.

Run: `python -m pytest -q`
Expected: full suite green.

- [ ] **Step 7: Manual smoke check.** Run `streamlit run Summary.py` and open Run Check. Check the stepper in three states:
- no file;
- after Run Check (step 2);
- after Finalize for a client with a Jira key (step 3).

Check that each badge shows its Material icon rather than literal `:material/...:` text. Check that the four metric cards are bordered with icons. Repeat in the dark theme.

If a badge shows the icon markup as literal text, drop the `:material/{icon}: ` prefix from `stepper_markdown` and keep the colour-only badges. Update the Task 1 and Task 4 expected strings to match, and record the fallback in the commit message.

- [ ] **Step 8: Commit**

```bash
git add pages/2_Run_Check.py tests/test_run_check_page.py
git commit -m "Replace Run Check's step indicator with a visual stepper and show metric cards"
```

---

### Task 5: Run Check — Needs Review row-level decisions next to bulk actions (HIGH RISK)

**Files:**
- Modify: `pages/2_Run_Check.py`
- Test: `tests/test_run_check_page.py` (append new tests only)

**Current UX, for reference (lines 585-663):**
- A `st.data_editor` with a `Select` checkbox column plus read-only Row/Email/Company/CID/Reasons columns.
- Select all / Clear selection / ⬇️ Download above the table.
- **Approve N selected as valid** / **Mark N selected as refund** below it.
- A nonce bump resets the editor after each action.

Deciding 3 leads one way and 2 the other currently takes two tick-and-act passes.

**New UX:**
- A new editable **Action** column is added as the last column, after Reasons, so the user reads the reason before deciding. It's a selectbox with options `Approve as valid` / `Mark as refund`, blank by default.
- One **Apply N row decision(s)** button (key `review_apply_row_actions`) applies every row's decision in one click. It's disabled at 0.
- Everything in the bulk flow stays as it is: Select column, Select all, Clear selection, Download, and both bulk buttons with their keys and labels.
- Each path acts only on its own column: row-apply ignores Select, and bulk ignores Action. Either one bumps the nonce, which clears all pending ticks and picks. The caption says so.
- **No per-row buttons.** See Global Constraints item 1: they were removed deliberately in `3da390b`, and a test checks that.

**Interfaces:** consumes `REVIEW_ACTIONS`, `approve_review_leads`, `refund_review_leads` and `split_row_actions` (Task 3).

- [ ] **Step 1: Pin today's bulk-refund behaviour.** No page-level test covers `review_bulk_refund` yet. Append these helpers and the characterization test. They should **pass against the current code** before anything changes.

```python
def _two_review_leads_page(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    _make_accumulated_report(acc_path)
    fm = FieldMapping(email="Email_Address", first_name="First_Name", last_name="Last_Name",
                       company="Company_Name", cid="CID")
    save_profile(ClientProfile(name="Test Client", accumulated_report_path=acc_path, field_mapping=fm),
                 get_clients_dir())
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["run_new_leads"] = pd.DataFrame([
        {"Email_Address": "a@x.com", "First_Name": "A", "Last_Name": "One", "Company_Name": "X", "CID": "1"},
        {"Email_Address": "b@x.com", "First_Name": "B", "Last_Name": "Two", "Company_Name": "Y", "CID": "1"},
    ])
    at.session_state["run_result"] = PipelineResult(valid_indices=[], refund_reasons={}, review_reasons={
        0: [ReviewDetail(check="Duplicate", message="reason a")],
        1: [ReviewDetail(check="Duplicate", message="reason b")],
    })
    at.session_state["run_result_for"] = "Test Client"
    return at, acc_path


def _review_only_editor(edited_review):
    # patch("streamlit.data_editor") replaces BOTH editors on the page. Hand
    # the canned table back only to the Needs Review editor (the only one
    # with a "Select" column) and pass every other table (e.g. the Refund
    # Reasons editor that appears after a lead is refunded) through unedited.
    def _editor(data, *args, **kwargs):
        return edited_review if "Select" in data.columns else data
    return _editor


def test_review_bulk_refund_selected_leads(tmp_path, monkeypatch):
    at, _ = _two_review_leads_page(tmp_path, monkeypatch)
    at.run()
    assert not at.exception
    edited = pd.DataFrame([
        {"Select": True, "Row": 2, "Email": "a@x.com", "Company": "X", "CID": "1", "Reasons": "Duplicate - reason a"},
        {"Select": False, "Row": 3, "Email": "b@x.com", "Company": "Y", "CID": "1", "Reasons": "Duplicate - reason b"},
    ])
    with patch("streamlit.data_editor", side_effect=_review_only_editor(edited)):
        next(b for b in at.button if b.key == "review_bulk_refund").click().run()
    assert not at.exception

    result = at.session_state["run_result"]
    assert result.refund_reasons == {0: "Duplicate - reason a"}
    assert list(result.review_reasons) == [1]
    assert result.valid_indices == []
```

Run: `python -m pytest tests/test_run_check_page.py -q -k "bulk_refund_selected or bulk_approve_selected"`
Expected: 2 passed, against **unchanged** page code. If the new one fails, fix the test harness, not the page: this test describes today's behaviour.

- [ ] **Step 2: Route the existing bulk buttons through the shared helpers (refactor, no behaviour change).**

Add the import:

```python
from core.review_actions import REVIEW_ACTIONS, approve_review_leads, refund_review_leads, split_row_actions
```

In the `review_bulk_approve` handler, replace

```python
                for idx in selected_review_indices:
                    result.valid_indices.append(idx)
                    del result.review_reasons[idx]
```

with `approve_review_leads(result, selected_review_indices)`.

In the `review_bulk_refund` handler, replace

```python
                for idx in selected_review_indices:
                    result.refund_reasons[idx] = "; ".join(str(d) for d in result.review_reasons[idx])
                    del result.review_reasons[idx]
```

with `refund_review_leads(result, selected_review_indices)`.

Both handlers keep the `review_all_selected_default = False` / nonce bump / `st.rerun()` lines unchanged.

Run: `python -m pytest tests/test_run_check_page.py -q`
Expected: all pass. The two bulk tests prove the refactor is behaviour-neutral.

- [ ] **Step 3: Write the failing tests for row decisions** (append)

```python
def test_needs_review_table_offers_a_per_row_action_column(tmp_path, monkeypatch):
    at, _ = _two_review_leads_page(tmp_path, monkeypatch)
    calls = []

    def _spy(data, *args, **kwargs):
        calls.append((data, kwargs))
        return data

    with patch("streamlit.data_editor", side_effect=_spy):
        at.run()
    assert not at.exception

    review_data, review_kwargs = next((d, k) for d, k in calls if "Select" in d.columns)
    assert list(review_data.columns) == ["Select", "Row", "Email", "Company", "CID", "Reasons", "Action"]
    assert review_data["Action"].isna().all()  # blank by default
    assert "Action" not in review_kwargs["disabled"]
    assert review_kwargs["column_config"]["Action"]["type_config"] == {
        "type": "selectbox", "options": ["Approve as valid", "Mark as refund"]}

    apply_button = next(b for b in at.button if b.key == "review_apply_row_actions")
    assert apply_button.label == "Apply 0 row decision(s)"
    assert apply_button.disabled is True
    # The bulk select-and-act flow stays alongside it, untouched.
    assert {"review_select_all", "review_clear_all", "review_bulk_approve", "review_bulk_refund"} <= {
        b.key for b in at.button}


def test_row_decisions_approve_and_refund_in_one_click_then_finalize_writes_both(tmp_path, monkeypatch):
    at, acc_path = _two_review_leads_page(tmp_path, monkeypatch)
    at.run()
    edited = pd.DataFrame([
        {"Select": False, "Row": 2, "Email": "a@x.com", "Company": "X", "CID": "1",
         "Reasons": "Duplicate - reason a", "Action": "Approve as valid"},
        {"Select": False, "Row": 3, "Email": "b@x.com", "Company": "Y", "CID": "1",
         "Reasons": "Duplicate - reason b", "Action": "Mark as refund"},
    ])
    with patch("streamlit.data_editor", side_effect=_review_only_editor(edited)):
        next(b for b in at.button if b.key == "review_apply_row_actions").click().run()
    assert not at.exception

    result = at.session_state["run_result"]
    assert result.valid_indices == [0]
    assert result.refund_reasons == {1: "Duplicate - reason b"}
    assert result.review_reasons == {}

    # The existing write path is unchanged: Finalize sends each lead where
    # the row decision put it.
    next(b for b in at.button if b.label == "Finalize").click().run()
    assert not at.exception
    wb = openpyxl.load_workbook(acc_path)
    acc_emails = {r[0] for r in wb["Accumulated"].iter_rows(min_row=2, values_only=True) if r[0] is not None}
    refund_emails = {r[0] for r in wb["Refund"].iter_rows(min_row=2, values_only=True) if r[0] is not None}
    assert "a@x.com" in acc_emails
    assert refund_emails == {"b@x.com"}


def test_row_decisions_ignore_select_ticks_and_leave_undecided_rows_in_review(tmp_path, monkeypatch):
    at, _ = _two_review_leads_page(tmp_path, monkeypatch)
    at.run()
    edited = pd.DataFrame([
        {"Select": True, "Row": 2, "Email": "a@x.com", "Company": "X", "CID": "1",
         "Reasons": "Duplicate - reason a", "Action": None},
        {"Select": False, "Row": 3, "Email": "b@x.com", "Company": "Y", "CID": "1",
         "Reasons": "Duplicate - reason b", "Action": "Approve as valid"},
    ])
    with patch("streamlit.data_editor", side_effect=_review_only_editor(edited)):
        next(b for b in at.button if b.key == "review_apply_row_actions").click().run()
    assert not at.exception

    result = at.session_state["run_result"]
    assert result.valid_indices == [1]
    assert list(result.review_reasons) == [0]  # ticked but undecided -> still needs review
    assert result.refund_reasons == {}
```

- [ ] **Step 4: Run to verify they fail**

Run: `python -m pytest tests/test_run_check_page.py -q -k "row_action or row_decisions"`
Expected: 3 failures. The column list doesn't match (there's no `Action`), and `StopIteration` is raised for key `review_apply_row_actions`.

- [ ] **Step 5: Implement.** Inside `if result.review_reasons:`, make these edits.

5a. Replace the caption `st.caption("Tick leads below, then act on them in bulk.")` (no test asserts on it) with:

```python
        st.caption("Pick an **Action** for individual leads and click **Apply row decisions**, or tick "
                   "**Select** on several and act on them in bulk. Either one resets the other's picks.")
```

5b. In the `review_table = pd.DataFrame([...])` row dict, add `"Action": None,` as the **last** key, after `"Reasons"`. Directly after the DataFrame is built, add:

```python
        # An all-None column would serialise as Arrow's null type; a string
        # column gives the Action selectbox a blank, editable start.
        review_table["Action"] = review_table["Action"].astype("string")
```

5c. In the `st.data_editor(...)` call, replace the `column_config=` argument with the one below. `disabled=` stays exactly `["Row", "Email", "Company", "CID", "Reasons"]`.

```python
            column_config={
                "Select": st.column_config.CheckboxColumn(required=True),
                "Action": st.column_config.SelectboxColumn(
                    options=list(REVIEW_ACTIONS), required=False,
                    help="Decide just this lead, then click Apply row decisions below."),
            },
```

5d. Directly after the unchanged `selected_review_indices = [...]` list, and before `col_bulk_valid, col_bulk_refund = st.columns(2)`, insert:

```python
        # .get(): a returned table with no Action column (as the page's
        # existing st.data_editor-patching tests produce) means no row decisions.
        row_approve_indices, row_refund_indices = split_row_actions(
            review_indices, edited_review_table.get("Action", []))
        row_decision_count = len(row_approve_indices) + len(row_refund_indices)
        if st.button(f"Apply {row_decision_count} row decision(s)", key="review_apply_row_actions",
                     use_container_width=True, disabled=not row_decision_count):
            approve_review_leads(result, row_approve_indices)
            refund_review_leads(result, row_refund_indices)
            st.session_state["review_all_selected_default"] = False
            st.session_state["review_editor_nonce"] += 1
            st.rerun()
```

Everything else in the block stays as it is: the nonce setup, Select all / Clear selection / Download, and both bulk buttons after Step 2.

- [ ] **Step 6: Verify the diff is scoped**

Run: `git diff -w pages/2_Run_Check.py`
Expected, for this task only, and nothing else:
- one import line;
- the caption text;
- `"Action": None,` plus the `astype` line and its comment;
- the `column_config` dict;
- the inserted row-decision block;
- the two bulk loops collapsed into helper calls.

- [ ] **Step 7: Run to verify everything passes**

Run: `python -m pytest tests/test_run_check_page.py -q`
Expected: all existing tests plus the 8 new ones from Tasks 4-5 pass, **with no edits to existing tests**. Check these three in particular:
- `test_review_bulk_approve_selected_leads` (a patched table with no Action column);
- `test_review_download_button_and_refund_download_button_present` (no new download button, no `approve_1`);
- `test_approved_refund_lead_lands_in_accumulated_tab_not_just_refund` (refund editor unaffected).

If anything fails, use `superpowers:systematic-debugging` before changing code.

Run: `python -m pytest -q`
Expected: full suite green.

- [ ] **Step 8: Manual smoke check.** This is the only way to confirm the Action cell really opens a dropdown from a blank `string`-dtype start, since AppTest can't drive `st.data_editor`. Run `streamlit run Summary.py` and use a client whose run produces at least 3 Needs Review leads.

1. Set one row to Approve and one to Refund. The button should read "Apply 2 row decision(s)". Click it and confirm the metric cards and tables update.
2. Tick one remaining row and use **Mark 1 selected as refund**. Confirm bulk still works.
3. Clear the remaining reviews and Finalize. Confirm the Accumulated and Refund tabs.

**Fallback:** if the Action cell isn't editable, build the column as `pd.Categorical([None] * len(review_table), categories=list(REVIEW_ACTIONS))` instead of the `astype("string")` line. `split_row_actions` already treats NaN as blank. Record the fallback in the commit message.

- [ ] **Step 9: Commit**

```bash
git add pages/2_Run_Check.py tests/test_run_check_page.py
git commit -m "Add per-row Action decisions to Run Check's Needs Review table alongside bulk actions"
```

---

## Self-Review Notes

- **Spec coverage (section 5):**
  - Visual stepper: Task 1 builds the component and Task 4 wires it in, replacing the `✅`/`**➡️**`/`⚪` markdown-in-columns loop.
  - Metric cards: Task 2 builds the component and Task 4 wires it in. The page already used `st.metric`, so "bare numbers" means no border, no icon and no card treatment. Labels are unchanged.
  - Needs Review row-level controls next to bulk: Task 3 builds the shared helpers and Task 5 wires them in.
  - Client picker: out of scope and untouched. Both existing picker tests are named as regression checks in Tasks 4 and 5.
- **Departures from, or interpretations of, the spec:**
  - "Row-level action controls" became an inline Action column plus one Apply button, **not** per-row buttons. Per-row buttons (the old per-lead expander) were deliberately removed in `3da390b` as redundant with the bulk table, and an existing test checks they stay gone. The Action column is the "clean fit" the spec allows: one decision per row, made in the same table, with no parallel UI.
  - `core/review_actions.py` is a new `core/` module. It holds page-level review resolution copied verbatim from the page, not check logic. The spec's "no change to check logic" still holds: `run_pipeline`, `core/checks/*`, `apply_refund_overrides` and every write path are untouched. Task 5 Step 1 pins bulk-refund behaviour before the refactor, and the existing bulk-approve test pins the other path.
  - Left alone on purpose, for Phase 4 or never, because they're outside section 5:
    - the `▶️ Run Check` title;
    - `🔄 Clear` and the other emoji button labels, some of which tests match exactly (e.g. `"⬇️ Download"`);
    - the `✅ ... — all completed` caption, which `test_completed_checks_status_shown_for_enabled_checks_only` counts;
    - Run Check's ad hoc `st.error`/`st.warning` calls.
- **Placeholder scan:** every step has real code or an exact command. The only conditional wording is two flagged fallbacks, each with concrete replacement code: badge icon markup rendering literally (Task 4 Step 7) and the Action cell not being editable (Task 5 Step 8).
- **Type consistency:**
  - `StepState` values `"done"`/`"current"`/`"todo"` match across `step_state`, `_STEPS` and `stepper_markdown`.
  - `render_stepper(steps: list[str], current: int)` is called with `_step_labels` (`list[str]`) and `_step_current` (`int`).
  - `render_metric_cards(items: list[tuple[str, int, str]])` is called with `(label, len(...), icon)` tuples.
  - `split_row_actions(indices, actions) -> (approve, refund)` feeds `approve_review_leads(result, ...)` and `refund_review_leads(result, ...)`, which take the same `PipelineResult` the bulk handlers already mutate.
  - `REVIEW_ACTIONS` is the single source for the selectbox options and the matched strings. The tests assert the literal `["Approve as valid", "Mark as refund"]`.
- **Test preservation strategy:**
  - The pieces tests pin by exact text are left alone: button labels and keys, download labels, captions containing "completed" or "Enabled checks", subheaders, and the client picker.
  - The pieces no test pins are pure visual replacements: the step indicator and the metric presentation. Task 4 Step 1 re-checks this with grep.
  - The one harness-sensitive change is the Needs Review editor's new column. It's absorbed by `DataFrame.get("Action", [])`, and new tests avoid the both-editors patch trap with `_review_only_editor`.
  - Same rule as Phases 1 and 2: if an existing test has to change, the design is wrong, not the test.

### Critical Files for Implementation
- `pages/2_Run_Check.py`
- `tests/test_run_check_page.py`
- `core/ui_components.py`
- `core/review_actions.py` (new)
- `tests/test_review_actions.py` (new), plus appended tests in `tests/test_ui_components.py`

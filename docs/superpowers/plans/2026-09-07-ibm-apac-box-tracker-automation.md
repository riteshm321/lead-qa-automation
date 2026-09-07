# IBM APAC Box Tracker Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate the parts of IBM APAC's Complex Account leadflow that don't require touching the real Box tracker file directly: TAL-based Segment backfill, picking the right leads for client approval based on the Box tracker's own Pacing formulas, and preparing the Response Details/Pacing updates after the client's decision and portal upload — all against a **local mirror workbook** that is copy-pasted into the real Box file by hand, never written to directly (no Box API access exists yet — see 2026-09-01 design discussion in-session; this is a deliberate, agreed scope boundary, not an oversight).

**Architecture:** New pure functions in `core/complex_account.py` (TAL segment index) and a new `core/box_tracker.py` module (CID→Campaign map, Pacing reading, pick/shortfall logic, generic mirror-workbook row writer). A new `BoxTrackerConfig` dataclass on `ClientProfile` holds the CID map and the local mirror workbook's path, edited from Client Setup. A new dedicated page, `pages/5_Box_Tracker.py`, drives the actual workflow (pick → write Approval Sheet mirror + set Pacing → manual "cleared for Lead Template" gate → batch upload-status reconciliation → write Response Details mirror + set Pacing final), since this workflow's shape (multi-stage, spans two mirrored files, has manual human gates) doesn't fit the existing single-pass Run Check page.

**Tech Stack:** Python, Streamlit, pandas, openpyxl — same as the rest of this codebase. No new external dependencies.

## Global Constraints

- **No Box API / live sync in this phase.** Every write happens on a local mirror workbook (a plain `.xlsx` the tool fully owns); the user copy-pastes ranges into the real Box file by hand. Do not add any Box/Google API calls, credentials, or "sync" behavior — that's an explicitly deferred future phase.
- **Lead Template column mapping is out of scope for this plan.** The user will define it later. The "cleared for Lead Template" step in this plan only tags/exports which leads are cleared — it does not write a Lead Template file.
- **TAL Segment backfill only fills blanks.** A lead that already has a non-blank `Segment` value is left untouched.
- **CID → Campaign map** (exact values, from the live Box file): `118741`→`Bob`, `118742`→`CXO`, `118743`→`wxO (AI Pod) IN`, `118744`→`Hashicorp Solutions (Secure Pod) IN`, `118745`→`wxO (AI Pod) AU`, `118747`→`Hashicorp Solutions (Secure Pod) AU`. Stored per-client (not hardcoded), since a different Complex Account client would have its own map.
- **Diff-based picking is per-campaign-column, and dynamic.** The count to pick for a campaign = (that campaign's `Diff` value from the Pacing summary block) + 5. Which campaigns are pickable is whatever columns currently exist in that summary block — not a hardcoded list of 3 or 6. When the user adds more campaign columns to the mirror's Pacing summary block later, the tool picks those up automatically.
- **Shortfall handling:** if fewer than the target count are available (blank `Status`, matching CID) in Accumulated, take all available and report which CID(s) fell short and by how much. Never raise an error or block the run over a shortfall.
- **Status label format:** exactly `"Sent for Approval - {date}"` where `{date}` is today's date formatted `%d-%b` (e.g. `07-Sep`), written into Accumulated's `Status` column (column D) for every picked lead, at pick time.
- **Pacing's current-week `Delivered` (`D`) cell is `set`, not incremented,** at exactly two points per campaign: (1) to the count sent to the Approval Sheet mirror, (2) later overwritten to the final Response Details count once upload status is known. Never write to the `Pending` (`P`) column — that's a manually-maintained target, out of scope.
- **"Current week" resolution:** the Pacing grid's week columns are labeled `"Week of {N}"` where `N` is the day-of-month of that week's Monday. Resolve "this week" by finding the most recent Monday on or before today and matching `N` to its day-of-month.
- Every new function needs a docstring stating what it does and why, matching this codebase's existing style (see `core/complex_account.py` for the tone/format to match) — no bare one-liners on non-trivial logic.

---

## Task 1: TAL Segment backfill from a multi-tab TAL workbook

**Files:**
- Modify: `core/complex_account.py`
- Test: `tests/test_complex_account.py`

**Interfaces:**
- Produces: `load_tal_segment_index(tal_path: str, domain_column: str = "company_domain") -> dict[str, str]` and `fill_blank_segments(leads_df: pd.DataFrame, email_column: str, segment_index: dict[str, str], segment_column: str = "Segment") -> pd.DataFrame`, both importable from `core.complex_account`.
- Consumes: `_norm_domain` (existing, same file) and `extract_domain` (existing import, same file).

- [x] **Step 1: Write the failing tests**

Add to `tests/test_complex_account.py`:

```python
def test_load_tal_segment_index_reads_all_matching_tabs(tmp_path):
    from core.complex_account import load_tal_segment_index

    path = str(tmp_path / "tal.xlsx")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sheet_name, domain in [
        ("TAL Q3 Select T IN", "selectin.com"),
        ("TAL Q3 Select T AU", "selectau.com"),
        ("TAL Named IN", "namedin.com"),
        ("TAL Named AU", "namedau.com"),
    ]:
        ws = wb.create_sheet(sheet_name)
        ws.append(["company_domain", "location"])
        ws.append([domain, "somewhere"])
    wb.save(path)

    index = load_tal_segment_index(path)

    assert index == {
        "selectin.com": "SelectT",
        "selectau.com": "SelectT",
        "namedin.com": "Named",
        "namedau.com": "Named",
    }


def test_load_tal_segment_index_ignores_unrecognized_tabs(tmp_path):
    from core.complex_account import load_tal_segment_index

    path = str(tmp_path / "tal.xlsx")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Some Other Tab")
    ws.append(["company_domain"])
    ws.append(["ignored.com"])
    wb.save(path)

    assert load_tal_segment_index(path) == {}


def test_fill_blank_segments_only_fills_blanks_by_domain():
    from core.complex_account import fill_blank_segments

    leads_df = pd.DataFrame([
        {"Email": "a@selectin.com", "Segment": ""},
        {"Email": "b@namedin.com", "Segment": "AlreadySet"},
        {"Email": "c@unknown.com", "Segment": ""},
    ])
    segment_index = {"selectin.com": "SelectT", "namedin.com": "Named"}

    result = fill_blank_segments(leads_df, "Email", segment_index)

    assert result.loc[0, "Segment"] == "SelectT"
    assert result.loc[1, "Segment"] == "AlreadySet"
    assert result.loc[2, "Segment"] == ""
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_complex_account.py -k "tal_segment_index or fill_blank_segments" -v`
Expected: FAIL with `ImportError`/`AttributeError` (`load_tal_segment_index`/`fill_blank_segments` don't exist yet).

- [x] **Step 3: Implement the two functions**

Add to `core/complex_account.py`, after `apply_tal_mapping` (so it sits alongside the other TAL-related functions):

```python
# A different TAL shape from Dell's flat CSV (load_tal_index above): one
# tab per tiering segment, tab name carrying an IN/AU country suffix that
# doesn't affect the segment label itself. Matched by substring so the
# exact tab names ("TAL Q3 Select T IN", "TAL Named AU", ...) can keep
# drifting (e.g. the quarter number) without breaking this.
_SEGMENT_TAB_MARKERS = [
    ("select t", "SelectT"),
    ("named", "Named"),
]


def _segment_label_for_tab(sheet_name: str) -> str | None:
    normalized = sheet_name.strip().lower()
    for marker, label in _SEGMENT_TAB_MARKERS:
        if marker in normalized:
            return label
    return None


def load_tal_segment_index(tal_path: str, domain_column: str = "company_domain") -> dict[str, str]:
    """Loads a multi-tab TAL workbook (one tab per tiering segment) into a
    domain -> segment label ("SelectT"/"Named") index, for clients (e.g.
    IBM APAC) whose TAL classifies accounts by which SHEET they're listed
    on rather than by an in-sheet tier column. A tab whose name doesn't
    match a known segment marker (see _SEGMENT_TAB_MARKERS) is skipped
    entirely -- this workbook can carry other, unrelated tabs.
    """
    wb = openpyxl.load_workbook(tal_path, read_only=True, data_only=True)
    try:
        index: dict[str, str] = {}
        for sheet_name in wb.sheetnames:
            label = _segment_label_for_tab(sheet_name)
            if label is None:
                continue
            ws = wb[sheet_name]
            header_row = next(ws.iter_rows(min_row=1, max_row=1), None)
            if header_row is None:
                continue
            headers = [cell.value for cell in header_row]
            domain_col_idx = next(
                (i for i, h in enumerate(headers)
                 if _normalize_header_text(h) == _normalize_header_text(domain_column)),
                None,
            )
            if domain_col_idx is None:
                continue
            for row in ws.iter_rows(min_row=2, values_only=True):
                if domain_col_idx >= len(row):
                    continue
                domain = _norm_domain(row[domain_col_idx])
                if domain:
                    index[domain] = label
    finally:
        wb.close()
    return index


def fill_blank_segments(
    leads_df: pd.DataFrame, email_column: str, segment_index: dict[str, str],
    segment_column: str = "Segment",
) -> pd.DataFrame:
    """Fills segment_column for every lead whose value is blank, by
    looking up that lead's email domain in segment_index (see
    load_tal_segment_index). A lead with no TAL match, or one that already
    has a Segment value, is left untouched -- this only backfills gaps,
    never overwrites an existing value.
    """
    if segment_column not in leads_df.columns:
        return leads_df
    df = leads_df.copy()
    for idx, row in df.iterrows():
        if str(row.get(segment_column) or "").strip():
            continue
        domain = _norm_domain(extract_domain(row.get(email_column)))
        label = segment_index.get(domain)
        if label:
            df.at[idx, segment_column] = label
    return df
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_complex_account.py -k "tal_segment_index or fill_blank_segments" -v`
Expected: PASS

- [x] **Step 5: Wire it into `apply_complex_account_rules` as an optional parameter**

Modify the signature (around line 443) to add one new parameter:

```python
def apply_complex_account_rules(
    leads_df: pd.DataFrame,
    field_mapping,
    tal_index: dict[str, list[dict]] | None,
    installed_tech_map: dict[str, str],
    pbs_map: dict[str, str],
    asset_specs: dict[str, dict] | None = None,
    tal_segment_index: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, dict[int, list[ReviewDetail]], dict[int, list[str]]]:
```

Update the docstring's summary line to add: `tal_segment_index (if given) backfills any blank Segment value by email domain -- see fill_blank_segments.` Then, right after the existing `if tal_index is not None:` block (around line 484-485), add:

```python
    if tal_segment_index is not None:
        df = fill_blank_segments(df, field_mapping.email, tal_segment_index)
```

- [x] **Step 6: Write a test for the wiring**

Add to `tests/test_complex_account.py`:

```python
def test_apply_complex_account_rules_backfills_blank_segment(tmp_path):
    from core.complex_account import apply_complex_account_rules
    from core.models import FieldMapping

    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    leads_df = pd.DataFrame([
        {"Email": "a@selectin.com", "First": "A", "Last": "One", "Company": "X", "CID": "1", "Segment": ""},
    ])
    segment_index = {"selectin.com": "SelectT"}

    enriched, _, _ = apply_complex_account_rules(
        leads_df, fm, tal_index=None, installed_tech_map={}, pbs_map={},
        tal_segment_index=segment_index,
    )

    assert enriched.loc[0, "Segment"] == "SelectT"
```

- [x] **Step 7: Run the full complex-account test file and verify all pass**

Run: `python -m pytest tests/test_complex_account.py -v`
Expected: PASS (all tests, including pre-existing ones — this change is purely additive).

- [x] **Step 8: Commit**

```bash
git add core/complex_account.py tests/test_complex_account.py
git commit -m "Add TAL Segment backfill for multi-tab TAL workbooks (IBM APAC)"
```

---

## Task 2: `BoxTrackerConfig` data model and Client Setup UI

**Files:**
- Modify: `core/models.py`
- Modify: `core/profile_store.py`
- Modify: `pages/1_Client_Setup.py`
- Test: `tests/test_models.py` (create if it doesn't already cover `ClientProfile` round-tripping — check first; if a suitable round-trip test already exists elsewhere, e.g. `tests/test_profile_store.py`, add there instead)

**Interfaces:**
- Produces: `BoxTrackerConfig` dataclass (fields below), a `box_tracker: BoxTrackerConfig` field on `ClientProfile`, round-tripped by `save_profile`/`load_profile`.
- Consumes: existing `atomic_write_json`/dataclass patterns already used for `ComplexAccountConfig`.

- [x] **Step 1: Check what profile round-trip tests already exist**

Run: `python -m pytest --collect-only -q | grep -i profile_store`

If a file like `tests/test_profile_store.py` exists, add the new test there in Step 6 below. If not, add it to whichever existing test file already covers `save_profile`/`load_profile` round-tripping `ComplexAccountConfig` (search `tests/` for `ComplexAccountConfig` to find it) — do not create a new test file for one test.

- [x] **Step 2: Add the dataclass**

In `core/models.py`, add after `ComplexAccountConfig`:

```python
@dataclass
class BoxTrackerConfig:
    # IBM APAC's process (and any future similar Complex Account client)
    # pastes picked leads into a client-facing Box-hosted tracker workbook
    # for approval, then logs accepted leads back into it after upload --
    # but this app has no Box API access, so it maintains a LOCAL mirror
    # workbook with the same tab/column shape instead, and the user
    # copy-pastes between the two by hand. See
    # docs/superpowers/plans/2026-09-07-ibm-apac-box-tracker-automation.md
    # for the full design.
    enabled: bool = False
    mirror_workbook_path: str = ""
    # {CID: Campaign name}, e.g. {"118741": "Bob"} -- used both to sort
    # picked leads into the right Pacing/Approval-Sheet bucket and to fill
    # Response Details' Campaign Name column.
    cid_campaign_map: dict[str, str] = field(default_factory=dict)
```

- [x] **Step 3: Add the field to `ClientProfile`**

In `core/models.py`, add to `ClientProfile` right after `complex_account: ComplexAccountConfig = field(default_factory=ComplexAccountConfig)`:

```python
    box_tracker: BoxTrackerConfig = field(default_factory=BoxTrackerConfig)
```

- [x] **Step 4: Wire it into `profile_store.py`**

In `core/profile_store.py`, add `BoxTrackerConfig` to the import from `core.models` (alongside `ComplexAccountConfig`), then in `load_profile`, add right after the `complex_account=ComplexAccountConfig(**(data.get("complex_account") or {}))` line:

```python
        box_tracker=BoxTrackerConfig(**(data.get("box_tracker") or {})),
```

(Both go inside the same `ClientProfile(...)` constructor call — add as a new keyword argument.)

- [x] **Step 5: Run the full test suite to check nothing broke**

Run: `python -m pytest tests/ -k "profile_store or client_setup" -v`
Expected: PASS (this is purely additive — every existing profile lacks `box_tracker` in its JSON, and `data.get("box_tracker") or {}` handles that as an empty dict, defaulting the new dataclass).

- [x] **Step 6: Write the round-trip test**

Add (to the file identified in Step 1):

```python
def test_box_tracker_config_round_trips(tmp_path):
    from core.models import ClientProfile, FieldMapping, BoxTrackerConfig
    from core.profile_store import save_profile, load_profile

    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(
        name="IBM APAC", accumulated_report_path="acc.xlsx", field_mapping=fm,
        box_tracker=BoxTrackerConfig(
            enabled=True, mirror_workbook_path="mirror.xlsx",
            cid_campaign_map={"118741": "Bob", "118742": "CXO"},
        ),
    )
    save_profile(profile, str(tmp_path))

    loaded = load_profile("IBM APAC", str(tmp_path))

    assert loaded.box_tracker.enabled is True
    assert loaded.box_tracker.mirror_workbook_path == "mirror.xlsx"
    assert loaded.box_tracker.cid_campaign_map == {"118741": "Bob", "118742": "CXO"}


def test_box_tracker_config_defaults_when_absent_from_saved_json(tmp_path):
    # A profile saved before this feature existed has no "box_tracker" key
    # at all -- loading it must default cleanly, not raise.
    from core.models import ClientProfile, FieldMapping
    from core.profile_store import save_profile, load_profile
    import json, os

    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(name="Old Client", accumulated_report_path="acc.xlsx", field_mapping=fm)
    path = save_profile(profile, str(tmp_path))
    with open(path) as f:
        data = json.load(f)
    del data["box_tracker"]
    with open(path, "w") as f:
        json.dump(data, f)

    loaded = load_profile("Old Client", str(tmp_path))

    assert loaded.box_tracker.enabled is False
    assert loaded.box_tracker.cid_campaign_map == {}
```

- [x] **Step 7: Run the new tests to verify they pass**

Run: `python -m pytest <file from Step 1> -k "box_tracker" -v`
Expected: PASS

- [x] **Step 8: Add the Client Setup UI section**

In `pages/1_Client_Setup.py`, find the existing Complex Account section (the `complex_account_enabled` checkbox and its `if complex_account_enabled:` block — around line 658). Add a new, separate section right after it (still inside whatever outer `if` scopes that block, so it only shows for a client being edited):

```python
        st.divider()
        st.markdown("**Box Tracker (optional)** — for clients whose lead-approval process runs through "
                     "a Box-hosted tracker workbook this app can't write to directly. See "
                     "docs/superpowers/plans/2026-09-07-ibm-apac-box-tracker-automation.md.")
        box_tracker_enabled = st.checkbox(
            "This client uses a Box Tracker", value=profile.box_tracker.enabled if profile else False)
        box_tracker_mirror_path = ""
        box_tracker_cid_map: dict[str, str] = {}
        if box_tracker_enabled:
            box_tracker_mirror_path = _path_input_with_browse(
                "Local mirror workbook path", "box_tracker_mirror_path_input",
                profile.box_tracker.mirror_workbook_path if profile else "")
            st.caption("CID → Campaign name mapping (one per line, format `CID,Campaign Name`):")
            _existing_map_text = "\n".join(
                f"{cid},{name}" for cid, name in
                (profile.box_tracker.cid_campaign_map.items() if profile else {}.items())
            )
            _map_text = st.text_area(
                "CID to Campaign mapping", value=_existing_map_text, key="box_tracker_cid_map_input",
                label_visibility="collapsed", height=120)
            for _line in _map_text.splitlines():
                _line = _line.strip()
                if not _line or "," not in _line:
                    continue
                _cid, _name = _line.split(",", 1)
                box_tracker_cid_map[_cid.strip()] = _name.strip()
```

Then in the `ClientProfile(...)` construction further down (near where `complex_account=ComplexAccountConfig(...)` is built, around line 764), add:

```python
            box_tracker=BoxTrackerConfig(
                enabled=box_tracker_enabled,
                mirror_workbook_path=box_tracker_mirror_path if box_tracker_enabled else "",
                cid_campaign_map=box_tracker_cid_map if box_tracker_enabled else {},
            ),
```

And add `BoxTrackerConfig` to this file's existing `from core.models import (...)` line.

- [x] **Step 9: Manually verify in the running app**

Start the app (`streamlit run Summary.py`), open Client Setup, edit (or create) a client, enable "This client uses a Box Tracker", enter a mirror path and a couple of CID/Campaign lines, save, then re-open that same client and confirm the fields are pre-filled with what was saved.

- [x] **Step 10: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS

- [x] **Step 11: Commit**

```bash
git add core/models.py core/profile_store.py pages/1_Client_Setup.py tests/
git commit -m "Add BoxTrackerConfig (CID/Campaign map + mirror workbook path) to ClientProfile"
```

---

## Task 3: Reading the Pacing summary block and resolving "this week"

**Files:**
- Create: `core/box_tracker.py`
- Test: `tests/test_box_tracker.py`

**Interfaces:**
- Produces: `current_week_label(today: datetime.date) -> str`, `read_pacing_diffs(mirror_path: str, pacing_tab: str = "Pacing") -> dict[str, int]`, both importable from `core.box_tracker`. `read_pacing_diffs` returns `{campaign_name: diff_value}` for every campaign column present in the mirror's Pacing summary block.
- Consumes: `openpyxl` (already a project dependency).

- [x] **Step 1: Write the failing tests**

Create `tests/test_box_tracker.py`:

```python
import datetime
import openpyxl
import pytest

from core.box_tracker import current_week_label, read_pacing_diffs


def test_current_week_label_finds_the_most_recent_monday():
    # 2026-09-09 is a Wednesday; that week's Monday is 2026-09-07.
    assert current_week_label(datetime.date(2026, 9, 9)) == "Week of 7"


def test_current_week_label_when_today_is_the_monday():
    assert current_week_label(datetime.date(2026, 9, 7)) == "Week of 7"


def _make_pacing_workbook(path: str) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Pacing"
    # Summary block starting at row 13, matching the real Box tracker's
    # layout: row 13 = campaign name headers, row 14 = Pending,
    # row 15 = Delivered, row 16 = Diff.
    ws["B13"] = "Bob"
    ws["C13"] = "wxO (AI Pod) IN"
    ws["D13"] = "wxO (AI Pod) AU"
    ws["A14"], ws["B14"], ws["C14"], ws["D14"] = "Pending", 333, 179, 74
    ws["A15"], ws["B15"], ws["C15"], ws["D15"] = "Delivered", 320, 166, 63
    ws["A16"], ws["B16"], ws["C16"], ws["D16"] = "Diff", 13, 13, 11
    wb.save(path)


def test_read_pacing_diffs_reads_every_campaign_column(tmp_path):
    path = str(tmp_path / "mirror.xlsx")
    _make_pacing_workbook(path)

    diffs = read_pacing_diffs(path)

    assert diffs == {"Bob": 13, "wxO (AI Pod) IN": 13, "wxO (AI Pod) AU": 11}


def test_read_pacing_diffs_is_dynamic_to_however_many_columns_exist(tmp_path):
    # Adding a 4th campaign column must be picked up with no code change --
    # this is a Global Constraint of the whole feature, not just a nicety.
    path = str(tmp_path / "mirror.xlsx")
    _make_pacing_workbook(path)
    wb = openpyxl.load_workbook(path)
    ws = wb["Pacing"]
    ws["E13"] = "CXO"
    ws["E14"], ws["E15"], ws["E16"] = 50, 40, 10
    wb.save(path)

    diffs = read_pacing_diffs(path)

    assert diffs["CXO"] == 10
    assert len(diffs) == 4
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_box_tracker.py -v`
Expected: FAIL with `ModuleNotFoundError` (`core.box_tracker` doesn't exist yet).

- [x] **Step 3: Implement `core/box_tracker.py`**

```python
"""Automation for IBM APAC's Box-hosted lead-approval tracker workbook.

This app has no Box API access (see docs/superpowers/plans/
2026-09-07-ibm-apac-box-tracker-automation.md for why), so every function
here reads from or writes to a LOCAL MIRROR workbook that the user
maintains with the same tab/column shape as the real Box file, copying
ranges between the two by hand. Nothing in this module ever talks to Box.
"""
import datetime

import openpyxl

_PACING_SUMMARY_LABEL_ROW_OFFSET = {"Pending": 1, "Delivered": 2, "Diff": 3}


def current_week_label(today: datetime.date) -> str:
    """The Pacing tab's week columns are labeled "Week of {N}", where N is
    the day-of-month of that week's Monday. Resolves which label
    corresponds to "this week" for a given date.
    """
    monday = today - datetime.timedelta(days=today.weekday())
    return f"Week of {monday.day}"


def read_pacing_diffs(mirror_path: str, pacing_tab: str = "Pacing") -> dict[str, int]:
    """Reads the Pacing tab's Pending/Delivered/Diff summary block into
    {campaign_name: diff}, for however many campaign columns currently
    exist there -- this must stay dynamic (not a hardcoded campaign list),
    since the user adds new campaign columns to this block as new
    campaigns go live, and picking must pick those up automatically.

    Locates the block by searching column A for a "Diff" label rather
    than hardcoding row 16, since the row it lands on can drift as more
    campaign rows get added elsewhere in the sheet above it.
    """
    wb = openpyxl.load_workbook(mirror_path, read_only=True, data_only=True)
    try:
        ws = wb[pacing_tab]
        diff_row = None
        for row in ws.iter_rows(min_row=1, max_col=1):
            cell = row[0]
            if str(cell.value or "").strip().lower() == "diff":
                diff_row = cell.row
                break
        if diff_row is None:
            return {}
        header_row = diff_row - _PACING_SUMMARY_LABEL_ROW_OFFSET["Diff"]

        diffs: dict[str, int] = {}
        col = 2  # column B -- column A holds the row labels (Pending/Delivered/Diff)
        while True:
            campaign = ws.cell(row=header_row, column=col).value
            if not campaign:
                break
            diff_value = ws.cell(row=diff_row, column=col).value
            diffs[str(campaign).strip()] = int(diff_value) if diff_value is not None else 0
            col += 1
        return diffs
    finally:
        wb.close()
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_box_tracker.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add core/box_tracker.py tests/test_box_tracker.py
git commit -m "Add Pacing summary block reader and current-week resolver for Box Tracker"
```

---

## Task 4: Picking leads for approval, with shortfall reporting and Status marking

**Files:**
- Modify: `core/box_tracker.py`
- Test: `tests/test_box_tracker.py`

**Interfaces:**
- Produces: `pick_leads_for_approval(accumulated_df, cid_column, status_column, cid_campaign_map, diffs, buffer=5) -> tuple[pd.DataFrame, dict[str, int]]` (picked rows, {CID: shortfall_amount} for any CID that came up short) and `sent_for_approval_label(today) -> str`, both in `core.box_tracker`.
- Consumes: `read_pacing_diffs`'s output shape (`{campaign_name: diff}`) and `BoxTrackerConfig.cid_campaign_map`'s shape (`{cid: campaign_name}`) from Task 2/3.

- [x] **Step 1: Write the failing tests**

Add to `tests/test_box_tracker.py`:

```python
import pandas as pd

from core.box_tracker import pick_leads_for_approval, sent_for_approval_label


def test_sent_for_approval_label_format():
    assert sent_for_approval_label(datetime.date(2026, 9, 7)) == "Sent for Approval - 07-Sep"


def _accumulated_df(rows):
    return pd.DataFrame(rows)


def test_pick_leads_for_approval_picks_diff_plus_five_per_campaign():
    accumulated = _accumulated_df([
        {"CID": "118741", "Status": ""} for _ in range(20)
    ] + [
        {"CID": "118743", "Status": ""} for _ in range(20)
    ])
    cid_campaign_map = {"118741": "Bob", "118743": "wxO (AI Pod) IN"}
    diffs = {"Bob": 13, "wxO (AI Pod) IN": 13}

    picked, shortfall = pick_leads_for_approval(
        accumulated, "CID", "Status", cid_campaign_map, diffs, buffer=5)

    assert len(picked[picked["CID"] == "118741"]) == 18  # 13 + 5
    assert len(picked[picked["CID"] == "118743"]) == 18
    assert shortfall == {}


def test_pick_leads_for_approval_ignores_leads_with_a_non_blank_status():
    accumulated = _accumulated_df([
        {"CID": "118741", "Status": "Sent for Approval - 01-Sep"},
        {"CID": "118741", "Status": ""},
    ])
    picked, _ = pick_leads_for_approval(
        accumulated, "CID", "Status", {"118741": "Bob"}, {"Bob": 0}, buffer=5)

    assert len(picked) == 1


def test_pick_leads_for_approval_reports_shortfall_by_cid():
    accumulated = _accumulated_df([{"CID": "118741", "Status": ""} for _ in range(3)])
    diffs = {"Bob": 13}  # needs 13 + 5 = 18, only 3 available

    picked, shortfall = pick_leads_for_approval(
        accumulated, "CID", "Status", {"118741": "Bob"}, diffs, buffer=5)

    assert len(picked) == 3
    assert shortfall == {"118741": 15}  # needed 18, short by 15


def test_pick_leads_for_approval_ignores_cids_with_no_campaign_mapping():
    # A CID not in cid_campaign_map has no way to know its target count --
    # must be left alone, never picked, never reported as a shortfall.
    accumulated = _accumulated_df([{"CID": "999999", "Status": ""}])
    picked, shortfall = pick_leads_for_approval(
        accumulated, "CID", "Status", {"118741": "Bob"}, {"Bob": 13}, buffer=5)

    assert picked.empty
    assert shortfall == {}
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_box_tracker.py -k pick_leads_for_approval -v`
Expected: FAIL (`ImportError`).

- [x] **Step 3: Implement, appending to `core/box_tracker.py`**

```python
def sent_for_approval_label(today: datetime.date) -> str:
    return f"Sent for Approval - {today.strftime('%d-%b')}"


def pick_leads_for_approval(
    accumulated_df, cid_column: str, status_column: str,
    cid_campaign_map: dict[str, str], diffs: dict[str, int], buffer: int = 5,
) -> tuple:
    """Picks which blank-Status Accumulated leads go to the client for
    approval this cycle: for every CID with a known campaign mapping AND
    a Diff value for that campaign, picks (diff + buffer) leads with that
    CID and a blank status_column value.

    A CID with no entry in cid_campaign_map, or whose campaign has no
    entry in diffs (that campaign column doesn't exist in the Pacing
    summary block yet), is skipped entirely -- there's no target count to
    pick towards, so picking arbitrarily would be a guess, not a decision.

    Returns (picked_df, shortfall) where shortfall is {cid: amount_short}
    for every CID that had fewer than its target available -- picking
    still proceeds with whatever was available, this is purely a report
    for the caller to surface, never a reason to stop.
    """
    picked_frames = []
    shortfall: dict[str, int] = {}
    is_blank_status = accumulated_df[status_column].fillna("").astype(str).str.strip() == ""

    for cid, campaign in cid_campaign_map.items():
        if campaign not in diffs:
            continue
        target = diffs[campaign] + buffer
        candidates = accumulated_df[is_blank_status & (accumulated_df[cid_column].astype(str) == cid)]
        picked = candidates.head(target)
        if len(picked) < target:
            shortfall[cid] = target - len(picked)
        if not picked.empty:
            picked_frames.append(picked)

    if not picked_frames:
        return accumulated_df.iloc[0:0], shortfall
    import pandas as pd
    return pd.concat(picked_frames), shortfall
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_box_tracker.py -v`
Expected: PASS (all tests in the file, including Task 3's).

- [x] **Step 5: Commit**

```bash
git add core/box_tracker.py tests/test_box_tracker.py
git commit -m "Add diff-based lead picking with per-CID shortfall reporting"
```

---

## Task 5: Generic mirror-workbook row writer, and setting Pacing's Delivered cell

**Files:**
- Modify: `core/box_tracker.py`
- Test: `tests/test_box_tracker.py`

**Interfaces:**
- Produces: `append_mirror_rows(mirror_path: str, tab_name: str, rows: list[dict], header_row: int = 1) -> None` and `set_pacing_delivered(mirror_path: str, campaign: str, value: int, pacing_tab: str = "Pacing", week_label: str | None = None) -> None`, both in `core.box_tracker`.
- Consumes: `current_week_label` (Task 3).

This is deliberately a NEW, simpler writer rather than reusing `core/excel_io.py`'s `append_leads` — that function's header-matching is built around the accumulated/Lead-Template FieldMapping role model (email/first/last/company/cid), which doesn't fit the Approval Sheet's or Response Details' arbitrary business columns. Matching by exact header text (normalized) is sufficient here since these are the tool's own mirror files with known, fixed headers.

- [x] **Step 1: Write the failing tests**

Add to `tests/test_box_tracker.py`:

```python
from core.box_tracker import append_mirror_rows, set_pacing_delivered


def test_append_mirror_rows_matches_by_header_and_appends_after_last_row(tmp_path):
    path = str(tmp_path / "mirror.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Approval Sheet"
    ws.append(["Company Name", "Market", "Date", "Segment"])
    ws.append(["Existing Co", "IN", "01-Sep", "SelectT"])
    wb.save(path)

    append_mirror_rows(path, "Approval Sheet", [
        {"Company Name": "New Co", "Market": "AU", "Date": "07-Sep", "Segment": "Named"},
    ])

    wb2 = openpyxl.load_workbook(path)
    ws2 = wb2["Approval Sheet"]
    assert ws2.cell(row=3, column=1).value == "New Co"
    assert ws2.cell(row=3, column=2).value == "AU"
    assert ws2.cell(row=3, column=4).value == "Named"


def test_append_mirror_rows_leaves_unmatched_dict_keys_out(tmp_path):
    path = str(tmp_path / "mirror.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["A", "B"])
    wb.save(path)

    append_mirror_rows(path, "Sheet1", [{"A": "value", "NotAColumn": "ignored"}])

    wb2 = openpyxl.load_workbook(path)
    ws2 = wb2["Sheet1"]
    assert ws2.cell(row=2, column=1).value == "value"
    assert ws2.cell(row=2, column=2).value is None


def test_set_pacing_delivered_writes_the_current_weeks_column(tmp_path):
    path = str(tmp_path / "mirror.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Pacing"
    ws.append(["Funding Source", "Publisher", "Country", "Segment", "Campaign", "Week of 7", ""])
    ws.append([None, None, None, None, None, "P", "D"])
    ws.append(["Cash", "Madison Logic", "IN", "Select-T", "Bob", 18, 0])
    wb.save(path)

    set_pacing_delivered(path, "Bob", 18, week_label="Week of 7")

    wb2 = openpyxl.load_workbook(path)
    ws2 = wb2["Pacing"]
    assert ws2.cell(row=3, column=7).value == 18  # the "D" sub-column under "Week of 7"


def test_set_pacing_delivered_overwrites_not_adds(tmp_path):
    path = str(tmp_path / "mirror.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Pacing"
    ws.append(["Funding Source", "Publisher", "Country", "Segment", "Campaign", "Week of 7", ""])
    ws.append([None, None, None, None, None, "P", "D"])
    ws.append(["Cash", "Madison Logic", "IN", "Select-T", "Bob", 18, 18])
    wb.save(path)

    set_pacing_delivered(path, "Bob", 15, week_label="Week of 7")

    wb2 = openpyxl.load_workbook(path)
    assert wb2["Pacing"].cell(row=3, column=7).value == 15
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_box_tracker.py -k "append_mirror_rows or set_pacing_delivered" -v`
Expected: FAIL (`ImportError`).

- [x] **Step 3: Implement, appending to `core/box_tracker.py`**

```python
def append_mirror_rows(mirror_path: str, tab_name: str, rows: list[dict], header_row: int = 1) -> None:
    """Appends rows to a mirror workbook tab, matching each dict's keys to
    that tab's header cells by exact text (case/whitespace-insensitive) --
    unlike core/excel_io.py's append_leads, there's no FieldMapping role
    model here, just plain header-name matching, since these are the
    tool's own mirror files with fixed, known business-column headers
    (Company Name, Market, Segment, ...), not a generic leadfile.
    A dict key with no matching header is silently ignored; a header with
    no matching key is left blank for that row.
    """
    wb = openpyxl.load_workbook(mirror_path)
    try:
        ws = wb[tab_name]
        headers = [cell.value for cell in next(ws.iter_rows(min_row=header_row, max_row=header_row))]
        header_to_col = {
            str(h).strip().lower(): i + 1 for i, h in enumerate(headers) if h is not None
        }
        next_row = ws.max_row + 1
        for offset, row_dict in enumerate(rows):
            excel_row = next_row + offset
            for key, value in row_dict.items():
                col = header_to_col.get(str(key).strip().lower())
                if col is not None:
                    ws.cell(row=excel_row, column=col, value=value)
        wb.save(mirror_path)
    finally:
        wb.close()


def set_pacing_delivered(
    mirror_path: str, campaign: str, value: int,
    pacing_tab: str = "Pacing", week_label: str | None = None,
) -> None:
    """Sets (never adds to) the Delivered ("D") cell for `campaign`'s row,
    under `week_label`'s week block (defaults to the current week -- see
    current_week_label). The main Pacing grid pairs a "P" and "D"
    sub-column under each "Week of N" header; this locates the "D"
    sub-column by scanning the sub-header row for "D" starting at the
    "Week of N" column, then finds `campaign`'s row by scanning the
    Campaign column.
    """
    if week_label is None:
        week_label = current_week_label(datetime.date.today())

    wb = openpyxl.load_workbook(mirror_path)
    try:
        ws = wb[pacing_tab]
        header_row_idx = 1
        subheader_row_idx = 2

        week_col = next(
            (cell.column for cell in ws[header_row_idx] if str(cell.value or "").strip() == week_label),
            None,
        )
        if week_col is None:
            raise ValueError(f"No \"{week_label}\" column found in {pacing_tab!r}")

        d_col = None
        for col in range(week_col, ws.max_column + 1):
            sub = ws.cell(row=subheader_row_idx, column=col).value
            if str(sub or "").strip().upper() == "D":
                d_col = col
                break
            if str(sub or "").strip() and col > week_col:
                break  # ran into the next week block without finding "D"
        if d_col is None:
            raise ValueError(f"No \"D\" sub-column found under \"{week_label}\" in {pacing_tab!r}")

        campaign_col = next(
            (cell.column for cell in ws[header_row_idx] if str(cell.value or "").strip().lower() == "campaign"),
            None,
        )
        if campaign_col is None:
            raise ValueError(f"No \"Campaign\" column found in {pacing_tab!r}")

        for row in ws.iter_rows(min_row=subheader_row_idx + 1):
            if str(row[campaign_col - 1].value or "").strip() == campaign:
                ws.cell(row=row[0].row, column=d_col, value=value)
                break
        else:
            raise ValueError(f"No row for campaign {campaign!r} found in {pacing_tab!r}")

        wb.save(mirror_path)
    finally:
        wb.close()
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_box_tracker.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add core/box_tracker.py tests/test_box_tracker.py
git commit -m "Add mirror-workbook row appender and Pacing Delivered-cell setter"
```

---

## Task 6: The Box Tracker page — pick, write Approval Sheet mirror, mark Status, set Pacing

**Files:**
- Create: `pages/5_Box_Tracker.py`
- Test: `tests/test_box_tracker_page.py`

**Interfaces:**
- Consumes: everything from Tasks 1-5 (`read_pacing_diffs`, `pick_leads_for_approval`, `sent_for_approval_label`, `append_mirror_rows`, `set_pacing_delivered`), plus existing `list_profile_names`/`load_profile` (from `core.profile_store`) and `read_sheet_as_dataframe` (from `core.excel_io`) for loading the Accumulated Report.
- Produces: nothing new consumed elsewhere — this is a leaf page, same as `pages/2_Run_Check.py`.

This page only handles the picking → Approval Sheet mirror → Pacing (instance 1) stage. The manual "cleared for Lead Template" gate and the batch upload-status reconciliation (Refund + Response Details mirror + Pacing instance 2) are Task 7 — kept separate since Task 6 alone is a complete, independently useful, testable slice (you can run it and get a real Approval Sheet mirror to paste, without Task 7 existing yet).

- [x] **Step 1: Write the failing test**

Create `tests/test_box_tracker_page.py`:

```python
import os

import openpyxl
import pandas as pd
from streamlit.testing.v1 import AppTest

from core.app_settings import get_clients_dir
from core.models import ClientProfile, FieldMapping, BoxTrackerConfig, ComplexAccountConfig
from core.profile_store import save_profile

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages", "5_Box_Tracker.py")


def _make_accumulated(path: str, rows: list[dict]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Accumulated"
    ws.append(["Email", "First", "Last", "Company", "CID", "Status"])
    for row in rows:
        ws.append([row["Email"], row["First"], row["Last"], row["Company"], row["CID"], row.get("Status", "")])
    wb.save(path)


def _make_mirror(path: str) -> None:
    wb = openpyxl.Workbook()
    approval = wb.active
    approval.title = "Approval Sheet"
    approval.append(["Company Name", "Market", "Date", "Segment", "Job Title"])
    pacing = wb.create_sheet("Pacing")
    pacing.append(["Funding Source", "Publisher", "Country", "Segment", "Campaign", "Week of 7", ""])
    pacing.append([None, None, None, None, None, "P", "D"])
    pacing.append(["Cash", "Madison Logic", "IN", "Select-T", "Bob", 18, 0])
    pacing["B13"] = "Bob"
    pacing["A14"], pacing["B14"] = "Pending", 20
    pacing["A15"], pacing["B15"] = "Delivered", 7
    pacing["A16"], pacing["B16"] = "Diff", 13
    wb.save(path)


def test_pick_and_send_writes_approval_sheet_mirror_and_sets_pacing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    _make_accumulated(acc_path, [
        {"Email": f"lead{i}@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741"}
        for i in range(20)
    ])
    _make_mirror(mirror_path)

    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(
        name="IBM APAC", accumulated_report_path=acc_path, field_mapping=fm,
        complex_account=ComplexAccountConfig(enabled=True),
        box_tracker=BoxTrackerConfig(
            enabled=True, mirror_workbook_path=mirror_path, cid_campaign_map={"118741": "Bob"},
        ),
    )
    save_profile(profile, get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.selectbox[0].set_value("IBM APAC").run()

    pick_button = next(b for b in at.button if b.label == "Pick leads and send for approval")
    pick_button.click().run()

    assert not at.exception

    wb = openpyxl.load_workbook(mirror_path)
    approval_ws = wb["Approval Sheet"]
    assert approval_ws.max_row == 1 + 18  # header + (13 diff + 5 buffer)

    pacing_ws = wb["Pacing"]
    assert pacing_ws.cell(row=3, column=7).value == 18  # "D" column under "Week of 7"

    accumulated_df = pd.read_excel(acc_path, sheet_name="Accumulated")
    sent_count = (accumulated_df["Status"].astype(str).str.startswith("Sent for Approval")).sum()
    assert sent_count == 18


def test_pick_and_send_reports_shortfall(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "lead1@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741"},
    ])
    _make_mirror(mirror_path)

    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(
        name="IBM APAC", accumulated_report_path=acc_path, field_mapping=fm,
        complex_account=ComplexAccountConfig(enabled=True),
        box_tracker=BoxTrackerConfig(
            enabled=True, mirror_workbook_path=mirror_path, cid_campaign_map={"118741": "Bob"},
        ),
    )
    save_profile(profile, get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.selectbox[0].set_value("IBM APAC").run()
    at.button(key="pick_and_send_button").click().run()

    assert not at.exception
    assert any("118741" in w.value and "short" in w.value.lower() for w in at.warning)
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_box_tracker_page.py -v`
Expected: FAIL (page doesn't exist).

- [x] **Step 3: Implement `pages/5_Box_Tracker.py`**

```python
# pages/5_Box_Tracker.py
import datetime
import os

import pandas as pd
import streamlit as st

from core.app_settings import get_clients_dir
from core.box_tracker import (
    read_pacing_diffs, pick_leads_for_approval, sent_for_approval_label,
    append_mirror_rows, set_pacing_delivered,
)
from core.branding import configure_page
from core.excel_io import read_sheet_as_dataframe
from core.profile_store import list_profile_names, load_profile, save_profile

_current_user = configure_page("Box Tracker")
st.title("📦 Box Tracker")
st.caption(
    "For Complex Account clients whose lead-approval process runs through a Box-hosted tracker "
    "workbook this app has no API access to. Every write here goes to a LOCAL MIRROR workbook — "
    "you copy the results into the real Box file by hand."
)

_STATUS_COLUMN = "Status"
_APPROVAL_SHEET_TAB = "Approval Sheet"
_PACING_TAB = "Pacing"

profile_names = [
    name for name in list_profile_names(get_clients_dir())
    if load_profile(name, get_clients_dir()).box_tracker.enabled
]
if not profile_names:
    st.warning("No client has Box Tracker enabled yet. Set it up on the Client Setup page first.")
    st.stop()

client_name = st.selectbox("Client", profile_names)
profile = load_profile(client_name, get_clients_dir())

st.subheader("1. Pick leads and send for approval")
st.caption(
    f"Reads {profile.box_tracker.mirror_workbook_path}'s Pacing summary block, picks "
    f"(Diff + 5) blank-{_STATUS_COLUMN} leads per campaign from the Accumulated Report, writes "
    f"them into the mirror's {_APPROVAL_SHEET_TAB} tab, marks their {_STATUS_COLUMN}, and sets "
    "this week's Pacing Delivered count to the number sent."
)

if st.button("Pick leads and send for approval", key="pick_and_send_button"):
    try:
        accumulated_df = read_sheet_as_dataframe(profile.accumulated_report_path, profile.accumulated_tab_name)
        diffs = read_pacing_diffs(profile.box_tracker.mirror_workbook_path, _PACING_TAB)
        picked_df, shortfall = pick_leads_for_approval(
            accumulated_df, profile.field_mapping.cid, _STATUS_COLUMN,
            profile.box_tracker.cid_campaign_map, diffs, buffer=5,
        )

        if picked_df.empty:
            st.warning("No blank-Status leads matched any mapped CID with a known Pacing Diff — nothing to send.")
            st.stop()

        today = datetime.date.today()
        status_label = sent_for_approval_label(today)
        date_label = today.strftime("%d-%b")

        # Mark Status in the Accumulated Report itself.
        import openpyxl
        wb = openpyxl.load_workbook(profile.accumulated_report_path)
        ws = wb[profile.accumulated_tab_name]
        headers = [cell.value for cell in ws[1]]
        status_col = headers.index(_STATUS_COLUMN) + 1
        cid_col = headers.index(profile.field_mapping.cid) + 1
        picked_cids_by_row = set(picked_df.index)
        for row in ws.iter_rows(min_row=2):
            if (row[0].row - 2) in picked_cids_by_row:
                ws.cell(row=row[0].row, column=status_col, value=status_label)
        wb.save(profile.accumulated_report_path)

        # Write the Approval Sheet mirror rows.
        rows = []
        for _, lead in picked_df.iterrows():
            rows.append({
                "Company Name": lead.get(profile.field_mapping.company, ""),
                "Segment": lead.get("Segment", ""),
                "Job Title": lead.get("Job Title", ""),
                "Date": date_label,
            })
        append_mirror_rows(profile.box_tracker.mirror_workbook_path, _APPROVAL_SHEET_TAB, rows)

        # Set Pacing's Delivered count per campaign, for leads actually sent.
        cid_to_campaign = profile.box_tracker.cid_campaign_map
        picked_counts = picked_df[profile.field_mapping.cid].astype(str).value_counts()
        for cid, count in picked_counts.items():
            campaign = cid_to_campaign.get(cid)
            if campaign:
                set_pacing_delivered(profile.box_tracker.mirror_workbook_path, campaign, int(count))

        st.success(f"Sent {len(picked_df)} lead(s) for approval — see {_APPROVAL_SHEET_TAB} in the mirror workbook.")
        if shortfall:
            for cid, amount in shortfall.items():
                st.warning(f"CID {cid} was short by {amount} lead(s) — sent all that were available.")
    except Exception as exc:
        st.error(f"Error: {exc}")
```

Note for the implementer: the row-matching between `picked_df`'s index and the Accumulated worksheet's rows (the `(row[0].row - 2) in picked_cids_by_row` line) assumes `read_sheet_as_dataframe` preserves the same 0-based row order as the worksheet's data rows starting at row 2 — verify this against `read_sheet_as_dataframe`'s actual implementation in `core/excel_io.py` before trusting it, and adjust to whatever row-identity mechanism that function actually guarantees (e.g. it may be safer to match back by a unique column like email rather than positional index, if `read_sheet_as_dataframe` does any filtering/reordering). Confirm and fix this in Step 4 if the test in Step 1 reveals a mismatch.

- [x] **Step 4: Run the test, fix row-identity matching if needed, run again**

Run: `python -m pytest tests/test_box_tracker_page.py -v`
Expected: PASS once the Accumulated Status-marking correctly targets the picked rows (see the note in Step 3).

- [x] **Step 5: Manually verify in the running app**

Start the app, go to Box Tracker, select the test client, click "Pick leads and send for approval", then open the mirror workbook and confirm: the Approval Sheet has the new rows with today's date, the Accumulated Report's Status column shows "Sent for Approval - ..." for exactly those leads, and the Pacing tab's current week D column shows the count sent.

- [x] **Step 6: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add pages/5_Box_Tracker.py tests/test_box_tracker_page.py
git commit -m "Add Box Tracker page: pick leads by Pacing diff, write Approval Sheet mirror"
```

---

## Task 7: Batch upload-status reconciliation — Refund tab, Response Details mirror, final Pacing set

**Files:**
- Modify: `pages/5_Box_Tracker.py`
- Test: `tests/test_box_tracker_page.py`

**Interfaces:**
- Consumes: `append_leads` (existing, from `core.excel_io`, for writing to the Refund tab — reuse exactly as `pages/2_Run_Check.py` already does), plus everything from Task 6.

**Note on scope:** per the Global Constraints, Lead Template column mapping is deferred — this task's "cleared for Lead Template" step only marks which leads are cleared (an in-memory/session marker) so the reconciliation step below knows which leads it's reconciling; it never writes a Lead Template file.

- [x] **Step 1: Write the failing tests**

Add to `tests/test_box_tracker_page.py`:

```python
def test_upload_reconciliation_moves_rejected_to_refund_and_logs_accepted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    mirror_path = str(tmp_path / "mirror.xlsx")
    _make_accumulated(acc_path, [
        {"Email": "lead1@x.com", "First": "F", "Last": "L", "Company": "X", "CID": "118741",
         "Status": "Sent for Approval - 07-Sep"},
        {"Email": "lead2@x.com", "First": "F", "Last": "L", "Company": "Y", "CID": "118741",
         "Status": "Sent for Approval - 07-Sep"},
    ])
    # Refund tab required by append_leads' target sheet.
    wb = openpyxl.load_workbook(acc_path)
    wb.create_sheet("Refund").append(["Email", "First", "Last", "Company", "CID", "Status", "Refund Reason"])
    wb.save(acc_path)
    _make_mirror(mirror_path)
    wb2 = openpyxl.load_workbook(mirror_path)
    wb2.create_sheet("Response Details").append(
        ["Publisher Name", "source_site", "Market", "Company", "UUCID", "Project Code",
         "Uploaded Date", "Campaign Name", "Segment", "Job Title", "Contact Type", "State",
         "Campaign Type", "Asset Title"])
    wb2.create_sheet("Response Details").append([])  # placeholder if needed
    wb2.save(mirror_path)

    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(
        name="IBM APAC", accumulated_report_path=acc_path, field_mapping=fm,
        complex_account=ComplexAccountConfig(enabled=True),
        box_tracker=BoxTrackerConfig(
            enabled=True, mirror_workbook_path=mirror_path, cid_campaign_map={"118741": "Bob"},
        ),
    )
    save_profile(profile, get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.selectbox[0].set_value("IBM APAC").run()

    # Mark lead2 as rejected with a reason; lead1 accepted (default).
    reject_checkbox = next(cb for cb in at.checkbox if cb.key == "reject_lead2@x.com")
    reject_checkbox.set_value(True).run()
    reason_input = next(t for t in at.text_input if t.key == "reject_reason_lead2@x.com")
    reason_input.set_value("Portal duplicate").run()

    reconcile_button = next(b for b in at.button if b.key == "reconcile_upload_button")
    reconcile_button.click().run()

    assert not at.exception

    refund_df = pd.read_excel(acc_path, sheet_name="Refund")
    assert "lead2@x.com" in refund_df["Email"].values
    assert refund_df.loc[refund_df["Email"] == "lead2@x.com", "Refund Reason"].iloc[0] == "Portal duplicate"

    response_wb = openpyxl.load_workbook(mirror_path)
    response_ws = response_wb["Response Details"]
    values = [c.value for c in response_ws[response_ws.max_row]]
    assert "lead1@x.com" not in values  # Response Details logs Company, not Email -- check Company instead
```

Note for the implementer: the exact assertion for "accepted lead logged to Response Details" needs to check the `Company` column (Response Details has no Email column per the real sheet's headers from Task 2's docs) — fix the last assertion to check `values` contains lead1's Company value ("X") in the Company column position, once the actual UI/session-state keys for the reject-checkbox/reason-input are finalized in Step 3 (the keys above, `reject_{email}`/`reject_reason_{email}`, are this plan's proposed convention — keep them if reasonable, adjust the test to match if the implementer picks different key names, as long as they're descriptive and collision-free per lead).

- [x] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_box_tracker_page.py -k reconciliation -v`
Expected: FAIL.

- [x] **Step 3: Implement the reconciliation section, appended to `pages/5_Box_Tracker.py`**

```python
st.divider()
st.subheader("2. Reconcile portal upload status")
st.caption(
    "For leads already cleared and pasted into the Lead Template, then uploaded to the client "
    "portal by hand: check any that the portal rejected, with a reason. Everything left unchecked "
    "is treated as accepted."
)

_status_prefix = "Sent for Approval"
try:
    accumulated_df = read_sheet_as_dataframe(profile.accumulated_report_path, profile.accumulated_tab_name)
    _sent_df = accumulated_df[
        accumulated_df[_STATUS_COLUMN].astype(str).str.startswith(_status_prefix)
    ]
except Exception as exc:
    _sent_df = pd.DataFrame()
    st.error(f"Could not load Accumulated Report: {exc}")

if _sent_df.empty:
    st.caption("No leads currently marked \"Sent for Approval\".")
else:
    email_col = profile.field_mapping.email
    reject_flags: dict[str, bool] = {}
    reject_reasons: dict[str, str] = {}
    for _, lead in _sent_df.iterrows():
        email = str(lead.get(email_col, ""))
        col_check, col_reason = st.columns([1, 3])
        reject_flags[email] = col_check.checkbox(
            f"Reject {email}", key=f"reject_{email}", label_visibility="collapsed")
        reject_reasons[email] = col_reason.text_input(
            "Reason", key=f"reject_reason_{email}", label_visibility="collapsed",
            placeholder=f"Reason for rejecting {email} (required if rejected)")

    if st.button("Reconcile upload status", key="reconcile_upload_button"):
        try:
            rejected_emails = {e for e, flag in reject_flags.items() if flag}
            missing_reasons = [e for e in rejected_emails if not reject_reasons.get(e, "").strip()]
            if missing_reasons:
                st.error(f"Missing rejection reason for: {', '.join(missing_reasons)}")
                st.stop()

            accepted_df = _sent_df[~_sent_df[email_col].astype(str).isin(rejected_emails)]
            rejected_df = _sent_df[_sent_df[email_col].astype(str).isin(rejected_emails)]

            if not rejected_df.empty:
                from core.excel_io import append_leads
                reasons = {idx: reject_reasons[str(row[email_col])] for idx, row in rejected_df.iterrows()}
                append_leads(
                    profile.accumulated_report_path, profile.refund_tab_name,
                    rejected_df, profile.field_mapping, datetime.date.today(), reasons=reasons,
                )

            if not accepted_df.empty:
                cid_to_campaign = profile.box_tracker.cid_campaign_map
                rows = []
                for _, lead in accepted_df.iterrows():
                    campaign = cid_to_campaign.get(str(lead.get(profile.field_mapping.cid, "")), "")
                    rows.append({
                        "Company": lead.get(profile.field_mapping.company, ""),
                        "Campaign Name": campaign,
                        "Segment": lead.get("Segment", ""),
                        "Job Title": lead.get("Job Title", ""),
                        "Uploaded Date": datetime.date.today().strftime("%d-%b"),
                    })
                append_mirror_rows(profile.box_tracker.mirror_workbook_path, "Response Details", rows)

                accepted_counts = accepted_df[profile.field_mapping.cid].astype(str).value_counts()
                for cid, count in accepted_counts.items():
                    campaign = cid_to_campaign.get(cid)
                    if campaign:
                        set_pacing_delivered(profile.box_tracker.mirror_workbook_path, campaign, int(count))

            st.success(
                f"Reconciled: {len(accepted_df)} accepted (logged to Response Details, Pacing updated), "
                f"{len(rejected_df)} rejected (moved to Refund)."
            )
        except Exception as exc:
            st.error(f"Error: {exc}")
```

Note for the implementer: `append_leads`' exact keyword-argument shape must be double-checked against its current signature in `core/excel_io.py` before relying on the call above (it may need `target_field_mapping` or other arguments depending on how `Refund`'s columns compare to `profile.field_mapping`'s roles — follow the same call shape `pages/2_Run_Check.py`'s `_finalize_write` already uses for its own Refund-tab write).

- [x] **Step 4: Run the test, fix the Response Details assertion and any call-shape mismatches, run again**

Run: `python -m pytest tests/test_box_tracker_page.py -v`
Expected: PASS

- [x] **Step 5: Manually verify in the running app**

Run the "Pick and send" step, manually edit the Accumulated Report to simulate a client decision if needed, then run the reconciliation step with one lead checked as rejected (with a reason) and confirm: the Refund tab gets that lead with the reason, the mirror's Response Details tab gets the accepted lead(s), and Pacing's current-week D column is overwritten to the final accepted count.

- [x] **Step 6: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add pages/5_Box_Tracker.py tests/test_box_tracker_page.py
git commit -m "Add portal-upload reconciliation: Refund tab, Response Details mirror, final Pacing set"
```

---

## Explicitly Out of Scope (for a later plan)

- Any live Box or Google Sheets API integration — everything above writes only to the local mirror workbook.
- Lead Template column mapping/writing for IBM APAC.
- Automated detection of the Approval Sheet's own `Approval` column — the user has said this is a manual, out-of-band decision for now.
- Anything for the 3 additional campaign columns (CXO, both Hashicorp Solutions rows) beyond what the CID map already supports for Response Details' Campaign Name — they'll be picked up automatically for diff-based picking the moment the user adds their columns to the mirror's Pacing summary block, per Task 3/4's dynamic design, so no further code change is anticipated, but this should be verified against the real file once those columns exist.

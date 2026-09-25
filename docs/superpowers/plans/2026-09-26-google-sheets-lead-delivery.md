# Google Sheets Lead Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a client's valid leads write straight to a Google Sheet,
routed per CID, as a peer destination type alongside the existing Excel
Lead Template — reusing the exact mandatory/override/date-format column
mapping model already built for Excel templates.

**Architecture:** A new `core/google_sheets_client.py` (auth + read/append
via `gspread`), a new `GoogleSheetsConfig`/`GoogleSheetTab` pair on
`ClientProfile` that reuses the existing `LeadTemplateMappingConfig`
dataclass verbatim, a shared `resolve_lead_template_rules` helper
extracted out of `core/excel_io.py`'s two near-duplicate blocks, a new
Client Setup section, and write-path/pipeline wiring in
`pages/2_Run_Check.py`.

**Tech Stack:** Python, `gspread` (new dependency), `google-auth` (new,
`gspread`'s own dependency), Streamlit, pytest.

## Global Constraints

- Every existing client (Excel Lead Template, Accumulated Report, or
  neither) sees ZERO behavior change. `ClientProfile.google_sheets`
  defaults to `GoogleSheetsConfig()` — disabled, empty tabs, empty
  mapping — for every profile that hasn't explicitly configured it.
- `GoogleSheetTab(cid: str, sheet_id: str, worksheet_name: str = "Sheet1")`;
  `GoogleSheetsConfig(enabled: bool = False, tabs: list[GoogleSheetTab] = [], mapping: LeadTemplateMappingConfig = LeadTemplateMappingConfig())`.
  `mapping` is a SEPARATE `LeadTemplateMappingConfig` instance from
  `ClientProfile.lead_template_mapping` — do not conflate the two.
- The service-account JSON key file's PATH (not its content) is the only
  thing this app stores, in the plain local `app_settings.json` only,
  same as every other live credential in this app (Jira, Enhancio,
  Integrate) — never the shared clients folder.
- Sheet writes use `value_input_option="USER_ENTERED"` so a date string is
  recognized as a real Sheets date value, not left as plain text.
- `pages/2_Run_Check.py`'s `_stage_labels` AND `_completed_checks` BOTH
  get a new entry for the Google Sheets mandatory-check stage in the SAME
  task that wires the check into the pipeline (Task 5) — this exact class
  of bug (a new pipeline stage with no matching UI-list entry) shipped
  once already in this session's prior feature and crashed Run Check for
  any client that used it; do not repeat it.
- Run the affected test file(s) after each task; run the full suite
  (`python -m pytest -q`) before considering the plan done.

---

### Task 1: Data model — `GoogleSheetTab` / `GoogleSheetsConfig`

**Files:**
- Modify: `core/models.py`
- Modify: `core/profile_store.py`
- Test: `tests/test_models.py`, `tests/test_profile_store.py`

**Interfaces:**
- Produces: `GoogleSheetTab(cid: str, sheet_id: str, worksheet_name: str = "Sheet1")`;
  `GoogleSheetsConfig(enabled: bool = False, tabs: list[GoogleSheetTab] = [], mapping: LeadTemplateMappingConfig = LeadTemplateMappingConfig())`;
  `ClientProfile.google_sheets: GoogleSheetsConfig`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_models.py (append)
from core.models import ClientProfile, GoogleSheetTab, GoogleSheetsConfig


def test_client_profile_defaults_to_a_disabled_google_sheets_config():
    profile = ClientProfile(name="X", accumulated_report_path="acc.xlsx")
    assert profile.google_sheets.enabled is False
    assert profile.google_sheets.tabs == []
    assert profile.google_sheets.mapping.rules == []


def test_google_sheet_tab_defaults():
    tab = GoogleSheetTab(cid="119999", sheet_id="1o_v7oMh6Y5VcX0COIjWQ_y00IVKGbwbznCEzNGcyhpU")
    assert tab.worksheet_name == "Sheet1"
```

```python
# tests/test_profile_store.py (append, mirroring however
# test_lead_template_mapping_rules_round_trip_through_save_and_load or
# the equivalent lead_template_tabs round-trip test in this file is
# already structured -- read that existing test first and match its
# exact fixture style, e.g. tmp_path/clients_dir/_sample_profile usage)
def test_google_sheets_config_round_trips_through_save_and_load(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import get_clients_dir
    from core.models import (
        ClientProfile, GoogleSheetTab, GoogleSheetsConfig,
        LeadTemplateColumnRule, LeadTemplateMappingConfig,
    )
    from core.profile_store import save_profile, load_profile

    profile = ClientProfile(
        name="China Webinar Client", accumulated_report_path="acc.xlsx",
        google_sheets=GoogleSheetsConfig(
            enabled=True,
            tabs=[
                GoogleSheetTab(cid="119999", sheet_id="1o_v7oMh6Y5VcX0COIjWQ_y00IVKGbwbznCEzNGcyhpU"),
                GoogleSheetTab(cid="120000", sheet_id="1zU6rm9EvksfJUA91JrLIOPneWTNRgjK6jpm4Ukb2PPA", worksheet_name="Leads"),
            ],
            mapping=LeadTemplateMappingConfig(rules=[
                LeadTemplateColumnRule(template_column="Work Email", mandatory=True),
            ]),
        ),
    )
    save_profile(profile, get_clients_dir())

    loaded = load_profile("China Webinar Client", get_clients_dir())

    assert loaded.google_sheets.enabled is True
    assert loaded.google_sheets.tabs == profile.google_sheets.tabs
    assert loaded.google_sheets.mapping.rules == profile.google_sheets.mapping.rules
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_models.py tests/test_profile_store.py -k google_sheets -v`
Expected: FAIL with `ImportError: cannot import name 'GoogleSheetTab'`

- [ ] **Step 3: Add the dataclasses to `core/models.py`**

Add directly after the existing `LeadTemplateMappingConfig` dataclass
(search for `class LeadTemplateMappingConfig:` to find the exact spot —
`GoogleSheetsConfig` references it, so it must be defined after):

```python
@dataclass
class GoogleSheetTab:
    # Which CID's leads go to this Sheet -- same per-CID routing shape as
    # LeadTemplateTab, for a client whose Lead Template destination is a
    # Google Sheet instead of (or, in the future, alongside) an Excel file.
    cid: str
    sheet_id: str
    worksheet_name: str = "Sheet1"


@dataclass
class GoogleSheetsConfig:
    enabled: bool = False
    tabs: list[GoogleSheetTab] = field(default_factory=list)
    # A SEPARATE LeadTemplateMappingConfig instance from
    # ClientProfile.lead_template_mapping -- a client's Sheet(s) can have
    # entirely different headers/mandatory rules than its Excel template
    # (if it even has one). One mapping shared across all this client's
    # Sheet tabs, same as lead_template_mapping is shared across all
    # lead_template_tabs today.
    mapping: LeadTemplateMappingConfig = field(default_factory=LeadTemplateMappingConfig)
```

Then find `@dataclass class ClientProfile:` and add, alongside the
existing `lead_template_mapping: LeadTemplateMappingConfig = ...` line:

```python
    google_sheets: GoogleSheetsConfig = field(default_factory=GoogleSheetsConfig)
```

- [ ] **Step 4: Wire deserialization into `core/profile_store.py`**

Read the file first to find the EXACT existing pattern used for
`lead_template_mapping`'s deserialization (search for
`lead_template_mapping = LeadTemplateMappingConfig(` inside
`load_profile`) and mirror it precisely. Add `GoogleSheetTab,
GoogleSheetsConfig` to the existing `from core.models import (...)` line.
Then add, near the existing `lead_template_mapping = ...` block:

```python
    _gs_data = data.get("google_sheets") or {}
    _gs_mapping_data = _gs_data.get("mapping") or {}
    google_sheets = GoogleSheetsConfig(
        enabled=_gs_data.get("enabled", False),
        tabs=[GoogleSheetTab(**t) for t in _gs_data.get("tabs", [])],
        mapping=LeadTemplateMappingConfig(
            rules=[LeadTemplateColumnRule(**r) for r in _gs_mapping_data.get("rules", [])]),
    )
```

Add `google_sheets=google_sheets,` as a sibling argument to the
`ClientProfile(...)` constructor call inside `load_profile` (same block
where `lead_template_mapping=lead_template_mapping,` already appears).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_models.py tests/test_profile_store.py -k google_sheets -v`
Expected: PASS

- [ ] **Step 6: Run the full model/profile_store suite**

Run: `python -m pytest tests/test_models.py tests/test_profile_store.py tests/test_client_setup_page.py -q`
Expected: PASS, unchanged (new field defaults to disabled/empty, so every
existing profile round-trips identically)

- [ ] **Step 7: Commit**

```bash
git add core/models.py core/profile_store.py tests/test_models.py tests/test_profile_store.py
git commit -m "Add GoogleSheetTab/GoogleSheetsConfig to ClientProfile"
```

---

### Task 2: Dependency + credential storage

**Files:**
- Modify: `requirements.txt`
- Modify: `core/app_settings.py`
- Test: `tests/test_app_settings.py`

**Interfaces:**
- Produces: `get_google_sheets_key_path() -> str`;
  `save_google_sheets_key_path(path: str) -> None`.

- [ ] **Step 1: Add the dependency**

Add a new line to `requirements.txt`: `gspread` (pulls in `google-auth`
as its own dependency automatically — no separate line needed). Match
whatever version-pinning convention the rest of `requirements.txt`
already uses (read the file first — if other lines are unpinned, leave
this unpinned too, for consistency).

- [ ] **Step 2: Install it**

Run: `python -m pip install gspread`
Expected: installs `gspread` plus `google-auth`, `google-auth-oauthlib`
(transitive), etc. with no errors.

- [ ] **Step 3: Write the failing test**

```python
# tests/test_app_settings.py (append)
from core.app_settings import get_google_sheets_key_path, save_google_sheets_key_path


def test_save_and_get_google_sheets_key_path_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert get_google_sheets_key_path() == ""
    save_google_sheets_key_path("  C:\\keys\\service-account.json  ")
    assert get_google_sheets_key_path() == "C:\\keys\\service-account.json"
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `python -m pytest tests/test_app_settings.py -k google_sheets_key -v`
Expected: FAIL with `ImportError: cannot import name 'get_google_sheets_key_path'`

- [ ] **Step 5: Add the functions**

Append to the end of `core/app_settings.py` (after the existing
`save_integrate_credentials` function — read the file first to confirm
this is still the last function, since the file may have grown):

```python
def get_google_sheets_key_path() -> str:
    # A Google service-account JSON key is a live credential file --
    # only its local filesystem PATH is stored here, in the plain local
    # app_settings.json, same reasoning as get_jira_settings/
    # get_integrate_credentials. The key file's actual CONTENT is never
    # read or copied by this function -- core.google_sheets_client reads
    # it directly from this path at call time.
    settings = load_app_settings()
    return settings.get("google_sheets_key_path", "")


def save_google_sheets_key_path(path: str) -> None:
    updated = load_app_settings()
    updated["google_sheets_key_path"] = path.strip()
    save_app_settings(updated)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest tests/test_app_settings.py -k google_sheets_key -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add requirements.txt core/app_settings.py tests/test_app_settings.py
git commit -m "Add gspread dependency and Google Sheets key-path credential storage"
```

---

### Task 3: `core/excel_io.py` extraction + `core/google_sheets_client.py`

**Files:**
- Modify: `core/excel_io.py`
- Create: `core/google_sheets_client.py`
- Test: `tests/test_excel_io_append.py`, `tests/test_google_sheets_client.py`

**Interfaces:**
- Consumes: `LeadTemplateMappingConfig` (Task 1); `get_google_sheets_key_path`
  (Task 2, used by the page layer, not this module directly — this
  module takes `key_path` as a plain argument, staying testable without
  touching `app_settings.json`).
- Produces: `core.excel_io.resolve_lead_template_rules(lead_template_mapping: LeadTemplateMappingConfig | None) -> tuple[dict[str, str], dict[str, tuple[str, str]]]`
  (returns `(manual_overrides, date_formats)`, the exact shape both
  `append_leads` branches already build inline).
  `core.google_sheets_client.GoogleSheetsError(Exception)`;
  `read_sheet_headers(key_path: str, sheet_id: str, worksheet_name: str) -> list[str]`;
  `append_rows(key_path: str, sheet_id: str, worksheet_name: str, rows: list[dict[str, str]]) -> int`.

- [ ] **Step 1: Write the failing test for the extraction**

Read `core/excel_io.py`'s CURRENT two `manual_overrides = {...}` /
`date_formats = {...}` blocks first (search `manual_overrides = {` — two
occurrences, in `_append_leads_csv` and `append_leads`) to copy their
exact current logic verbatim into the new function (this must be a
byte-identical extraction, not a rewrite).

```python
# tests/test_excel_io_append.py (append)
def test_resolve_lead_template_rules_returns_overrides_and_date_formats():
    from core.excel_io import resolve_lead_template_rules
    from core.models import LeadTemplateColumnRule, LeadTemplateMappingConfig

    config = LeadTemplateMappingConfig(rules=[
        LeadTemplateColumnRule(template_column="Company Size", source_column="Employee Count"),
        LeadTemplateColumnRule(template_column="Capture Date", date_format="YYYY-MM-DD"),
        LeadTemplateColumnRule(template_column="Untouched Column"),
    ])

    overrides, date_formats = resolve_lead_template_rules(config)

    assert overrides == {"companysize": "Employee Count"}
    assert "capturedate" in date_formats
    assert date_formats["capturedate"][0] == "%Y-%m-%d"


def test_resolve_lead_template_rules_handles_none_config():
    from core.excel_io import resolve_lead_template_rules
    overrides, date_formats = resolve_lead_template_rules(None)
    assert overrides == {} and date_formats == {}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_excel_io_append.py -k resolve_lead_template_rules -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_lead_template_rules'`

- [ ] **Step 3: Extract the function, then call it from both existing branches**

Add near `_resolve_date_format` in `core/excel_io.py`:

```python
def resolve_lead_template_rules(
    lead_template_mapping: "LeadTemplateMappingConfig | None",
) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """(manual_overrides, date_formats) exactly as append_leads' xlsx and
    CSV branches each used to compute inline -- factored out here so
    core.google_sheets_client can resolve the SAME rules against a
    Google Sheet's headers without a third copy of this logic.
    """
    manual_overrides = {
        normalize_header_text(r.template_column): r.source_column
        for r in (lead_template_mapping.rules if lead_template_mapping else [])
        if r.source_column
    }
    date_formats = {
        normalize_header_text(r.template_column): _resolve_date_format(r.date_format)
        for r in (lead_template_mapping.rules if lead_template_mapping else [])
        if r.date_format
    }
    return manual_overrides, date_formats
```

Then, in BOTH `_append_leads_csv` and `append_leads`, replace their own
inline `manual_overrides = {...}` / `date_formats = {...}` blocks with a
single line: `manual_overrides, date_formats = resolve_lead_template_rules(lead_template_mapping)`.
This is a pure extraction — the computed values must be identical to
before, which the EXISTING date-format tests from the prior feature
(`tests/test_excel_io_append.py`, search `test_append_leads_applies_a_configured_date_format`)
already protect.

- [ ] **Step 4: Run the extraction test and the full existing append_leads suite**

Run: `python -m pytest tests/test_excel_io_append.py tests/test_excel_io_generic.py -q`
Expected: PASS, all tests including the new 2 and every pre-existing one
(confirms the extraction changed nothing observable)

- [ ] **Step 5: Write the failing tests for `core/google_sheets_client.py`**

Read `tests/test_enhancio_client.py` or `tests/test_integrate_client.py`
first for this codebase's established mocking style for an external API
client, then write (mocking `gspread` itself, not making real network
calls):

```python
# tests/test_google_sheets_client.py
from unittest.mock import patch, MagicMock

import pytest

from core.google_sheets_client import GoogleSheetsError, read_sheet_headers, append_rows


def test_read_sheet_headers_returns_row_1_values():
    mock_worksheet = MagicMock()
    mock_worksheet.row_values.return_value = ["First Name", "Last Name", "Work Email"]
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_spreadsheet

    with patch("core.google_sheets_client.gspread.service_account", return_value=mock_client):
        headers = read_sheet_headers("fake_key.json", "sheet123", "Sheet1")

    assert headers == ["First Name", "Last Name", "Work Email"]
    mock_client.open_by_key.assert_called_once_with("sheet123")
    mock_spreadsheet.worksheet.assert_called_once_with("Sheet1")


def test_read_sheet_headers_raises_google_sheets_error_when_key_file_missing():
    with patch("core.google_sheets_client.gspread.service_account", side_effect=FileNotFoundError("no such file")):
        with pytest.raises(GoogleSheetsError, match="key"):
            read_sheet_headers("missing.json", "sheet123", "Sheet1")


def test_append_rows_calls_append_rows_with_user_entered_and_matching_header_order():
    mock_worksheet = MagicMock()
    mock_worksheet.row_values.return_value = ["First Name", "Work Email"]
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_spreadsheet

    with patch("core.google_sheets_client.gspread.service_account", return_value=mock_client):
        count = append_rows("fake_key.json", "sheet123", "Sheet1", [
            {"First Name": "A", "Work Email": "a@x.com"},
            {"First Name": "B", "Work Email": "b@x.com"},
        ])

    assert count == 2
    args, kwargs = mock_worksheet.append_rows.call_args
    assert args[0] == [["A", "a@x.com"], ["B", "b@x.com"]]
    assert kwargs["value_input_option"] == "USER_ENTERED"


def test_append_rows_raises_google_sheets_error_on_api_failure():
    mock_worksheet = MagicMock()
    mock_worksheet.row_values.return_value = ["First Name"]
    mock_worksheet.append_rows.side_effect = Exception("API quota exceeded")
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_spreadsheet

    with patch("core.google_sheets_client.gspread.service_account", return_value=mock_client):
        with pytest.raises(GoogleSheetsError, match="API quota exceeded"):
            append_rows("fake_key.json", "sheet123", "Sheet1", [{"First Name": "A"}])
```

- [ ] **Step 6: Run the tests to verify they fail**

Run: `python -m pytest tests/test_google_sheets_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.google_sheets_client'`

- [ ] **Step 7: Write the implementation**

```python
# core/google_sheets_client.py
import gspread


class GoogleSheetsError(Exception):
    """Raised for any failure reading from or writing to a Google Sheet --
    a missing/invalid service-account key file, or any Sheets API error."""


def _open_worksheet(key_path: str, sheet_id: str, worksheet_name: str):
    try:
        client = gspread.service_account(filename=key_path)
    except Exception as exc:
        raise GoogleSheetsError(
            f"Couldn't authenticate with the Google Sheets service-account key at "
            f"\"{key_path}\": {exc}"
        ) from exc
    try:
        spreadsheet = client.open_by_key(sheet_id)
        return spreadsheet.worksheet(worksheet_name)
    except Exception as exc:
        raise GoogleSheetsError(
            f"Couldn't open Sheet \"{sheet_id}\" (tab \"{worksheet_name}\"): {exc}"
        ) from exc


def read_sheet_headers(key_path: str, sheet_id: str, worksheet_name: str) -> list[str]:
    """Reads row 1 of the given Sheet tab live -- used both for the
    Client Setup mapping-preview UI and for resolving write-time column
    order, so a Sheet's headers changing between setup and a later run
    is picked up automatically.
    """
    worksheet = _open_worksheet(key_path, sheet_id, worksheet_name)
    try:
        return worksheet.row_values(1)
    except Exception as exc:
        raise GoogleSheetsError(f"Couldn't read headers from Sheet \"{sheet_id}\": {exc}") from exc


def append_rows(key_path: str, sheet_id: str, worksheet_name: str, rows: list[dict[str, str]]) -> int:
    """Appends each row (already resolved to {header: value} by the
    caller, via core.excel_io.resolve_lead_template_rules +
    _resolve_passthrough_columns) after the Sheet's last real row, using
    the Sheets API's own native append -- no manual "find the next empty
    row" bookkeeping needed, unlike the Excel writer. value_input_option
    is USER_ENTERED so a date string is recognized as a real Sheets date
    value, not left as plain text, matching how append_leads' xlsx branch
    requires a genuine date value rather than text.

    Raises GoogleSheetsError on any failure -- a lead this function
    believes it sent is never silently dropped.
    """
    if not rows:
        return 0
    worksheet = _open_worksheet(key_path, sheet_id, worksheet_name)
    try:
        headers = worksheet.row_values(1)
        values = [[row.get(header, "") for header in headers] for row in rows]
        worksheet.append_rows(values, value_input_option="USER_ENTERED")
        return len(rows)
    except Exception as exc:
        raise GoogleSheetsError(f"Failed to append {len(rows)} lead(s) to Sheet \"{sheet_id}\": {exc}") from exc
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python -m pytest tests/test_google_sheets_client.py -v`
Expected: PASS (4 tests)

- [ ] **Step 9: Commit**

```bash
git add core/excel_io.py core/google_sheets_client.py tests/test_excel_io_append.py tests/test_google_sheets_client.py
git commit -m "Extract resolve_lead_template_rules and add core/google_sheets_client.py"
```

---

### Task 4: Client Setup UI section

**Files:**
- Modify: `pages/1_Client_Setup.py`
- Test: `tests/test_client_setup_page.py`

**Interfaces:**
- Consumes: `GoogleSheetTab`, `GoogleSheetsConfig` (Task 1);
  `get_google_sheets_key_path` (Task 2);
  `core.google_sheets_client.read_sheet_headers`, `GoogleSheetsError` (Task 3).
- Produces: the saved profile's `.google_sheets` field.

- [ ] **Step 1: Write the failing test**

Read an existing Task-5-style save test in `tests/test_client_setup_page.py`
(search for `test_saving_lead_template_mapping_persists_mandatory_and_override`)
to copy the exact real widget keys/labels for client name, accumulated
path, and the Save button. Then add:

```python
def test_saving_google_sheets_tabs_and_mandatory_column_persists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from unittest.mock import patch
    from core.app_settings import save_app_settings, save_google_sheets_key_path
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_google_sheets_key_path(str(tmp_path / "fake-key.json"))

    with patch("core.google_sheets_client.read_sheet_headers",
               return_value=["First Name", "Last Name", "Work Email"]):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(t for t in at.text_input if t.label == "Client name").set_value("China Webinar Client").run()
        at.text_input(key="accumulated_path_input").set_value(str(tmp_path / "acc.xlsx")).run()

        at.checkbox(key="gs_enabled").set_value(True).run()
        at.text_area(key="gs_tabs_input").set_value(
            "119999,https://docs.google.com/spreadsheets/d/1o_v7oMh6Y5VcX0COIjWQ_y00IVKGbwbznCEzNGcyhpU/edit\n"
            "120000,https://docs.google.com/spreadsheets/d/1zU6rm9EvksfJUA91JrLIOPneWTNRgjK6jpm4Ukb2PPA/edit,Leads"
        ).run()
        at.checkbox(key="gs_mandatory_Work Email").set_value(True).run()

        next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile
    saved = load_profile("China Webinar Client", get_clients_dir())

    assert saved.google_sheets.enabled is True
    assert saved.google_sheets.tabs == [
        __import__("core.models", fromlist=["GoogleSheetTab"]).GoogleSheetTab(
            cid="119999", sheet_id="1o_v7oMh6Y5VcX0COIjWQ_y00IVKGbwbznCEzNGcyhpU"),
        __import__("core.models", fromlist=["GoogleSheetTab"]).GoogleSheetTab(
            cid="120000", sheet_id="1zU6rm9EvksfJUA91JrLIOPneWTNRgjK6jpm4Ukb2PPA", worksheet_name="Leads"),
    ]
    rule = next(r for r in saved.google_sheets.mapping.rules if r.template_column == "Work Email")
    assert rule.mandatory is True
```

(Replace the awkward `__import__` calls with a normal
`from core.models import GoogleSheetTab` at the top of the test file once
you're writing the real test — it's spelled out inline above only so the
exact expected values are unambiguous in this brief.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_client_setup_page.py -k google_sheets -v`
Expected: FAIL (the new widgets don't exist yet)

- [ ] **Step 3: Add the Client Setup section**

Add `GoogleSheetTab, GoogleSheetsConfig` to the `from core.models import
(...)` line. Add `from core.app_settings import get_google_sheets_key_path`
if not already imported (check — `app_settings` functions are likely
already partially imported in this file; add to that same import line).
Add `from core import google_sheets_client` and
`from core.google_sheets_client import GoogleSheetsError`.

Insert this new section as its own top-level block (NOT nested inside
`if client_mode == "Lead QA":`, since this client has no Excel Lead
Template at all) — place it after the existing Lead Template Column
Mapping section (Task 5's work) ends, before whatever section follows:

```python
        st.divider()
        st.markdown("**Google Sheets Lead Delivery (optional)**")
        st.caption(
            "Route this client's valid leads straight to a Google Sheet per CID, instead of (or alongside) "
            "an Excel Lead Template. Requires the Google Sheets service account key to be set on the "
            "⚙️ Settings page, and each Sheet to be individually shared with that service account's email "
            "as Editor."
        )
        gs_enabled = st.checkbox(
            "This client delivers leads to Google Sheets", value=profile.google_sheets.enabled if profile else False,
            key="gs_enabled")
        gs_tabs: list[GoogleSheetTab] = []
        gs_mapping_rules: list[LeadTemplateColumnRule] = []
        if gs_enabled:
            st.caption(
                "CID → Sheet mapping, one per line, format `CID,Sheet URL` or `CID,Sheet URL,worksheet name` "
                "(worksheet name defaults to \"Sheet1\") — paste the exact URL from your browser's address bar:"
            )
            _existing_gs_tabs_text = "\n".join(
                f"{t.cid},https://docs.google.com/spreadsheets/d/{t.sheet_id}/edit"
                + (f",{t.worksheet_name}" if t.worksheet_name != "Sheet1" else "")
                for t in (profile.google_sheets.tabs if profile else [])
            )
            _gs_tabs_text = st.text_area(
                "CID to Google Sheet mapping", value=_existing_gs_tabs_text,
                key="gs_tabs_input", label_visibility="collapsed", height=100)
            import re as _re
            for _line in _gs_tabs_text.splitlines():
                _line = _line.strip()
                if not _line or "," not in _line:
                    continue
                _parts = [p.strip() for p in _line.split(",")]
                _cid, _url = _parts[0], _parts[1]
                _worksheet = _parts[2] if len(_parts) > 2 and _parts[2] else "Sheet1"
                _match = _re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", _url)
                if _cid and _match:
                    gs_tabs.append(GoogleSheetTab(cid=_cid, sheet_id=_match.group(1), worksheet_name=_worksheet))

            _gs_key_path = get_google_sheets_key_path()
            if not _gs_key_path:
                st.caption("No Google Sheets service account key configured yet — set one on the ⚙️ Settings page.")
            elif gs_tabs:
                _gs_sample_headers: list[str] = []
                try:
                    _first_tab = gs_tabs[0]
                    _gs_sample_headers = google_sheets_client.read_sheet_headers(
                        _gs_key_path, _first_tab.sheet_id, _first_tab.worksheet_name)
                except GoogleSheetsError as exc:
                    render_error(exc)

                _existing_gs_rules = {r.template_column: r for r in (profile.google_sheets.mapping.rules if profile else [])}
                _DATE_FORMAT_OPTIONS = [
                    "(no special formatting)", "MM/DD/YYYY", "DD/MM/YYYY", "DD-MMM-YY",
                    "YYYY-MM-DD", "YYYY-MM-DD HH:MM:SS", "Custom...",
                ]
                for _gs_col in _gs_sample_headers:
                    _existing_rule = _existing_gs_rules.get(_gs_col)
                    with st.container(border=True):
                        st.write(f"**{_gs_col}**")
                        _gs_mandatory = st.checkbox(
                            "Mandatory", value=_existing_rule.mandatory if _existing_rule else False,
                            key=f"gs_mandatory_{_gs_col}")
                        _default_fmt = _existing_rule.date_format if _existing_rule else ""
                        _fmt_idx = _DATE_FORMAT_OPTIONS.index(_default_fmt) if _default_fmt in _DATE_FORMAT_OPTIONS else 0
                        _gs_fmt_selected = st.selectbox(
                            "Date format", _DATE_FORMAT_OPTIONS, index=_fmt_idx, key=f"gs_fmt_{_gs_col}")
                        _gs_date_format = "" if _gs_fmt_selected == "(no special formatting)" else _gs_fmt_selected
                    if _gs_mandatory or _gs_date_format:
                        gs_mapping_rules.append(LeadTemplateColumnRule(
                            template_column=_gs_col, mandatory=_gs_mandatory, date_format=_gs_date_format))
        else:
            st.caption("Google Sheets delivery is disabled for this client.")
```

Then, in the `ClientProfile(...)` constructor call (search for
`lead_template_mapping=LeadTemplateMappingConfig(` to find the exact
block), add a sibling argument:

```python
            google_sheets=GoogleSheetsConfig(
                enabled=gs_enabled,
                tabs=gs_tabs if gs_enabled else [],
                mapping=LeadTemplateMappingConfig(rules=gs_mapping_rules if gs_enabled else []),
            ),
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_client_setup_page.py -k google_sheets -v`
Expected: PASS

- [ ] **Step 5: Run the full Client Setup suite**

Run: `python -m pytest tests/test_client_setup_page.py -q`
Expected: PASS, all tests (including every pre-existing one — confirms
no regression to the section it's inserted after)

- [ ] **Step 6: Commit**

```bash
git add pages/1_Client_Setup.py tests/test_client_setup_page.py
git commit -m "Add Google Sheets Lead Delivery section to Client Setup"
```

---

### Task 5: Settings credentials section, pipeline wiring, and write-path integration

**Files:**
- Modify: `pages/3_Settings.py`
- Modify: `core/pipeline.py`
- Modify: `pages/2_Run_Check.py`
- Test: `tests/test_settings_page.py`, `tests/test_pipeline.py`, `tests/test_run_check_page.py`

**Interfaces:**
- Consumes: `get_google_sheets_key_path`/`save_google_sheets_key_path`
  (Task 2); `core.excel_io.resolve_lead_template_rules`,
  `_resolve_passthrough_columns` (Task 3, existing); `google_sheets_client.append_rows`
  (Task 3); `check_lead_template_mandatory_columns` (existing, from the
  prior feature — reused unchanged, called a second time against
  `profile.google_sheets.mapping`).

- [ ] **Step 1: Settings section — write the failing test**

Read `tests/test_settings_page.py`'s existing Integrate-credentials save
test (search for `"Save Integrate credentials"`) to copy its exact
pattern, then add:

```python
def test_saving_google_sheets_key_path_persists_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.text_input(key="google_sheets_key_path_input").set_value(str(tmp_path / "key.json")).run()
    next(b for b in at.button if "Save Google Sheets key path" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_google_sheets_key_path
    assert get_google_sheets_key_path() == str(tmp_path / "key.json")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_settings_page.py -k google_sheets -v`
Expected: FAIL (widget doesn't exist)

- [ ] **Step 3: Add the Settings section**

Add `get_google_sheets_key_path, save_google_sheets_key_path` to the
existing `core.app_settings` import line in `pages/3_Settings.py`. Add
this new expander directly after the existing "🔑 Integrate API
credentials" section:

```python
with st.expander("🔑 Google Sheets service account (private to this machine)", expanded=False):
    st.caption(
        "Used by any client with Google Sheets Lead Delivery enabled. One shared service-account key file "
        "for the whole org — each individual Sheet still needs to be shared with that service account's "
        "email as Editor. This is a live credential, so only its local file path is stored here, never "
        "inside the shared clients folder above."
    )
    google_sheets_key_path = st.text_input(
        "Path to the service account JSON key file", value=get_google_sheets_key_path(),
        key="google_sheets_key_path_input")
    if st.button("Save Google Sheets key path", key="google_sheets_key_path_save"):
        save_google_sheets_key_path(google_sheets_key_path)
        queue_toast_before_rerun("Saved.")
        st.rerun()
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/test_settings_page.py -q`
Expected: PASS, all tests

- [ ] **Step 5: Pipeline wiring — write the failing test**

Read `core/pipeline.py`'s existing `run_pipeline` tests (search
`tests/test_pipeline.py` for the Lead Template mandatory-column test from
the prior feature) to copy its exact fixture pattern, then add:

```python
def test_run_pipeline_flags_every_lead_when_a_mandatory_google_sheets_column_has_no_source(...):
    # Build a ClientProfile the same way the existing Lead Template
    # mandatory-column test does, but set google_sheets=GoogleSheetsConfig(
    #   mapping=LeadTemplateMappingConfig(rules=[LeadTemplateColumnRule(
    #     template_column="Totally Unmatched Column", mandatory=True)]))
    # instead of lead_template_mapping. Assert every lead's review_reasons
    # contains a "Google Sheets Mapping" flag (distinct check label from
    # "Lead Template Mapping").
    ...


def test_run_pipeline_with_no_mandatory_google_sheets_rules_is_unaffected(...):
    # Same zero-rule-configured non-regression shape as the existing
    # Lead Template equivalent test.
    ...
```

(Write these using the EXACT fixture helper this test file's existing
`run_pipeline` tests already use — read them first, don't invent a new
pattern.)

- [ ] **Step 6: Run it to verify it fails**

Run: `python -m pytest tests/test_pipeline.py -k google_sheets -v`
Expected: FAIL (no such stage wired yet)

- [ ] **Step 7: Wire the second mandatory-check call into `run_pipeline`**

In `core/pipeline.py`, directly after the existing block:
```python
    if any(r.mandatory for r in profile.lead_template_mapping.rules):
        report("Checking Lead Template Mandatory Columns")
        merge(lead_template_mapping.check_lead_template_mandatory_columns(
            new_leads, fm, profile.lead_template_mapping))
```
add:
```python
    if any(r.mandatory for r in profile.google_sheets.mapping.rules):
        report("Checking Google Sheets Mandatory Columns")
        merge(lead_template_mapping.check_lead_template_mandatory_columns(
            new_leads, fm, profile.google_sheets.mapping))
```

This reuses `check_lead_template_mandatory_columns` completely unchanged
— it only reads `config.rules`, never anything Excel-specific — but each
`ReviewDetail` it produces carries `check="Lead Template Mapping"`
regardless of which config triggered it (read
`core/checks/lead_template_mapping.py` to confirm — if the `check=`
value really is hardcoded rather than parameterized, that's fine for
this task: a lead review-flagged by EITHER config still correctly goes to
Needs Review either way, and distinguishing the two check labels in the
UI is a nice-to-have, not required for correctness. Do not modify
`check_lead_template_mandatory_columns` itself to add a `check_label`
parameter unless you determine it's trivial and low-risk — if it would
require touching call sites in three already-shipped, already-tested
files, leave the shared label as-is and note this in your report instead
of expanding scope).

- [ ] **Step 8: Run it to verify it passes**

Run: `python -m pytest tests/test_pipeline.py -q`
Expected: PASS, all tests

- [ ] **Step 9: `_stage_labels`/`_completed_checks` — write the failing test**

Read `tests/test_run_check_page.py`'s existing
`test_run_check_button_succeeds_for_client_with_mandatory_lead_template_rule`
test (from the bugfix earlier this session) to copy its EXACT pattern,
then add:

```python
def test_run_check_button_succeeds_for_client_with_mandatory_google_sheets_rule(...):
    # Same shape as the Lead Template equivalent, but with
    # google_sheets=GoogleSheetsConfig(mapping=LeadTemplateMappingConfig(
    #   rules=[LeadTemplateColumnRule(template_column="X", mandatory=True)]))
    # instead. Click "Run Check" via a real AppTest button click. Assert
    # not at.exception AND "run_result" in at.session_state (mirroring
    # the exact assertion style that test uses, since a raw
    # `assert not at.exception` alone would pass identically whether the
    # bug is present or fixed -- render_error swallows the ValueError via
    # st.error(), so at.exception never actually fires for this class of
    # bug; the stronger assertion is what actually discriminates).
    ...
```

- [ ] **Step 10: Run it to verify it fails**

Run: `python -m pytest tests/test_run_check_page.py -k google_sheets -v`
Expected: FAIL with `ValueError: 'Checking Google Sheets Mandatory Columns' is not in list`
(the exact bug class this step exists to prevent)

- [ ] **Step 11: Add the missing stage-label entries**

In `pages/2_Run_Check.py`, find `_stage_labels` (search
`("Checking Dedupe List", profile.dedupe_list.enabled),` — the new Lead
Template entry from the earlier bugfix should already be the line right
after it) and add, immediately after that Lead Template entry:

```python
                ("Checking Google Sheets Mandatory Columns", any(r.mandatory for r in profile.google_sheets.mapping.rules)),
```

Find `_completed_checks` (search for the Lead Template entry added in
the earlier bugfix, e.g. `("Lead Template Mapping", ...)`) and add,
immediately after it:

```python
            ("Google Sheets Mapping", any(r.mandatory for r in profile.google_sheets.mapping.rules)),
```

Confirm both placements match the ACTUAL call order in `core/pipeline.py`
(read it directly — the Google Sheets check you just added in Step 7 is
called AFTER the Lead Template check, so these entries belong after the
Lead Template ones, not before) — do not just assume "last," verify it.

- [ ] **Step 12: Run it to verify it passes**

Run: `python -m pytest tests/test_run_check_page.py -k google_sheets -v`
Expected: PASS

- [ ] **Step 13: Write-path integration — write the failing test**

Add a test to `tests/test_run_check_page.py` (or a focused new test file
if that one is getting unwieldy — check its current line count first)
that: configures a client with `google_sheets.enabled=True` and one
`GoogleSheetTab`, mocks `core.google_sheets_client.append_rows` (same
mocking pattern as `tests/test_google_sheets_client.py`'s own tests,
applied here via `unittest.mock.patch("pages.2_Run_Check.google_sheets_client.append_rows", ...)`
or however this file's existing Convertr/Enhancio-equivalent tests mock
an external write call — read one of those first), uploads a leadfile,
runs Run Check through to Finalize, and asserts `append_rows` was called
once with the expected resolved row data.

- [ ] **Step 14: Run it to verify it fails**

Run the new test. Expected: FAIL (no Sheets write wired into
`_finalize_write` yet).

- [ ] **Step 15: Wire the write into `_finalize_write`**

Add `from core import google_sheets_client` and
`from core.google_sheets_client import GoogleSheetsError` to
`pages/2_Run_Check.py`'s imports if not already present. Add
`resolve_lead_template_rules` to the existing `core.excel_io` import
line. Read the CURRENT end of `_finalize_write` (search for `return
lead_template_links_used`) and insert, directly before that return:

```python
        if profile.google_sheets.enabled and not valid_leads_df.empty:
            _gs_key_path = get_google_sheets_key_path()
            if not _gs_key_path:
                st.error("Set the Google Sheets service account key path on the ⚙️ Settings page first.")
            else:
                _gs_manual_overrides, _gs_date_formats = resolve_lead_template_rules(profile.google_sheets.mapping)
                _gs_tab_by_cid = {t.cid: t for t in profile.google_sheets.tabs}
                _gs_unmatched_cids = []
                for cid, group in valid_leads_df.groupby(valid_leads_df[profile.field_mapping.cid].astype(str)):
                    tab = _gs_tab_by_cid.get(cid)
                    if tab is None:
                        _gs_unmatched_cids.append(cid)
                        continue
                    try:
                        _gs_headers = google_sheets_client.read_sheet_headers(_gs_key_path, tab.sheet_id, tab.worksheet_name)
                        _gs_col_source, _ = _resolve_passthrough_columns(
                            _gs_headers, group, profile.field_mapping, None, set(),
                            manual_overrides=_gs_manual_overrides)
                        _gs_rows = []
                        for _, lead_row in group.iterrows():
                            _row = {}
                            for _idx, _header in enumerate(_gs_headers, start=1):
                                _source_col = _gs_col_source.get(_idx)
                                _row[_header] = str(lead_row.get(_source_col, "") or "") if _source_col else ""
                            _gs_rows.append(_row)
                        google_sheets_client.append_rows(_gs_key_path, tab.sheet_id, tab.worksheet_name, _gs_rows)
                    except GoogleSheetsError as exc:
                        render_error(exc)
                if _gs_unmatched_cids:
                    st.warning(
                        f"⚠️ {len(_gs_unmatched_cids)} valid lead(s) had a CID with no matching Google Sheet "
                        f"(CIDs: {', '.join(sorted(_gs_unmatched_cids))}) — skipped for Google Sheets delivery, "
                        "but still added to the Accumulated Report."
                    )
```

(This block intentionally does NOT use `_resolve_date_format`/date
formatting inline here beyond what `_gs_date_formats` computes — if you
find, while implementing, that date-formatted values need explicit
per-cell handling before being placed into `_row` (matching how
`append_leads`' own per-row loop applies `date_formats`), add that
handling here following the exact same pattern `append_leads` uses for
its date-format branch, rather than skipping it — a client that
configured a date format on a Google Sheets column must see it actually
applied, not silently ignored.)

- [ ] **Step 16: Run it to verify it passes**

Run the new test from Step 13. Expected: PASS.

- [ ] **Step 17: Run the full suites for every file touched this task**

Run: `python -m pytest tests/test_settings_page.py tests/test_pipeline.py tests/test_run_check_page.py -q`
Expected: PASS, all tests (including every pre-existing one)

- [ ] **Step 18: Commit**

```bash
git add pages/3_Settings.py core/pipeline.py pages/2_Run_Check.py tests/test_settings_page.py tests/test_pipeline.py tests/test_run_check_page.py
git commit -m "Wire Google Sheets credentials, mandatory-check, and write-path into Run Check"
```

---

### Task 6: Full verification, manual smoke test, and PyInstaller rebuild

**Files:** none new — verification only, unless a bug surfaces.

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`
Expected: everything passes except the 2 pre-existing, unrelated
`tests/test_end_to_end_basware.py` errors.

- [ ] **Step 2: Manually verify in the browser**

Start the dev server, log in, and on a throwaway test client:
- Set the Google Sheets service-account key path in Settings (use the
  REAL key file already created for this project — path is in the
  `google_sheets_service_account` memory file — since a live smoke test
  needs a real, working credential, not a fake one).
- In Client Setup, enable Google Sheets delivery, map one CID to a
  throwaway test Sheet (create a new, empty Google Sheet for this test —
  NOT the real "China Webinar" sheet — with a header row like `Email,
  First Name`, shared with the service account as Editor), confirm the
  live header-read preview renders with no exceptions, mark one column
  mandatory, save.
- On Run Check, upload a leadfile with one lead missing the mandatory
  column's value and one lead with it, run the check, confirm the
  missing one is flagged Needs Review and the other is valid.
- Finalize/write the valid lead, then confirm (via the Sheet's own UI, or
  a quick `gspread` read) that the row actually landed in the test Sheet
  with the right values.
- Check `read_console_messages(onlyErrors: true)` for new/unexpected
  errors.
- Clean up: remove the throwaway test client profile and the throwaway
  test Google Sheet (or its test row) afterward.

- [ ] **Step 3: Rebuild the packaged exe**

Check whether `LeadQAAutomation.exe` is currently running
(`tasklist //FI "IMAGENAME eq LeadQAAutomation.exe"`); if so, ask the
user for permission to close it before rebuilding (same established
rhythm as every other rebuild this session). Then:
`python -m PyInstaller LeadQAAutomation.spec --noconfirm`. Launch the
rebuilt exe briefly to confirm it starts with no import errors (the new
`gspread`/`google-auth` dependency must be correctly bundled — if
PyInstaller's analysis misses a hidden import somewhere in `gspread`'s
own dependency tree, this is where it would surface as an `ImportError`
at runtime, not at build time).

- [ ] **Step 4: Report results**

Commit any fix needed if step 2 or step 3 surfaces a real bug, with a
regression test, clearly labeled in the final report.

## Self-Review Notes

- **Spec coverage:** data model (Task 1), dependency + credential storage
  (Task 2), shared extraction + Sheets client (Task 3), Client Setup UI
  (Task 4), Settings/pipeline/write-path wiring including the
  explicitly-required `_stage_labels`/`_completed_checks` entries (Task
  5), full verification + packaged-exe rebuild (Task 6). Every "In scope"
  item from the spec has a task producing it; every "Out of scope" item
  (Accumulated Report via Sheets, reading FROM Sheets) has no task, as
  intended.
- **The `_stage_labels` lesson is directly encoded** as an explicit,
  named step (Task 5 Steps 9-12) rather than left implicit — this is the
  one thing that shipped broken in the prior feature and is the highest-
  value thing this plan must not repeat.
- **Type consistency check:** `GoogleSheetTab`/`GoogleSheetsConfig`'s
  field names (`cid`, `sheet_id`, `worksheet_name`, `enabled`, `tabs`,
  `mapping`) are used identically across Task 1's dataclass, Task 4's UI
  save code, and Task 5's pipeline/write-path code. `resolve_lead_template_rules`'s
  return shape (`(manual_overrides: dict[str,str], date_formats: dict[str, tuple[str,str]])`)
  matches between Task 3's extraction and Task 5's write-path consumer.
  `google_sheets_client.append_rows`'s signature
  (`key_path, sheet_id, worksheet_name, rows: list[dict[str,str]]`) matches
  between Task 3's definition and Task 5's call site.

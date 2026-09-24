# Lead Template Column Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** At Client Setup, let the user preview which Lead Template
columns the app's existing auto-matcher can/can't resolve from a
leadfile, manually override a column's source, mark columns mandatory
(blank value → flagged for review), and set a per-column output date
format — all additive, with zero behavior change for any client that
hasn't configured a rule.

**Architecture:** A new `LeadTemplateMappingConfig` (list of
`LeadTemplateColumnRule`) on `ClientProfile`. `core/excel_io.py`'s
existing `_resolve_passthrough_columns`/`append_leads` gain an optional
manual-override + date-format layer on top of their current exact→
synonym→fuzzy chain. A new `core/checks/lead_template_mapping.py` check
plugs into the existing `run_pipeline`/`CheckOutcome` mechanism. A new
Client Setup section drives all of it.

**Tech Stack:** Python, pandas, openpyxl, Streamlit, pytest.

## Global Constraints

- With `LeadTemplateMappingConfig.rules == []` (every existing client,
  today), `append_leads`, `_resolve_passthrough_columns`, and
  `run_pipeline` must behave byte-for-byte identically to their current
  behavior. Every new parameter is optional/defaulted; every new code
  path is gated on rules being non-empty.
- Date format presets and their strftime equivalents:
  `"MM/DD/YYYY" → "%m/%d/%Y"`, `"DD/MM/YYYY" → "%d/%m/%Y"`,
  `"DD-MMM-YY" → "%d-%b-%y"`, `"YYYY-MM-DD" → "%Y-%m-%d"`,
  `"YYYY-MM-DD HH:MM:SS" → "%Y-%m-%d %H:%M:%S"`. A rule's `date_format`
  may also be any other raw strftime string directly (the "Custom..."
  UI option) — resolution is "look up the preset name; if not a known
  preset, use the string as-is."
- Excel number-format strings must have their `/` characters escaped
  (`\/`) exactly like the existing `_DATE_NUMBER_FORMAT = "mm\\/dd\\/yyyy"`
  constant in `core/excel_io.py` — an unescaped `/` is read as "use
  whatever date separator Windows' Regional Settings configures," not a
  literal slash (confirmed root cause of a real Dell EMEA bug this
  session).
- Manual column-override matching and mandatory-column resolution both
  use `core.excel_io.normalize_header_text`/`find_passthrough_lead_column`
  — no new/parallel text-normalization logic.
- Only columns actually touched (mandatory, source override, or date
  format set) get saved as a rule — a column left at every default is
  never written to the profile JSON.
- Run the affected test file(s) after each task; run the full suite
  (`python -m pytest -q`) before considering the plan done.

---

### Task 1: Data model — `LeadTemplateColumnRule` / `LeadTemplateMappingConfig`

**Files:**
- Modify: `core/models.py`
- Modify: `core/profile_store.py`
- Test: `tests/test_models.py`, `tests/test_profile_store.py` (check with
  `ls tests/test_profile_store.py` first — if it doesn't exist, check
  whether profile round-trip tests live somewhere else, e.g.
  `tests/test_client_setup_page.py`, by searching for `lead_template_tabs`
  in the test directory: `grep -rn "lead_template_tabs" tests/`. Put the
  new round-trip test in whichever file already covers `LeadTemplateTab`'s
  own round-trip, or `tests/test_models.py` if none does.)

**Interfaces:**
- Produces: `LeadTemplateColumnRule(template_column: str, source_column: str = "", mandatory: bool = False, date_format: str = "")`;
  `LeadTemplateMappingConfig(rules: list[LeadTemplateColumnRule] = [])`;
  `ClientProfile.lead_template_mapping: LeadTemplateMappingConfig`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_models.py (append)
from core.models import ClientProfile, LeadTemplateColumnRule, LeadTemplateMappingConfig


def test_client_profile_defaults_to_an_empty_lead_template_mapping():
    profile = ClientProfile(name="X", accumulated_report_path="acc.xlsx")
    assert profile.lead_template_mapping.rules == []


def test_lead_template_column_rule_defaults():
    rule = LeadTemplateColumnRule(template_column="Company Size")
    assert rule.source_column == ""
    assert rule.mandatory is False
    assert rule.date_format == ""
```

```python
# In whichever test file already round-trips LeadTemplateTab via
# save_profile/load_profile (find it with the grep command above) — add:
def test_lead_template_mapping_rules_round_trip_through_save_and_load(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.app_settings import get_clients_dir
    from core.models import ClientProfile, LeadTemplateColumnRule, LeadTemplateMappingConfig
    from core.profile_store import save_profile, load_profile

    profile = ClientProfile(
        name="Test Client", accumulated_report_path="acc.xlsx",
        lead_template_mapping=LeadTemplateMappingConfig(rules=[
            LeadTemplateColumnRule(
                template_column="Company Size", source_column="Employee Count",
                mandatory=True, date_format=""),
            LeadTemplateColumnRule(
                template_column="Capture Date", source_column="", mandatory=False,
                date_format="MM/DD/YYYY"),
        ]),
    )
    save_profile(profile, get_clients_dir())

    loaded = load_profile("Test Client", get_clients_dir())

    assert loaded.lead_template_mapping.rules == profile.lead_template_mapping.rules
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_models.py -k lead_template_mapping -v`
Expected: FAIL with `ImportError: cannot import name 'LeadTemplateColumnRule'`

- [ ] **Step 3: Add the dataclasses to `core/models.py`**

Add directly after the existing `LeadTemplateTab` dataclass (search for
`class LeadTemplateTab:` to find the exact spot):

```python
@dataclass
class LeadTemplateColumnRule:
    # Exact Lead Template header text this rule applies to.
    template_column: str
    # Blank means "use the existing auto-match chain unchanged"
    # (core.excel_io._resolve_passthrough_columns) -- set only to
    # override it with a specific leadfile column name.
    source_column: str = ""
    # A blank/unmapped value for this column on a given lead gets flagged
    # for review (core.checks.lead_template_mapping) instead of silently
    # written blank -- only for columns the user actually marks.
    mandatory: bool = False
    # Blank means "no special formatting -- pass the leadfile's raw value
    # through unchanged," exactly like every column does today. A preset
    # name ("MM/DD/YYYY", "DD/MM/YYYY", "DD-MMM-YY", "YYYY-MM-DD",
    # "YYYY-MM-DD HH:MM:SS") or a custom strftime-style string.
    date_format: str = ""


@dataclass
class LeadTemplateMappingConfig:
    rules: list[LeadTemplateColumnRule] = field(default_factory=list)
```

Then find `@dataclass class ClientProfile:` and add a new field alongside
the existing `lead_template_tabs: list[LeadTemplateTab] = field(default_factory=list)`
line:

```python
    lead_template_mapping: LeadTemplateMappingConfig = field(default_factory=LeadTemplateMappingConfig)
```

- [ ] **Step 4: Wire deserialization into `core/profile_store.py`**

Read `core/profile_store.py` first to find the exact existing pattern for
`lead_template_tabs` (search for `lead_template_tabs = [LeadTemplateTab(**t)`)
and mirror it. Add `LeadTemplateColumnRule, LeadTemplateMappingConfig` to
the existing `from core.models import (...)` line. Then, near the
existing `lead_template_tabs = [...]` line inside `load_profile`, add:

```python
    _ltm_data = data.get("lead_template_mapping") or {}
    lead_template_mapping = LeadTemplateMappingConfig(
        rules=[LeadTemplateColumnRule(**r) for r in _ltm_data.get("rules", [])])
```

Then add `lead_template_mapping=lead_template_mapping,` as a sibling
argument to the `ClientProfile(...)` constructor call inside
`load_profile` (same block where `lead_template_tabs=lead_template_tabs,`
already appears).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_models.py -k lead_template_mapping -v`
Then run whichever file you added the round-trip test to, e.g.:
Run: `python -m pytest tests/test_client_setup_page.py -k lead_template_mapping -v`
(adjust to the actual file/test name you used)
Expected: PASS

- [ ] **Step 6: Run the full model/profile_store-adjacent suite**

Run: `python -m pytest tests/test_client_setup_page.py -q`
Expected: PASS, unchanged (new field defaults to an empty config, so
every existing profile round-trips identically)

- [ ] **Step 7: Commit**

```bash
git add core/models.py core/profile_store.py tests/test_models.py <the other test file you edited>
git commit -m "Add LeadTemplateColumnRule/LeadTemplateMappingConfig to ClientProfile"
```

---

### Task 2: Manual override support in `_resolve_passthrough_columns`

**Files:**
- Modify: `core/excel_io.py`
- Test: `tests/test_excel_io_generic.py` (search for
  `_resolve_passthrough_columns` or `find_passthrough_lead_column` to
  find where its existing tests live, and add alongside them)

**Interfaces:**
- Consumes: nothing new from other tasks (this task only touches
  `_resolve_passthrough_columns`'s own signature).
- Produces: `_resolve_passthrough_columns(headers, leads_df, field_mapping, target_field_mapping, skip_normalized, manual_overrides: dict[str, str] | None = None)`
  — `manual_overrides` keys are `normalize_header_text`-normalized
  template header text, values are the exact leadfile column name to use.

- [ ] **Step 1: Write the failing tests**

First read the existing `_resolve_passthrough_columns` docstring/tests in
`core/excel_io.py`/`tests/test_excel_io_generic.py` to match the exact
existing test fixture style (a `leads_df`, a `field_mapping`, a headers
list), then add:

```python
def test_resolve_passthrough_columns_manual_override_wins_over_auto_match():
    from core.excel_io import _resolve_passthrough_columns
    from core.models import FieldMapping
    import pandas as pd

    leads_df = pd.DataFrame([{"Company Size": "50", "Employee Count": "75"}])
    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")

    # Without an override, "Company Size" auto-matches to the identically
    # named leadfile column (exact match beats anything else).
    column_source, unmatched = _resolve_passthrough_columns(
        ["Company Size"], leads_df, fm, None, set())
    assert column_source[1] == "Company Size"

    # With an override, it's redirected to a DIFFERENT leadfile column
    # even though an exact-name match also exists.
    column_source, unmatched = _resolve_passthrough_columns(
        ["Company Size"], leads_df, fm, None, set(),
        manual_overrides={"companysize": "Employee Count"})
    assert column_source[1] == "Employee Count"
    assert unmatched == []


def test_resolve_passthrough_columns_manual_override_of_nonexistent_column_falls_back_to_auto_match():
    from core.excel_io import _resolve_passthrough_columns
    from core.models import FieldMapping
    import pandas as pd

    leads_df = pd.DataFrame([{"Company Size": "50"}])
    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")

    # The override names a column that doesn't actually exist in this
    # leadfile -- must NOT silently resolve to nothing; falls back to the
    # normal auto-match chain, which finds the exact-name match.
    column_source, unmatched = _resolve_passthrough_columns(
        ["Company Size"], leads_df, fm, None, set(),
        manual_overrides={"companysize": "Nonexistent Column"})
    assert column_source[1] == "Company Size"
    assert unmatched == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_excel_io_generic.py -k manual_override -v`
Expected: FAIL with `TypeError: _resolve_passthrough_columns() got an unexpected keyword argument 'manual_overrides'`

- [ ] **Step 3: Add the parameter**

In `core/excel_io.py`, modify `_resolve_passthrough_columns`'s signature
and body (the exact current body is what you'll read when you open the
file — insert the override check as the FIRST check inside the per-header
loop, before the existing `target_role_by_header` check, since a manual
override is the highest-priority source):

```python
def _resolve_passthrough_columns(
    headers: list, leads_df: pd.DataFrame, field_mapping: FieldMapping,
    target_field_mapping: FieldMapping | None, skip_normalized: set[str],
    manual_overrides: dict[str, str] | None = None,
) -> tuple[dict[int, str | None], list[str]]:
    """[keep the existing docstring, then add:]

    manual_overrides ({normalized template header: leadfile column name})
    takes priority over every other resolution source when the named
    leadfile column actually exists in leads_df -- an override naming a
    column that doesn't exist in THIS leadfile falls back to the normal
    auto-match chain below rather than silently resolving to nothing.
    """
    manual_overrides = manual_overrides or {}
    lead_headers_norm = {normalize_header_text(h): h for h in leads_df.columns}
    target_role_by_header: dict[str, str] = {}
    if target_field_mapping is not None:
        for attr in ("email", "first_name", "last_name", "company", "cid"):
            target_header = getattr(target_field_mapping, attr, "")
            if target_header:
                target_role_by_header[normalize_header_text(target_header)] = attr

    column_source: dict[int, str | None] = {}
    unmatched_passthrough_headers: list[str] = []
    for col_idx, header in enumerate(headers, start=1):
        if header is None:
            continue
        header_norm = normalize_header_text(header)
        if header_norm in skip_normalized:
            continue
        override_col = manual_overrides.get(header_norm)
        if override_col and override_col in leads_df.columns:
            column_source[col_idx] = override_col
            continue
        if header_norm in target_role_by_header:
            column_source[col_idx] = getattr(field_mapping, target_role_by_header[header_norm])
            continue
        attr = _resolve_field_attr(header_norm)
        if attr:
            column_source[col_idx] = getattr(field_mapping, attr)
            continue
        source_col = find_passthrough_lead_column(header_norm, lead_headers_norm)
        column_source[col_idx] = source_col
        if source_col is None:
            unmatched_passthrough_headers.append(header)
    return column_source, unmatched_passthrough_headers
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_excel_io_generic.py -k "manual_override or passthrough" -v`
Expected: PASS

- [ ] **Step 5: Run the full excel_io test suite to confirm the default (no-override) behavior is unchanged**

Run: `python -m pytest tests/test_excel_io_generic.py tests/test_excel_io_append.py -q`
Expected: PASS, unchanged (every existing call passes no `manual_overrides`,
which defaults to `{}` — identical to before this change)

- [ ] **Step 6: Commit**

```bash
git add core/excel_io.py tests/test_excel_io_generic.py
git commit -m "Add manual column-override support to _resolve_passthrough_columns"
```

---

### Task 3: Date-format support in `append_leads`

**Files:**
- Modify: `core/excel_io.py`
- Test: `tests/test_excel_io_append.py`

**Interfaces:**
- Consumes: `LeadTemplateColumnRule`, `LeadTemplateMappingConfig` (Task 1);
  `_resolve_passthrough_columns`'s new `manual_overrides` param (Task 2).
- Produces: `append_leads(..., lead_template_mapping: LeadTemplateMappingConfig | None = None)`
  (new trailing optional param, both the top-level dispatcher and its
  `_append_leads_csv` helper). Also produces `_DATE_FORMAT_PRESETS: dict[str, str]`
  (preset name → strftime string) and `_resolve_date_format(name: str) -> str`
  (preset lookup, else the string itself) as new module-level helpers in
  `core/excel_io.py`.

- [ ] **Step 1: Write the failing tests**

First read `core/excel_io.py`'s existing `append_leads` xlsx-branch tests
in `tests/test_excel_io_append.py` to copy their exact workbook-fixture
style (how they build a template workbook with openpyxl, call
`append_leads`, then reopen and assert on cell values/number_format).
Then add:

```python
def test_append_leads_applies_a_configured_date_format_to_xlsx(tmp_path):
    import openpyxl
    from core.excel_io import append_leads
    from core.models import FieldMapping, LeadTemplateColumnRule, LeadTemplateMappingConfig
    import pandas as pd

    path = str(tmp_path / "template.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Email", "Capture Date"])
    wb.save(path)

    fm = FieldMapping(email="Email", first_name="", last_name="", company="", cid="")
    leads_df = pd.DataFrame([{"Email": "a@x.com", "Capture Date": "2026-03-15"}])
    ltm = LeadTemplateMappingConfig(rules=[
        LeadTemplateColumnRule(template_column="Capture Date", date_format="YYYY-MM-DD"),
    ])

    append_leads(path, "Sheet1", leads_df, fm, run_date=None, lead_template_mapping=ltm)

    wb2 = openpyxl.load_workbook(path)
    cell = wb2["Sheet1"].cell(row=2, column=2)
    assert cell.value.strftime("%Y-%m-%d") == "2026-03-15"
    assert cell.number_format == "yyyy\\-mm\\-dd"


def test_append_leads_keeps_unparseable_date_value_as_raw_text(tmp_path):
    import openpyxl
    from core.excel_io import append_leads
    from core.models import FieldMapping, LeadTemplateColumnRule, LeadTemplateMappingConfig
    import pandas as pd

    path = str(tmp_path / "template.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Email", "Capture Date"])
    wb.save(path)

    fm = FieldMapping(email="Email", first_name="", last_name="", company="", cid="")
    leads_df = pd.DataFrame([{"Email": "a@x.com", "Capture Date": "not a date"}])
    ltm = LeadTemplateMappingConfig(rules=[
        LeadTemplateColumnRule(template_column="Capture Date", date_format="YYYY-MM-DD"),
    ])

    append_leads(path, "Sheet1", leads_df, fm, run_date=None, lead_template_mapping=ltm)

    wb2 = openpyxl.load_workbook(path)
    cell = wb2["Sheet1"].cell(row=2, column=2)
    assert cell.value == "not a date"


def test_append_leads_applies_a_configured_date_format_to_csv(tmp_path):
    from core.excel_io import append_leads
    from core.models import FieldMapping, LeadTemplateColumnRule, LeadTemplateMappingConfig
    import pandas as pd

    path = str(tmp_path / "template.csv")
    with open(path, "w", encoding="utf-8") as f:
        f.write("Email,Capture Date\n")

    fm = FieldMapping(email="Email", first_name="", last_name="", company="", cid="")
    leads_df = pd.DataFrame([{"Email": "a@x.com", "Capture Date": "2026-03-15"}])
    ltm = LeadTemplateMappingConfig(rules=[
        LeadTemplateColumnRule(template_column="Capture Date", date_format="DD/MM/YYYY"),
    ])

    append_leads(path, "Sheet1", leads_df, fm, run_date=None, lead_template_mapping=ltm)

    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines[1] == "a@x.com,15/03/2026"
```

(If any of these three tests' exact fixture setup doesn't match how
`append_leads` is actually called elsewhere in the test file once you
read it — e.g. `run_date=None` might not be accepted, or the workbook
needs a different header row — adjust to match the real signature/
behavior you find; the ASSERTIONS are what matters, not the exact
fixture boilerplate.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_excel_io_append.py -k date_format -v`
Expected: FAIL (either `TypeError` on the new kwarg, or the date isn't
actually reformatted yet)

- [ ] **Step 3: Add the preset table and resolution helper**

Add near the existing `_DATE_NUMBER_FORMAT` constant in `core/excel_io.py`:

```python
# strftime string -> Excel number-format string (backslash-escaped, same
# reasoning as _DATE_NUMBER_FORMAT above -- an unescaped "/" or "-" is
# read as "whatever date separator Windows' Regional Settings configures,"
# not a literal character).
_DATE_FORMAT_PRESETS = {
    "MM/DD/YYYY": ("%m/%d/%Y", "mm\\/dd\\/yyyy"),
    "DD/MM/YYYY": ("%d/%m/%Y", "dd\\/mm\\/yyyy"),
    "DD-MMM-YY": ("%d-%b-%y", "dd\\-mmm\\-yy"),
    "YYYY-MM-DD": ("%Y-%m-%d", "yyyy\\-mm\\-dd"),
    "YYYY-MM-DD HH:MM:SS": ("%Y-%m-%d %H:%M:%S", "yyyy\\-mm\\-dd\\ hh:mm:ss"),
}


def _resolve_date_format(value: str) -> tuple[str, str]:
    """Resolves a LeadTemplateColumnRule.date_format value to
    (strftime_string, excel_number_format). A known preset name resolves
    to its pair above; anything else is treated as a raw strftime string
    directly (the "Custom..." UI option), with its Excel number format
    approximated by escaping every "/"/"-" the same way the presets do --
    good enough for a custom format, since Excel's own format-code syntax
    and Python's strftime syntax mostly overlap for date tokens anyway.
    """
    if value in _DATE_FORMAT_PRESETS:
        return _DATE_FORMAT_PRESETS[value]
    escaped = value.replace("/", "\\/").replace("-", "\\-")
    return value, escaped
```

- [ ] **Step 4: Thread `lead_template_mapping` through `append_leads` and `_append_leads_csv`**

Read the current full body of `append_leads` and `_append_leads_csv` in
`core/excel_io.py` (they were shown earlier in this conversation, but the
file is the source of truth — re-read it now). Make these changes:

1. Add `lead_template_mapping: LeadTemplateMappingConfig | None = None` as
   the new final parameter of both `append_leads` and `_append_leads_csv`.
   `append_leads`'s CSV-dispatch line (`return _append_leads_csv(...)`)
   must pass it through.
2. At the top of both functions (right where `column_source, unmatched_passthrough_headers = _resolve_passthrough_columns(...)`
   is called), build:
   ```python
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
   ```
   and pass `manual_overrides=manual_overrides` into the existing
   `_resolve_passthrough_columns(...)` call (added as its new trailing
   argument from Task 2).
3. **xlsx branch** — in the per-row/per-column writing loop (search for
   `source_col = column_source.get(col_idx)` inside `append_leads`), after
   the existing value assignment and BEFORE the two existing
   `was_general_format`/date-number-format `if`/`elif` checks that follow
   it, insert a new check that takes priority over those (a header with a
   configured date_format always gets that format, regardless of whether
   the cell started as "General"):
   ```python
   date_fmt = date_formats.get(header_norm)
   if date_fmt is not None and source_col is not None:
       strftime_fmt, excel_fmt = date_fmt
       raw_value = lead_row.get(source_col, "")
       parsed = pd.to_datetime(raw_value, errors="coerce")
       if pd.isna(parsed) and isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
           # Bare Excel serial number fallback -- same origin already
           # proven necessary elsewhere in this codebase (e.g.
           # core/enhancio_sync.py's _EXCEL_DATE_ORIGIN).
           parsed = pd.to_datetime(raw_value, unit="D", origin="1899-12-30", errors="coerce")
       if pd.notna(parsed):
           cell.value = parsed.to_pydatetime()
           cell.number_format = excel_fmt
       else:
           # Unparseable -- leave the raw text visible rather than
           # silently blanking a malformed source value.
           cell.value = str(raw_value) if raw_value not in (None, "") and pd.notna(raw_value) else None
   ```
   Place this as an `elif` chained onto the existing `if header_norm ==
   "date": ... elif header in formula_template: ... elif header_norm in
   ("comment", "status"): ...` chain (i.e. it should come BEFORE the final
   generic `else:` branch that does the normal passthrough assignment,
   since a date-formatted column is handled entirely by this new branch
   instead of falling through to the generic one).
4. **CSV branch** (`_append_leads_csv`) — in its per-row loop (search for
   `value = lead_row.get(source_col, "") if source_col is not None else ""`),
   add an equivalent check before that line:
   ```python
   date_fmt = date_formats.get(header_norm)
   if date_fmt is not None and source_col is not None:
       strftime_fmt, _ = date_fmt
       raw_value = lead_row.get(source_col, "")
       parsed = pd.to_datetime(raw_value, errors="coerce")
       if pd.isna(parsed) and isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
           parsed = pd.to_datetime(raw_value, unit="D", origin="1899-12-30", errors="coerce")
       value = parsed.strftime(strftime_fmt) if pd.notna(parsed) else (
           str(raw_value) if raw_value not in (None, "") and pd.notna(raw_value) else "")
   else:
       value = lead_row.get(source_col, "") if source_col is not None else ""
   ```
   (replacing, not duplicating, the original line — this `if/else` IS the
   new version of that line.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_excel_io_append.py -k date_format -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the full excel_io suite to confirm nothing else broke**

Run: `python -m pytest tests/test_excel_io_append.py tests/test_excel_io_generic.py -q`
Expected: PASS, unchanged for every existing test (none pass
`lead_template_mapping`, so it defaults to `None` → empty `date_formats`
dict → the new branches never fire, identical to current behavior)

- [ ] **Step 7: Commit**

```bash
git add core/excel_io.py tests/test_excel_io_append.py
git commit -m "Add per-column date-format support to append_leads"
```

---

### Task 4: Mandatory-column review check

**Files:**
- Create: `core/checks/lead_template_mapping.py`
- Modify: `core/pipeline.py`
- Test: `tests/test_checks_lead_template_mapping.py` (new file — check
  `ls tests/test_checks_*.py` first to match this repo's actual naming
  convention for a check-module test file, e.g. it might be
  `tests/test_check_exclusion.py` instead; use whatever pattern you find)

**Interfaces:**
- Consumes: `LeadTemplateMappingConfig` (Task 1); `normalize_header_text`,
  `find_passthrough_lead_column` (existing, from `core/excel_io.py`);
  `CheckOutcome`, `ReviewDetail` (existing, from `core/check_result.py`).
- Produces: `check_lead_template_mandatory_columns(new_leads: pd.DataFrame, field_mapping: FieldMapping, config: LeadTemplateMappingConfig) -> CheckOutcome`.

- [ ] **Step 1: Write the failing tests**

Read an existing check test file first (e.g.
`tests/test_check_exclusion.py` or wherever `check_exclusion` is tested —
find it with `grep -rln "check_exclusion" tests/`) to match this repo's
exact test-fixture style for a `CheckOutcome`-returning function, then
create the new test file modeled on it:

```python
# tests/test_checks_lead_template_mapping.py
import pandas as pd

from core.checks.lead_template_mapping import check_lead_template_mandatory_columns
from core.models import FieldMapping, LeadTemplateColumnRule, LeadTemplateMappingConfig

FM = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")


def test_flags_every_lead_once_when_mandatory_column_has_no_resolvable_source():
    new_leads = pd.DataFrame([
        {"Email": "a@x.com", "CID": "1"},
        {"Email": "b@x.com", "CID": "1"},
    ])
    config = LeadTemplateMappingConfig(rules=[
        LeadTemplateColumnRule(template_column="Totally Unmatched Column", mandatory=True),
    ])

    outcome = check_lead_template_mandatory_columns(new_leads, FM, config)

    assert set(outcome.review.keys()) == {0, 1}
    assert "Totally Unmatched Column" in outcome.review[0].message


def test_flags_only_rows_with_a_blank_value_in_a_resolvable_mandatory_column():
    new_leads = pd.DataFrame([
        {"Email": "a@x.com", "CID": "1", "Company Size": "50"},
        {"Email": "b@x.com", "CID": "1", "Company Size": ""},
        {"Email": "c@x.com", "CID": "1", "Company Size": float("nan")},
    ])
    config = LeadTemplateMappingConfig(rules=[
        LeadTemplateColumnRule(template_column="Company Size", mandatory=True),
    ])

    outcome = check_lead_template_mandatory_columns(new_leads, FM, config)

    assert set(outcome.review.keys()) == {1, 2}
    assert "Company Size" in outcome.review[1].message


def test_manual_source_override_is_used_for_mandatory_resolution():
    new_leads = pd.DataFrame([{"Email": "a@x.com", "CID": "1", "Employee Count": "75"}])
    config = LeadTemplateMappingConfig(rules=[
        LeadTemplateColumnRule(template_column="Company Size", source_column="Employee Count", mandatory=True),
    ])

    outcome = check_lead_template_mandatory_columns(new_leads, FM, config)

    assert outcome.review == {}


def test_non_mandatory_rule_never_produces_a_review_flag():
    new_leads = pd.DataFrame([{"Email": "a@x.com", "CID": "1"}])
    config = LeadTemplateMappingConfig(rules=[
        LeadTemplateColumnRule(template_column="Totally Unmatched Column", mandatory=False),
    ])

    outcome = check_lead_template_mandatory_columns(new_leads, FM, config)

    assert outcome.review == {}
    assert outcome.fail == {}


def test_empty_config_produces_no_flags():
    new_leads = pd.DataFrame([{"Email": "a@x.com", "CID": "1"}])
    outcome = check_lead_template_mandatory_columns(new_leads, FM, LeadTemplateMappingConfig())
    assert outcome.review == {} and outcome.fail == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_checks_lead_template_mapping.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.checks.lead_template_mapping'`

- [ ] **Step 3: Write the check**

```python
# core/checks/lead_template_mapping.py
import pandas as pd

from core.check_result import CheckOutcome, ReviewDetail
from core.excel_io import normalize_header_text, find_passthrough_lead_column
from core.models import FieldMapping, LeadTemplateMappingConfig


def _resolve_mandatory_source(rule, lead_headers_norm: dict[str, str]) -> str | None:
    if rule.source_column and rule.source_column in lead_headers_norm.values():
        return rule.source_column
    return find_passthrough_lead_column(normalize_header_text(rule.template_column), lead_headers_norm)


def check_lead_template_mandatory_columns(
    new_leads: pd.DataFrame, field_mapping: FieldMapping, config: LeadTemplateMappingConfig,
) -> CheckOutcome:
    """A lead with a blank value in a column the user marked mandatory
    (LeadTemplateColumnRule.mandatory) is flagged for review instead of
    silently written blank. Resolution of which leadfile column supplies
    a mandatory field reuses the exact same manual-override-then-fuzzy-
    match chain append_leads itself uses (find_passthrough_lead_column),
    so this check's verdict always matches what would actually be written.
    A mandatory column with NO resolvable leadfile column at all flags
    every lead once (there is nothing per-row to check); a mandatory
    column that DOES resolve flags only the rows whose value there is
    blank/NaN.
    """
    outcome = CheckOutcome()
    mandatory_rules = [r for r in config.rules if r.mandatory]
    if not mandatory_rules:
        return outcome

    lead_headers_norm = {normalize_header_text(h): h for h in new_leads.columns}

    for rule in mandatory_rules:
        source_col = _resolve_mandatory_source(rule, lead_headers_norm)
        if source_col is None:
            for idx in new_leads.index:
                outcome.review.setdefault(idx, ReviewDetail(
                    check="Lead Template Mapping",
                    message=f"No leadfile column found for mandatory field '{rule.template_column}'",
                ))
            continue
        for idx, value in new_leads[source_col].items():
            if pd.isna(value) or str(value).strip() == "":
                outcome.review.setdefault(idx, ReviewDetail(
                    check="Lead Template Mapping",
                    message=f"'{rule.template_column}' is required but blank",
                ))

    return outcome
```

Note: `outcome.review.setdefault` (not overwrite) so a lead already
flagged by an earlier mandatory rule in this same function keeps its
FIRST flag's message rather than a later rule silently replacing it —
matches this being one `CheckOutcome` merged once by the pipeline, same
as every other check already does (see `merge()` in `core/pipeline.py`,
which itself only ever adds one reason per check-call, not per-rule — a
review dict with multiple DISTINCT messages per lead isn't supported by
the existing `ReviewDetail`-per-idx shape, so this function intentionally
reports only the first mandatory-column problem per lead, consistent
with how `CheckOutcome.review` is a single `ReviewDetail` per index
everywhere else in this codebase).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_checks_lead_template_mapping.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Wire into `core/pipeline.py`**

Add the import (alongside the existing
`from core.checks import duplicate, leadcap, exclusion, tal, suppression, dedupe_list`
line):

```python
from core.checks import duplicate, leadcap, exclusion, tal, suppression, dedupe_list, lead_template_mapping
```

Then add, inside `run_pipeline`, after the existing `if
profile.dedupe_list.enabled:` block (the last check in the current
chain):

```python
    if any(r.mandatory for r in profile.lead_template_mapping.rules):
        report("Checking Lead Template Mandatory Columns")
        merge(lead_template_mapping.check_lead_template_mandatory_columns(
            new_leads, fm, profile.lead_template_mapping))
```

- [ ] **Step 6: Add a `run_pipeline`-level regression test confirming zero-rule behavior is unchanged**

Find `run_pipeline`'s existing tests (search `grep -rln "run_pipeline"
tests/`) and add:

```python
def test_run_pipeline_with_no_mandatory_lead_template_rules_is_unaffected(...):
    # Build the same minimal ClientProfile/new_leads fixture this test
    # file's OTHER run_pipeline tests already use (read one for the exact
    # pattern), leaving lead_template_mapping at its default (empty), and
    # assert the PipelineResult is identical to calling run_pipeline
    # before this feature existed -- i.e. just confirm no exception and
    # the expected valid_indices/review_reasons for a fixture with no
    # data-quality issues at all.
    ...
```

(Write this using whatever exact fixture pattern the existing
`run_pipeline` tests in this repo use — the important assertion is that
a `ClientProfile` with no `lead_template_mapping` rules configured
produces the exact same `PipelineResult` as before.)

- [ ] **Step 7: Run the full pipeline/checks suite**

Run: `python -m pytest tests/ -k "pipeline or checks_lead_template_mapping" -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add core/checks/lead_template_mapping.py core/pipeline.py tests/test_checks_lead_template_mapping.py <the run_pipeline test file you edited>
git commit -m "Add mandatory Lead Template column review check"
```

---

### Task 5: Client Setup UI section

**Files:**
- Modify: `pages/1_Client_Setup.py`
- Test: `tests/test_client_setup_page.py`

**Interfaces:**
- Consumes: `LeadTemplateColumnRule`, `LeadTemplateMappingConfig` (Task 1);
  the existing `_safe_read_template_headers` helper (already in this
  file); `core.excel_io.find_passthrough_lead_column`,
  `normalize_header_text` (existing); `core.excel_io.read_leadfile`
  (existing, for the new sample-leadfile uploader).
- Produces: the saved profile's `.lead_template_mapping` field, populated
  from this section's inputs.

- [ ] **Step 1: Write the failing test**

Read this file's existing Lead Template path/sheet save test (search for
`lead_template_path_input` or `"Lead Template path"` in
`tests/test_client_setup_page.py`) to copy its exact `AppTest` setup
(client name field, accumulated path field, Lead Template path/sheet
fields, and the "Save Client Profile" button — use the REAL key names/
label text you find there, not a guess), then add:

```python
def test_saving_lead_template_mapping_persists_mandatory_and_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    # Build a minimal real Lead Template workbook so _safe_read_template_headers
    # has something to read.
    import openpyxl
    template_path = str(tmp_path / "template.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Email", "Company Size"])
    wb.save(template_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    # [fill client name / accumulated path fields using the real keys you
    # found in Step 1's research]
    # [fill Lead Template path = template_path, sheet = "Sheet1"]

    at.checkbox(key="ltm_mandatory_Company Size").set_value(True).run()

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile
    saved = load_profile("<the client name you used>", get_clients_dir())
    rule = next(r for r in saved.lead_template_mapping.rules if r.template_column == "Company Size")
    assert rule.mandatory is True


def test_a_lead_template_column_left_at_every_default_is_not_saved_as_a_rule(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    import openpyxl
    template_path = str(tmp_path / "template.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Email", "Company Size"])
    wb.save(template_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    # [fill the same fields as above, but do NOT touch the "Company Size"
    # mandatory checkbox, source override, or date format at all]

    next(b for b in at.button if "Save Client Profile" in b.label).click().run()
    assert not at.exception

    from core.app_settings import get_clients_dir
    from core.profile_store import load_profile
    saved = load_profile("<the client name you used>", get_clients_dir())
    assert saved.lead_template_mapping.rules == []
```

(These two tests need real widget keys/labels this file actually uses —
write them by directly copying the setup boilerplate from an existing
save-flow test in the same file, adjusting only the new
Lead-Template-mapping-specific interactions.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_client_setup_page.py -k lead_template_mapping -v`
Expected: FAIL (the checkbox/widget keys don't exist yet)

- [ ] **Step 3: Add the Client Setup section**

Add `LeadTemplateColumnRule, LeadTemplateMappingConfig` to the existing
`from core.models import (...)` line. Add
`from core.excel_io import find_passthrough_lead_column, normalize_header_text, read_leadfile`
if any of these aren't already imported in this file (check first — some
may already be imported).

Find where the existing Lead Template path/sheet/tabs configuration ends
in this file (search for `lead_template_tabs_result` and the surrounding
block) and insert this new section directly after it, before whatever
section currently follows:

```python
        st.divider()
        st.markdown("**Lead Template Column Mapping (optional)**")
        st.caption(
            "Preview which Lead Template columns the app can auto-match from a leadfile, mark specific "
            "columns as mandatory (a blank value gets flagged for review instead of silently left blank), "
            "manually override a column's source, or set a specific date format for a column. Every "
            "column left untouched here keeps working exactly as it does today."
        )
        _ltm_template_headers: list[str] = []
        if lead_template_path and lead_template_sheet_name:
            _ltm_template_headers, _ltm_err = _safe_read_template_headers(
                lead_template_path, lead_template_sheet_name)
            if _ltm_err is not None:
                render_error(_ltm_err)

        _ltm_skip = {"date", "comment", "status", "refund reason", "reason"}
        _ltm_template_headers = [h for h in _ltm_template_headers if normalize_header_text(h) not in _ltm_skip]

        _ltm_sample_file = st.file_uploader(
            "Sample leadfile (optional — lets this preview show real auto-match results and pick a source "
            "column from a dropdown instead of typing it)",
            type=["xlsx", "csv"], key="ltm_sample_file")
        _ltm_sample_headers: list[str] = []
        if _ltm_sample_file is not None:
            try:
                _ltm_sample_headers = list(read_leadfile(_ltm_sample_file).columns)
            except Exception as exc:
                render_error(exc)

        _ltm_sample_headers_norm = {normalize_header_text(h): h for h in _ltm_sample_headers}
        _existing_ltm_rules = {r.template_column: r for r in (profile.lead_template_mapping.rules if profile else [])}
        _DATE_FORMAT_OPTIONS = [
            "(no special formatting)", "MM/DD/YYYY", "DD/MM/YYYY", "DD-MMM-YY",
            "YYYY-MM-DD", "YYYY-MM-DD HH:MM:SS", "Custom...",
        ]

        lead_template_mapping_rules: list[LeadTemplateColumnRule] = []
        if not _ltm_template_headers:
            st.caption("Set a Lead Template path and sheet above to configure column mapping.")
        for _ltm_col in _ltm_template_headers:
            _existing_rule = _existing_ltm_rules.get(_ltm_col)
            with st.container(border=True):
                if _ltm_sample_headers:
                    _auto_match = find_passthrough_lead_column(
                        normalize_header_text(_ltm_col), _ltm_sample_headers_norm)
                    st.write(
                        f"**{_ltm_col}** — auto-matches: *{_auto_match}*" if _auto_match
                        else f"**{_ltm_col}** — ⚠️ no auto-match found")
                else:
                    st.write(f"**{_ltm_col}**")

                _col_a, _col_b = st.columns(2)
                _ltm_mandatory = _col_a.checkbox(
                    "Mandatory", value=_existing_rule.mandatory if _existing_rule else False,
                    key=f"ltm_mandatory_{_ltm_col}")

                if _ltm_sample_headers:
                    _override_options = ["(auto)"] + _ltm_sample_headers
                    _default_override = _existing_rule.source_column if _existing_rule and _existing_rule.source_column else "(auto)"
                    _override_idx = _override_options.index(_default_override) if _default_override in _override_options else 0
                    _ltm_source_selected = _col_b.selectbox(
                        "Source column", _override_options, index=_override_idx, key=f"ltm_source_{_ltm_col}")
                    _ltm_source = "" if _ltm_source_selected == "(auto)" else _ltm_source_selected
                else:
                    _ltm_source = _col_b.text_input(
                        "Source column override (blank = auto)",
                        value=_existing_rule.source_column if _existing_rule else "",
                        key=f"ltm_source_text_{_ltm_col}")

                _default_fmt = _existing_rule.date_format if _existing_rule else ""
                _fmt_idx = _DATE_FORMAT_OPTIONS.index(_default_fmt) if _default_fmt in _DATE_FORMAT_OPTIONS else 0
                _ltm_fmt_selected = st.selectbox(
                    "Date format", _DATE_FORMAT_OPTIONS, index=_fmt_idx, key=f"ltm_fmt_{_ltm_col}")
                if _ltm_fmt_selected == "Custom...":
                    _ltm_date_format = st.text_input(
                        "Custom date format (Python strftime, e.g. %d %b %Y)",
                        value=_default_fmt if _default_fmt not in _DATE_FORMAT_OPTIONS else "",
                        key=f"ltm_fmt_custom_{_ltm_col}")
                elif _ltm_fmt_selected == "(no special formatting)":
                    _ltm_date_format = ""
                else:
                    _ltm_date_format = _ltm_fmt_selected

            if _ltm_mandatory or _ltm_source or _ltm_date_format:
                lead_template_mapping_rules.append(LeadTemplateColumnRule(
                    template_column=_ltm_col, source_column=_ltm_source,
                    mandatory=_ltm_mandatory, date_format=_ltm_date_format,
                ))
```

Then, in the `ClientProfile(...)` constructor call near the bottom of the
file (search for `lead_template_tabs=` to find the exact block), add a
sibling argument:

```python
            lead_template_mapping=LeadTemplateMappingConfig(rules=lead_template_mapping_rules),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_client_setup_page.py -k lead_template_mapping -v`
Expected: PASS

- [ ] **Step 5: Run the full Client Setup test suite**

Run: `python -m pytest tests/test_client_setup_page.py -q`
Expected: PASS, all tests (including pre-existing ones — confirms the new
section doesn't break the existing Lead Template save flow it's inserted
after)

- [ ] **Step 6: Commit**

```bash
git add pages/1_Client_Setup.py tests/test_client_setup_page.py
git commit -m "Add Lead Template Column Mapping section to Client Setup"
```

---

### Task 6: Wire `lead_template_mapping` into the actual Lead Template write call sites

**Files:**
- Modify: `pages/2_Run_Check.py`
- Modify: `pages/5_Box_Tracker.py`
- Test: `tests/test_run_check_page.py`, `tests/test_box_tracker_page.py`

**Interfaces:**
- Consumes: `append_leads`'s new `lead_template_mapping` parameter
  (Task 3); `ClientProfile.lead_template_mapping` (Task 1).

- [ ] **Step 1: Write the failing tests**

In `tests/test_run_check_page.py`, find an existing Lead Template write
test (search for `lead_template_path` or `Lead Template at`) to copy its
exact fixture/AppTest flow, then add a test confirming a configured
mandatory rule with no resolvable source produces a Needs Review outcome
instead of a normal valid write (exercises Task 4's check end-to-end
through the real page) — write this using whatever this file's own
existing "confirm a lead goes to Needs Review" test already does as your
template (search for `"Needs Review"` in the file).

In `tests/test_box_tracker_page.py`, similarly find the existing "Wrote N
lead(s) to their Lead Template(s)" test and add an assertion (or a
focused new test) confirming a configured date-format rule actually
reformats a date cell in the written Lead Template file — mock nothing
here; write to a real temp workbook and re-open it to check the cell,
matching this file's existing style for verifying real written output.

(Because these two tests depend heavily on each file's own existing
fixture conventions, which you must read firsthand rather than guess,
write the exact test bodies after reading the surrounding existing tests
in each file — the requirement is: one test per file, exercising the real
page path, that proves `lead_template_mapping` is actually reaching
`append_leads`/the pipeline check when writing to a Lead Template.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_run_check_page.py tests/test_box_tracker_page.py -k lead_template_mapping -v`
Expected: FAIL (the new behavior isn't wired up yet)

- [ ] **Step 3: Wire `pages/2_Run_Check.py`**

In `_finalize_write`, both `append_leads` calls inside the `if
lead_template_configured and not valid_leads_df.empty:` block (the
multi-tab loop's call and the single-tab `else` branch's call — search
for `clear_existing=profile.lead_template_clear_existing` to find both)
get a new argument added:

```python
                        lead_template_mapping=profile.lead_template_mapping,
```

Do NOT add this to the Accumulated Report or Refund `append_leads` calls
earlier in the same function — this feature is scoped to Lead Template
writes only, per the design spec.

Also, the mandatory-column check itself (Task 4) is wired into
`run_pipeline`, which `pages/2_Run_Check.py` already calls elsewhere to
produce `valid_leads_df`/review reasons — confirm (read the surrounding
code around wherever `run_pipeline(...)` is called in this file) that
nothing else needs to change here for the check to take effect; if
`run_pipeline` is already called with the full `profile` object, Task 4's
pipeline wiring is sufficient on its own and this task only needs the
`append_leads` argument additions above.

- [ ] **Step 4: Wire `pages/5_Box_Tracker.py`**

The Lead Template `append_leads` call (search for
`clear_existing=True,` near `template_path, sheet_name, enriched_group,
_acc_fm,`) gets the same new argument:

```python
                        lead_template_mapping=profile.lead_template_mapping,
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_run_check_page.py tests/test_box_tracker_page.py -k lead_template_mapping -v`
Expected: PASS

- [ ] **Step 6: Run the full suites for both pages**

Run: `python -m pytest tests/test_run_check_page.py tests/test_box_tracker_page.py -q`
Expected: PASS, all tests unchanged (every existing test's `ClientProfile`
fixture has an empty `lead_template_mapping` by default, so passing it
through has no effect on any pre-existing test)

- [ ] **Step 7: Commit**

```bash
git add pages/2_Run_Check.py pages/5_Box_Tracker.py tests/test_run_check_page.py tests/test_box_tracker_page.py
git commit -m "Wire lead_template_mapping into Run Check and Box Tracker Lead Template writes"
```

---

### Task 7: Full-suite verification and manual smoke test

**Files:** none new — verification only.

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`
Expected: every test passes except the 2 pre-existing, unrelated
`tests/test_end_to_end_basware.py` filename-encoding errors (confirmed
present on unmodified `master` too, unrelated to this feature).

- [ ] **Step 2: Manually verify in the browser**

Start the dev server (`preview_start` with the `streamlit-app-dev`
config), log in, and on a throwaway test client:
- Set a Lead Template path/sheet, open the new "Lead Template Column
  Mapping (optional)" section, upload a small sample leadfile, confirm
  the auto-match preview renders per column with no exceptions, mark one
  column mandatory, set a date format on another, save.
- Re-open Client Setup for that same client and confirm the saved
  mandatory checkbox/override/date-format selections reload correctly
  (not reset to defaults).
- On Run Check, upload a leadfile missing the mandatory column's data for
  one lead, run the check, confirm that lead is flagged Needs Review
  (not silently written) while a lead WITH that data present flows
  through normally.
- Check `read_console_messages(onlyErrors: true)` for any new/unexpected
  errors (ignore pre-existing benign static-asset 404s).

- [ ] **Step 3: Report results**

No commit needed for this task unless step 2 surfaces a bug requiring a
fix — if it does, fix it, add a regression test in the appropriate task's
test file, and commit that fix separately with a clear message describing
what the manual check caught.

## Self-Review Notes

- **Spec coverage:** data model (Task 1), manual override (Task 2), date
  format (Task 3), mandatory-column review check (Task 4), Client Setup
  UI (Task 5), write-path wiring (Task 6), full verification (Task 7).
  Every "In scope" item from the spec has a task producing it.
- **Non-breaking guarantee:** explicitly tested at Task 2 Step 5, Task 3
  Step 6, Task 4 Step 6-7, Task 5 Step 5, and Task 6 Step 6 — every task
  that touches shared/existing code re-runs that code's full pre-existing
  test suite to confirm zero regression, not just its own new tests.
- **Type consistency check:** `LeadTemplateColumnRule`'s four fields
  (`template_column`, `source_column`, `mandatory`, `date_format`) are
  used identically across Task 1's dataclass, Task 2/3's
  `manual_overrides`/`date_formats` dict-building code, Task 4's check,
  and Task 5's UI save code. `append_leads`'s new
  `lead_template_mapping` parameter name and type
  (`LeadTemplateMappingConfig | None = None`) match between Task 3's
  definition and Task 6's call-site additions.

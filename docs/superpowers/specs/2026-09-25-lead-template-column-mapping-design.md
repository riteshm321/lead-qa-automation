# Lead Template Column Mapping & Date Format Design

## Goal

At Client Setup time, let the user see (and fix) which Lead Template
columns the app's auto-matcher can/can't resolve from a leadfile, mark
specific columns as mandatory (a blank value gets flagged for review
instead of silently written blank), manually override the source leadfile
column for any Lead Template column, and configure a specific output date
format for any column that needs one — all **without changing any
existing client's current behavior** unless the user explicitly opens
Client Setup and configures something for that client.

Modeled on a standalone tool the user already relies on for AWS/Everpure/
Adobe (`SID Collation/update_sid.py`): a manual `{target column: {source,
is_date}}` override table that wins over auto-matching, plus a warning
when a column has no match at all.

## Current state (do not break)

`core/excel_io.py`'s `_resolve_passthrough_columns` already runs at every
`append_leads` call (both the xlsx and CSV branches) and resolves each
Lead Template header to a leadfile column via, in order: (1) the target
field-mapping role (email/first/last/company/CID), (2) a known field
synonym, (3) `find_passthrough_lead_column`'s fuzzy match
(`rapidfuzz.fuzz.ratio`, threshold 88). Unresolved headers are collected
into `unmatched_passthrough_headers` and already surface as a warning on
Run Check / Box Tracker **after** a lead is written — this design adds a
**Client-Setup-time** preview of the same resolution (so mapping gaps are
visible before a real run) plus a manual override and mandatory-column
flag, layered on top of, not replacing, this existing chain.

## Scope

- **In scope:** Client Setup UI to preview auto-match results, mark
  mandatory columns, manually override a column's source, and set a
  date format — for any client with a Lead Template configured. Write-time
  integration in `append_leads` (manual override wins over auto-match;
  configured date format applied as a real Excel date + number format,
  not text). A new pipeline check that flags a lead with a blank value in
  a mandatory column for review, using the existing `ReviewDetail`/
  `CheckOutcome` mechanism every other check already uses.
- **In scope:** date format as a dropdown of the formats already used
  elsewhere in this app (MM/DD/YYYY, DD/MM/YYYY, DD-MMM-YY, YYYY-MM-DD,
  YYYY-MM-DD HH:MM:SS) plus a free-text custom-format escape hatch.
- **Explicit non-negotiable constraint:** with zero rules configured for
  a client (every existing client, today, until someone opens this new
  section), `append_leads` and the pipeline behave byte-for-byte
  identically to current behavior. This is achieved by every new
  parameter being optional/defaulted and every new code path being gated
  on `LeadTemplateMappingConfig.rules` being non-empty.
- **Out of scope:** auto-detecting which columns are "usually mandatory"
  (the user marks them manually, per client) or building a generic
  column-type inference system beyond the explicit date-format opt-in.

## Data model

```python
@dataclass
class LeadTemplateColumnRule:
    template_column: str          # exact Lead Template header text
    # Blank means "use the existing auto-match chain unchanged". Set only
    # to override it with a specific leadfile column name.
    source_column: str = ""
    # A blank/unmapped value for this column on a given lead gets flagged
    # for review (see core/checks/lead_template_mapping.py) instead of
    # silently written blank -- only for columns the user actually marks.
    mandatory: bool = False
    # Blank means "no special formatting -- pass the leadfile's raw value
    # through unchanged", exactly like every column does today. A preset
    # name ("MM/DD/YYYY", "DD/MM/YYYY", "DD-MMM-YY", "YYYY-MM-DD",
    # "YYYY-MM-DD HH:MM:SS") or a custom strftime-style string.
    date_format: str = ""


@dataclass
class LeadTemplateMappingConfig:
    rules: list[LeadTemplateColumnRule] = field(default_factory=list)
```

Added to `ClientProfile`:
`lead_template_mapping: LeadTemplateMappingConfig = field(default_factory=LeadTemplateMappingConfig)`.

Only columns the user actually touched (mandatory, or a source override,
or a date format) are saved as a rule — a column left at every default is
not written to the profile JSON at all, keeping the saved config small
and matching the existing "blank/default = don't save a row" convention
used elsewhere in Client Setup (e.g. `_render_paired_field_mapping`).

## Client Setup UI (new "Lead Template Column Mapping (optional)" section)

Placed directly after the existing Lead Template path/sheet/tabs
configuration, so it only renders once a Lead Template path+sheet is set.

1. Reads the Lead Template's real headers via the already-existing
   `_safe_read_template_headers(lead_template_path, lead_template_sheet_name)`
   — no new header-reading logic.
2. A new, optional `st.file_uploader("Sample leadfile (optional — lets
   this preview show real auto-match results and pick a source column
   from a dropdown instead of typing it)")`. This is the first
   file-uploader in Client Setup — justified because there is no other
   way to know the leadfile's real column names at setup time (unlike
   the Lead Template, which already has a persisted path this app can
   read). Without a sample uploaded, the source-override field falls back
   to free text (same pattern as `_render_leadfile_column_mapping`).
3. For each Lead Template header that isn't one of the columns
   `append_leads` already special-cases unconditionally ("Date",
   "Comment", "Status", "Refund Reason", any formula column — these never
   come from a leadfile passthrough at all, mapping them would be
   meaningless), render one row:
   - **Auto-match preview**: if a sample leadfile was uploaded, calls the
     same resolution chain (`find_passthrough_lead_column`, etc.) against
     its real headers and shows "auto-matches: *{column}*" or
     "⚠️ no match found" — this is a preview of the exact same result
     `append_leads` would compute today, not a new/different algorithm.
   - **Mandatory** checkbox.
   - **Source override**: a selectbox (sample leadfile headers, default
     "(auto)") or free-text input if no sample was uploaded.
   - **Date format**: a selectbox — "(no special formatting)", the 5
     presets above, or "Custom..." (reveals a text input for a strftime
     string) — defaulting to "(no special formatting)".
4. Save builds `LeadTemplateMappingConfig.rules`, one entry per column
   where mandatory is checked, or a source override is set, or a date
   format is set — skipping every column left fully at its defaults.

## Write-time integration (`core/excel_io.py`)

`append_leads` gains an optional parameter,
`lead_template_mapping: LeadTemplateMappingConfig | None = None`
(defaulting to `None` — every existing call site is unaffected until a
caller explicitly passes the client's config). Internally split into:

- `manual_overrides: dict[str, str]` — `{normalize_header_text(rule.template_column): rule.source_column}`
  for every rule with a non-blank `source_column`.
- `date_formats: dict[str, str]` — `{normalize_header_text(rule.template_column): resolved_strftime_format}`
  for every rule with a non-blank `date_format` (preset names resolved to
  their strftime string once, e.g. "MM/DD/YYYY" → `"%m/%d/%Y"`).

`_resolve_passthrough_columns` gains a `manual_overrides: dict[str, str] |
None = None` parameter: when a header's normalized text is a key in
`manual_overrides` **and** that value is a real column in `leads_df`, it
is used directly, bypassing the target-role/synonym/fuzzy chain entirely
for that header (matching SID Collation's manual-mapping precedence). A
manual override naming a column that doesn't actually exist in the
uploaded leadfile falls back to the normal auto-match chain rather than
silently resolving to nothing — the existing `unmatched_passthrough_headers`
reporting already covers that case correctly.

Both the xlsx and CSV per-row writing loops gain the same conditional: if
the header's normalized text is a key in `date_formats`, the raw value is
parsed as a date (reusing `pd.to_datetime`, with the same Excel-serial
fallback already proven necessary elsewhere in this codebase — see
`core/box_tracker.py`'s Excel-origin date handling) and, for xlsx, written
as a real `datetime` value with `cell.number_format` set to the
backslash-escaped equivalent (same `_DATE_NUMBER_FORMAT`-style escaping
already required — confirmed necessary for Dell EMEA's Capture Date to
render correctly regardless of the reading machine's regional date
separator). For CSV, the value is written as the formatted date string
directly (CSV has no separate cell-format layer, matching how the
existing "Date"/other date columns already handle CSV output). An
unparseable value for a configured date column is left as the original
raw text rather than silently blanked, so a malformed source value stays
visible instead of vanishing.

## Mandatory-column review check (`core/checks/lead_template_mapping.py`)

New check, following the exact `CheckOutcome`/`ReviewDetail` pattern every
other check in `core/checks/` already uses:

```python
def check_lead_template_mandatory_columns(
    new_leads: pd.DataFrame, field_mapping: FieldMapping,
    config: LeadTemplateMappingConfig, leadfile_headers: list[str],
) -> CheckOutcome
```

For each rule with `mandatory=True`: resolves which leadfile column
supplies it (manual override if set and present in `leadfile_headers`,
else the same auto-match chain `_resolve_passthrough_columns` uses,
reusing `find_passthrough_lead_column` directly rather than duplicating
its matching logic). If no column resolves at all, every lead is flagged
once (`ReviewDetail(check="Lead Template Mapping", message=f"No leadfile
column found for mandatory field '{rule.template_column}'")`). If a
column resolves, each row whose value in that column is blank/NaN is
flagged (`message=f"'{rule.template_column}' is required but blank"`).

Wired into `core/pipeline.py::run_pipeline`, gated on
`any(r.mandatory for r in profile.lead_template_mapping.rules)` (no
separate `.enabled` flag needed — the presence of a mandatory rule is
itself the opt-in, and a client with zero mandatory rules configured sees
zero change to pipeline behavior).

## Testing

- `core/excel_io.py`: `_resolve_passthrough_columns` — manual override
  wins over auto-match; a manual override naming a non-existent leadfile
  column falls back to auto-match; unchanged behavior with no overrides
  passed (regression-protects the existing behavior this must not break).
  `append_leads` (xlsx and CSV) — a configured date format produces a
  real Excel date with the correct number format / the correctly
  formatted CSV string; an unparseable value for a date-formatted column
  is left as its original raw text, not blanked.
- `core/checks/lead_template_mapping.py`: a mandatory column with no
  resolvable leadfile column flags every lead once; a resolvable
  mandatory column flags only the rows with a blank value; a non-mandatory
  rule never produces any review flag; `run_pipeline` with zero mandatory
  rules configured produces byte-identical `PipelineResult` to before this
  feature existed.
- `pages/1_Client_Setup.py`: saving mandatory/source-override/date-format
  selections persists a correctly-shaped `LeadTemplateMappingConfig`; a
  column left at every default is not saved as a rule at all.

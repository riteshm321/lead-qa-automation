# Google Sheets Lead Delivery Design

## Goal

Let a client's valid leads be written straight to a Google Sheet — routed
per CID, same as today's multi-tab Excel Lead Template — as a peer
destination type alongside the existing Excel Lead Template/Accumulated
Report writers, reusable by any teammate for any future client, not a
one-off for this specific client.

First real use case: a brand-new client with **no Excel Lead Template at
all** — its two CIDs each write to their own Google Sheet
(`First Name, Last Name, Company Name, Work Email, Job Title, Country`),
both already shared with a service account this session created
(`lead-template-writer@lead-qa-automation.iam.gserviceaccount.com`,
project `lead-qa-automation`, Sheets + Drive APIs enabled — see the
`google_sheets_service_account` memory file for exact values).

## Why this reuses Task 5's Lead Template Column Mapping model

A Google Sheet's header row and an Excel Lead Template's header row pose
the identical problem this app already solved: some leadfile columns
auto-match a target header, some need a manual override, some target
columns are mandatory (missing value → flag for review), some need a
specific date format. `core/models.py`'s `LeadTemplateColumnRule`/
`LeadTemplateMappingConfig` are already header-agnostic (`template_column:
str`, nothing Excel-specific in the dataclass) — this feature gives a
client a SECOND, independent instance of that same config
(`ClientProfile.google_sheets.mapping`) for its Sheet's headers, and
reuses `core/checks/lead_template_mapping.py`'s existing
`check_lead_template_mandatory_columns` unchanged (it already only takes
a `LeadTemplateMappingConfig`, never touches a file path).

## Scope

- **In scope:** one shared, per-machine Google service-account credential
  (a local JSON key file path, Settings page) reusable across every
  client's Sheets — a Sheet only needs to be individually shared with that
  service account's email as Editor, same as any two people sharing a
  Sheet. Per-CID Sheet routing in Client Setup (paste a Sheet URL, parse
  the Sheet ID out of it). The same mandatory/override/date-format mapping
  UI Task 5 built, pointed at a Sheet's real header row (read live via the
  Sheets API) instead of an Excel file's. Wiring into Run Check's Finalize
  step, appending valid leads via the Sheets API's native append (no
  manual "find the next empty row" bookkeeping needed, unlike Excel).
- **In scope:** extracting the `manual_overrides`/`date_formats`
  resolution logic already duplicated between `append_leads`' xlsx and CSV
  branches (a known minor finding from this session's audit of that code)
  into one shared helper, reused by both those branches AND the new
  Sheets writer — three consumers is exactly the point past which this
  duplication stops being "three similar lines" and starts being real
  drift risk.
- **In scope:** a NEW pipeline check-stage label for
  `_stage_labels`/`_completed_checks` in `pages/2_Run_Check.py`, added in
  the SAME task that wires the Sheets mandatory-check into the pipeline —
  explicit checklist item, since the equivalent Lead Template Mapping
  wiring shipped without this and caused a real crash discovered later in
  the same session. Not repeating that mistake.
- **Explicit non-negotiable constraint:** every existing client (Excel
  Lead Template, Accumulated Report, or no Lead Template at all) sees zero
  behavior change. `ClientProfile.google_sheets` defaults to
  `GoogleSheetsConfig()` (disabled, no tabs) for every profile that
  doesn't explicitly configure it.
- **Out of scope:** writing to Accumulated Report via Google Sheets (only
  the Lead-Template-equivalent "valid leads" write path is in scope for
  this pass — Accumulated Report stays Excel-only for now, per the user's
  own framing: "for now there is no lead template it is directly on
  google sheet," i.e. the Sheet stands in for the Lead Template, not the
  Accumulated Report). Reading FROM a Google Sheet (e.g. as a leadfile
  source) — out of scope, this is a write-only destination feature.
  Real-time collaborative editing conflict handling — out of scope; the
  Sheets API's native append already avoids the "two teammates overwrite
  each other's row" class of bug Excel's shared-file writes are
  susceptible to, so this is a net reliability improvement, not a new gap
  to design around.

## Data model

```python
@dataclass
class GoogleSheetTab:
    cid: str
    sheet_id: str          # parsed from a pasted Sheet URL
    worksheet_name: str = "Sheet1"


@dataclass
class GoogleSheetsConfig:
    enabled: bool = False
    tabs: list[GoogleSheetTab] = field(default_factory=list)
    # Same dataclass Task 5 built for Excel Lead Templates -- a
    # SEPARATE instance from ClientProfile.lead_template_mapping, since a
    # client's Sheet(s) can have entirely different headers/rules than
    # its Excel template (if it even has one).
    mapping: LeadTemplateMappingConfig = field(default_factory=LeadTemplateMappingConfig)
```

Added to `ClientProfile`:
`google_sheets: GoogleSheetsConfig = field(default_factory=GoogleSheetsConfig)`.

## Credential storage (`core/app_settings.py`)

`get_google_sheets_key_path() -> str` / `save_google_sheets_key_path(path: str) -> None`
— the local filesystem path to the service-account JSON key file, stored
in the plain local `app_settings.json` only (same reasoning as every
other live credential in this app: a secret belongs on the machine using
it, never in the shared clients folder every teammate can read). The key
file itself is NOT copied anywhere by this app — it stays wherever the
user places it (e.g. `C:\Users\<name>\Downloads\<key>.json`, or a
team-agreed shared-but-access-controlled location outside this app's own
folders); the app only stores the path to it.

## `core/google_sheets_client.py`

- `GoogleSheetsError(Exception)`.
- `_client(key_path: str)` — internal, builds an authenticated `gspread`
  client from the service-account key file (`gspread.service_account(filename=key_path)`),
  raising `GoogleSheetsError` with a clear message on a missing/invalid
  key file (distinct from an API/permission error, so a teammate who
  hasn't set up their local credential yet gets a message telling them
  that, not a raw stack trace).
- `read_sheet_headers(key_path: str, sheet_id: str, worksheet_name: str) -> list[str]`
  — reads row 1 live, for both the Client Setup mapping-preview UI and
  the actual write-time column resolution (so a Sheet's headers changing
  between setup and a later run is picked up automatically, unlike an
  Excel Lead Template's headers which are effectively static per-client
  path/sheet config).
- `append_rows(key_path: str, sheet_id: str, worksheet_name: str, rows: list[dict[str, str]]) -> int`
  — each dict is `{header: value}` for one lead, already resolved via the
  shared `manual_overrides`/`date_formats` helper (see below) exactly as
  `append_leads` resolves them for Excel. Uses the Sheets API's native
  `values.append` (via `gspread`'s `worksheet.append_rows(..., value_input_option="USER_ENTERED")`
  — `USER_ENTERED` so a date string like `"03/15/2026"` is recognized as
  a real Sheets date value, not left as plain text, matching the
  "must be a genuine date, not text" requirement Task 5's date-format
  work already established for Excel). Returns the count of rows
  appended. Raises `GoogleSheetsError` on any API failure — this app
  never silently drops a lead it believes it sent.

## Shared column-resolution extraction (`core/excel_io.py`)

New function, extracted from the two near-identical blocks already in
`append_leads`/`_append_leads_csv`:

```python
def resolve_lead_template_rules(
    lead_template_mapping: "LeadTemplateMappingConfig | None",
) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """Returns (manual_overrides, date_formats) exactly as append_leads'
    two branches already compute them -- factored out so the Google
    Sheets writer (core/google_sheets_client.py) can resolve the SAME
    rules against a Sheet's headers without a third copy of this logic.
    """
```

Both `append_leads` branches call this instead of inlining the dict
comprehensions; behavior is unchanged (this is a pure extraction, not a
logic change — the existing Task 3 tests already cover the computed
values, so this refactor is protected by existing coverage, not just new
tests).

## Client Setup UI (new "Google Sheets Lead Delivery (optional)" section)

Placed as its own top-level section (not nested inside the existing "if
client_mode == Lead QA" Lead Template block, since a client can use this
with NO Excel Lead Template configured at all — this client is exactly
that case).

1. Enable checkbox.
2. CID → Sheet URL mapping, one per line (`CID,Sheet URL[,worksheet name]`
   — worksheet name optional, defaults to `Sheet1`), parsed into
   `GoogleSheetTab` entries — Sheet ID extracted from the pasted URL via
   regex (`/spreadsheets/d/([a-zA-Z0-9_-]+)/`), so the user pastes exactly
   what's in their browser's address bar, never a raw ID they'd have to
   extract by hand.
3. For each configured tab, a "Preview headers" action reads that Sheet's
   real header row live (via `read_sheet_headers`, requires the
   credential to already be set in Settings — a clear error if not) and
   renders the SAME per-column mandatory/override/date-format UI Task 5
   built, saving into `google_sheets.mapping` (one shared mapping across
   all this client's Sheets tabs, matching how `lead_template_mapping` is
   one shared mapping across all `lead_template_tabs` today — if two
   Sheets for the same client genuinely need different mandatory rules in
   the future, that's a real design question to revisit then, not
   speculatively solved now).

## Write-time integration (`pages/2_Run_Check.py`'s `_finalize_write`)

After the existing Lead Template write block, a new block: if
`profile.google_sheets.enabled` and there are valid leads, route them by
CID to their `GoogleSheetTab` (same `groupby` shape as the existing
Excel multi-tab routing — reuse the grouping logic, not
`route_leads_by_cid` itself, since that function is Excel-file-specific
via `default_file_path`), resolve each row's attributes via
`resolve_lead_template_rules(profile.google_sheets.mapping)` +
`_resolve_passthrough_columns`, and call
`google_sheets_client.append_rows(...)` per Sheet tab. A CID with no
matching Sheet tab is reported the same way an unmatched Lead Template
CID is today (warning, still added to Accumulated Report). A single
Sheet's API failure does not abort leads destined for a DIFFERENT Sheet
tab (same per-target isolation principle as every other multi-target
write in this app).

## Pipeline check wiring (`core/pipeline.py`, `pages/2_Run_Check.py`)

`run_pipeline` gains a second call to
`check_lead_template_mandatory_columns`, gated on
`any(r.mandatory for r in profile.google_sheets.mapping.rules)`, using a
distinct `report(...)` label ("Checking Google Sheets Mandatory Columns")
and a distinct `ReviewDetail.check` value ("Google Sheets Mapping", vs.
the existing "Lead Template Mapping") so a lead failing one is
distinguishable from a lead failing the other if a client somehow has
both configured. **`_stage_labels` and `_completed_checks` in
`pages/2_Run_Check.py` both get a matching new entry in this SAME task**
— this is the exact class of bug that shipped once already in this
session's Lead Template Mapping work and was only caught by a later
review; not repeating it.

## Testing

- `core/excel_io.py`: `resolve_lead_template_rules` extraction —
  existing `append_leads` date-format/override tests already cover its
  behavior; add one direct unit test confirming the function's return
  shape in isolation.
- `core/google_sheets_client.py`: `read_sheet_headers`/`append_rows` —
  mocked `gspread` client (no real network calls in tests), covering a
  missing-key-file error, an API-failure error, and a successful append
  with `USER_ENTERED` value-input-option asserted.
- `core/checks/lead_template_mapping.py`: no new test needed — already
  generic over any `LeadTemplateMappingConfig`, already proven to work
  against a non-Excel-specific config in Task 4's own tests.
- `pages/1_Client_Setup.py`: saving CID→Sheet mappings, the mandatory/
  override/date-format UI reusing Task 5's pattern, Sheet-ID parsing from
  a pasted full URL.
- `pages/2_Run_Check.py`: a mandatory Google Sheets rule with no
  resolvable source flags every lead (mirroring Task 4's Lead Template
  test); the new `_stage_labels`/`_completed_checks` entries present and
  correctly gated; a real Run Check click with a mandatory Sheets rule
  configured does not crash (the exact regression class from the bug
  this whole design explicitly guards against repeating).

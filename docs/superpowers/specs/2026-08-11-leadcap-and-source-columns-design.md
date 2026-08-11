# Leadcap Company Pass, Per-Source Columns & Run-Check-Only Leads File — Design Spec

Date: 2026-08-11
Status: Approved by user, pending implementation plan

## Purpose

Three related improvements to the existing Lead QA Automation tool:

1. Leadcap should also check by company name (in addition to the existing domain-based check), with clearer CID-based cap setup.
2. Exclusion, TAL, Suppression, and Dedupe should all support multiple files/sheets (Suppression and Dedupe currently don't — only Exclusion/TAL do, from the prior multi-file work), each with its own Domain/Company/Email column selection (not a single shared setting per check), plus a native "Browse..." file picker.
3. The New Leads file should be selected exactly once, on the Run Check page — not also on Client Setup — with column mapping handled inline the first time and remembered afterward.

## 1. Leadcap: Company-Name Pass & CID Auto-Detection

### Config changes (`core/models.py`)

`LeadcapConfig` gains:
- `check_company_name: bool = False`
- `purchased_report_company_column: str = "Company"`

Cap modes are unchanged: **flat** (`flat_cap`, one cap number applied to every CID individually) and **segmented** (`segments: list[LeadcapSegment]`, each segment pools multiple CIDs against one cap).

### Check logic (`core/checks/leadcap.py`)

For each lead, within its resolved cap/segment scope:
1. **Domain pass** (existing, unchanged): count Purchased Lead Report rows matching the lead's CID(s) and domain (via email). If count ≥ cap → fail, reason `"Leadcap exceeded"`.
2. **Company pass** (new): only evaluated for leads that passed the domain pass, and only when `check_company_name` is on. Count Purchased Lead Report rows matching the lead's CID(s) and an exact, case-insensitive, whitespace-trimmed match against `purchased_report_company_column`. If count ≥ cap → fail, reason `"Leadcap Exceed - By Company Name"`.

A lead gets at most one leadcap-related reason. If a CID has zero leads in the current run's New Leads file, its cap is never evaluated — this already falls out of iterating only over leads actually present, no new logic needed.

### Client Setup: CID auto-detection

When Leadcap is segmented and the Accumulated Report path is filled in, a **"Detect CIDs from Accumulated Report"** button reads the CID column (and campaign-name column, used as default segment names) from the Accumulated Report's `Pacing Overview` sheet, and pre-fills the segments text area with one row per detected CID (`<campaign name>|<cid>|` — cap left blank for the user to fill in). The user can still freely edit the CIDs field on any row to pool multiple CIDs into one shared-cap group, exactly as today's manual entry already allows — this button only removes the need to type CID numbers from scratch. If the Accumulated Report can't be read or has no `Pacing Overview` sheet, the button shows a clear error and the manual text area remains fully usable as before.

## 2. Multi-Source + Per-Source Columns (Exclusion, TAL, Suppression, Dedupe)

### `ReferenceSource` changes (`core/models.py`)

```python
@dataclass
class ReferenceSource:
    name: str
    file_path: str
    sheet_name: str
    cids: list[str] = field(default_factory=list)
    domain_column: str = "Domain"
    company_column: str = "Account Name"
    email_column: str = "Email"
```

Every source now carries its own column names. `ExclusionConfig`, `TalConfig`, and `SuppressionConfig` drop their check-level `domain_column`/`company_column` fields (Suppression also drops `email_column`, `sheet_name`); `DedupeListConfig` drops `sheet_name`/`email_column`. All four configs converge on the same shape: `enabled` (+ check-specific toggles) + `sources: list[ReferenceSource]`.

- `ExclusionConfig(enabled, check_company_name, sources)`
- `TalConfig(enabled, check_company_name, sources)`
- `SuppressionConfig(enabled, check_domain, check_company_name, check_email, sources)`
- `DedupeListConfig(enabled, sources)`

### Check logic

`core/checks/exclusion.py` and `core/checks/tal.py`: read `source.domain_column`/`source.company_column` per source instead of a config-level setting when building the union of applicable sources' data — the CID-scoping and union-matching logic from the existing multi-file work is otherwise unchanged.

`core/checks/suppression.py` and `core/checks/dedupe_list.py`: rewritten to the same multi-source, CID-scoped, union-matching pattern as Exclusion/TAL (they currently take a single DataFrame). Suppression's per-source columns used depend on which of `check_domain`/`check_company_name`/`check_email` are on; Dedupe only ever uses `email_column`.

### Client Setup UI

Suppression and Dedupe each get the same dynamic "Add Source" list UI already built for Exclusion/TAL (stable `uuid` row ids, Add/Remove, live sheet dropdown, CIDs field). Every source row, for every one of the four checks, additionally shows column-picker dropdowns (populated from that source's actual sheet headers, same mechanism as the existing field-mapping step) for whichever of Domain/Company/Email are relevant to that check's enabled toggles.

### Native file Browse button

Every file-path text input (New Leads sample removed per Section 3; all Exclusion/TAL/Suppression/Dedupe source file-path fields; Accumulated Report path) gets an adjacent **"Browse..."** button. Clicking it calls Python's `tkinter.filedialog.askopenfilename()`, which opens the native Windows file-picker dialog on the machine actually running the Streamlit process, and writes the chosen path into the corresponding text field. This requires no new dependency (`tkinter` ships with standard Python on Windows) and needs a hidden root `Tk()` window created and immediately withdrawn before invoking the dialog, to avoid a stray blank window appearing.

Known constraint: the dialog reflects the filesystem of whichever machine is running the Streamlit server — when a colleague reaches the app over the network (per the existing sharing setup), clicking Browse opens a dialog on the host PC, not the colleague's own machine. Acceptable for how this tool is used today (the host user is the one configuring client profiles).

## 3. New Leads File — Run Check Only

Client Setup's "Field Mapping (from a sample New Leads file)" section and its `sample_leads_path` input are removed entirely — `ClientProfile.field_mapping` is set/updated only from the Run Check page now.

**Run Check flow**, after a New Leads file is uploaded and Run Check is clicked, before running the pipeline:
1. Read the uploaded file's headers.
2. If `profile.field_mapping` is set and every one of its five mapped column names is present in the uploaded file's headers → proceed directly to running the pipeline.
3. Otherwise (no field mapping yet, or a previously-mapped column name is missing from this file — e.g. the client changed their export format) → show the five column-mapping dropdowns (Email/First Name/Last Name/Company/CID), populated from the uploaded file's real headers, defaulting to the profile's existing mapped values where still valid. On confirmation, build the new `FieldMapping`, call `save_profile` to persist it onto the client's profile file, then proceed to run the pipeline.

This makes the New Leads file selection happen exactly once per Run Check click; mapping is handled inline only when needed (first run, or whenever the file's headers no longer match what's on file) rather than as a separate always-shown Client Setup step.

## Backward Compatibility

No real client profiles currently exist in `clients/` (git-ignored). This is a clean schema change — no migration path needed for existing saved profiles, consistent with the prior multi-file work's approach.

## Testing

- `core/checks/leadcap.py`: new tests for the company pass — a lead that passes domain but exceeds by company name; a lead that fails domain and never reaches the company pass; company matching is exact/case-insensitive/trimmed, not fuzzy.
- `core/checks/suppression.py`, `core/checks/dedupe_list.py`: full test rewrites mirroring the existing Exclusion/TAL multi-source test patterns (universal sources unioned, CID-scoped isolation, mixed universal+scoped).
- `core/models.py`/`core/profile_store.py`: round-trip tests updated for `ReferenceSource`'s new per-source column fields and the four configs' converged shape.
- No automated test for the Browse button or CID-auto-detection button (Streamlit UI, verified by running, consistent with how the rest of the UI has been tested throughout this project) or for the Run-Check field-mapping flow (also Streamlit UI).
- End-to-end test (`tests/test_end_to_end_basware.py`) updated for the new `ExclusionConfig`/`ReferenceSource` shape.

## Out of Scope

- Any change to how the Leadcap check's Purchased Lead Report is uploaded (still a fresh per-run upload, not a persistent path) — untouched by this spec.
- Fuzzy/alias-based company matching for Leadcap (explicitly exact-match only, per user decision).
- Making the Browse button reflect a remote colleague's filesystem when the app is accessed over the network — documented as a known constraint, not solved here.

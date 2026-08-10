# Multi-File Exclusion & TAL Sources — Design Spec

Date: 2026-08-09
Status: Approved by user, pending implementation plan

## Purpose

A client's Exclusion List or TAL is sometimes split across more than one Excel file (e.g. one file per geo/segment, or a file from the client plus one from a partner/agency), in addition to the existing case of multiple tabs within one file. Today `ExclusionConfig` and `TalConfig` each assume exactly one file (`ClientProfile.exclusion_path` / `ClientProfile.tal_path`), with TAL additionally supporting multiple *sheets within that one file* via its existing segment mechanism. This spec generalizes both checks to support any number of files and/or sheets, each optionally scoped to specific CIDs, unifying the "one file, multiple sheets" and "multiple independent files" cases into a single mechanism.

Leadcap is explicitly out of scope — it already has its own working CID-segment model (`LeadcapConfig.segments`) tied to per-run Purchased Lead Report uploads, which is a different mechanism (per-run file uploads vs. fixed reference files) and isn't affected by this change.

## Data Model

New shared dataclass in `core/models.py`:

```python
@dataclass
class ReferenceSource:
    name: str
    file_path: str
    sheet_name: str
    cids: list[str] = field(default_factory=list)  # empty = applies to every lead
```

`ExclusionConfig` changes:
- Remove: implicit reliance on `ClientProfile.exclusion_path` + single `sheet_name`
- Add: `sources: list[ReferenceSource] = field(default_factory=list)`
- Keep: `enabled`, `check_company_name`, `domain_column`, `company_column` (shared across all of this client's exclusion sources — assumes consistent column naming across a client's own exclusion files, which is the common case; if a client's sources genuinely use different column names, that's an explicit non-goal for this change and would need a future per-source override)

`TalConfig` changes:
- Remove: `segmented`, `flat_sheet_name`, `segments` (the `TalSegment` dataclass is removed, superseded by `ReferenceSource`)
- Add: `sources: list[ReferenceSource] = field(default_factory=list)`
- Keep: `enabled`, `check_company_name`, `domain_column`, `company_column`

`ClientProfile` changes:
- Remove: `exclusion_path`, `tal_path` (file paths now live per-source, inside each `ReferenceSource`)

A source with an empty `cids` list applies to every lead regardless of CID (covers both "one universal file" and "one of several independent files that all apply"). A source with a non-empty `cids` list applies only to leads whose CID is in that list (covers the geo/segment case). Both kinds can coexist on the same client.

## Check Logic

`core/checks/exclusion.py` and `core/checks/tal.py` both change from taking a single `exclusion_df`/`tal_sheets` argument to taking a `sources_data: dict[str, pd.DataFrame]` keyed by `ReferenceSource.name`, alongside `config.sources` (the CID-scoping metadata).

For each lead:
1. Resolve applicable sources: `[s for s in config.sources if not s.cids or lead_cid in s.cids]`
2. Build the union of domains (and, if `check_company_name`, companies) across `sources_data[s.name]` for every applicable `s`
3. Apply the existing match logic (exact domain match; company match via the existing normalize → alias → fuzzy pipeline) against that unioned set — behavior for a single-source client is identical to today

Exclusion fails a lead if it matches any applicable source. TAL passes a lead if it matches any applicable source (fails with `"TAL - not found"` otherwise, exactly as today). If `config.sources` is empty, the check behaves as if disabled (no sources to check against) — mirrors current behavior when a check is enabled but its reference file is absent.

`core/pipeline.py`'s `reference_data` dict keys change: `"exclusion_df"` → `"exclusion_sources"` (a `dict[str, DataFrame]`), `"tal_sheets"` → `"tal_sources"` (a `dict[str, DataFrame]`, replacing the prior segment-sheet-name-keyed dict with a source-name-keyed one).

## Client Setup UI

Both the Exclusion and TAL sections in `pages/1_Client_Setup.py` replace their current single file-path + single sheet-dropdown with a dynamic "sources" list:

- An **"Add Exclusion Source"** / **"Add TAL Source"** button appends a new blank source row to a `st.session_state`-held list.
- Each source row shows: a **Name** text input, a **File path** text input, a **Sheet** dropdown (populated live via `list_sheet_names` once a valid file path is entered — same live-read behavior as today's single-file picker), a **CIDs** text input (comma-separated; blank means "applies to all leads"), and a **Remove** button.
- When editing an existing client, the session-state list is initialized from `profile.exclusion.sources` / `profile.tal.sources` on first load (not re-initialized on every rerun, so in-progress edits aren't clobbered).
- On Save, the current session-state list (minus any removed rows) is converted into `ReferenceSource` objects and assigned to `ExclusionConfig.sources` / `TalConfig.sources`.

## Run Check Page

`pages/2_Run_Check.py` reads every configured source's file+sheet (for both Exclusion and TAL, when each check is enabled) into a `{source_name: DataFrame}` dict before running the pipeline, using the existing `require_columns` validation (domain column required per source) wrapped in the existing `try/except Exception` block.

## Backward Compatibility

No real client profiles currently exist in `clients/` (git-ignored; the one test profile created during earlier interactive verification was already deleted). This is treated as a clean schema change — no migration path is needed for existing saved profiles.

## Testing

- Unit tests for `ReferenceSource` construction/equality (trivial, covered incidentally by `ClientProfile` round-trip tests)
- `core/checks/exclusion.py` and `core/checks/tal.py` test suites updated to construct `config.sources` instead of the old single-file/segment shape, plus new tests proving: (a) a lead matches when found in any one of several universal (empty-`cids`) sources, (b) a lead is correctly scoped to only its own CID's segment-specific source and not affected by a different segment's source, (c) a mix of one universal + one segment-specific source both apply correctly to an in-scope lead
- `core/profile_store.py` round-trip test updated to include `sources` lists with multiple entries, including CID-scoped ones
- `core/pipeline.py` test updated for the renamed `reference_data` keys (`exclusion_sources`, `tal_sources`)
- End-to-end test (`tests/test_end_to_end_basware.py`) updated to construct the new `ExclusionConfig(sources=[...])` shape (single source, matching current real Basware usage)

## Out of Scope

- Per-source override of `domain_column`/`company_column` (assumes consistent column naming across a client's own sources)
- Any change to Leadcap's existing segment mechanism
- Migration tooling for old-shape profile JSON (none exist to migrate)

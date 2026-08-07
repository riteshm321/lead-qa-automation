# Lead QA & Upload Automation Tool — Design Spec

Date: 2026-08-07
Status: Approved by user, pending implementation plan

## Purpose

Replace the fully manual process of checking new lead batches (for multiple clients/campaigns) against six recurring checks — Duplicate, Leadcap, Exclusion, TAL, Suppression, Dedupe list — with a one-click local tool. Valid leads are appended to a client's persistent Accumulated Report; invalid leads are appended to its Refund tab with a reason. Not every client uses every check, and check behavior (domain-only vs domain+company, flat vs CID-segmented) varies per client.

Scope for v1 explicitly **excludes**: dumping valid leads into the separate Lead QA output template, and mapping/uploading leads into portal-specific upload templates (SID-tied). Those are deferred until the core checking tool is solid.

## Architecture

Python 3 + Streamlit (local browser-based UI, no external network calls) + pandas/openpyxl for all Excel I/O. Launched via a double-clickable `run.bat`.

```
Lead QA Automation/
├── app.py
├── run.bat
├── requirements.txt
├── core/
│   ├── models.py            # ClientProfile, Segment, CheckConfig dataclasses
│   ├── profile_store.py     # load/save client profiles as JSON
│   ├── excel_io.py          # workbook/tab reading & writing, accumulated-report format preservation
│   ├── checks/
│   │   ├── duplicate.py
│   │   ├── leadcap.py
│   │   ├── exclusion.py
│   │   ├── tal.py
│   │   ├── suppression.py
│   │   └── dedupe_list.py
│   ├── pipeline.py          # runs checks in order, aggregates results
│   └── matching.py          # domain extraction, name normalization, alias table, fuzzy scoring
├── pages/
│   ├── 1_Client_Setup.py
│   └── 2_Run_Check.py
├── clients/
│   └── <ClientName>.json
└── aliases/
    └── company_aliases.json # global, editable, reusable across clients
```

Each check is an independently testable module: given the leads dataframe + relevant reference data + this client's config for that check, it returns pass/fail + reason per row. Checks can be toggled per client without affecting others.

## Client Profile

One JSON file per client, created once at campaign start via the Client Setup page.

**Fixed reference files** (path saved, reused every run):
- Accumulated Report (tabs vary by client — real sample has `Lead Cap Lookup`, `Pacing Overview`, `Accumulated`, `Refund`; see "Accumulated Report Structure" below)
- TAL file (one sheet, or one sheet per segment)
- Exclusion List (the actual exclusion data may live on one specific sheet within a multi-sheet workbook — see below)
- Suppression List
- Dedupe List (optional)

**Per-client one-time setup, in addition to file paths:**
- Which sheet in the Exclusion List workbook holds the actual Account Name/Domain data (real sample file `Basware -Exclusion List.xlsx` has 4 sheets — `TAL`, `Persona titles `, `Expanded Job Titles`, `Exclusion` — only the last is the real exclusion data; the tool must let the user pick the sheet, not assume the first/only sheet)
- Same sheet-picker pattern applies to Suppression List and Dedupe List, in case they're also multi-sheet
- Field mapping: which column in the New Leads file is Email, First Name, Last Name, Company, CID — read once from the actual file's header row and picked from a dropdown, since exact header text varies by client (e.g. Basware uses `emailaddress`, `firstname`, `lastname`, `CID`, `company`, no spaces, mixed casing) even though the concept is always present

**Per-run files** (re-selected/uploaded every run):
- New Leads file (always required)
- Purchased Lead Report(s) — one per configured Leadcap segment, or one flat file if not segmented

**Per-check configuration:**

| Check | Config |
|---|---|
| Duplicate | On/off. Always checks exact email match + name+company fuzzy match, within the new-leads batch and against the Accumulated tab. |
| Leadcap | Off / Flat (one purchased-report file, one cap) / Segmented (list of `{name, CIDs, cap}` — the run screen generates one labeled upload slot per segment). The cap number is always entered/edited manually in the profile — real Purchased Lead Report files carry no cap column, and the Accumulated Report's own `Lead Cap Lookup` tab (if present) stores caps as free-text prose (e.g. "Lead cap = 5 leads/account shared CID 98779 and 98778") that the tool does not attempt to parse. A cap shared across multiple CIDs is expressed as one segment listing all of those CIDs. |
| Exclusion | Off / Domain only / Domain + Company name |
| TAL | Off / Domain only / Domain + Company name; Flat (one tab) / Segmented (list of `{name, CIDs, TAL tab name}`, tab picked from a dropdown of the actual sheet names in the TAL file) |
| Suppression | Off / any combination of Domain, Company name, Email |
| Dedupe list | Off / On — checks new leads' emails against the fixed dedupe list |

Cap values and other config are editable at any time without recreating the profile (caps can change mid-campaign).

Leadcap segments and TAL segments are independent of each other, even when they reference the same CIDs — no shared segment definition between the two checks, since real-world segmentation for each doesn't always line up.

## Check Logic & Order

Checks run in this order against the new collated leads file (Duplicate additionally checks the Accumulated tab). A lead runs through **all** checks regardless of an earlier failure, so its final Reason column lists every check it failed, not just the first.

1. **Duplicate**
   - Exact email match (within batch or vs. Accumulated tab) → fail, reason `Duplicate - exact email`
   - Same first+last name + same company, where the email domain is a recognizable variant of the company name → fail, reason `Duplicate - name/company match`
   - Same name but company/domain similarity is ambiguous → routed to **Needs Review**, not auto-passed or auto-failed

2. **Leadcap**
   - Resolve the lead's segment by CID (if segmented); read that segment's Purchased Lead Report (or the flat one)
   - Purchased Lead Report reflects the running cumulative count to date per domain/company
   - If count ≥ cap → fail, reason `Leadcap exceeded`
   - Segment-file identification: since files carry no segment/geo label, the run screen presents one labeled upload slot per configured segment (e.g. "Upload Purchased Lead Report for: AU Geo — CID 114578"). After upload, the tool cross-checks the CIDs actually present in the file against the segment's expected CID list and warns on mismatch.

3. **Exclusion**
   - Domain always checked (extracted from lead email) against Exclusion List domains
   - If company-name toggle on, also checked via the name-matching pipeline below
   - Fail reason: `Exclusion - domain` / `Exclusion - company`

4. **TAL**
   - Domain always checked against the TAL (correct tab if segmented, via the profile's CID→tab mapping)
   - If company-name toggle on, also checked via the name-matching pipeline
   - Fail if domain not found: `TAL - not found`

5. **Suppression**
   - Checks whichever of domain/company/email are toggled on, against the Suppression List
   - Fail reason: `Suppression - domain` / `Suppression - company` / `Suppression - email`

6. **Dedupe list**
   - Lead's email checked against the fixed dedupe list
   - Fail reason: `Dedupe list - email match`

### Company-name matching pipeline (used by Exclusion, TAL, Suppression, and Duplicate's company check)

Three layers, cheapest first:
1. **Normalize** — lowercase, strip punctuation and legal suffixes (Inc, LLC, Corp, Ltd, Co, etc.) before comparing.
2. **Alias table** (`aliases/company_aliases.json`, global, reusable across clients) — known equivalent names (e.g. `Facebook = Meta`, `Google = Alphabet`) checked after normalization fails to match directly. Grows over time as the user resolves Needs Review items.
3. **Fuzzy match** — similarity scoring for everything else. Above a high-confidence threshold → auto-match. Below a low threshold → no match. In between → routed to **Needs Review**, with an option to add the pair to the alias table on resolution so it's never manually reviewed again.

Domain matching is always the primary, exact signal; company-name matching is a supplementary layer for when domain alone isn't decisive or isn't present.

## Run Workflow

1. Pick a Client from a dropdown (loads saved profile).
2. Upload today's New Leads file, plus any per-run files needed for Leadcap.
3. Click **Run Check**. Pipeline executes checks 1–6 in order, tagging every lead with pass/fail + reasons.
4. Results screen shows:
   - Summary counts (e.g. "120 in → 95 valid, 18 refunded, 7 needs review")
   - Refund reason breakdown table
   - **Needs Review** list (ambiguous duplicates, ambiguous company-name matches) for manual resolution — approve as valid, mark as refund, or (for company-name cases) add an alias
5. Click **Finalize** once review items are resolved. This:
   - Appends valid leads to the Accumulated tab and refunded leads to the Refund tab, per the column-handling rules below
   - Saves the Accumulated Report back to its original path, after writing a timestamped backup copy alongside it

Nothing is written to disk until Finalize is clicked — an interrupted or abandoned run is always safe to redo.

## Accumulated Report Structure & Write Rules

The Accumulated Report is user-maintained and its exact tabs/columns vary by client/campaign — the tool does not assume a fixed universal schema. Instead, at append time it reads whatever header row currently exists in the target tab and fills each column using these rules, matched by header name (case-insensitive):

- **`Date`** → the run date
- **`CID`** → the lead's CID (from the field-mapped New Leads column)
- **`Campaign Name`** (or equivalent) → a live formula matching the pattern already used in the sheet's existing rows (e.g. `=VLOOKUP(CID_cell, 'Pacing Overview' lookup range, 2, 0)`), copied and adjusted for the new row number — not a static value. This is safe because one Accumulated Report only ever holds CIDs belonging to its own campaign's Pacing Overview, so every CID the tool appends is guaranteed to already be in that lookup range.
- **`Comment`** / **`Status`** (or equivalent) → left blank for the user to annotate manually; the tool does not auto-fill it
- **Any other existing column header** → matched by name against the New Leads file's columns (using the field mapping for Email/First Name/Last Name/Company/CID, and direct header-text match for everything else, e.g. `jobtitle`, `address`, `industry`); if a match is found, the lead's value is pasted in; if the Accumulated tab has a column with no corresponding data in the New Leads file, it's left blank for that row
- Columns present in the New Leads file but absent from the Accumulated tab's headers are **not** added automatically — the user adds a new column header to the Accumulated tab themselves first if they want it captured, and the tool will then start filling it on the next run

**Refund tab** uses the exact same header set and fill rules as the Accumulated tab, plus one additional dedicated **`Reason`** column (not reusing `Comment`) listing every check the lead failed, e.g. `Exclusion - domain; TAL - not found`.

## Data Assumptions

- Email, First Name, Last Name, Company, and CID concepts are always present in a client's New Leads file, but exact header text varies by client — handled via the one-time field mapping in Client Setup.
- The Accumulated Report carries additional client-specific columns beyond these core fields; the tool passes these through by header-name match rather than requiring them to be modeled (see "Accumulated Report Structure & Write Rules").
- Domains are not present as their own column in lead files or Purchased Lead Reports — always extracted from the email address.
- Reference list workbooks (Exclusion, Suppression, Dedupe) may contain multiple sheets where only one holds the real list data — the relevant sheet is picked once during Client Setup, not assumed.
- Real sample data (client: Basware) has been inspected and used to validate all of the above — see `sample_data/` in the project root.

## Error Handling

- Missing/renamed expected column in an uploaded file → explicit error naming the file and missing column, not a raw exception
- Uploaded file mismatched against what a slot expects (e.g. TAL file missing the mapped tab) → warning surfaced before running checks
- Timestamped backup of the Accumulated Report is always written before it's overwritten on Finalize

## Testing

- Unit tests per check module using small synthetic Excel fixtures: exact matches, normalized-name matches, alias-table matches, fuzzy gray-zone cases, segmented vs. flat Leadcap/TAL, missing optional files
- One end-to-end test: full client profile + run → verifies Accumulated/Refund tab output
- Once the real Accumulated Report format is supplied, a fixture derived from it will validate the format-preservation logic against actual structure, not an assumption

## Out of Scope (v1)

- Dumping valid leads into the separate Lead QA output template
- Mapping/uploading leads into portal-specific upload templates tied to SIDs

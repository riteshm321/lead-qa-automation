# Lead QA Automation

A local Streamlit tool that runs a batch of new leads through a client's configured QA
checks (duplicates, lead caps, exclusion/TAL/suppression lists, dedupe lists), lets you
review anything ambiguous, and writes the results into that client's Accumulated Report
(and Lead Template, if configured) — instead of doing all of that by hand in Excel.

> **Note on this README:** all paths, folder names, and client names below are examples
> only. Do not put real client names, real file paths, or any other client-identifying
> information into this repository — it's source code, not a place for client data.

---

## 1. Getting the tool

The packaged app is a folder, not a single file: `LeadQAAutomation.exe` plus an
`_internal` folder next to it (the actual Python/Streamlit runtime and dependencies).

- **Always share/copy the whole folder**, not just the `.exe`. If only the `.exe` is
  copied, it will open and close immediately, because it can't find `_internal`.
- To run it: open the folder and double-click `LeadQAAutomation.exe`. It opens your
  default browser to the app automatically.
- Building it yourself from source: `pyinstaller LeadQAAutomation.spec --noconfirm`
  (see [Development](#7-development--running-from-source) below).

---

## 2. First launch — where your data lives

The app keeps two kinds of files outside this repository, on your own machine:

- **Client profiles** (one JSON file per client — which checks are on, file paths,
  column mappings, etc.)
- **Company aliases** (a shared list of "these two company names are the same",
  learned over time)

By default both are **private to your machine**, stored in
`%LOCALAPPDATA%\LeadQAAutomation\`. A colleague running their own copy of the exe won't
see your clients or aliases unless you both point at the same shared folder — see
[Section 6](#6-sharing-clients-across-a-team-optional).

---

## 3. Setting up a client (Client Setup page)

Each client is configured **once**, then reused every time you run a check for them.

### 3.1 Basics tab

- **Client name** — anything memorable; this is also the filename of its saved profile.
- **Accumulated Report path** — the full path to that client's Accumulated Report
  `.xlsx` file. Use the **Browse...** button rather than typing it, to avoid typos.
- **Accumulated Report SharePoint link** (optional) — used as the "Accumulated File"
  link when posting a summary to Jira, instead of a local file path; see
  [Section 13](#13-posting-a-run-summary-to-jira-optional).
- **Accumulated tab name** / **Refund tab name** — the sheet names inside that workbook
  where valid leads and refunded leads get written. Defaults are `Accumulated` and
  `Refund`; change these if the client's file uses different sheet names. **These
  sheets must already exist in the file** — the tool doesn't create new sheets from
  scratch, only new rows in ones that exist.
- **Column mapping** — map the Accumulated Report's own column headers to Email,
  First Name, Last Name, Company, and CID once. Other columns are matched
  automatically by name when possible (see [Section 8](#8-header-matching--what-to-name-your-columns)).
- **Jira ticket key or link** (optional) — paste either `PROJ-1234` or the full
  ticket URL (e.g. copied from your browser's address bar); both work; a pasted
  link is automatically reduced to just the key. Set this to enable a "Post
  summary to Jira" button after Finalize — see [Section 13](#13-posting-a-run-summary-to-jira-optional).

### 3.2 Client Mode

- **Lead QA** — leads also get appended to a separate **Lead Template** file (e.g.
  for uploading to a client's own portal), configured as below. Despite the name,
  this is the mode *with* Lead Template support.
- **Lead QA & Upload** — leads only go into the Accumulated Report; no Lead
  Template section is shown at all (reserved for a future direct-upload
  mechanism that isn't file-based).

When mode is **Lead QA**, configure:
  - **Lead Template path** and its **sheet name** (single-tab). This can be left
    blank if every CID group has its own separate file (see below) — a shared
    default isn't required.
  - **Lead Template SharePoint link** (optional) — used as the "Lead Report" link
    when posting a summary to Jira, instead of a local file path; see
    [Section 13](#13-posting-a-run-summary-to-jira-optional).
  - **multi-tab/multi-file routing**: tick "Route different CIDs to different tabs
    and/or separate files" and list each tab's sheet name plus which CIDs belong to
    it. A lead's CID decides which tab it lands in; a CID that matches no tab still
    goes to the Accumulated Report, just not the Lead Template.
    - Each tab can optionally point at its **own file** — leave it blank to use
      the shared Lead Template path above, or set it when that CID group's leads
      actually belong in a completely separate workbook, not just another tab.
    - Each tab can also optionally set its **own SharePoint link**, for when its
      file lives at a different location than the shared Lead Template link above.
  - **Clear existing leads before adding new ones** — off by default (leads
    accumulate below whatever's already there, like the Accumulated Report). Turn
    this on for a Lead Report that gets re-sent fresh each time rather than
    accumulated: it removes all existing data rows (keeping the header and its
    formatting, which is reused for the new rows) before pasting this run's leads.
  - The Lead Template's header row doesn't have to be row 1 — the tool scans the
    first 20 rows for one that looks like a real header row.
  - For a plain **Lead QA** client (not a Complex Account), every row this run
    added to the Lead Template is highlighted in light green (`#C6E0B4`) so the
    newest batch stands out — any highlight left over from an earlier run is
    cleared first, so only the latest batch is ever colored. The Accumulated
    Report is never highlighted.

### 3.3 Leadcap, Exclusion, TAL, Suppression, Dedupe & Duplicate tabs

Each check is opt-in — leave it off if a client doesn't need it.

- **Duplicate** — no configuration; compares new leads against the Accumulated
  Report and against each other in the same batch (see rules in
  [Section 9](#9-what-each-check-actually-does)).
- **Leadcap** — checks a lead's company/domain against a **Purchased Lead Report**
  (uploaded fresh each run) and fails leads once a cap is exceeded. Supports a flat
  cap or per-segment caps (a segment = a name + a list of CIDs + its own cap).
- **Exclusion / TAL / Suppression / Dedupe list** — each takes one or more
  **reference sources**: a file path, a sheet name, and which of its columns hold
  Domain / Company / Email. A source can optionally be scoped to specific CIDs
  (leave blank to apply it to every CID). Use the **Auto-detect from Pacing
  Overview** helper if the client's Accumulated Report has a "Pacing Overview"
  sheet listing CIDs — it saves typing them in by hand.

Click **Save Client Profile** when done. Re-open the same client from the "Edit
existing client" mode to change anything later.

---

## 4. Running a check (Run Check page)

1. Pick the client from the dropdown.
2. Upload the **New Leads file** — `.xlsx` or `.csv` (see
   [Section 10](#10-csv-upload-notes) for CSV specifics).
3. If this is the first time this leadfile's column names have been seen for this
   client, map Email/First Name/Last Name/Company/CID once — it's remembered after
   that.
4. If Leadcap is enabled, upload the **Purchased Lead Report** for this run.
5. Click **Run Check**.
6. Review the results:
   - **Refund Reasons** — leads the tool auto-flagged for refund. Tick "approve as
     valid" on any that should actually count as valid (e.g. a false-positive
     duplicate), or use **Select all as valid**. Anything left unticked stays in the
     Refund tab only.
   - **Needs Review** — leads the tool couldn't confidently pass or fail (e.g. a
     borderline company-name match). Each card shows the actual values compared side
     by side. Approve or refund each one individually.
7. Click **Finalize**. This backs up the Accumulated Report first (see
   [Section 11](#11-backups)), then writes valid leads to the Accumulated Report (and
   Lead Template, if configured) and refund-only leads to the Refund tab.
8. If the client has a Jira ticket key configured, a **Post summary to Jira** prompt
   appears — see [Section 13](#13-posting-a-run-summary-to-jira-optional).

Use **Clear** (top right) to discard the current upload/results and start over.

---

## 5. File & tab naming conventions

| What | Convention |
|---|---|
| Accumulated Report tab names | Configurable per client (Basics tab); default `Accumulated` / `Refund`. Must already exist in the workbook. |
| Accumulated Report header row | Normally row 1; if the tool can't find your mapped columns there, it scans for the row that looks most like a real header. |
| Lead Template sheet name(s) | Configurable per client; for multi-tab clients, one sheet per CID group. |
| Lead Template header row | Auto-detected — doesn't have to be row 1. |
| New Leads (leadfile) columns | Any names — mapped once per client, remembered afterward. |
| Extra columns (beyond Email/Name/Company/CID) | Matched to the leadfile automatically by name — see [Section 8](#8-header-matching--what-to-name-your-columns). |
| Purchased Lead Report / reference source files | `.csv` (Leadcap) or `.xlsx` (Exclusion/TAL/Suppression/Dedupe) with a Domain/Company/Email/CID column, named per your Client Setup configuration. |

---

## 6. Sharing clients across a team (optional)

By default, clients and aliases are private to your machine. To share them with a
colleague:

1. On the **⚙️ Settings** page, open **⚙️ Shared team data location**.
2. Point **Shared team data folder** at a folder inside a OneDrive folder you both
   sync locally — e.g. `C:\Users\<you>\OneDrive - <Your Org>\Shared\LeadQA` (pick the
   folder itself, not a `clients` subfolder inside it; the app manages its own
   `clients/` and `aliases/` subfolders under whatever you pick). Click **Save**.
3. Your colleague does the same **on their own machine**, pointing at their own local
   path to that same shared OneDrive folder.

Once both of you point at the same underlying folder, clients either of you creates
show up for the other (after OneDrive finishes syncing — usually seconds).

**Caveat:** OneDrive syncs file-by-file, not instantly. If you both save the exact
same client profile at the exact same moment, OneDrive may create a conflicted copy
instead of merging. Treat this as low-frequency shared config, not simultaneous
editing.

---

## 7. Development — running from source

```bash
pip install -r requirements.txt
python -m streamlit run Summary.py
```

Run the test suite:

```bash
pytest
```

Rebuild the exe after making changes:

```bash
pyinstaller LeadQAAutomation.spec --noconfirm
```

The build output (`dist/LeadQAAutomation/`) is git-ignored — share it as described in
[Section 1](#1-getting-the-tool), not via this repository.

---

## 8. Header matching — what to name your columns

Beyond the 5 explicitly-mapped fields (Email, First Name, Last Name, Company, CID),
other columns are matched between the leadfile and the target (Accumulated Report or
Lead Template) automatically:

1. **Exact match** after stripping spaces/underscores/hyphens/case — e.g.
   `Job_Function` matches `Job Function` matches `jobfunction`.
2. **Containment** — e.g. a leadfile column like `MarketSegmentReferential` still
   matches a target column named `Market Segment`.
3. **Fuzzy similarity** — catches typos and reordered words.

A match is only used when it's unambiguous. If two leadfile columns could equally
match one target column, neither is auto-picked — the target column is left blank and
listed in an on-screen warning after Finalize, so you can rename a column and re-run
rather than silently getting the wrong data in the wrong place.

---

## 9. What each check actually does

- **Duplicate**: same email as an existing lead → **fail**. Same first+last name as an
  existing lead, and the *same company*, but a *different email domain* →
  **needs review**. Same name, same company, and the *same domain* (just a different
  address) → **fail**. Same name but a genuinely different (or unknown) company →
  passes through untouched — that's just two different people sharing a name.
- **Leadcap**: fails a lead once the number of prior purchases for its
  company/domain (from the Purchased Lead Report) exceeds the configured cap.
- **Exclusion / TAL**: checks a lead's email domain (and optionally company name)
  against a reference list; TAL also fails a lead outright if its domain isn't found
  at all (target account list = only these accounts are in-scope).
- **Suppression**: fails a lead whose domain, email, and/or company name (configurable)
  matches a suppression list.
- **Dedupe list**: fails a lead whose email matches a separate dedupe reference list.
- Ambiguous company-name matches (not exact, not clearly different) land in
  **Needs Review** instead of being auto-decided either way.

---

## 10. CSV upload notes

The New Leads uploader accepts CSV in addition to Excel. It automatically handles the
most common real-world quirks so you don't need to "clean" the file first:

- UTF-8 files with or without a byte-order mark (BOM) — common from Excel's own
  "Save As CSV".
- Windows-1252 / Latin-1 encoded files — common from older export tools.
- Comma, semicolon, tab, or pipe delimiters — semicolon is common in European-locale
  exports.

---

## 11. Backups

Before every Finalize, the tool copies the client's current Accumulated Report into a
`backup` subfolder next to it (created automatically if it doesn't exist yet), named
with a timestamp. If something goes wrong, restore from there.

---

## 12. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Exe opens and closes immediately | Only the `.exe` file was copied, not the whole folder — see [Section 1](#1-getting-the-tool). |
| "Windows couldn't find part of that file path" (WinError 3) | The full file path is too long (Windows' ~260-character limit) — common with deeply nested OneDrive folders. Move the file to a shorter path or shorten a parent folder name. |
| Excel prompts "we found a problem" / offers to repair after a Finalize | Should not happen — the tool preserves the workbook's external-link data byte-for-byte across saves. If you still see this, it's worth a bug report. |
| A client you expect to see isn't in the dropdown | Check the **Shared team data location** setting points at the right folder, and that the client's `.json` file sits directly inside its `clients` subfolder (not nested further). |
| A column you expect to be filled is blank after Finalize | Check the on-screen "these columns had no matching leadfile column" warning after Finalize — rename the leadfile column to something closer to the target header and re-run. |

---

## 13. Posting a run summary to Jira (optional)

After Finalize, if the client has a **Jira ticket key** set (Client Setup → Basics),
a "Post summary to Jira" prompt appears, pre-filled and ready to review:

- **Opening message** (editable) — `Hi <reporter name>,` (or just `Hi,` if none is
  set) followed by `PFB summary for the Lead QA dated <date>. Also, PFB the links for
  the relevant files.`
- **File links** — checkboxes to include the Accumulated Report and (for
  "Lead QA" clients with a Lead Template configured) the Lead Report as clickable
  links in the comment. If a SharePoint link is configured for that file (Client
  Setup → Basics), that's what gets used — a universal link anyone can open. If
  per-CID routing wrote to more than one Lead Template file this run, each file
  gets its own labeled link. Without a configured SharePoint link, it falls back
  to a local file path that only opens **on a machine where that exact path
  exists** (typically your own machine, or a teammate syncing the identical
  shared folder).
- **Pacing Overview table** (if the Accumulated Report has that sheet) — a live
  preview of the table exactly as it'll post, as a real Jira table (not an image or
  plain text). Untick to leave it out.
  - If any of that sheet's columns are **formulas** (e.g. Delivered/Remaining/
    Pacing/date columns driven by `COUNTIFS`-style formulas), the tool briefly
    opens a hidden copy of the file in Excel to force a fresh recalculation
    before reading it — otherwise it would show whatever value Excel last
    cached, which goes stale the moment this app appends new leads (it writes
    via openpyxl, which never recalculates formulas). This requires **Excel to
    be installed** on this machine; if it isn't (or the attempt fails), the
    preview falls back to the file's last-saved values with an on-screen
    warning, rather than blocking the Jira post entirely.
  - A free-text cell over 20 characters (e.g. a long Campaign Segment name) is
    truncated with `…` so every row stays the same height. **Note:** Jira's ADF
    comment format has no way to shrink a table's font size via the API — column
    widths and this truncation are the only levers available to keep a wide,
    growing table compact.
- **Closing message** (editable) — defaults to "Thanks".

Since not every run is a QA task — some are plain uploads — nothing here is
hard-coded to always appear; the file links and table sections only show up when
there's actually something to link or a Pacing Overview sheet to show.

**Per-client setup** (Client Setup → Basics):

- **Jira ticket key or link** — paste either form; a link is auto-reduced to the
  key. The same ticket usually covers a client's whole campaign — come back and
  update it here if that ever changes (e.g. a new campaign, a new ticket).
- **Jira reporter's name** (optional) — used for the greeting.

**One-time account setup**, on the **⚙️ Settings** page → **🔑 Jira account (private to this machine)**:

- **Jira site URL** — e.g. `https://yourcompany.atlassian.net`.
- **Your Jira email** and **API token** — generate a token at
  `id.atlassian.com/manage-profile/security/api-tokens`. The comment is posted under
  *your own* Jira account, using your own credentials.

These credentials are stored **only** in your local, private settings file — never
inside the shared clients folder from [Section 6](#6-sharing-clients-across-a-team-optional),
since an API token is a personal secret, not something to sync to a team folder. Each
person who wants to use this button configures their own token once, on their own
machine.

Nothing is posted automatically — review (and edit) everything first, then click the
button to actually send it. Click **Dismiss** to skip posting for that run without
sending anything.

---

## 14. Complex Accounts (optional)

Some accounts need extra, highly specific enrichment rules on top of the standard
checks — currently built for one client, **Dell APAC** — rather than a generic,
configurable feature. See `core/complex_account.py` for the actual rule logic; column
names are hardcoded there, not configurable per client.

**One-time setup** (Client Setup → **🧩 Complex Account**):

- Tick **"This is a complex account"**.
- **TAL file path** — the account-ID/company-name reference (large CSV). Matched by
  the lead's email domain; when a domain maps to more than one account, the one whose
  country matches the lead's own `Country` column wins.
- **Specifications file path** (the "...BANT NTQ & EHS" workbook) — Asset Name → URN /
  Asset URL 1 & 2 / Dell URL, used to check whether the leadfile's already-filled Asset
  URN / Form URL / Dell Asset URL are correct for that Asset Title.

**Every run** (Run Check page, only shown for a complex-account client): upload that
run's **Installed Technologies** and **Predictive Buying Stage** files — one pair per
CID, like the Purchased Lead Report. After uploading the New Leads file, a **CID
dropdown appears under each uploaded file** — pick which of the leadfile's own CIDs
that file belongs to (the filename doesn't reliably identify it, so it isn't
auto-detected). A CID with no file assigned to it this run has its corresponding
column cleared rather than left with stale data.

**Run Check works in two extra stages for a complex-account client**, instead of a
single Finalize:

1. **Run Check** — the normal checks (Duplicate/Leadcap/Exclusion/TAL/Suppression/
   Dedupe) and three Complex Account conditions run together on the raw leads: a
   blank/unparseable **Capture Date**, an **Email Opt-in** value that isn't clearly
   "Yes"/"No", or an already-filled **Asset URN/Form URL/Dell Asset URL** that doesn't
   match the specifications file for that lead's Asset Title — any of these sends that
   lead to **Needs Review** exactly like any other check. Resolve Refund Reasons/Needs
   Review as usual. The Summary also lists every enabled check (normal and Complex
   Account) that ran, so it's clear what was actually applied to this batch.
2. **Finalize (fill columns)** — runs the actual column-filling rules below on just the
   leads that ended up valid, and shows a **preview** of the filled columns. Nothing is
   written yet.
3. **Confirm & Write** — writes the previewed leads to the Accumulated Report and Lead
   Template(s), same as the normal single-step Finalize.

**Column-filling rules**, applied only to that valid-leads preview:

1. **TAL mapping** — `Account ID` and `Company` filled from the TAL by domain (no
   match → blank Account ID, `Company` left as-is).
2. **Installed Technologies** / **Predictive Buying Stage** — looked up by domain in
   that lead's CID's uploaded file, written as `"Installed Technologies: {value}"` /
   `"Predictive Buying Stage: {value}"`, replacing whatever was there. A domain listed
   on more than one Installed Technologies row (one technology per row) gets all of
   them combined, comma-separated. A Predictive Buying Stage value of "No Active
   Signals" is treated as nothing to report — that lead's column is left blank.
3. The first "Additional Data Point" column keeps its existing value, prefixed with
   `"Top Trending Topics: "`.
4. **Capture Date** reformatted to `mm/dd/yyyy` (parsed flexibly, not just already
   the right format) and written as a real Excel date, not text, so it displays and
   filters like a date rather than tripping Excel's "Number Stored as Text" warning.
5. **Email Opt-in** collapsed to a bare `"Yes"`/`"No"`.
6. **Asset download day/month/year** derived from the (now-clean) Capture Date — day
   and year written as real numbers (not zero-padded text), month as its full name,
   year hardcoded `2026`.
7. **Phone** — every non-digit character stripped, then a space inserted after the
   first 2 digits.

The preview (and this list) never includes Asset URN/Form URL/Dell Asset URL — those
are already filled in the leadfile and are only ever checked (step 1 above), never
rewritten.

---

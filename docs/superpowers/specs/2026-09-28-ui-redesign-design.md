# UI Redesign & Client Grouping Design

## Goal

Make the app look and feel like a polished, professional internal tool
instead of "default Streamlit with a color theme" — both the visual craft
(icons, cards, spacing, status feedback) and the information architecture
(long, undifferentiated forms) — without leaving Streamlit or touching any
business logic in `core/`. Alongside this, let a brand split across
multiple regional client profiles (e.g. one brand with an APAC profile and
an EMEA profile) be picked as one recognizable group instead of two
unrelated entries in a flat alphabetical list.

## Scope

- **In scope:** icon system, card/chip visual language, shared empty/
  loading/error treatment, Home page as a real dashboard, Client Setup's
  tab consolidation, Run Check's stepper/metric-card treatment, the
  two-step client-group picker (shared by both pages), and extending the
  same visual language to the remaining 6 pages.
- **Out of scope:** replacing Streamlit with a custom web front-end (a
  separate, much larger project — considered and explicitly declined, see
  below); any change to check logic, file formats, or write paths; a fixed
  region taxonomy (region names stay free text, matching how client names
  already work); bundling a custom brand font (already declined in the
  2026-08-21 UI branding pass, still holds).

## Design

### 1. Visual language (foundation)

- **Icons**: replace every emoji (sidebar nav, section headers, in-page
  buttons/captions) with Streamlit's built-in Material Symbols shorthand
  (`icon=":material/name:"`). Zero new dependency — `Summary.py` already
  passes `icon=` to every `st.Page(...)`, so the nav swap is a one-file
  change; section-header emoji get the same treatment page by page.
- **Cards**: every related group of settings/fields renders inside a
  bordered `st.container(border=True)` with a small icon + title in the
  header — the pattern the app already uses in a few places, made the
  default everywhere instead of the exception.
- **Status chips**: small colored pill badges (`● On` / `○ Off`,
  `✓ Configured`, `⚠ Needs setup`) rendered via `st.badge` (Streamlit's
  built-in colored-badge primitive) so a client's configuration reads at a
  glance instead of requiring every checkbox to be read individually.
- **Section headers**: icon + title + one-line caption, applied
  consistently — Client Setup already does this for some sections; this
  makes it universal.

### 2. Shared chrome

- **Home page** becomes a real dashboard: recent activity (last few
  clients run, read from the existing Activity Log data — no new
  tracking), quick-launch cards linking to Client Setup/Run Check, and the
  Time Saved figures already computed for the sidebar promoted into the
  main view too.
- **Empty states**: a section with nothing configured shows an icon + one
  short line explaining what's missing + where to fix it, instead of
  rendering nothing or a bare caption.
- **Loading feedback**: the 2026-08 pass added `st.spinner` around Run
  Check's slow buttons; extend the same treatment to Client Setup's save
  action and any other multi-second operation that currently gives no
  feedback.
- **Errors/warnings**: a single shared rendering helper (icon + message +,
  where there's an obvious next step, a one-line suggestion) instead of
  each page's own ad hoc `st.error`/`st.warning` call, so every error looks
  and reads the same way everywhere.

### 3. Client group + region picker

**Problem:** a brand split across regional profiles (e.g. one APAC profile
and one EMEA profile for the same brand) sits wherever alphabetical order
puts each one in today's flat client dropdown, with no visual link between
them.

**Data model:** one new optional field on `ClientProfile`:
`client_group: str = ""`. Blank by default — nothing changes for a client
that isn't part of a multi-region split. Set once per regional profile in
Client Setup (e.g. both the APAC and EMEA profiles for the same brand get
`client_group` set to that brand's name).

**Picker UI**, shared by Client Setup's "Edit existing client" selector and
Run Check's "Client" selector (one new shared helper so the two pages can
never disagree about how grouping renders):

1. **Group step** — one dropdown listing every distinct `client_group`
   value, plus every ungrouped profile's own name treated as its own
   singleton group, so nothing is ever hidden behind a group it didn't ask
   to join. A group with more than one profile shows a small count badge
   (e.g. "2 regions").
2. **Profile step** — only rendered when the chosen group actually has more
   than one profile; auto-selects the sole profile and skips this step
   entirely otherwise, so the common (non-split) case stays exactly as
   fast as today — one click, not two.

This is native Streamlit widgets only (two `st.selectbox` calls plus one
small grouping helper) — no new dependency, and it's fully backward
compatible since every existing profile defaults to its own ungrouped
singleton entry.

### 4. Client Setup restructure

Today, Basics/Leadcap/Exclusion/TAL/Suppression/Dedupe/Complex Account are
tabs, but Reference Files, Client Mode, Lead Template, Google Sheets, and
Duplicate Check sit outside the tabs in one long scroll below them — an
inconsistent split between two different navigation models on the same
page.

Fold everything into one consistent tab structure:

- **Basics** — client name, client group, reference files, Jira.
- **Delivery** — Client Mode, Lead Template, Google Sheets (the "where do
  valid leads go" question, grouped together since they're related).
- **Checks** — Leadcap, Exclusion, TAL, Suppression, Dedupe, Complex
  Account, Duplicate — each still its own card, each tab label carrying a
  small "configured" chip when that check is on.

An always-visible summary strip (the status-chip row from section 1) sits
above the tabs, so a client's whole configuration is readable before
opening any tab.

### 5. Run Check restructure

Run Check is already a real 3-step flow (Run Check → Review & Finalize →
Post to Jira) — the redesign makes that visually obvious instead of
implicit:

- The 3 steps become a real visual stepper using the icon/chip language
  from section 1, instead of plain text with a coloured circle.
- Leads In / Valid / Refunded / Needs Review become metric cards instead
  of four bare numbers.
- The Needs Review table gets row-level action controls where that's a
  clean fit, alongside the existing bulk select-and-act flow (which stays,
  for genuinely bulk actions).
- The client picker here uses the same two-step group→profile picker from
  section 3.

## Rollout

1. **Foundation** — icon swap, card/chip components, shared empty/loading/
   error treatment, the client-group data field + shared picker helper.
   Touches both Client Setup and Run Check's client selectors plus every
   page's `configure_page()`-driven chrome, so it's felt everywhere
   immediately even before the two big pages are individually restructured.
2. **Client Setup** — tab consolidation + section visual treatment.
3. **Run Check** — stepper + metric cards + Needs Review polish.
4. **Remaining 6 pages** (Settings, Activity Log, Box Tracker, Fuzzy Match,
   Convertr, Enhancio, Integrate) — apply the same foundation elements
   built in step 1; lighter-touch since these pages are smaller and
   simpler already.

Each phase ships as its own reviewed change, per this project's existing
TDD/incremental-commit convention — nothing here requires phases 2-4 to
land together.

## Explicitly declined

- **Custom web front-end rebuild** — full creative freedom, but a total
  rewrite of every page's UI layer, a new packaging/deployment story
  (replacing the current PyInstaller-exe model), and a much larger, riskier
  project than what "make it look professional" actually calls for.
  Considered and set aside in favor of polishing within Streamlit.
- **A fixed region taxonomy** for the client-group feature — region labels
  stay free text (the profile's own existing `name` field already carries
  this, e.g. "Brand APAC"), avoiding a second naming system to keep in
  sync with client names.
- **Third-party Streamlit UI components** (e.g. a tree-select widget) for
  the group picker — would add a new dependency and packaging risk for the
  exe build; the two-step native-selectbox approach achieves the same
  outcome with zero new dependencies, consistent with this project's
  established minimal-dependency stance (e.g. choosing Material Symbols
  over a bundled icon font, the built-in sans-serif theme font over a
  bundled brand font).

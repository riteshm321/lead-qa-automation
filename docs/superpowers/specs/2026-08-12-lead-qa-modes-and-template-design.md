# Lead QA Modes & Lead Template — Design Spec

Date: 2026-08-12
Status: Approved by user

## Purpose

Introduce a per-client mode setting — **"Lead QA"** or **"Lead QA & Upload"** — that controls whether, in addition to the existing Accumulated Report append, valid leads also get pasted into a per-client **Lead Template** file.

## Data Model (`core/models.py`)

`ClientProfile` gains:
- `client_mode: str = "Lead QA"` — one of `"Lead QA"` or `"Lead QA & Upload"`.
- `lead_template_path: str = ""`
- `lead_template_sheet_name: str = ""`

No changes to `profile_store.py` are needed beyond what dataclass (de)serialization already handles.

## Client Setup UI (`pages/1_Client_Setup.py`)

- Add a mode selector (`st.radio` or `st.selectbox`) near the top of the checks/config area: "Lead QA" / "Lead QA & Upload", defaulting to the profile's saved `client_mode` (or "Lead QA" for a new profile).
- When the selected mode is **"Lead QA"**, show a "Lead Template" section: a file path input with the existing Browse button pattern (`_path_input_with_browse`, matching the Accumulated Report path field) plus a sheet-name picker populated from that file's actual sheets (matching the existing pattern used elsewhere for source files). Persist as `lead_template_path` / `lead_template_sheet_name`.
- When the selected mode is **"Lead QA & Upload"**, the Lead Template section is hidden entirely, and `lead_template_path`/`lead_template_sheet_name` are saved as empty strings regardless of any previously-configured value (mirroring how other checks fall back to disabled state — mode change is an explicit user action, not a rerun artifact, so no stale-widget guard is needed for the hide/show itself, only the normal `_profile_identity` reinit already governing all such text inputs).

## Run Check (`pages/2_Run_Check.py`)

At Finalize time, after the existing Accumulated/Refund appends:

```python
if profile.client_mode == "Lead QA" and profile.lead_template_path and result.valid_indices:
    append_leads(profile.lead_template_path, profile.lead_template_sheet_name,
                 new_leads.loc[result.valid_indices], profile.field_mapping, run_date)
```

This reuses `append_leads` exactly as-is (same header-matching, formula/date/comment handling, and the row-formatting propagation already built) — no `reasons` argument, since only valid leads go to the template and it has no reason column. No backup is taken of the template file (only the Accumulated Report is backed up, unchanged from today).

If `client_mode == "Lead QA & Upload"`, this step is skipped entirely — behavior is identical to today.

## Testing

- `core/models.py`: round-trip test confirming `client_mode`/`lead_template_path`/`lead_template_sheet_name` persist through `profile_store` save/load, and that an old profile JSON without these fields loads with the defaults (`"Lead QA"`, `""`, `""`).
- `pages/*.py`: Streamlit UI, verified by running (consistent with how the rest of the UI has been tested throughout this project) — no automated test for the mode selector or template Browse button.
- No new test needed for the Finalize-time template append itself beyond what `append_leads` already covers — the call site is a one-line reuse of already-tested logic.

## Out of Scope

- The actual per-lead-ID upload-routing tool for "Lead QA & Upload" mode (deferred, per user).
- Any change to Accumulated/Refund append behavior (unchanged from the just-completed formatting/reason-column work).

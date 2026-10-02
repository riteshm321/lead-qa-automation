# pages/5_Box_Tracker.py
import datetime
import os

import pandas as pd
import streamlit as st

from core.app_settings import get_clients_dir
from core.box_tracker import (
    read_pacing_diffs, pick_leads_for_approval, sent_for_approval_label,
    append_mirror_rows, set_pacing_delivered,
    project_code_for_cid, parse_amal_id, strip_country_suffix,
    uploaded_to_approval_sheet_label,
)
from core.branding import configure_page
from core.errors import render_error, render_problem
from core.excel_io import read_sheet_as_dataframe, set_status_by_row_index
from core.models import resolve_field_mapping
from core.profile_store import list_profile_names, load_profile
from core.ui_components import render_empty_state

_current_user = configure_page("Box Tracker")
st.title(":material/inventory_2: Box Tracker")


@st.cache_data(show_spinner=False)
def _cached_profile_names(clients_dir: str, dir_mtime: float) -> list[str]:
    # Same fix/reasoning as pages/2_Run_Check.py's _cached_profile_names --
    # dir_mtime must NOT be underscore-prefixed (Streamlit excludes any
    # leading-underscore parameter from the cache key hash).
    return list_profile_names(clients_dir)


@st.cache_data(show_spinner=False)
def _cached_load_profile(name: str, clients_dir: str, mtime: float):
    # See _cached_profile_names above for the mtime-not-underscored reasoning.
    return load_profile(name, clients_dir)


@st.cache_data(show_spinner=False)
def _cached_sheet_df(path: str, sheet_name: str, mtime: float) -> pd.DataFrame:
    # The Accumulated Report was being re-read from disk via
    # read_sheet_as_dataframe up to 4 separate times on every single
    # rerun of this page (once per section, unconditionally) -- every
    # per-lead checkbox toggle across 3 lists re-parsed the whole
    # workbook that many times over. Same fix/reasoning as
    # pages/2_Run_Check.py's _cached_sheet_df. Keyed on the file's own
    # mtime (recomputed fresh at each call site, never itself cached) so
    # a write earlier in the SAME rerun -- e.g. the
    # set_status_by_row_index before this same page's later reads --
    # still correctly invalidates the cache for whatever reads it first.
    return read_sheet_as_dataframe(path, sheet_name)


def _clients_dir_mtime(clients_dir: str) -> float:
    try:
        return os.path.getmtime(clients_dir)
    except OSError:
        return 0.0


def _profile_file_mtime(name: str, clients_dir: str) -> float:
    try:
        return os.path.getmtime(os.path.join(clients_dir, f"{name}.json"))
    except OSError:
        return 0.0

# This workflow is specific to IBM APAC's Box-hosted lead-approval
# tracker -- no other client runs this process, so the page is tied to
# that one client rather than offered as a generic multi-client picker.
_IBM_APAC_CLIENT_NAME = "IBM APAC Interactive Avenues Pvt Ltd"

_STATUS_COLUMN = "Status"
_APPROVAL_SHEET_TAB = "Approval Sheet"
_PACING_TAB = "Pacing"
_MANUAL_STATUS_PREFIX = "Uploaded to Approval Sheet"

_clients_dir_now = get_clients_dir()
if _IBM_APAC_CLIENT_NAME not in _cached_profile_names(_clients_dir_now, _clients_dir_mtime(_clients_dir_now)):
    render_problem(f"Client \"{_IBM_APAC_CLIENT_NAME}\" isn't set up yet. Set it up on the Client Setup page first.",
                   level="warning")
    st.stop()

profile = _cached_load_profile(
    _IBM_APAC_CLIENT_NAME, _clients_dir_now, _profile_file_mtime(_IBM_APAC_CLIENT_NAME, _clients_dir_now))
if not profile.box_tracker.enabled:
    render_problem("Box Tracker isn't enabled for this client yet. Enable it on the Client Setup page first.",
                   "Tick **This client uses a Box Tracker** under Client Setup → Delivery.", level="warning")
    st.stop()
_pacing_skipped = set(profile.box_tracker.pacing_skipped_campaigns)
# Every DataFrame this page ever works with comes from re-reading the
# ACCUMULATED REPORT (read_sheet_as_dataframe calls throughout) -- never
# straight from a raw uploaded leadfile. profile.field_mapping describes
# the RAW LEADFILE's own column names (e.g. "company" for this client);
# profile.accumulated_field_mapping describes what those same roles are
# actually called INSIDE the Accumulated Report (e.g. "Company").
# Confirmed as the cause of "Company"/"Company Name" silently writing
# blank everywhere on this page whenever the two mappings disagree --
# using the accumulated one (falling back to field_mapping only if it was
# never set) everywhere below fixes that and prevents the same class of
# bug for any other role that drifts between the two in the future.
_acc_fm = resolve_field_mapping(profile.accumulated_field_mapping, profile.field_mapping)

st.caption(
    f"**{_IBM_APAC_CLIENT_NAME}**'s Box-hosted lead-approval tracker has no API access, so every write "
    "here goes straight to Box Desktop's local sync copy of the real file at "
    f"`{profile.box_tracker.mirror_workbook_path}` — Box syncs it from there on its own, no manual "
    "copy-paste step."
)


with st.container(border=True):
    st.subheader(":material/outgoing_mail: Send leads for approval")
    st.caption(
        "**Use this when:** you want the tool to pick leads for you, based on this week's Pacing "
        "numbers, and write them into the mirror's Approval Sheet automatically."
    )
    with st.expander("How this works", icon=":material/info:"):
        st.write(
            f"Reads {profile.box_tracker.mirror_workbook_path}'s Pacing summary block, picks "
            f"(Diff + 5) blank-{_STATUS_COLUMN} leads per campaign from the Accumulated Report (or ALL "
            "available leads for any campaign listed under Client Setup's \"skip Pacing updates\" list), "
            f"writes them into the mirror's {_APPROVAL_SHEET_TAB} tab, marks their {_STATUS_COLUMN}, and "
            "sets this week's Pacing Delivered count to the number sent (skipped entirely for those same "
            "campaigns)."
        )

    if st.button("Pick leads and send for approval", key="pick_and_send_button"):
        try:
            with st.spinner('Picking leads and sending for approval...'):
                accumulated_df = _cached_sheet_df(
                    profile.accumulated_report_path, profile.accumulated_tab_name,
                    os.path.getmtime(profile.accumulated_report_path))
                diffs = read_pacing_diffs(profile.box_tracker.mirror_workbook_path, _PACING_TAB)
                picked_df, shortfall = pick_leads_for_approval(
                    accumulated_df, _acc_fm.cid, _STATUS_COLUMN,
                    profile.box_tracker.cid_campaign_map, diffs, buffer=5,
                    uncapped_campaigns=_pacing_skipped,
                )

                if picked_df.empty:
                    render_problem("No blank-Status leads matched any mapped CID with a known Pacing Diff — nothing to send.",
                                   "Check the CID → campaign mapping under Client Setup → Delivery → Box Tracker covers "
                                   "these leads' CIDs.", level="warning")
                    st.stop()

                today = datetime.date.today()
                status_label = sent_for_approval_label(today)
                date_label = today.strftime("%d-%b")

                # Write the Approval Sheet mirror rows. Persona/Industry is the
                # campaign name; Project Code and AMAL ID normally pass through
                # from the leadfile's own columns, except for CIDs with a fixed
                # override (see project_code_for_cid/amal_id_for_cid) -- newly
                # live segments whose leadfile doesn't carry reliable values yet.
                # Approval is deliberately left blank -- the client fills it in.
                cid_to_campaign = profile.box_tracker.cid_campaign_map
                rows = []
                for _, lead in picked_df.iterrows():
                    cid = str(lead.get(_acc_fm.cid, ""))
                    rows.append({
                        "Company Name": lead.get(_acc_fm.company, ""),
                        "Segment": lead.get("Segment", ""),
                        "Persona/Industry": strip_country_suffix(cid_to_campaign.get(cid, "")),
                        "Project Code": project_code_for_cid(cid, lead.get("Project Code", "")),
                        "Market": lead.get("Country", ""),
                        "Job Title": lead.get("Job Title", ""),
                        "AMAL ID": parse_amal_id(lead.get("AMAL ID", "")),
                        "Date": date_label,
                    })
                _approval_unmatched = append_mirror_rows(profile.box_tracker.mirror_workbook_path, _APPROVAL_SHEET_TAB, rows)
                # "Approval" is deliberately never filled by this tool -- the
                # client fills it in -- so it's not a real mismatch to warn about.
                _approval_unmatched = [h for h in _approval_unmatched if str(h).strip().lower() != "approval"]

                # Set Pacing's Delivered count per campaign, for leads actually
                # sent -- except campaigns still on the skip list.
                cid_to_campaign = profile.box_tracker.cid_campaign_map
                picked_counts = picked_df[_acc_fm.cid].astype(str).value_counts()
                for cid, count in picked_counts.items():
                    campaign = cid_to_campaign.get(cid)
                    if campaign and campaign not in _pacing_skipped:
                        set_pacing_delivered(profile.box_tracker.mirror_workbook_path, campaign, int(count))

                # Mark Status in the Accumulated Report itself LAST, only once
                # the mirror write (and Pacing update) actually succeeded --
                # picked_df.index holds the original 0-based row positions
                # from accumulated_df (pandas preserves index labels through
                # boolean filtering/.head()), and read_sheet_as_dataframe is a
                # plain pd.read_excel with header row 1, so worksheet row =
                # index + 2. Previously this ran FIRST: if append_mirror_rows
                # failed for any reason (wrong tab, mirror file locked mid-Box-
                # sync, disk error), Status had already been persisted as sent
                # even though the leads were never actually written to the
                # Approval Sheet -- both recovery paths on this page filter
                # strictly on blank Status, so those leads became permanently
                # invisible to the whole tool with no way to recover them short
                # of manually editing the Accumulated Report. Confirmed real by
                # the audit; ordering it last means a failure here instead
                # just leaves Status blank, so the same leads are simply picked
                # again on the next attempt.
                set_status_by_row_index(
                    profile.accumulated_report_path, profile.accumulated_tab_name, _STATUS_COLUMN,
                    {idx: status_label for idx in picked_df.index},
                )

                st.success(f"Sent {len(picked_df)} lead(s) for approval — see {_APPROVAL_SHEET_TAB} in the mirror workbook.")
                if _approval_unmatched:
                    render_problem(
                        f"The {_APPROVAL_SHEET_TAB} tab has column(s) this tool doesn't fill in and left blank: "
                        f"{', '.join(sorted(_approval_unmatched))}. If that's unexpected, the mirror workbook's real "
                        "header text may not match what this page writes.",
                        level="warning",
                    )
                if shortfall:
                    for cid, amount in shortfall.items():
                        render_problem(f"CID {cid} was short by {amount} lead(s) — sent all that were available.",
                                       level="warning")
        except Exception as exc:
            render_error(exc)

    with st.expander("Or: I already added these leads to the real Approval Sheet myself", icon=":material/back_hand:"):
        st.caption(
            "**Use this when:** you approved leads directly in the real Box file, skipping the "
            "automated picking above. Select them here to record that they were sent."
        )
        try:
            _accumulated_for_manual = _cached_sheet_df(
                profile.accumulated_report_path, profile.accumulated_tab_name,
                os.path.getmtime(profile.accumulated_report_path))
            _blank_status_df = _accumulated_for_manual[
                _accumulated_for_manual[_STATUS_COLUMN].fillna("").astype(str).str.strip() == ""
            ]
        except Exception as exc:
            _blank_status_df = pd.DataFrame()
            render_error(exc)

        if _blank_status_df.empty:
            render_empty_state("No blank-Status leads available to mark.",
                               "Every lead in the Accumulated Report already has a Status.", icon="task_alt")
        else:
            _manual_email_col = _acc_fm.email
            # Keyed by row index, not email -- two leads can share the same
            # email, or (confirmed in real IBM APAC data) both have a blank
            # one, and email-keyed widget keys/dicts collapse those into one,
            # crashing with a duplicate Streamlit element key.
            manual_flags: dict[int, bool] = {}
            for idx, lead in _blank_status_df.iterrows():
                _raw_manual_email = lead.get(_manual_email_col, "")
                email = str(_raw_manual_email).strip() if pd.notna(_raw_manual_email) else ""
                label_text = email if email else f"(no email — row {idx + 2})"
                manual_flags[idx] = st.checkbox(f"Mark {label_text}", key=f"manual_{idx}")

            if st.button("Mark as added to Approval Sheet", key="mark_manual_button"):
                marked_indices = {idx for idx, flag in manual_flags.items() if flag}
                if not marked_indices:
                    render_problem("No leads checked — nothing to mark.", "Tick at least one **Mark ...** box above first.",
                                   level="warning")
                else:
                    set_status_by_row_index(
                        profile.accumulated_report_path, profile.accumulated_tab_name, _STATUS_COLUMN,
                        {idx: uploaded_to_approval_sheet_label(datetime.date.today()) for idx in marked_indices},
                    )
                    st.success(
                        f"Marked {len(marked_indices)} lead(s) as \"{_MANUAL_STATUS_PREFIX}\" — "
                        "they're no longer offered here."
                    )

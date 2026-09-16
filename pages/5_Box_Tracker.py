# pages/5_Box_Tracker.py
import datetime

import openpyxl
import pandas as pd
import streamlit as st

from core.app_settings import get_clients_dir
from core.box_tracker import (
    read_pacing_diffs, pick_leads_for_approval, sent_for_approval_label,
    cleared_for_upload_label, uploaded_accepted_label, uploaded_rejected_label,
    append_mirror_rows, set_pacing_delivered, add_lead_template_columns, read_lead_template_constants,
    project_code_for_cid, parse_amal_id, strip_country_suffix, campaign_type_for_cid,
    uploaded_to_approval_sheet_label,
)
from core.branding import configure_page
from core.excel_io import read_sheet_as_dataframe, append_leads, find_header_row, set_status_by_row_index
from core.models import resolve_field_mapping
from core.profile_store import list_profile_names, load_profile

_current_user = configure_page("Box Tracker")
st.title("📦 Box Tracker")

# This workflow is specific to IBM APAC's Box-hosted lead-approval
# tracker -- no other client runs this process, so the page is tied to
# that one client rather than offered as a generic multi-client picker.
_IBM_APAC_CLIENT_NAME = "IBM APAC Interactive Avenues Pvt Ltd"

_STATUS_COLUMN = "Status"
_APPROVAL_SHEET_TAB = "Approval Sheet"
_RESPONSE_DETAILS_TAB = "Response Details"
# The real Box file's Response Details tab has a blank row 1 (leftover
# title spacing) with the actual column headers in row 2.
_RESPONSE_DETAILS_HEADER_ROW = 2
# Fixed for every row -- Madison Logic is always the publisher for this
# client's uploads.
_RESPONSE_DETAILS_PUBLISHER_NAME = "Madison Logic"
_RESPONSE_DETAILS_SOURCE_SITE = "madisonlogic.com"
_PACING_TAB = "Pacing"
_SENT_STATUS_PREFIX = "Sent for Approval"
_MANUAL_STATUS_PREFIX = "Uploaded to Approval Sheet"
_CLEARED_STATUS_PREFIX = "Cleared for Upload"

if _IBM_APAC_CLIENT_NAME not in list_profile_names(get_clients_dir()):
    st.warning(f"Client \"{_IBM_APAC_CLIENT_NAME}\" isn't set up yet. Set it up on the Client Setup page first.")
    st.stop()

profile = load_profile(_IBM_APAC_CLIENT_NAME, get_clients_dir())
if not profile.box_tracker.enabled:
    st.warning("Box Tracker isn't enabled for this client yet. Enable it on the Client Setup page first.")
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
    "copy-paste step. Work through the 3 steps below in order."
)


st.subheader("1. Send leads for approval")
st.caption(
    "**Use this when:** you want the tool to pick leads for you, based on this week's Pacing "
    "numbers, and write them into the mirror's Approval Sheet automatically."
)
with st.expander("ℹ️ How this works"):
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
        accumulated_df = read_sheet_as_dataframe(profile.accumulated_report_path, profile.accumulated_tab_name)
        diffs = read_pacing_diffs(profile.box_tracker.mirror_workbook_path, _PACING_TAB)
        picked_df, shortfall = pick_leads_for_approval(
            accumulated_df, _acc_fm.cid, _STATUS_COLUMN,
            profile.box_tracker.cid_campaign_map, diffs, buffer=5,
            uncapped_campaigns=_pacing_skipped,
        )

        if picked_df.empty:
            st.warning("No blank-Status leads matched any mapped CID with a known Pacing Diff — nothing to send.")
            st.stop()

        today = datetime.date.today()
        status_label = sent_for_approval_label(today)
        date_label = today.strftime("%d-%b")

        # Mark Status in the Accumulated Report itself -- picked_df.index
        # holds the original 0-based row positions from accumulated_df
        # (pandas preserves index labels through boolean filtering/.head()),
        # and read_sheet_as_dataframe is a plain pd.read_excel with header
        # row 1, so worksheet row = index + 2.
        set_status_by_row_index(
            profile.accumulated_report_path, profile.accumulated_tab_name, _STATUS_COLUMN,
            {idx: status_label for idx in picked_df.index},
        )

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

        st.success(f"Sent {len(picked_df)} lead(s) for approval — see {_APPROVAL_SHEET_TAB} in the mirror workbook.")
        if _approval_unmatched:
            st.warning(
                f"⚠️ The {_APPROVAL_SHEET_TAB} tab has column(s) this tool doesn't fill in and left blank: "
                f"{', '.join(sorted(_approval_unmatched))}. If that's unexpected, the mirror workbook's real "
                "header text may not match what this page writes."
            )
        if shortfall:
            for cid, amount in shortfall.items():
                st.warning(f"CID {cid} was short by {amount} lead(s) — sent all that were available.")
    except Exception as exc:
        st.error(f"Error: {exc}")

with st.expander("✋ Or: I already added these leads to the real Approval Sheet myself"):
    st.caption(
        "**Use this when:** you approved leads directly in the real Box file, skipping the "
        "automated picking above. Select them here so step 2 below can find and pick them up."
    )
    try:
        _accumulated_for_manual = read_sheet_as_dataframe(
            profile.accumulated_report_path, profile.accumulated_tab_name)
        _blank_status_df = _accumulated_for_manual[
            _accumulated_for_manual[_STATUS_COLUMN].fillna("").astype(str).str.strip() == ""
        ]
    except Exception as exc:
        _blank_status_df = pd.DataFrame()
        st.error(f"Could not load Accumulated Report: {exc}")

    if _blank_status_df.empty:
        st.caption("No blank-Status leads available to mark.")
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
                st.warning("No leads checked — nothing to mark.")
            else:
                set_status_by_row_index(
                    profile.accumulated_report_path, profile.accumulated_tab_name, _STATUS_COLUMN,
                    {idx: uploaded_to_approval_sheet_label(datetime.date.today()) for idx in marked_indices},
                )
                st.success(
                    f"Marked {len(marked_indices)} lead(s) as \"{_MANUAL_STATUS_PREFIX}\" — "
                    "they'll show up in step 2 below."
                )

st.divider()
st.subheader("2. Write cleared leads to the Lead Template")
st.caption(
    "**Use this when:** the client has approved some or all leads from step 1 (either the "
    "automated or the manual path), and you're ready to prep them for portal upload."
)
with st.expander("ℹ️ How this works"):
    st.write(
        "The tool fills in micro_audience/Industry/AID/campaign_code/etc. and writes cleared leads "
        "into that CID's Lead Template file (routed by CID — see Client Setup). **Any existing leads "
        "already in that file are wiped first** — new leads always start fresh at row 2. You then "
        "upload them to the client portal by hand."
    )

try:
    _accumulated_for_clearing = read_sheet_as_dataframe(profile.accumulated_report_path, profile.accumulated_tab_name)
    _clearing_status = _accumulated_for_clearing[_STATUS_COLUMN].fillna("").astype(str)
    _clearance_mask = (
        _clearing_status.str.startswith(_SENT_STATUS_PREFIX)
        | _clearing_status.str.startswith(_MANUAL_STATUS_PREFIX)
    )
    _awaiting_clearance_df = _accumulated_for_clearing[_clearance_mask]
except Exception as exc:
    _awaiting_clearance_df = pd.DataFrame()
    st.error(f"Could not load Accumulated Report: {exc}")

if _awaiting_clearance_df.empty:
    st.caption(f"No leads currently marked \"{_SENT_STATUS_PREFIX}\" or \"{_MANUAL_STATUS_PREFIX}\".")
else:
    _clear_email_col = _acc_fm.email
    # Keyed by row index -- see the identical comment on manual_flags
    # above; email alone can't be trusted as a unique widget/dict key.
    clear_flags: dict[int, bool] = {}
    for idx, lead in _awaiting_clearance_df.iterrows():
        _raw_clear_email = lead.get(_clear_email_col, "")
        email = str(_raw_clear_email).strip() if pd.notna(_raw_clear_email) else ""
        label_text = email if email else f"(no email — row {idx + 2})"
        clear_flags[idx] = st.checkbox(f"Clear {label_text}", key=f"clear_{idx}")

    if st.button("Write cleared leads to Lead Template", key="write_lead_template_button"):
        try:
            cleared_indices = {idx for idx, flag in clear_flags.items() if flag}
            if not cleared_indices:
                st.warning("No leads checked — nothing to write.")
                st.stop()

            cleared_df = _awaiting_clearance_df.loc[sorted(cleared_indices)]

            # Group by the resolved TEMPLATE FILE, not by CID -- several
            # CIDs can route to the same Lead Template (e.g. IN LOB and
            # IN WXO share one file, see Client Setup). Grouping by CID
            # would write one CID's rows with clear_existing=True and then
            # wipe them out again writing the next CID into the same file.
            cleared_df = cleared_df.copy()
            cleared_df["_template_path"] = cleared_df[_acc_fm.cid].astype(str).map(
                profile.box_tracker.cid_lead_template_path.get)

            missing_template_cids: set[str] = set(
                cleared_df.loc[cleared_df["_template_path"].isna(), _acc_fm.cid].astype(str)
            )

            written_cids: list[str] = []
            written_indices: set[int] = set()
            unmatched_headers: set[str] = set()
            routed_df = cleared_df[cleared_df["_template_path"].notna()]
            for template_path, group in routed_df.groupby("_template_path"):
                group = group.drop(columns="_template_path")
                template_wb = openpyxl.load_workbook(template_path, read_only=True)
                sheet_name = template_wb.active.title
                template_wb.close()

                # Must read AID/NC_*/campaign_code BEFORE clear_existing wipes
                # the file's only source of those values (see
                # read_lead_template_constants) -- they're the same for
                # every row in this one file, never derived from the leadfile.
                template_constants = read_lead_template_constants(template_path, sheet_name)
                enriched_group = add_lead_template_columns(
                    group, _acc_fm.cid, template_constants=template_constants)

                expected = [v for v in [
                    _acc_fm.email, _acc_fm.first_name,
                    _acc_fm.last_name, _acc_fm.company,
                    _acc_fm.cid,
                ] if v]
                header_row = find_header_row(template_path, sheet_name, expected)
                unmatched_headers.update(append_leads(
                    template_path, sheet_name, enriched_group, _acc_fm,
                    datetime.date.today(), header_row=header_row, clear_existing=True,
                ))
                written_cids.extend(sorted(group[_acc_fm.cid].astype(str).unique()))
                written_indices.update(group.index)

            if written_indices:
                set_status_by_row_index(
                    profile.accumulated_report_path, profile.accumulated_tab_name, _STATUS_COLUMN,
                    {idx: cleared_for_upload_label(datetime.date.today()) for idx in written_indices},
                )
                st.success(
                    f"Wrote {len(written_indices)} lead(s) to their Lead Template(s) (CIDs: {', '.join(written_cids)}).")
            if unmatched_headers:
                st.warning(
                    "⚠️ These Lead Template columns had no matching Accumulated Report column and were left "
                    f"blank: {', '.join(sorted(unmatched_headers))}. If that data does exist under a different "
                    "column name, rename it (or the Lead Template's header) to something closer and re-run."
                )
            if missing_template_cids:
                st.warning(
                    f"No Lead Template path configured for CID(s): {', '.join(sorted(missing_template_cids))} "
                    "— those leads were left with their current Status and not written anywhere. "
                    "Add their template path in Client Setup and try again."
                )
        except Exception as exc:
            st.error(f"Error: {exc}")

st.divider()
st.subheader("3. Reconcile portal upload status")
st.caption(
    "**Use this when:** you've already pasted step 2's leads into the client portal by hand, "
    "and know which (if any) the portal rejected."
)
with st.expander("ℹ️ How this works"):
    st.write(
        "Check any leads the portal rejected, with a reason — they'll be moved to the Refund tab. "
        "Everything left unchecked is treated as accepted, logged to Response Details, and counted "
        "toward this week's Pacing Delivered total."
    )

try:
    _accumulated_df = read_sheet_as_dataframe(profile.accumulated_report_path, profile.accumulated_tab_name)
    _sent_df = _accumulated_df[
        _accumulated_df[_STATUS_COLUMN].astype(str).str.startswith(_CLEARED_STATUS_PREFIX)
    ]
except Exception as exc:
    _sent_df = pd.DataFrame()
    st.error(f"Could not load Accumulated Report: {exc}")

if _sent_df.empty:
    st.caption(f"No leads currently marked \"{_CLEARED_STATUS_PREFIX}\".")
else:
    _email_col = _acc_fm.email
    # Keyed by row index -- see the identical comment on manual_flags in
    # step 1; email alone can't be trusted as a unique widget/dict key.
    reject_flags: dict[int, bool] = {}
    reject_reasons: dict[int, str] = {}
    for idx, lead in _sent_df.iterrows():
        _raw_reject_email = lead.get(_email_col, "")
        email = str(_raw_reject_email).strip() if pd.notna(_raw_reject_email) else ""
        label_text = email if email else f"(no email — row {idx + 2})"
        col_check, col_reason = st.columns([1, 3])
        reject_flags[idx] = col_check.checkbox(
            f"Reject {label_text}", key=f"reject_{idx}", label_visibility="collapsed")
        reject_reasons[idx] = col_reason.text_input(
            "Reason", key=f"reject_reason_{idx}", label_visibility="collapsed",
            placeholder=f"Reason for rejecting {label_text} (required if rejected)")

    if st.button("Reconcile upload status", key="reconcile_upload_button"):
        try:
            rejected_indices = {idx for idx, flag in reject_flags.items() if flag}
            missing_reasons = [idx for idx in rejected_indices if not reject_reasons.get(idx, "").strip()]
            if missing_reasons:
                _missing_labels = [
                    str(_sent_df.loc[idx, _email_col] or "") or f"row {idx + 2}" for idx in missing_reasons]
                st.error(f"Missing rejection reason for: {', '.join(_missing_labels)}")
                st.stop()

            accepted_df = _sent_df[~_sent_df.index.isin(rejected_indices)]
            rejected_df = _sent_df[_sent_df.index.isin(rejected_indices)]
            today = datetime.date.today()

            if not rejected_df.empty:
                reasons = {idx: reject_reasons[idx] for idx in rejected_df.index}
                append_leads(
                    profile.accumulated_report_path, profile.refund_tab_name,
                    rejected_df, _acc_fm, today, reasons=reasons,
                )
                set_status_by_row_index(
                    profile.accumulated_report_path, profile.accumulated_tab_name, _STATUS_COLUMN,
                    {idx: uploaded_rejected_label(today) for idx in rejected_df.index},
                )

            if not accepted_df.empty:
                cid_to_campaign = profile.box_tracker.cid_campaign_map
                response_rows = []
                for _, lead in accepted_df.iterrows():
                    cid = str(lead.get(_acc_fm.cid, ""))
                    campaign = strip_country_suffix(cid_to_campaign.get(cid, ""))
                    response_rows.append({
                        "Publisher Name": _RESPONSE_DETAILS_PUBLISHER_NAME,
                        "source_site": _RESPONSE_DETAILS_SOURCE_SITE,
                        "Market": lead.get("Country", ""),
                        "Company": lead.get(_acc_fm.company, ""),
                        "UUCID": lead.get("2nd Asset OV Code", ""),
                        "Project Code": project_code_for_cid(cid, lead.get("Project Code", "")),
                        "Campaign Name": campaign,
                        "Segment": lead.get("Segment", ""),
                        "Job Title": lead.get("Job Title", ""),
                        "Contact Type": lead.get("Contact Type", ""),
                        "State": lead.get("State", ""),
                        "Campaign Type": campaign_type_for_cid(cid),
                        "Asset Title": lead.get("Asset Title", ""),
                        "Asset Link": lead.get("Asset Link", ""),
                        "Uploaded Date": today.strftime("%d-%b"),
                    })
                _response_unmatched = append_mirror_rows(
                    profile.box_tracker.mirror_workbook_path, _RESPONSE_DETAILS_TAB, response_rows,
                    header_row=_RESPONSE_DETAILS_HEADER_ROW,
                )
                set_status_by_row_index(
                    profile.accumulated_report_path, profile.accumulated_tab_name, _STATUS_COLUMN,
                    {idx: uploaded_accepted_label(today) for idx in accepted_df.index},
                )

                accepted_counts = accepted_df[_acc_fm.cid].astype(str).value_counts()
                for cid, count in accepted_counts.items():
                    campaign = cid_to_campaign.get(cid)
                    if campaign and campaign not in _pacing_skipped:
                        set_pacing_delivered(profile.box_tracker.mirror_workbook_path, campaign, int(count))
            else:
                _response_unmatched = []

            st.success(
                f"Reconciled: {len(accepted_df)} accepted (logged to {_RESPONSE_DETAILS_TAB}, Pacing updated), "
                f"{len(rejected_df)} rejected (moved to Refund)."
            )
            if _response_unmatched:
                st.warning(
                    f"⚠️ The {_RESPONSE_DETAILS_TAB} tab has column(s) this tool doesn't fill in and left "
                    f"blank: {', '.join(sorted(_response_unmatched))}. If that's unexpected, the mirror "
                    "workbook's real header text may not match what this page writes."
                )
        except Exception as exc:
            st.error(f"Error: {exc}")

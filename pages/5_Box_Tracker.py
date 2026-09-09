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
)
from core.branding import configure_page
from core.excel_io import read_sheet_as_dataframe, append_leads, find_header_row
from core.profile_store import list_profile_names, load_profile

_current_user = configure_page("Box Tracker")
st.title("📦 Box Tracker")
st.caption(
    "For Complex Account clients whose lead-approval process runs through a Box-hosted tracker "
    "workbook this app has no API access to. Every write here goes to a LOCAL MIRROR workbook — "
    "you copy the results into the real Box file by hand."
)

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
_CLEARED_STATUS_PREFIX = "Cleared for Upload"

profile_names = [
    name for name in list_profile_names(get_clients_dir())
    if load_profile(name, get_clients_dir()).box_tracker.enabled
]
if not profile_names:
    st.warning("No client has Box Tracker enabled yet. Set it up on the Client Setup page first.")
    st.stop()

client_name = st.selectbox("Client", profile_names)
profile = load_profile(client_name, get_clients_dir())
_pacing_skipped = set(profile.box_tracker.pacing_skipped_campaigns)


def _set_status_for_emails(email_col: str, emails: set[str], label: str) -> None:
    """Writes `label` into the Accumulated Report's Status column for every
    row whose email matches one in `emails` -- matching by email (not
    positional index) since this is called from steps that only have a
    DataFrame slice, not the original full-sheet row positions."""
    wb = openpyxl.load_workbook(profile.accumulated_report_path)
    ws = wb[profile.accumulated_tab_name]
    headers = [cell.value for cell in ws[1]]
    status_col = headers.index(_STATUS_COLUMN) + 1
    email_col_idx = headers.index(email_col) + 1
    for row in ws.iter_rows(min_row=2):
        if str(row[email_col_idx - 1].value or "") in emails:
            ws.cell(row=row[0].row, column=status_col, value=label)
    wb.save(profile.accumulated_report_path)


st.subheader("1. Pick leads and send for approval")
st.caption(
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
            accumulated_df, profile.field_mapping.cid, _STATUS_COLUMN,
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
        wb = openpyxl.load_workbook(profile.accumulated_report_path)
        ws = wb[profile.accumulated_tab_name]
        headers = [cell.value for cell in ws[1]]
        status_col = headers.index(_STATUS_COLUMN) + 1
        picked_indices = set(picked_df.index)
        for idx in picked_indices:
            ws.cell(row=idx + 2, column=status_col, value=status_label)
        wb.save(profile.accumulated_report_path)

        # Write the Approval Sheet mirror rows. Persona/Industry is the
        # campaign name; Project Code and AMAL ID normally pass through
        # from the leadfile's own columns, except for CIDs with a fixed
        # override (see project_code_for_cid/amal_id_for_cid) -- newly
        # live segments whose leadfile doesn't carry reliable values yet.
        # Approval is deliberately left blank -- the client fills it in.
        cid_to_campaign = profile.box_tracker.cid_campaign_map
        rows = []
        for _, lead in picked_df.iterrows():
            cid = str(lead.get(profile.field_mapping.cid, ""))
            rows.append({
                "Company Name": lead.get(profile.field_mapping.company, ""),
                "Segment": lead.get("Segment", ""),
                "Persona/Industry": strip_country_suffix(cid_to_campaign.get(cid, "")),
                "Project Code": project_code_for_cid(cid, lead.get("Project Code", "")),
                "Market": lead.get("Country", ""),
                "Job Title": lead.get("Job Title", ""),
                "AMAL ID": parse_amal_id(lead.get("AMAL ID", "")),
                "Date": date_label,
            })
        append_mirror_rows(profile.box_tracker.mirror_workbook_path, _APPROVAL_SHEET_TAB, rows)

        # Set Pacing's Delivered count per campaign, for leads actually
        # sent -- except campaigns still on the skip list.
        cid_to_campaign = profile.box_tracker.cid_campaign_map
        picked_counts = picked_df[profile.field_mapping.cid].astype(str).value_counts()
        for cid, count in picked_counts.items():
            campaign = cid_to_campaign.get(cid)
            if campaign and campaign not in _pacing_skipped:
                set_pacing_delivered(profile.box_tracker.mirror_workbook_path, campaign, int(count))

        st.success(f"Sent {len(picked_df)} lead(s) for approval — see {_APPROVAL_SHEET_TAB} in the mirror workbook.")
        if shortfall:
            for cid, amount in shortfall.items():
                st.warning(f"CID {cid} was short by {amount} lead(s) — sent all that were available.")
    except Exception as exc:
        st.error(f"Error: {exc}")

st.divider()
st.subheader("2. Write cleared leads to the Lead Template")
st.caption(
    "Once the client gives the green flag for some or all leads sent for approval: check which ones "
    "are cleared, and the tool fills in micro_audience/Industry/AID/campaign_code/etc. and writes them "
    "into that CID's Lead Template file (routed by CID — see Client Setup). **Any existing leads "
    "already in that file are wiped first** — new leads always start fresh at row 2. You then upload "
    "them to the client portal by hand."
)

_show_manual_leads = st.checkbox(
    "Also include leads not yet marked \"Sent for Approval\" "
    "(e.g. you added them to the real Approval Sheet yourself, skipping step 1)",
    key="show_manual_leads",
)

try:
    _accumulated_for_clearing = read_sheet_as_dataframe(profile.accumulated_report_path, profile.accumulated_tab_name)
    _clearing_status = _accumulated_for_clearing[_STATUS_COLUMN].fillna("").astype(str)
    _clearance_mask = _clearing_status.str.startswith(_SENT_STATUS_PREFIX)
    if _show_manual_leads:
        _clearance_mask = _clearance_mask | (_clearing_status.str.strip() == "")
    _awaiting_clearance_df = _accumulated_for_clearing[_clearance_mask]
except Exception as exc:
    _awaiting_clearance_df = pd.DataFrame()
    st.error(f"Could not load Accumulated Report: {exc}")

if _awaiting_clearance_df.empty:
    st.caption(f"No leads currently marked \"{_SENT_STATUS_PREFIX}\".")
else:
    _clear_email_col = profile.field_mapping.email
    clear_flags: dict[str, bool] = {}
    for _, lead in _awaiting_clearance_df.iterrows():
        email = str(lead.get(_clear_email_col, ""))
        clear_flags[email] = st.checkbox(f"Clear {email}", key=f"clear_{email}")

    if st.button("Write cleared leads to Lead Template", key="write_lead_template_button"):
        try:
            cleared_emails = {e for e, flag in clear_flags.items() if flag}
            if not cleared_emails:
                st.warning("No leads checked — nothing to write.")
                st.stop()

            cleared_df = _awaiting_clearance_df[
                _awaiting_clearance_df[_clear_email_col].astype(str).isin(cleared_emails)
            ]

            written_cids: list[str] = []
            written_emails: set[str] = set()
            missing_template_cids: set[str] = set()
            for cid, group in cleared_df.groupby(cleared_df[profile.field_mapping.cid].astype(str)):
                template_path = profile.box_tracker.cid_lead_template_path.get(cid)
                if not template_path:
                    missing_template_cids.add(cid)
                    continue
                template_wb = openpyxl.load_workbook(template_path, read_only=True)
                sheet_name = template_wb.active.title
                template_wb.close()

                # Must read AID/NC_*/campaign_code BEFORE clear_existing wipes
                # the file's only source of those values (see
                # read_lead_template_constants) -- they're the same for
                # every row in this one file, never derived from the leadfile.
                template_constants = read_lead_template_constants(template_path, sheet_name)
                enriched_group = add_lead_template_columns(
                    group, profile.field_mapping.cid, template_constants=template_constants)

                expected = [v for v in [
                    profile.field_mapping.email, profile.field_mapping.first_name,
                    profile.field_mapping.last_name, profile.field_mapping.company,
                    profile.field_mapping.cid,
                ] if v]
                header_row = find_header_row(template_path, sheet_name, expected)
                append_leads(
                    template_path, sheet_name, enriched_group, profile.field_mapping,
                    datetime.date.today(), header_row=header_row, clear_existing=True,
                )
                written_cids.append(cid)
                written_emails.update(group[_clear_email_col].astype(str))

            if written_emails:
                _set_status_for_emails(_clear_email_col, written_emails, cleared_for_upload_label(datetime.date.today()))
                st.success(
                    f"Wrote {len(written_emails)} lead(s) to their Lead Template(s) (CIDs: {', '.join(written_cids)}).")
            if missing_template_cids:
                st.warning(
                    f"No Lead Template path configured for CID(s): {', '.join(sorted(missing_template_cids))} "
                    "— those leads were left as \"Sent for Approval\" and not written anywhere. "
                    "Add their template path in Client Setup and try again."
                )
        except Exception as exc:
            st.error(f"Error: {exc}")

st.divider()
st.subheader("3. Reconcile portal upload status")
st.caption(
    "For leads already cleared and pasted into the Lead Template, then uploaded to the client "
    "portal by hand: check any that the portal rejected, with a reason. Everything left unchecked "
    "is treated as accepted."
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
    _email_col = profile.field_mapping.email
    reject_flags: dict[str, bool] = {}
    reject_reasons: dict[str, str] = {}
    for _, lead in _sent_df.iterrows():
        email = str(lead.get(_email_col, ""))
        col_check, col_reason = st.columns([1, 3])
        reject_flags[email] = col_check.checkbox(
            f"Reject {email}", key=f"reject_{email}", label_visibility="collapsed")
        reject_reasons[email] = col_reason.text_input(
            "Reason", key=f"reject_reason_{email}", label_visibility="collapsed",
            placeholder=f"Reason for rejecting {email} (required if rejected)")

    if st.button("Reconcile upload status", key="reconcile_upload_button"):
        try:
            rejected_emails = {e for e, flag in reject_flags.items() if flag}
            missing_reasons = [e for e in rejected_emails if not reject_reasons.get(e, "").strip()]
            if missing_reasons:
                st.error(f"Missing rejection reason for: {', '.join(missing_reasons)}")
                st.stop()

            accepted_df = _sent_df[~_sent_df[_email_col].astype(str).isin(rejected_emails)]
            rejected_df = _sent_df[_sent_df[_email_col].astype(str).isin(rejected_emails)]
            today = datetime.date.today()

            if not rejected_df.empty:
                reasons = {idx: reject_reasons[str(row[_email_col])] for idx, row in rejected_df.iterrows()}
                append_leads(
                    profile.accumulated_report_path, profile.refund_tab_name,
                    rejected_df, profile.field_mapping, today, reasons=reasons,
                )
                _set_status_for_emails(
                    _email_col, set(rejected_df[_email_col].astype(str)), uploaded_rejected_label(today))

            if not accepted_df.empty:
                cid_to_campaign = profile.box_tracker.cid_campaign_map
                response_rows = []
                for _, lead in accepted_df.iterrows():
                    cid = str(lead.get(profile.field_mapping.cid, ""))
                    campaign = strip_country_suffix(cid_to_campaign.get(cid, ""))
                    response_rows.append({
                        "Publisher Name": _RESPONSE_DETAILS_PUBLISHER_NAME,
                        "source_site": _RESPONSE_DETAILS_SOURCE_SITE,
                        "Market": lead.get("Country", ""),
                        "Company": lead.get(profile.field_mapping.company, ""),
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
                append_mirror_rows(
                    profile.box_tracker.mirror_workbook_path, _RESPONSE_DETAILS_TAB, response_rows,
                    header_row=_RESPONSE_DETAILS_HEADER_ROW,
                )
                _set_status_for_emails(
                    _email_col, set(accepted_df[_email_col].astype(str)), uploaded_accepted_label(today))

                accepted_counts = accepted_df[profile.field_mapping.cid].astype(str).value_counts()
                for cid, count in accepted_counts.items():
                    campaign = cid_to_campaign.get(cid)
                    if campaign and campaign not in _pacing_skipped:
                        set_pacing_delivered(profile.box_tracker.mirror_workbook_path, campaign, int(count))

            st.success(
                f"Reconciled: {len(accepted_df)} accepted (logged to {_RESPONSE_DETAILS_TAB}, Pacing updated), "
                f"{len(rejected_df)} rejected (moved to Refund)."
            )
        except Exception as exc:
            st.error(f"Error: {exc}")

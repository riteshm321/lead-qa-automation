# pages/8_Enhancio.py
import datetime
from collections import defaultdict

import pandas as pd
import streamlit as st

from core.app_settings import get_clients_dir, get_enhancio_client_id, get_jira_settings
from core.branding import configure_page
from core import enhancio_client
from core.enhancio_client import EnhancioError
from core.enhancio_sync import (
    rejection_reason_from_status_entry, load_pending_leads, save_pending_leads, remove_pending_leads,
    load_uploaded_emails, save_uploaded_emails, filter_already_uploaded, select_rows_for_test_mode,
    format_enhancio_field_value,
)
from core.excel_io import read_leadfile, append_leads
from core import jira_client
from core.jira_client import JiraError
from core.profile_store import list_profile_names, load_profile

_current_user = configure_page("Enhancio")
st.title("🔗 Enhancio")

_profile_names = [
    name for name in list_profile_names(get_clients_dir())
    if load_profile(name, get_clients_dir()).enhancio.enabled
]
if not _profile_names:
    st.warning("No client has Enhancio enabled yet. Set it up on the Client Setup page first.")
    st.stop()

client_name = st.selectbox("Client", _profile_names)
profile = load_profile(client_name, get_clients_dir())
_enhancio = profile.enhancio
_allocation_by_cid = {a.cid: a.allocation_uid for a in _enhancio.allocations}
# Enhancio's own mapping (set on Client Setup's Enhancio section) takes
# priority; falls back to the client's QA field_mapping so an
# already-configured client keeps working unchanged. This is what lets a
# client with no QA at all (e.g. uploaded straight to Enhancio) use this
# page without ever visiting Run Check first.
_leadfile_mapping = _enhancio.leadfile_field_mapping or profile.field_mapping


def _get_token() -> str:
    client_id = get_enhancio_client_id()
    if not client_id:
        st.error("No Enhancio Client ID configured — set one on the Settings page first.")
        st.stop()
    try:
        return enhancio_client.get_access_token(client_id)["access_token"]
    except EnhancioError as exc:
        st.error(f"Enhancio login failed: {exc}")
        st.stop()


st.divider()
st.subheader("1. Upload leads to Enhancio")
st.caption(
    "Uploads a client-verified leadfile straight to Enhancio's Lead Import API — each CID routes to its "
    "own allocation, per the mapping configured on Client Setup. A lead already uploaded before (by "
    "email) is skipped automatically, so re-uploading the same or an overlapping file is safe."
)

_test_mode = st.checkbox(
    "Test mode — upload only 1 lead per Enhancio allocation",
    help="Use this for a first-time check before uploading real volume. Several CIDs can share one "
         "allocation, so this touches each real allocation exactly once, not once per CID.",
)
_upload_file = st.file_uploader("Verified leadfile", type=["xlsx", "csv"], key="enhancio_upload_file")

if _upload_file:
    try:
        leads_df = read_leadfile(_upload_file)
    except Exception as exc:
        st.error(f"Could not read this file: {exc}")
        st.stop()

    if not _leadfile_mapping:
        st.error(
            "This client has no leadfile column mapping for Enhancio yet — set one under Client Setup's "
            "Enhancio section (Email/First Name/Last Name/Company/CID columns)."
        )
        st.stop()
    cid_column = _leadfile_mapping.cid
    if not cid_column or cid_column not in leads_df.columns:
        st.error(f"This client's CID column (\"{cid_column}\") isn't in the uploaded file.")
        st.stop()

    # Preview, before anything is actually sent, how many of these leads
    # were already uploaded before -- scoped per ALLOCATION (AID), not per
    # client, since the same lead can legitimately go to two different
    # allocations. Lets the user choose to re-send them anyway instead of
    # always silently skipping them.
    _dup_preview_count = 0
    for _cid, _group in leads_df.groupby(leads_df[cid_column].astype(str)):
        _allocation_uid = _allocation_by_cid.get(_cid)
        if _allocation_uid is None:
            continue
        _, _dup_group = filter_already_uploaded(
            _group, _leadfile_mapping.email, load_uploaded_emails(client_name, _allocation_uid))
        _dup_preview_count += len(_dup_group)
    _reupload_duplicates = False
    if _dup_preview_count:
        st.warning(f"{_dup_preview_count} lead(s) in this file were already uploaded to their allocation before.")
        _reupload_duplicates = st.checkbox(
            "Upload these already-uploaded leads again anyway", value=False,
            key="enhancio_reupload_duplicates",
            help="Leave unchecked to skip them as usual (recommended, avoids duplicate submissions to Enhancio).",
        )

    if st.button("Upload to Enhancio", type="primary"):
        _token = _get_token()

        results = []
        _newly_pending: dict[str, dict] = {}
        _newly_uploaded_emails_by_allocation: dict[str, set[str]] = defaultdict(set)

        _upload_df = leads_df

        if _test_mode:
            _send_df, _skipped_df = select_rows_for_test_mode(_upload_df, cid_column, _allocation_by_cid)
            for _, lead in _skipped_df.iterrows():
                _cid = str(lead[cid_column])
                results.append({
                    "CID": _cid, "Email": lead.get(_leadfile_mapping.email, ""),
                    "Result": f"⏭️ Skipped (test mode — allocation {_allocation_by_cid[_cid]} "
                              "already tested via another CID)",
                })
            # A CID with no allocation mapping at all is excluded from both
            # _send_df/_skipped_df above (test mode has nothing to do with
            # that) -- keep those rows in play so they still get the
            # correct "No Enhancio allocation mapped" error below, not
            # silently vanish.
            _unmapped_df = _upload_df[~_upload_df[cid_column].astype(str).isin(_allocation_by_cid)]
            _upload_df = pd.concat([_send_df, _unmapped_df])

        # Rows to actually send, grouped by allocation_uid rather than CID --
        # several CIDs commonly share one allocation, the Lead Import API
        # takes a whole batch of leads per allocation in one call rather
        # than one HTTP request per lead, and "already uploaded" is checked
        # per allocation too (see load_uploaded_emails).
        _df_by_allocation: dict[str, list] = defaultdict(list)
        for cid, group in _upload_df.groupby(_upload_df[cid_column].astype(str)):
            allocation_uid = _allocation_by_cid.get(cid)
            if allocation_uid is None:
                for _, lead in group.iterrows():
                    results.append({"CID": cid, "Email": lead.get(_leadfile_mapping.email, ""),
                                     "Result": "❌ No Enhancio allocation mapped for this CID"})
                continue
            _df_by_allocation[allocation_uid].append(group)

        for allocation_uid, groups in _df_by_allocation.items():
            allocation_df = pd.concat(groups)
            _already_uploaded = load_uploaded_emails(client_name, allocation_uid)
            _send_df, _dup_df = filter_already_uploaded(allocation_df, _leadfile_mapping.email, _already_uploaded)
            if _reupload_duplicates:
                _send_df = pd.concat([_send_df, _dup_df])
                _dup_df = _dup_df.iloc[0:0]
            for _, lead in _dup_df.iterrows():
                results.append({
                    "CID": lead.get(cid_column, ""), "Email": lead.get(_leadfile_mapping.email, ""),
                    "Result": "⏭️ Skipped (already uploaded to this allocation previously)",
                })
            if _send_df.empty:
                continue

            # Fixed values (confirmed once on Client Setup, per allocation --
            # a field like Company Size that's the same for every lead sent
            # to this allocation rather than read from the leadfile) applied
            # after the per-row mapping, so they always win if a field
            # somehow appears in both.
            _fixed_values = _enhancio.fixed_field_values.get(allocation_uid, {})
            lead_payloads = [
                {
                    **{
                        enhancio_field: format_enhancio_field_value(enhancio_field, lead.get(leadfile_col, ""))
                        for leadfile_col, enhancio_field in _enhancio.field_mapping.items()
                    },
                    **_fixed_values,
                }
                for _, lead in _send_df.iterrows()
            ]
            try:
                submitted = enhancio_client.import_leads(_token, allocation_uid, lead_payloads)
            except EnhancioError as exc:
                for _, lead in _send_df.iterrows():
                    results.append({"CID": lead.get(cid_column, ""), "Email": lead.get(_leadfile_mapping.email, ""),
                                     "Result": f"❌ {exc}"})
                continue
            for (_, lead), submitted_entry in zip(_send_df.iterrows(), submitted):
                cid = lead.get(cid_column, "")
                email = lead.get(_leadfile_mapping.email, "")
                lead_id = submitted_entry.get("leadId")
                status = submitted_entry.get("status", "")
                if lead_id:
                    # The original leadfile row, kept exactly as uploaded --
                    # reconcile has no other way to recover a lead's data
                    # once it writes to Accumulated/Refund later.
                    _newly_pending[str(lead_id)] = {col: lead.get(col, "") for col in leads_df.columns}
                    _newly_uploaded_emails_by_allocation[allocation_uid].add(str(email))
                    results.append({"CID": cid, "Email": email, "Result": f"✅ Lead ID {lead_id} ({status})"})
                else:
                    results.append({"CID": cid, "Email": email, "Result": f"❌ {status or 'Not submitted'}"})

        if _newly_pending:
            save_pending_leads(client_name, _newly_pending)
        for allocation_uid, emails in _newly_uploaded_emails_by_allocation.items():
            save_uploaded_emails(client_name, allocation_uid, emails)
        st.session_state["enhancio_upload_results"] = pd.DataFrame(results)

if st.session_state.get("enhancio_upload_results") is not None:
    _results_df = st.session_state["enhancio_upload_results"]
    _ok = int(_results_df["Result"].str.startswith("✅").sum())
    _failed = int(_results_df["Result"].str.startswith("❌").sum())
    _skipped = int(_results_df["Result"].str.startswith("⏭️").sum())
    _sum_col1, _sum_col2, _sum_col3 = st.columns(3)
    _sum_col1.metric("✅ Uploaded", _ok)
    _sum_col2.metric("❌ Failed", _failed)
    _sum_col3.metric("⏭️ Skipped", _skipped)
    st.dataframe(_results_df, hide_index=True)

st.divider()
st.subheader("2. Reconcile accepted/rejected leads")
st.caption(
    "Polls Enhancio for every lead uploaded in step 1 that hasn't been resolved yet, and writes accepted "
    "ones into the Accumulated tab and rejected ones into the Refund tab (with Enhancio's own reason) — "
    "matched by column header, same as any other lead write, with that day's date under Date and each "
    "lead's own CID from the leadfile it was uploaded from. A lead still mid-processing is left pending "
    "and checked again on the next sync; once written, it's never fetched or written again."
)

if st.button("Fetch decisions from Enhancio"):
    _token = _get_token()

    pending = load_pending_leads(client_name)
    accepted_rows, rejected_rows = [], []
    try:
        with st.spinner(f"Checking {len(pending)} pending lead(s)..."):
            status_entries = enhancio_client.get_lead_status(_token, list(pending.keys())) if pending else []
    except EnhancioError as exc:
        st.error(f"Error fetching lead status: {exc}")
        st.stop()

    status_by_id = {str(entry.get("leadId")): entry for entry in status_entries}
    for lead_id, row in pending.items():
        entry = status_by_id.get(lead_id)
        if entry is None:
            continue  # not returned yet -- still pending, check again next sync
        status = str(entry.get("status", "")).strip().lower()
        out_row = dict(row)
        out_row["_enhancio_lead_id"] = lead_id
        if status == "accepted":
            accepted_rows.append(out_row)
        elif status == "rejected":
            out_row["_reason"] = rejection_reason_from_status_entry(entry)
            rejected_rows.append(out_row)
        # any other status (e.g. still processing) is left pending

    st.session_state["enhancio_accepted_rows"] = accepted_rows
    st.session_state["enhancio_rejected_rows"] = rejected_rows

_accepted_rows = st.session_state.get("enhancio_accepted_rows", [])
_rejected_rows = st.session_state.get("enhancio_rejected_rows", [])

if _accepted_rows or _rejected_rows:
    st.info(f"{len(_accepted_rows)} newly accepted, {len(_rejected_rows)} newly rejected — not yet written.")
    if _accepted_rows:
        st.dataframe(pd.DataFrame(_accepted_rows).drop(columns=["_enhancio_lead_id"]), hide_index=True)
    if _rejected_rows:
        st.dataframe(pd.DataFrame(_rejected_rows).drop(columns=["_enhancio_lead_id"]), hide_index=True)

    if st.button("Write to Accumulated & Refund", type="primary"):
        if not _leadfile_mapping:
            st.error(
                "This client has no leadfile column mapping for Enhancio yet — set one under Client "
                "Setup's Enhancio section (Email/First Name/Last Name/Company/CID columns)."
            )
            st.stop()
        today = datetime.date.today()
        resolved_ids = []

        if _accepted_rows:
            accepted_df = pd.DataFrame(_accepted_rows)
            resolved_ids += list(accepted_df.pop("_enhancio_lead_id"))
            append_leads(
                profile.accumulated_report_path, profile.accumulated_tab_name,
                accepted_df, _leadfile_mapping, today,
            )

        if _rejected_rows:
            rejected_df = pd.DataFrame(_rejected_rows)
            resolved_ids += list(rejected_df.pop("_enhancio_lead_id"))
            reasons = dict(zip(rejected_df.index, rejected_df.pop("_reason")))
            append_leads(
                profile.accumulated_report_path, profile.refund_tab_name,
                rejected_df, _leadfile_mapping, today, reasons=reasons,
            )

        remove_pending_leads(client_name, resolved_ids)
        st.session_state["enhancio_reconcile_summary"] = {
            "client_name": client_name, "accepted": len(_accepted_rows), "rejected": len(_rejected_rows),
        }
        st.session_state["enhancio_accepted_rows"] = []
        st.session_state["enhancio_rejected_rows"] = []
        st.success(f"Wrote {len(_accepted_rows)} accepted lead(s) and {len(_rejected_rows)} rejected lead(s).")
        st.rerun()
elif "enhancio_accepted_rows" in st.session_state:
    st.caption("No new decided leads since the last sync.")

st.divider()
st.subheader("Post to Jira")
if not profile.jira_ticket_key:
    st.caption("No Jira ticket configured for this client (set one up on Client Setup).")
else:
    st.caption("Nothing is sent until you click Post below — review (and edit) first.")

    _upload_results_df = st.session_state.get("enhancio_upload_results")
    _reconcile_summary = st.session_state.get("enhancio_reconcile_summary")
    _summary_lines = []
    if _upload_results_df is not None:
        _ok_count = _upload_results_df["Result"].str.startswith("✅").sum()
        _summary_lines.append(f"Uploaded {len(_upload_results_df)} lead(s) to Enhancio ({_ok_count} succeeded).")
    if _reconcile_summary and _reconcile_summary["client_name"] == client_name:
        _summary_lines.append(
            f"Reconciled Enhancio decisions: {_reconcile_summary['accepted']} accepted, "
            f"{_reconcile_summary['rejected']} rejected (moved to Refund)."
        )
    _greeting = f"Hi {profile.jira_reporter_name}," if profile.jira_reporter_name else "Hi,"
    _default_opening = _greeting + "\n" + ("\n".join(_summary_lines) if _summary_lines else "")
    st.text_area("Message", _default_opening, key="enhancio_jira_message", height=120)

    st.caption("Optional attachment (uploaded after the comment posts):")
    _attachment_file = st.file_uploader("Attach a file", key="enhancio_jira_attachment")
    if _attachment_file is not None:
        st.session_state["enhancio_jira_attachment_bytes"] = _attachment_file.getvalue()
        st.session_state["enhancio_jira_attachment_name"] = _attachment_file.name

    if st.button(f"📋 Post to {jira_client.extract_ticket_key(profile.jira_ticket_key)}", key="enhancio_jira_post"):
        jira_settings = get_jira_settings()
        if not all([jira_settings["base_url"], jira_settings["email"], jira_settings["api_token"]]):
            st.error("Set up your Jira account (site URL, email, API token) in Client Setup first.")
        else:
            try:
                adf_body = jira_client.build_comment_body(opening_text=st.session_state["enhancio_jira_message"])
                jira_client.post_comment_body(
                    jira_settings["base_url"], jira_settings["email"], jira_settings["api_token"],
                    jira_client.extract_ticket_key(profile.jira_ticket_key), adf_body,
                )
                _att_bytes = st.session_state.get("enhancio_jira_attachment_bytes")
                _att_name = st.session_state.get("enhancio_jira_attachment_name")
                if _att_bytes is not None:
                    jira_client.upload_attachment(
                        jira_settings["base_url"], jira_settings["email"], jira_settings["api_token"],
                        jira_client.extract_ticket_key(profile.jira_ticket_key), _att_name, _att_bytes,
                    )
                st.success("Posted to Jira.")
            except JiraError as exc:
                st.error(f"Failed to post to Jira: {exc}")

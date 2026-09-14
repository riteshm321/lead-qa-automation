# pages/7_Convertr.py
import datetime

import pandas as pd
import streamlit as st

from core.app_settings import get_clients_dir, get_convertr_account_credentials, get_jira_settings
from core.branding import configure_page
from core import convertr_client
from core.convertr_client import ConvertrError
from core.convertr_sync import (
    rejection_reason_from_result, load_pending_leads, save_pending_leads, remove_pending_leads,
    select_rows_for_test_mode,
)
from core.excel_io import read_leadfile, append_leads
from core import jira_client
from core.jira_client import JiraError
from core.profile_store import list_profile_names, load_profile

_current_user = configure_page("Convertr")
st.title("🔗 Convertr")

_profile_names = [
    name for name in list_profile_names(get_clients_dir())
    if load_profile(name, get_clients_dir()).convertr.enabled
]
if not _profile_names:
    st.warning("No client has Convertr enabled yet. Set it up on the Client Setup page first.")
    st.stop()

client_name = st.selectbox("Client", _profile_names)
profile = load_profile(client_name, get_clients_dir())
_convertr = profile.convertr
_campaign_by_cid = {c.cid: c for c in _convertr.campaigns}

st.divider()
st.subheader("1. Upload leads to Convertr")
st.caption(
    "Uploads a client-verified leadfile straight to Convertr — each CID routes to its own campaign, "
    "per the mapping configured on Client Setup."
)

_test_mode = st.checkbox(
    "Test mode — upload only 1 lead per Convertr campaign (SID)",
    help="Use this for a first-time check before uploading real volume. Several CIDs can share one "
         "campaign, so this touches each real campaign exactly once, not once per CID.",
)
_upload_file = st.file_uploader("Verified leadfile", type=["xlsx", "csv"], key="convertr_upload_file")

if _upload_file:
    try:
        leads_df = read_leadfile(_upload_file)
    except Exception as exc:
        st.error(f"Could not read this file: {exc}")
        st.stop()

    cid_column = profile.field_mapping.cid if profile.field_mapping else None
    if not cid_column or cid_column not in leads_df.columns:
        st.error(f"This client's CID column (\"{cid_column}\") isn't in the uploaded file.")
        st.stop()

    if st.button("Upload to Convertr", type="primary"):
        _creds = get_convertr_account_credentials(client_name)
        if not _creds["username"] or not _creds["password"]:
            st.error("Save this client's Convertr account username/password on Client Setup first.")
            st.stop()
        try:
            with st.spinner("Logging in to Convertr..."):
                _token = convertr_client.login(_convertr.enterprise, _creds["username"], _creds["password"])["access_token"]
        except ConvertrError as exc:
            st.error(f"Login failed: {exc}")
            st.stop()

        results = []
        _newly_pending: dict[str, dict] = {}
        _upload_df = leads_df
        if _test_mode:
            _cid_to_campaign_id = {cid: m.campaign_id for cid, m in _campaign_by_cid.items()}
            _send_df, _skipped_df = select_rows_for_test_mode(leads_df, cid_column, _cid_to_campaign_id)
            for _, lead in _skipped_df.iterrows():
                _cid = str(lead[cid_column])
                results.append({
                    "CID": _cid, "Email": lead.get(profile.field_mapping.email, ""),
                    "Result": f"⏭️ Skipped (test mode — campaign {_cid_to_campaign_id[_cid]} "
                              "already tested via another CID)",
                })
            # A CID with no campaign mapping at all is excluded from both
            # _send_df/_skipped_df above (test mode has nothing to do with
            # that) -- keep those rows in play so they still get the
            # correct "No Convertr campaign mapped" error below, not
            # silently vanish.
            _unmapped_df = leads_df[~leads_df[cid_column].astype(str).isin(_cid_to_campaign_id)]
            _upload_df = pd.concat([_send_df, _unmapped_df])

        for cid, group in _upload_df.groupby(_upload_df[cid_column].astype(str)):
            mapping = _campaign_by_cid.get(cid)
            if mapping is None:
                for _, lead in group.iterrows():
                    results.append({"CID": cid, "Email": lead.get(profile.field_mapping.email, ""),
                                     "Result": "❌ No Convertr campaign mapped for this CID"})
                continue
            if not mapping.global_form_id:
                for _, lead in group.iterrows():
                    results.append({"CID": cid, "Email": lead.get(profile.field_mapping.email, ""),
                                     "Result": f"❌ No Form ID saved for campaign {mapping.campaign_id}"})
                continue

            for _, lead in group.iterrows():
                form_data = {
                    convertr_field: str(lead.get(leadfile_col, "") or "")
                    for leadfile_col, convertr_field in _convertr.field_mapping.items()
                }
                email = lead.get(profile.field_mapping.email, "")
                try:
                    response = convertr_client.submit_lead_as_publisher(
                        _convertr.enterprise, _token, _convertr.publisher_id, mapping.campaign_id,
                        mapping.global_form_id, form_data, link_id=mapping.campaign_link_id,
                    )
                    lead_id = str(response.get("data"))
                    # The original leadfile row, kept exactly as uploaded --
                    # a "valid" lead's own get_lead_result comes back with
                    # NO data at all, so this is the only reliable source
                    # for that lead's fields (CID included) once reconcile
                    # writes it to Accumulated/Refund.
                    _newly_pending[lead_id] = {col: lead.get(col, "") for col in leads_df.columns}
                    results.append({"CID": cid, "Email": email, "Result": f"✅ Lead ID {lead_id}"})
                except ConvertrError as exc:
                    results.append({"CID": cid, "Email": email, "Result": f"❌ {exc}"})

        if _newly_pending:
            save_pending_leads(client_name, _newly_pending)
        st.session_state["convertr_upload_results"] = pd.DataFrame(results)

if st.session_state.get("convertr_upload_results") is not None:
    _results_df = st.session_state["convertr_upload_results"]
    st.dataframe(_results_df, hide_index=True)
    _ok = _results_df["Result"].str.startswith("✅").sum()
    st.caption(f"{_ok} of {len(_results_df)} lead(s) uploaded successfully.")

st.divider()
st.subheader("2. Reconcile accepted/rejected leads")
st.caption(
    "Polls Convertr for every lead uploaded in step 1 that hasn't been resolved yet, and writes accepted "
    "ones into the Accumulated tab and rejected ones into the Refund tab (with Convertr's reason) — "
    "matched by column header, same as any other lead write, with that day's date under Date and each "
    "lead's own CID from the leadfile it was uploaded from. A lead still mid-QA is left pending and "
    "checked again on the next sync; once written, it's never fetched or written again."
)

if st.button("Fetch decisions from Convertr"):
    _creds = get_convertr_account_credentials(client_name)
    if not _creds["username"] or not _creds["password"]:
        st.error("Save this client's Convertr account username/password on Client Setup first.")
        st.stop()
    try:
        with st.spinner("Logging in to Convertr..."):
            _token = convertr_client.login(_convertr.enterprise, _creds["username"], _creds["password"])["access_token"]
    except ConvertrError as exc:
        st.error(f"Login failed: {exc}")
        st.stop()

    pending = load_pending_leads(client_name)
    accepted_rows, rejected_rows = [], []
    try:
        with st.spinner(f"Checking {len(pending)} pending lead(s)..."):
            for lead_id, row in pending.items():
                result = convertr_client.get_lead_result(_convertr.enterprise, _token, _convertr.publisher_id, lead_id)
                status = result["status"]
                if status == "pending":
                    continue
                out_row = dict(row)
                out_row["_convertr_lead_id"] = lead_id
                if status == "valid":
                    accepted_rows.append(out_row)
                else:
                    out_row["_reason"] = rejection_reason_from_result(result)
                    rejected_rows.append(out_row)
    except ConvertrError as exc:
        st.error(f"Error fetching lead results: {exc}")
        st.stop()

    st.session_state["convertr_accepted_rows"] = accepted_rows
    st.session_state["convertr_rejected_rows"] = rejected_rows

_accepted_rows = st.session_state.get("convertr_accepted_rows", [])
_rejected_rows = st.session_state.get("convertr_rejected_rows", [])

if _accepted_rows or _rejected_rows:
    st.info(f"{len(_accepted_rows)} newly accepted, {len(_rejected_rows)} newly rejected — not yet written.")
    if _accepted_rows:
        st.dataframe(pd.DataFrame(_accepted_rows).drop(columns=["_convertr_lead_id"]), hide_index=True)
    if _rejected_rows:
        st.dataframe(pd.DataFrame(_rejected_rows).drop(columns=["_convertr_lead_id"]), hide_index=True)

    if st.button("Write to Accumulated & Refund", type="primary"):
        today = datetime.date.today()
        resolved_ids = []

        if _accepted_rows:
            accepted_df = pd.DataFrame(_accepted_rows)
            resolved_ids += list(accepted_df.pop("_convertr_lead_id"))
            append_leads(
                profile.accumulated_report_path, profile.accumulated_tab_name,
                accepted_df, profile.field_mapping, today,
            )

        if _rejected_rows:
            rejected_df = pd.DataFrame(_rejected_rows)
            resolved_ids += list(rejected_df.pop("_convertr_lead_id"))
            reasons = dict(zip(rejected_df.index, rejected_df.pop("_reason")))
            append_leads(
                profile.accumulated_report_path, profile.refund_tab_name,
                rejected_df, profile.field_mapping, today, reasons=reasons,
            )

        remove_pending_leads(client_name, resolved_ids)
        st.session_state["convertr_reconcile_summary"] = {
            "client_name": client_name, "accepted": len(_accepted_rows), "rejected": len(_rejected_rows),
        }
        st.session_state["convertr_accepted_rows"] = []
        st.session_state["convertr_rejected_rows"] = []
        st.success(f"Wrote {len(_accepted_rows)} accepted lead(s) and {len(_rejected_rows)} rejected lead(s).")
        st.rerun()
elif "convertr_accepted_rows" in st.session_state:
    st.caption("No new decided leads since the last sync.")

st.divider()
st.subheader("Post to Jira")
if not profile.jira_ticket_key:
    st.caption("No Jira ticket configured for this client (set one up on Client Setup).")
else:
    st.caption("Nothing is sent until you click Post below — review (and edit) first.")

    _upload_results_df = st.session_state.get("convertr_upload_results")
    _reconcile_summary = st.session_state.get("convertr_reconcile_summary")
    _summary_lines = []
    if _upload_results_df is not None:
        _ok_count = _upload_results_df["Result"].str.startswith("✅").sum()
        _summary_lines.append(f"Uploaded {len(_upload_results_df)} lead(s) to Convertr ({_ok_count} succeeded).")
    if _reconcile_summary and _reconcile_summary["client_name"] == client_name:
        _summary_lines.append(
            f"Reconciled Convertr decisions: {_reconcile_summary['accepted']} accepted, "
            f"{_reconcile_summary['rejected']} rejected (moved to Refund)."
        )
    _greeting = f"Hi {profile.jira_reporter_name}," if profile.jira_reporter_name else "Hi,"
    _default_opening = _greeting + "\n" + ("\n".join(_summary_lines) if _summary_lines else "")
    st.text_area("Message", _default_opening, key="convertr_jira_message", height=120)

    st.caption("Optional attachment (uploaded after the comment posts):")
    _attachment_file = st.file_uploader("Attach a file", key="convertr_jira_attachment")
    if _attachment_file is not None:
        st.session_state["convertr_jira_attachment_bytes"] = _attachment_file.getvalue()
        st.session_state["convertr_jira_attachment_name"] = _attachment_file.name

    if st.button(f"📋 Post to {jira_client.extract_ticket_key(profile.jira_ticket_key)}", key="convertr_jira_post"):
        jira_settings = get_jira_settings()
        if not all([jira_settings["base_url"], jira_settings["email"], jira_settings["api_token"]]):
            st.error("Set up your Jira account (site URL, email, API token) in Client Setup first.")
        else:
            try:
                adf_body = jira_client.build_comment_body(opening_text=st.session_state["convertr_jira_message"])
                jira_client.post_comment_body(
                    jira_settings["base_url"], jira_settings["email"], jira_settings["api_token"],
                    jira_client.extract_ticket_key(profile.jira_ticket_key), adf_body,
                )
                _att_bytes = st.session_state.get("convertr_jira_attachment_bytes")
                _att_name = st.session_state.get("convertr_jira_attachment_name")
                if _att_bytes is not None:
                    jira_client.upload_attachment(
                        jira_settings["base_url"], jira_settings["email"], jira_settings["api_token"],
                        jira_client.extract_ticket_key(profile.jira_ticket_key), _att_name, _att_bytes,
                    )
                st.success("Posted to Jira.")
            except JiraError as exc:
                st.error(f"Failed to post to Jira: {exc}")

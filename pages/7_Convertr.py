# pages/7_Convertr.py
import datetime

import pandas as pd
import streamlit as st

from core.app_settings import get_clients_dir, get_convertr_api_key, get_convertr_account_credentials
from core.branding import configure_page
from core import convertr_client
from core.convertr_client import ConvertrError
from core.convertr_sync import (
    classify_lead, rejection_reason, lead_to_leadfile_row, load_synced_lead_ids, mark_leads_synced,
    save_email_to_cid_map, load_email_to_cid_map, cid_for_email,
)
from core.excel_io import read_leadfile, append_leads
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
    "Test mode — upload only 1 lead per CID",
    help="Use this for a first-time check before uploading real volume.",
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
        # Recorded for every lead in the file regardless of upload outcome
        # (or test-mode skipping) -- reconcile later looks up a returned
        # lead's CID by matching its email back to this, since Convertr's
        # own forms have no native place to carry CID through and echo it
        # back on their own.
        save_email_to_cid_map(
            client_name,
            dict(zip(leads_df[profile.field_mapping.email].astype(str), leads_df[cid_column].astype(str))),
        )

        results = []
        for cid, group in leads_df.groupby(leads_df[cid_column].astype(str)):
            mapping = _campaign_by_cid.get(cid)
            if mapping is None:
                for _, lead in group.iterrows():
                    results.append({"CID": cid, "Email": lead.get(profile.field_mapping.email, ""),
                                     "Result": "❌ No Convertr campaign mapped for this CID"})
                continue
            api_key = get_convertr_api_key(client_name, mapping.campaign_id)
            if not api_key:
                for _, lead in group.iterrows():
                    results.append({"CID": cid, "Email": lead.get(profile.field_mapping.email, ""),
                                     "Result": f"❌ No API key saved for campaign {mapping.campaign_id}"})
                continue
            if not mapping.global_form_id:
                for _, lead in group.iterrows():
                    results.append({"CID": cid, "Email": lead.get(profile.field_mapping.email, ""),
                                     "Result": f"❌ No Global Form ID saved for campaign {mapping.campaign_id}"})
                continue

            rows = group.head(1) if _test_mode else group
            for _, lead in rows.iterrows():
                form_data = {
                    convertr_field: str(lead.get(leadfile_col, "") or "")
                    for leadfile_col, convertr_field in _convertr.field_mapping.items()
                }
                email = lead.get(profile.field_mapping.email, "")
                try:
                    response = convertr_client.submit_lead(
                        _convertr.enterprise, mapping.campaign_id, mapping.global_form_id, api_key,
                        form_data, campaign_link_id=mapping.campaign_link_id, publisher_id=mapping.publisher_id,
                    )
                    results.append({"CID": cid, "Email": email, "Result": f"✅ Lead ID {response.get('data')}"})
                except ConvertrError as exc:
                    results.append({"CID": cid, "Email": email, "Result": f"❌ {exc}"})

        st.session_state["convertr_upload_results"] = pd.DataFrame(results)

if st.session_state.get("convertr_upload_results") is not None:
    _results_df = st.session_state["convertr_upload_results"]
    st.dataframe(_results_df, hide_index=True)
    _ok = _results_df["Result"].str.startswith("✅").sum()
    st.caption(f"{_ok} of {len(_results_df)} lead(s) uploaded successfully.")

st.divider()
st.subheader("2. Reconcile accepted/rejected leads")
st.caption(
    "Fetches each campaign's leads from Convertr, and writes accepted ones into the Accumulated tab and "
    "rejected ones into the Refund tab (with Convertr's reason) — matched by column header, same as any "
    "other lead write, with that day's date under Date and each lead's CID recovered by matching its "
    "email back to the leadfile uploaded in step 1. Only leads Convertr has actually decided on (not "
    "still mid-QA) are written; a lead already synced in a previous run is never written twice."
)

_unique_campaign_ids = sorted({c.campaign_id for c in _convertr.campaigns})

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

    reverse_field_mapping = {v: k for k, v in _convertr.field_mapping.items()}
    already_synced = load_synced_lead_ids(client_name)
    email_to_cid = load_email_to_cid_map(client_name)
    cid_column = profile.field_mapping.cid
    accepted_rows, rejected_rows = [], []
    try:
        with st.spinner("Fetching leads..."):
            for campaign_id in _unique_campaign_ids:
                page = 1
                while True:
                    body = convertr_client.get_leads(_convertr.enterprise, _token, campaign_id, page=page, items_per_page=100)
                    members = body.get("hydra:member", [])
                    for lead in members:
                        lead_id = str(lead.get("id"))
                        if lead_id in already_synced:
                            continue
                        status = classify_lead(lead)
                        if status == "pending":
                            continue
                        row = lead_to_leadfile_row(lead, reverse_field_mapping)
                        row[cid_column] = cid_for_email(lead.get("email", ""), email_to_cid)
                        row["_convertr_lead_id"] = lead_id
                        if status == "accepted":
                            accepted_rows.append(row)
                        else:
                            row["_reason"] = rejection_reason(lead)
                            rejected_rows.append(row)
                    if len(members) < 100:
                        break
                    page += 1
    except ConvertrError as exc:
        st.error(f"Error fetching leads: {exc}")
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
        synced_ids = []

        if _accepted_rows:
            accepted_df = pd.DataFrame(_accepted_rows)
            synced_ids += list(accepted_df.pop("_convertr_lead_id"))
            append_leads(
                profile.accumulated_report_path, profile.accumulated_tab_name,
                accepted_df, profile.field_mapping, today,
            )

        if _rejected_rows:
            rejected_df = pd.DataFrame(_rejected_rows)
            synced_ids += list(rejected_df.pop("_convertr_lead_id"))
            reasons = dict(zip(rejected_df.index, rejected_df.pop("_reason")))
            append_leads(
                profile.accumulated_report_path, profile.refund_tab_name,
                rejected_df, profile.field_mapping, today, reasons=reasons,
            )

        mark_leads_synced(client_name, synced_ids)
        st.session_state["convertr_accepted_rows"] = []
        st.session_state["convertr_rejected_rows"] = []
        st.success(f"Wrote {len(_accepted_rows)} accepted lead(s) and {len(_rejected_rows)} rejected lead(s).")
        st.rerun()
elif "convertr_accepted_rows" in st.session_state:
    st.caption("No new decided leads since the last sync.")

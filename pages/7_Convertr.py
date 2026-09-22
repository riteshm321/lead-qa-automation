# pages/7_Convertr.py
import datetime
import os

import pandas as pd
import requests
import streamlit as st

from core.app_settings import get_clients_dir, get_convertr_account_credentials, get_jira_settings
from core.branding import configure_page
from core import convertr_client
from core.convertr_client import ConvertrError
from core.convertr_sync import (
    rejection_reason_from_result, load_pending_leads, save_pending_leads, remove_pending_leads,
    load_uploaded_emails, save_uploaded_emails, filter_already_uploaded, select_rows_for_test_mode,
)
from core.errors import render_error
from core.excel_io import read_leadfile, append_leads, dataframe_to_excel_bytes
from core import jira_client
from core.jira_client import JiraError
from core.models import resolve_field_mapping
from core.profile_store import list_profile_names, load_profile
from core.toast import queue_toast_before_rerun, show_pending_toast

_current_user = configure_page("Convertr")
show_pending_toast()
st.title("🔗 Convertr")


@st.cache_data(show_spinner=False)
def _cached_profile_names(clients_dir: str, dir_mtime: float) -> list[str]:
    # mtime must NOT be underscore-prefixed -- Streamlit excludes any
    # leading-underscore parameter from the cache key hash. Same fix as
    # pages/2_Run_Check.py's _cached_profile_names.
    return list_profile_names(clients_dir)


@st.cache_data(show_spinner=False)
def _cached_load_profile(name: str, clients_dir: str, mtime: float):
    # See _cached_profile_names above for the mtime-not-underscored
    # reasoning. This page used to re-parse EVERY client profile in the
    # shared folder (to check .convertr.enabled) plus the selected
    # client's profile again, all uncached, on every single widget
    # interaction -- the same anti-pattern already fixed for Run Check/
    # Client Setup. Caching per-name+mtime (not the whole filtered list
    # by directory mtime) means a single profile's edit still invalidates
    # correctly even though the directory's own mtime only changes on
    # add/remove, not on an existing file being edited in place.
    return load_profile(name, clients_dir)


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


_clients_dir_now = get_clients_dir()
_profile_names = [
    name for name in _cached_profile_names(_clients_dir_now, _clients_dir_mtime(_clients_dir_now))
    if _cached_load_profile(name, _clients_dir_now, _profile_file_mtime(name, _clients_dir_now)).convertr.enabled
]
if not _profile_names:
    st.warning("No client has Convertr enabled yet. Set it up on the Client Setup page first.")
    st.stop()

client_name = st.selectbox("Client", _profile_names)
profile = _cached_load_profile(client_name, _clients_dir_now, _profile_file_mtime(client_name, _clients_dir_now))
_convertr = profile.convertr
_campaign_by_cid = {c.cid: c for c in _convertr.campaigns}
# Convertr's own mapping (set on Client Setup's Convertr section) takes
# priority; falls back to the client's QA field_mapping so an
# already-configured client keeps working unchanged. This is what lets a
# client with no QA at all (e.g. uploaded straight to Convertr) use this
# page without ever visiting Run Check first.
_leadfile_mapping = resolve_field_mapping(_convertr.leadfile_field_mapping, profile.field_mapping)

st.divider()
st.subheader("1. Upload leads to Convertr")
st.caption(
    "Uploads a client-verified leadfile straight to Convertr — each CID routes to its own campaign, "
    "per the mapping configured on Client Setup. A lead already uploaded before (by email) is skipped "
    "automatically, so re-uploading the same or an overlapping file is safe."
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
        render_error(exc)
        st.stop()

    if not _leadfile_mapping:
        st.error(
            "This client has no leadfile column mapping for Convertr yet — set one under Client Setup's "
            "Convertr section (Email/First Name/Last Name/Company/CID columns)."
        )
        st.stop()
    cid_column = _leadfile_mapping.cid
    if not cid_column or cid_column not in leads_df.columns:
        st.error(f"This client's CID column (\"{cid_column}\") isn't in the uploaded file.")
        st.stop()

    # Preview, before anything is actually sent, how many of these leads
    # were already uploaded to Convertr for THIS CLIENT before (scoped per
    # client, not per campaign) -- lets the user choose to re-send them
    # anyway instead of always silently skipping them.
    _, _dup_preview_df = filter_already_uploaded(
        leads_df, _leadfile_mapping.email, load_uploaded_emails(client_name))
    _reupload_duplicates = False
    if not _dup_preview_df.empty:
        st.warning(f"{len(_dup_preview_df)} lead(s) in this file were already uploaded to Convertr before.")
        _reupload_duplicates = st.checkbox(
            "Upload these already-uploaded leads again anyway", value=False,
            key="convertr_reupload_duplicates",
            help="Leave unchecked to skip them as usual (recommended, avoids duplicate submissions to Convertr).",
        )

    def _plan_sends(source_df: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], list[dict]]:
        """Exactly which leads would be sent for which CID, applying
        per-client dedup and test mode -- the single source of truth both
        the preview below and the actual "Upload to Convertr" button use,
        so they can never disagree about what's about to go out. Grouped
        by CID (not campaign_id), matching the leadfile's own routing key
        -- a campaign can be shared by more than one CID.
        Returns ({cid: send_df}, [skip/error result dicts]).
        """
        skip_results: list[dict] = []

        already_uploaded = load_uploaded_emails(client_name)
        upload_df, dup_df = filter_already_uploaded(source_df, _leadfile_mapping.email, already_uploaded)
        if _reupload_duplicates:
            upload_df = pd.concat([upload_df, dup_df])
            dup_df = dup_df.iloc[0:0]
        for _, lead in dup_df.iterrows():
            skip_results.append({
                "CID": lead.get(cid_column, ""), "Email": lead.get(_leadfile_mapping.email, ""),
                "Result": "⏭️ Skipped (already uploaded previously)",
            })

        if _test_mode:
            cid_to_campaign_id = {cid: m.campaign_id for cid, m in _campaign_by_cid.items()}
            send_df, skipped_df = select_rows_for_test_mode(upload_df, cid_column, cid_to_campaign_id)
            for _, lead in skipped_df.iterrows():
                _cid = str(lead[cid_column])
                skip_results.append({
                    "CID": _cid, "Email": lead.get(_leadfile_mapping.email, ""),
                    "Result": f"⏭️ Skipped (test mode — campaign {cid_to_campaign_id[_cid]} "
                              "already tested via another CID)",
                })
            # A CID with no campaign mapping at all is excluded from both
            # send_df/skipped_df above (test mode has nothing to do with
            # that) -- keep those rows in play so they still get the
            # correct "No Convertr campaign mapped" error below, not
            # silently vanish.
            unmapped_df = upload_df[~upload_df[cid_column].astype(str).isin(cid_to_campaign_id)]
            upload_df = pd.concat([send_df, unmapped_df])

        send_by_cid: dict[str, pd.DataFrame] = {}
        for cid, group in upload_df.groupby(upload_df[cid_column].astype(str)):
            mapping = _campaign_by_cid.get(cid)
            if mapping is None:
                for _, lead in group.iterrows():
                    skip_results.append({"CID": cid, "Email": lead.get(_leadfile_mapping.email, ""),
                                     "Result": "❌ No Convertr campaign mapped for this CID"})
                continue
            if not mapping.global_form_id:
                for _, lead in group.iterrows():
                    skip_results.append({"CID": cid, "Email": lead.get(_leadfile_mapping.email, ""),
                                     "Result": f"❌ No Form ID saved for campaign {mapping.campaign_id}"})
                continue
            send_by_cid[cid] = group

        return send_by_cid, skip_results

    _preview_send_by_cid, _preview_skip_results = _plan_sends(leads_df)
    with st.expander(
        f"📋 Preview leads to send ({sum(len(df) for df in _preview_send_by_cid.values())} lead(s) "
        f"across {len(_preview_send_by_cid)} CID(s))",
    ):
        st.caption(
            "The exact rows that will be sent if you click \"Upload to Convertr\" below right now — "
            "already reflects Test mode and any duplicate-skipping above. Nothing here has been sent yet."
        )
        if not _preview_send_by_cid:
            st.caption(
                "Nothing would be sent — every lead is either already uploaded, unmapped, or missing a Form ID.")
        else:
            for _cid, _df in _preview_send_by_cid.items():
                _mapping = _campaign_by_cid[_cid]
                st.write(f"**CID {_cid}** (campaign {_mapping.campaign_id}) — {len(_df)} lead(s)")
            _preview_combined = pd.concat(list(_preview_send_by_cid.values()))
            st.download_button(
                "⬇️ Download these leads (.xlsx)",
                dataframe_to_excel_bytes(_preview_combined, sheet_name="Leads to send"),
                file_name=f"convertr_preview_{client_name}.xlsx",
                key="convertr_preview_download",
            )

    if st.button("Upload to Convertr", type="primary"):
        _creds = get_convertr_account_credentials(client_name)
        if not _creds["username"] or not _creds["password"]:
            st.error("Save this client's Convertr account username/password on Client Setup first.")
            st.stop()
        try:
            with st.spinner("Logging in to Convertr..."):
                _token = convertr_client.login(_convertr.enterprise, _creds["username"], _creds["password"])["access_token"]
        except (ConvertrError, requests.exceptions.RequestException, KeyError) as exc:
            # Only ConvertrError was caught before -- a network hiccup
            # (requests.exceptions.RequestException, e.g. a timeout/DNS/
            # connection drop) or an unexpected response shape missing
            # "access_token" (KeyError) crashed the whole page with a raw
            # traceback instead of this same friendly, logged error.
            render_error(exc)
            st.stop()

        results = []

        _send_by_cid, _skip_results = _plan_sends(leads_df)
        results.extend(_skip_results)

        # A single live API call per lead with no progress indicator made a
        # batch of 50-100 leads look hung -- every other slow/multi-step
        # operation on this page (or Run Check's Finalize) already gives
        # some form of feedback while it works.
        _total_to_send = sum(len(group) for group in _send_by_cid.values())
        _send_progress = st.progress(0.0, text=f"Uploading 0 / {_total_to_send} lead(s) to Convertr...") \
            if _total_to_send else None
        _sent_so_far = 0

        for cid, group in _send_by_cid.items():
            mapping = _campaign_by_cid[cid]
            _cid_newly_pending: dict[str, dict] = {}
            _cid_newly_uploaded_emails: set[str] = set()
            for _, lead in group.iterrows():
                form_data = {
                    convertr_field: str(lead.get(leadfile_col, "") or "")
                    for leadfile_col, convertr_field in _convertr.field_mapping.items()
                }
                email = lead.get(_leadfile_mapping.email, "")
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
                    _cid_newly_pending[lead_id] = {col: lead.get(col, "") for col in leads_df.columns}
                    _cid_newly_uploaded_emails.add(str(email))
                    results.append({"CID": cid, "Email": email, "Result": f"✅ Lead ID {lead_id}"})
                except ConvertrError as exc:
                    results.append({"CID": cid, "Email": email, "Result": f"❌ {exc}"})
                _sent_so_far += 1
                if _send_progress is not None:
                    _send_progress.progress(
                        _sent_so_far / _total_to_send,
                        text=f"Uploading {_sent_so_far} / {_total_to_send} lead(s) to Convertr...")

            # Persist THIS cid group's results immediately, not batched to
            # the end of the whole multi-CID loop -- previously an
            # uncaught exception anywhere outside the per-lead try/except
            # (e.g. in the per-row form_data construction) could abort the
            # handler before the single end-of-loop save, discarding
            # tracking for every EARLIER CID group that had already
            # succeeded -- those leads exist at Convertr with real lead
            # IDs, but this tool would have no record they were ever sent,
            # so a retry would resend them as "new," creating real
            # duplicate leads.
            if _cid_newly_pending:
                save_pending_leads(client_name, _cid_newly_pending)
            if _cid_newly_uploaded_emails:
                save_uploaded_emails(client_name, _cid_newly_uploaded_emails)
        if _send_progress is not None:
            _send_progress.empty()

        st.session_state["convertr_upload_results"] = pd.DataFrame(results)

if st.session_state.get("convertr_upload_results") is not None:
    _results_df = st.session_state["convertr_upload_results"]
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
    except (ConvertrError, requests.exceptions.RequestException, KeyError) as exc:
        render_error(exc)
        st.stop()

    pending = load_pending_leads(client_name)
    accepted_rows, rejected_rows = [], []
    # Per-lead try/except -- this used to wrap the WHOLE loop in one
    # try/except, so a single pending lead that became permanently
    # unresolvable at Convertr (e.g. its campaign was deleted, or it
    # consistently errors) aborted the sync before any of the OTHER
    # already-decided pending leads (which could be many) got polled,
    # read, or written -- every future "Fetch decisions" click would hit
    # the same lead_id and re-abort, silently blocking reconciliation for
    # the whole client indefinitely. Matches the upload loop above, which
    # already isolated ConvertrError per lead.
    _lead_fetch_errors: list[str] = []
    with st.spinner(f"Checking {len(pending)} pending lead(s)..."):
        for lead_id, row in pending.items():
            try:
                result = convertr_client.get_lead_result(
                    _convertr.enterprise, _token, _convertr.publisher_id, lead_id)
            except ConvertrError as exc:
                _lead_fetch_errors.append(f"{lead_id}: {exc}")
                continue
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
    if _lead_fetch_errors:
        st.warning(
            f"{len(_lead_fetch_errors)} pending lead(s) couldn't be checked this sync and will be "
            "retried next time: " + "; ".join(_lead_fetch_errors)
        )

    st.session_state["convertr_accepted_rows"] = accepted_rows
    st.session_state["convertr_rejected_rows"] = rejected_rows
    st.session_state["convertr_decisions_client_name"] = client_name

# Scoped to the CURRENTLY selected client -- fetched decisions used to
# stay visible/writable after switching the Client dropdown, so a fetch
# for Client A followed by a switch to Client B before clicking "Write to
# Accumulated & Refund" silently wrote Client A's leads into Client B's
# Accumulated/Refund tabs (and cleared Client B's pending-leads store
# using Client A's lead ids). Mirrors the same client_name guard
# convertr_reconcile_summary already uses below.
if st.session_state.get("convertr_decisions_client_name") == client_name:
    _accepted_rows = st.session_state.get("convertr_accepted_rows", [])
    _rejected_rows = st.session_state.get("convertr_rejected_rows", [])
else:
    _accepted_rows, _rejected_rows = [], []

if _accepted_rows or _rejected_rows:
    st.info(f"{len(_accepted_rows)} newly accepted, {len(_rejected_rows)} newly rejected — not yet written.")
    if _accepted_rows:
        st.dataframe(pd.DataFrame(_accepted_rows).drop(columns=["_convertr_lead_id"]), hide_index=True)
    if _rejected_rows:
        st.dataframe(pd.DataFrame(_rejected_rows).drop(columns=["_convertr_lead_id"]), hide_index=True)

    if st.button("Write to Accumulated & Refund", type="primary"):
        if not _leadfile_mapping:
            st.error(
                "This client has no leadfile column mapping for Convertr yet — set one under Client "
                "Setup's Convertr section (Email/First Name/Last Name/Company/CID columns)."
            )
            st.stop()
        today = datetime.date.today()
        resolved_ids = []

        if _accepted_rows:
            accepted_df = pd.DataFrame(_accepted_rows)
            resolved_ids += list(accepted_df.pop("_convertr_lead_id"))
            append_leads(
                profile.accumulated_report_path, profile.accumulated_tab_name,
                accepted_df, _leadfile_mapping, today,
            )

        if _rejected_rows:
            rejected_df = pd.DataFrame(_rejected_rows)
            resolved_ids += list(rejected_df.pop("_convertr_lead_id"))
            reasons = dict(zip(rejected_df.index, rejected_df.pop("_reason")))
            append_leads(
                profile.accumulated_report_path, profile.refund_tab_name,
                rejected_df, _leadfile_mapping, today, reasons=reasons,
            )

        remove_pending_leads(client_name, resolved_ids)
        st.session_state["convertr_reconcile_summary"] = {
            "client_name": client_name, "accepted": len(_accepted_rows), "rejected": len(_rejected_rows),
        }
        st.session_state["convertr_accepted_rows"] = []
        st.session_state["convertr_rejected_rows"] = []
        queue_toast_before_rerun(
            f"Wrote {len(_accepted_rows)} accepted lead(s) and {len(_rejected_rows)} rejected lead(s).")
        st.rerun()
elif st.session_state.get("convertr_decisions_client_name") == client_name:
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
                _accumulated_href = (
                    profile.accumulated_report_link
                    or jira_client.path_to_link_href(profile.accumulated_report_path)
                )
                adf_body = jira_client.build_comment_body(
                    opening_text=st.session_state["convertr_jira_message"],
                    file_links=[("Accumulated File", _accumulated_href)],
                )
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

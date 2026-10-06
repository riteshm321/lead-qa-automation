# pages/8_Enhancio.py
import datetime
import os
from collections import defaultdict

import pandas as pd
import requests
import streamlit as st

from core.app_settings import get_clients_dir, get_enhancio_client_id, get_jira_settings
from core.box_tracker import (
    has_micro_audience_override, micro_audience_for_lead, has_asset_title_override, asset_title_for_lead,
    has_industry_override, industry_for_lead,
)
from core.branding import configure_page
from core import enhancio_client
from core.enhancio_client import EnhancioError
from core.errors import render_error, render_problem
from core.enhancio_sync import (
    rejection_reason_from_status_entry, load_pending_leads, load_pending_lead_batches, save_pending_leads,
    remove_pending_leads,
    load_uploaded_emails, save_uploaded_emails, remove_uploaded_emails, clear_uploaded_emails,
    filter_already_uploaded, select_rows_for_test_mode, format_enhancio_field_value, is_accepted_submission,
)
from core.failed_leads import (
    failed_leads_memory, failed_leads_source_df, load_failed_leads, make_failed_entry, pop_retry_request,
    render_failed_leads_section, update_failed_leads,
)
from core.excel_io import (
    read_leadfile, append_leads, dataframe_to_excel_bytes, normalize_header_text, find_passthrough_lead_column,
)
from core import jira_client
from core.jira_client import JiraError
from core.jira_summary import jira_greeting, jira_reporter_name, seed_message_default
from core.models import resolve_field_mapping
from core.profile_store import list_profile_names, load_profile
from core.toast import queue_toast_before_rerun, show_pending_toast
from core.ui_components import render_empty_state, render_metric_cards, render_status_strip, setup_state
from core.upload_batches import new_batch_id, render_fetch_scope

_current_user = configure_page("Enhancio")
show_pending_toast()
st.title(":material/link: Enhancio")


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
    # shared folder (to check .enhancio.enabled) plus the selected
    # client's profile again, all uncached, on every single widget
    # interaction -- the same anti-pattern already fixed for Run Check/
    # Client Setup/Convertr. Caching per-name+mtime (not the whole
    # filtered list by directory mtime) means a single profile's edit
    # still invalidates correctly even though the directory's own mtime
    # only changes on add/remove, not on an existing file being edited
    # in place.
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
    if _cached_load_profile(name, _clients_dir_now, _profile_file_mtime(name, _clients_dir_now)).enhancio.enabled
]
if not _profile_names:
    render_problem("No client has Enhancio enabled yet. Set it up on the Client Setup page first.",
                   "Tick **This client uploads to Enhancio** under Client Setup → Delivery.", level="warning")
    st.stop()

client_name = st.selectbox("Client", _profile_names, filter_mode=None)
# Per-client state not already scoped by client name: the keyed Jira
# message box (Streamlit ignores its per-client default once the key
# exists), a staged Jira attachment, and the last upload's results (which
# also feed the Jira message). Without this, switching the Client dropdown
# kept client A's message/attachment and Post sent them to client B's ticket.
_enhancio_previous_client = st.session_state.get("_enhancio_loaded_for")
st.session_state["_enhancio_loaded_for"] = client_name
if _enhancio_previous_client is not None and _enhancio_previous_client != client_name:
    for _stale_key in ("enhancio_jira_message", "enhancio_jira_attachment_bytes",
                       "enhancio_jira_attachment_name", "enhancio_upload_results"):
        st.session_state.pop(_stale_key, None)
profile = _cached_load_profile(client_name, _clients_dir_now, _profile_file_mtime(client_name, _clients_dir_now))
_enhancio = profile.enhancio
_allocation_by_cid = {a.cid: a.allocation_uid for a in _enhancio.allocations}
# Enhancio's own mapping (set on Client Setup's Enhancio section) takes
# priority; falls back to the client's QA field_mapping so an
# already-configured client keeps working unchanged. This is what lets a
# client with no QA at all (e.g. uploaded straight to Enhancio) use this page
# without ever visiting Run Check first.
_leadfile_mapping = resolve_field_mapping(_enhancio.leadfile_field_mapping, profile.field_mapping)
# What this client still needs before steps 1-2 can run -- readable at a
# glance instead of discovered from an error after clicking Upload.
render_status_strip([
    ("Allocations", setup_state(bool(_enhancio.allocations))),
    ("Field mapping", setup_state(bool(_enhancio.field_mapping))),
    ("Enhancio Client ID", setup_state(bool(get_enhancio_client_id()))),
    ("Jira ticket", setup_state(bool(profile.jira_ticket_key), required=False)),
])


def _get_token() -> str:
    client_id = get_enhancio_client_id()
    if not client_id:
        render_problem("No Enhancio Client ID configured - set one on the Settings page first.",
                       "It's under **Settings → Enhancio Client ID (private to this machine)**.")
        st.stop()
    try:
        return enhancio_client.get_access_token(client_id)["access_token"]
    except (EnhancioError, requests.exceptions.RequestException, KeyError) as exc:
        # Only EnhancioError was caught before -- a network hiccup
        # (requests.exceptions.RequestException, e.g. a timeout/DNS/
        # connection drop) or an unexpected response shape missing
        # "access_token" (KeyError) crashed the whole page with a raw
        # traceback instead of this same friendly, logged error.
        render_error(exc)
        st.stop()


def _load_already_uploaded_by_allocation(df: pd.DataFrame, cid_column: str) -> dict[str, set[str]]:
    """Already-uploaded emails for every allocation df's CIDs route to."""
    allocation_uids = sorted({
        _allocation_by_cid[_cid] for _cid in df[cid_column].astype(str).unique() if _cid in _allocation_by_cid
    })
    return {_uid: load_uploaded_emails(client_name, _uid) for _uid in allocation_uids}


def _plan_sends(
        source_df: pd.DataFrame, leadfile_mapping, test_mode: bool, reupload: bool,
        already_uploaded_by_allocation: dict[str, set[str]],
) -> tuple[dict[str, pd.DataFrame], list[dict], list]:
    """Exactly which leads would be sent to which allocation, applying
    test mode and per-allocation dedup -- the single source of truth
    both the preview below and the actual "Upload to Enhancio" button
    use, so they can never disagree about what's about to go out.
    Returns ({allocation_uid: send_df}, [skip/error result dicts],
    [failed-lead entries for core.failed_leads, one per "Failed" result]).
    """
    cid_column = leadfile_mapping.cid
    failed_entries: list = []
    skip_results: list[dict] = []
    upload_df = source_df

    if test_mode:
        send_df, skipped_df = select_rows_for_test_mode(
            upload_df, cid_column, _allocation_by_cid,
            email_column=leadfile_mapping.email,
            already_uploaded_by_allocation=already_uploaded_by_allocation,
        )
        for _, lead in skipped_df.iterrows():
            _cid = str(lead[cid_column])
            skip_results.append({
                "CID": _cid, "Email": lead.get(leadfile_mapping.email, ""),
                "Result": f"Skipped (test mode - allocation {_allocation_by_cid[_cid]} "
                          "already tested via another CID)",
            })
        # A CID with no allocation mapping at all is excluded from both
        # send_df/skipped_df above (test mode has nothing to do with
        # that) -- keep those rows in play so they still get the
        # correct "No Enhancio allocation mapped" error below, not
        # silently vanish.
        unmapped_df = upload_df[~upload_df[cid_column].astype(str).isin(_allocation_by_cid)]
        upload_df = pd.concat([send_df, unmapped_df])

    # Rows to actually send, grouped by allocation_uid rather than CID --
    # several CIDs commonly share one allocation, the Lead Import API
    # takes a whole batch of leads per allocation in one call rather
    # than one HTTP request per lead, and "already uploaded" is checked
    # per allocation too (see load_uploaded_emails).
    df_by_allocation: dict[str, list] = defaultdict(list)
    for cid, group in upload_df.groupby(upload_df[cid_column].astype(str)):
        allocation_uid = _allocation_by_cid.get(cid)
        if allocation_uid is None:
            for _, lead in group.iterrows():
                skip_results.append({"CID": cid, "Email": lead.get(leadfile_mapping.email, ""),
                                 "Result": "Failed - No Enhancio allocation mapped for this CID"})
                failed_entries.append(make_failed_entry(
                    lead.to_dict(), lead.get(leadfile_mapping.email, ""),
                    "No Enhancio allocation mapped for this CID"))
            continue
        df_by_allocation[allocation_uid].append(group)

    send_by_allocation: dict[str, pd.DataFrame] = {}
    for allocation_uid, groups in df_by_allocation.items():
        allocation_df = pd.concat(groups)
        already_uploaded = already_uploaded_by_allocation[allocation_uid]
        send_df, dup_df = filter_already_uploaded(allocation_df, leadfile_mapping.email, already_uploaded)
        if reupload:
            send_df = pd.concat([send_df, dup_df])
            dup_df = dup_df.iloc[0:0]
        for _, lead in dup_df.iterrows():
            skip_results.append({
                "CID": lead.get(cid_column, ""), "Email": lead.get(leadfile_mapping.email, ""),
                "Result": "Skipped (already uploaded to this allocation previously)",
            })
        if not send_df.empty:
            send_by_allocation[allocation_uid] = send_df

    return send_by_allocation, skip_results, failed_entries


def _upload_leads(
        source_df: pd.DataFrame, leadfile_mapping, test_mode: bool, reupload: bool,
) -> list[dict]:
    """Sends every lead _plan_sends picks, one batch per allocation, and
    records every outcome: a lead Enhancio genuinely accepted goes to the
    pending and already-uploaded stores (only then -- a failed lead must
    stay re-sendable), a failed one to the persistent failed-leads list
    with its full original row. Returns the per-lead results rows.
    Shared by "Upload to Enhancio" and "Retry failed leads".
    """
    cid_column = leadfile_mapping.cid
    _token = _get_token()

    results = []
    _newly_uploaded_emails_by_allocation: dict[str, set[str]] = defaultdict(set)
    # One batch id for everything this click sends, so "Fetch decisions"
    # can default to polling just this upload.
    _batch_id = new_batch_id()

    _send_by_allocation, _skip_results, _failed_entries = _plan_sends(
        source_df, leadfile_mapping, test_mode, reupload,
        _load_already_uploaded_by_allocation(source_df, cid_column))
    results.extend(_skip_results)
    # Leads skipped as already accepted are at Enhancio per this tool's
    # own record -- nothing left to retry for them.
    _succeeded_emails: set[str] = {
        str(r["Email"]) for r in _skip_results if r["Result"].startswith("Skipped (already uploaded")
    }

    # One live batch API call per allocation with no progress indicator
    # made a multi-allocation upload look hung -- every other slow/
    # multi-step operation on this page (or Run Check's Finalize)
    # already gives some form of feedback while it works.
    _total_allocations = len(_send_by_allocation)
    _send_progress = st.progress(0.0, text=f"Uploading allocation 0 / {_total_allocations}...") \
        if _total_allocations else None

    for _allocation_idx, (allocation_uid, _send_df) in enumerate(_send_by_allocation.items(), start=1):
        if _send_progress is not None:
            _send_progress.progress(
                (_allocation_idx - 1) / _total_allocations,
                text=f"Uploading allocation {_allocation_idx} / {_total_allocations} ({allocation_uid})...")
        # Fixed values (confirmed once on Client Setup, per allocation --
        # a field like Company Size that's the same for every lead sent
        # to this allocation rather than read from the leadfile) applied
        # after the per-row mapping, so they always win if a field
        # somehow appears in both.
        _fixed_values = _enhancio.fixed_field_values.get(allocation_uid, {})
        # field_mapping's leadfile-column side is configured once on
        # Client Setup, but a later export of the "same" leadfile can
        # cosmetically differ (a trailing "Job Title:" colon, "I AM A"
        # vs "I am a", "Zip Code" vs "Zip / Postal Code") -- an exact
        # key miss here silently sent Enhancio an empty string, which
        # it then rejected as a missing mandatory field even though the
        # leadfile actually had the data. Resolved once per allocation
        # (not per row -- column names don't vary row to row), same
        # normalized/synonym/fuzzy matching append_leads' passthrough
        # columns already get.
        _leadfile_headers_norm = {normalize_header_text(c): c for c in _send_df.columns}
        _resolved_source_col = {
            leadfile_col: leadfile_col if leadfile_col in _send_df.columns else (
                find_passthrough_lead_column(normalize_header_text(leadfile_col), _leadfile_headers_norm)
                or leadfile_col
            )
            for leadfile_col in _enhancio.field_mapping
        }
        lead_payloads = [
            {
                **{
                    enhancio_field: format_enhancio_field_value(
                        enhancio_field, lead.get(_resolved_source_col[leadfile_col], ""))
                    for leadfile_col, enhancio_field in _enhancio.field_mapping.items()
                },
                **_fixed_values,
            }
            for _, lead in _send_df.iterrows()
        ]
        try:
            _import_result = enhancio_client.import_leads(_token, allocation_uid, lead_payloads)
        except EnhancioError as exc:
            if exc.partial_result is not None:
                # A >1000-lead batch is chunked internally -- some
                # earlier chunk(s) already succeeded before a LATER
                # chunk failed. Use what actually went through instead
                # of discarding it and reporting every lead in this
                # allocation (including genuinely-accepted ones) as
                # failed -- see core.enhancio_client.EnhancioError.
                _import_result = {
                    "submitted": exc.partial_result.get("submitted", []),
                    "errors": exc.partial_result.get("errors", []),
                }
                render_problem(
                    f"Allocation {allocation_uid}: the import failed partway through this batch "
                    f"({exc}) -- leads already accepted before the failure are still recorded "
                    "below; leads after the failure point were never sent and should be retried.",
                    level="warning",
                )
            else:
                for _, lead in _send_df.iterrows():
                    results.append({
                        "CID": lead.get(cid_column, ""), "Email": lead.get(leadfile_mapping.email, ""),
                        "Result": f"Failed - {exc}"})
                    _failed_entries.append(make_failed_entry(
                        lead.to_dict(), lead.get(leadfile_mapping.email, ""), str(exc)))
                continue

        # A batch can accept some leads and reject others (e.g.
        # duplicates) in the SAME response -- Enhancio doesn't echo
        # back one outcome per lead sent, in order, so successes are
        # matched to leadfile rows by email rather than assumed to line
        # up positionally with what was sent.
        # Only an entry Enhancio genuinely took in (a real lead id, no
        # failure status) counts -- an echoed-back entry with e.g.
        # status "Rejected" and no lead id used to be recorded as
        # already uploaded, so a re-upload of the corrected file
        # skipped it and only the "upload again anyway" checkbox
        # (which also resends every accepted lead) could send it.
        _submitted_by_email = {
            str(entry.get("email", "")).strip().lower(): entry
            for entry in _import_result["submitted"]
            if entry.get("email") and is_accepted_submission(entry)
        }
        _not_accepted_status_by_email = {
            str(entry.get("email", "")).strip().lower(): str(entry.get("status") or "").strip()
            for entry in _import_result["submitted"]
            if isinstance(entry, dict) and entry.get("email") and not is_accepted_submission(entry)
        }
        _distinct_batch_errors = sorted({
            str(err.get("message", err)) if isinstance(err, dict) else str(err)
            for err in _import_result["errors"]
        })
        if _distinct_batch_errors:
            render_problem(
                f"Allocation {allocation_uid}: Enhancio reported {len(_distinct_batch_errors)} distinct "
                f"error reason(s) for leads it did not accept in this batch: "
                + "; ".join(_distinct_batch_errors),
                level="warning",
            )
        _allocation_newly_pending: dict[str, dict] = {}
        for _, lead in _send_df.iterrows():
            cid = lead.get(cid_column, "")
            email = lead.get(leadfile_mapping.email, "")
            submitted_entry = _submitted_by_email.get(str(email).strip().lower())
            if submitted_entry is not None:
                lead_id = submitted_entry.get("leadId")
                status = submitted_entry.get("status", "")
                # The original leadfile row, kept exactly as uploaded --
                # reconcile has no other way to recover a lead's data
                # once it writes to Accumulated/Refund later.
                _allocation_newly_pending[str(lead_id)] = {col: lead.get(col, "") for col in source_df.columns}
                _newly_uploaded_emails_by_allocation[allocation_uid].add(str(email))
                results.append({"CID": cid, "Email": email, "Result": f"Uploaded - Lead ID {lead_id} ({status})"})
                _succeeded_emails.add(str(email))
            else:
                _echoed_status = _not_accepted_status_by_email.get(str(email).strip().lower())
                _reason = (
                    "Not accepted by Enhancio"
                    + (f" (status: {_echoed_status})" if _echoed_status else "")
                    + (": " + "; ".join(_distinct_batch_errors) if _distinct_batch_errors else "")
                )
                results.append({"CID": cid, "Email": email, "Result": f"Failed - {_reason}"})
                _failed_entries.append(make_failed_entry(lead.to_dict(), email, _reason))

        # Persist THIS allocation's results immediately, not batched to
        # the end of the whole multi-allocation loop -- previously a
        # LATER allocation's failure (e.g. an uncaught exception in the
        # per-row matching logic) could abort the handler before the
        # single end-of-loop save, discarding tracking for every
        # EARLIER allocation that had already succeeded -- those leads
        # exist at Enhancio with real lead IDs, but this tool would
        # have no record they were ever sent, so a retry would resend
        # them as "new," creating real duplicate leads. Confirmed real
        # by the audit.
        if _allocation_newly_pending:
            save_pending_leads(client_name, _allocation_newly_pending, batch_id=_batch_id)
        if _newly_uploaded_emails_by_allocation[allocation_uid]:
            save_uploaded_emails(
                client_name, allocation_uid, _newly_uploaded_emails_by_allocation[allocation_uid])

    if _send_progress is not None:
        _send_progress.empty()

    update_failed_leads("enhancio", client_name, _failed_entries, _succeeded_emails,
                        memory=failed_leads_memory("enhancio"))
    return results


with st.container(border=True):
    st.subheader(":material/upload: 1. Upload leads to Enhancio")
    st.caption(
        "Uploads a client-verified leadfile straight to Enhancio's Lead Import API - each CID routes to its "
        "own allocation, per the mapping configured on Client Setup. A lead already uploaded before (by "
        "email) is skipped automatically, so re-uploading the same or an overlapping file is safe."
    )

    _test_mode = st.checkbox(
        "Test mode - upload only 1 lead per Enhancio allocation",
        help="Use this for a first-time check before uploading real volume. Several CIDs can share one "
             "allocation, so this touches each real allocation exactly once, not once per CID.",
    )

    leads_df = None
    _upload_file = st.file_uploader("Verified leadfile", type=["xlsx", "csv"], key="enhancio_upload_file")
    if _upload_file:
        try:
            leads_df = read_leadfile(_upload_file)
        except Exception as exc:
            render_error(exc)
            st.stop()

    if leads_df is not None:
        if not _leadfile_mapping:
            render_problem(
                "This client has no leadfile column mapping for Enhancio yet - set one under Client Setup's "
                "Enhancio section (Email/First Name/Last Name/Company/CID columns)."
            )
            st.stop()
        cid_column = _leadfile_mapping.cid
        if not cid_column or cid_column not in leads_df.columns:
            render_problem(f"This client's CID column (\"{cid_column}\") isn't in the uploaded file.",
                           "Check you uploaded the right file, or fix the CID column under Client Setup → "
                           "Delivery → Enhancio Upload.")
            st.stop()

        # A few CIDs need micro_audience computed per a fixed business rule
        # (or derived from LOB/the leadfile's own micro_audience column)
        # instead of a plain leadfile passthrough -- the exact same rule the
        # Box Tracker Lead Template already applies for these same CIDs (see
        # core.box_tracker.micro_audience_for_lead). Only rows whose CID is
        # actually covered by that rule are touched, so a different client's
        # own "micro_audience" column (if it happens to have one) is never
        # blanked out by this running for an unrelated CID.
        leads_df = leads_df.copy()
        _micro_audience_mask = leads_df[cid_column].astype(str).map(has_micro_audience_override)
        if _micro_audience_mask.any():
            # A leadfile column that's blank for every
            # covered row infers a strict numeric/string dtype that a plain
            # Python string can't be assigned into -- widen to plain object
            # first, same reasoning as core.box_tracker.add_lead_template_columns.
            leads_df["micro_audience"] = (
                leads_df["micro_audience"].astype(object) if "micro_audience" in leads_df.columns else ""
            )
            leads_df.loc[_micro_audience_mask, "micro_audience"] = leads_df.loc[_micro_audience_mask].apply(
                lambda row: micro_audience_for_lead(row[cid_column], row), axis=1)

        # Same reasoning, for the touch-specific asset_title rule -- see
        # core.box_tracker.asset_title_for_lead.
        _asset_title_mask = leads_df[cid_column].astype(str).map(has_asset_title_override)
        if _asset_title_mask.any():
            leads_df["asset_title"] = (
                leads_df["asset_title"].astype(object) if "asset_title" in leads_df.columns else ""
            )
            leads_df.loc[_asset_title_mask, "asset_title"] = leads_df.loc[_asset_title_mask].apply(
                lambda row: asset_title_for_lead(row[cid_column], row), axis=1)

        # Every known IBM APAC CID needs Industry forced to a fixed value on
        # Enhancio upload too -- the leadfile's own real Industry values (e.g.
        # "Professional Services") are rejected as "Invalid field value(s)"
        # since Enhancio only accepts its own registered picklist, not free
        # text. See core.box_tracker.has_industry_override.
        _industry_mask = leads_df[cid_column].astype(str).map(has_industry_override)
        if _industry_mask.any():
            leads_df["Industry"] = (
                leads_df["Industry"].astype(object) if "Industry" in leads_df.columns else ""
            )
            leads_df.loc[_industry_mask, "Industry"] = leads_df.loc[_industry_mask, cid_column].apply(
                industry_for_lead)

        # Every allocation this file's CIDs actually route to -- computed once
        # and reused below for the duplicate preview, test mode's per-allocation
        # slot selection, and the reset control, instead of re-reading each
        # allocation's already-uploaded-email memory from disk repeatedly.
        _file_allocation_uids = sorted({
            _allocation_by_cid[_cid] for _cid in leads_df[cid_column].astype(str).unique()
            if _cid in _allocation_by_cid
        })
        _already_uploaded_by_allocation = {
            _uid: load_uploaded_emails(client_name, _uid) for _uid in _file_allocation_uids
        }

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
                _group, _leadfile_mapping.email, _already_uploaded_by_allocation[_allocation_uid])
            _dup_preview_count += len(_dup_group)
        _reupload_duplicates = False
        if _dup_preview_count:
            render_problem(
                f"{_dup_preview_count} lead(s) in this file were already uploaded to (accepted by) their allocation "
                "before and will be skipped. Leads that failed before are never counted here - they're sent "
                "again automatically.",
                level="warning")
            _reupload_duplicates = st.checkbox(
                "Also resend the leads Enhancio already accepted", value=False,
                key="enhancio_reupload_duplicates",
                help="Leave unchecked to retry only what failed before (recommended - failed leads are never "
                     "remembered as uploaded, so they go out again on their own). Tick this only to deliberately "
                     "resend leads Enhancio already accepted; that creates duplicate submissions.",
            )

        with st.expander("Reset already-uploaded memory for an allocation"):
            st.caption(
                "Wipes this tool's own record of which leads it already sent to an allocation (does not touch "
                "anything in Enhancio itself). Use this if you deliberately want to re-send leads Enhancio "
                "already has, or if Test mode keeps skipping every CID for an allocation because the one lead "
                "it already tried was itself an already-uploaded lead."
            )
            for _uid in _file_allocation_uids:
                _count = len(_already_uploaded_by_allocation[_uid])
                _reset_col1, _reset_col2 = st.columns([3, 1])
                _reset_col1.write(f"**{_uid}** - {_count} email(s) remembered")
                if _reset_col2.button("Reset", key=f"enhancio_reset_{_uid}", disabled=_count == 0):
                    clear_uploaded_emails(client_name, _uid)
                    queue_toast_before_rerun(f"Cleared already-uploaded memory for allocation {_uid}.")
                    st.rerun()


        _preview_send_by_allocation, _preview_skip_results, _ = _plan_sends(
            leads_df, _leadfile_mapping, _test_mode, _reupload_duplicates, _already_uploaded_by_allocation)
        with st.expander(
            f"Preview leads to send ({sum(len(df) for df in _preview_send_by_allocation.values())} lead(s) "
            f"across {len(_preview_send_by_allocation)} allocation(s))",
            icon=":material/preview:",
        ):
            st.caption(
                "The exact rows that will be sent if you click \"Upload to Enhancio\" below right now - "
                "already reflects Test mode and any duplicate-skipping above. Nothing here has been sent yet."
            )
            if not _preview_send_by_allocation:
                render_empty_state("Nothing would be sent - every lead is either already uploaded or unmapped.",
                                   icon="block")
            else:
                for _uid, _df in _preview_send_by_allocation.items():
                    st.write(f"**Allocation {_uid}** - {len(_df)} lead(s)")
                _preview_combined = pd.concat([
                    _df.assign(**{"Enhancio Allocation": _uid}) for _uid, _df in _preview_send_by_allocation.items()
                ])
                st.download_button(
                    "Download these leads (.xlsx)",
                    dataframe_to_excel_bytes(_preview_combined, sheet_name="Leads to send"),
                    file_name=f"enhancio_preview_{client_name}.xlsx",
                    key="enhancio_preview_download",
                    icon=":material/download:",
                )

        if st.button("Upload to Enhancio", type="primary"):
            st.session_state["enhancio_upload_results"] = pd.DataFrame(_upload_leads(
                leads_df, _leadfile_mapping, _test_mode, _reupload_duplicates))

    if pop_retry_request("enhancio"):
        # Test mode is deliberately not applied -- a retry sends every
        # stored failed lead. Dedup still is, so a lead accepted since (e.g.
        # by a teammate) is skipped rather than resent.
        _retry_df = failed_leads_source_df(
            load_failed_leads("enhancio", client_name, failed_leads_memory("enhancio")))
        if not _retry_df.empty:
            if not _leadfile_mapping or not _leadfile_mapping.cid or not _leadfile_mapping.email \
                    or not {_leadfile_mapping.cid, _leadfile_mapping.email} <= set(_retry_df.columns):
                render_problem("The failed leads can't be retried: this client's Enhancio CID/Email columns aren't "
                               "in them.", "Download them, fix the file, and upload it instead.")
            else:
                _retry_results = _upload_leads(_retry_df, _leadfile_mapping, test_mode=False, reupload=False)
                if _retry_results:
                    st.session_state["enhancio_upload_results"] = pd.DataFrame(_retry_results)

    if st.session_state.get("enhancio_upload_results") is not None:
        _results_df = st.session_state["enhancio_upload_results"]
        _ok = int(_results_df["Result"].str.startswith("Uploaded").sum())
        _failed = int(_results_df["Result"].str.startswith("Failed").sum())
        _skipped = int(_results_df["Result"].str.startswith("Skipped").sum())
        render_metric_cards([
            ("Uploaded", _ok, "check_circle"),
            ("Failed", _failed, "error"),
            ("Skipped", _skipped, "skip_next"),
        ])
        st.dataframe(_results_df, hide_index=True)
        # Clears only this summary -- the failed-leads list below has its
        # own Clear button.
        st.button("Clear upload summary", key="enhancio_clear_summary", icon=":material/clear_all:",
                  on_click=lambda: st.session_state.pop("enhancio_upload_results", None))

    render_failed_leads_section("enhancio", "Enhancio", client_name)

with st.container(border=True):
    st.subheader(":material/sync: 2. Reconcile accepted/rejected leads")
    st.caption(
        "Polls Enhancio for the leads uploaded in step 1 that haven't been resolved yet (the latest upload by "
        "default), and writes accepted "
        "ones into the Accumulated tab and rejected ones into the Refund tab (with Enhancio's own reason) - "
        "matched by column header, same as any other lead write, with that day's date under Date and each "
        "lead's own CID from the leadfile it was uploaded from. A lead still mid-processing is left pending "
        "and checked again on the next sync; once written, it's never fetched or written again."
    )

    _lead_ids_to_fetch = render_fetch_scope("enhancio", load_pending_lead_batches(client_name))
    if st.button("Fetch decisions from Enhancio"):
        _token = _get_token()

        _all_pending = load_pending_leads(client_name)
        pending = {_id: _all_pending[_id] for _id in _lead_ids_to_fetch if _id in _all_pending}
        accepted_rows, rejected_rows = [], []
        try:
            with st.spinner(f"Checking {len(pending)} pending lead(s)..."):
                status_entries = enhancio_client.get_lead_status(_token, list(pending.keys())) if pending else []
        except EnhancioError as exc:
            render_problem(f"Error fetching lead status: {exc}",
                           "Nothing was written - click **Fetch decisions from Enhancio** again in a moment.")
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
        st.session_state["enhancio_decisions_client_name"] = client_name

    # Scoped to the CURRENTLY selected client -- fetched decisions used to
    # stay visible/writable after switching the Client dropdown, so a fetch
    # for Client A followed by a switch to Client B before clicking "Write to
    # Accumulated & Refund" silently wrote Client A's leads into Client B's
    # Accumulated/Refund tabs (and cleared Client B's pending-leads store
    # using Client A's lead ids). Mirrors the same client_name guard
    # enhancio_reconcile_summary already uses below.
    if st.session_state.get("enhancio_decisions_client_name") == client_name:
        _accepted_rows = st.session_state.get("enhancio_accepted_rows", [])
        _rejected_rows = st.session_state.get("enhancio_rejected_rows", [])
    else:
        _accepted_rows, _rejected_rows = [], []

    if _accepted_rows or _rejected_rows:
        st.info(f"{len(_accepted_rows)} newly accepted, {len(_rejected_rows)} newly rejected - not yet written.")
        if _accepted_rows:
            st.dataframe(pd.DataFrame(_accepted_rows).drop(columns=["_enhancio_lead_id"]), hide_index=True)
        if _rejected_rows:
            st.dataframe(pd.DataFrame(_rejected_rows).drop(columns=["_enhancio_lead_id"]), hide_index=True)

        if st.button("Write to Accumulated & Refund", type="primary"):
            if not _leadfile_mapping:
                render_problem(
                    "This client has no leadfile column mapping for Enhancio yet - set one under Client "
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
                # A rejected lead was only ever "submitted" to Enhancio (received
                # for evaluation), never actually accepted -- free its email back
                # up from the allocation's already-uploaded memory so the next
                # upload of the same file resends just this lead, not every
                # already-accepted lead alongside it (see remove_uploaded_emails).
                _rejected_emails_by_allocation: dict[str, set[str]] = defaultdict(set)
                for _, _row in rejected_df.iterrows():
                    _allocation_uid = _allocation_by_cid.get(str(_row.get(_leadfile_mapping.cid, "")))
                    _email = _row.get(_leadfile_mapping.email, "")
                    if _allocation_uid and _email:
                        _rejected_emails_by_allocation[_allocation_uid].add(str(_email))
                for _allocation_uid, _emails in _rejected_emails_by_allocation.items():
                    remove_uploaded_emails(client_name, _allocation_uid, _emails)

            remove_pending_leads(client_name, resolved_ids)
            st.session_state["enhancio_reconcile_summary"] = {
                "client_name": client_name, "accepted": len(_accepted_rows), "rejected": len(_rejected_rows),
            }
            st.session_state["enhancio_accepted_rows"] = []
            st.session_state["enhancio_rejected_rows"] = []
            queue_toast_before_rerun(
                f"Wrote {len(_accepted_rows)} accepted lead(s) and {len(_rejected_rows)} rejected lead(s).")
            st.rerun()
    elif st.session_state.get("enhancio_decisions_client_name") == client_name:
        st.caption("No new decided leads since the last sync.")

with st.container(border=True):
    st.subheader(":material/forum: Post to Jira")
    if not profile.jira_ticket_key:
        render_empty_state("No Jira ticket configured for this client (set one up on Client Setup).", icon="confirmation_number")
    else:
        st.caption("Nothing is sent until you click Post below - review (and edit) first.")

        _upload_results_df = st.session_state.get("enhancio_upload_results")
        _reconcile_summary = st.session_state.get("enhancio_reconcile_summary")
        _summary_lines = []
        if _upload_results_df is not None:
            _ok_count = _upload_results_df["Result"].str.startswith("Uploaded").sum()
            _summary_lines.append(f"Uploaded {len(_upload_results_df)} lead(s) to Enhancio ({_ok_count} succeeded).")
        if _reconcile_summary and _reconcile_summary["client_name"] == client_name:
            _summary_lines.append(
                f"Reconciled Enhancio decisions: {_reconcile_summary['accepted']} accepted, "
                f"{_reconcile_summary['rejected']} rejected (moved to Refund)."
            )
        _greeting = jira_greeting(jira_reporter_name(profile))
        _default_opening = _greeting + "\n" + ("\n".join(_summary_lines) if _summary_lines else "")
        seed_message_default("enhancio_jira_message", _default_opening)
        st.text_area("Message", key="enhancio_jira_message", height=120)

        st.caption("Optional attachment (uploaded after the comment posts):")
        _attachment_file = st.file_uploader("Attach a file", key="enhancio_jira_attachment")
        if _attachment_file is not None:
            st.session_state["enhancio_jira_attachment_bytes"] = _attachment_file.getvalue()
            st.session_state["enhancio_jira_attachment_name"] = _attachment_file.name

        if st.button(f"Post to {jira_client.extract_ticket_key(profile.jira_ticket_key)}", key="enhancio_jira_post",
                     icon=":material/send:"):
            jira_settings = get_jira_settings()
            if not all([jira_settings["base_url"], jira_settings["email"], jira_settings["api_token"]]):
                render_problem("Set up your Jira account (site URL, email, API token) on the Settings page first.",
                               "It's under **Settings → Jira account (private to this machine)**.")
            else:
                try:
                    _accumulated_href = (
                        profile.accumulated_report_link
                        or jira_client.path_to_link_href(profile.accumulated_report_path)
                    )
                    adf_body = jira_client.build_comment_body(
                        opening_text=st.session_state["enhancio_jira_message"],
                        file_links=[("Accumulated File", _accumulated_href)],
                    )
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
                    render_problem(f"Failed to post to Jira: {exc}",
                                   "Nothing else was affected - click **Post to ...** again once this is fixed.")

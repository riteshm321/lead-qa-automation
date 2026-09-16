import datetime
import json
import os
import re

import pandas as pd

from core.app_settings import get_shared_root_dir
from core.atomic_io import atomic_write_json

# Enhancio expects every date/timestamp value in this exact format -- the
# SAME format for every client, campaign, and allocation, never
# configurable per client. Matched by the ENHANCIO field label (e.g.
# "Created Timestamp"), not the leadfile's own column name (which varies
# per client) -- this is what lets a genuine date field always get
# reformatted while a CID/phone/zip that happens to contain digits is
# never touched.
_ENHANCIO_DATE_FORMAT = "%m-%d-%Y %H:%M:%S"
# IBM APAC's own Enhancio field is literally named "user_transaction_date"
# (matching their Lead Template's own placeholder convention) and,
# confirmed against a real rejected batch, needs YYYY-MM-DD HH:MM:SS
# specifically -- not the MM-DD-YYYY format every other client's
# date/timestamp field uses. Matched on the exact field name, not a
# per-client setting, since this is a fixed Enhancio schema fact for
# whichever allocations happen to use this exact field name.
_USER_TRANSACTION_DATE_FIELD = "user_transaction_date"
_USER_TRANSACTION_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_DATE_FIELD_LABEL_PATTERN = re.compile(r"date|timestamp", re.IGNORECASE)
# Excel's date epoch, as pandas/most libraries interpret Excel serial
# numbers (day 0 = 1899-12-30) -- reproduces Excel's own 1900-leap-year
# quirk, which is what makes this the correct origin to match Excel's
# actual serial values, not a plain "day 1 = 1900-01-01" scheme.
_EXCEL_DATE_ORIGIN = "1899-12-30"


def format_enhancio_field_value(enhancio_field: str, value) -> str:
    """Formats one lead field's value for Enhancio's Import Lead payload.

    A date/timestamp field is coerced to MM-DD-YYYY HH:MM:SS (or, for
    "user_transaction_date" specifically, YYYY-MM-DD HH:MM:SS) regardless
    of how the leadfile itself held it -- a real Excel date cell (read
    back as a datetime by pandas), a plain text string in some other
    format, or a bare Excel serial NUMBER (confirmed in a real leadfile --
    a date-valued cell with no actual date number format applied reads
    back as a plain int/float instead of a datetime; pd.to_datetime on a
    bare number otherwise assumes Unix-epoch nanoseconds and silently
    produces a bogus ~1970 date instead of the real one) -- since Enhancio
    expects one of these two fixed formats everywhere, not whatever the
    source file happened to use. Every other field is passed through as
    plain text, unparsed.
    """
    if _DATE_FIELD_LABEL_PATTERN.search(enhancio_field):
        if isinstance(value, (int, float)) and not isinstance(value, bool) and pd.notna(value):
            parsed = pd.to_datetime(value, unit="D", origin=_EXCEL_DATE_ORIGIN, errors="coerce")
        else:
            parsed = pd.to_datetime(value, errors="coerce")
        if pd.notna(parsed):
            date_format = (
                _USER_TRANSACTION_DATE_FORMAT if enhancio_field.strip().lower() == _USER_TRANSACTION_DATE_FIELD
                else _ENHANCIO_DATE_FORMAT
            )
            return parsed.strftime(date_format)
    return str(value or "")


def rejection_reason_from_status_entry(entry: dict) -> str:
    """Best-effort human-readable reason a lead was rejected, so Refund
    Reason is never left blank for one -- Enhancio's own comments field
    first (observed to carry the actual detail, e.g. "Lead validation
    failed: Duplicate lead within the campaign allocation"), else the
    terser rejectionReason (e.g. just "Lead Duplicate"), else a generic
    fallback.
    """
    comments = str(entry.get("comments") or "").strip()
    if comments:
        return comments
    reason = str(entry.get("rejectionReason") or "").strip()
    if reason:
        return reason
    return "Rejected by Enhancio"


def _normalize_email(email) -> str:
    return str(email or "").strip().lower()


def filter_already_uploaded(
    leads_df: pd.DataFrame, email_column: str, already_uploaded_emails: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Splits a leadfile into (rows_to_send, rows_already_uploaded) by
    email, so a repeated upload of the same (or an overlapping) file never
    resends a lead already submitted to Enhancio. Both preserve leads_df's
    own index.
    """
    is_duplicate = leads_df[email_column].astype(str).map(_normalize_email).isin(already_uploaded_emails)
    return leads_df[~is_duplicate], leads_df[is_duplicate]


def select_rows_for_test_mode(
    leads_df: pd.DataFrame, cid_column: str, cid_to_allocation_uid: dict[str, str],
    email_column: str | None = None,
    already_uploaded_by_allocation: dict[str, set[str]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """For the Upload page's test mode: exactly one row per unique Enhancio
    allocation, not one per CID -- several CIDs can share one allocation,
    and the point of a test run is to touch each real allocation exactly
    once, not once per CID.

    already_uploaded_by_allocation (allocation_uid -> already-uploaded
    emails, from load_uploaded_emails) lets the picked representative skip
    past a lead that was already uploaded to that allocation before. Such a
    lead gets filtered out later by filter_already_uploaded regardless, so
    picking it as the one test lead would leave the allocation with nothing
    actually sent this run -- while every OTHER CID sharing that allocation
    is still reported as "already tested", even though the allocation was
    never actually touched this time. That row is still returned in
    rows_to_send (so the later dedupe step reports it honestly as already
    uploaded) but doesn't use up the allocation's one slot, so the next CID
    for that allocation gets a real chance to be the test lead instead.

    Returns (rows_to_send, rows_skipped), both preserving leads_df's own
    index. A CID with no entry in cid_to_allocation_uid (no allocation
    mapped at all) is left out of both -- the caller reports that
    separately, it has nothing to do with test-mode's per-allocation
    limiting.
    """
    already_uploaded_by_allocation = already_uploaded_by_allocation or {}
    seen_allocation_uids: set[str] = set()
    send_indices, skip_indices = [], []
    for idx, cid in leads_df[cid_column].astype(str).items():
        allocation_uid = cid_to_allocation_uid.get(cid)
        if allocation_uid is None:
            continue
        if allocation_uid in seen_allocation_uids:
            skip_indices.append(idx)
            continue
        email = _normalize_email(leads_df.at[idx, email_column]) if email_column else ""
        if email and email in already_uploaded_by_allocation.get(allocation_uid, set()):
            send_indices.append(idx)
            continue
        seen_allocation_uids.add(allocation_uid)
        send_indices.append(idx)
    return leads_df.loc[send_indices], leads_df.loc[skip_indices]


def _pending_leads_path(client_name: str) -> str:
    root = get_shared_root_dir()
    return os.path.join(root, "enhancio_pending_leads", f"{client_name}.json") if root else ""


def load_pending_leads(client_name: str) -> dict[str, dict]:
    """Enhancio lead IDs uploaded but not yet resolved (or resolved but not
    yet written) for this client, across every teammate -- {lead_id: the
    full original leadfile row that was submitted for it}. Reconcile polls
    each of these ids via get_lead_status instead of pulling a whole
    allocation's leads back from Enhancio.
    """
    path = _pending_leads_path(client_name)
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _json_safe_value(value):
    # A row pulled from a re-read Excel sheet (see the Enhancio page's
    # "pull from Accumulated Report" mode) can carry a real pd.Timestamp/
    # datetime -- json.dump has no idea how to serialize those, and this
    # store's whole point is being safely written/re-read as JSON.
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if pd.isna(value):
        return ""
    return value


def save_pending_leads(client_name: str, lead_id_to_row: dict[str, dict]) -> None:
    path = _pending_leads_path(client_name)
    if not path:
        return
    existing = load_pending_leads(client_name)
    existing.update({
        str(lead_id): {col: _json_safe_value(value) for col, value in row.items()}
        for lead_id, row in lead_id_to_row.items()
    })
    atomic_write_json(path, existing)


def remove_pending_leads(client_name: str, lead_ids: list[str]) -> None:
    """Called once a pending lead's outcome has actually been written to
    Accumulated/Refund -- removing it here is what prevents a repeated sync
    from re-polling (and re-writing) the same lead.
    """
    path = _pending_leads_path(client_name)
    if not path:
        return
    existing = load_pending_leads(client_name)
    for lead_id in lead_ids:
        existing.pop(str(lead_id), None)
    atomic_write_json(path, existing)


def _uploaded_emails_path(client_name: str, allocation_uid: str) -> str:
    root = get_shared_root_dir()
    return (
        os.path.join(root, "enhancio_uploaded_emails", client_name, f"{allocation_uid}.json")
        if root else ""
    )


def load_uploaded_emails(client_name: str, allocation_uid: str) -> set[str]:
    """Every email successfully submitted to this ALLOCATION (AID) for this
    client, ever -- across every teammate, and kept even after a lead is
    later reconciled and removed from load_pending_leads. Scoped per
    allocation rather than per client: the same lead can legitimately be
    routed to two different allocations (e.g. two CIDs for the same client
    mapped to different allocations), and uploading it to one must not
    block uploading it to the other. This is what filter_already_uploaded
    checks a new upload against, so a repeated (or overlapping) leadfile
    never resends the same lead to the same allocation.
    """
    path = _uploaded_emails_path(client_name, allocation_uid)
    if not path or not os.path.isfile(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_uploaded_emails(client_name: str, allocation_uid: str, emails: set[str]) -> None:
    path = _uploaded_emails_path(client_name, allocation_uid)
    if not path:
        return
    existing = load_uploaded_emails(client_name, allocation_uid)
    existing.update(_normalize_email(e) for e in emails if _normalize_email(e))
    atomic_write_json(path, sorted(existing))


def clear_uploaded_emails(client_name: str, allocation_uid: str) -> None:
    """Wipes this allocation's already-uploaded-email memory, so the next
    upload treats every lead as new again -- for a deliberate re-test (test
    mode's one-lead-per-allocation slot is otherwise stuck on whatever was
    sent first) or to recover from a mismatch against Enhancio's own state.
    """
    path = _uploaded_emails_path(client_name, allocation_uid)
    if not path:
        return
    atomic_write_json(path, [])

"""Upload-batch tagging for the Convertr/Enhancio pending-leads stores.

Every lead accepted by one click of Upload (or Retry failed leads) is
tagged with the same timestamp-based batch id when it is saved as pending,
so "Fetch decisions" can poll just the most recent upload instead of every
pending lead the client has ever had. A lead saved before tagging existed
has no batch id and counts as an earlier upload.
"""
import datetime

import streamlit as st

# Reserved key stored inside each pending row on disk. The sync modules
# strip it on load, so it never reaches the Accumulated/Refund write.
BATCH_KEY = "_upload_batch"
_BATCH_ID_FORMAT = "%Y%m%dT%H%M%S%f"


def new_batch_id(now: datetime.datetime | None = None) -> str:
    """A batch id that sorts in upload order (plain string comparison)."""
    return (now or datetime.datetime.now()).strftime(_BATCH_ID_FORMAT)


def batch_display_time(batch_id: str) -> str:
    try:
        return datetime.datetime.strptime(batch_id, _BATCH_ID_FORMAT).strftime("%d %b %Y %H:%M")
    except ValueError:
        return batch_id


def tag_rows(lead_id_to_row: dict[str, dict], batch_id: str) -> dict[str, dict]:
    """Copies of the rows with the batch id added (untouched when blank)."""
    if not batch_id:
        return {lead_id: dict(row) for lead_id, row in lead_id_to_row.items()}
    return {lead_id: {**row, BATCH_KEY: batch_id} for lead_id, row in lead_id_to_row.items()}


def split_rows_and_batches(raw: dict[str, dict]) -> tuple[dict[str, dict], dict[str, str]]:
    """({lead_id: row without the batch key}, {lead_id: batch id or ""})."""
    rows: dict[str, dict] = {}
    batches: dict[str, str] = {}
    for lead_id, row in raw.items():
        rows[lead_id] = {col: value for col, value in row.items() if col != BATCH_KEY}
        batches[lead_id] = str(row.get(BATCH_KEY) or "")
    return rows, batches


def partition_by_latest_batch(lead_id_to_batch: dict[str, str]) -> tuple[str, list[str], list[str]]:
    """(latest batch id, its lead ids, every other lead id). Untagged leads
    are always "earlier"; with no tagged lead at all the latest id is ""."""
    latest = max((b for b in lead_id_to_batch.values() if b), default="")
    latest_ids = [lead_id for lead_id, b in lead_id_to_batch.items() if latest and b == latest]
    earlier_ids = [lead_id for lead_id, b in lead_id_to_batch.items() if not latest or b != latest]
    return latest, latest_ids, earlier_ids


def render_fetch_scope(key_prefix: str, lead_id_to_batch: dict[str, str]) -> list[str]:
    """Shown above a "Fetch decisions" button: which pending leads it will
    poll. Defaults to the latest upload's leads; a checkbox (only when
    there are any) adds the ones from earlier uploads. Returns the ids."""
    latest, latest_ids, earlier_ids = partition_by_latest_batch(lead_id_to_batch)
    if latest_ids:
        st.caption(f"Checking the latest upload: {len(latest_ids)} lead(s) "
                   f"(uploaded {batch_display_time(latest)}).")
    elif earlier_ids:
        st.caption("No pending leads from the latest upload.")
    else:
        st.caption("No pending leads to check.")
    include_earlier = bool(earlier_ids) and st.checkbox(
        f"Also check {len(earlier_ids)} pending lead(s) from earlier uploads",
        key=f"{key_prefix}_fetch_include_earlier",
    )
    return latest_ids + earlier_ids if include_earlier else latest_ids

"""Persistent per-client list of leads that failed to upload to a portal
(Convertr, Enhancio, Integrate) -- the full original leadfile row plus why
it failed, so a failure survives page navigation and app restarts instead
of living only in the transient upload results table.

Stored on disk under the shared root as
<root>/<portal>_failed_leads/<client>.json, next to the portals' own
pending/uploaded-email stores, as {key: entry} where key is the lead's
normalized email and entry is {"row": {...}, "reason": str, "meta": {...}}.
A `memory` dict (the page passes a st.session_state-backed one) mirrors it
and is the only store when no shared root is configured.
"""
import datetime
import hashlib
import json
import os

import pandas as pd
import streamlit as st

from core.app_settings import get_shared_root_dir
from core.atomic_io import atomic_write_json
from core.excel_io import dataframe_to_excel_bytes

FAILURE_REASON_COLUMN = "Failure reason"


def _normalize_email(email) -> str:
    if email is None or (isinstance(email, float) and pd.isna(email)):
        return ""
    return str(email).strip().lower()


def _json_safe_value(value):
    if isinstance(value, (pd.Timestamp, datetime.date, datetime.datetime)):
        return value.isoformat()
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):  # numpy scalar -> plain Python
        return value.item()
    return value


def make_failed_entry(row: dict, email, reason: str, meta: dict | None = None) -> tuple[str, dict]:
    """(key, entry) for one failed lead. A lead with no email can't be
    matched against a later success, so it's keyed by its own content."""
    safe_row = {str(col): _json_safe_value(value) for col, value in row.items() if col != FAILURE_REASON_COLUMN}
    key = _normalize_email(email)
    if not key:
        digest = hashlib.sha1(json.dumps(safe_row, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
        key = f"(no email) {digest}"
    return key, {"row": safe_row, "reason": str(reason), "meta": dict(meta or {})}


def _path(portal: str, client_name: str) -> str:
    root = get_shared_root_dir()
    return os.path.join(root, f"{portal}_failed_leads", f"{client_name}.json") if root else ""


def load_failed_leads(portal: str, client_name: str, memory: dict | None = None) -> dict[str, dict]:
    path = _path(portal, client_name)
    if path:
        entries = {}
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                entries = json.load(f)
        if memory is not None:
            memory[client_name] = entries
        return entries
    return dict((memory or {}).get(client_name, {}))


def _save(portal: str, client_name: str, entries: dict, memory: dict | None) -> None:
    if memory is not None:
        memory[client_name] = entries
    path = _path(portal, client_name)
    if path:
        atomic_write_json(path, entries)


def update_failed_leads(
    portal: str, client_name: str, failed: list[tuple[str, dict]], succeeded_emails: set[str],
    memory: dict | None = None,
) -> None:
    """New failures replace any stored entry for the same email; every
    email in succeeded_emails is dropped from the list."""
    if not failed and not succeeded_emails:
        return
    entries = load_failed_leads(portal, client_name, memory)
    for email in succeeded_emails:
        entries.pop(_normalize_email(email), None)
    for key, entry in failed:
        entries.pop(key, None)  # re-insert so the newest failures sort last
        entries[key] = entry
    _save(portal, client_name, entries, memory)


def clear_failed_leads(portal: str, client_name: str, memory: dict | None = None) -> None:
    _save(portal, client_name, {}, memory)


def _ordered_columns(entries: dict) -> list[str]:
    columns: list[str] = []
    for entry in entries.values():
        for col in entry["row"]:
            if col not in columns:
                columns.append(col)
    return columns


def failed_leads_source_df(entries: dict) -> pd.DataFrame:
    """The stored rows exactly as they were uploaded (no Failure reason),
    ready to send through the upload path again."""
    return pd.DataFrame([entry["row"] for entry in entries.values()], columns=_ordered_columns(entries))


def failed_leads_dataframe(entries: dict) -> pd.DataFrame:
    df = failed_leads_source_df(entries).fillna("")
    df[FAILURE_REASON_COLUMN] = [entry["reason"] for entry in entries.values()]
    return df


def failed_leads_memory(portal: str) -> dict:
    """This portal's session_state mirror of the failed-lead store."""
    return st.session_state.setdefault(f"{portal}_failed_leads", {})


def retry_flag_key(portal: str) -> str:
    return f"{portal}_retry_failed_requested"


def pop_retry_request(portal: str) -> bool:
    return bool(st.session_state.pop(retry_flag_key(portal), False))


def _request_retry(portal: str) -> None:
    st.session_state[retry_flag_key(portal)] = True


def render_failed_leads_section(portal: str, portal_label: str, client_name: str) -> None:
    """Count, table, .xlsx download, "Retry failed leads" (sets a flag the
    page acts on via pop_retry_request) and "Clear failed list"."""
    memory = failed_leads_memory(portal)
    entries = load_failed_leads(portal, client_name, memory)
    st.markdown("**:material/error: Failed leads**")
    if not entries:
        st.caption(f"No failed {portal_label} uploads are waiting for this client.")
        return
    df = failed_leads_dataframe(entries)
    st.caption(
        f"{len(df)} lead(s) failed to upload to {portal_label} for this client and haven't succeeded since. "
        "Kept until they upload successfully or you clear the list."
    )
    st.dataframe(df, hide_index=True)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button(
            "Download failed leads (.xlsx)",
            dataframe_to_excel_bytes(df, sheet_name="Failed leads"),
            file_name=f"{portal}_failed_leads_{client_name}.xlsx",
            key=f"{portal}_failed_leads_download",
            icon=":material/download:",
        )
    with col2:
        st.button(
            "Retry failed leads", key=f"{portal}_retry_failed", icon=":material/replay:",
            on_click=_request_retry, args=(portal,),
            help="Sends exactly these leads again (test mode is not applied).",
        )
    with col3:
        st.button(
            "Clear failed list", key=f"{portal}_clear_failed", icon=":material/delete_sweep:",
            on_click=clear_failed_leads, args=(portal, client_name, memory),
        )

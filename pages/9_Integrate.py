import os

import pandas as pd
import streamlit as st

from core.app_settings import get_clients_dir, get_integrate_credentials
from core.branding import configure_page
from core.errors import render_error, render_problem
from core.excel_io import read_leadfile
from core import integrate_client
from core.integrate_client import IntegrateError
from core.integrate_sync import filter_already_uploaded, load_uploaded_emails, save_uploaded_emails
from core.models import resolve_field_mapping
from core.profile_store import list_profile_names, load_profile
from core.ui_components import render_metric_cards, render_status_strip, setup_state

def _nan_safe_cell(value) -> str:
    # pd.notna, not `value or ""` -- a blank leadfile cell comes back as
    # float NaN, and NaN is truthy in Python, so `nan or ""` evaluates to
    # nan itself and str()'s to the literal text "nan" (same footgun
    # documented in core/complex_account.py's Customer Comments handling).
    return str(value).strip() if pd.notna(value) else ""


_current_user = configure_page("Integrate")
st.title(":material/link: Integrate")


@st.cache_data(show_spinner=False)
def _cached_profile_names(clients_dir: str, dir_mtime: float) -> list[str]:
    # mtime must NOT be underscore-prefixed -- Streamlit excludes any
    # leading-underscore parameter from the cache key hash. Same fix as
    # pages/7_Convertr.py's _cached_profile_names.
    return list_profile_names(clients_dir)


@st.cache_data(show_spinner=False)
def _cached_load_profile(name: str, clients_dir: str, mtime: float):
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
    if _cached_load_profile(name, _clients_dir_now, _profile_file_mtime(name, _clients_dir_now)).integrate.enabled
]
if not _profile_names:
    render_problem("No client has Integrate enabled yet. Set it up on the Client Setup page first.",
                   "Tick **This client uploads to Integrate** under Client Setup → Delivery.", level="warning")
    st.stop()

client_name = st.selectbox("Client", _profile_names, filter_mode=None)
# The last upload's results table isn't scoped by client -- clear it on a
# Client switch so client A's results never show under client B.
_integrate_previous_client = st.session_state.get("_integrate_loaded_for")
st.session_state["_integrate_loaded_for"] = client_name
if _integrate_previous_client is not None and _integrate_previous_client != client_name:
    st.session_state.pop("integrate_upload_results", None)
profile = _cached_load_profile(client_name, _clients_dir_now, _profile_file_mtime(client_name, _clients_dir_now))
_integrate = profile.integrate
_leadfile_mapping = resolve_field_mapping(_integrate.leadfile_field_mapping, profile.field_mapping)

_api_key, _api_secret = get_integrate_credentials()
# Rendered before the hard-stops below, so a half-configured client sees
# everything it's missing at once rather than one error per fix-and-reload.
render_status_strip([
    ("API credentials", setup_state(bool(_api_key and _api_secret))),
    ("Source ID", setup_state(bool(_integrate.sid))),
    ("Field mapping", setup_state(bool(_integrate.field_mapping))),
    ("Leadfile mapping", setup_state(bool(_leadfile_mapping and _leadfile_mapping.email))),
])
if not _api_key or not _api_secret:
    render_problem("Set the Integrate API Key/Secret on the Settings page first.",
                   "It's under **Settings → Integrate API credentials (private to this machine)**.")
    st.stop()
if not _integrate.sid:
    render_problem("This client has no Integrate Source ID (SID) saved — set one on Client Setup.",
                   "It's under **Client Setup → Delivery → Integrate Upload**.")
    st.stop()

with st.container(border=True):
    st.subheader(":material/upload: Upload leads to Integrate")
    st.caption(
        "Uploads a client-verified leadfile straight to this client's Integrate Source. A lead already "
        "uploaded before (by email) is skipped automatically, so re-uploading the same or an overlapping "
        "file is safe."
    )

    _test_mode = st.checkbox(
        "Test mode — upload only 1 lead", key="integrate_test_mode",
        help="Use this for a first-time check before uploading real volume.",
    )
    _upload_file = st.file_uploader("Verified leadfile", type=["xlsx", "csv"], key="integrate_upload_file")

    if _upload_file:
        try:
            leads_df = read_leadfile(_upload_file)
        except Exception as exc:
            render_error(exc)
            st.stop()

        if not _leadfile_mapping or not _leadfile_mapping.email:
            render_problem(
                "This client has no leadfile column mapping for Integrate yet — set one under Client "
                "Setup's Integrate section (at least the Email column)."
            )
            st.stop()
        email_column = _leadfile_mapping.email
        if email_column not in leads_df.columns:
            render_problem(f"This client's Email column (\"{email_column}\") isn't in the uploaded file.",
                           "Check you uploaded the right file, or fix the Email column under Client Setup → "
                           "Delivery → Integrate Upload.")
            st.stop()

        _already_uploaded = load_uploaded_emails(client_name)
        _send_df, _dup_df = filter_already_uploaded(leads_df, email_column, _already_uploaded)
        if not _dup_df.empty:
            render_problem(f"{len(_dup_df)} lead(s) in this file were already uploaded to Integrate before — skipped.",
                           level="warning")
        if _test_mode and len(_send_df) > 1:
            st.caption(f"Test mode: only the first lead of {len(_send_df)} will actually be sent.")
            _send_df = _send_df.iloc[:1]

        if not _integrate.field_mapping:
            render_problem(
                "This client has no Integrate field mapping configured yet — set one under Client Setup's "
                "Integrate section."
            )
            st.stop()

        # A mapped leadfile column that doesn't exist in THIS uploaded file
        # likely means a genuine leadfile/config mismatch (a renamed export
        # column, the wrong file, a stale mapping) -- surfaced immediately
        # rather than silently sending "" for it per lead, same reasoning as
        # the Email-column check above.
        _missing_mapped_columns = sorted(
            col for col in _integrate.field_mapping if col not in leads_df.columns
        )
        if _missing_mapped_columns:
            render_problem(
                "This client's Integrate field mapping references column(s) not present in the uploaded "
                "file: " + ", ".join(_missing_mapped_columns),
                "Rename the file's columns to match, or update the Integrate field mapping under Client Setup → "
                "Delivery → Integrate Upload.",
            )
            st.stop()

        if st.button("Upload to Integrate", type="primary"):
            results = []
            for _, lead in _dup_df.iterrows():
                results.append({"Email": lead.get(email_column, ""), "Result": "Skipped (already uploaded previously)"})

            _total_to_send = len(_send_df)
            _send_progress = st.progress(0.0, text=f"Uploading 0 / {_total_to_send} lead(s) to Integrate...") \
                if _total_to_send else None
            _sent_so_far = 0
            _newly_uploaded_emails: set[str] = set()

            for _, lead in _send_df.iterrows():
                attributes = {
                    integrate_attr: _nan_safe_cell(lead.get(leadfile_col, ""))
                    for leadfile_col, integrate_attr in _integrate.field_mapping.items()
                }
                attributes.update(_integrate.fixed_field_values)
                email = _nan_safe_cell(lead.get(email_column, ""))
                if not email:
                    # Skip BEFORE submit_lead/save_uploaded_emails -- a blank
                    # email that reached save_uploaded_emails used to
                    # normalize to the literal string "nan" and get saved to
                    # the dedup store, which then made every SUBSEQUENT
                    # blank-email row for this client match that same "nan"
                    # entry in filter_already_uploaded and get silently
                    # skipped as "already uploaded" forever. Surfacing it here
                    # instead keeps it visible in the results table.
                    results.append({"Email": email, "Result": "Failed — No email value for this row"})
                else:
                    try:
                        response = integrate_client.submit_lead(
                            _integrate.sid, _api_key, _api_secret, attributes, callback_url=_integrate.callback_url,
                        )
                        lead_id = str(response.get("id", ""))
                        results.append({"Email": email, "Result": f"Uploaded — Lead ID {lead_id}"})
                        # Saved per-lead, not batched to the end of the whole loop
                        # -- same reasoning as pages/7_Convertr.py's per-CID
                        # incremental save: an exception on a LATER lead must
                        # never discard an earlier, already-succeeded lead's
                        # dedup record.
                        save_uploaded_emails(client_name, {str(email)})
                    except IntegrateError as exc:
                        results.append({"Email": email, "Result": f"Failed — {exc}"})
                _sent_so_far += 1
                if _send_progress is not None:
                    _send_progress.progress(
                        _sent_so_far / _total_to_send,
                        text=f"Uploading {_sent_so_far} / {_total_to_send} lead(s) to Integrate...")
            if _send_progress is not None:
                _send_progress.empty()

            st.session_state["integrate_upload_results"] = pd.DataFrame(results)

    if st.session_state.get("integrate_upload_results") is not None:
        _results_df = st.session_state["integrate_upload_results"]
        _ok = int(_results_df["Result"].str.startswith("Uploaded").sum())
        _failed = int(_results_df["Result"].str.startswith("Failed").sum())
        _skipped = int(_results_df["Result"].str.startswith("Skipped").sum())
        render_metric_cards([
            ("Uploaded", _ok, "check_circle"),
            ("Failed", _failed, "error"),
            ("Skipped", _skipped, "skip_next"),
        ])
        st.dataframe(_results_df, hide_index=True)

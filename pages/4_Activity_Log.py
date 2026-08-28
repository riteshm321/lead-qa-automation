import pandas as pd
import streamlit as st

from core.activity_tracker import load_all_activity, get_user_stats, format_minutes
from core.branding import configure_page

_current_user = configure_page("Activity Log")
st.title("📊 Activity Log")

if not _current_user["is_admin"]:
    st.warning("This page is only available to admins.")
    st.stop()

st.caption(
    "Every completed client process (Finalize/Confirm & Write), across every user, with the real "
    "measured automated time -- the same data behind the sidebar's Time Saved card."
)

_activity = load_all_activity()
if not _activity:
    st.caption("No client processes completed yet.")
    st.stop()

_usernames = sorted(_activity.keys())
_selected_user = st.selectbox("Filter by user", ["All users"] + _usernames)

_rows = []
for _username, _record in _activity.items():
    if _selected_user != "All users" and _username != _selected_user:
        continue
    for _entry in _record.get("log", []):
        _timestamp = _entry.get("timestamp", "")
        _date, _, _time = _timestamp.partition("T")
        _automated = _entry.get("automated_minutes", 0.0)
        _manual = _entry.get("manual_minutes", 0.0)
        _rows.append({
            "User": _username,
            "Client": _entry.get("client", "—"),
            "Date": _date or "—",
            "Time": _time or "—",
            "Automated": format_minutes(_automated),
            "Manual": format_minutes(_manual),
            "Saved": format_minutes(_manual - _automated),
            "Complex Account": "Yes" if _entry.get("is_complex_account") else "",
            "_sort_key": _timestamp,
        })

st.subheader("Process log")
if not _rows:
    st.caption(
        "No logged processes yet for this filter -- processes completed before per-client logging "
        "existed won't have individual entries here (see the per-user totals below instead)."
    )
else:
    _log_df = pd.DataFrame(sorted(_rows, key=lambda r: r["_sort_key"], reverse=True)).drop(columns=["_sort_key"])
    st.dataframe(_log_df, hide_index=True, width="stretch")

st.divider()
st.subheader("Per-user totals")
for _username, _record in sorted(_activity.items()):
    if _selected_user != "All users" and _username != _selected_user:
        continue
    _stats = get_user_stats(_record)
    _count = _record.get("process_count", 0)
    st.markdown(
        f"**{_username}** — {_count} process(es), {format_minutes(_stats['total_saved_minutes'])} saved "
        f"(last: {_record.get('last_updated', '—')})"
    )
    st.caption(
        f"Avg {format_minutes(_stats['avg_automated_minutes'])}/process · "
        f"{_stats['plain_count']} Lead QA, {_stats['complex_account_count']} Complex Account · "
        f"{_stats['distinct_clients']} distinct client(s)"
    )

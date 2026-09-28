import pandas as pd
import streamlit as st

from core.activity_tracker import load_all_activity, get_user_stats, format_minutes
from core.branding import configure_page
from core.errors import render_problem
from core.ui_components import render_empty_state

_current_user = configure_page("Activity Log")
st.title(":material/bar_chart: Activity Log")

if not _current_user["is_admin"]:
    render_problem("This page is only available to admins.",
                   "Ask an admin to open it for you.", level="warning")
    st.stop()

st.caption(
    "Every completed client process (Finalize/Confirm & Write), across every user, with the real "
    "measured automated time -- the same data behind the sidebar's Time Saved card."
)

_activity = load_all_activity()
if not _activity:
    render_empty_state("No client processes completed yet.",
                       "Every successful Finalize/Confirm & Write on Run Check is logged here.", icon="history")
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

with st.container(border=True):
    st.subheader(":material/list_alt: Process log")
    if not _rows:
        render_empty_state(
            "No logged processes yet for this filter.",
            "Processes completed before per-client logging existed won't have individual entries here "
            "(see the per-user totals below instead).",
            icon="filter_list_off",
        )
    else:
        _log_df = pd.DataFrame(sorted(_rows, key=lambda r: r["_sort_key"], reverse=True)).drop(columns=["_sort_key"])
        st.dataframe(_log_df, hide_index=True, width="stretch")

with st.container(border=True):
    st.subheader(":material/groups: Per-user totals")
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

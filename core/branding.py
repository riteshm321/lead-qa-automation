import textwrap

import streamlit as st

from core import auth_gate
from core.activity_tracker import compute_time_saved_summary, format_minutes
from core.app_settings import get_shared_root_dir
from core.resources import resource_path

_LOGO_PATH = resource_path("assets/madison_logic_logo.svg")
# A separate, dedicated favicon file — the sidebar logo above is a wide
# wordmark (~3:1 aspect ratio) that reads fine at sidebar size but becomes an
# illegible smudge squeezed into a 16-32px browser tab icon.
_FAVICON_PATH = resource_path("assets/favicon.ico")


def configure_page(page_title: str) -> dict:
    """Call as the very first Streamlit command in every page script.

    Applies the app's branding consistently everywhere: browser tab
    icon/title, wide layout, the Madison Logic logo above the sidebar nav,
    a login gate, and a small developer credit card below it.
    set_page_config() must be the first Streamlit command a script makes,
    so every page calls this instead of st.set_page_config directly.

    Returns the logged-in user's {"username", "is_admin", "role"} -- pages
    that need to gate a section on admin access (e.g. Settings' user
    management panel) can use the return value instead of importing
    auth_gate.
    """
    st.set_page_config(page_title=page_title, page_icon=_FAVICON_PATH, layout="wide")
    st.logo(_LOGO_PATH, size="large")
    # The logo's own ink (dark indigo, close to the dark theme's own sidebar
    # color) has no separate light/reversed variant, so it reads fine on the
    # light theme's near-white sidebar but nearly vanishes against the dark
    # theme's own indigo-toned one. A small light backdrop behind it keeps it
    # legible in both — a standard treatment for a single-ink logo that isn't
    # dark-mode-safe on its own. Uses stSidebarLogo, Streamlit's own stable
    # test id for this element, so it isn't tied to generated CSS class names.
    st.markdown(
        """<style>
        [data-testid="stSidebarLogo"] {
            background-color: #FFFFFF;
            padding: 6px 10px;
            border-radius: 8px;
        }
        </style>""",
        unsafe_allow_html=True,
    )
    user = auth_gate.require_login()

    st.sidebar.divider()
    _render_time_saved_card()

    st.sidebar.divider()
    with st.sidebar.container(border=True):
        st.caption("Logged in as")
        st.markdown(f"👤 **{user['username']}**")
        st.markdown(f"💼 {user['role']}" if user.get("role") else "💼 Admin" if user["is_admin"] else "💼 User")
    if st.sidebar.button("Log out", key="_logout_button", use_container_width=True):
        auth_gate.logout()
        st.rerun()

    st.sidebar.divider()
    with st.sidebar.container(border=True):
        st.caption("Tool Made By")
        st.caption("👤 Ritesh Majumdar")
        st.caption("💼 Sr. Client Reporting Specialist")
    return user


@st.cache_data(ttl=30, show_spinner=False)
def _cached_time_saved_summary(shared_root: str) -> dict:
    # Reads every user's activity file from the shared OneDrive folder --
    # configure_page() runs at the top of every page, and Streamlit reruns
    # the whole script on every single widget interaction (not just page
    # navigation), so an uncached read here was hitting synced cloud
    # storage dozens of times per minute across the whole app. A 30s TTL
    # keeps the sidebar figure fresh without doing that on every click.
    # Keyed on shared_root (not a no-arg cache) so switching the shared
    # folder in Settings doesn't keep showing the old folder's numbers.
    return compute_time_saved_summary()


def _render_time_saved_card() -> None:
    summary = _cached_time_saved_summary(get_shared_root_dir())
    manual = format_minutes(summary["total_manual_minutes"])
    automated = format_minutes(summary["total_automated_minutes"])
    saved = format_minutes(summary["total_saved_minutes"])
    pct = round(summary["percent_saved"], 1)

    # Every line must start at column 0 -- Markdown treats a run of lines
    # indented 4+ spaces as a code block unless they're literally inside an
    # (equally unindented) <style>/<script>/<pre> tag, which the closing
    # </style> tag below ends; the <div> markup that follows it is regular
    # block content and would otherwise get swallowed into a code block and
    # rendered as literal text instead of real HTML.
    card_html = textwrap.dedent(f"""\
        <style>
        .ts-header {{ display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 0.95rem; }}
        .ts-header .ts-sub {{ font-weight: 400; opacity: 0.7; font-size: 0.8rem; }}
        .ts-count {{ margin: 6px 0 10px 0; font-size: 0.85rem; }}
        .ts-count strong {{ color: #4C6FFF; }}
        .ts-stats {{ display: flex; justify-content: space-between; gap: 4px; }}
        .ts-stat {{ flex: 1; text-align: center; }}
        .ts-stat-icon {{
            width: 30px; height: 30px; border-radius: 50%; display: flex;
            align-items: center; justify-content: center; margin: 0 auto 4px auto; font-size: 0.95rem;
        }}
        .ts-stat-label {{ font-size: 0.68rem; opacity: 0.7; line-height: 1.1; }}
        .ts-stat-value {{ font-weight: 700; font-size: 0.85rem; margin-top: 2px; }}
        .ts-blue-bg {{ background: rgba(76, 111, 255, 0.12); }} .ts-blue-fg {{ color: #4C6FFF; }}
        .ts-green-bg {{ background: rgba(34, 197, 94, 0.12); }} .ts-green-fg {{ color: #16A34A; }}
        .ts-purple-bg {{ background: rgba(147, 51, 234, 0.12); }} .ts-purple-fg {{ color: #9333EA; }}
        .ts-banner {{
            margin-top: 10px; padding: 6px 8px; border-radius: 6px; font-size: 0.72rem;
            background: rgba(34, 197, 94, 0.12); color: #16A34A; line-height: 1.3;
        }}
        </style>
        <div class="ts-header">⏱️ Time Saved <span class="ts-sub">(all users, till date)</span></div>
        <div class="ts-count"><strong>{summary['total_processes']}</strong> client process(es) completed</div>
        <div class="ts-stats">
        <div class="ts-stat">
        <div class="ts-stat-icon ts-blue-bg">🕐</div>
        <div class="ts-stat-label">Manual Time</div>
        <div class="ts-stat-value ts-blue-fg">{manual}</div>
        </div>
        <div class="ts-stat">
        <div class="ts-stat-icon ts-green-bg">⚡</div>
        <div class="ts-stat-label">Automated Time</div>
        <div class="ts-stat-value ts-green-fg">{automated}</div>
        </div>
        <div class="ts-stat">
        <div class="ts-stat-icon ts-purple-bg">📊</div>
        <div class="ts-stat-label">Time Saved</div>
        <div class="ts-stat-value ts-purple-fg">{saved}</div>
        </div>
        </div>
        <div class="ts-banner">✅ <strong>{pct}% time saved</strong><br>You saved {saved} vs. manual work</div>
        """)
    with st.sidebar.container(border=True):
        st.markdown(card_html, unsafe_allow_html=True)

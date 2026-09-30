import os
import textwrap
import time

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


# App-wide polish, injected once per rerun by configure_page(). Colors come
# from Streamlit's own theme (currentColor / translucent overlays) so the
# same rules read correctly in both the light and dark theme. Selectors use
# Streamlit's stable data-testid attributes, not generated class names.
_POLISH_CSS = """<style>
[data-testid="stMainBlockContainer"] { max-width: 1280px; padding-top: 2.5rem; }
[data-testid="stHeadingWithActionElements"] h1 { font-weight: 700; letter-spacing: -0.02em; font-size: 2.1rem; }
[data-testid="stHeadingWithActionElements"] h2 { font-weight: 650; letter-spacing: -0.01em; font-size: 1.5rem; }
[data-testid="stHeadingWithActionElements"] h3 { font-weight: 600; font-size: 1.2rem; }
/* Streamlit 1.61 gives bordered and plain containers the same markup, so
   the card shadow is opted into via a container key prefix (class st-key-*). */
[class*="st-key-ml_card"], [data-testid="stMetric"] {
    box-shadow: 0 1px 3px rgba(0, 27, 71, 0.08);
    transition: box-shadow 150ms ease, transform 150ms ease;
}
[class*="st-key-ml_card"]:hover { box-shadow: 0 6px 16px rgba(0, 27, 71, 0.14); transform: translateY(-1px); }
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-secondary"],
[data-testid="stDownloadButton"] button { font-weight: 600; }
[data-testid="stMetricLabel"] { opacity: 0.75; }
[data-testid="stMetricValue"] { font-weight: 700; }
[data-testid="stPageLink"] a { font-weight: 600; }
/* Every st.selectbox/st.multiselect should look and feel like a dropdown,
   not an editable text box. Pages pass filter_mode=None (typing disabled,
   enforced by a guard test); these rules make the whole control, not just
   its inner input, show a pointer with no text caret or selection
   highlight. Streamlit 1.61 renders selects as react-aria ComboBoxes (not
   BaseWeb), so the selectors use its stable data-testid and ARIA roles;
   the [data-baseweb="select"] ones keep older/newer builds covered. No
   colors, so both themes are unaffected; the chevron button and keyboard
   handling (arrows/Enter/Escape) are untouched. */
[data-testid="stSelectbox"] [role="group"], [data-testid="stSelectbox"] [role="group"] *,
[data-testid="stMultiSelect"] [role="group"], [data-testid="stMultiSelect"] [role="group"] *,
[data-testid="stSelectbox"] [data-baseweb="select"], [data-testid="stSelectbox"] [data-baseweb="select"] *,
[data-testid="stMultiSelect"] [data-baseweb="select"], [data-testid="stMultiSelect"] [data-baseweb="select"] *,
[role="listbox"] [role="option"] { cursor: pointer; }
[data-testid="stSelectbox"] input, [data-testid="stMultiSelect"] input {
    caret-color: transparent; user-select: none; -webkit-user-select: none;
}
[data-testid="stSelectbox"] input::selection, [data-testid="stMultiSelect"] input::selection { background: transparent; }
</style>"""


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
    st.markdown(_POLISH_CSS, unsafe_allow_html=True)
    user = auth_gate.require_login()

    # No divider directly above the Time Saved card -- it sits right after
    # the page nav links, closer to the top of the sidebar rather than
    # pushed down by an extra divider's worth of gap.
    _render_time_saved_card()

    with st.sidebar.container(border=True):
        st.caption("Logged in as")
        st.caption(f":material/person: {user['username']}")
        st.caption(f":material/work: {user['role']}" if user.get("role") else ":material/work: Admin" if user["is_admin"] else ":material/work: User")
    if st.sidebar.button("Log out", key="_logout_button", use_container_width=True):
        auth_gate.logout()
        st.rerun()

    _render_quit_app_button()

    st.sidebar.divider()
    with st.sidebar.container(border=True):
        st.caption("Tool Made By")
        st.caption(":material/person: Ritesh Majumdar")
        st.caption(":material/work: Sr. Client Reporting Specialist")
    return user


_PENDING_QUIT_KEY = "_pending_quit_app"


def _quit_app() -> None:
    # os._exit bypasses normal interpreter teardown (atexit hooks, thread
    # joins) and kills the process immediately -- needed because this is a
    # packaged, one-process-per-window desktop-style app (see launcher.py):
    # a plain sys.exit() inside a Streamlit script rerun is caught by
    # Streamlit's own script-runner machinery and would just end that one
    # rerun, not stop the server process or close the console window.
    os._exit(0)


def _render_quit_app_button() -> None:
    # Two-step confirm, same pattern as Settings' "Remove account" button --
    # this ends the whole app process, not just the current page, so a
    # stray click deserves a confirmation, not an instant exit.
    if st.session_state.get(_PENDING_QUIT_KEY):
        st.sidebar.warning("Quit the app? Close any open browser tab afterward.", icon=":material/warning:")
        _col_confirm, _col_cancel = st.sidebar.columns(2)
        if _col_confirm.button("Confirm quit", key="_confirm_quit_button", type="primary", use_container_width=True):
            # window.close() only works if the browser considers this tab
            # script-opened -- ours was opened by launcher.py's plain
            # webbrowser.open(), the same as a user navigating there by
            # hand, so most browsers silently refuse it. Still worth
            # attempting (harmless, and it does work in a few browser/
            # kiosk configs), but the visible message is the real
            # fallback -- it must render regardless of whether the script
            # actually closes anything.
            st.sidebar.markdown(
                "<script>window.close();</script>"
                "<p style='font-size:0.85rem;'>App is quitting — you can close this browser tab now.</p>",
                unsafe_allow_html=True,
            )
            # Give Streamlit's server a moment to push the markdown above
            # to the browser over its websocket before os._exit(0) kills
            # the process outright -- without this the process can die
            # before that last frame is ever sent.
            time.sleep(0.3)
            _quit_app()
        if _col_cancel.button("Cancel", key="_cancel_quit_button", use_container_width=True):
            st.session_state.pop(_PENDING_QUIT_KEY, None)
            st.rerun()
    elif st.sidebar.button("Quit App", key="_quit_app_button", use_container_width=True):
        st.session_state[_PENDING_QUIT_KEY] = True
        st.rerun()


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


# Inline line-icons (not emoji) so the card stays crisp at sidebar size —
# emoji glyphs are bitmap-ish at small sizes and render blurry/inconsistent
# across platforms. `currentColor` lets each one inherit whatever text
# color it's placed in, so the same markup works in both the light and
# dark theme without a separate icon per theme.
_ICON_ATTRS = 'viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
_ICON_TIMER = f'<svg {_ICON_ATTRS}><line x1="10" y1="2" x2="14" y2="2"/><line x1="12" y1="14" x2="15" y2="11"/><circle cx="12" cy="14" r="8"/></svg>'
_ICON_CLOCK = f'<svg {_ICON_ATTRS}><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>'
_ICON_ZAP = f'<svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" stroke="none"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>'
_ICON_BARS = f'<svg {_ICON_ATTRS}><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>'
_ICON_CHECK = f'<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>'

# Same brand blue as .streamlit/config.toml's primaryColor -- kept in sync
# manually since Streamlit doesn't expose theme colors as CSS variables.
_ACCENT = "#1C6BFF"
_SAVED_COLOR = "#1A9E6B"


def _render_time_saved_card() -> None:
    summary = _cached_time_saved_summary(get_shared_root_dir())
    manual = format_minutes(summary["total_manual_minutes"])
    automated = format_minutes(summary["total_automated_minutes"])
    saved = format_minutes(summary["total_saved_minutes"])
    pct = round(summary["percent_saved"], 1)
    count = summary["total_processes"]
    count_noun = f"{'Client' if count == 1 else 'Clients'} QA/{'Upload' if count == 1 else 'Uploads'} Done"

    # Every line must start at column 0 -- Markdown treats a run of lines
    # indented 4+ spaces as a code block unless they're literally inside an
    # (equally unindented) <style>/<script>/<pre> tag, which the closing
    # </style> tag below ends; the <div> markup that follows it is regular
    # block content and would otherwise get swallowed into a code block and
    # rendered as literal text instead of real HTML.
    card_html = textwrap.dedent(f"""\
        <style>
        .ts-header {{
            display: flex; align-items: center; justify-content: center; gap: 6px;
            font-weight: 600; font-size: 0.95rem; text-align: center;
        }}
        .ts-header .ts-icon {{ color: {_ACCENT}; display: flex; }}
        .ts-count {{ margin: 6px 0 16px 0; font-size: 0.82rem; opacity: 0.85; text-align: center; }}
        .ts-count strong {{ color: {_ACCENT}; opacity: 1; }}
        .ts-stats {{ display: flex; justify-content: space-between; gap: 4px; text-align: center; }}
        .ts-stat {{ flex: 1; }}
        .ts-stat-icon {{ opacity: 0.55; display: flex; justify-content: center; margin-bottom: 3px; }}
        .ts-stat-label {{ font-size: 0.66rem; opacity: 0.65; line-height: 1.2; }}
        .ts-stat-value {{ font-weight: 600; font-size: 0.85rem; margin-top: 2px; }}
        .ts-stat-value.ts-saved {{ color: {_SAVED_COLOR}; font-weight: 700; }}
        .ts-footer {{
            margin-top: 10px; padding-top: 8px; border-top: 1px solid rgba(128, 128, 128, 0.25);
            font-size: 0.8rem; display: flex; align-items: center; justify-content: center; gap: 5px;
        }}
        .ts-footer .ts-icon {{ color: {_SAVED_COLOR}; display: flex; flex-shrink: 0; }}
        .ts-footer strong {{ color: {_SAVED_COLOR}; }}
        </style>
        <div class="ts-header"><span class="ts-icon">{_ICON_TIMER}</span>Time Saved</div>
        <div class="ts-count"><strong>{count}</strong> {count_noun}</div>
        <div class="ts-stats">
        <div class="ts-stat">
        <div class="ts-stat-icon">{_ICON_CLOCK}</div>
        <div class="ts-stat-label">Manual Time</div>
        <div class="ts-stat-value">{manual}</div>
        </div>
        <div class="ts-stat">
        <div class="ts-stat-icon">{_ICON_ZAP}</div>
        <div class="ts-stat-label">Automated Time</div>
        <div class="ts-stat-value">{automated}</div>
        </div>
        <div class="ts-stat">
        <div class="ts-stat-icon">{_ICON_BARS}</div>
        <div class="ts-stat-label">Time Saved</div>
        <div class="ts-stat-value ts-saved">{saved}</div>
        </div>
        </div>
        <div class="ts-footer"><span class="ts-icon">{_ICON_CHECK}</span><strong>{pct}% time saved</strong></div>
        """)
    with st.sidebar.container(border=True):
        st.markdown(card_html, unsafe_allow_html=True)

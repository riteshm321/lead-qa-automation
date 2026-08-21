import streamlit as st

from core.resources import resource_path

_LOGO_PATH = resource_path("assets/madison_logic_logo.svg")
# A separate, dedicated favicon file — the sidebar logo above is a wide
# wordmark (~3:1 aspect ratio) that reads fine at sidebar size but becomes an
# illegible smudge squeezed into a 16-32px browser tab icon.
_FAVICON_PATH = resource_path("assets/favicon.ico")


def configure_page(page_title: str) -> None:
    """Call as the very first Streamlit command in every page script.

    Applies the app's branding consistently everywhere: browser tab
    icon/title, wide layout, the Madison Logic logo above the sidebar nav,
    and a small developer credit below it. set_page_config() must be the
    first Streamlit command a script makes, so every page calls this
    instead of st.set_page_config directly.
    """
    st.set_page_config(page_title=page_title, page_icon=_FAVICON_PATH, layout="wide")
    st.logo(_LOGO_PATH, size="large")
    st.sidebar.caption("Built by Ritesh")

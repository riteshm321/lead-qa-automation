import streamlit as st

from core.resources import resource_path

_LOGO_PATH = resource_path("assets/madison_logic_logo.svg")


def configure_page(page_title: str) -> None:
    """Call as the very first Streamlit command in every page script.

    Applies the app's branding consistently everywhere: browser tab
    icon/title, wide layout, the Madison Logic logo above the sidebar nav,
    and a small developer credit below it. set_page_config() must be the
    first Streamlit command a script makes, so every page calls this
    instead of st.set_page_config directly.
    """
    st.set_page_config(page_title=page_title, page_icon=_LOGO_PATH, layout="wide")
    st.logo(_LOGO_PATH, size="large")
    st.sidebar.caption("Built by Ritesh")

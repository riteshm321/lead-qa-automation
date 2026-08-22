import streamlit as st

_PENDING_TOAST_KEY = "_pending_toast_message"


def show_pending_toast() -> None:
    """Call once near the top of a page script (after configure_page()).

    Displays and clears any toast queued by queue_toast_before_rerun() on
    this page's previous run. This exists because st.toast() called
    immediately before st.rerun() is discarded before the user ever sees it
    — Streamlit tears down the current run the instant rerun() is called,
    with no chance for the toast to reach the browser. Queuing the message
    now and showing it on the *next* run is the only way to combine
    "confirm an action, then immediately refresh the page" without losing
    the confirmation.
    """
    message = st.session_state.pop(_PENDING_TOAST_KEY, None)
    if message:
        st.toast(message, icon="✅")


def queue_toast_before_rerun(message: str) -> None:
    """Call instead of st.toast() right before st.rerun() — see
    show_pending_toast() for why a direct st.toast() call there would
    silently never be seen."""
    st.session_state[_PENDING_TOAST_KEY] = message

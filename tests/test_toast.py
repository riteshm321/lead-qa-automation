from unittest.mock import patch

import streamlit as st

from core.toast import queue_toast_before_rerun, show_pending_toast


def test_show_pending_toast_does_nothing_when_none_queued():
    st.session_state.clear()
    with patch("core.toast.st.toast") as mock_toast:
        show_pending_toast()
    mock_toast.assert_not_called()


def test_queue_then_show_displays_and_clears_the_message():
    # Regression test for the underlying bug this module exists to avoid:
    # st.toast() called immediately before st.rerun() is discarded before
    # the user ever sees it. Queuing now and showing on the *next* run is
    # the only way to combine "confirm an action, then immediately refresh
    # the page" without silently losing the confirmation.
    st.session_state.clear()
    queue_toast_before_rerun("Saved.")

    with patch("core.toast.st.toast") as mock_toast:
        show_pending_toast()

    mock_toast.assert_called_once_with("Saved.", icon="✅")
    # Shown once — a second call on a later run must not repeat it.
    with patch("core.toast.st.toast") as mock_toast_again:
        show_pending_toast()
    mock_toast_again.assert_not_called()

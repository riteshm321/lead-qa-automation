"""The Jira comment greeting shared by Run Check and the upload portals
(Convertr, Enhancio), so every page greets the same reporter.

The reporter is the client profile's own jira_reporter_name (set on Client
Setup) -- there is no Jira API lookup of the ticket's reporter anywhere.
"""
import streamlit as st


def jira_reporter_name(profile) -> str:
    return profile.jira_reporter_name


def jira_greeting(reporter_name: str) -> str:
    """Run Check's greeting line: "Hi <name>," or a plain "Hi," when the
    profile has no reporter name."""
    return f"Hi {reporter_name}," if reporter_name else "Hi,"


def seed_message_default(key: str, default: str) -> None:
    """Keeps a keyed Jira message text_area in step with its computed
    default. Streamlit ignores a keyed text_area's value= after the first
    render, so without this a portal's message kept the greeting (and
    summary) it was first drawn with -- e.g. the old reporter after the
    profile's reporter changed, while Run Check, which builds its message
    fresh at Finalize, already used the new one. The box is re-seeded only
    when the default itself changes, so a hand edit survives ordinary
    reruns. Render the text_area with this key and no value=.
    """
    seeded_key = f"_{key}_seeded_default"
    if st.session_state.get(seeded_key) != default or key not in st.session_state:
        st.session_state[key] = default
        st.session_state[seeded_key] = default

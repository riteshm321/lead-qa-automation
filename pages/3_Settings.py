import os

import streamlit as st

from core.app_settings import (
    get_aliases_path, get_clients_dir, get_jira_settings, get_shared_root_dir,
    load_app_settings, save_app_settings, save_jira_settings,
)
from core.branding import configure_page
from core.file_browser import browse_for_folder

configure_page("Settings")
st.title("⚙️ Settings")
st.caption("App-wide settings, set up once — not tied to any specific client.")

with st.expander("⚙️ Shared team data location", expanded=True):
    _clients_dir = get_clients_dir()
    _aliases_path = get_aliases_path()
    st.caption(f"Clients are currently stored at: `{os.path.abspath(_clients_dir)}`")
    st.caption(f"Company aliases are currently stored at: `{os.path.abspath(_aliases_path)}`")
    st.caption(
        "By default both are private to this machine — a colleague using the exe on their own "
        "laptop won't see these clients or learned aliases. To share them across a team, point this "
        "at a folder inside a OneDrive folder you both sync locally (each person sets their own local "
        "path to that same shared folder) — pick the folder itself, not a 'clients' subfolder inside "
        "it; the app creates and manages its own `clients/` and `aliases/` subfolders under whatever "
        "you select here, the same way it does for the private default. Any aliases you'd already "
        "taught locally are copied over so nothing is lost. Note: OneDrive syncs file-by-file, not "
        "instantly — if two people save the *same* client profile at the *same* moment, OneDrive may "
        "create a conflicted copy instead of merging, so treat this as low-frequency shared config, "
        "not simultaneous editing."
    )
    # Label rendered above (not inline in the text_input) so both columns
    # start at the exact same vertical offset — keeps the Browse button
    # aligned with the input box regardless of label text/theme font metrics,
    # same as _path_input_with_browse on the Client Setup page.
    st.markdown("**Shared team data folder**")
    col_input, col_browse = st.columns([5, 1])
    # The Browse button's session_state write must run before the
    # text_input with the same key is instantiated below — Streamlit
    # forbids modifying a widget's session_state value after that widget
    # has already been created in the same script run. Filling col_browse
    # first (button) and col_input second (text_input) — both from this one
    # st.columns() call, with no bare/unwrapped calls in between — keeps
    # col_input rendering on the left regardless of that fill order, exactly
    # like the proven pattern in Client Setup's _path_input_with_browse.
    with col_browse:
        if st.button("📂 Browse...", key="clients_dir_browse", use_container_width=True):
            chosen = browse_for_folder()
            if chosen:
                st.session_state["clients_dir_input"] = chosen
                st.rerun()
    with col_input:
        _new_dir = st.text_input("Shared team data folder", value=get_shared_root_dir(),
                                  placeholder="Leave blank for the private default", key="clients_dir_input",
                                  label_visibility="collapsed")

    col_save, col_reset = st.columns(2)
    with col_save:
        if st.button("Save", key="clients_dir_save", use_container_width=True):
            new_root = _new_dir.strip()
            if new_root:
                os.makedirs(os.path.join(new_root, "clients"), exist_ok=True)
                new_aliases_path = os.path.join(new_root, "aliases", "company_aliases.json")
                old_aliases_path = get_aliases_path()
                if not os.path.isfile(new_aliases_path) and os.path.isfile(old_aliases_path):
                    import shutil
                    os.makedirs(os.path.dirname(new_aliases_path), exist_ok=True)
                    shutil.copy2(old_aliases_path, new_aliases_path)
            updated_settings = {k: v for k, v in load_app_settings().items()
                                if k not in ("clients_dir", "shared_root_dir")}
            updated_settings["shared_root_dir"] = new_root
            save_app_settings(updated_settings)
            st.success("Saved. Reloading...")
            st.rerun()
    with col_reset:
        if st.button("Reset to default", key="clients_dir_reset", use_container_width=True):
            save_app_settings({
                k: v for k, v in load_app_settings().items() if k not in ("clients_dir", "shared_root_dir")
            })
            st.rerun()

with st.expander("🔑 Jira account (private to this machine)", expanded=True):
    st.caption(
        "Used only for the \"Post summary to Jira\" button on the Run Check page, so a finalized run's "
        "summary can be posted as a comment on that client's Jira ticket under your own account. "
        "This is stored locally on this machine only — never inside the shared clients folder above, "
        "since an API token is a secret tied to your Jira login."
    )
    _jira = get_jira_settings()
    jira_base_url = st.text_input("Jira site URL", value=_jira["base_url"],
                                   placeholder="https://yourcompany.atlassian.net", key="jira_base_url_input")
    jira_email = st.text_input("Your Jira email", value=_jira["email"], key="jira_email_input")
    jira_api_token = st.text_input(
        "Your Jira API token", value=_jira["api_token"], type="password", key="jira_api_token_input",
        help="Generate one at id.atlassian.com/manage-profile/security/api-tokens",
    )
    if st.button("Save Jira account", key="jira_settings_save"):
        save_jira_settings(jira_base_url, jira_email, jira_api_token)
        st.success("Saved.")
        st.rerun()

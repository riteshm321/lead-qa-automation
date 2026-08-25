import os

import streamlit as st

from core.app_settings import (
    get_aliases_path, get_clients_dir, get_jira_settings, get_shared_root_dir,
    load_app_settings, save_app_settings, save_jira_settings,
)
from core.auth import create_user, delete_user, load_users
from core.branding import configure_page
from core.file_browser import browse_for_folder
from core.onedrive import is_onedrive_synced_path
from core.toast import queue_toast_before_rerun, show_pending_toast

_current_user = configure_page("Settings")
show_pending_toast()
st.title("⚙️ Settings")
st.caption("App-wide settings, set up once — not tied to any specific client.")

with st.expander("⚙️ Shared team data location", expanded=False):
    _clients_dir = get_clients_dir()
    _aliases_path = get_aliases_path()
    st.caption(f"Clients are currently stored at: `{os.path.abspath(_clients_dir)}`")
    st.caption(f"Company aliases are currently stored at: `{os.path.abspath(_aliases_path)}`")
    st.caption(
        "Required, and must be a folder inside a OneDrive folder you sync locally (each person sets "
        "their own local path to that same shared folder) — a folder on your personal computer that "
        "isn't OneDrive-synced won't be accepted, since your colleagues (and, later, the admin "
        "activity dashboard) need to see the same data. Pick the folder itself, not a 'clients' "
        "subfolder inside it; the app creates and manages its own `clients/` and `aliases/` subfolders "
        "under whatever you select here. Note: OneDrive syncs file-by-file, not instantly — if two "
        "people save the *same* client profile at the *same* moment, OneDrive may create a conflicted "
        "copy instead of merging, so treat this as low-frequency shared config, not simultaneous "
        "editing."
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
                                  placeholder="A folder inside your synced OneDrive", key="clients_dir_input",
                                  label_visibility="collapsed")

    if st.button("Save", key="clients_dir_save", use_container_width=True):
        new_root = _new_dir.strip()
        if not new_root:
            st.error("A shared team data folder is required — this can no longer be left blank.")
        elif not is_onedrive_synced_path(new_root):
            st.error(
                "That folder doesn't look like it's inside a OneDrive-synced folder on this machine. "
                "Pick a folder inside your synced OneDrive (or a synced SharePoint team library) so "
                "your colleagues can access the same data."
            )
        else:
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
            queue_toast_before_rerun("Saved.")
            st.rerun()

with st.expander("🔑 Jira account (private to this machine)", expanded=False):
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
        queue_toast_before_rerun("Saved.")
        st.rerun()

if _current_user["is_admin"]:
    with st.expander("👤 Manage user accounts (admin only)", expanded=False):
        st.caption(
            "Accounts are local to this machine. Add one for each colleague who runs this app here."
        )
        # Add-account form comes first, above the existing-accounts list, so
        # it's immediately visible on expanding rather than sinking further
        # down (and needing more scrolling) as more colleagues get added.
        st.markdown("**Add a new account**")
        with st.form("add_user_form"):
            _new_username = st.text_input("Username")
            _new_password = st.text_input("Password", type="password")
            _new_is_admin = st.checkbox("Admin")
            _add_submitted = st.form_submit_button("Add account")
        if _add_submitted:
            _new_username = _new_username.strip()
            if not _new_username or not _new_password:
                st.error("Username and password are required.")
            elif _new_username in load_users():
                st.error("That username already exists.")
            else:
                create_user(_new_username, _new_password, _new_is_admin)
                queue_toast_before_rerun(f"Added {_new_username}.")
                st.rerun()

        st.divider()
        st.markdown("**Existing accounts**")
        _users = load_users()
        _admin_count = sum(1 for r in _users.values() if r.get("is_admin"))
        for _username, _record in _users.items():
            _col_name, _col_role, _col_remove = st.columns([3, 2, 1])
            _col_name.write(_username)
            _col_role.write("Admin" if _record.get("is_admin") else "User")
            _is_last_admin = _record.get("is_admin") and _admin_count <= 1
            if _col_remove.button(
                "Remove", key=f"remove_user_{_username}", disabled=_is_last_admin,
                help="Can't remove the only remaining admin." if _is_last_admin else None,
            ):
                delete_user(_username)
                queue_toast_before_rerun(f"Removed {_username}.")
                st.rerun()

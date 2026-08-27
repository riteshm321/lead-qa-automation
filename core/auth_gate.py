import os

import streamlit as st

from core.app_settings import get_shared_root_dir, load_app_settings, save_app_settings
from core.auth import authenticate, create_user, has_any_users
from core.file_browser import browse_for_folder
from core.onedrive import is_onedrive_synced_path

_SESSION_KEY = "auth_user"


def get_current_user() -> dict | None:
    return st.session_state.get(_SESSION_KEY)


def logout() -> None:
    st.session_state.pop(_SESSION_KEY, None)


def require_login() -> dict:
    """Blocks the rest of the current page until someone is logged in.

    Call as the first thing on every page (configure_page does this).
    Returns the logged-in user's {"username", "is_admin", "role"} so the
    page can continue; otherwise renders whichever of three forms applies
    and stops the script:

    1. This machine has no shared team folder configured yet -- accounts
       live under that folder (see core/auth.py), so there's no way to
       know whether any exist at all without it. Every machine hits this
       once, the very first time the app runs on it.
    2. The shared folder is configured but has no accounts in it yet --
       one-time admin-creation (the very first person on the whole team
       to ever set this up).
    3. Accounts already exist there -- ordinary login.
    """
    user = get_current_user()
    if user is not None:
        return user

    if not get_shared_root_dir():
        _render_shared_root_setup_form()
    elif not has_any_users():
        _render_bootstrap_form()
    else:
        _render_login_form()
    st.stop()


def _render_shared_root_setup_form() -> None:
    st.title("📁 Set up your shared team folder")
    st.caption(
        "Before you can log in, point this machine at your team's shared OneDrive folder -- this is "
        "where accounts, clients, and activity are all kept in sync across everyone's machines. Ask "
        "whoever set this up already for the folder path if you're not sure."
    )
    col_input, col_browse = st.columns([5, 1])
    with col_browse:
        if st.button("📂 Browse...", key="_bootstrap_shared_root_browse", use_container_width=True):
            chosen = browse_for_folder()
            if chosen:
                st.session_state["_bootstrap_shared_root_input"] = chosen
                st.rerun()
    with col_input:
        new_root = st.text_input(
            "Shared team data folder", key="_bootstrap_shared_root_input",
            placeholder="A folder inside your synced OneDrive", label_visibility="collapsed",
        )
    if st.button("Continue", key="_bootstrap_shared_root_continue"):
        new_root = new_root.strip()
        if not new_root:
            st.error("A shared team data folder is required.")
        elif not is_onedrive_synced_path(new_root):
            st.error(
                "That folder doesn't look like it's inside a OneDrive-synced folder on this machine. "
                "Pick a folder inside your synced OneDrive (or a synced SharePoint team library)."
            )
        else:
            os.makedirs(os.path.join(new_root, "clients"), exist_ok=True)
            updated = {k: v for k, v in load_app_settings().items()
                       if k not in ("clients_dir", "shared_root_dir")}
            updated["shared_root_dir"] = new_root
            save_app_settings(updated)
            st.rerun()


def _render_bootstrap_form() -> None:
    st.title("🔐 Set up your admin account")
    st.caption("No accounts exist yet on your shared team folder. Create the first one -- it's automatically an admin.")
    with st.form("bootstrap_admin_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        confirm = st.text_input("Confirm password", type="password")
        role = st.text_input("Your role/title", placeholder="e.g. Sr. Client Reporting Specialist")
        submitted = st.form_submit_button("Create admin account")
    if submitted:
        username = username.strip()
        if not username or not password:
            st.error("Username and password are required.")
        elif password != confirm:
            st.error("Passwords don't match.")
        else:
            create_user(username, password, is_admin=True, role=role)
            st.session_state[_SESSION_KEY] = {"username": username, "is_admin": True, "role": role.strip()}
            st.rerun()


def _render_login_form() -> None:
    st.title("🔐 Log in")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        user = authenticate(username.strip(), password)
        if user is None:
            st.error("Incorrect username or password.")
        else:
            st.session_state[_SESSION_KEY] = user
            st.rerun()

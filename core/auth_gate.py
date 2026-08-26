import streamlit as st

from core.auth import authenticate, create_user, has_any_users

_SESSION_KEY = "auth_user"


def get_current_user() -> dict | None:
    return st.session_state.get(_SESSION_KEY)


def logout() -> None:
    st.session_state.pop(_SESSION_KEY, None)


def require_login() -> dict:
    """Blocks the rest of the current page until someone is logged in.

    Call as the first thing on every page (configure_page does this).
    Returns the logged-in user's {"username", "is_admin", "role"} so the
    page can continue; otherwise renders the login (or, on a fresh machine
    with no accounts yet, one-time admin-creation) form and stops the
    script.
    """
    user = get_current_user()
    if user is not None:
        return user

    if not has_any_users():
        _render_bootstrap_form()
    else:
        _render_login_form()
    st.stop()


def _render_bootstrap_form() -> None:
    st.title("🔐 Set up your admin account")
    st.caption("No accounts exist yet on this machine. Create the first one -- it's automatically an admin.")
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

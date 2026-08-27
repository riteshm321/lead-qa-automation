import os

from streamlit.testing.v1 import AppTest

from core import auth_gate
from core.app_settings import save_app_settings
from core.auth import create_user
from core.auth_gate import require_login as _real_require_login

_SUMMARY_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Summary.py")


def _unbypassed_app(monkeypatch):
    # Undo tests/conftest.py's autouse bypass so this file exercises the
    # real login gate end to end.
    monkeypatch.setattr(auth_gate, "require_login", _real_require_login)
    return AppTest.from_file(_SUMMARY_PAGE_PATH, default_timeout=15)


def _configure_shared_root(tmp_path, monkeypatch) -> str:
    monkeypatch.chdir(tmp_path)
    root = str(tmp_path / "shared_root")
    os.makedirs(root, exist_ok=True)
    save_app_settings({"shared_root_dir": root})
    return root


def test_fresh_machine_shows_shared_root_setup_form_first(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = _unbypassed_app(monkeypatch)
    at.run()

    assert not at.exception
    assert any("Set up your shared team folder" in t.value for t in at.title)
    # Neither the bootstrap form nor the real page must render past the gate.
    assert not any("Set up your admin account" in t.value for t in at.title)
    assert not any("Lead QA" in t.value for t in at.title)


def test_shared_root_setup_with_valid_onedrive_path_continues_to_bootstrap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(auth_gate, "is_onedrive_synced_path", lambda path: True)
    new_root = str(tmp_path / "team_shared")

    at = _unbypassed_app(monkeypatch)
    at.run()
    at.text_input(key="_bootstrap_shared_root_input").set_value(new_root)
    at.button(key="_bootstrap_shared_root_continue").click().run()

    assert not at.exception
    assert any("Set up your admin account" in t.value for t in at.title)


def test_shared_root_setup_rejects_a_path_outside_onedrive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(auth_gate, "is_onedrive_synced_path", lambda path: False)

    at = _unbypassed_app(monkeypatch)
    at.run()
    at.text_input(key="_bootstrap_shared_root_input").set_value(str(tmp_path / "not_onedrive"))
    at.button(key="_bootstrap_shared_root_continue").click().run()

    assert not at.exception
    assert len(at.error) == 1
    assert any("Set up your shared team folder" in t.value for t in at.title)


def test_bootstrap_form_creates_admin_and_logs_in(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    at = _unbypassed_app(monkeypatch)
    at.run()

    inputs = {w.label: w for w in at.text_input}
    inputs["Username"].set_value("ritesh")
    inputs["Password"].set_value("correct-horse")
    inputs["Confirm password"].set_value("correct-horse")
    at.button[0].click().run()

    assert not at.exception
    assert at.session_state["auth_user"] == {"username": "ritesh", "is_admin": True, "role": ""}
    assert any("Lead QA" in t.value for t in at.title)


def test_existing_accounts_show_login_form_not_bootstrap(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    create_user("ritesh", "correct-horse", is_admin=True)

    at = _unbypassed_app(monkeypatch)
    at.run()

    assert not at.exception
    assert any("Log in" in t.value for t in at.title)
    assert not any("Set up your admin account" in t.value for t in at.title)


def test_login_with_correct_password_reaches_the_page(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    create_user("ritesh", "correct-horse", is_admin=True)

    at = _unbypassed_app(monkeypatch)
    at.run()
    inputs = {w.label: w for w in at.text_input}
    inputs["Username"].set_value("ritesh")
    inputs["Password"].set_value("correct-horse")
    at.button[0].click().run()

    assert not at.exception
    assert at.session_state["auth_user"] == {"username": "ritesh", "is_admin": True, "role": ""}
    assert any("Lead QA" in t.value for t in at.title)


def test_login_with_wrong_password_shows_error_and_stays_on_login(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    create_user("ritesh", "correct-horse", is_admin=True)

    at = _unbypassed_app(monkeypatch)
    at.run()
    inputs = {w.label: w for w in at.text_input}
    inputs["Username"].set_value("ritesh")
    inputs["Password"].set_value("wrong-password")
    at.button[0].click().run()

    assert not at.exception
    assert "auth_user" not in at.session_state
    assert len(at.error) == 1
    assert any("Log in" in t.value for t in at.title)


def test_logout_button_returns_to_login_screen(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    create_user("ritesh", "correct-horse", is_admin=True)

    at = _unbypassed_app(monkeypatch)
    at.run()
    inputs = {w.label: w for w in at.text_input}
    inputs["Username"].set_value("ritesh")
    inputs["Password"].set_value("correct-horse")
    at.button[0].click().run()
    assert any("Lead QA" in t.value for t in at.title)

    logout_button = next(b for b in at.sidebar.button if b.key == "_logout_button")
    logout_button.click().run()

    assert not at.exception
    assert "auth_user" not in at.session_state
    assert any("Log in" in t.value for t in at.title)


def test_two_machines_sharing_the_same_root_see_the_same_accounts(tmp_path, monkeypatch):
    # Simulates the real bug report: an admin creates a colleague's account
    # from their machine, and the colleague's machine -- pointed at the
    # same shared root -- must see it too, rather than showing bootstrap.
    root = _configure_shared_root(tmp_path, monkeypatch)
    create_user("ritesh", "correct-horse", is_admin=True)
    create_user("colleague", "another-pass", is_admin=False)

    # A second "machine" is just a separate app_settings.json pointed at
    # the same shared root.
    other_machine_dir = tmp_path / "other_machine"
    os.makedirs(other_machine_dir, exist_ok=True)
    monkeypatch.chdir(other_machine_dir)
    save_app_settings({"shared_root_dir": root})

    at = _unbypassed_app(monkeypatch)
    at.run()
    inputs = {w.label: w for w in at.text_input}
    inputs["Username"].set_value("colleague")
    inputs["Password"].set_value("another-pass")
    at.button[0].click().run()

    assert not at.exception
    assert at.session_state["auth_user"] == {"username": "colleague", "is_admin": False, "role": ""}
    assert any("Lead QA" in t.value for t in at.title)

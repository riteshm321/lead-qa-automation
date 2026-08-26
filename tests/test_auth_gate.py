import os

from streamlit.testing.v1 import AppTest

from core import auth_gate
from core.auth import create_user
from core.auth_gate import require_login as _real_require_login

_SUMMARY_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Summary.py")


def _unbypassed_app(monkeypatch):
    # Undo tests/conftest.py's autouse bypass so this file exercises the
    # real login gate end to end.
    monkeypatch.setattr(auth_gate, "require_login", _real_require_login)
    return AppTest.from_file(_SUMMARY_PAGE_PATH, default_timeout=15)


def test_fresh_machine_shows_bootstrap_admin_form_not_the_page(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = _unbypassed_app(monkeypatch)
    at.run()

    assert not at.exception
    assert any("Set up your admin account" in t.value for t in at.title)
    # The real page content must not have rendered past the gate.
    assert not any("Lead QA" in t.value for t in at.title)


def test_bootstrap_form_creates_admin_and_logs_in(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
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
    monkeypatch.chdir(tmp_path)
    create_user("ritesh", "correct-horse", is_admin=True)

    at = _unbypassed_app(monkeypatch)
    at.run()

    assert not at.exception
    assert any("Log in" in t.value for t in at.title)
    assert not any("Set up your admin account" in t.value for t in at.title)


def test_login_with_correct_password_reaches_the_page(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
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
    monkeypatch.chdir(tmp_path)
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
    monkeypatch.chdir(tmp_path)
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

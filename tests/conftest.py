import pytest

from core import auth_gate


@pytest.fixture(autouse=True)
def _bypass_login_gate(monkeypatch):
    # Every page now starts with auth_gate.require_login() via
    # configure_page(), which would otherwise st.stop() every existing
    # AppTest-based page test at the login screen. Tests that exercise the
    # gate itself (tests/test_auth_gate.py) restore the real function with
    # their own monkeypatch.setattr(auth_gate, "require_login", ...).
    monkeypatch.setattr(
        auth_gate, "require_login",
        lambda: {"username": "test-admin", "is_admin": True, "role": "Client Reporting Specialist"},
    )

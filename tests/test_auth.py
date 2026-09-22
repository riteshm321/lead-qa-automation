import os

import pytest

from core.app_settings import save_app_settings
from core.auth import (
    authenticate, create_user, delete_user, has_any_users, load_users, CorruptedCredentialsError,
)


def _configure_shared_root(tmp_path, monkeypatch) -> str:
    monkeypatch.chdir(tmp_path)
    root = str(tmp_path / "shared_root")
    os.makedirs(root, exist_ok=True)
    save_app_settings({"shared_root_dir": root})
    return root


def test_has_any_users_is_false_with_no_credentials_file(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    assert has_any_users() is False


def test_has_any_users_is_false_without_a_configured_shared_root(tmp_path, monkeypatch):
    # No shared_root_dir set at all -- accounts live under the shared
    # folder, so there's nowhere to even look for them yet.
    monkeypatch.chdir(tmp_path)
    assert has_any_users() is False


def test_create_user_is_a_noop_without_a_configured_shared_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_user("ritesh", "correct-horse", is_admin=True)

    assert has_any_users() is False
    assert authenticate("ritesh", "correct-horse") is None


def test_load_users_raises_a_distinct_error_on_corrupted_credentials_json(tmp_path, monkeypatch):
    # Regression test for a real risk this app's own architecture invites:
    # credentials.json lives on a shared OneDrive root and load_users() is
    # the literal first thing require_login() calls on every page. Before
    # this fix, a malformed file (a OneDrive conflict copy, or one caught
    # mid-sync) raised a bare json.JSONDecodeError straight out of
    # load_users(), crashing the app for the whole team with no recovery
    # path. It must now raise a distinct, catchable exception instead of
    # a generic parse error, so callers can tell "corrupted" apart from
    # "genuinely no accounts yet" (has_any_users() returning False) --
    # conflating the two would offer to bootstrap a duplicate admin
    # account over a file that already has real ones.
    root = _configure_shared_root(tmp_path, monkeypatch)
    creds_path = os.path.join(root, "auth", "credentials.json")
    os.makedirs(os.path.dirname(creds_path), exist_ok=True)
    with open(creds_path, "w", encoding="utf-8") as f:
        f.write("{not valid json")

    with pytest.raises(CorruptedCredentialsError):
        load_users()
    with pytest.raises(CorruptedCredentialsError):
        has_any_users()


def test_create_user_then_authenticate_succeeds_with_correct_password(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    create_user("ritesh", "correct-horse", is_admin=True)

    user = authenticate("ritesh", "correct-horse")

    assert user == {"username": "ritesh", "is_admin": True, "role": ""}
    assert has_any_users() is True


def test_accounts_are_stored_under_the_shared_root_not_locally(tmp_path, monkeypatch):
    # The whole point of this design: a colleague on a different machine,
    # pointed at the SAME shared root, must see the same accounts.
    root = _configure_shared_root(tmp_path, monkeypatch)
    create_user("ritesh", "correct-horse", is_admin=True)

    assert os.path.isfile(os.path.join(root, "auth", "credentials.json"))
    assert not os.path.isfile("auth/credentials.json")


def test_authenticate_fails_with_wrong_password(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    create_user("ritesh", "correct-horse", is_admin=True)

    assert authenticate("ritesh", "wrong-password") is None


def test_authenticate_fails_for_unknown_username(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    create_user("ritesh", "correct-horse", is_admin=True)

    assert authenticate("someone-else", "correct-horse") is None


def test_password_is_never_stored_in_plaintext(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    create_user("ritesh", "correct-horse", is_admin=True)

    record = load_users()["ritesh"]

    assert "correct-horse" not in record["hash"]
    assert record["salt"] != ""


def test_delete_user_removes_account(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    create_user("ritesh", "correct-horse", is_admin=True)
    create_user("colleague", "another-pass", is_admin=False)

    delete_user("colleague")

    assert list(load_users().keys()) == ["ritesh"]
    assert authenticate("colleague", "another-pass") is None

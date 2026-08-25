from core.auth import authenticate, create_user, delete_user, has_any_users, load_users


def test_has_any_users_is_false_with_no_credentials_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert has_any_users() is False


def test_create_user_then_authenticate_succeeds_with_correct_password(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_user("ritesh", "correct-horse", is_admin=True)

    user = authenticate("ritesh", "correct-horse")

    assert user == {"username": "ritesh", "is_admin": True}
    assert has_any_users() is True


def test_authenticate_fails_with_wrong_password(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_user("ritesh", "correct-horse", is_admin=True)

    assert authenticate("ritesh", "wrong-password") is None


def test_authenticate_fails_for_unknown_username(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_user("ritesh", "correct-horse", is_admin=True)

    assert authenticate("someone-else", "correct-horse") is None


def test_password_is_never_stored_in_plaintext(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_user("ritesh", "correct-horse", is_admin=True)

    record = load_users()["ritesh"]

    assert "correct-horse" not in record["hash"]
    assert record["salt"] != ""


def test_delete_user_removes_account(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_user("ritesh", "correct-horse", is_admin=True)
    create_user("colleague", "another-pass", is_admin=False)

    delete_user("colleague")

    assert list(load_users().keys()) == ["ritesh"]
    assert authenticate("colleague", "another-pass") is None

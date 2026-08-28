import os

from streamlit.testing.v1 import AppTest

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages", "4_Activity_Log.py")


def _configure_shared_root(tmp_path, monkeypatch) -> str:
    monkeypatch.chdir(tmp_path)
    root = str(tmp_path / "shared")
    from core.app_settings import save_app_settings
    save_app_settings({"shared_root_dir": root})
    return root


def test_shows_no_processes_message_with_no_activity(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    assert not at.exception
    assert any("No client processes completed yet" in c.value for c in at.caption)


def test_process_log_lists_every_process_with_client_date_and_time(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    from core.activity_tracker import record_process_completed
    record_process_completed("alice", "Acme", 3.0, is_complex_account=False)
    record_process_completed("bob", "Beta Corp", 2.0, is_complex_account=True)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    assert not at.exception
    log_df = at.dataframe[0].value
    assert set(log_df["User"]) == {"alice", "bob"}
    assert set(log_df["Client"]) == {"Acme", "Beta Corp"}
    assert "Yes" in list(log_df["Complex Account"])
    # Every row has a real date and time split out of the stored timestamp,
    # not the literal "—" placeholder used only when a timestamp is missing.
    assert all(d != "—" for d in log_df["Date"])
    assert all(t != "—" for t in log_df["Time"])


def test_filter_by_user_narrows_the_log_and_the_totals(tmp_path, monkeypatch):
    _configure_shared_root(tmp_path, monkeypatch)
    from core.activity_tracker import record_process_completed
    record_process_completed("alice", "Acme", 3.0, is_complex_account=False)
    record_process_completed("bob", "Beta Corp", 2.0, is_complex_account=False)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.selectbox[0].set_value("alice").run()

    assert not at.exception
    log_df = at.dataframe[0].value
    assert set(log_df["User"]) == {"alice"}
    assert any("alice" in m.value for m in at.markdown)
    assert not any("**bob**" in m.value for m in at.markdown)


def test_non_admin_sees_warning_not_the_log(tmp_path, monkeypatch):
    # Overrides tests/conftest.py's autouse admin bypass for this one test --
    # everywhere else in the suite intentionally runs as an admin.
    from core import auth_gate
    monkeypatch.setattr(
        auth_gate, "require_login",
        lambda: {"username": "regular-user", "is_admin": False, "role": ""},
    )
    _configure_shared_root(tmp_path, monkeypatch)
    from core.activity_tracker import record_process_completed
    record_process_completed("alice", "Acme", 3.0, is_complex_account=False)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    assert not at.exception
    assert len(at.warning) == 1
    assert len(at.dataframe) == 0

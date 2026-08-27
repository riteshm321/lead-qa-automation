import os

from streamlit.testing.v1 import AppTest

_PAGE_PATH = os.path.join(os.path.dirname(__file__), "..", "Summary.py")


def test_sidebar_shows_logged_in_user_and_role(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    assert not at.exception
    sidebar_text = "\n".join(m.value for m in at.sidebar.markdown) + "\n".join(c.value for c in at.sidebar.caption)
    assert "test-admin" in sidebar_text
    assert "Client Reporting Specialist" in sidebar_text


def test_sidebar_time_saved_card_shows_zero_with_no_activity(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    assert not at.exception
    sidebar_markdown = "\n".join(m.value for m in at.sidebar.markdown)
    assert "0" in sidebar_markdown
    assert "client process" in sidebar_markdown


def test_sidebar_time_saved_card_reflects_recorded_activity(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shared_root = str(tmp_path / "shared")
    from core.app_settings import save_app_settings
    save_app_settings({"shared_root_dir": shared_root})
    from core.activity_tracker import record_process_completed
    record_process_completed("alice", 3.0, is_complex_account=False)
    record_process_completed("bob", 3.0, is_complex_account=False)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    assert not at.exception
    sidebar_markdown = "\n".join(m.value for m in at.sidebar.markdown)
    assert "2" in sidebar_markdown  # 2 total processes across both users
    assert "30m" in sidebar_markdown  # 2 * 15 min saved = 30m

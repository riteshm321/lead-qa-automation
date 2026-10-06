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
    assert "Clients QA/Uploads Done" in sidebar_markdown


def test_sidebar_time_saved_card_reflects_recorded_activity(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shared_root = str(tmp_path / "shared")
    from core.app_settings import save_app_settings
    save_app_settings({"shared_root_dir": shared_root})
    from core.activity_tracker import record_process_completed
    record_process_completed("alice", "Acme", 3.0, is_complex_account=False)
    record_process_completed("bob", "Acme", 3.0, is_complex_account=False)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    assert not at.exception
    sidebar_markdown = "\n".join(m.value for m in at.sidebar.markdown)
    assert "2" in sidebar_markdown  # 2 total processes across both users
    assert "30m" in sidebar_markdown  # 2 * 15 min saved = 30m


def test_sidebar_shows_quit_app_button(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()

    assert not at.exception
    assert any(b.label == "Quit App" for b in at.sidebar.button)


def test_quit_app_button_requires_confirmation_before_exiting(tmp_path, monkeypatch):
    # The actual quit is os._exit(0), which would kill the test process
    # itself -- patch it out and assert on whether it was called, the same
    # way the real button only calls it after a second, explicit click.
    calls = []
    monkeypatch.setattr("core.branding._quit_app", lambda: calls.append(True))
    monkeypatch.setattr("core.branding.time.sleep", lambda *_a, **_k: None)
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(b for b in at.sidebar.button if b.label == "Quit App").click().run()

    assert not calls
    assert any("quit" in w.value.lower() for w in at.sidebar.warning)

    next(b for b in at.sidebar.button if b.label == "Confirm quit").click().run()
    assert calls == [True]


def test_confirm_quit_attempts_to_close_the_browser_tab_before_exiting(tmp_path, monkeypatch):
    # window.close() only works if the browser considers this tab
    # script-opened -- ours is opened by launcher.py's plain
    # webbrowser.open(), so most browsers silently refuse it. Still worth
    # attempting (harmless, works in a few browser/kiosk configs), but the
    # visible "close this tab" message is the real fallback that must
    # always render regardless of whether the script actually works.
    calls = []
    monkeypatch.setattr("core.branding._quit_app", lambda: calls.append(True))
    monkeypatch.setattr("core.branding.time.sleep", lambda *_a, **_k: None)
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(b for b in at.sidebar.button if b.label == "Quit App").click().run()
    next(b for b in at.sidebar.button if b.label == "Confirm quit").click().run()

    assert calls == [True]
    rendered_html = "\n".join(m.value for m in at.sidebar.markdown)
    assert "window.close()" in rendered_html
    assert "close this" in rendered_html.lower()


def test_quit_app_cancel_dismisses_the_confirmation_without_exiting(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("core.branding._quit_app", lambda: calls.append(True))
    monkeypatch.chdir(tmp_path)

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(b for b in at.sidebar.button if b.label == "Quit App").click().run()
    next(b for b in at.sidebar.button if b.label == "Cancel").click().run()

    assert not calls
    assert not any("quit" in w.value.lower() for w in at.sidebar.warning)
    assert any(b.label == "Quit App" for b in at.sidebar.button)


def test_sidebar_nav_uses_material_symbols_not_emoji():
    with open("Summary.py", encoding="utf-8") as f:
        source = f.read()
    # Every icon= argument passed to st.Page must be a :material/...:
    # shorthand, not a raw emoji -- catches a future page addition that
    # reverts to emoji just as easily as it catches this task's own change.
    import re
    icon_args = re.findall(r'icon="([^"]+)"', source)
    assert len(icon_args) >= 10  # one per st.Page call (10 pages + Home)
    assert all(icon.startswith(":material/") for icon in icon_args)


def _selectbox_calls_missing_filter_mode(path: str) -> list[str]:
    import ast
    tree = ast.parse(open(path, encoding="utf-8").read())
    missing = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("selectbox", "multiselect")):
            fm = next((k for k in node.keywords if k.arg == "filter_mode"), None)
            if fm is None or not (isinstance(fm.value, ast.Constant) and fm.value.value is None):
                missing.append(f"{os.path.basename(path)}:{node.lineno}")
    return missing


def test_every_selectbox_and_multiselect_is_a_plain_dropdown():
    # Guard: Streamlit's default type-to-filter combobox shows a text caret,
    # so users took dropdowns for editable text boxes. Every selectbox/
    # multiselect in the app must pass filter_mode=None.
    import glob
    root = os.path.join(os.path.dirname(__file__), "..")
    paths = glob.glob(os.path.join(root, "pages", "*.py")) + glob.glob(os.path.join(root, "core", "*.py"))
    paths.append(os.path.join(root, "Summary.py"))
    missing = [m for p in paths for m in _selectbox_calls_missing_filter_mode(p)]
    assert missing == []


def test_polish_css_makes_selects_feel_like_dropdowns():
    from core.branding import _POLISH_CSS
    assert '[data-testid="stSelectbox"] [role="group"]' in _POLISH_CSS
    assert '[data-testid="stMultiSelect"] input' in _POLISH_CSS
    assert "caret-color: transparent" in _POLISH_CSS
    assert "cursor: pointer" in _POLISH_CSS
    assert "user-select: none" in _POLISH_CSS


def test_quit_app_logs_the_reason_before_exiting(caplog):
    # Every process exit must leave a line in logs/app.log saying why, so a
    # deliberate Quit is distinguishable from a crash or a console Ctrl+C.
    import logging
    from unittest.mock import patch

    import core.branding as branding

    with patch("core.branding.os._exit") as mock_exit,          caplog.at_level(logging.WARNING, logger="lead_qa_automation"):
        branding._quit_app()

    mock_exit.assert_called_once_with(0)
    assert any("Quit App button" in r.getMessage() for r in caplog.records)

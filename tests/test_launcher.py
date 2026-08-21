from unittest.mock import MagicMock, patch

import launcher


def test_port_already_serving_true_when_url_responds():
    with patch("launcher.urllib.request.urlopen", return_value=MagicMock()):
        assert launcher._port_already_serving("http://localhost:8501") is True


def test_port_already_serving_false_when_connection_fails():
    with patch("launcher.urllib.request.urlopen", side_effect=OSError("refused")):
        assert launcher._port_already_serving("http://localhost:8501") is False


def test_main_reuses_existing_instance_without_starting_a_second_server():
    # Regression test: launching a second instance while one is already
    # running used to call stcli.main() a second time, which fails to bind
    # the already-used port with an unhandled OSError that kills the whole
    # process (daemon threads included) before it can open a browser tab.
    with patch("launcher._chdir_to_app_folder"), \
         patch("launcher._port_already_serving", return_value=True), \
         patch("launcher.webbrowser.open") as mock_open, \
         patch("launcher.stcli.main") as mock_stcli_main, \
         patch("launcher.threading.Thread") as mock_thread:
        result = launcher.main()

    assert result == 0
    mock_open.assert_called_once_with("http://localhost:8501")
    mock_stcli_main.assert_not_called()
    mock_thread.assert_not_called()


def test_main_starts_server_and_browser_thread_when_port_is_free():
    with patch("launcher._chdir_to_app_folder"), \
         patch("launcher._port_already_serving", return_value=False), \
         patch("launcher.stcli.main", return_value=0) as mock_stcli_main, \
         patch("launcher.threading.Thread") as mock_thread_cls:
        mock_thread_instance = MagicMock()
        mock_thread_cls.return_value = mock_thread_instance

        result = launcher.main()

    assert result == 0
    mock_stcli_main.assert_called_once()
    mock_thread_cls.assert_called_once()
    mock_thread_instance.start.assert_called_once()


def test_sync_bundled_theme_config_copies_config_to_app_data(tmp_path):
    # Regression test: Streamlit discovers .streamlit/config.toml relative
    # to the current working directory, which _chdir_to_app_folder points
    # at the per-user app-data folder — without copying our bundled theme
    # config there, the packaged exe silently fell back to Streamlit's own
    # default theme instead of the app's branded one.
    bundled_dir = tmp_path / "bundled" / ".streamlit"
    bundled_dir.mkdir(parents=True)
    (bundled_dir / "config.toml").write_text("[theme]\nprimaryColor = \"#1C6BFF\"\n", encoding="utf-8")

    app_data = tmp_path / "app_data"
    app_data.mkdir()

    with patch("launcher._resource_path", side_effect=lambda p: str(tmp_path / "bundled" / p)):
        launcher._sync_bundled_theme_config(str(app_data))

    dest = app_data / ".streamlit" / "config.toml"
    assert dest.is_file()
    assert "#1C6BFF" in dest.read_text(encoding="utf-8")


def test_sync_bundled_theme_config_overwrites_a_stale_copy(tmp_path):
    # Unlike aliases (user-editable, copied only if missing), the theme
    # config is app-owned — a stale copy from an older build must be
    # replaced, not preserved, so branding updates actually take effect.
    bundled_dir = tmp_path / "bundled" / ".streamlit"
    bundled_dir.mkdir(parents=True)
    (bundled_dir / "config.toml").write_text("[theme]\nprimaryColor = \"#NEW\"\n", encoding="utf-8")

    app_data = tmp_path / "app_data"
    dest_dir = app_data / ".streamlit"
    dest_dir.mkdir(parents=True)
    (dest_dir / "config.toml").write_text("[theme]\nprimaryColor = \"#OLD\"\n", encoding="utf-8")

    with patch("launcher._resource_path", side_effect=lambda p: str(tmp_path / "bundled" / p)):
        launcher._sync_bundled_theme_config(str(app_data))

    assert "#NEW" in (dest_dir / "config.toml").read_text(encoding="utf-8")


def test_main_reports_failure_instead_of_crashing_on_startup_error():
    # Regression test: an unhandled exception anywhere during startup (e.g.
    # a permission error creating the per-user data folder) used to crash
    # with a bare traceback and no context. main() now catches it and
    # returns a non-zero status instead of propagating.
    with patch("launcher._chdir_to_app_folder", side_effect=PermissionError("denied")):
        result = launcher.main()

    assert result == 1

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


def test_use_pure_python_protobuf_sets_backend_when_unset():
    # Root cause of the "app closes by itself while idle" bug: protobuf's
    # upb C extension (_message.pyd) crashed the packaged exe natively on
    # Python 3.14. The launcher must select the pure-Python backend.
    env = {}
    launcher._use_pure_python_protobuf(env)
    assert env["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] == "python"


def test_use_pure_python_protobuf_respects_an_explicit_override():
    env = {"PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION": "upb"}
    launcher._use_pure_python_protobuf(env)
    assert env["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] == "upb"


def test_importing_launcher_selects_pure_python_protobuf_before_streamlit_loads():
    # The backend is fixed at protobuf's first import, so this only works
    # if launcher sets it before importing streamlit -- check in a fresh
    # interpreter, since this test process already imported protobuf.
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k != "PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"}
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run(
        [sys.executable, "-c",
         "import launcher; from google.protobuf.internal import api_implementation as a; print(a.Type())"],
        cwd=repo_root, env=env, capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "python"


def test_enable_crash_log_points_faulthandler_at_logs_crash_log(tmp_path):
    with patch("launcher.faulthandler.enable") as mock_enable:
        path = launcher._enable_crash_log(str(tmp_path / "logs"))

    try:
        assert path == str(tmp_path / "logs" / "crash.log")
        mock_enable.assert_called_once()
        assert mock_enable.call_args.kwargs["file"].name == path
        assert mock_enable.call_args.kwargs["all_threads"] is True
        assert "started" in (tmp_path / "logs" / "crash.log").read_text(encoding="utf-8")
    finally:
        launcher._crash_log_file.close()
        launcher._crash_log_file = None


def test_enable_crash_log_never_blocks_startup():
    with patch("launcher.os.makedirs", side_effect=PermissionError("denied")):
        assert launcher._enable_crash_log("whatever") is None


def test_main_logs_why_the_server_stopped(caplog):
    import logging

    import pytest

    with patch("launcher._chdir_to_app_folder"), \
         patch("launcher._enable_crash_log"), \
         patch("launcher._port_already_serving", return_value=False), \
         patch("launcher.stcli.main", side_effect=SystemExit(0)), \
         patch("launcher.threading.Thread"), \
         caplog.at_level(logging.INFO, logger="lead_qa_automation"):
        with pytest.raises(SystemExit):
            launcher.main()

    messages = [r.getMessage() for r in caplog.records]
    assert any("App starting" in m for m in messages)
    assert any("Streamlit server stopped (exit code 0)" in m for m in messages)

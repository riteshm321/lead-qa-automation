import os

from core.app_settings import (
    load_app_settings, save_app_settings, get_clients_dir, get_aliases_path, get_shared_root_dir,
    get_jira_settings, save_jira_settings,
)

_ROOT = r"C:\Shared\OneDrive\LeadQA"


def test_get_clients_dir_defaults_to_clients_when_no_settings_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert get_clients_dir() == "clients"


def test_get_shared_root_dir_defaults_to_blank_when_no_settings_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert get_shared_root_dir() == ""


def test_save_and_load_app_settings_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": _ROOT})
    assert load_app_settings() == {"shared_root_dir": _ROOT}
    assert get_shared_root_dir() == _ROOT


def test_get_clients_dir_uses_clients_subfolder_under_shared_root(tmp_path, monkeypatch):
    # The user picks a root folder (e.g. a OneDrive folder they both sync) —
    # the app owns a "clients" subfolder under it, mirroring the private
    # default's cwd/clients layout, rather than expecting profile JSONs
    # directly in the selected folder.
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": _ROOT})
    assert get_clients_dir() == os.path.join(_ROOT, "clients")


def test_get_clients_dir_falls_back_to_default_when_override_blank(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": ""})
    assert get_clients_dir() == "clients"


def test_get_aliases_path_defaults_to_private_location_when_no_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert get_aliases_path() == "aliases/company_aliases.json"


def test_get_aliases_path_follows_shared_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": _ROOT})
    assert get_aliases_path() == os.path.join(_ROOT, "aliases", "company_aliases.json")


def test_get_aliases_path_reverts_to_default_when_override_blank(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": ""})
    assert get_aliases_path() == "aliases/company_aliases.json"


def test_old_clients_dir_key_still_works_as_shared_root(tmp_path, monkeypatch):
    # Backward compatibility: a machine that saved this setting before the
    # "clients_dir" -> "shared_root_dir" rename must not silently revert to
    # the private default — its existing pointer should keep working, and
    # since its already-configured folder already used the "clients"/
    # "aliases" subfolder convention, no file migration is needed either.
    monkeypatch.chdir(tmp_path)
    save_app_settings({"clients_dir": _ROOT})
    assert get_shared_root_dir() == _ROOT
    assert get_clients_dir() == os.path.join(_ROOT, "clients")
    assert get_aliases_path() == os.path.join(_ROOT, "aliases", "company_aliases.json")


def test_new_key_takes_priority_over_old_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"clients_dir": r"C:\Old", "shared_root_dir": r"C:\New"})
    assert get_shared_root_dir() == r"C:\New"


def test_get_jira_settings_defaults_to_blank_when_unset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert get_jira_settings() == {"base_url": "", "email": "", "api_token": ""}


def test_save_and_load_jira_settings_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_jira_settings("https://example.atlassian.net", "me@example.com", "token123")
    assert get_jira_settings() == {
        "base_url": "https://example.atlassian.net", "email": "me@example.com", "api_token": "token123",
    }


def test_jira_settings_never_derive_from_shared_root(tmp_path, monkeypatch):
    # Jira credentials must stay local even when clients_dir/aliases_path
    # are pointed at a shared folder — this is what keeps a personal API
    # token out of a folder the whole team syncs.
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": _ROOT})
    save_jira_settings("https://example.atlassian.net", "me@example.com", "token123")
    assert get_shared_root_dir() == _ROOT
    assert get_jira_settings()["api_token"] == "token123"
    with open("app_settings.json", encoding="utf-8") as f:
        raw = f.read()
    assert _ROOT.replace("\\", "\\\\") in raw  # sanity: still the same local settings file

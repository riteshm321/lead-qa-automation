import json
import os

from core.atomic_io import atomic_write_json

_SETTINGS_PATH = "app_settings.json"


def load_app_settings() -> dict:
    if not os.path.isfile(_SETTINGS_PATH):
        return {}
    with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_app_settings(settings: dict) -> None:
    atomic_write_json(_SETTINGS_PATH, settings)


def get_shared_root_dir() -> str:
    # The folder a user points "Shared team data folder" at (e.g. inside a
    # synced OneDrive folder). The app owns "clients/" and "aliases/" as
    # subfolders under this root — mirroring the private-mode layout
    # (cwd/clients, cwd/aliases) — rather than expecting profile JSONs
    # directly in the selected folder, which is what a user picking a plain
    # shared folder would naturally assume. Falls back to the older
    # "clients_dir" settings key (which used to hold this same folder
    # directly) so an already-configured machine doesn't silently revert to
    # the private default after this rename.
    settings = load_app_settings()
    return settings.get("shared_root_dir") or settings.get("clients_dir") or ""


def get_clients_dir() -> str:
    root = get_shared_root_dir()
    return os.path.join(root, "clients") if root else "clients"


def get_aliases_path() -> str:
    # Nested in an "aliases" subfolder (not directly in the clients folder)
    # so list_profile_names()'s flat directory scan for client profile
    # JSONs never picks it up as a fake client.
    root = get_shared_root_dir()
    if root:
        return os.path.join(root, "aliases", "company_aliases.json")
    return "aliases/company_aliases.json"


def get_jira_settings() -> dict:
    # Deliberately read from the plain local app_settings.json only — never
    # from anything under get_shared_root_dir(). An API token is a secret
    # tied to one person's Jira account; it must never end up inside the
    # clients folder a whole team may sync via OneDrive.
    settings = load_app_settings()
    return {
        "base_url": settings.get("jira_base_url", ""),
        "email": settings.get("jira_email", ""),
        "api_token": settings.get("jira_api_token", ""),
    }


def save_jira_settings(base_url: str, email: str, api_token: str) -> None:
    updated = load_app_settings()
    updated["jira_base_url"] = base_url.strip()
    updated["jira_email"] = email.strip()
    updated["jira_api_token"] = api_token
    save_app_settings(updated)

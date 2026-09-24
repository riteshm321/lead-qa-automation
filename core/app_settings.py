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


def get_convertr_account_credentials(client_name: str) -> dict:
    # Same reasoning as get_jira_settings: a live, write-capable Convertr
    # credential belongs in the plain local app_settings.json only, never
    # in the client profile JSON that lives in the shared clients folder
    # every teammate can read. Every Publisher account uses this same
    # username/password for both uploading leads and reading back
    # accepted/rejected outcomes -- there is no separate per-campaign key.
    settings = load_app_settings()
    creds = settings.get("convertr_account_credentials", {}).get(client_name, {})
    return {"username": creds.get("username", ""), "password": creds.get("password", "")}


def save_convertr_account_credentials(client_name: str, username: str, password: str) -> None:
    updated = load_app_settings()
    all_creds = updated.setdefault("convertr_account_credentials", {})
    all_creds[client_name] = {"username": username.strip(), "password": password}
    save_app_settings(updated)


def get_enhancio_client_id() -> str:
    # Unlike Convertr's per-client username/password, Enhancio uses ONE
    # shared org-wide Connected App (Enhancio-managed OAuth2, Client ID
    # only -- no secret) that every client's leads route through via their
    # own allocationUid. Still a live API credential, so it belongs in the
    # plain local app_settings.json only, same reasoning as get_jira_settings.
    settings = load_app_settings()
    return settings.get("enhancio_client_id", "")


def save_enhancio_client_id(client_id: str) -> None:
    updated = load_app_settings()
    updated["enhancio_client_id"] = client_id.strip()
    save_app_settings(updated)


def get_integrate_credentials() -> tuple[str, str]:
    # Unconfirmed whether Integrate's API Key/Secret is genuinely
    # org-wide-shared or needs to be per-client (see the design spec's
    # "Open questions") -- built as ONE shared credential for now, same
    # storage reasoning as get_jira_settings/get_enhancio_client_id: a
    # live API credential belongs in the plain local app_settings.json
    # only, never inside the shared clients folder every teammate can read.
    settings = load_app_settings()
    return settings.get("integrate_api_key", ""), settings.get("integrate_api_secret", "")


def save_integrate_credentials(api_key: str, api_secret: str) -> None:
    updated = load_app_settings()
    updated["integrate_api_key"] = api_key.strip()
    updated["integrate_api_secret"] = api_secret.strip()
    save_app_settings(updated)

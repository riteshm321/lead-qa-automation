import hashlib
import json
import os
import secrets

from core.app_settings import get_shared_root_dir
from core.atomic_io import atomic_write_json

# Under the shared OneDrive root (not local-per-machine like the Jira API
# token in app_settings.py) -- accounts must be visible from every
# machine on the team, which is the whole point of named logins for the
# activity tracker. A hashed+salted password (600k PBKDF2 iterations,
# below) isn't directly usable by anyone who reads the file the way a raw
# API token would be, so unlike the Jira token this is safe to share.
# When this app moves to a hosted server, this file-based store gets
# replaced by a real identity system.
_CREDENTIALS_SUBPATH = os.path.join("auth", "credentials.json")

# OWASP's 2023 minimum for PBKDF2-HMAC-SHA256.
_PBKDF2_ITERATIONS = 600_000


def _credentials_path() -> str:
    root = get_shared_root_dir()
    return os.path.join(root, _CREDENTIALS_SUBPATH) if root else ""


def load_users() -> dict:
    path = _credentials_path()
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_users(users: dict) -> None:
    path = _credentials_path()
    if not path:
        # No shared team folder configured on this machine yet -- nowhere
        # to durably put accounts. require_login() gates on this and
        # always sets up the shared folder before any account-creation UI
        # ever renders, so this should never actually be reached.
        return
    atomic_write_json(path, users)


def has_any_users() -> bool:
    return bool(load_users())


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS).hex()


def create_user(username: str, password: str, is_admin: bool, role: str = "") -> None:
    users = load_users()
    salt = secrets.token_hex(16)
    users[username] = {
        "salt": salt,
        "hash": _hash_password(password, bytes.fromhex(salt)),
        "is_admin": is_admin,
        "role": role.strip(),
    }
    save_users(users)


def delete_user(username: str) -> None:
    users = load_users()
    users.pop(username, None)
    save_users(users)


def update_user_role(username: str, role: str) -> None:
    users = load_users()
    if username in users:
        users[username]["role"] = role.strip()
        save_users(users)


def authenticate(username: str, password: str) -> dict | None:
    record = load_users().get(username)
    if record is None:
        return None
    actual = _hash_password(password, bytes.fromhex(record["salt"]))
    if not secrets.compare_digest(actual, record["hash"]):
        return None
    return {
        "username": username,
        "is_admin": bool(record.get("is_admin", False)),
        "role": record.get("role", ""),
    }

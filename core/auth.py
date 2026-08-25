import hashlib
import json
import os
import secrets

from core.atomic_io import atomic_write_json

# Local to this machine, not under get_shared_root_dir() -- like the Jira
# API token in app_settings.py, credentials are a secret that must never
# end up inside a OneDrive folder a whole team syncs. When this app moves
# to a hosted server, this file-based store gets replaced by a real
# identity system; for now, one machine == one set of accounts.
_CREDENTIALS_PATH = "auth/credentials.json"

# OWASP's 2023 minimum for PBKDF2-HMAC-SHA256.
_PBKDF2_ITERATIONS = 600_000


def load_users() -> dict:
    if not os.path.isfile(_CREDENTIALS_PATH):
        return {}
    with open(_CREDENTIALS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_users(users: dict) -> None:
    atomic_write_json(_CREDENTIALS_PATH, users)


def has_any_users() -> bool:
    return bool(load_users())


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS).hex()


def create_user(username: str, password: str, is_admin: bool) -> None:
    users = load_users()
    salt = secrets.token_hex(16)
    users[username] = {
        "salt": salt,
        "hash": _hash_password(password, bytes.fromhex(salt)),
        "is_admin": is_admin,
    }
    save_users(users)


def delete_user(username: str) -> None:
    users = load_users()
    users.pop(username, None)
    save_users(users)


def authenticate(username: str, password: str) -> dict | None:
    record = load_users().get(username)
    if record is None:
        return None
    actual = _hash_password(password, bytes.fromhex(record["salt"]))
    if not secrets.compare_digest(actual, record["hash"]):
        return None
    return {"username": username, "is_admin": bool(record.get("is_admin", False))}

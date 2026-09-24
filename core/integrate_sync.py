import json
import os

import pandas as pd

from core.app_settings import get_shared_root_dir
from core.atomic_io import atomic_write_json


def _normalize_email(email) -> str:
    return str(email or "").strip().lower()


def filter_already_uploaded(
    leads_df: pd.DataFrame, email_column: str, already_uploaded_emails: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Splits a leadfile into (rows_to_send, rows_already_uploaded) by
    email, so a repeated (or overlapping) upload never resends a lead
    already submitted to this client's Integrate Source. Both preserve
    leads_df's own index.
    """
    is_duplicate = leads_df[email_column].astype(str).map(_normalize_email).isin(already_uploaded_emails)
    return leads_df[~is_duplicate], leads_df[is_duplicate]


def _uploaded_emails_path(client_name: str) -> str:
    root = get_shared_root_dir()
    return os.path.join(root, "integrate_uploaded_emails", f"{client_name}.json") if root else ""


def load_uploaded_emails(client_name: str) -> set[str]:
    """Every email successfully submitted to this client's Integrate
    Source, ever -- across every teammate. Scoped per client (not per
    allocation, unlike Enhancio) since a client maps to exactly one SID.
    """
    path = _uploaded_emails_path(client_name)
    if not path or not os.path.isfile(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_uploaded_emails(client_name: str, emails: set[str]) -> None:
    path = _uploaded_emails_path(client_name)
    if not path:
        return
    existing = load_uploaded_emails(client_name)
    existing.update(_normalize_email(e) for e in emails if _normalize_email(e))
    atomic_write_json(path, sorted(existing))

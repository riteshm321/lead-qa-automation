import os

from core.app_settings import get_shared_root_dir
from core.atomic_io import atomic_write_json

# Convertr's own status vocabulary (see GET Leads v4's "leadStatus"/
# "qaResult" objects) -- a lead not yet in either bucket is still being
# processed and must never be guessed as accepted or rejected.
_ACCEPTED_STATUS_NAMES = {"valid"}
_REJECTED_STATUS_NAMES = {"invalid"}


def classify_lead(lead: dict) -> str:
    """'accepted', 'rejected', or 'pending' from a Convertr lead object's
    own leadStatus. A lead still mid-QA (any other status, or none yet)
    is 'pending' -- never written to either the Accumulated or Refund tab
    until Convertr has actually decided it.
    """
    status_name = str((lead.get("leadStatus") or {}).get("name", "")).strip().lower()
    if status_name in _ACCEPTED_STATUS_NAMES:
        return "accepted"
    if status_name in _REJECTED_STATUS_NAMES:
        return "rejected"
    return "pending"


def rejection_reason(lead: dict) -> str:
    """Best-effort human-readable reason a lead was rejected, so Refund
    Reason is never left blank for one: Convertr's own lead-flag reason if
    present, else the qaResult name, else a generic fallback.
    """
    flag = lead.get("leadFlag") or {}
    reason = flag.get("reason") or flag.get("name")
    if reason:
        return str(reason)
    qa_name = (lead.get("qaResult") or {}).get("name")
    if qa_name:
        return str(qa_name)
    return "Rejected by Convertr"


def lead_field_values(lead: dict) -> dict[str, str]:
    """Flattens one Convertr lead into {field name: value}: its core
    fields (firstName, lastName, email, telephone, ...) plus every entry
    in its "leadData" array (the custom fields submitted at upload time,
    e.g. a mapped CID or job_title) -- core fields take priority so a
    leadData entry never overwrites a same-named top-level field.
    """
    core_fields = {
        k: v for k, v in lead.items()
        if k not in ("leadData",) and not isinstance(v, (dict, list)) and v is not None
    }
    data_fields = {}
    for entry in lead.get("leadData") or []:
        name = entry.get("name")
        if name is not None:
            data_fields[name] = entry.get("value")
    return {**data_fields, **core_fields}


def lead_to_leadfile_row(lead: dict, convertr_field_to_leadfile_column: dict[str, str]) -> dict:
    """Maps one Convertr lead's fields back into leadfile-shaped columns,
    via convertr_field_to_leadfile_column ({Convertr field name: leadfile
    column name} -- the inverse of ConvertrConfig.field_mapping, which
    maps leadfile column -> Convertr field name for uploads).

    This can only recover a column if it was actually submitted as a real
    field on the Convertr form at upload time. CID deliberately isn't
    handled this way at all -- see cid_for_email/save_email_to_cid_map,
    which look it up from the leadfile used at upload time instead, since
    Convertr's own forms have no natural place for it.
    """
    values = lead_field_values(lead)
    return {
        leadfile_column: values.get(convertr_field, "")
        for convertr_field, leadfile_column in convertr_field_to_leadfile_column.items()
    }


def _normalize_email(email) -> str:
    return str(email or "").strip().lower()


def _uploaded_lookup_path(client_name: str) -> str:
    root = get_shared_root_dir()
    return os.path.join(root, "convertr_email_to_cid", f"{client_name}.json") if root else ""


def load_email_to_cid_map(client_name: str) -> dict[str, str]:
    path = _uploaded_lookup_path(client_name)
    if not path or not os.path.isfile(path):
        return {}
    import json
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_email_to_cid_map(client_name: str, email_to_cid: dict[str, object]) -> None:
    """Records which CID each email belongs to, straight from the leadfile
    used to upload to Convertr -- so reconcile can recover a returned
    lead's CID by matching its email back to this, without depending on
    Convertr's own form carrying a CID field at all (it has none
    natively). Merges into whatever's already recorded, shared across the
    team the same way load_synced_lead_ids is; a later upload for the
    same email overwrites its earlier recorded CID.
    """
    path = _uploaded_lookup_path(client_name)
    if not path:
        return
    existing = load_email_to_cid_map(client_name)
    for email, cid in email_to_cid.items():
        normalized = _normalize_email(email)
        if normalized:
            existing[normalized] = str(cid)
    atomic_write_json(path, existing)


def cid_for_email(email: str, email_to_cid: dict[str, str]) -> str:
    return email_to_cid.get(_normalize_email(email), "")


def _synced_leads_path(client_name: str) -> str:
    root = get_shared_root_dir()
    return os.path.join(root, "convertr_synced_leads", f"{client_name}.json") if root else ""


def load_synced_lead_ids(client_name: str) -> set[str]:
    """Convertr lead IDs already written to Accumulated/Refund for this
    client, across every teammate -- shared (not per-machine) so two
    people reconciling the same client never double-append the same
    lead. A repeated sync only needs to act on IDs not in this set.
    """
    path = _synced_leads_path(client_name)
    if not path or not os.path.isfile(path):
        return set()
    import json
    with open(path, "r", encoding="utf-8") as f:
        return set(json.load(f))


def mark_leads_synced(client_name: str, lead_ids: list[str]) -> None:
    path = _synced_leads_path(client_name)
    if not path:
        return
    existing = load_synced_lead_ids(client_name)
    existing.update(str(lead_id) for lead_id in lead_ids)
    atomic_write_json(path, sorted(existing))

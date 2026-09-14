import json
import os

import pandas as pd

from core.app_settings import get_shared_root_dir
from core.atomic_io import atomic_write_json


def rejection_reason_from_result(result: dict) -> str:
    """Best-effort human-readable reason a lead was rejected, so Refund
    Reason is never left blank for one: Convertr's own failed-job
    messages from get_lead_result, joined together, else a generic
    fallback.
    """
    reasons = [str(r) for r in (result.get("reasons") or []) if r]
    if reasons:
        return "; ".join(reasons)
    return "Rejected by Convertr"


def select_rows_for_test_mode(
    leads_df: pd.DataFrame, cid_column: str, cid_to_campaign_id: dict[str, str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """For the Upload page's test mode: exactly one row per unique
    Convertr campaign (SID), not one per CID -- several CIDs commonly
    share one campaign (e.g. 5 CIDs -> one SID), and the point of a test
    run is to touch each real campaign exactly once, not once per CID.

    Returns (rows_to_send, rows_skipped), both preserving leads_df's own
    index. A CID with no entry in cid_to_campaign_id (no campaign mapped
    at all) is left out of both -- the caller reports that separately,
    it has nothing to do with test-mode's per-SID limiting.
    """
    seen_campaign_ids: set[str] = set()
    send_indices, skip_indices = [], []
    for idx, cid in leads_df[cid_column].astype(str).items():
        campaign_id = cid_to_campaign_id.get(cid)
        if campaign_id is None:
            continue
        if campaign_id in seen_campaign_ids:
            skip_indices.append(idx)
        else:
            seen_campaign_ids.add(campaign_id)
            send_indices.append(idx)
    return leads_df.loc[send_indices], leads_df.loc[skip_indices]


def _pending_leads_path(client_name: str) -> str:
    root = get_shared_root_dir()
    return os.path.join(root, "convertr_pending_leads", f"{client_name}.json") if root else ""


def load_pending_leads(client_name: str) -> dict[str, dict]:
    """Convertr lead IDs uploaded but not yet resolved (or resolved but
    not yet written) for this client, across every teammate -- {lead_id:
    the full original leadfile row that was submitted for it}. The
    Publisher API has no bulk "list leads" call, and returns nothing at
    all for an accepted lead, so the only reliable source for a decided
    lead's data is what we ourselves submitted -- reconcile polls each of
    these ids via get_lead_result instead of pulling a whole campaign's
    leads back from Convertr.
    """
    path = _pending_leads_path(client_name)
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_pending_leads(client_name: str, lead_id_to_row: dict[str, dict]) -> None:
    path = _pending_leads_path(client_name)
    if not path:
        return
    existing = load_pending_leads(client_name)
    existing.update({str(lead_id): row for lead_id, row in lead_id_to_row.items()})
    atomic_write_json(path, existing)


def remove_pending_leads(client_name: str, lead_ids: list[str]) -> None:
    """Called once a pending lead's outcome has actually been written to
    Accumulated/Refund -- removing it here is what prevents a repeated
    sync from re-polling (and re-writing) the same lead.
    """
    path = _pending_leads_path(client_name)
    if not path:
        return
    existing = load_pending_leads(client_name)
    for lead_id in lead_ids:
        existing.pop(str(lead_id), None)
    atomic_write_json(path, existing)

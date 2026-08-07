import pandas as pd

from core.check_result import CheckOutcome
from core.models import FieldMapping, LeadcapConfig


def check_leadcap(
    new_leads: pd.DataFrame,
    field_mapping: FieldMapping,
    config: LeadcapConfig,
    purchased_reports: dict[str, pd.DataFrame],
) -> CheckOutcome:
    outcome = CheckOutcome()
    if not config.enabled:
        return outcome

    for idx, row in new_leads.iterrows():
        cid = str(row.get(field_mapping.cid, "")).strip()

        if config.segmented:
            segment = next((s for s in config.segments if cid in s.cids), None)
            if segment is None:
                continue
            report = purchased_reports.get(segment.name)
            cap = segment.cap
            relevant_cids = segment.cids
        else:
            report = purchased_reports.get("_flat_")
            cap = config.flat_cap
            relevant_cids = None

        if report is None or cap is None or config.purchased_report_cid_column not in report.columns:
            continue

        cid_col = report[config.purchased_report_cid_column].astype(str).str.strip()
        count = cid_col.isin(relevant_cids).sum() if relevant_cids is not None else (cid_col == cid).sum()

        if count >= cap:
            outcome.fail[idx] = "Leadcap exceeded"

    return outcome


def validate_purchased_report_cids(report: pd.DataFrame, expected_cids: list[str], cid_column: str) -> list[str]:
    actual = set(report[cid_column].astype(str).str.strip().unique())
    expected = set(expected_cids)
    return sorted(actual - expected)

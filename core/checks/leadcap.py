import pandas as pd

from core.check_result import CheckOutcome
from core.matching import extract_domain
from core.models import FieldMapping, LeadcapConfig


def _norm_cid(value) -> str:
    # CSVs are read without dtype=str, so a CID column with any blank cell
    # comes back as floats ("120653.0") and never equals the "120653" on
    # the other side - which silently skipped the whole leadcap check.
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return "" if text.lower() == "nan" else text


def _resolve_scope(cid: str, config: LeadcapConfig):
    if config.segmented:
        segment = next((s for s in config.segments if cid in s.cids), None)
        if segment is None:
            return None, None, None
        return segment.name, segment.cap, segment.cids
    return "_flat_", config.flat_cap, None


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
        cid = _norm_cid(row.get(field_mapping.cid, ""))
        report_key, cap, relevant_cids = _resolve_scope(cid, config)
        if report_key is None:
            continue

        report = purchased_reports.get(report_key)
        if report is None or cap is None or config.purchased_report_cid_column not in report.columns:
            continue

        cid_col = report[config.purchased_report_cid_column].map(_norm_cid)
        cid_mask = cid_col.isin([_norm_cid(c) for c in relevant_cids]) if relevant_cids is not None else (cid_col == cid)

        domain_pass_failed = False
        if config.purchased_report_email_column in report.columns:
            lead_domain = extract_domain(str(row.get(field_mapping.email, "")))
            domain_col = report[config.purchased_report_email_column].astype(str).map(extract_domain)
            domain_count = (cid_mask & (domain_col == lead_domain)).sum()
            if domain_count > cap:
                outcome.fail[idx] = "Leadcap exceeded"
                domain_pass_failed = True

        if domain_pass_failed:
            continue

        if config.check_company_name and config.purchased_report_company_column in report.columns:
            lead_company = str(row.get(field_mapping.company, "") or "").strip().lower()
            if lead_company:
                company_col = report[config.purchased_report_company_column].astype(str).str.strip().str.lower()
                company_count = (cid_mask & (company_col == lead_company)).sum()
                if company_count > cap:
                    outcome.fail[idx] = "Leadcap Exceed - By Company Name"

    return outcome


def validate_purchased_report_cids(report: pd.DataFrame, expected_cids: list[str], cid_column: str) -> list[str]:
    actual = set(report[cid_column].map(_norm_cid).unique()) - {""}
    expected = set(expected_cids)
    return sorted(actual - expected)

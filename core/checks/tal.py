import pandas as pd

from core.check_result import CheckOutcome
from core.matching import extract_domain, company_names_match
from core.models import FieldMapping, TalConfig


def _resolve_tal_df(cid: str, config: TalConfig, tal_sheets: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    if config.segmented:
        segment = next((s for s in config.segments if cid in s.cids), None)
        if segment is None:
            return None
        return tal_sheets.get(segment.sheet_name)
    return tal_sheets.get(config.flat_sheet_name)


def check_tal(
    new_leads: pd.DataFrame,
    field_mapping: FieldMapping,
    config: TalConfig,
    tal_sheets: dict[str, pd.DataFrame],
    alias_groups: list[list[str]],
) -> CheckOutcome:
    outcome = CheckOutcome()
    if not config.enabled:
        return outcome

    for idx, row in new_leads.iterrows():
        cid = str(row.get(field_mapping.cid, "")).strip()
        tal_df = _resolve_tal_df(cid, config, tal_sheets)
        if tal_df is None:
            continue

        domains = set()
        if config.domain_column in tal_df.columns:
            domains = set(tal_df[config.domain_column].astype(str).str.strip().str.lower())

        email = str(row.get(field_mapping.email, "") or "")
        domain = extract_domain(email)
        domain_found = domain in domains

        if not domain_found:
            outcome.fail[idx] = "TAL - not found"
            continue

        if config.check_company_name:
            company = str(row.get(field_mapping.company, "") or "")
            companies = list(tal_df[config.company_column].astype(str)) if config.company_column in tal_df.columns else []
            status = "no_match"
            for candidate in companies:
                result = company_names_match(company, candidate, alias_groups)
                if result.status == "match":
                    status = "match"
                    break
                if result.status == "review":
                    status = "review"
            if status == "no_match":
                outcome.fail[idx] = "TAL - company not found"
            elif status == "review":
                outcome.review[idx] = "TAL - company name ambiguous match"

    return outcome

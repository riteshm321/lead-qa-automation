import pandas as pd

from core.check_result import CheckOutcome
from core.matching import extract_domain, company_names_match
from core.models import FieldMapping, ExclusionConfig


def check_exclusion(
    new_leads: pd.DataFrame,
    field_mapping: FieldMapping,
    config: ExclusionConfig,
    exclusion_df: pd.DataFrame,
    alias_groups: list[list[str]],
) -> CheckOutcome:
    outcome = CheckOutcome()
    if not config.enabled:
        return outcome

    domains = set()
    if config.domain_column in exclusion_df.columns:
        domains = set(exclusion_df[config.domain_column].astype(str).str.strip().str.lower())

    companies: list[str] = []
    if config.check_company_name and config.company_column in exclusion_df.columns:
        companies = list(exclusion_df[config.company_column].astype(str))

    for idx, row in new_leads.iterrows():
        email = str(row.get(field_mapping.email, "") or "")
        domain = extract_domain(email)
        reasons = []

        if domain and domain in domains:
            reasons.append("Exclusion - domain")

        if config.check_company_name:
            company = str(row.get(field_mapping.company, "") or "")
            status = "no_match"
            for candidate in companies:
                result = company_names_match(company, candidate, alias_groups)
                if result.status == "match":
                    status = "match"
                    break
                if result.status == "review":
                    status = "review"
            if status == "match":
                reasons.append("Exclusion - company")
            elif status == "review" and not reasons:
                outcome.review[idx] = "Exclusion - company name ambiguous match"

        if reasons:
            outcome.fail[idx] = "; ".join(reasons)

    return outcome

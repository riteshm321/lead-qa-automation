import pandas as pd

from core.check_result import CheckOutcome
from core.matching import extract_domain, company_names_match
from core.models import FieldMapping, SuppressionConfig


def check_suppression(
    new_leads: pd.DataFrame,
    field_mapping: FieldMapping,
    config: SuppressionConfig,
    suppression_df: pd.DataFrame,
    alias_groups: list[list[str]],
) -> CheckOutcome:
    outcome = CheckOutcome()
    if not config.enabled:
        return outcome

    domains = set()
    if config.check_domain and config.domain_column in suppression_df.columns:
        domains = set(suppression_df[config.domain_column].astype(str).str.strip().str.lower())

    emails = set()
    if config.check_email and config.email_column in suppression_df.columns:
        emails = set(suppression_df[config.email_column].astype(str).str.strip().str.lower())

    companies: list[str] = []
    if config.check_company_name and config.company_column in suppression_df.columns:
        companies = list(suppression_df[config.company_column].astype(str))

    for idx, row in new_leads.iterrows():
        email = str(row.get(field_mapping.email, "") or "").strip().lower()
        domain = extract_domain(email)
        reasons = []

        if config.check_domain and domain and domain in domains:
            reasons.append("Suppression - domain")
        if config.check_email and email and email in emails:
            reasons.append("Suppression - email")

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
                reasons.append("Suppression - company")
            elif status == "review" and not reasons:
                outcome.review[idx] = "Suppression - company name ambiguous match"

        if reasons:
            outcome.fail[idx] = "; ".join(reasons)

    return outcome

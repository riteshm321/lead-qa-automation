import pandas as pd

from core.check_result import CheckOutcome
from core.matching import extract_domain, company_names_match
from core.models import FieldMapping, TalConfig


def _applicable_sources(cid: str, config: TalConfig) -> list:
    return [s for s in config.sources if not s.cids or cid in s.cids]


def check_tal(
    new_leads: pd.DataFrame,
    field_mapping: FieldMapping,
    config: TalConfig,
    sources_data: dict[str, pd.DataFrame],
    alias_groups: list[list[str]],
) -> CheckOutcome:
    outcome = CheckOutcome()
    if not config.enabled:
        return outcome

    for idx, row in new_leads.iterrows():
        cid = str(row.get(field_mapping.cid, "")).strip()
        applicable = _applicable_sources(cid, config)
        if not applicable:
            continue

        domains: set[str] = set()
        companies: list[str] = []
        for source in applicable:
            df = sources_data.get(source.name)
            if df is None:
                continue
            if source.domain_column in df.columns:
                domains |= set(df[source.domain_column].astype(str).str.strip().str.lower())
            if config.check_company_name and source.company_column in df.columns:
                companies.extend(list(df[source.company_column].astype(str)))

        email = str(row.get(field_mapping.email, "") or "")
        domain = extract_domain(email)
        domain_found = domain in domains

        if not domain_found:
            outcome.fail[idx] = "TAL - not found"
            continue

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
            if status == "no_match":
                outcome.fail[idx] = "TAL - company not found"
            elif status == "review":
                outcome.review[idx] = "TAL - company name ambiguous match"

    return outcome

import pandas as pd

from core.check_result import CheckOutcome
from core.models import FieldMapping, DedupeListConfig


def _applicable_sources(cid: str, config: DedupeListConfig) -> list:
    return [s for s in config.sources if not s.cids or cid in s.cids]


def check_dedupe_list(
    new_leads: pd.DataFrame,
    field_mapping: FieldMapping,
    config: DedupeListConfig,
    sources_data: dict[str, pd.DataFrame],
) -> CheckOutcome:
    outcome = CheckOutcome()
    if not config.enabled:
        return outcome

    for idx, row in new_leads.iterrows():
        cid = str(row.get(field_mapping.cid, "")).strip()
        applicable = _applicable_sources(cid, config)
        if not applicable:
            continue

        emails: set[str] = set()
        for source in applicable:
            df = sources_data.get(source.name)
            if df is None:
                continue
            if source.email_column in df.columns:
                emails |= set(df[source.email_column].astype(str).str.strip().str.lower())

        email = str(row.get(field_mapping.email, "") or "").strip().lower()
        if email and email in emails:
            outcome.fail[idx] = "Dedupe list - email match"

    return outcome

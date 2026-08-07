import pandas as pd

from core.check_result import CheckOutcome
from core.models import FieldMapping, DedupeListConfig


def check_dedupe_list(
    new_leads: pd.DataFrame,
    field_mapping: FieldMapping,
    config: DedupeListConfig,
    dedupe_df: pd.DataFrame,
) -> CheckOutcome:
    outcome = CheckOutcome()
    if not config.enabled:
        return outcome

    emails = set()
    if config.email_column in dedupe_df.columns:
        emails = set(dedupe_df[config.email_column].astype(str).str.strip().str.lower())

    for idx, row in new_leads.iterrows():
        email = str(row.get(field_mapping.email, "") or "").strip().lower()
        if email and email in emails:
            outcome.fail[idx] = "Dedupe list - email match"

    return outcome

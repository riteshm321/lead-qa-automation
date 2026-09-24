import pandas as pd

from core.check_result import CheckOutcome, ReviewDetail
from core.excel_io import normalize_header_text, find_passthrough_lead_column
from core.models import FieldMapping, LeadTemplateMappingConfig


def _resolve_mandatory_source(rule, lead_headers_norm: dict[str, str]) -> str | None:
    if rule.source_column and rule.source_column in lead_headers_norm.values():
        return rule.source_column
    return find_passthrough_lead_column(normalize_header_text(rule.template_column), lead_headers_norm)


def check_lead_template_mandatory_columns(
    new_leads: pd.DataFrame, field_mapping: FieldMapping, config: LeadTemplateMappingConfig,
) -> CheckOutcome:
    """A lead with a blank value in a column the user marked mandatory
    (LeadTemplateColumnRule.mandatory) is flagged for review instead of
    silently written blank. Resolution of which leadfile column supplies
    a mandatory field reuses the exact same manual-override-then-fuzzy-
    match chain append_leads itself uses (find_passthrough_lead_column),
    so this check's verdict always matches what would actually be written.
    A mandatory column with NO resolvable leadfile column at all flags
    every lead once (there is nothing per-row to check); a mandatory
    column that DOES resolve flags only the rows whose value there is
    blank/NaN.
    """
    outcome = CheckOutcome()
    mandatory_rules = [r for r in config.rules if r.mandatory]
    if not mandatory_rules:
        return outcome

    lead_headers_norm = {normalize_header_text(h): h for h in new_leads.columns}

    for rule in mandatory_rules:
        source_col = _resolve_mandatory_source(rule, lead_headers_norm)
        if source_col is None:
            for idx in new_leads.index:
                outcome.review.setdefault(idx, ReviewDetail(
                    check="Lead Template Mapping",
                    message=f"No leadfile column found for mandatory field '{rule.template_column}'",
                ))
            continue
        for idx, value in new_leads[source_col].items():
            if pd.isna(value) or str(value).strip() == "":
                outcome.review.setdefault(idx, ReviewDetail(
                    check="Lead Template Mapping",
                    message=f"'{rule.template_column}' is required but blank",
                ))

    return outcome

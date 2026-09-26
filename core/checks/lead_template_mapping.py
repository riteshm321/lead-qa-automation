import pandas as pd

from core.check_result import CheckOutcome, ReviewDetail
from core.excel_io import normalize_header_text, resolve_one_header_source
from core.models import FieldMapping, LeadTemplateMappingConfig


def check_lead_template_mandatory_columns(
    new_leads: pd.DataFrame, field_mapping: FieldMapping, config: LeadTemplateMappingConfig,
    target_field_mapping: FieldMapping | None = None,
) -> CheckOutcome:
    """A lead with a blank value in a column the user marked mandatory
    (LeadTemplateColumnRule.mandatory) is flagged for review instead of
    silently written blank. Resolution of which leadfile column supplies
    a mandatory field reuses the exact same manual-override -> target-role
    -> synonym -> fuzzy-match chain append_leads itself uses
    (resolve_one_header_source), so this check's verdict always matches
    what would actually be written -- e.g. marking "Email Address"
    mandatory resolves through target_field_mapping/field_mapping the same
    way append_leads would, instead of only trying a manual override then
    jumping straight to fuzzy matching. A mandatory column with NO
    resolvable leadfile column at all flags every lead once (there is
    nothing per-row to check); a mandatory column that DOES resolve flags
    only the rows whose value there is blank/NaN.
    """
    outcome = CheckOutcome()
    mandatory_rules = [r for r in config.rules if r.mandatory]
    if not mandatory_rules:
        return outcome

    for rule in mandatory_rules:
        manual_overrides = (
            {normalize_header_text(rule.template_column): rule.source_column} if rule.source_column else None
        )
        source_col = resolve_one_header_source(
            rule.template_column, new_leads, field_mapping, target_field_mapping, manual_overrides)
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

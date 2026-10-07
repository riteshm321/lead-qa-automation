import pandas as pd

from core.check_result import CheckOutcome, ReviewDetail
from core.excel_io import normalize_header_text, resolve_one_header_source
from core.models import FieldMapping, LeadTemplateMappingConfig
from core.phone_format import is_phone_column, looks_excel_mangled


def _phone_sources(
    new_leads: pd.DataFrame, field_mapping: FieldMapping, config: LeadTemplateMappingConfig | None,
    target_field_mapping: FieldMapping | None = None,
) -> list[tuple[str, str]]:
    """(label shown in the message, leadfile column) pairs to scan: every
    Lead Template rule for a phone column that resolves to a leadfile column
    (same resolution as check_lead_template_mandatory_columns), plus every
    leadfile column whose own name looks like a phone column, so the check
    still works for a client with no Lead Template rules at all."""
    sources: list[tuple[str, str]] = []
    seen: set[str] = set()
    for rule in (config.rules if config else []):
        if not is_phone_column(rule.template_column):
            continue
        manual_overrides = (
            {normalize_header_text(rule.template_column): rule.source_column} if rule.source_column else None
        )
        source_col = resolve_one_header_source(
            rule.template_column, new_leads, field_mapping, target_field_mapping, manual_overrides)
        if source_col is not None and source_col in new_leads.columns and source_col not in seen:
            seen.add(source_col)
            sources.append((rule.template_column, source_col))
    for col in new_leads.columns:
        if col not in seen and is_phone_column(col):
            seen.add(col)
            sources.append((str(col), col))
    return sources


def phone_check_applies(
    new_leads: pd.DataFrame, field_mapping: FieldMapping, config: LeadTemplateMappingConfig | None,
    target_field_mapping: FieldMapping | None = None,
) -> bool:
    """Whether check_excel_mangled_phone_numbers has anything to scan --
    run_pipeline and Run Check's progress-bar stage list both use this so
    they always agree on whether the stage exists."""
    return bool(_phone_sources(new_leads, field_mapping, config, target_field_mapping))


def check_excel_mangled_phone_numbers(
    new_leads: pd.DataFrame, field_mapping: FieldMapping, config: LeadTemplateMappingConfig | None,
    target_field_mapping: FieldMapping | None = None,
) -> CheckOutcome:
    """Flags (Needs Review, approvable) a lead whose phone number Excel has
    already damaged -- scientific notation or zeroed-out trailing digits
    (core.phone_format.looks_excel_mangled). At most one flag per lead."""
    outcome = CheckOutcome()
    for label, source_col in _phone_sources(new_leads, field_mapping, config, target_field_mapping):
        for idx, value in new_leads[source_col].items():
            if idx in outcome.review or pd.isna(value):
                continue
            if looks_excel_mangled(value):
                outcome.review[idx] = ReviewDetail(
                    check="Phone Number",
                    message=(f"'{label}' looks damaged by Excel ({value}) - the last digits may have been "
                             "replaced with zeros. Fix the number in the leadfile and run the check again"),
                )
    return outcome

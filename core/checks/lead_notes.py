import pandas as pd

from core.check_result import CheckOutcome, ReviewDetail
from core.custom_questions import normalize_question
from core.lead_notes import MISMATCH, NOT_MENTIONED, check_field
from core.models import LeadNotesConfig, LeadNotesField

_CHECK_NAME = "Lead Notes"
_KIND_LABELS = {
    "email": "email", "phone": "phone", "first_name": "first name", "last_name": "last name",
    "company": "company", "job_title": "job title",
}


def _cell(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _resolve_column(df: pd.DataFrame, name: str):
    """The leadfile column named `name`, matched loosely (case, spacing,
    punctuation and underscores ignored), or None."""
    if name in df.columns:
        return name
    wanted = normalize_question(name)
    if not wanted:
        return None
    return next((col for col in df.columns if normalize_question(col) == wanted), None)


def _field_label(f: LeadNotesField) -> str:
    return _KIND_LABELS.get(f.kind) or f.label.strip() or f.column


class _Findings:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.reviews: list[ReviewDetail] = []

    def add(self, action: str, message: str, lead_value: str = "", found: str = "",
            score: float | None = None) -> None:
        if action == "refund":
            self.fails.append(message)
        else:
            self.reviews.append(ReviewDetail(check=_CHECK_NAME, message=message, lead_value=lead_value,
                                             candidate_value=found, candidate_context="the lead notes",
                                             score=score))


def check_lead_notes(new_leads: pd.DataFrame, config: LeadNotesConfig, alias_groups=()) -> CheckOutcome:
    """Verifies each lead's narrative notes against the lead's own column
    values (see core/lead_notes.py for how each kind is recognized). A
    contradicting email/phone, or a required field the notes don't mention,
    gets that field's configured action (Refund or Needs Review); optional
    fields are only flagged on a contradiction. Blank notes count once,
    with the strictest action among the required fields."""
    outcome = CheckOutcome()
    fields = [f for f in config.fields if f.column.strip()]
    if not config.enabled or not config.notes_column.strip() or not fields:
        return outcome

    required_actions = {f.action for f in fields if f.required}
    blank_action = "refund" if "refund" in required_actions else "review"
    notes_col = _resolve_column(new_leads, config.notes_column.strip())
    field_cols = [(f, _resolve_column(new_leads, f.column.strip())) for f in fields]

    findings = {idx: _Findings() for idx in new_leads.index}
    for idx, row in new_leads.iterrows():
        found = findings[idx]
        if notes_col is None:
            if required_actions:
                found.add(blank_action, f"Notes: '{config.notes_column.strip()}' column not found")
            continue
        notes = _cell(row[notes_col])
        if not notes:
            if required_actions:
                found.add(blank_action, f"Notes: '{notes_col}' is blank")
            continue
        for f, col in field_cols:
            if col is None:
                found.add(f.action, f"Notes: '{f.column.strip()}' column not found")
                continue
            expected = _cell(row[col])
            result = check_field(f.kind, notes, expected, alias_groups)
            label = _field_label(f)
            if result.status == MISMATCH:
                found.add(f.action, f"Notes: {label} {result.found} doesn't match lead {label} {expected}",
                          lead_value=expected, found=result.found, score=result.score)
            elif result.status == NOT_MENTIONED and f.required:
                message = (f"Notes: {label} '{expected}' not mentioned" if f.kind == "value"
                           else f"Notes: {label} not mentioned")
                found.add(f.action, message, lead_value=expected, score=result.score)

    for idx, found in findings.items():
        if found.fails:
            outcome.fail[idx] = "; ".join(found.fails)
        elif found.reviews:
            first = found.reviews[0]
            outcome.review[idx] = ReviewDetail(
                check=_CHECK_NAME, message="; ".join(r.message for r in found.reviews),
                lead_value=first.lead_value, candidate_value=first.candidate_value,
                candidate_context=first.candidate_context, score=first.score,
            )
    return outcome

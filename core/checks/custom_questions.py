import pandas as pd
from rapidfuzz import fuzz

from core.check_result import CheckOutcome, ReviewDetail
from core.custom_questions import (
    NEAR_MISS_THRESHOLD, locate_questions, match_answers, normalize_question,
)
from core.models import CustomQuestionRule, CustomQuestionsConfig

_CHECK_NAME = "Custom Questions"


def _cell(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _resolve_column(df: pd.DataFrame, name: str, allow_fuzzy: bool) -> tuple[str | None, float]:
    """The leadfile column matching `name` loosely (case, whitespace,
    punctuation and "1."/"Q1:" numbering ignored) with score 100, else --
    when allow_fuzzy -- the closest header at or above NEAR_MISS_THRESHOLD
    with its score, else (None, 0)."""
    wanted = normalize_question(name)
    if not wanted:
        return None, 0.0
    best_col, best_score = None, 0.0
    for col in df.columns:
        header = normalize_question(col)
        if header == wanted:
            return col, 100.0
        if allow_fuzzy:
            score = fuzz.ratio(header, wanted)
            if score > best_score:
                best_col, best_score = col, score
    if allow_fuzzy and best_score >= NEAR_MISS_THRESHOLD:
        return best_col, float(best_score)
    return None, 0.0


def _plural(n: int) -> str:
    return f"{n} answer" if n == 1 else f"{n} answers"


def _count_problem(label: str, rule: CustomQuestionRule, n: int) -> str | None:
    k = rule.count
    if rule.count_rule == "exactly" and n != k:
        return f"{label}: {_plural(n)} given, exactly {k} required"
    if rule.count_rule == "at_least" and n < k:
        return f"{label}: {_plural(n)} given, at least {k} required"
    if rule.count_rule == "at_most" and n > k:
        return f"{label}: {_plural(n)} given, at most {k} allowed"
    return None


class _LeadFindings:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.reviews: list[ReviewDetail] = []

    def review(self, message: str, lead_value: str = "", candidate_value: str = "",
               candidate_context: str = "", score: float | None = None) -> None:
        self.reviews.append(ReviewDetail(check=_CHECK_NAME, message=message, lead_value=lead_value,
                                         candidate_value=candidate_value,
                                         candidate_context=candidate_context, score=score))


def _evaluate_answer(label: str, rule: CustomQuestionRule, answer: str, findings: _LeadFindings) -> None:
    if not answer:
        findings.fails.append(f"{label} not answered")
        return
    if rule.mode == "exists":
        return
    match = match_answers(answer, rule.allowed_answers, rule.separator)
    for given in match.unrecognized:
        findings.fails.append(f"{label}: '{given}' is not an allowed answer")
    for given, closest, score in match.near_misses:
        findings.review(f"{label}: '{given}' is close to allowed answer '{closest}'",
                        lead_value=given, candidate_value=closest,
                        candidate_context="an allowed answer", score=score)
    problem = _count_problem(label, rule, match.count)
    if problem:
        findings.fails.append(problem)


def _question_text_review(label: str, actual: str, expected: str, score: float, findings: _LeadFindings) -> None:
    findings.review(f"{label} question text doesn't exactly match the configured question",
                    lead_value=actual, candidate_value=expected,
                    candidate_context="the configured question", score=score)


def check_custom_questions(new_leads: pd.DataFrame, config: CustomQuestionsConfig) -> CheckOutcome:
    """Validates each lead's answers to the client's configured custom
    questions. Clear failures (question missing/unanswered, an answer that
    isn't allowed, wrong number of answers) refund the lead; near misses
    (slightly reworded question, typo'd answer) send it to Needs Review.
    Every rule's problems on one lead combine into one reason, labelled
    CQ1, CQ2, ... by the rule's position in the config."""
    outcome = CheckOutcome()
    if not config.enabled or not config.rules:
        return outcome

    findings = {idx: _LeadFindings() for idx in new_leads.index}

    # Combined-format rules sharing one cell are located together, so each
    # question's answers stop where the next configured question begins.
    combined_groups: dict[str, list[int]] = {}
    for n, rule in enumerate(config.rules):
        if rule.format == "combined":
            col, _ = _resolve_column(new_leads, rule.column, allow_fuzzy=False)
            if col is not None:
                combined_groups.setdefault(col, []).append(n)
    combined_located: dict[int, dict] = {n: {} for group in combined_groups.values() for n in group}
    for col, rule_numbers in combined_groups.items():
        questions = [config.rules[n].question_text for n in rule_numbers]
        for idx, value in new_leads[col].items():
            located = locate_questions(_cell(value), questions)
            for position, n in enumerate(rule_numbers):
                if position in located:
                    combined_located[n][idx] = located[position]

    for n, rule in enumerate(config.rules):
        label = f"CQ{n + 1}"
        if rule.format == "combined":
            if n not in combined_located:
                for idx in new_leads.index:
                    findings[idx].fails.append(f"{label} missing")
                continue
            for idx in new_leads.index:
                located = combined_located[n].get(idx)
                if located is None:
                    findings[idx].fails.append(f"{label} missing")
                    continue
                if located.score < 100:
                    _question_text_review(label, located.matched_text, rule.question_text,
                                          located.score, findings[idx])
                _evaluate_answer(label, rule, located.segment, findings[idx])

        elif rule.format == "columns":
            q_col, _ = _resolve_column(new_leads, rule.question_column, allow_fuzzy=False)
            a_col, _ = _resolve_column(new_leads, rule.column, allow_fuzzy=False)
            expected = normalize_question(rule.question_text)
            for idx, row in new_leads.iterrows():
                question = _cell(row[q_col]) if q_col is not None else ""
                if q_col is None or a_col is None or not question:
                    findings[idx].fails.append(f"{label} missing")
                    continue
                if expected:
                    actual = normalize_question(question)
                    if actual != expected:
                        score = fuzz.ratio(actual, expected)
                        if score < NEAR_MISS_THRESHOLD:
                            findings[idx].fails.append(f"{label} question text doesn't match")
                            continue
                        _question_text_review(label, question, rule.question_text, score, findings[idx])
                _evaluate_answer(label, rule, _cell(row[a_col]), findings[idx])

        else:  # "header": the column header IS the question
            col, score = _resolve_column(new_leads, rule.column or rule.question_text, allow_fuzzy=True)
            if col is None:
                for idx in new_leads.index:
                    findings[idx].fails.append(f"{label} missing")
                continue
            for idx, value in new_leads[col].items():
                if score < 100:
                    _question_text_review(label, str(col), rule.column or rule.question_text,
                                          score, findings[idx])
                _evaluate_answer(label, rule, _cell(value), findings[idx])

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

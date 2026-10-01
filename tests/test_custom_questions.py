"""Pure-logic tests for core/custom_questions.py -- normalization, answer
matching against an allowed list, combined-cell question location and
"Detect from leadfile" rule suggestion. All data is synthetic, mimicking
only the FORMAT of real survey-question leadfile columns."""
import pandas as pd

from core.custom_questions import (
    normalize_question, normalize_answer, split_answers, match_answers, locate_questions,
    detect_question_rules,
)

Q1 = "1. What are your biggest challenges when deploying widgets for your customers?"
A_SEC = "a) Widget Security / API Governance & Compliance (Injection / leakage / guardrails)"
A_INT = "b) Integration with Existing Infrastructure, Pipelines & Data (Hybrid/multicloud / latency)"
A_COST = "c) High Compute & Platform Costs (Token use / cluster utilization)"
A_SKILL = "d) Internal Skills Shortage & Bandwidth"
ALLOWED = [A_SEC, A_INT, A_COST, A_SKILL]


# --- normalization -----------------------------------------------------------

def test_normalize_question_ignores_numbering_case_whitespace_and_punctuation():
    assert normalize_question("1. What is your  ROLE?") == normalize_question("what is your role")
    assert normalize_question("Q1: What is your role?") == "what is your role"
    assert normalize_question("Q2 What is your role") == "what is your role"
    assert normalize_question("  3)  What’s your role ?") == normalize_question("What's your role")


def test_normalize_question_keeps_a_leading_number_that_is_not_numbering():
    assert normalize_question("2025 budget planned?") == "2025 budget planned"


def test_normalize_answer_strips_letter_code_prefixes_either_style():
    assert normalize_answer("a) Yes, definitely") == "yes definitely"
    assert normalize_answer("(b) Yes, definitely") == "yes definitely"
    assert normalize_answer("C. Yes, definitely") == "yes definitely"
    assert normalize_answer("Yes, definitely") == "yes definitely"


# --- splitting (fallback counting / detection) --------------------------------

def test_split_answers_prefers_letter_codes_over_separator():
    cell = f"{A_SEC}, {A_INT}"
    assert split_answers(cell, ",") == [A_SEC, A_INT]


def test_split_answers_falls_back_to_separator_without_letter_codes():
    assert split_answers("Red; Green ;Blue;", ";") == ["Red", "Green", "Blue"]
    assert split_answers("  ", ",") == []


# --- matching against the allowed list ----------------------------------------

def test_match_answers_handles_answers_that_contain_the_separator():
    m = match_answers(f"{A_SEC}, {A_INT}", ALLOWED, ",")
    assert m.matched == [A_SEC, A_INT]
    assert m.unrecognized == [] and m.near_misses == []
    assert m.count == 2


def test_match_answers_tolerates_letter_codes_missing_on_either_side():
    no_codes_in_cell = "Widget Security / API Governance & Compliance (Injection / leakage / guardrails)"
    assert match_answers(no_codes_in_cell, ALLOWED, ",").matched == [A_SEC]
    allowed_without_codes = ["Red apple", "Green pear"]
    assert match_answers("a) Red apple, b) Green pear", allowed_without_codes, ",").matched == [
        "Red apple", "Green pear"]


def test_match_answers_prefers_longest_match():
    allowed = ["Cloud", "Cloud Security"]
    m = match_answers("Cloud Security", allowed, ",")
    assert m.matched == ["Cloud Security"]
    assert m.count == 1


def test_match_answers_reports_unrecognized_leftover_text():
    m = match_answers(f"{A_SEC}, Totally unrelated thing", ALLOWED, ",")
    assert m.matched == [A_SEC]
    assert m.unrecognized == ["Totally unrelated thing"]
    assert m.count == 2


def test_match_answers_flags_typo_as_near_miss():
    typo = "d) Internal Skils Shortage & Bandwith"
    m = match_answers(f"{A_SEC}, {typo}", ALLOWED, ",")
    assert m.matched == [A_SEC]
    assert len(m.near_misses) == 1
    given, closest, score = m.near_misses[0]
    assert given == typo and closest == A_SKILL and score >= 85
    assert m.unrecognized == []
    assert m.count == 2


def test_match_answers_counts_duplicate_answer_once():
    assert match_answers("Red apple; Red apple", ["Red apple"], ";").count == 1


def test_match_answers_without_allowed_list_counts_by_splitting():
    m = match_answers("Red; Green; Blue", [], ";")
    assert m.matched == [] and m.unrecognized == []
    assert m.count == 3


# --- combined-cell question location ------------------------------------------

def test_locate_questions_splits_one_cell_into_each_questions_answers():
    cell = "Q1 Which colour do you like? Red; Green | Q2 How many seats: 10-50, Q3 Budget? Yes"
    found = locate_questions(cell, ["Which colour do you like?", "How many seats", "Budget"])
    assert found[0].segment == "Red; Green"
    assert found[1].segment == "10-50"
    assert found[2].segment == "Yes"
    assert all(f.score == 100 for f in found.values())


def test_locate_questions_reports_missing_and_near_miss_questions():
    cell = "Which colour do you likee? Red; Budget: Yes"
    found = locate_questions(cell, ["Which colour do you like?", "Budget", "Number of seats"])
    assert 2 not in found
    assert found[1].segment == "Yes"
    assert 85 <= found[0].score < 100
    assert found[0].segment == "Red"


# --- detect from leadfile -------------------------------------------------------

def test_detect_question_rules_finds_header_style_questions_and_answer_options():
    df = pd.DataFrame({
        "Email": ["x@example.com", "y@example.com", "z@example.com"],
        Q1: [f"{A_SEC}, {A_INT}", A_COST, f"{A_INT}, {A_SKILL}"],
        "Q2 Preferred contact method?": ["Phone; Email", "Email", "Phone"],
        "Company": ["Acme", "Beta", "Gamma"],
    })
    rules = detect_question_rules(df)
    assert [r.column for r in rules] == [Q1, "Q2 Preferred contact method?"]

    r1 = rules[0]
    assert r1.format == "header" and r1.mode == "full"
    assert r1.question_text == Q1
    assert r1.allowed_answers == [A_SEC, A_INT, A_COST, A_SKILL]
    assert (r1.count_rule, r1.count) == ("at_most", 2)

    r2 = rules[1]
    assert r2.separator == ";"
    assert r2.allowed_answers == ["Email", "Phone"]
    assert (r2.count_rule, r2.count) == ("at_most", 2)

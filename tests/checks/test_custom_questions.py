"""Check-level tests for core/checks/custom_questions.py. Synthetic data only,
mimicking the format of real survey-question leadfile columns."""
import pandas as pd

from core.checks.custom_questions import check_custom_questions
from core.models import CustomQuestionRule, CustomQuestionsConfig

Q1 = "1. What are your biggest challenges when deploying widgets for your customers?"
A_SEC = "a) Widget Security / API Governance & Compliance (Injection / leakage / guardrails)"
A_INT = "b) Integration with Existing Infrastructure, Pipelines & Data (Hybrid/multicloud / latency)"
A_COST = "c) High Compute & Platform Costs (Token use / cluster utilization)"
ALLOWED = [A_SEC, A_INT, A_COST]


def _header_rule(**overrides) -> CustomQuestionRule:
    base = dict(format="header", column=Q1, question_text=Q1, mode="full",
                allowed_answers=ALLOWED, count_rule="at_most", count=2, separator=",")
    base.update(overrides)
    return CustomQuestionRule(**base)


def _config(*rules) -> CustomQuestionsConfig:
    return CustomQuestionsConfig(enabled=True, rules=list(rules))


def test_disabled_config_does_nothing():
    df = pd.DataFrame({"Email": ["a@example.com"]})
    outcome = check_custom_questions(df, CustomQuestionsConfig(enabled=False, rules=[_header_rule()]))
    assert outcome.fail == {} and outcome.review == {}


def test_header_format_valid_answers_pass_even_when_header_numbering_and_case_differ():
    df = pd.DataFrame({
        "what are your biggest challenges when deploying widgets for your customers": [
            f"{A_SEC}, {A_INT}", A_COST],
    })
    outcome = check_custom_questions(df, _config(_header_rule()))
    assert outcome.fail == {} and outcome.review == {}


def test_header_format_refund_reasons_for_bad_answer_count_and_blank():
    df = pd.DataFrame({Q1: [
        f"{A_SEC}, Something we never offered",
        f"{A_SEC}, {A_INT}, {A_COST}",
        "",
    ]})
    outcome = check_custom_questions(df, _config(_header_rule()))
    assert outcome.fail[0] == "CQ1: 'Something we never offered' is not an allowed answer"
    assert outcome.fail[1] == "CQ1: 3 answers given, at most 2 allowed"
    assert outcome.fail[2] == "CQ1 not answered"
    assert outcome.review == {}


def test_missing_question_column_refunds_every_lead():
    df = pd.DataFrame({"Email": ["a@example.com", "b@example.com"]})
    outcome = check_custom_questions(df, _config(_header_rule()))
    assert outcome.fail == {0: "CQ1 missing", 1: "CQ1 missing"}


def test_slightly_reworded_question_header_goes_to_review():
    reworded = "1. What are your biggest challenge when deploying widgets for your customer?"
    df = pd.DataFrame({reworded: [A_SEC]})
    outcome = check_custom_questions(df, _config(_header_rule()))
    assert outcome.fail == {}
    detail = outcome.review[0]
    assert detail.check == "Custom Questions"
    assert "CQ1 question text doesn't exactly match" in detail.message
    assert detail.lead_value == reworded


def test_typo_answer_goes_to_review_with_closest_allowed_answer():
    typo = "c) High Compute & Platfrom Costs (Token use / cluster utilisation)"
    df = pd.DataFrame({Q1: [typo]})
    outcome = check_custom_questions(df, _config(_header_rule()))
    assert outcome.fail == {}
    detail = outcome.review[0]
    assert detail.message == f"CQ1: '{typo}' is close to allowed answer '{A_COST}'"
    assert detail.lead_value == typo and detail.candidate_value == A_COST
    assert detail.score >= 85


def test_exists_mode_only_checks_presence_and_non_blank():
    rule = _header_rule(mode="exists", allowed_answers=[], count_rule="exactly", count=1)
    df = pd.DataFrame({Q1: ["anything at all, really", None]})
    outcome = check_custom_questions(df, _config(rule))
    assert outcome.fail == {1: "CQ1 not answered"}


def test_full_mode_without_allowed_list_counts_by_separator():
    rule = _header_rule(allowed_answers=[], count_rule="at_least", count=2, separator=";")
    df = pd.DataFrame({Q1: ["Red; Green", "Red"]})
    outcome = check_custom_questions(df, _config(rule))
    assert outcome.fail == {1: "CQ1: 1 answer given, at least 2 required"}


def test_exactly_count_rule():
    rule = _header_rule(count_rule="exactly", count=1)
    df = pd.DataFrame({Q1: [A_SEC, f"{A_SEC}, {A_INT}"]})
    outcome = check_custom_questions(df, _config(rule))
    assert outcome.fail == {1: "CQ1: 2 answers given, exactly 1 required"}


def test_combined_format_locates_each_question_in_one_cell():
    colour = CustomQuestionRule(format="combined", column="Survey Answers",
                                question_text="Which colour do you like?",
                                allowed_answers=["Red, dark", "Green"], count_rule="at_most", count=2,
                                separator=";")
    seats = CustomQuestionRule(format="combined", column="survey answers", question_text="How many seats",
                               allowed_answers=["1-10", "11-50"], count_rule="exactly", count=1,
                               separator=";")
    df = pd.DataFrame({"Survey Answers": [
        "Q1 Which colour do you like? Red, dark; Green | Q2 How many seats: 11-50",
        "Which colour do you like? Purple; How many seats: 1-10; 11-50",
        "How many seats: 1-10",
    ]})
    outcome = check_custom_questions(df, _config(colour, seats))
    assert 0 not in outcome.fail and 0 not in outcome.review
    assert outcome.fail[1] == ("CQ1: 'Purple' is not an allowed answer; "
                               "CQ2: 2 answers given, exactly 1 required")
    assert outcome.fail[2] == "CQ1 missing"


def test_columns_format_checks_question_text_and_answer_column():
    rule = CustomQuestionRule(format="columns", question_column="Question 1", column="Answer 1",
                              question_text="Do you have budget approved?", allowed_answers=["Yes", "No"],
                              count_rule="exactly", count=1)
    df = pd.DataFrame({
        "Question 1": ["Do you have budget approved?", "Do you have a budget approved?",
                       "What is your job title?", ""],
        "Answer 1": ["Yes", "No", "Yes", "Yes"],
    })
    outcome = check_custom_questions(df, _config(rule))
    assert 0 not in outcome.fail and 0 not in outcome.review
    assert "CQ1 question text doesn't exactly match" in outcome.review[1].message
    assert outcome.fail[2] == "CQ1 question text doesn't match"
    assert outcome.fail[3] == "CQ1 missing"


def test_multiple_rule_failures_combine_into_one_reason():
    rule2 = CustomQuestionRule(format="header", column="Q2 Budget approved?", question_text="Q2 Budget approved?",
                               allowed_answers=["Yes", "No"], count_rule="exactly", count=1)
    df = pd.DataFrame({Q1: ["Not an option"], "Q2 Budget approved?": ["Maybe later"]})
    outcome = check_custom_questions(df, _config(_header_rule(), rule2))
    assert outcome.fail[0] == ("CQ1: 'Not an option' is not an allowed answer; "
                               "CQ2: 'Maybe later' is not an allowed answer")


# --- combined "Custom" cell cross-check -------------------------------------

CONSENT_TEXT = ('I agree to receive updates from Acme Widgets Ltd. (see <a href="https://acme.example/p">'
                'Privacy Policy</a>), including: news, offers and events')
WIDGET_Q = "Which widget do you use?"
WIDGET_RULE = CustomQuestionRule(format="header", column="1. " + WIDGET_Q, question_text="1. " + WIDGET_Q,
                                 allowed_answers=["Blue widget", "Red widget"])


def _custom(budget="$10,000 to $50,000", widget="Blue widget", consent="true", timeframe="Within 6 months"):
    return (f"{WIDGET_Q}: {widget};Budget: {budget};{CONSENT_TEXT}: {consent};"
            f"Timeframe: {timeframe};Favourite colour: Teal")


def _cc_config(*rules, **overrides) -> CustomQuestionsConfig:
    base = dict(enabled=True, rules=list(rules), combined_cell_column="Custom")
    base.update(overrides)
    return CustomQuestionsConfig(**base)


def test_combined_cell_matching_separate_columns_passes_and_ignores_unmatched_pairs():
    df = pd.DataFrame({
        "Custom": [_custom()],
        "1. " + WIDGET_Q: ["Blue widget"], "Budget": ["$10,000 to $50,000"], "timeframe": ["within 6 months"],
    })
    outcome = check_custom_questions(df, _cc_config(WIDGET_RULE))
    assert outcome.fail == {} and outcome.review == {}


def test_combined_cell_clear_mismatch_with_a_column_refunds_with_both_values():
    df = pd.DataFrame({
        "Custom": [_custom(budget="Above $50,000"), _custom(widget="Red widget")],
        "1. " + WIDGET_Q: ["Blue widget", "Blue widget"], "Budget": ["$10,000 to $50,000"] * 2,
    })
    outcome = check_custom_questions(df, _cc_config(WIDGET_RULE))
    assert outcome.fail == {
        0: "Custom cell says 'Above $50,000' but 'Budget' column says '$10,000 to $50,000'",
        1: f"Custom cell says 'Red widget' but '1. {WIDGET_Q}' column says 'Blue widget'",
    }


def test_combined_cell_near_miss_goes_to_review():
    df = pd.DataFrame({"Custom": [_custom(timeframe="Within 6 month")], "Timeframe": ["Within 6 months"]})
    outcome = check_custom_questions(df, _cc_config())
    assert outcome.fail == {}
    detail = outcome.review[0]
    assert detail.check == "Custom Questions"
    assert detail.message == "Custom cell says 'Within 6 month' but 'Timeframe' column says 'Within 6 months'"
    assert (detail.lead_value, detail.candidate_value) == ("Within 6 month", "Within 6 months")


def test_combined_cell_blank_column_value_is_a_mismatch():
    df = pd.DataFrame({"Custom": [_custom()], "Budget": [""]})
    outcome = check_custom_questions(df, _cc_config())
    assert outcome.fail == {0: "Custom cell says '$10,000 to $50,000' but 'Budget' column is blank"}


def test_combined_only_mode_validates_answers_against_the_rule_when_its_column_is_absent():
    df = pd.DataFrame({"Custom": [
        _custom(), _custom(widget="Green widget"), "Budget: Above $50,000", _custom(widget="Blue widgett"),
    ]})
    outcome = check_custom_questions(df, _cc_config(WIDGET_RULE))
    assert outcome.fail == {1: "CQ1: 'Green widget' is not an allowed answer", 2: "CQ1 missing"}
    assert list(outcome.review) == [3]
    assert "close to allowed answer 'Blue widget'" in outcome.review[3].message


def test_without_a_combined_column_an_absent_rule_column_is_still_missing():
    df = pd.DataFrame({"Custom": [_custom()]})
    outcome = check_custom_questions(df, _config(WIDGET_RULE))
    assert outcome.fail == {0: "CQ1 missing"}


def test_required_consent_pairs_must_be_present_and_true():
    df = pd.DataFrame({"Custom": [_custom(), _custom(consent="false"), "Budget: Above $50,000"]})
    outcome = check_custom_questions(df, _cc_config(
        require_consent_true=True, consent_keys=["I agree to receive updates from Acme"]))
    assert outcome.fail == {
        1: "Custom cell: consent 'I agree to receive updates from Acme' is 'false', must be true",
        2: "Custom cell: consent 'I agree to receive updates from Acme' missing",
    }


def test_consent_keys_are_ignored_while_the_toggle_is_off():
    df = pd.DataFrame({"Custom": [_custom(consent="false")]})
    outcome = check_custom_questions(df, _cc_config(
        require_consent_true=False, consent_keys=["I agree to receive updates from Acme"]))
    assert outcome.fail == {} and outcome.review == {}


def test_configured_combined_column_missing_from_leadfile_refunds_every_lead():
    df = pd.DataFrame({"Email": ["a@example.com", "b@example.com"]})
    outcome = check_custom_questions(df, _cc_config())
    assert outcome.fail == {0: "Custom cell column 'Custom' not found", 1: "Custom cell column 'Custom' not found"}

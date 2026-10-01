"""Check-level tests for core/checks/lead_notes.py. Synthetic data only."""
import pandas as pd

from core.checks.lead_notes import check_lead_notes
from core.models import LeadNotesConfig, LeadNotesField


def _notes(first="Jane", last="Doe", title="VP of Operations", company="Acme Widgets Ltd.",
           phone="1 555 0100123", email="jane.doe@acmewidgets.example", budget="$10,000 to $50,000"):
    return (f"The conversation with {first} {last} on 09/20/2026 followed access to Asset X. {first} is "
            f"{title} at {company} and is considering Product Y within the next 6 months. Reducing cost was "
            f"the main challenge, with a Budget of {budget}. Acme can reach {first} at {phone} within 5 days. "
            f"An email was sent to {email}")


def _lead(**overrides) -> dict:
    base = {"Email": "jane.doe@acmewidgets.example", "Phone": "+1 (555) 010-0123", "First Name": "Jane",
            "Last Name": "Doe", "Company": "Acme Widgets", "Job Title": "VP Operations",
            "Budget": "$10,000 to $50,000", "Signal Notes": _notes()}
    base.update(overrides)
    return base


ALL_FIELDS = [
    LeadNotesField(kind="email", column="Email", required=True, action="refund"),
    LeadNotesField(kind="phone", column="Phone"),
    LeadNotesField(kind="first_name", column="First Name", required=True),
    LeadNotesField(kind="last_name", column="Last Name", required=True),
    LeadNotesField(kind="company", column="Company", required=True, action="refund"),
    LeadNotesField(kind="job_title", column="Job Title", required=True),
    LeadNotesField(kind="value", column="Budget", label="Budget", required=True),
]


def _config(fields=None, **overrides) -> LeadNotesConfig:
    base = dict(enabled=True, notes_column="Signal Notes", fields=ALL_FIELDS if fields is None else fields)
    base.update(overrides)
    return LeadNotesConfig(**base)


def test_disabled_or_unconfigured_does_nothing():
    df = pd.DataFrame([_lead(Email="other@example.com")])
    assert check_lead_notes(df, _config(enabled=False)).fail == {}
    assert check_lead_notes(df, _config(notes_column="")).fail == {}
    assert check_lead_notes(df, _config(fields=[])).fail == {}


def test_notes_agreeing_with_every_field_pass():
    outcome = check_lead_notes(pd.DataFrame([_lead()]), _config())
    assert outcome.fail == {} and outcome.review == {}


def test_email_mismatch_refunds_with_both_values():
    df = pd.DataFrame([_lead(Email="j.doe@other.example")])
    outcome = check_lead_notes(df, _config())
    assert outcome.fail == {
        0: "Notes: email jane.doe@acmewidgets.example doesn't match lead email j.doe@other.example"}


def test_review_action_and_default_action_go_to_needs_review():
    df = pd.DataFrame([_lead(**{"Job Title": "Chief Technology Officer", "Phone": "+1 555 010 9999"})])
    outcome = check_lead_notes(df, _config())
    assert outcome.fail == {}
    detail = outcome.review[0]
    assert detail.check == "Lead Notes"
    assert detail.message == ("Notes: phone 1 555 0100123 doesn't match lead phone +1 555 010 9999; "
                              "Notes: job title not mentioned")
    assert (detail.lead_value, detail.candidate_value) == ("+1 555 010 9999", "1 555 0100123")


def test_optional_field_not_mentioned_is_ignored_but_a_mismatch_is_not():
    notes_without_phone = _notes(phone="her desk line")
    df = pd.DataFrame([_lead(**{"Signal Notes": notes_without_phone})])
    assert check_lead_notes(df, _config()).review == {}


def test_required_value_field_not_mentioned_names_the_value():
    df = pd.DataFrame([_lead(Budget="Above $50,000")])
    outcome = check_lead_notes(df, _config())
    assert outcome.review[0].message == "Notes: Budget 'Above $50,000' not mentioned"


def test_refund_wins_over_review_on_the_same_lead():
    df = pd.DataFrame([_lead(Company="Globex Corporation", **{"First Name": "Priya"})])
    outcome = check_lead_notes(df, _config())
    assert outcome.fail == {0: "Notes: company not mentioned"}
    assert outcome.review == {}


def test_blank_lead_value_is_skipped():
    df = pd.DataFrame([_lead(Email="", **{"Job Title": None})])
    outcome = check_lead_notes(df, _config())
    assert outcome.fail == {} and outcome.review == {}


def test_blank_notes_use_the_strictest_required_action():
    df = pd.DataFrame([_lead(**{"Signal Notes": ""}), _lead(**{"Signal Notes": "  "})])
    assert check_lead_notes(df, _config()).fail == {0: "Notes: 'Signal Notes' is blank",
                                                    1: "Notes: 'Signal Notes' is blank"}
    review_only = [LeadNotesField(kind="first_name", column="First Name", required=True)]
    assert check_lead_notes(df, _config(review_only)).review[0].message == "Notes: 'Signal Notes' is blank"
    optional_only = [LeadNotesField(kind="first_name", column="First Name")]
    assert check_lead_notes(df, _config(optional_only)).review == {}


def test_missing_notes_or_field_column_is_reported():
    df = pd.DataFrame([_lead()]).drop(columns=["Signal Notes"])
    assert check_lead_notes(df, _config()).fail == {0: "Notes: 'Signal Notes' column not found"}

    df = pd.DataFrame([_lead()]).drop(columns=["Budget"])
    assert check_lead_notes(df, _config()).review[0].message == "Notes: 'Budget' column not found"


def test_columns_are_matched_loosely():
    df = pd.DataFrame([_lead()]).rename(columns={"Signal Notes": "signal_notes", "Email": "EMAIL"})
    outcome = check_lead_notes(df, _config())
    assert outcome.fail == {} and outcome.review == {}


def test_company_aliases_are_used():
    df = pd.DataFrame([_lead(**{"Signal Notes": _notes(company="AW Group")})])
    fields = [LeadNotesField(kind="company", column="Company", required=True, action="refund")]
    assert check_lead_notes(df, _config(fields)).fail == {0: "Notes: company not mentioned"}
    outcome = check_lead_notes(df, _config(fields), alias_groups=[["acme widgets", "aw group"]])
    assert outcome.fail == {}

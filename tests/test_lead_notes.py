"""Pure-logic tests for core/lead_notes.py -- rule-based extraction from a
lead's narrative notes paragraph. All people, companies, emails and phone
numbers are synthetic (example.* domains, 555 numbers)."""
import pytest

from core.lead_notes import (
    MATCH, MISMATCH, NOT_MENTIONED, NO_LEAD_VALUE,
    check_field, extract_emails, extract_phones, phone_digits,
)

NOTES = (
    "The conversation with Jane Doe on 09/20/2026 followed access to Asset X. Jane is VP of Operations at "
    "Acme Widgets Ltd. and is considering Product Y within the next 6 months. Reducing cost was the main "
    "challenge, with a Budget of $10,000 to $50,000. Acme can reach Jane at 1 555 0100123 within 5 days. "
    "An email was sent to jane.doe@acmewidgets.example"
)


# --- email ---------------------------------------------------------------------

def test_extract_emails_finds_addresses_and_drops_trailing_punctuation():
    assert extract_emails("Mail j.doe@acme.example. Or JANE@Beta.example, thanks") == [
        "j.doe@acme.example", "jane@beta.example"]


def test_email_match_mismatch_and_not_mentioned():
    assert check_field("email", NOTES, "Jane.Doe@AcmeWidgets.example").status == MATCH
    finding = check_field("email", NOTES, "j.doe@other.example")
    assert (finding.status, finding.found) == (MISMATCH, "jane.doe@acmewidgets.example")
    assert check_field("email", "No contact details given.", "j.doe@other.example").status == NOT_MENTIONED


def test_blank_lead_value_is_not_checked():
    assert check_field("email", NOTES, "").status == NO_LEAD_VALUE
    assert check_field("job_title", NOTES, None).status == NO_LEAD_VALUE


# --- phone ---------------------------------------------------------------------

def test_phone_digits_strips_formatting():
    assert phone_digits("+1 (555) 010-0123") == "15550100123"


def test_extract_phones_ignores_dates_money_and_small_numbers():
    assert extract_phones(NOTES) == ["1 555 0100123"]
    assert extract_phones("Call on 2026-09-20 about 12 seats, $1,500,000 budget") == []


@pytest.mark.parametrize("lead_phone", [
    "+1 555 010 0123", "555-010-0123", "(555) 010-0123", "+1-555-0100123", "15550100123", "5550100123",
])
def test_phone_matches_across_formats_on_the_last_digits(lead_phone):
    assert check_field("phone", NOTES, lead_phone).status == MATCH


def test_phone_formats_in_the_notes_text_also_vary():
    for text in ("Reach her at +1 (555) 010-0123.", "Phone: 555.010.0123", "tel 555 010 0123 ext"):
        assert check_field("phone", text, "5550100123").status == MATCH, text


def test_phone_mismatch_and_not_mentioned():
    finding = check_field("phone", NOTES, "+1 555 010 9999")
    assert (finding.status, finding.found) == (MISMATCH, "1 555 0100123")
    assert check_field("phone", "No number was shared.", "+1 555 010 9999").status == NOT_MENTIONED


# --- names ---------------------------------------------------------------------

def test_names_match_case_insensitively_and_with_a_small_typo():
    assert check_field("first_name", NOTES, "JANE").status == MATCH
    assert check_field("last_name", NOTES, "Doe").status == MATCH
    assert check_field("first_name", "Spoke with Jonathon Smith today.", "Jonathan").status == MATCH


def test_names_not_mentioned():
    assert check_field("first_name", NOTES, "Priya").status == NOT_MENTIONED
    assert check_field("last_name", NOTES, "Doerr-Smith").status == NOT_MENTIONED


def test_short_name_needs_an_exact_word_not_a_fragment():
    assert check_field("first_name", "Bob and Alice met.", "Al").status == NOT_MENTIONED
    assert check_field("first_name", "Al and Bob met.", "Al").status == MATCH


# --- company -------------------------------------------------------------------

def test_company_match_ignores_legal_suffixes_and_punctuation():
    assert check_field("company", NOTES, "Acme Widgets").status == MATCH
    assert check_field("company", NOTES, "ACME WIDGETS, LTD").status == MATCH
    assert check_field("company", NOTES, "Acme Widgets Inc.").status == MATCH


def test_company_fuzzy_and_alias_match():
    assert check_field("company", NOTES, "Acme Widget Ltd").status == MATCH
    assert check_field("company", "She works at AW Group.", "Acme Widgets",
                       alias_groups=[["acme widgets", "aw group"]]).status == MATCH


def test_company_not_mentioned():
    assert check_field("company", NOTES, "Globex Corporation").status == NOT_MENTIONED


# --- job title -----------------------------------------------------------------

def test_job_title_token_match_with_abbreviations_and_word_order():
    assert check_field("job_title", NOTES, "VP of Operations").status == MATCH
    assert check_field("job_title", NOTES, "Vice President, Operations").status == MATCH
    assert check_field("job_title", "He is the Senior Manager, IT Infrastructure.",
                       "Sr. IT Infrastructure Manager").status == MATCH


def test_job_title_not_mentioned_when_a_key_word_is_absent():
    assert check_field("job_title", NOTES, "VP of Finance").status == NOT_MENTIONED
    assert check_field("job_title", NOTES, "Chief Technology Officer").status == NOT_MENTIONED


# --- free value fields ---------------------------------------------------------

def test_value_field_normalized_substring_and_word_match():
    assert check_field("value", NOTES, "$10,000 to $50,000").status == MATCH
    assert check_field("value", NOTES, "Within 6 months").status == MATCH
    assert check_field("value", NOTES, "Product Y").status == MATCH


def test_value_field_fuzzy_partial_match_and_not_mentioned():
    assert check_field("value", NOTES, "Reducing costs").status == MATCH
    assert check_field("value", NOTES, "Above $50,000").status == NOT_MENTIONED
    assert check_field("value", NOTES, "Within 12 months").status == NOT_MENTIONED

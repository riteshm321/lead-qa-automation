import pandas as pd

from core.checks.duplicate import check_duplicates
from core.models import FieldMapping

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")


def test_exact_email_match_against_accumulated_fails():
    new_leads = pd.DataFrame([
        {"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert outcome.fail[0] == "Duplicate - exact email"


def test_exact_email_match_within_new_batch_fails():
    new_leads = pd.DataFrame([
        {"emailaddress": "a@x.com", "firstname": "A", "lastname": "B", "company": "X", "CID": 1},
        {"emailaddress": "a@x.com", "firstname": "A", "lastname": "B", "company": "X", "CID": 1},
    ])
    accumulated = pd.DataFrame(columns=["emailaddress", "firstname", "lastname", "company", "CID"])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert outcome.fail[1] == "Duplicate - exact email"
    assert 0 not in outcome.fail


def test_same_name_same_company_same_domain_fails():
    # Rule 3: same name, same company, same email domain, different email
    # address — a clear duplicate (e.g. a second alias for the same person).
    new_leads = pd.DataFrame([
        {"emailaddress": "andy.jones@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google Inc", "CID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert outcome.fail[0] == "Duplicate - same name, company, and email domain"


def test_same_name_same_company_different_domain_goes_to_review():
    # Rule 2: same name, same company, but a different email domain — can't
    # auto-confirm or auto-clear, needs a human look.
    new_leads = pd.DataFrame([
        {"emailaddress": "andy@gooooogle.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google Inc", "CID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert 0 not in outcome.fail
    detail = outcome.review[0]
    assert detail.check == "Duplicate"
    assert detail.lead_value == "gooooogle.com"
    assert detail.candidate_value == "google.com"


def test_same_name_different_company_passes():
    # Rule 2 (second half): same name but a genuinely different company —
    # two different people who happen to share a name, so it passes through.
    new_leads = pd.DataFrame([
        {"emailaddress": "andy@unrelatedco.com", "firstname": "Andy", "lastname": "Jones", "company": "Unrelated Co", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert outcome.fail == {}
    assert outcome.review == {}


def test_same_name_blank_existing_company_passes():
    # If the existing record's company is blank, there's nothing to confirm
    # a company match against — treated the same as a different company.
    new_leads = pd.DataFrame([
        {"emailaddress": "sachin.thakare@kpit.com", "firstname": "Sachin", "lastname": "Sachin", "company": "KPIT Technologies Limited", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"emailaddress": "sachin.agrawal@heromotocorp.com", "firstname": "Sachin", "lastname": "Sachin", "company": "", "CID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert outcome.fail == {}
    assert outcome.review == {}


def test_exact_email_match_against_accumulated_with_different_headers_fails():
    # Regression test: the Accumulated Report commonly uses different header
    # text than the New Leads file (that's exactly what
    # ClientProfile.accumulated_field_mapping exists for), but check_duplicates
    # previously only accepted a single FieldMapping and used it to read both
    # sides — so a lead already in the Accumulated Report under headers like
    # "Email Add." never matched anything, since fm.email ("emailaddress")
    # doesn't exist as a column there at all and .get() silently returned "".
    acc_fm = FieldMapping(email="Email Add.", first_name="Given Name", last_name="Surname",
                           company="Org", cid="Campaign ID")
    new_leads = pd.DataFrame([
        {"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"Email Add.": "andy@google.com", "Given Name": "Andy", "Surname": "Jones", "Org": "Google", "Campaign ID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM, accumulated_field_mapping=acc_fm)

    assert outcome.fail[0] == "Duplicate - exact email"


def test_no_match_for_distinct_leads():
    new_leads = pd.DataFrame([
        {"emailaddress": "ida@scania.com", "firstname": "Ida", "lastname": "Ekendahl", "company": "Scania", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"emailaddress": "alexey@danone.com", "firstname": "Alexey", "lastname": "Pavlov", "company": "Danone", "CID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert outcome.fail == {}
    assert outcome.review == {}


def test_name_and_company_prefix_match_against_accumulated_goes_to_review():
    # Rule 5: full name differs (Michael/Micheal, Johnson/Johnston) so the
    # exact-name rule never fires, but the first 3 letters of first name,
    # last name, and company all match — a plausible typo/near-duplicate,
    # coarse enough that it's only ever sent to review, never auto-failed.
    new_leads = pd.DataFrame([
        {"emailaddress": "michael.johnson@acme.com", "firstname": "Michael", "lastname": "Johnson",
         "company": "Acme Corp", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"emailaddress": "m.johnston@acmecorp.com", "firstname": "Micheal", "lastname": "Johnston",
         "company": "Acme Corporation", "CID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert outcome.fail == {}
    detail = outcome.review[0]
    assert detail.check == "Duplicate"
    assert "company prefix" in detail.message.lower()


def test_name_and_domain_prefix_match_against_accumulated_goes_to_review():
    # Rule 6: same idea as Rule 5, but keyed on the email domain instead of
    # company — different (or blank) company, so Rule 5 doesn't fire first.
    new_leads = pd.DataFrame([
        {"emailaddress": "robert.smith@techcorp.com", "firstname": "Robert", "lastname": "Smith",
         "company": "", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"emailaddress": "r.smith@technologycorp.io", "firstname": "Rob", "lastname": "Smithson",
         "company": "", "CID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert outcome.fail == {}
    detail = outcome.review[0]
    assert detail.check == "Duplicate"
    assert "domain prefix" in detail.message.lower()


def test_prefix_rules_do_not_fire_on_blank_fields():
    new_leads = pd.DataFrame([
        {"emailaddress": "", "firstname": "Michael", "lastname": "Johnson", "company": "", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"emailaddress": "", "firstname": "Micheal", "lastname": "Johnston", "company": "", "CID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert outcome.fail == {}
    assert outcome.review == {}


def test_prefix_rule_only_first_of_several_in_batch_matches_passes_through():
    # Several new leads share the same first-3-letter name & company prefix
    # purely within this batch (no accumulated counterpart) — the first one
    # processed is the "original" and passes clean; the rest are flagged
    # against it, one at a time as they're seen.
    new_leads = pd.DataFrame([
        {"emailaddress": "a@acme.com", "firstname": "Michael", "lastname": "Johnson", "company": "Acme Corp", "CID": 1},
        {"emailaddress": "b@acme.com", "firstname": "Micheal", "lastname": "Johnston", "company": "Acme Co", "CID": 1},
        {"emailaddress": "c@acme.com", "firstname": "Mich", "lastname": "Johns", "company": "Acme Ltd", "CID": 1},
    ])
    accumulated = pd.DataFrame(columns=["emailaddress", "firstname", "lastname", "company", "CID"])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert 0 not in outcome.fail and 0 not in outcome.review
    assert outcome.review[1].check == "Duplicate"
    assert outcome.review[2].check == "Duplicate"


def test_prefix_rule_flags_every_batch_lead_matching_an_accumulated_lead():
    # Unlike purely in-batch duplicates, when the match is against an
    # existing Accumulated Report lead, every matching new lead is flagged
    # — none should pass as valid, since the accumulated lead already
    # counts as delivered.
    new_leads = pd.DataFrame([
        {"emailaddress": "a@acme.com", "firstname": "Michael", "lastname": "Johnson", "company": "Acme Corp", "CID": 1},
        {"emailaddress": "b@acme.com", "firstname": "Mich", "lastname": "Johns", "company": "Acme Ltd", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"emailaddress": "existing@acmecorp.com", "firstname": "Micheal", "lastname": "Johnston",
         "company": "Acme Corporation", "CID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert outcome.fail == {}
    assert 0 in outcome.review
    assert 1 in outcome.review

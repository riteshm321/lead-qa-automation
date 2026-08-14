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

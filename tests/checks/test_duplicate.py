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


def test_same_name_same_company_variant_domain_fails():
    new_leads = pd.DataFrame([
        {"emailaddress": "andy@gooooogle.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google Inc", "CID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert outcome.fail[0] == "Duplicate - name/company match"


def test_same_name_different_unrelated_company_goes_to_review():
    new_leads = pd.DataFrame([
        {"emailaddress": "andy@unrelatedco.com", "firstname": "Andy", "lastname": "Jones", "company": "Unrelated Co", "CID": 1},
    ])
    accumulated = pd.DataFrame([
        {"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": 1},
    ])

    outcome = check_duplicates(new_leads, accumulated, FM)

    assert 0 not in outcome.fail
    assert 0 in outcome.review


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

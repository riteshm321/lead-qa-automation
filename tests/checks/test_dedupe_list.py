import pandas as pd

from core.checks.dedupe_list import check_dedupe_list
from core.models import FieldMapping, DedupeListConfig

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")

DEDUPE_DF = pd.DataFrame([{"Email": "delivered@acme.com"}])


def test_email_in_dedupe_list_fails():
    config = DedupeListConfig(enabled=True)
    new_leads = pd.DataFrame([{"emailaddress": "delivered@acme.com"}])

    outcome = check_dedupe_list(new_leads, FM, config, DEDUPE_DF)

    assert outcome.fail[0] == "Dedupe list - email match"


def test_email_not_in_dedupe_list_passes():
    config = DedupeListConfig(enabled=True)
    new_leads = pd.DataFrame([{"emailaddress": "new@acme.com"}])

    outcome = check_dedupe_list(new_leads, FM, config, DEDUPE_DF)

    assert outcome.fail == {}


def test_disabled_check_produces_no_failures():
    config = DedupeListConfig(enabled=False)
    new_leads = pd.DataFrame([{"emailaddress": "delivered@acme.com"}])

    outcome = check_dedupe_list(new_leads, FM, config, DEDUPE_DF)

    assert outcome.fail == {}

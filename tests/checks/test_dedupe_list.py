import pandas as pd

from core.checks.dedupe_list import check_dedupe_list
from core.models import FieldMapping, DedupeListConfig, ReferenceSource

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")

UNIVERSAL_SOURCE = ReferenceSource(name="Global", file_path="unused.xlsx", sheet_name="Sheet1")
DEDUPE_DF = pd.DataFrame([{"Email": "delivered@acme.com"}])


def test_email_in_dedupe_list_fails():
    config = DedupeListConfig(enabled=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "delivered@acme.com", "CID": "1"}])

    outcome = check_dedupe_list(new_leads, FM, config, {"Global": DEDUPE_DF})

    assert outcome.fail[0] == "Dedupe list - email match"


def test_email_not_in_dedupe_list_passes():
    config = DedupeListConfig(enabled=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "new@acme.com", "CID": "1"}])

    outcome = check_dedupe_list(new_leads, FM, config, {"Global": DEDUPE_DF})

    assert outcome.fail == {}


def test_disabled_check_produces_no_failures():
    config = DedupeListConfig(enabled=False, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "delivered@acme.com", "CID": "1"}])

    outcome = check_dedupe_list(new_leads, FM, config, {"Global": DEDUPE_DF})

    assert outcome.fail == {}


def test_multiple_sources_are_unioned():
    df_a = pd.DataFrame([{"Email": "a@delivered.com"}])
    df_b = pd.DataFrame([{"Email": "b@delivered.com"}])
    config = DedupeListConfig(enabled=True, sources=[
        ReferenceSource(name="A", file_path="a.xlsx", sheet_name="Sheet1"),
        ReferenceSource(name="B", file_path="b.xlsx", sheet_name="Sheet1"),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "b@delivered.com", "CID": "1"}])

    outcome = check_dedupe_list(new_leads, FM, config, {"A": df_a, "B": df_b})

    assert outcome.fail[0] == "Dedupe list - email match"


def test_segment_scoped_source_only_applies_to_its_own_cids():
    df_emea = pd.DataFrame([{"Email": "delivered@emea.com"}])
    config = DedupeListConfig(enabled=True, sources=[
        ReferenceSource(name="EMEA", file_path="emea.xlsx", sheet_name="Sheet1", cids=["100"]),
    ])
    apac_lead = pd.DataFrame([{"emailaddress": "delivered@emea.com", "CID": "200"}])

    outcome = check_dedupe_list(apac_lead, FM, config, {"EMEA": df_emea})

    assert outcome.fail == {}

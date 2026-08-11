import pandas as pd

from core.checks.suppression import check_suppression
from core.models import FieldMapping, SuppressionConfig, ReferenceSource

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")

SUPPRESSION_DF = pd.DataFrame([
    {"Account Name": "Acme Corp", "Domain": "acme.com", "Email": "known@acme.com"},
    {"Account Name": "Acme Industries", "Domain": "acmeindustries.com", "Email": "info@acmeindustries.com"},
])

UNIVERSAL_SOURCE = ReferenceSource(name="Global", file_path="unused.xlsx", sheet_name="Sheet1")


def test_domain_check_fails():
    config = SuppressionConfig(enabled=True, check_domain=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@acme.com", "company": "Someone", "CID": "1"}])

    outcome = check_suppression(new_leads, FM, config, {"Global": SUPPRESSION_DF}, alias_groups=[])

    assert outcome.fail[0] == "Suppression - domain"


def test_email_check_fails():
    config = SuppressionConfig(enabled=True, check_email=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "known@acme.com", "company": "Someone", "CID": "1"}])

    outcome = check_suppression(new_leads, FM, config, {"Global": SUPPRESSION_DF}, alias_groups=[])

    assert outcome.fail[0] == "Suppression - email"


def test_company_check_fails_when_toggled_on():
    config = SuppressionConfig(enabled=True, check_company_name=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@other.com", "company": "Acme Corp", "CID": "1"}])

    outcome = check_suppression(new_leads, FM, config, {"Global": SUPPRESSION_DF}, alias_groups=[])

    assert outcome.fail[0] == "Suppression - company"


def test_no_toggles_enabled_produces_no_failures_even_if_row_matches():
    config = SuppressionConfig(enabled=True, check_domain=False, check_company_name=False, check_email=False,
                                sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "known@acme.com", "company": "Acme Corp", "CID": "1"}])

    outcome = check_suppression(new_leads, FM, config, {"Global": SUPPRESSION_DF}, alias_groups=[])

    assert outcome.fail == {}


def test_disabled_check_produces_no_failures():
    config = SuppressionConfig(enabled=False, check_domain=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@acme.com", "company": "Someone", "CID": "1"}])

    outcome = check_suppression(new_leads, FM, config, {"Global": SUPPRESSION_DF}, alias_groups=[])

    assert outcome.fail == {}


def test_company_name_gray_zone_match_routes_to_review():
    config = SuppressionConfig(enabled=True, check_company_name=True, check_domain=False, check_email=False,
                                sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@other.com", "company": "Acme Industrial", "CID": "1"}])

    outcome = check_suppression(new_leads, FM, config, {"Global": SUPPRESSION_DF}, alias_groups=[])

    assert 0 not in outcome.fail
    assert outcome.review[0] == "Suppression - company name ambiguous match"


def test_multiple_sources_are_unioned():
    df_a = pd.DataFrame([{"Domain": "a.com"}])
    df_b = pd.DataFrame([{"Domain": "b.com"}])
    config = SuppressionConfig(enabled=True, check_domain=True, sources=[
        ReferenceSource(name="A", file_path="a.xlsx", sheet_name="Sheet1"),
        ReferenceSource(name="B", file_path="b.xlsx", sheet_name="Sheet1"),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@b.com", "company": "X", "CID": "1"}])

    outcome = check_suppression(new_leads, FM, config, {"A": df_a, "B": df_b}, alias_groups=[])

    assert outcome.fail[0] == "Suppression - domain"


def test_segment_scoped_source_only_applies_to_its_own_cids():
    df_emea = pd.DataFrame([{"Domain": "emea-suppressed.com"}])
    config = SuppressionConfig(enabled=True, check_domain=True, sources=[
        ReferenceSource(name="EMEA", file_path="emea.xlsx", sheet_name="Sheet1", cids=["100"]),
    ])
    apac_lead = pd.DataFrame([{"emailaddress": "x@emea-suppressed.com", "company": "X", "CID": "200"}])

    outcome = check_suppression(apac_lead, FM, config, {"EMEA": df_emea}, alias_groups=[])

    assert outcome.fail == {}

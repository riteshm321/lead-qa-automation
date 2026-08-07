import pandas as pd

from core.checks.suppression import check_suppression
from core.models import FieldMapping, SuppressionConfig

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")

SUPPRESSION_DF = pd.DataFrame([
    {"Account Name": "Acme Corp", "Domain": "acme.com", "Email": "known@acme.com"},
    {"Account Name": "Acme Industries", "Domain": "acmeindustries.com", "Email": "info@acmeindustries.com"},
])


def test_domain_check_fails():
    config = SuppressionConfig(enabled=True, check_domain=True)
    new_leads = pd.DataFrame([{"emailaddress": "x@acme.com", "company": "Someone"}])

    outcome = check_suppression(new_leads, FM, config, SUPPRESSION_DF, alias_groups=[])

    assert outcome.fail[0] == "Suppression - domain"


def test_email_check_fails():
    config = SuppressionConfig(enabled=True, check_email=True)
    new_leads = pd.DataFrame([{"emailaddress": "known@acme.com", "company": "Someone"}])

    outcome = check_suppression(new_leads, FM, config, SUPPRESSION_DF, alias_groups=[])

    assert outcome.fail[0] == "Suppression - email"


def test_company_check_fails_when_toggled_on():
    config = SuppressionConfig(enabled=True, check_company_name=True)
    new_leads = pd.DataFrame([{"emailaddress": "x@other.com", "company": "Acme Corp"}])

    outcome = check_suppression(new_leads, FM, config, SUPPRESSION_DF, alias_groups=[])

    assert outcome.fail[0] == "Suppression - company"


def test_no_toggles_enabled_produces_no_failures_even_if_row_matches():
    config = SuppressionConfig(enabled=True, check_domain=False, check_company_name=False, check_email=False)
    new_leads = pd.DataFrame([{"emailaddress": "known@acme.com", "company": "Acme Corp"}])

    outcome = check_suppression(new_leads, FM, config, SUPPRESSION_DF, alias_groups=[])

    assert outcome.fail == {}


def test_disabled_check_produces_no_failures():
    config = SuppressionConfig(enabled=False, check_domain=True)
    new_leads = pd.DataFrame([{"emailaddress": "x@acme.com", "company": "Someone"}])

    outcome = check_suppression(new_leads, FM, config, SUPPRESSION_DF, alias_groups=[])

    assert outcome.fail == {}


def test_company_name_gray_zone_match_routes_to_review():
    """Test that fuzzy company name match (gray-zone) routes to review, not fail."""
    config = SuppressionConfig(enabled=True, check_company_name=True, check_domain=False, check_email=False)
    # Use a company name that will fuzzy match but not be an exact match
    # The suppression list has "Acme Industries", so "Acme Industrial" is a gray-zone fuzzy match
    new_leads = pd.DataFrame([{"emailaddress": "x@other.com", "company": "Acme Industrial"}])

    outcome = check_suppression(new_leads, FM, config, SUPPRESSION_DF, alias_groups=[])

    # Should be in review, not in fail
    assert 0 not in outcome.fail
    assert outcome.review[0] == "Suppression - company name ambiguous match"

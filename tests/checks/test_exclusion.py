import pandas as pd

from core.checks.exclusion import check_exclusion
from core.models import FieldMapping, ExclusionConfig

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")

EXCLUSION_DF = pd.DataFrame([
    {"Account Name": "Adecco UK Ltd", "Domain": "adecco.co.uk"},
    {"Account Name": "Enerpac Tool Group, Inc.", "Domain": "enerpactoolgroup.com"},
])


def test_domain_match_fails():
    config = ExclusionConfig(enabled=True, check_company_name=False)
    new_leads = pd.DataFrame([{"emailaddress": "x@adecco.co.uk", "company": "Someone Else"}])

    outcome = check_exclusion(new_leads, FM, config, EXCLUSION_DF, alias_groups=[])

    assert outcome.fail[0] == "Exclusion - domain"


def test_no_match_passes():
    config = ExclusionConfig(enabled=True)
    new_leads = pd.DataFrame([{"emailaddress": "x@scania.com", "company": "Scania"}])

    outcome = check_exclusion(new_leads, FM, config, EXCLUSION_DF, alias_groups=[])

    assert outcome.fail == {}
    assert outcome.review == {}


def test_company_name_match_fails_when_toggled_on():
    config = ExclusionConfig(enabled=True, check_company_name=True)
    new_leads = pd.DataFrame([{"emailaddress": "x@unrelated-domain.com", "company": "Enerpac Tool Group"}])

    outcome = check_exclusion(new_leads, FM, config, EXCLUSION_DF, alias_groups=[])

    assert outcome.fail[0] == "Exclusion - company"


def test_disabled_check_produces_no_failures():
    config = ExclusionConfig(enabled=False)
    new_leads = pd.DataFrame([{"emailaddress": "x@adecco.co.uk", "company": "Adecco"}])

    outcome = check_exclusion(new_leads, FM, config, EXCLUSION_DF, alias_groups=[])

    assert outcome.fail == {}

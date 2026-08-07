import pandas as pd

from core.checks.tal import check_tal
from core.models import FieldMapping, TalConfig, TalSegment

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")

TAL_SHEET1 = pd.DataFrame([
    {"Account Name": "Severn Trent Water Limited", "Domain": "stwater.co.uk"},
])


def test_flat_tal_domain_found_passes():
    config = TalConfig(enabled=True, segmented=False, flat_sheet_name="Sheet1")
    new_leads = pd.DataFrame([{"emailaddress": "x@stwater.co.uk", "company": "Severn Trent", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {"Sheet1": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail == {}


def test_flat_tal_domain_not_found_fails():
    config = TalConfig(enabled=True, segmented=False, flat_sheet_name="Sheet1")
    new_leads = pd.DataFrame([{"emailaddress": "x@notlisted.com", "company": "Not Listed", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {"Sheet1": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail[0] == "TAL - not found"


def test_segmented_tal_resolves_correct_sheet_by_cid():
    config = TalConfig(enabled=True, segmented=True, segments=[
        TalSegment(name="UK Geo", cids=["114578"], sheet_name="UKTab"),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@stwater.co.uk", "company": "Severn Trent", "CID": "114578"}])

    outcome = check_tal(new_leads, FM, config, {"UKTab": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail == {}


def test_company_name_required_and_not_found_fails_even_with_domain_match():
    config = TalConfig(enabled=True, segmented=False, flat_sheet_name="Sheet1", check_company_name=True)
    new_leads = pd.DataFrame([{"emailaddress": "x@stwater.co.uk", "company": "Totally Different Co", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {"Sheet1": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail[0] == "TAL - company not found"


def test_disabled_check_produces_no_failures():
    config = TalConfig(enabled=False)
    new_leads = pd.DataFrame([{"emailaddress": "x@notlisted.com", "company": "X", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {}, alias_groups=[])

    assert outcome.fail == {}

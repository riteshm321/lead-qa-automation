import pandas as pd

from core.checks.tal import check_tal
from core.models import FieldMapping, TalConfig, ReferenceSource

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")

TAL_SHEET1 = pd.DataFrame([
    {"Account Name": "Severn Trent Water Limited", "Domain": "stwater.co.uk"},
])

TAL_SHEET_ACME = pd.DataFrame([
    {"Account Name": "Acme Industrial Supply", "Domain": "acme.com"},
])

UNIVERSAL_SOURCE = ReferenceSource(name="Global TAL", file_path="tal.xlsx", sheet_name="Sheet1")


def test_flat_tal_domain_found_passes():
    config = TalConfig(enabled=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@stwater.co.uk", "company": "Severn Trent", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {"Global TAL": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail == {}


def test_flat_tal_domain_not_found_fails():
    config = TalConfig(enabled=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@notlisted.com", "company": "Not Listed", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {"Global TAL": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail[0] == "TAL - not found"


def test_segmented_tal_resolves_correct_source_by_cid():
    config = TalConfig(enabled=True, sources=[
        ReferenceSource(name="UK Geo", file_path="tal_uk.xlsx", sheet_name="UKTab", cids=["114578"]),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@stwater.co.uk", "company": "Severn Trent", "CID": "114578"}])

    outcome = check_tal(new_leads, FM, config, {"UK Geo": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail == {}


def test_lead_outside_any_segment_cids_is_skipped_not_failed():
    config = TalConfig(enabled=True, sources=[
        ReferenceSource(name="UK Geo", file_path="tal_uk.xlsx", sheet_name="UKTab", cids=["114578"]),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@notlisted.com", "company": "X", "CID": "999999"}])

    outcome = check_tal(new_leads, FM, config, {"UK Geo": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail == {}


def test_universal_and_segment_scoped_sources_combine_for_in_scope_lead():
    universal_df = pd.DataFrame([{"Account Name": "Global Partner", "Domain": "globalpartner.com"}])
    config = TalConfig(enabled=True, sources=[
        ReferenceSource(name="Global", file_path="global.xlsx", sheet_name="Sheet1"),
        ReferenceSource(name="UK Geo", file_path="tal_uk.xlsx", sheet_name="UKTab", cids=["114578"]),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@stwater.co.uk", "company": "Severn Trent", "CID": "114578"}])

    outcome = check_tal(new_leads, FM, config, {"Global": universal_df, "UK Geo": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail == {}


def test_company_name_required_and_not_found_fails_even_with_domain_match():
    config = TalConfig(enabled=True, sources=[UNIVERSAL_SOURCE], check_company_name=True)
    new_leads = pd.DataFrame([{"emailaddress": "x@stwater.co.uk", "company": "Totally Different Co", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {"Global TAL": TAL_SHEET1}, alias_groups=[])

    assert outcome.fail[0] == "TAL - company not found"


def test_disabled_check_produces_no_failures():
    config = TalConfig(enabled=False)
    new_leads = pd.DataFrame([{"emailaddress": "x@notlisted.com", "company": "X", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {}, alias_groups=[])

    assert outcome.fail == {}


def test_company_name_gray_zone_fuzzy_match_goes_to_review():
    config = TalConfig(enabled=True, sources=[
        ReferenceSource(name="Acme Source", file_path="acme.xlsx", sheet_name="Sheet1"),
    ], check_company_name=True)
    new_leads = pd.DataFrame([{"emailaddress": "x@acme.com", "company": "Acme Industries", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {"Acme Source": TAL_SHEET_ACME}, alias_groups=[])

    assert 0 not in outcome.fail, "Lead should not fail when company name is a gray-zone match"
    detail = outcome.review[0]
    assert detail.check == "TAL"
    assert detail.lead_value == "Acme Industries"
    assert detail.candidate_value


def test_sources_with_different_column_names_each_use_their_own():
    df_a = pd.DataFrame([{"Domain": "a.com", "Account Name": "A Co"}])
    df_b = pd.DataFrame([{"Website": "b.com", "Company": "B Co"}])
    config = TalConfig(enabled=True, sources=[
        ReferenceSource(name="A", file_path="a.xlsx", sheet_name="Sheet1"),
        ReferenceSource(name="B", file_path="b.xlsx", sheet_name="Sheet1",
                         domain_column="Website", company_column="Company"),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@b.com", "company": "B Co", "CID": "1"}])

    outcome = check_tal(new_leads, FM, config, {"A": df_a, "B": df_b}, alias_groups=[])

    assert outcome.fail == {}

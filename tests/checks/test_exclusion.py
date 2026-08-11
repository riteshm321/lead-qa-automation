import pandas as pd

from core.checks.exclusion import check_exclusion
from core.models import FieldMapping, ExclusionConfig, ReferenceSource

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")

EXCLUSION_DF = pd.DataFrame([
    {"Account Name": "Adecco UK Ltd", "Domain": "adecco.co.uk"},
    {"Account Name": "Enerpac Tool Group, Inc.", "Domain": "enerpactoolgroup.com"},
])

UNIVERSAL_SOURCE = ReferenceSource(name="Global", file_path="unused.xlsx", sheet_name="Exclusion")


def test_domain_match_fails():
    config = ExclusionConfig(enabled=True, check_company_name=False, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@adecco.co.uk", "company": "Someone Else", "CID": "1"}])

    outcome = check_exclusion(new_leads, FM, config, {"Global": EXCLUSION_DF}, alias_groups=[])

    assert outcome.fail[0] == "Exclusion - domain"


def test_no_match_passes():
    config = ExclusionConfig(enabled=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@scania.com", "company": "Scania", "CID": "1"}])

    outcome = check_exclusion(new_leads, FM, config, {"Global": EXCLUSION_DF}, alias_groups=[])

    assert outcome.fail == {}
    assert outcome.review == {}


def test_company_name_match_fails_when_toggled_on():
    config = ExclusionConfig(enabled=True, check_company_name=True, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@unrelated-domain.com", "company": "Enerpac Tool Group", "CID": "1"}])

    outcome = check_exclusion(new_leads, FM, config, {"Global": EXCLUSION_DF}, alias_groups=[])

    assert outcome.fail[0] == "Exclusion - company"


def test_disabled_check_produces_no_failures():
    config = ExclusionConfig(enabled=False, sources=[UNIVERSAL_SOURCE])
    new_leads = pd.DataFrame([{"emailaddress": "x@adecco.co.uk", "company": "Adecco", "CID": "1"}])

    outcome = check_exclusion(new_leads, FM, config, {"Global": EXCLUSION_DF}, alias_groups=[])

    assert outcome.fail == {}


def test_multiple_universal_sources_are_unioned():
    df_a = pd.DataFrame([{"Account Name": "A Co", "Domain": "a.com"}])
    df_b = pd.DataFrame([{"Account Name": "B Co", "Domain": "b.com"}])
    config = ExclusionConfig(enabled=True, sources=[
        ReferenceSource(name="A", file_path="a.xlsx", sheet_name="Sheet1"),
        ReferenceSource(name="B", file_path="b.xlsx", sheet_name="Sheet1"),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@b.com", "company": "B Co", "CID": "1"}])

    outcome = check_exclusion(new_leads, FM, config, {"A": df_a, "B": df_b}, alias_groups=[])

    assert outcome.fail[0] == "Exclusion - domain"


def test_segment_scoped_source_only_applies_to_its_own_cids():
    df_emea = pd.DataFrame([{"Account Name": "EMEA Excluded Co", "Domain": "emea-excluded.com"}])
    config = ExclusionConfig(enabled=True, sources=[
        ReferenceSource(name="EMEA", file_path="emea.xlsx", sheet_name="Sheet1", cids=["100"]),
    ])
    apac_lead = pd.DataFrame([{"emailaddress": "x@emea-excluded.com", "company": "X", "CID": "200"}])

    outcome = check_exclusion(apac_lead, FM, config, {"EMEA": df_emea}, alias_groups=[])

    assert outcome.fail == {}


def test_universal_and_segment_scoped_sources_combine_for_in_scope_lead():
    universal_df = pd.DataFrame([{"Account Name": "Global Bad Co", "Domain": "globalbad.com"}])
    emea_df = pd.DataFrame([{"Account Name": "EMEA Bad Co", "Domain": "emeabad.com"}])
    config = ExclusionConfig(enabled=True, sources=[
        ReferenceSource(name="Global", file_path="global.xlsx", sheet_name="Sheet1"),
        ReferenceSource(name="EMEA", file_path="emea.xlsx", sheet_name="Sheet1", cids=["100"]),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@emeabad.com", "company": "X", "CID": "100"}])

    outcome = check_exclusion(new_leads, FM, config, {"Global": universal_df, "EMEA": emea_df}, alias_groups=[])

    assert outcome.fail[0] == "Exclusion - domain"


def test_sources_with_different_column_names_each_use_their_own():
    df_a = pd.DataFrame([{"Domain": "a.com", "Account Name": "A Co"}])
    df_b = pd.DataFrame([{"Website": "b.com", "Company": "B Co"}])
    config = ExclusionConfig(enabled=True, sources=[
        ReferenceSource(name="A", file_path="a.xlsx", sheet_name="Sheet1"),
        ReferenceSource(name="B", file_path="b.xlsx", sheet_name="Sheet1",
                         domain_column="Website", company_column="Company"),
    ])
    new_leads = pd.DataFrame([{"emailaddress": "x@b.com", "company": "B Co", "CID": "1"}])

    outcome = check_exclusion(new_leads, FM, config, {"A": df_a, "B": df_b}, alias_groups=[])

    assert outcome.fail[0] == "Exclusion - domain"

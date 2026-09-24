from core.models import (
    FieldMapping, LeadcapSegment, LeadcapConfig, TalConfig,
    ExclusionConfig, ReferenceSource, SuppressionConfig, DedupeListConfig, DuplicateConfig,
    ClientProfile, IntegrateConfig, resolve_field_mapping,
)
from core.check_result import CheckOutcome


def test_client_profile_defaults():
    fm = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                       company="company", cid="CID")
    profile = ClientProfile(
        name="Basware",
        accumulated_report_path="sample_data/Basware APAC – Accumulated Report.xlsx",
        field_mapping=fm,
    )
    assert profile.duplicate == DuplicateConfig()
    assert profile.leadcap.enabled is False
    assert profile.tal.sources == []
    assert profile.exclusion.sources == []
    assert profile.suppression.sources == []
    assert profile.dedupe_list.sources == []
    assert profile.field_mapping.email == "emailaddress"


def test_field_mapping_is_blank():
    assert FieldMapping(email="", first_name="", last_name="", company="", cid="").is_blank() is True
    assert FieldMapping(email="Email", first_name="", last_name="", company="", cid="").is_blank() is False


def test_resolve_field_mapping_falls_back_when_preferred_is_none_or_blank():
    fallback = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    blank = FieldMapping(email="", first_name="", last_name="", company="", cid="")
    real = FieldMapping(email="Work Email", first_name="F", last_name="L", company="Co", cid="CID2")

    # Regression test for a real bug: Client Setup's "optional" column-
    # mapping sections used to save FieldMapping(all blank) instead of
    # None when every dropdown was left unset -- a plain `preferred or
    # fallback` treats that blank-but-non-None object as truthy and wins
    # over the fallback, silently blanking every field it's used for
    # (confirmed in IBM APAC's real profile: Company/CID came out blank
    # everywhere accumulated_field_mapping was consulted).
    assert resolve_field_mapping(None, fallback) is fallback
    assert resolve_field_mapping(blank, fallback) is fallback
    assert resolve_field_mapping(real, fallback) is real


def test_leadcap_segment_equality():
    a = LeadcapSegment(name="AU Geo", cids=["114578"], cap=8)
    b = LeadcapSegment(name="AU Geo", cids=["114578"], cap=8)
    assert a == b


def test_reference_source_defaults_to_applying_everywhere():
    source = ReferenceSource(name="Global", file_path="x.xlsx", sheet_name="Sheet1")
    assert source.cids == []


def test_reference_source_column_defaults():
    source = ReferenceSource(name="Global", file_path="x.xlsx", sheet_name="Sheet1")
    assert source.domain_column == "Domain"
    assert source.company_column == "Account Name"
    assert source.email_column == "Email"


def test_reference_source_equality():
    a = ReferenceSource(name="EMEA", file_path="emea.xlsx", sheet_name="Sheet1", cids=["100"])
    b = ReferenceSource(name="EMEA", file_path="emea.xlsx", sheet_name="Sheet1", cids=["100"])
    assert a == b


def test_check_outcome_defaults_are_independent():
    a = CheckOutcome()
    b = CheckOutcome()
    a.fail[1] = "x"
    assert b.fail == {}


def test_client_profile_defaults_to_a_disabled_integrate_config():
    profile = ClientProfile(name="X", accumulated_report_path="acc.xlsx")
    assert profile.integrate.enabled is False
    assert profile.integrate.sid == ""
    assert profile.integrate.field_mapping == {}
    assert profile.integrate.fixed_field_values == {}
    assert profile.integrate.leadfile_field_mapping is None

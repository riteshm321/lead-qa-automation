from core.models import (
    FieldMapping, LeadcapSegment, LeadcapConfig, TalConfig,
    ExclusionConfig, ReferenceSource, SuppressionConfig, DuplicateConfig, DedupeListConfig,
    ClientProfile,
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
    assert profile.field_mapping.email == "emailaddress"


def test_leadcap_segment_equality():
    a = LeadcapSegment(name="AU Geo", cids=["114578"], cap=8)
    b = LeadcapSegment(name="AU Geo", cids=["114578"], cap=8)
    assert a == b


def test_reference_source_defaults_to_applying_everywhere():
    source = ReferenceSource(name="Global", file_path="x.xlsx", sheet_name="Sheet1")
    assert source.cids == []


def test_reference_source_equality():
    a = ReferenceSource(name="EMEA", file_path="emea.xlsx", sheet_name="Sheet1", cids=["100"])
    b = ReferenceSource(name="EMEA", file_path="emea.xlsx", sheet_name="Sheet1", cids=["100"])
    assert a == b


def test_check_outcome_defaults_are_independent():
    a = CheckOutcome()
    b = CheckOutcome()
    a.fail[1] = "x"
    assert b.fail == {}

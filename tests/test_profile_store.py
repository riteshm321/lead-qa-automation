from core.models import (
    ClientProfile, FieldMapping, LeadcapConfig, LeadcapSegment,
    TalConfig, ExclusionConfig, ReferenceSource, SuppressionConfig, DedupeListConfig,
)
from core.profile_store import save_profile, load_profile, list_profile_names


def _sample_profile() -> ClientProfile:
    return ClientProfile(
        name="Basware",
        accumulated_report_path="sample_data/Basware APAC – Accumulated Report.xlsx",
        field_mapping=FieldMapping(email="emailaddress", first_name="firstname",
                                    last_name="lastname", company="company", cid="CID"),
        leadcap=LeadcapConfig(enabled=True, segmented=True, check_company_name=True, segments=[
            LeadcapSegment(name="AU Geo", cids=["114578"], cap=8),
            LeadcapSegment(name="IN Geo", cids=["114568"], cap=5),
        ]),
        tal=TalConfig(enabled=True, sources=[
            ReferenceSource(name="Global TAL", file_path="sample_data/tal.xlsx", sheet_name="Sheet1"),
        ]),
        exclusion=ExclusionConfig(enabled=True, sources=[
            ReferenceSource(name="Global Exclusion", file_path="sample_data/Basware -Exclusion List.xlsx",
                             sheet_name="Exclusion"),
            ReferenceSource(name="EMEA Exclusion", file_path="sample_data/emea_exclusion.xlsx",
                             sheet_name="Sheet1", cids=["114578", "114579"],
                             domain_column="Website", company_column="Company"),
        ]),
        suppression=SuppressionConfig(enabled=True, check_domain=True, sources=[
            ReferenceSource(name="Global Suppression", file_path="sample_data/suppression.xlsx", sheet_name="Sheet1"),
        ]),
        dedupe_list=DedupeListConfig(enabled=True, sources=[
            ReferenceSource(name="Global Dedupe", file_path="sample_data/dedupe.xlsx", sheet_name="Sheet1"),
        ]),
    )


def test_save_and_load_round_trip(tmp_path):
    clients_dir = str(tmp_path / "clients")
    profile = _sample_profile()

    saved_path = save_profile(profile, clients_dir=clients_dir)
    assert saved_path.endswith("Basware.json")

    loaded = load_profile("Basware", clients_dir=clients_dir)
    assert loaded == profile


def test_list_profile_names(tmp_path):
    clients_dir = str(tmp_path / "clients")
    save_profile(_sample_profile(), clients_dir=clients_dir)
    assert list_profile_names(clients_dir=clients_dir) == ["Basware"]

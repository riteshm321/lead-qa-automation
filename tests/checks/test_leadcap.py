import pandas as pd

from core.checks.leadcap import check_leadcap, validate_purchased_report_cids
from core.models import FieldMapping, LeadcapConfig, LeadcapSegment

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")


def test_flat_leadcap_fails_when_count_meets_cap():
    config = LeadcapConfig(enabled=True, segmented=False, flat_cap=2)
    new_leads = pd.DataFrame([{"CID": "118118", "emailaddress": "a@x.com"}])
    purchased = pd.DataFrame({"Campaign ID": ["118118", "118118"]})

    outcome = check_leadcap(new_leads, FM, config, {"_flat_": purchased})

    assert outcome.fail[0] == "Leadcap exceeded"


def test_flat_leadcap_passes_when_under_cap():
    config = LeadcapConfig(enabled=True, segmented=False, flat_cap=5)
    new_leads = pd.DataFrame([{"CID": "118118", "emailaddress": "a@x.com"}])
    purchased = pd.DataFrame({"Campaign ID": ["118118", "118118"]})

    outcome = check_leadcap(new_leads, FM, config, {"_flat_": purchased})

    assert outcome.fail == {}


def test_segmented_leadcap_pools_cap_across_cids_in_segment():
    config = LeadcapConfig(enabled=True, segmented=True, segments=[
        LeadcapSegment(name="Shared Pair", cids=["98778", "98779"], cap=5),
    ])
    new_leads = pd.DataFrame([{"CID": "98779", "emailaddress": "a@x.com"}])
    purchased = pd.DataFrame({"Campaign ID": ["98778", "98778", "98778", "98779", "98779"]})

    outcome = check_leadcap(new_leads, FM, config, {"Shared Pair": purchased})

    assert outcome.fail[0] == "Leadcap exceeded"


def test_leadcap_disabled_produces_no_failures():
    config = LeadcapConfig(enabled=False)
    new_leads = pd.DataFrame([{"CID": "118118", "emailaddress": "a@x.com"}])

    outcome = check_leadcap(new_leads, FM, config, {})

    assert outcome.fail == {}


def test_cid_not_in_any_segment_is_skipped():
    config = LeadcapConfig(enabled=True, segmented=True, segments=[
        LeadcapSegment(name="AU Geo", cids=["114578"], cap=8),
    ])
    new_leads = pd.DataFrame([{"CID": "999999", "emailaddress": "a@x.com"}])

    outcome = check_leadcap(new_leads, FM, config, {"AU Geo": pd.DataFrame({"Campaign ID": []})})

    assert outcome.fail == {}


def test_validate_purchased_report_cids_flags_unexpected():
    report = pd.DataFrame({"Campaign ID": ["114578", "114568"]})
    unexpected = validate_purchased_report_cids(report, expected_cids=["114578"], cid_column="Campaign ID")
    assert unexpected == ["114568"]

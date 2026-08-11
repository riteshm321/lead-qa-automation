import pandas as pd

from core.checks.leadcap import check_leadcap, validate_purchased_report_cids
from core.models import FieldMapping, LeadcapConfig, LeadcapSegment

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")


def test_flat_leadcap_fails_when_count_meets_cap():
    config = LeadcapConfig(enabled=True, segmented=False, flat_cap=2)
    new_leads = pd.DataFrame([{"CID": "118118", "emailaddress": "a@x.com"}])
    purchased = pd.DataFrame({
        "Campaign ID": ["118118", "118118"],
        "Email": ["p1@x.com", "p2@x.com"],
    })

    outcome = check_leadcap(new_leads, FM, config, {"_flat_": purchased})

    assert outcome.fail[0] == "Leadcap exceeded"


def test_flat_leadcap_passes_when_under_cap():
    config = LeadcapConfig(enabled=True, segmented=False, flat_cap=5)
    new_leads = pd.DataFrame([{"CID": "118118", "emailaddress": "a@x.com"}])
    purchased = pd.DataFrame({
        "Campaign ID": ["118118", "118118"],
        "Email": ["p1@x.com", "p2@x.com"],
    })

    outcome = check_leadcap(new_leads, FM, config, {"_flat_": purchased})

    assert outcome.fail == {}


def test_segmented_leadcap_pools_cap_across_cids_in_segment():
    config = LeadcapConfig(enabled=True, segmented=True, segments=[
        LeadcapSegment(name="Shared Pair", cids=["98778", "98779"], cap=5),
    ])
    new_leads = pd.DataFrame([{"CID": "98779", "emailaddress": "a@x.com"}])
    purchased = pd.DataFrame({
        "Campaign ID": ["98778", "98778", "98778", "98779", "98779"],
        "Email": ["p1@x.com", "p2@x.com", "p3@x.com", "p4@x.com", "p5@x.com"],
    })

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

    outcome = check_leadcap(new_leads, FM, config,
                             {"AU Geo": pd.DataFrame({"Campaign ID": [], "Email": []})})

    assert outcome.fail == {}


def test_leadcap_counts_per_domain_not_whole_campaign():
    # Regression test for the "counts total leads per CID, not per account/domain" bug.
    # A cap of 5 leads/account must not fail a lead just because the CID as a whole
    # has lots of purchased volume from OTHER domains.
    config = LeadcapConfig(enabled=True, segmented=True, segments=[
        LeadcapSegment(name="Shared Pair", cids=["98778", "98779"], cap=5),
    ])
    purchased = pd.DataFrame({
        "Campaign ID": ["98778", "98778", "98778", "98778", "98779", "98779"],
        "Email": [
            "a1@heavydomain.com", "a2@heavydomain.com", "a3@heavydomain.com", "a4@heavydomain.com",
            "b1@lightdomain.com", "b2@lightdomain.com",
        ],
    })

    new_leads = pd.DataFrame([
        {"CID": "98779", "emailaddress": "new@lightdomain.com"},  # domain has 2 prior purchases, cap=5 -> PASS
        {"CID": "98778", "emailaddress": "new@heavydomain.com"},  # domain has 4 prior purchases... still < 5 -> PASS
    ])

    outcome = check_leadcap(new_leads, FM, config, {"Shared Pair": purchased})

    assert outcome.fail == {}


def test_leadcap_fails_when_domain_specific_count_meets_cap():
    config = LeadcapConfig(enabled=True, segmented=True, segments=[
        LeadcapSegment(name="Shared Pair", cids=["98778", "98779"], cap=5),
    ])
    purchased = pd.DataFrame({
        "Campaign ID": ["98778", "98778", "98778", "98778", "98778", "98779"],
        "Email": [
            "a1@heavydomain.com", "a2@heavydomain.com", "a3@heavydomain.com",
            "a4@heavydomain.com", "a5@heavydomain.com", "b1@lightdomain.com",
        ],
    })

    new_leads = pd.DataFrame([
        {"CID": "98779", "emailaddress": "new@lightdomain.com"},  # only 1 prior purchase -> PASS
        {"CID": "98778", "emailaddress": "new@heavydomain.com"},  # 5 prior purchases, cap=5 -> FAIL
    ])

    outcome = check_leadcap(new_leads, FM, config, {"Shared Pair": purchased})

    assert 0 not in outcome.fail
    assert outcome.fail[1] == "Leadcap exceeded"


def test_validate_purchased_report_cids_flags_unexpected():
    report = pd.DataFrame({"Campaign ID": ["114578", "114568"], "Email": ["a@x.com", "b@x.com"]})
    unexpected = validate_purchased_report_cids(report, expected_cids=["114578"], cid_column="Campaign ID")
    assert unexpected == ["114568"]


def test_leadcap_company_pass_fails_when_passed_domain_but_exceeds_company():
    config = LeadcapConfig(enabled=True, segmented=True, check_company_name=True, segments=[
        LeadcapSegment(name="Shared Pair", cids=["98778", "98779"], cap=3),
    ])
    purchased = pd.DataFrame({
        "Campaign ID": ["98778", "98778", "98778", "98779"],
        "Email": ["a1@one.com", "a2@two.com", "a3@three.com", "b1@four.com"],
        "Company": ["Acme Corp", "Acme Corp", "Acme Corp", "Other Co"],
    })
    new_leads = pd.DataFrame([
        {"CID": "98778", "emailaddress": "new@brandnewdomain.com", "company": "Acme Corp"},
    ])

    outcome = check_leadcap(new_leads, FM, config, {"Shared Pair": purchased})

    assert outcome.fail[0] == "Leadcap Exceed - By Company Name"


def test_leadcap_company_pass_skipped_when_domain_already_failed():
    config = LeadcapConfig(enabled=True, segmented=True, check_company_name=True, segments=[
        LeadcapSegment(name="Shared Pair", cids=["98778"], cap=1),
    ])
    purchased = pd.DataFrame({
        "Campaign ID": ["98778"],
        "Email": ["existing@samedomain.com"],
        "Company": ["Totally Different Co"],
    })
    new_leads = pd.DataFrame([
        {"CID": "98778", "emailaddress": "new@samedomain.com", "company": "Totally Different Co"},
    ])

    outcome = check_leadcap(new_leads, FM, config, {"Shared Pair": purchased})

    assert outcome.fail[0] == "Leadcap exceeded"


def test_leadcap_company_pass_not_evaluated_when_toggle_off():
    config = LeadcapConfig(enabled=True, segmented=True, check_company_name=False, segments=[
        LeadcapSegment(name="Shared Pair", cids=["98778"], cap=1),
    ])
    purchased = pd.DataFrame({
        "Campaign ID": ["98778"],
        "Email": ["existing@other.com"],
        "Company": ["Acme Corp"],
    })
    new_leads = pd.DataFrame([
        {"CID": "98778", "emailaddress": "new@newdomain.com", "company": "Acme Corp"},
    ])

    outcome = check_leadcap(new_leads, FM, config, {"Shared Pair": purchased})

    assert outcome.fail == {}


def test_leadcap_company_match_is_exact_case_insensitive_trimmed():
    config = LeadcapConfig(enabled=True, segmented=True, check_company_name=True, segments=[
        LeadcapSegment(name="Shared Pair", cids=["98778"], cap=1),
    ])
    purchased = pd.DataFrame({
        "Campaign ID": ["98778"],
        "Email": ["existing@other.com"],
        "Company": ["  Acme Corp  "],
    })
    new_leads = pd.DataFrame([
        {"CID": "98778", "emailaddress": "new@newdomain.com", "company": "acme corp"},
    ])

    outcome = check_leadcap(new_leads, FM, config, {"Shared Pair": purchased})

    assert outcome.fail[0] == "Leadcap Exceed - By Company Name"


def test_leadcap_company_near_match_does_not_count_not_fuzzy():
    config = LeadcapConfig(enabled=True, segmented=True, check_company_name=True, segments=[
        LeadcapSegment(name="Shared Pair", cids=["98778"], cap=1),
    ])
    purchased = pd.DataFrame({
        "Campaign ID": ["98778"],
        "Email": ["existing@other.com"],
        "Company": ["Acme Corporation"],
    })
    new_leads = pd.DataFrame([
        {"CID": "98778", "emailaddress": "new@newdomain.com", "company": "Acme Corp"},
    ])

    outcome = check_leadcap(new_leads, FM, config, {"Shared Pair": purchased})

    assert outcome.fail == {}

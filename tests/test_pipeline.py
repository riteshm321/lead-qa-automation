import pandas as pd

from core.pipeline import run_pipeline
from core.models import (
    ClientProfile, FieldMapping, DuplicateConfig, ExclusionConfig, ReferenceSource,
)

FM = FieldMapping(email="emailaddress", first_name="firstname", last_name="lastname",
                   company="company", cid="CID")


def _profile(**overrides) -> ClientProfile:
    base = dict(
        name="Test",
        accumulated_report_path="unused.xlsx",
        field_mapping=FM,
    )
    base.update(overrides)
    return ClientProfile(**base)


def test_valid_lead_passes_through_with_no_checks_enabled():
    profile = _profile()
    new_leads = pd.DataFrame([{"emailaddress": "a@x.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1"}])
    accumulated = pd.DataFrame(columns=["emailaddress", "firstname", "lastname", "company", "CID"])

    result = run_pipeline(new_leads, profile, accumulated, reference_data={}, alias_groups=[])

    assert result.valid_indices == [0]
    assert result.refund_reasons == {}
    assert result.review_reasons == {}


def test_lead_failing_duplicate_and_exclusion_lists_both_reasons():
    profile = _profile(
        duplicate=DuplicateConfig(enabled=True),
        exclusion=ExclusionConfig(enabled=True, sources=[
            ReferenceSource(name="Global", file_path="unused.xlsx", sheet_name="Exclusion"),
        ]),
    )
    new_leads = pd.DataFrame([{"emailaddress": "a@excluded.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1"}])
    accumulated = pd.DataFrame([{"emailaddress": "a@excluded.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1"}])
    exclusion_df = pd.DataFrame([{"Account Name": "Excluded Co", "Domain": "excluded.com"}])

    result = run_pipeline(
        new_leads, profile, accumulated,
        reference_data={"exclusion_sources": {"Global": exclusion_df}},
        alias_groups=[],
    )

    assert result.valid_indices == []
    assert "Duplicate - exact email" in result.refund_reasons[0]
    assert "Exclusion - domain" in result.refund_reasons[0]


def test_review_item_excluded_from_valid_and_refund():
    profile = _profile(duplicate=DuplicateConfig(enabled=True))
    new_leads = pd.DataFrame([{"emailaddress": "andy@unrelated.com", "firstname": "Andy", "lastname": "Jones", "company": "Unrelated", "CID": "1"}])
    accumulated = pd.DataFrame([{"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": "1"}])

    result = run_pipeline(new_leads, profile, accumulated, reference_data={}, alias_groups=[])

    assert result.valid_indices == []
    assert result.refund_reasons == {}
    assert 0 in result.review_reasons


def test_fail_takes_precedence_over_review_for_same_lead():
    profile = _profile(
        duplicate=DuplicateConfig(enabled=True),
        exclusion=ExclusionConfig(enabled=True, sources=[
            ReferenceSource(name="Global", file_path="unused.xlsx", sheet_name="Exclusion"),
        ]),
    )
    new_leads = pd.DataFrame([{"emailaddress": "andy@excluded.com", "firstname": "Andy", "lastname": "Jones", "company": "Unrelated", "CID": "1"}])
    accumulated = pd.DataFrame([{"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": "1"}])
    exclusion_df = pd.DataFrame([{"Account Name": "Excluded Co", "Domain": "excluded.com"}])

    result = run_pipeline(
        new_leads, profile, accumulated,
        reference_data={"exclusion_sources": {"Global": exclusion_df}},
        alias_groups=[],
    )

    assert 0 in result.refund_reasons
    assert 0 not in result.review_reasons

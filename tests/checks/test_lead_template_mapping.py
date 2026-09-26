import pandas as pd

from core.checks.lead_template_mapping import check_lead_template_mandatory_columns
from core.models import FieldMapping, LeadTemplateColumnRule, LeadTemplateMappingConfig

FM = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")


def test_flags_every_lead_once_when_mandatory_column_has_no_resolvable_source():
    new_leads = pd.DataFrame([
        {"Email": "a@x.com", "CID": "1"},
        {"Email": "b@x.com", "CID": "1"},
    ])
    config = LeadTemplateMappingConfig(rules=[
        LeadTemplateColumnRule(template_column="Totally Unmatched Column", mandatory=True),
    ])

    outcome = check_lead_template_mandatory_columns(new_leads, FM, config)

    assert set(outcome.review.keys()) == {0, 1}
    assert "Totally Unmatched Column" in outcome.review[0].message


def test_flags_only_rows_with_a_blank_value_in_a_resolvable_mandatory_column():
    new_leads = pd.DataFrame([
        {"Email": "a@x.com", "CID": "1", "Company Size": "50"},
        {"Email": "b@x.com", "CID": "1", "Company Size": ""},
        {"Email": "c@x.com", "CID": "1", "Company Size": float("nan")},
    ])
    config = LeadTemplateMappingConfig(rules=[
        LeadTemplateColumnRule(template_column="Company Size", mandatory=True),
    ])

    outcome = check_lead_template_mandatory_columns(new_leads, FM, config)

    assert set(outcome.review.keys()) == {1, 2}
    assert "Company Size" in outcome.review[1].message


def test_manual_source_override_is_used_for_mandatory_resolution():
    new_leads = pd.DataFrame([{"Email": "a@x.com", "CID": "1", "Employee Count": "75"}])
    config = LeadTemplateMappingConfig(rules=[
        LeadTemplateColumnRule(template_column="Company Size", source_column="Employee Count", mandatory=True),
    ])

    outcome = check_lead_template_mandatory_columns(new_leads, FM, config)

    assert outcome.review == {}


def test_non_mandatory_rule_never_produces_a_review_flag():
    new_leads = pd.DataFrame([{"Email": "a@x.com", "CID": "1"}])
    config = LeadTemplateMappingConfig(rules=[
        LeadTemplateColumnRule(template_column="Totally Unmatched Column", mandatory=False),
    ])

    outcome = check_lead_template_mandatory_columns(new_leads, FM, config)

    assert outcome.review == {}
    assert outcome.fail == {}


def test_empty_config_produces_no_flags():
    new_leads = pd.DataFrame([{"Email": "a@x.com", "CID": "1"}])
    outcome = check_lead_template_mandatory_columns(new_leads, FM, LeadTemplateMappingConfig())
    assert outcome.review == {} and outcome.fail == {}


def test_mandatory_column_resolves_via_known_field_synonym_like_append_leads_does():
    # Regression test (Finding 1, final review): the mandatory-column check
    # previously only tried a manual source_column override, then jumped
    # straight to find_passthrough_lead_column's fuzzy-match chain -- it
    # never tried the plain field-synonym tier append_leads' own
    # _resolve_passthrough_columns (via resolve_one_header_source) tries
    # first. Marking "Email Address" mandatory with a leadfile column
    # literally named "Email" used to flag every lead as unresolvable
    # ("no leadfile column found") even though append_leads would
    # correctly write it via the email synonym.
    new_leads = pd.DataFrame([{"Email": "a@x.com", "CID": "1"}])
    config = LeadTemplateMappingConfig(rules=[
        LeadTemplateColumnRule(template_column="Email Address", mandatory=True),
    ])

    outcome = check_lead_template_mandatory_columns(new_leads, FM, config)

    assert outcome.review == {}


def test_mandatory_column_resolves_via_target_field_mapping_role_like_append_leads_does():
    # Same bug, exercised via the OTHER tier append_leads tries before
    # fuzzy matching: the Lead Template's own target_field_mapping role
    # (e.g. its "email" field mapped to header "Email Address"), which
    # resolves through field_mapping.email regardless of any synonym text
    # match at all.
    new_leads = pd.DataFrame([{"Email": "a@x.com", "CID": "1"}])
    target_fm = FieldMapping(email="Email Address", first_name="", last_name="", company="", cid="")
    config = LeadTemplateMappingConfig(rules=[
        LeadTemplateColumnRule(template_column="Email Address", mandatory=True),
    ])

    outcome = check_lead_template_mandatory_columns(new_leads, FM, config, target_fm)

    assert outcome.review == {}

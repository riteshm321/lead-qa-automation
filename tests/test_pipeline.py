import pandas as pd

from core.pipeline import run_pipeline, apply_refund_overrides, PipelineResult
from core.models import (
    ClientProfile, FieldMapping, DuplicateConfig, ExclusionConfig, ReferenceSource,
    SuppressionConfig, DedupeListConfig, LeadTemplateMappingConfig, LeadTemplateColumnRule,
    GoogleSheetsConfig,
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


def test_on_progress_called_once_per_enabled_check_in_order():
    profile = _profile(
        duplicate=DuplicateConfig(enabled=True),
        exclusion=ExclusionConfig(enabled=True, sources=[
            ReferenceSource(name="Global", file_path="unused.xlsx", sheet_name="Exclusion"),
        ]),
        suppression=SuppressionConfig(enabled=True, sources=[
            ReferenceSource(name="Global", file_path="unused.xlsx", sheet_name="Suppression"),
        ]),
    )
    new_leads = pd.DataFrame([{"emailaddress": "a@x.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1"}])
    accumulated = pd.DataFrame(columns=["emailaddress", "firstname", "lastname", "company", "CID"])
    seen_labels = []

    run_pipeline(
        new_leads, profile, accumulated,
        reference_data={
            "exclusion_sources": {"Global": pd.DataFrame(columns=["Account Name", "Domain"])},
            "suppression_sources": {"Global": pd.DataFrame(columns=["Account Name", "Domain"])},
        },
        alias_groups=[], on_progress=seen_labels.append,
    )

    assert seen_labels == ["Checking Duplicates", "Checking Exclusion List", "Checking Suppression List"]


def test_on_progress_is_optional_and_defaults_to_no_callback():
    profile = _profile(duplicate=DuplicateConfig(enabled=True))
    new_leads = pd.DataFrame([{"emailaddress": "a@x.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1"}])
    accumulated = pd.DataFrame(columns=["emailaddress", "firstname", "lastname", "company", "CID"])

    result = run_pipeline(new_leads, profile, accumulated, reference_data={}, alias_groups=[])

    assert result.valid_indices == [0]


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
    # Same name AND same company, but a different email domain - the one
    # scenario the duplicate check sends to review rather than pass/fail.
    profile = _profile(duplicate=DuplicateConfig(enabled=True))
    new_leads = pd.DataFrame([{"emailaddress": "andy@other-domain.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": "1"}])
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
    new_leads = pd.DataFrame([{"emailaddress": "andy@excluded.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": "1"}])
    accumulated = pd.DataFrame([{"emailaddress": "andy@google.com", "firstname": "Andy", "lastname": "Jones", "company": "Google", "CID": "1"}])
    exclusion_df = pd.DataFrame([{"Account Name": "Excluded Co", "Domain": "excluded.com"}])

    result = run_pipeline(
        new_leads, profile, accumulated,
        reference_data={"exclusion_sources": {"Global": exclusion_df}},
        alias_groups=[],
    )

    assert 0 in result.refund_reasons
    assert 0 not in result.review_reasons


def test_suppression_and_dedupe_use_sources_keys():
    profile = _profile(
        suppression=SuppressionConfig(enabled=True, check_domain=True, sources=[
            ReferenceSource(name="Sup", file_path="unused.xlsx", sheet_name="Sheet1"),
        ]),
        dedupe_list=DedupeListConfig(enabled=True, sources=[
            ReferenceSource(name="Dedupe", file_path="unused.xlsx", sheet_name="Sheet1"),
        ]),
    )
    new_leads = pd.DataFrame([{"emailaddress": "x@suppressed.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1"}])
    accumulated = pd.DataFrame(columns=["emailaddress", "firstname", "lastname", "company", "CID"])
    suppression_df = pd.DataFrame([{"Domain": "suppressed.com"}])

    result = run_pipeline(
        new_leads, profile, accumulated,
        reference_data={"suppression_sources": {"Sup": suppression_df}, "dedupe_sources": {}},
        alias_groups=[],
    )

    assert result.refund_reasons[0] == "Suppression - domain"


def test_run_pipeline_with_no_mandatory_lead_template_rules_is_unaffected():
    # Default ClientProfile.lead_template_mapping is an empty
    # LeadTemplateMappingConfig (no rules), so the new mandatory-column
    # check should never even run -- same PipelineResult as before this
    # feature existed for a fixture with no data-quality issues.
    profile = _profile()
    new_leads = pd.DataFrame([{"emailaddress": "a@x.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1"}])
    accumulated = pd.DataFrame(columns=["emailaddress", "firstname", "lastname", "company", "CID"])

    result = run_pipeline(new_leads, profile, accumulated, reference_data={}, alias_groups=[])

    assert result.valid_indices == [0]
    assert result.refund_reasons == {}
    assert result.review_reasons == {}


def test_run_pipeline_passes_lead_template_field_mapping_to_the_mandatory_check():
    # Regression test (Finding 1, final review): run_pipeline must pass
    # profile.lead_template_field_mapping through to
    # check_lead_template_mandatory_columns as its target_field_mapping --
    # otherwise the mandatory check can never resolve a column via the
    # Lead Template's own target role, only field_mapping's plain synonyms,
    # and would wrongly flag every lead for a column resolvable ONLY via
    # that target-role tier. "Primary Email" is deliberately not a known
    # field synonym (unlike e.g. "Email Address") -- it resolves ONLY
    # through the Lead Template's own target_field_mapping.email == "Primary
    # Email" pointing at field_mapping.email == "Email", exactly the tier
    # this test exists to prove run_pipeline actually wires up.
    profile = _profile(
        field_mapping=FieldMapping(email="Email", first_name="", last_name="", company="", cid=""),
        lead_template_field_mapping=FieldMapping(
            email="Primary Email", first_name="", last_name="", company="", cid=""),
        lead_template_mapping=LeadTemplateMappingConfig(rules=[
            LeadTemplateColumnRule(template_column="Primary Email", mandatory=True),
        ]),
    )
    new_leads = pd.DataFrame([{"Email": "a@x.com"}])
    accumulated = pd.DataFrame(columns=["Email"])

    result = run_pipeline(new_leads, profile, accumulated, reference_data={}, alias_groups=[])

    assert result.review_reasons == {}


def test_run_pipeline_ignores_mandatory_google_sheets_rules():
    # Same fixture shape as
    # test_run_pipeline_passes_lead_template_field_mapping_to_the_mandatory_check
    # above, but via profile.google_sheets.mapping instead of
    # profile.lead_template_mapping -- proves core/pipeline.py's SECOND
    # check_lead_template_mandatory_columns call (wired against
    # google_sheets.mapping, added by this task) actually runs. That
    # function is reused completely unchanged for this second call (see
    # Task 5 report) -- its ReviewDetail.check is still hardcoded "Lead
    # Template Mapping" regardless of which config triggered it, so the
    # message text (naming the specific unmatched column) is what actually
    # proves THIS rule fired, not the check label.
    profile = _profile(
        google_sheets=GoogleSheetsConfig(mapping=LeadTemplateMappingConfig(rules=[
            LeadTemplateColumnRule(template_column="Totally Unmatched Column", mandatory=True),
        ])),
    )
    new_leads = pd.DataFrame([
        {"emailaddress": "a@x.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1"},
        {"emailaddress": "b@x.com", "firstname": "C", "lastname": "D", "company": "Y", "CID": "2"},
    ])
    accumulated = pd.DataFrame(columns=["emailaddress", "firstname", "lastname", "company", "CID"])

    result = run_pipeline(new_leads, profile, accumulated, reference_data={}, alias_groups=[])

    # Mandatory columns apply only to the Lead Template, not Google Sheets.
    assert result.review_reasons == {}
    assert result.mandatory_blank_indices == set()


def test_run_pipeline_with_no_mandatory_google_sheets_rules_is_unaffected():
    # Default ClientProfile.google_sheets is an empty GoogleSheetsConfig (no
    # rules), so the new mandatory-column check should never even run --
    # same non-regression shape as
    # test_run_pipeline_with_no_mandatory_lead_template_rules_is_unaffected.
    profile = _profile()
    new_leads = pd.DataFrame([{"emailaddress": "a@x.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1"}])
    accumulated = pd.DataFrame(columns=["emailaddress", "firstname", "lastname", "company", "CID"])

    result = run_pipeline(new_leads, profile, accumulated, reference_data={}, alias_groups=[])

    assert result.valid_indices == [0]
    assert result.refund_reasons == {}
    assert result.review_reasons == {}


def test_apply_refund_overrides_promotes_approved_leads_to_valid():
    result = PipelineResult(valid_indices=[0], refund_reasons={1: "Duplicate - exact email", 2: "Exclusion - domain"})

    final_valid, final_refund_reasons = apply_refund_overrides(result, approved_refund_indices=[1])

    assert sorted(final_valid) == [0, 1]
    assert final_refund_reasons == {2: "Exclusion - domain"}


def test_apply_refund_overrides_with_no_approvals_leaves_refund_unchanged():
    result = PipelineResult(valid_indices=[0], refund_reasons={1: "Duplicate - exact email"})

    final_valid, final_refund_reasons = apply_refund_overrides(result, approved_refund_indices=[])

    assert final_valid == [0]
    assert final_refund_reasons == {1: "Duplicate - exact email"}


def test_apply_refund_overrides_approving_all_empties_refund_bucket():
    result = PipelineResult(valid_indices=[], refund_reasons={1: "A", 2: "B"})

    final_valid, final_refund_reasons = apply_refund_overrides(result, approved_refund_indices=[1, 2])

    assert sorted(final_valid) == [1, 2]
    assert final_refund_reasons == {}


def test_custom_questions_check_runs_in_pipeline_with_refund_review_and_valid():
    from core.models import CustomQuestionRule, CustomQuestionsConfig

    question = "1. Which widget features matter most to you?"
    allowed = ["a) Speed, reliability & uptime", "b) Security / compliance", "c) Price"]
    profile = _profile(custom_questions=CustomQuestionsConfig(enabled=True, rules=[
        CustomQuestionRule(format="header", column=question, question_text=question,
                           allowed_answers=allowed, count_rule="at_most", count=2),
    ]))
    base = {"emailaddress": "a@x.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1"}
    new_leads = pd.DataFrame([
        {**base, question: "a) Speed, reliability & uptime, b) Security / compliance"},
        {**base, question: "d) Free lunches"},
        {**base, question: "b) Security / complaince"},
        {**base, question: ""},
    ])
    accumulated = pd.DataFrame(columns=list(base))
    seen_labels = []

    result = run_pipeline(new_leads, profile, accumulated, reference_data={}, alias_groups=[],
                          on_progress=seen_labels.append)

    assert seen_labels == ["Checking Custom Questions"]
    assert result.valid_indices == [0]
    assert result.refund_reasons == {1: "CQ1: 'd) Free lunches' is not an allowed answer",
                                     3: "CQ1 not answered"}
    assert list(result.review_reasons) == [2]
    assert result.review_reasons[2][0].check == "Custom Questions"


def test_lead_notes_check_runs_in_pipeline_with_refund_review_and_valid():
    from core.models import LeadNotesConfig, LeadNotesField

    profile = _profile(lead_notes=LeadNotesConfig(enabled=True, notes_column="Lead Notes", fields=[
        LeadNotesField(kind="email", column="emailaddress", required=True, action="refund"),
        LeadNotesField(kind="job_title", column="Title", required=True),
    ]))
    base = {"emailaddress": "jane@acme.example", "firstname": "Jane", "lastname": "Doe", "company": "Acme",
            "CID": "1", "Title": "Director of Sales"}
    new_leads = pd.DataFrame([
        {**base, "Lead Notes": "Jane, Director of Sales, asked for a demo at jane@acme.example."},
        {**base, "Lead Notes": "Jane, Director of Sales, asked for a demo at jd@globex.example."},
        {**base, "Lead Notes": "Jane asked for a demo at jane@acme.example."},
    ])
    accumulated = pd.DataFrame(columns=list(base))
    seen_labels = []

    result = run_pipeline(new_leads, profile, accumulated, reference_data={}, alias_groups=[],
                          on_progress=seen_labels.append)

    assert seen_labels == ["Checking Lead Notes"]
    assert result.valid_indices == [0]
    assert result.refund_reasons == {
        1: "Notes: email jd@globex.example doesn't match lead email jane@acme.example"}
    assert list(result.review_reasons) == [2]
    assert result.review_reasons[2][0].check == "Lead Notes"


def test_custom_questions_combined_cell_runs_in_pipeline_without_rules():
    from core.models import CustomQuestionsConfig

    profile = _profile(custom_questions=CustomQuestionsConfig(enabled=True, combined_cell_column="Custom"))
    base = {"emailaddress": "a@x.example", "firstname": "A", "lastname": "B", "company": "X", "CID": "1",
            "Budget": "$10,000 to $50,000"}
    new_leads = pd.DataFrame([
        {**base, "Custom": "Budget: $10,000 to $50,000;I agree: true"},
        {**base, "Custom": "Budget: Above $50,000;I agree: true"},
    ])
    result = run_pipeline(new_leads, profile, pd.DataFrame(columns=list(base)), reference_data={},
                          alias_groups=[])
    assert result.valid_indices == [0]
    assert result.refund_reasons == {
        1: "Custom cell says 'Above $50,000' but 'Budget' column says '$10,000 to $50,000'"}


def test_blank_mandatory_lead_template_value_goes_to_review_and_cannot_be_approved():
    # A blank/unmapped mandatory column is a data/mapping gap, not a failed
    # lead: it goes to Needs Review, but can never be approved as valid
    # (directly, or after being marked refund), so it is never written blank.
    from core.review_actions import approve_review_leads, refund_review_leads
    profile = _profile(lead_template_mapping=LeadTemplateMappingConfig(rules=[
        LeadTemplateColumnRule(template_column="Company Size", mandatory=True),
    ]))
    new_leads = pd.DataFrame([
        {"emailaddress": "a@x.com", "firstname": "A", "lastname": "B", "company": "X", "CID": "1",
         "Company Size": "50"},
        {"emailaddress": "b@x.com", "firstname": "C", "lastname": "D", "company": "Y", "CID": "2",
         "Company Size": " "},
    ])
    accumulated = pd.DataFrame(columns=["emailaddress", "firstname", "lastname", "company", "CID"])

    result = run_pipeline(new_leads, profile, accumulated, reference_data={}, alias_groups=[])
    assert 1 in result.review_reasons and 1 not in result.refund_reasons
    assert result.mandatory_blank_indices == {1}

    assert approve_review_leads(result, [1]) == [1]
    assert 1 in result.review_reasons and 1 not in result.valid_indices

    refund_review_leads(result, [1])
    final_valid, final_refunds = apply_refund_overrides(result, [1])
    assert 1 not in final_valid and 1 in final_refunds

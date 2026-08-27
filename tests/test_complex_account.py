import datetime
import io

import openpyxl
import pandas as pd

from core.complex_account import (
    load_tal_index, match_tal_account, apply_tal_mapping,
    load_domain_value_map, reformat_capture_date, clean_email_optin, asset_download_parts,
    format_phone, load_asset_specifications, apply_complex_account_rules,
    merge_complex_account_review, check_complex_account_conditions, check_asset_url_mismatches,
)
from core.check_result import ReviewDetail
from core.models import FieldMapping
from core.pipeline import PipelineResult


def _upload(name: str, text: str) -> io.BytesIO:
    f = io.BytesIO(text.encode("utf-8"))
    f.name = name
    return f


FM = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")


def test_load_tal_index_and_match_unambiguous(tmp_path):
    tal_path = str(tmp_path / "tal.csv")
    pd.DataFrame([
        {"web_domain": "wipro.com", "account_id": "P123", "account_name": "Wipro Ltd", "country_code": "IN"},
        {"web_domain": "unrelated.com", "account_id": "P999", "account_name": "Unrelated Co", "country_code": "US"},
    ]).to_csv(tal_path, index=False)

    tal_index = load_tal_index(tal_path)
    account_id, account_name = match_tal_account("wipro.com", "IN", tal_index)
    assert account_id == "P123"
    assert account_name == "Wipro Ltd"

    assert match_tal_account("nomatch.com", "IN", tal_index) == (None, None)


def test_match_tal_account_ambiguous_domain_prefers_country_match(tmp_path):
    tal_path = str(tmp_path / "tal.csv")
    pd.DataFrame([
        {"web_domain": "shared.com", "account_id": "P_JP", "account_name": "Shared JP", "country_code": "JP"},
        {"web_domain": "shared.com", "account_id": "P_IN", "account_name": "Shared IN", "country_code": "IN"},
    ]).to_csv(tal_path, index=False)
    tal_index = load_tal_index(tal_path)

    account_id, account_name = match_tal_account("shared.com", "IN", tal_index)
    assert account_id == "P_IN"
    assert account_name == "Shared IN"


def test_match_tal_account_ambiguous_domain_with_no_country_match_still_returns_one(tmp_path):
    # Never leave it blank just because the tie can't be broken by country.
    tal_path = str(tmp_path / "tal.csv")
    pd.DataFrame([
        {"web_domain": "shared.com", "account_id": "P_JP", "account_name": "Shared JP", "country_code": "JP"},
        {"web_domain": "shared.com", "account_id": "P_AU", "account_name": "Shared AU", "country_code": "AU"},
    ]).to_csv(tal_path, index=False)
    tal_index = load_tal_index(tal_path)

    account_id, account_name = match_tal_account("shared.com", "IN", tal_index)
    assert account_id in ("P_JP", "P_AU")


def test_apply_tal_mapping_leaves_company_untouched_and_account_id_blank_on_no_match():
    tal_index = {"wipro.com": [{"account_id": "P123", "account_name": "Wipro Ltd", "country_code": "IN"}]}
    leads = pd.DataFrame([
        {"Email": "a@wipro.com", "Country": "IN", "Account ID": "Vlookup from TAL provided", "Company": "Wipro"},
        {"Email": "b@unknown.com", "Country": "IN", "Account ID": "Vlookup from TAL provided", "Company": "Unknown Inc"},
    ])
    result = apply_tal_mapping(leads, "Email", "Country", "Account ID", "Company", tal_index)

    assert result.loc[0, "Account ID"] == "P123"
    assert result.loc[0, "Company"] == "Wipro Ltd"
    assert result.loc[1, "Account ID"] == ""
    assert result.loc[1, "Company"] == "Unknown Inc"  # untouched, not blanked


def test_load_domain_value_map_skips_metadata_lines_and_blank_domains():
    csv_text = (
        "Client: Dell APAC\n"
        '"Program: Dell APAC_Whitespace (ID: 139849)"\n'
        "\n"
        "Company,Domain,Category,Installed Technologies,Verified on Date\n"
        "Wipro,wipro.com,Cloud,\"AWS, Azure\",2026-08-01\n"
        "Blank Domain Co,,Cloud,Something,2026-08-01\n"
    )
    mapping = load_domain_value_map(_upload("it.csv", csv_text), "Domain", "Installed Technologies")

    assert mapping == {"wipro.com": "AWS, Azure"}


def test_load_domain_value_map_matches_real_pbs_column_layout():
    # Real Predictive Buying Stage export: "Targeted Accounts" holds the
    # domain despite its header text, confirmed against the actual file.
    csv_text = (
        "Client: Dell APAC\n"
        '"Program: Dell APAC (ID: 139843)"\n'
        "\n"
        "Targeted Accounts,Trending,Reached,Engaged,Predictive Buying Stage\n"
        "kelltontech.com,Yes,Yes,Yes,No Active Signals\n"
        "emcure.com,Yes,Yes,Yes,Awareness\n"
    )
    mapping = load_domain_value_map(_upload("pbs.csv", csv_text), "Targeted Accounts", "Predictive Buying Stage")

    assert mapping == {"kelltontech.com": "No Active Signals", "emcure.com": "Awareness"}


def test_load_domain_value_map_aggregates_multiple_rows_for_same_domain():
    # A domain can appear on more than one row — one Installed Technology
    # per row — and all of them should be combined, not just the last one.
    csv_text = (
        "Client: Dell APAC\n"
        '"Program: Dell APAC (ID: 139849)"\n'
        "\n"
        "Company,Domain,Category,Installed Technologies,Verified on Date\n"
        "Cipla,cipla.com,OS,Oracle Linux,2026-08-01\n"
        "Cipla,cipla.com,Networking,Cisco,2026-08-01\n"
        "Cipla,cipla.com,Storage,Pure Storage,2026-08-01\n"
        "Cipla,cipla.com,OS,Oracle Linux,2026-08-01\n"  # exact duplicate — must not repeat
    )
    mapping = load_domain_value_map(
        _upload("it.csv", csv_text), "Domain", "Installed Technologies", aggregate=True)

    assert mapping == {"cipla.com": "Oracle Linux, Cisco, Pure Storage"}


def test_load_domain_value_map_skips_configured_values():
    csv_text = (
        "Client: Dell APAC\n"
        '"Program: Dell APAC (ID: 139843)"\n'
        "\n"
        "Targeted Accounts,Trending,Reached,Engaged,Predictive Buying Stage\n"
        "kelltontech.com,Yes,Yes,Yes,No Active Signals\n"
        "emcure.com,Yes,Yes,Yes,Awareness\n"
    )
    mapping = load_domain_value_map(
        _upload("pbs.csv", csv_text), "Targeted Accounts", "Predictive Buying Stage",
        skip_values={"No Active Signals"})

    # kelltontech.com is left out entirely, not mapped to the literal label.
    assert mapping == {"emcure.com": "Awareness"}


def test_reformat_capture_date_handles_mmddyyyy_text():
    assert reformat_capture_date("08/17/2026") == "08/17/2026"


def test_reformat_capture_date_handles_other_text_formats():
    assert reformat_capture_date("17-Aug-2026") == "08/17/2026"
    assert reformat_capture_date("August 17, 2026") == "08/17/2026"


def test_reformat_capture_date_returns_none_for_blank_or_unparseable():
    assert reformat_capture_date(None) is None
    assert reformat_capture_date("") is None
    assert reformat_capture_date("not a date") is None


def test_clean_email_optin_collapses_verbose_values():
    assert clean_email_optin("Yes, Yes") == "Yes"
    assert clean_email_optin("Yes, I would like Dell to contact me by email., Yes, I would like Dell to "
                              "contact me by phone.") == "Yes"
    assert clean_email_optin("No") == "No"


def test_clean_email_optin_returns_none_when_ambiguous():
    assert clean_email_optin("Maybe") is None
    assert clean_email_optin("") is None
    assert clean_email_optin(None) is None
    assert clean_email_optin("Yes and No") is None


def test_asset_download_parts():
    day, month = asset_download_parts("08/17/2026")
    assert day == 17
    assert month == "August"

    day, month = asset_download_parts("08/05/2026")
    assert day == 5


def test_asset_download_parts_accepts_a_date_object():
    day, month = asset_download_parts(datetime.date(2026, 8, 5))
    assert day == 5
    assert month == "August"


def test_format_phone_strips_punctuation_and_inserts_space():
    assert format_phone("+91-98-197-19038") == "91 9819719038"
    assert format_phone(919819719038) == "91 9819719038"
    assert format_phone("91") == "91"
    assert format_phone(None) == ""


def test_load_asset_specifications(tmp_path):
    # Real header text: wraps onto a second line and carries bracketed
    # "[to be filled in by ...]" annotations -- matched by substring, not
    # exact text, so this proves that robustness, not just the happy path.
    path = str(tmp_path / "specs.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([
        "Asset Name\n[to be filled in by EssenceMediacom]",
        "URN \n[to be filled in by EssenceMediacom]",
        "Publisher Link [AU]_BHRS\n[to be filled in by Publisher]",
        "Publisher Link INDIA]_ECS\n[to be filled in by Publisher]",
        "Dell Link",
    ])
    ws.append([
        "Fuel AI Innovation", "DT2503G0007_033",
        "https://a.com/au", "https://a.com/india", "https://dell.com/x",
    ])
    wb.save(path)

    specs = load_asset_specifications(path)

    assert "fuel ai innovation" in specs
    assert specs["fuel ai innovation"]["urn"] == "DT2503G0007_033"
    assert specs["fuel ai innovation"]["au_link"] == "https://a.com/au"
    assert specs["fuel ai innovation"]["india_link"] == "https://a.com/india"
    assert specs["fuel ai innovation"]["dell_url"] == "https://dell.com/x"


_ASSET_SPECS = {
    "fuel ai innovation": {
        "urn": "DT2503G0007_033", "au_link": "https://a.com/au",
        "india_link": "https://a.com/india", "dell_url": "https://dell.com/x",
    },
}


def test_check_asset_url_mismatches_passes_when_everything_matches_for_india_cid():
    df = pd.DataFrame([{
        "CID": "119414", "Asset Title": "Fuel AI Innovation", "Asset URN": "DT2503G0007_033",
        "Form URL": "https://a.com/india", "Dell Asset URL": "https://dell.com/x",
    }])
    assert check_asset_url_mismatches(df, _ASSET_SPECS, FM) == {}


def test_check_asset_url_mismatches_passes_when_everything_matches_for_au_cid():
    df = pd.DataFrame([{
        "CID": "119415", "Asset Title": "Fuel AI Innovation", "Asset URN": "DT2503G0007_033",
        "Form URL": "https://a.com/au", "Dell Asset URL": "https://dell.com/x",
    }])
    assert check_asset_url_mismatches(df, _ASSET_SPECS, FM) == {}


def test_check_asset_url_mismatches_flags_wrong_urn_and_dell_url():
    # Two separate mismatches -> two separate findings, each naming exactly
    # which field is wrong (not one combined "URN/Form URL/Dell Asset URL
    # don't match" catch-all a reviewer would have to guess at).
    df = pd.DataFrame([{
        "CID": "119414", "Asset Title": "Fuel AI Innovation", "Asset URN": "WRONG_URN",
        "Form URL": "https://a.com/india", "Dell Asset URL": "https://wrong-dell.com",
    }])
    review = check_asset_url_mismatches(df, _ASSET_SPECS, FM)

    assert 0 in review
    messages = [str(d) for d in review[0]]
    assert any("Asset URN doesn't match" in m for m in messages)
    assert any("Dell Asset URL doesn't match" in m for m in messages)
    assert not any("Form URL" in m for m in messages)  # matched the india_link — not flagged

    urn_detail = next(d for d in review[0] if "Asset URN" in d.message)
    assert urn_detail.lead_value == "WRONG_URN"
    assert urn_detail.candidate_value == "DT2503G0007_033"

    dell_detail = next(d for d in review[0] if "Dell Asset URL" in d.message)
    assert dell_detail.lead_value == "https://wrong-dell.com"
    assert dell_detail.candidate_value == "https://dell.com/x"


def test_check_asset_url_mismatches_flags_wrong_form_url_for_india_cid():
    df = pd.DataFrame([{
        "CID": "119414", "Asset Title": "Fuel AI Innovation", "Asset URN": "DT2503G0007_033",
        "Form URL": "https://wrong.com", "Dell Asset URL": "https://dell.com/x",
    }])
    review = check_asset_url_mismatches(df, _ASSET_SPECS, FM)

    assert 0 in review
    assert len(review[0]) == 1  # only Form URL is wrong -- not a combined finding
    detail = review[0][0]
    assert "Form URL doesn't match" in detail.message
    assert detail.lead_value == "https://wrong.com"
    assert detail.candidate_value == "https://a.com/india"


def test_check_asset_url_mismatches_flags_wrong_form_url_for_au_cid():
    df = pd.DataFrame([{
        "CID": "119415", "Asset Title": "Fuel AI Innovation", "Asset URN": "DT2503G0007_033",
        "Form URL": "https://wrong.com", "Dell Asset URL": "https://dell.com/x",
    }])
    review = check_asset_url_mismatches(df, _ASSET_SPECS, FM)

    assert 0 in review
    assert review[0][0].candidate_value == "https://a.com/au"


def test_check_asset_url_mismatches_skips_form_url_check_for_other_cids():
    # No rule was specified for any CID besides 119414/119415 -- Form URL
    # isn't checked at all for them, even though it matches neither link.
    df = pd.DataFrame([{
        "CID": "999999", "Asset Title": "Fuel AI Innovation", "Asset URN": "DT2503G0007_033",
        "Form URL": "https://totally-wrong.com", "Dell Asset URL": "https://dell.com/x",
    }])
    assert check_asset_url_mismatches(df, _ASSET_SPECS, FM) == {}


def test_check_asset_url_mismatches_skips_form_url_check_without_field_mapping():
    df = pd.DataFrame([{
        "CID": "119414", "Asset Title": "Fuel AI Innovation", "Asset URN": "DT2503G0007_033",
        "Form URL": "https://totally-wrong.com", "Dell Asset URL": "https://dell.com/x",
    }])
    assert check_asset_url_mismatches(df, _ASSET_SPECS) == {}


def test_check_asset_url_mismatches_flags_asset_title_not_found_in_specifications():
    df = pd.DataFrame([{
        "CID": "119414", "Asset Title": "Some Unknown Asset", "Asset URN": "whatever",
        "Form URL": "https://whatever.com", "Dell Asset URL": "https://whatever-dell.com",
    }])
    review = check_asset_url_mismatches(df, _ASSET_SPECS, FM)

    assert 0 in review
    assert len(review[0]) == 1
    assert "not found in the specifications file" in review[0][0].message
    assert review[0][0].lead_value == "Some Unknown Asset"


def test_check_asset_url_mismatches_does_not_flag_a_blank_asset_title():
    df = pd.DataFrame([{
        "CID": "119414", "Asset Title": "", "Asset URN": "", "Form URL": "", "Dell Asset URL": "",
    }])
    assert check_asset_url_mismatches(df, _ASSET_SPECS, FM) == {}


def _base_leads_df() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "CID": "119414", "Email": "a@wipro.com", "First": "A", "Last": "One",
            "Country": "IN", "Account ID": "Vlookup from TAL provided", "Company": "Wipro",
            "Capture Date": "08/17/2026", "Email Opt-in": "Yes, Yes", "Business Phone": 919819719038,
            "Asset Title": "Fuel AI Innovation", "Asset URN": "WRONG", "Form URL": "https://wrong.com",
            "Dell Asset URL": "https://wrong-dell.com",
            "Additional Data Point (poll questions, dynamic data, etc)  1": "AI, Cloud",
            "Additional Data Point (poll questions, dynamic data, etc)  2": "stale placeholder",
            "Additional Data Point (poll questions, dynamic data, etc)  3": "stale placeholder",
            "Asset download day": " ", "Asset download month": " ", "Asset download year": " ",
        },
    ])


def test_check_complex_account_conditions_flags_bad_date_and_optin_without_mutating():
    df = _base_leads_df()
    df.loc[0, "Capture Date"] = "not a date"
    df.loc[0, "Email Opt-in"] = "Maybe"

    review = check_complex_account_conditions(df)

    assert 0 in review
    assert any("Capture Date" in str(r) for r in review[0])
    assert any("Email Opt-in" in str(r) for r in review[0])
    # Purely a check — the source DataFrame must be untouched.
    assert df.loc[0, "Capture Date"] == "not a date"
    assert df.loc[0, "Email Opt-in"] == "Maybe"


def test_check_complex_account_conditions_passes_clean_leads():
    df = _base_leads_df()
    assert check_complex_account_conditions(df) == {}


def test_apply_complex_account_rules_end_to_end():
    df = _base_leads_df()
    tal_index = {"wipro.com": [{"account_id": "P123", "account_name": "Wipro Ltd", "country_code": "IN"}]}
    it_map = {"wipro.com": "AWS, Azure"}
    pbs_map = {"wipro.com": "Awareness"}

    enriched, review, _ = apply_complex_account_rules(df, FM, tal_index, it_map, pbs_map)

    assert review == {}
    row = enriched.iloc[0]
    assert row["Account ID"] == "P123"
    assert row["Company"] == "Wipro Ltd"
    assert row["Additional Data Point (poll questions, dynamic data, etc)  1"] == "Top Trending Topics: AI, Cloud"
    assert row["Additional Data Point (poll questions, dynamic data, etc)  2"] == "Installed Technologies: AWS, Azure"
    assert row["Additional Data Point (poll questions, dynamic data, etc)  3"] == "Predictive Buying Stage: Awareness"
    # A real date object, not text — so Excel stores/filters it as a date.
    assert row["Capture Date"] == datetime.date(2026, 8, 17)
    assert row["Email Opt-in"] == "Yes"
    assert row["Business Phone"] == "91 9819719038"
    # No asset_specs passed here -> the Asset URN/Form URL/Dell Asset URL
    # correction step (see the dedicated correction tests below) is a
    # no-op, leaving these untouched.
    assert row["Asset URN"] == "WRONG"
    assert row["Form URL"] == "https://wrong.com"
    assert row["Dell Asset URL"] == "https://wrong-dell.com"
    # Numbers, not text, so Excel doesn't flag "Number Stored as Text".
    assert row["Asset download day"] == 17
    assert row["Asset download month"] == "August"
    assert row["Asset download year"] == 2026


def test_apply_complex_account_rules_corrects_urn_dell_url_and_form_url_for_india_cid():
    df = _base_leads_df()  # CID 119414, wrong Asset URN/Form URL/Dell Asset URL

    enriched, _, corrections = apply_complex_account_rules(
        df, FM, None, {}, {}, asset_specs=_ASSET_SPECS)

    assert enriched.loc[0, "Asset URN"] == "DT2503G0007_033"
    assert enriched.loc[0, "Dell Asset URL"] == "https://dell.com/x"
    assert enriched.loc[0, "Form URL"] == "https://a.com/india"  # CID 119414 -> india_link
    assert 0 in corrections
    joined = "; ".join(corrections[0])
    assert "Asset URN" in joined and "WRONG" in joined and "DT2503G0007_033" in joined
    assert "Dell Asset URL" in joined
    assert "Form URL" in joined


def test_apply_complex_account_rules_corrects_form_url_using_au_link_for_119415():
    df = pd.DataFrame([{**_base_leads_df().iloc[0].to_dict(), "CID": "119415"}])

    enriched, _, corrections = apply_complex_account_rules(
        df, FM, None, {}, {}, asset_specs=_ASSET_SPECS)

    assert enriched.loc[0, "Form URL"] == "https://a.com/au"
    assert any("Form URL" in c for c in corrections[0])


def test_apply_complex_account_rules_does_not_touch_already_correct_values():
    df = pd.DataFrame([{
        **_base_leads_df().iloc[0].to_dict(),
        "Asset URN": "DT2503G0007_033", "Dell Asset URL": "https://dell.com/x",
        "Form URL": "https://a.com/india",
    }])

    _, _, corrections = apply_complex_account_rules(df, FM, None, {}, {}, asset_specs=_ASSET_SPECS)

    assert corrections == {}


def test_apply_complex_account_rules_skips_correction_for_unrecognized_asset():
    df = pd.DataFrame([{**_base_leads_df().iloc[0].to_dict(), "Asset Title": "Unknown Asset"}])

    enriched, _, corrections = apply_complex_account_rules(
        df, FM, None, {}, {}, asset_specs=_ASSET_SPECS)

    assert corrections == {}
    assert enriched.loc[0, "Asset URN"] == "WRONG"  # nothing to correct against


def test_apply_complex_account_rules_skips_correction_for_other_cids():
    df = pd.DataFrame([{**_base_leads_df().iloc[0].to_dict(), "CID": "999999"}])

    enriched, _, corrections = apply_complex_account_rules(
        df, FM, None, {}, {}, asset_specs=_ASSET_SPECS)

    # Asset URN/Dell Asset URL are still corrected (not CID-scoped)...
    assert enriched.loc[0, "Asset URN"] == "DT2503G0007_033"
    # ...but Form URL has no rule for this CID, so it's left untouched.
    assert enriched.loc[0, "Form URL"] == "https://wrong.com"
    assert not any("Form URL" in c for c in corrections.get(0, []))


def test_apply_complex_account_rules_no_op_without_asset_specs():
    df = _base_leads_df()

    _, _, corrections = apply_complex_account_rules(df, FM, None, {}, {})

    assert corrections == {}


def test_apply_complex_account_rules_clears_mail_optin_and_signal_notes():
    df = pd.DataFrame([{
        **_base_leads_df().iloc[0].to_dict(), "Mail Opt-In": "Yes", "Signal Notes": "some note",
    }])

    enriched, _, _ = apply_complex_account_rules(df, FM, None, {}, {})

    assert enriched.loc[0, "Mail Opt-In"] == ""
    assert enriched.loc[0, "Signal Notes"] == ""


def test_apply_complex_account_rules_matches_leads_from_different_cids_off_one_shared_map():
    # The whole point of the single combined file: a lead's CID doesn't
    # gate whether its domain gets matched -- two leads on different CIDs
    # both get filled from the very same installed_tech_map/pbs_map.
    df = pd.DataFrame([
        {**_base_leads_df().iloc[0].to_dict(), "CID": "119414", "Email": "a@wipro.com"},
        {**_base_leads_df().iloc[0].to_dict(), "CID": "119843", "Email": "b@acme.com"},
    ])
    it_map = {"wipro.com": "AWS, Azure", "acme.com": "GCP"}
    pbs_map = {"wipro.com": "Awareness", "acme.com": "Consideration"}

    enriched, _, _ = apply_complex_account_rules(df, FM, None, it_map, pbs_map)

    col_it = "Additional Data Point (poll questions, dynamic data, etc)  2"
    col_pbs = "Additional Data Point (poll questions, dynamic data, etc)  3"
    assert enriched.loc[0, col_it] == "Installed Technologies: AWS, Azure"
    assert enriched.loc[0, col_pbs] == "Predictive Buying Stage: Awareness"
    assert enriched.loc[1, col_it] == "Installed Technologies: GCP"
    assert enriched.loc[1, col_pbs] == "Predictive Buying Stage: Consideration"


def test_apply_complex_account_rules_sets_agreed_contacted_by_cid():
    # Fixed business rule for this client's two CID groups -- not derived
    # from the leadfile at all.
    df = pd.DataFrame([
        {**_base_leads_df().iloc[0].to_dict(), "CID": "119414",
         "Agreed to be contacted by Dell Technologies": ""},
        {**_base_leads_df().iloc[0].to_dict(), "CID": "119415",
         "Agreed to be contacted by Dell Technologies": ""},
        {**_base_leads_df().iloc[0].to_dict(), "CID": "999999",  # unrecognized CID
         "Agreed to be contacted by Dell Technologies": ""},
    ])

    enriched, _, _ = apply_complex_account_rules(df, FM, None, {}, {})

    col = "Agreed to be contacted by Dell Technologies"
    assert enriched.loc[0, col] == "No"
    assert enriched.loc[1, col] == "Yes"
    assert enriched.loc[2, col] == ""


def test_apply_complex_account_rules_matches_agreed_contacted_cid_when_column_upcast_to_float():
    # Same float-upcast risk as any other CID comparison -- a blank cell
    # elsewhere in the CID column turns "119414" into 119414.0.
    df = pd.DataFrame([
        {**_base_leads_df().iloc[0].to_dict(), "CID": "119415",
         "Agreed to be contacted by Dell Technologies": ""},
    ])
    df["CID"] = df["CID"].astype(float)

    enriched, _, _ = apply_complex_account_rules(df, FM, None, {}, {})

    assert enriched.loc[0, "Agreed to be contacted by Dell Technologies"] == "Yes"


def test_apply_complex_account_rules_sets_phone_optin_yes_for_every_lead_regardless_of_cid():
    df = pd.DataFrame([
        {**_base_leads_df().iloc[0].to_dict(), "CID": "119414", "Phone Opt-In": ""},
        {**_base_leads_df().iloc[0].to_dict(), "CID": "119415", "Phone Opt-In": "No"},
    ])

    enriched, _, _ = apply_complex_account_rules(df, FM, None, {}, {})

    assert enriched.loc[0, "Phone Opt-In"] == "Yes"
    assert enriched.loc[1, "Phone Opt-In"] == "Yes"


def test_apply_complex_account_rules_matches_by_domain_regardless_of_cid():
    # Installed Technologies/Predictive Buying Stage files now cover every
    # CID in one upload -- matching is by domain alone, so a lead's CID
    # value (or its dtype, e.g. pandas upcasting an int column to float)
    # must have no bearing on whether it gets matched.
    df = _base_leads_df()
    df["CID"] = df["CID"].astype(float)
    it_map = {"wipro.com": "AWS, Azure"}
    pbs_map = {"wipro.com": "Awareness"}

    enriched, _, _ = apply_complex_account_rules(df, FM, None, it_map, pbs_map)

    row = enriched.iloc[0]
    assert row["Additional Data Point (poll questions, dynamic data, etc)  2"] == "Installed Technologies: AWS, Azure"
    assert row["Additional Data Point (poll questions, dynamic data, etc)  3"] == "Predictive Buying Stage: Awareness"


def test_apply_complex_account_rules_flags_bad_capture_date_and_optin_for_review():
    df = _base_leads_df()
    df.loc[0, "Capture Date"] = "not a date"
    df.loc[0, "Email Opt-in"] = "Maybe"

    enriched, review, _ = apply_complex_account_rules(df, FM, None, {}, {})

    assert 0 in review
    assert all(isinstance(r, ReviewDetail) for r in review[0])
    assert any("Capture Date" in str(r) for r in review[0])
    assert any("Email Opt-in" in str(r) for r in review[0])
    # Asset download parts must not be derived from an unparseable date.
    assert enriched.loc[0, "Asset download day"] == " "


def test_apply_complex_account_rules_leaves_blank_top_topics_cell_blank():
    # Regression test: a genuinely blank cell in an Excel-sourced DataFrame
    # reads as float NaN, not None or "" — the prefix logic must not treat
    # that as "has content" and produce "Top Trending Topics: nan".
    df = _base_leads_df()
    df.loc[0, "Additional Data Point (poll questions, dynamic data, etc)  1"] = float("nan")

    enriched, _, _ = apply_complex_account_rules(df, FM, None, {}, {})

    value = enriched.loc[0, "Additional Data Point (poll questions, dynamic data, etc)  1"]
    assert pd.isna(value)


def test_apply_complex_account_rules_clears_columns_when_domain_not_in_uploaded_maps():
    df = _base_leads_df()
    # No entry for "wipro.com" in either map (e.g. no file uploaded this
    # run) -> its columns get cleared to blank rather than left with stale
    # placeholder text.
    enriched, _, _ = apply_complex_account_rules(df, FM, None, {}, {})

    assert enriched.loc[0, "Additional Data Point (poll questions, dynamic data, etc)  2"] == ""
    assert enriched.loc[0, "Additional Data Point (poll questions, dynamic data, etc)  3"] == ""


_DATE_DETAIL = ReviewDetail(check="Complex Account", message="Capture Date is blank or unparseable")
_OPTIN_DETAIL = ReviewDetail(check="Complex Account", message="Email Opt-in value is not clearly Yes/No")


def test_apply_complex_account_rules_tolerates_header_whitespace_and_case_variation():
    # Real leadfile exported "CaptureDate" (no space) instead of the expected
    # "Capture Date" -- the exact-match column lookup must still find it,
    # rather than silently skipping the whole date/day/month block.
    df = _base_leads_df().rename(columns={"Capture Date": "CaptureDate"})
    enriched, review, _ = apply_complex_account_rules(df, FM, None, {}, {})

    assert review == {}
    assert enriched.loc[0, "Capture Date"] == datetime.date(2026, 8, 17)
    assert enriched.loc[0, "Asset download day"] == 17
    assert enriched.loc[0, "Asset download month"] == "August"


def test_merge_complex_account_review_moves_lead_from_valid_to_review():
    result = PipelineResult(valid_indices=[0, 1], refund_reasons={}, review_reasons={})
    merge_complex_account_review(result, {0: [_DATE_DETAIL]})

    assert 0 not in result.valid_indices
    assert 1 in result.valid_indices
    assert result.review_reasons[0] == [_DATE_DETAIL]


def test_merge_complex_account_review_extends_existing_review_reasons():
    other_detail = ReviewDetail(check="Duplicate", message="Some other reason")
    result = PipelineResult(valid_indices=[], refund_reasons={}, review_reasons={0: [other_detail]})
    merge_complex_account_review(result, {0: [_OPTIN_DETAIL]})

    assert result.review_reasons[0] == [other_detail, _OPTIN_DETAIL]


def test_merge_complex_account_review_does_not_override_an_existing_refund():
    result = PipelineResult(valid_indices=[], refund_reasons={0: "Duplicate - exact email"}, review_reasons={})
    merge_complex_account_review(result, {0: [_DATE_DETAIL]})

    assert 0 not in result.review_reasons
    assert result.refund_reasons[0] == "Duplicate - exact email"

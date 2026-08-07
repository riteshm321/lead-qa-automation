from core.matching import (
    extract_domain, normalize_company_name, company_names_match,
    domain_is_company_variant, load_alias_groups, save_alias_groups, add_alias_pair,
)


def test_extract_domain():
    assert extract_domain("Andy@Google.com") == "google.com"
    assert extract_domain("") == ""
    assert extract_domain("not-an-email") == ""


def test_normalize_company_name_strips_suffixes_and_punctuation():
    assert normalize_company_name("Google, Inc.") == "google"
    assert normalize_company_name("Enerpac Tool Group, Inc.") == "enerpac tool group"
    assert normalize_company_name("") == ""


def test_company_names_match_exact_after_normalization():
    result = company_names_match("Google Inc", "Google, Inc.", alias_groups=[])
    assert result.status == "match"


def test_company_names_match_via_alias_table():
    aliases = [["facebook", "meta"]]
    result = company_names_match("Facebook", "Meta", alias_groups=aliases)
    assert result.status == "match"


def test_company_names_match_no_match_for_unrelated_names():
    result = company_names_match("Danone", "Scania", alias_groups=[])
    assert result.status == "no_match"


def test_company_names_match_review_for_gray_zone():
    result = company_names_match("Basware Corp", "Basware Oy", alias_groups=[])
    assert result.status in ("match", "review")  # never a hard no_match for near-identical roots


def test_domain_is_company_variant_true_for_typo_domain():
    assert domain_is_company_variant("gooooogle.com", "Google") is True


def test_domain_is_company_variant_false_for_unrelated_domain():
    assert domain_is_company_variant("scania.com", "Google") is False


def test_alias_table_round_trip(tmp_path):
    path = str(tmp_path / "aliases.json")
    save_alias_groups([["facebook", "meta"]], path)
    assert load_alias_groups(path) == [["facebook", "meta"]]

    add_alias_pair("Google", "Alphabet", path)
    groups = load_alias_groups(path)
    assert any("google" in g and "alphabet" in g for g in groups)


def test_load_alias_groups_missing_file_returns_empty(tmp_path):
    path = str(tmp_path / "does_not_exist.json")
    assert load_alias_groups(path) == []

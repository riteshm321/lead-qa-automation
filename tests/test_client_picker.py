from core.client_picker import group_profile_names


def test_ungrouped_profile_becomes_its_own_singleton_group():
    result = group_profile_names({"Solo Client": ""})
    assert result == {"Solo Client": ["Solo Client"]}


def test_shared_group_collects_all_its_profiles_sorted():
    result = group_profile_names({
        "Autodesk EMEA": "Autodesk", "Autodesk APAC": "Autodesk", "Solo Client": "",
    })
    assert result == {
        "Autodesk": ["Autodesk APAC", "Autodesk EMEA"],
        "Solo Client": ["Solo Client"],
    }


def test_groups_are_sorted_case_insensitively():
    result = group_profile_names({"zebra corp": "", "Acme": ""})
    assert list(result.keys()) == ["Acme", "zebra corp"]


def test_empty_input_returns_empty_dict():
    assert group_profile_names({}) == {}

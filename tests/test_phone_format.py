import pytest

from core.phone_format import add_space_after_country_code, is_phone_column, looks_excel_mangled


@pytest.mark.parametrize("raw, expected", [
    ("917020209586", "91 7020209586"),
    ("+447911123456", "+44 7911123456"),
    ("14155552671", "1 4155552671"),
    ("917020209586.0", "91 7020209586"),
    ("91 7020209586", "91 7020209586"),
    ("+44 7911 123456", "+44 7911 123456"),
    ("", ""),
    ("   ", "   "),
    (None, None),
    ("not a number", "not a number"),
])
def test_add_space_after_country_code(raw, expected):
    assert add_space_after_country_code(raw) == expected


@pytest.mark.parametrize("value", ["9.17E+11", "9.17e11", "917020200000", "+91 7020200000"])
def test_looks_excel_mangled_true(value):
    assert looks_excel_mangled(value)


@pytest.mark.parametrize("value", ["917020209586", "+447911123456", "", None, "100000"])
def test_looks_excel_mangled_false(value):
    assert not looks_excel_mangled(value)


@pytest.mark.parametrize("name", ["Phone", "Phone Number", "Contact Number", "Mobile", "Work Phone", "Tel"])
def test_is_phone_column_true(name):
    assert is_phone_column(name)


@pytest.mark.parametrize("name", ["Email", "Title", "Country", "", None])
def test_is_phone_column_false(name):
    assert not is_phone_column(name)

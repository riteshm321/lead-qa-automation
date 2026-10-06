import os

import pandas as pd
from streamlit.testing.v1 import AppTest

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages", "6_Fuzzy_Match.py")


def test_page_loads_without_a_file_uploaded(monkeypatch, tmp_path):
    # AppTest can't simulate a real file upload, so this just confirms the
    # page renders cleanly with nothing selected yet -- core/fuzzy_match.py's
    # own tests cover the actual comparison/coloring logic.
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert not at.file_uploader[0].value


def test_fuzzy_match_title_icon_and_empty_state(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert at.title[0].value == ":material/search: Fuzzy Match"
    assert any(c.value == ":material/upload_file: No file uploaded yet. - Upload an .xlsx or .csv above "
               "to compare two of its columns." for c in at.caption)


def test_uploaded_file_shows_column_pickers_in_an_icon_titled_card(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    csv_bytes = pd.DataFrame([{"Job Title": "CTO", "LinkedIn Job Title": "Chief Technology Officer"}]).to_csv(
        index=False).encode("utf-8")
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.get("file_uploader")[0].set_value(("titles.csv", csv_bytes, "text/csv")).run()
    assert not at.exception
    assert ":material/compare_arrows: Compare columns" in [s.value for s in at.subheader]
    assert not any("No file uploaded yet" in c.value for c in at.caption)

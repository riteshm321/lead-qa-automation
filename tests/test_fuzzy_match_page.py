import os

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

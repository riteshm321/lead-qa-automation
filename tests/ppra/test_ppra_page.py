import os
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from core.app_settings import save_jira_settings
from ppra import _decks as d

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "pages",
                          "10_PPRA_Reports.py")
_KEY = "TM-10001"
_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

TICKET = {
    "key": _KEY, "summary": "PPR - Client X", "client_name": "Client X", "report_format": "Redesigned CS Format",
    "products": ["Content Syndication"], "flight_start": "2026-08-04", "flight_end": "2026-10-01",
    "reporter": {"accountId": "acc-123", "displayName": "Sam Reporter"},
    "owner_name": "Pat Lee", "owner_title": "CXM", "owner_email": "plee@madisonlogic.com", "attachments": [],
}


def test_warns_when_jira_is_not_set_up(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=30)
    at.run()
    assert not at.exception
    assert any("Jira account" in w.value for w in at.warning)
    assert at.button(key="ppra_fetch_button").disabled


def test_ticket_to_post_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_jira_settings("https://example.atlassian.net", "me@x.com", "tok")
    deck_bytes = d.to_bytes(d.cs_deck())

    with patch("core.jira_client.fetch_ppra_ticket", return_value=TICKET) as fetch, \
            patch("core.jira_client.post_ppra_deck") as post:
        at = AppTest.from_file(_PAGE_PATH, default_timeout=60)
        at.run()
        at.text_input(key="ppra_ticket_input").set_value(f"https://example.atlassian.net/browse/{_KEY}").run()
        at.button(key="ppra_fetch_button").click().run()
        assert fetch.call_args.args[3] == _KEY
        assert any(_KEY in m.value for m in at.markdown)

        at.get("file_uploader")[0].set_value(("raw.pptx", deck_bytes, _PPTX_MIME)).run()
        assert at.selectbox(key=f"ppra_report_type_{_KEY}").value == "CS"

        at.button(key=f"ppra_scan_button_{_KEY}").click().run()
        assert not at.exception
        assert at.toggle(key=f"ppra_rule_{_KEY}_R1").value is True
        assert at.toggle(key=f"ppra_rule_{_KEY}_R9").value is False

        at.button(key=f"ppra_format_button_{_KEY}").click().run()
        assert not at.exception
        assert at.button(key=f"ppra_post_button_{_KEY}").disabled  # not downloaded yet

        at.session_state["ppra_tickets"][_KEY]["downloaded"] = True
        at.run()
        assert not at.button(key=f"ppra_post_button_{_KEY}").disabled
        at.button(key=f"ppra_post_button_{_KEY}").click().run()

    assert not at.exception
    post.assert_called_once()
    args = post.call_args.args
    assert args[3] == _KEY and args[5:] == ("acc-123", "Sam Reporter")
    assert args[4][:2] == b"PK"
    assert any("Posted" in s.value for s in at.success)

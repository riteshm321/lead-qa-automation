from unittest.mock import MagicMock, call, patch

import pytest

from core.jira_client import (
    JiraError, build_ppra_comment_body, download_attachment, fetch_ppra_ticket, get_issue, post_ppra_deck,
    ppra_comment_preview,
)

BASE = "https://example.atlassian.net"

ISSUE = {
    "key": "TM-10001",
    "fields": {
        "summary": "PPR - Client X - Q3",
        "reporter": {"accountId": "acc-123", "displayName": "Sam Reporter"},
        "customfield_12032": "Client X",
        "customfield_12167": {"value": "Redesigned CS Format", "id": "1"},
        "customfield_12035": [{"value": "Content Syndication"}, {"value": "Display"}],
        "customfield_12028": "2026-08-04",
        "customfield_12029": "2026-10-01",
        "customfield_12051": "Pat Lee",
        "customfield_12052": "CXM",
        "customfield_12053": "plee@madisonlogic.com",
        "attachment": [
            {"id": "101", "filename": "TM-10001 - Original.pptx", "size": 2048,
             "content": f"{BASE}/rest/api/3/attachment/content/101"},
            {"id": "102", "filename": "notes.xlsx", "size": 10, "content": f"{BASE}/x"},
        ],
    },
}


def test_fetch_ppra_ticket_flattens_the_fields():
    response = MagicMock(status_code=200)
    response.json.return_value = ISSUE
    with patch("core.jira_client.requests.get", return_value=response) as mock_get:
        ticket = fetch_ppra_ticket(BASE + "/", "me@x.com", "tok", "TM-10001")

    args, kwargs = mock_get.call_args
    assert args[0] == f"{BASE}/rest/api/3/issue/TM-10001"
    assert kwargs["auth"] == ("me@x.com", "tok")
    assert "customfield_12167" in kwargs["params"]["fields"]
    assert ticket["summary"] == "PPR - Client X - Q3"
    assert ticket["client_name"] == "Client X"
    assert ticket["report_format"] == "Redesigned CS Format"
    assert ticket["products"] == ["Content Syndication", "Display"]
    assert (ticket["flight_start"], ticket["flight_end"]) == ("2026-08-04", "2026-10-01")
    assert ticket["reporter"] == {"accountId": "acc-123", "displayName": "Sam Reporter"}
    assert (ticket["owner_name"], ticket["owner_title"], ticket["owner_email"]) == (
        "Pat Lee", "CXM", "plee@madisonlogic.com")
    assert ticket["attachments"] == [{"id": "101", "filename": "TM-10001 - Original.pptx", "size": 2048,
                                      "content_url": f"{BASE}/rest/api/3/attachment/content/101"}]


def test_fetch_ppra_ticket_tolerates_missing_fields():
    response = MagicMock(status_code=200)
    response.json.return_value = {"fields": {"summary": "x", "customfield_12035": None}}
    with patch("core.jira_client.requests.get", return_value=response):
        ticket = fetch_ppra_ticket(BASE, "me@x.com", "tok", "TM-1")
    assert ticket["products"] == [] and ticket["attachments"] == [] and ticket["owner_email"] == ""


def test_get_issue_raises_on_error():
    with patch("core.jira_client.requests.get", return_value=MagicMock(status_code=404, text="nope")):
        with pytest.raises(JiraError, match="404"):
            get_issue(BASE, "me@x.com", "tok", "TM-1")


def test_download_attachment_returns_bytes():
    with patch("core.jira_client.requests.get", return_value=MagicMock(status_code=200, content=b"PK")) as mock_get:
        assert download_attachment("me@x.com", "tok", f"{BASE}/a/1") == b"PK"
    assert mock_get.call_args.kwargs["allow_redirects"] is True


def test_comment_body_mentions_the_reporter():
    body = build_ppra_comment_body("acc-123", "Sam Reporter")
    first = body["content"][0]["content"]
    assert first[0] == {"type": "text", "text": "Hi "}
    assert first[1] == {"type": "mention", "attrs": {"id": "acc-123", "text": "@Sam Reporter"}}
    texts = [p["content"][0]["text"] for p in body["content"][1:]]
    assert texts == ["PFA PPR for your reference. Let me know if you require any changes.", "Thanks"]
    assert ppra_comment_preview("Sam Reporter").splitlines()[0] == "Hi @Sam Reporter"


def test_post_ppra_deck_uploads_then_comments():
    with patch("core.jira_client.upload_attachment") as upload, patch("core.jira_client.post_comment_body") as post:
        manager = MagicMock()
        manager.attach_mock(upload, "upload")
        manager.attach_mock(post, "post")
        post_ppra_deck(BASE, "me@x.com", "tok", "TM-10001", b"deck", "acc-123", "Sam Reporter")
    assert manager.mock_calls[0] == call.upload(BASE, "me@x.com", "tok", "TM-10001", "TM-10001.pptx", b"deck")
    assert manager.mock_calls[1][0] == "post"
    assert manager.mock_calls[1].args[4]["content"][0]["content"][1]["type"] == "mention"

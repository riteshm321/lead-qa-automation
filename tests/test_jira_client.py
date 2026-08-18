from unittest.mock import patch, MagicMock

import pytest

from core.jira_client import post_comment, JiraError, _text_to_adf, extract_ticket_key


def test_text_to_adf_one_paragraph_per_line():
    doc = _text_to_adf("Line one\nLine two")
    assert doc["type"] == "doc"
    assert len(doc["content"]) == 2
    assert doc["content"][0]["content"][0]["text"] == "Line one"
    assert doc["content"][1]["content"][0]["text"] == "Line two"


def test_text_to_adf_handles_blank_lines():
    doc = _text_to_adf("Line one\n\nLine three")
    assert len(doc["content"]) == 3
    assert doc["content"][1]["content"] == []


def test_post_comment_calls_expected_url_and_auth():
    mock_response = MagicMock(status_code=201, text="")
    with patch("core.jira_client.requests.post", return_value=mock_response) as mock_post:
        post_comment("https://example.atlassian.net", "me@example.com", "token123", "PROJ-1", "hello")

    args, kwargs = mock_post.call_args
    assert args[0] == "https://example.atlassian.net/rest/api/3/issue/PROJ-1/comment"
    assert kwargs["auth"] == ("me@example.com", "token123")
    assert kwargs["json"]["body"]["type"] == "doc"


def test_post_comment_strips_trailing_slash_from_base_url():
    mock_response = MagicMock(status_code=200, text="")
    with patch("core.jira_client.requests.post", return_value=mock_response) as mock_post:
        post_comment("https://example.atlassian.net/", "me@example.com", "token123", "PROJ-1", "hello")

    assert mock_post.call_args[0][0] == "https://example.atlassian.net/rest/api/3/issue/PROJ-1/comment"


def test_post_comment_raises_jira_error_on_non_2xx():
    mock_response = MagicMock(status_code=401, text="Unauthorized")
    with patch("core.jira_client.requests.post", return_value=mock_response):
        with pytest.raises(JiraError) as exc_info:
            post_comment("https://example.atlassian.net", "me@example.com", "bad-token", "PROJ-1", "hello")

    assert "401" in str(exc_info.value)
    assert "PROJ-1" in str(exc_info.value)


def test_extract_ticket_key_passes_through_a_bare_key():
    assert extract_ticket_key("PROJ-1234") == "PROJ-1234"


def test_extract_ticket_key_lowercase_key_gets_uppercased():
    assert extract_ticket_key("proj-1234") == "PROJ-1234"


def test_extract_ticket_key_from_browse_url():
    assert extract_ticket_key("https://yourteam.atlassian.net/browse/PROJ-1234") == "PROJ-1234"


def test_extract_ticket_key_from_url_with_trailing_query_string():
    assert extract_ticket_key("https://yourteam.atlassian.net/browse/PROJ-1234?filter=1") == "PROJ-1234"


def test_extract_ticket_key_strips_surrounding_whitespace():
    assert extract_ticket_key("  PROJ-1234  ") == "PROJ-1234"


def test_extract_ticket_key_falls_back_to_input_when_unrecognized():
    assert extract_ticket_key("not a ticket") == "not a ticket"

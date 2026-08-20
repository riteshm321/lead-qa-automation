from unittest.mock import patch, MagicMock

import pytest

from core.jira_client import (
    post_comment, post_comment_body, JiraError, _text_to_adf, extract_ticket_key,
    build_comment_body, path_to_link_href,
)


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


def test_path_to_link_href_produces_a_file_uri(tmp_path):
    f = tmp_path / "report.xlsx"
    f.write_text("x")
    href = path_to_link_href(str(f))
    assert href.startswith("file:///")
    assert "report.xlsx" in href


def test_path_to_link_href_falls_back_to_plain_path_on_relative_path():
    # Path.resolve() shouldn't raise for a relative path (it resolves
    # against cwd), but as_uri() requires an absolute path — cover the
    # defensive fallback regardless of exactly which step could fail.
    with patch("core.jira_client.Path") as mock_path_cls:
        mock_path_cls.side_effect = ValueError("boom")
        assert path_to_link_href("some/relative/path.xlsx") == "some/relative/path.xlsx"


def test_build_comment_body_basic_structure():
    doc = build_comment_body(opening_text="Hi there", closing_text="Thanks")
    assert doc["type"] == "doc"
    texts = [n["content"][0]["text"] for n in doc["content"] if n["type"] == "paragraph" and n["content"]]
    assert texts == ["Hi there", "Thanks"]


def test_build_comment_body_includes_file_links_as_ordered_list_with_link_marks():
    doc = build_comment_body(
        opening_text="Hi",
        file_links=[("Accumulated File", "file:///C:/acc.xlsx"), ("Lead Report", "file:///C:/lead.xlsx")],
    )
    list_nodes = [n for n in doc["content"] if n["type"] == "orderedList"]
    assert len(list_nodes) == 1
    items = list_nodes[0]["content"]
    assert len(items) == 2
    first_text_node = items[0]["content"][0]["content"][0]
    assert first_text_node["text"] == "Accumulated File"
    assert first_text_node["marks"][0]["attrs"]["href"] == "file:///C:/acc.xlsx"


def test_build_comment_body_includes_native_table():
    doc = build_comment_body(
        opening_text="Hi",
        table_headers=["CID", "Campaign"],
        table_rows=[["118118", "APAC Q3"], ["118119", "EMEA Q3"]],
    )
    table_nodes = [n for n in doc["content"] if n["type"] == "table"]
    assert len(table_nodes) == 1
    rows = table_nodes[0]["content"]
    assert len(rows) == 3  # header + 2 data rows
    assert rows[0]["content"][0]["type"] == "tableHeader"
    assert rows[1]["content"][0]["content"][0]["content"][0]["text"] == "118118"


def test_build_comment_body_table_uses_full_width_layout_with_bold_headers():
    # Regression test: the Pacing Overview table (7+ columns, growing by one
    # every time a new date column is added) was posted with ADF's narrow
    # "default" table layout, squeezing every column so tight that almost
    # every cell wrapped word-by-word — unreadable compared to the source
    # spreadsheet. "full-width" uses the whole comment pane instead.
    doc = build_comment_body(
        opening_text="Hi",
        table_headers=["CID", "Campaign"],
        table_rows=[["118118", "APAC Q3"]],
    )
    table_node = next(n for n in doc["content"] if n["type"] == "table")
    assert table_node["attrs"]["layout"] == "full-width"

    header_row = table_node["content"][0]
    header_text_node = header_row["content"][0]["content"][0]["content"][0]
    assert header_text_node["text"] == "CID"
    assert {"type": "strong"} in header_text_node["marks"]


def test_build_comment_body_table_gives_wider_columns_more_colwidth():
    # Regression test: every column got the same implicit width regardless
    # of content, so a long free-text column ("Campaign Segment") wrapped
    # word-by-word while short numeric columns ("CID") sat mostly empty —
    # looked misaligned/ugly compared to the source spreadsheet even after
    # switching to full-width layout. Widths must scale with actual content.
    doc = build_comment_body(
        opening_text="Hi",
        table_headers=["CID", "Campaign Segment"],
        table_rows=[["118118", "INT_ABM Leads_Arkance ADSK_AECO_Snr Mgr+_Jul-Aug'26"]],
    )
    table_node = next(n for n in doc["content"] if n["type"] == "table")
    header_cells = table_node["content"][0]["content"]
    cid_width = header_cells[0]["attrs"]["colwidth"][0]
    campaign_width = header_cells[1]["attrs"]["colwidth"][0]
    assert campaign_width > cid_width


def test_build_comment_body_omits_table_when_rows_not_provided():
    doc = build_comment_body(opening_text="Hi", table_headers=["CID"])
    assert not any(n["type"] == "table" for n in doc["content"])


def test_build_comment_body_orders_opening_links_table_closing():
    doc = build_comment_body(
        opening_text="Open",
        closing_text="Close",
        file_links=[("A", "file:///a")],
        table_headers=["H"],
        table_rows=[["v"]],
    )
    types_in_order = [n["type"] for n in doc["content"]]
    assert types_in_order == ["paragraph", "orderedList", "table", "paragraph"]


def test_post_comment_body_sends_prebuilt_adf_unmodified():
    mock_response = MagicMock(status_code=201, text="")
    adf = {"type": "doc", "version": 1, "content": []}
    with patch("core.jira_client.requests.post", return_value=mock_response) as mock_post:
        post_comment_body("https://example.atlassian.net", "me@example.com", "token123", "PROJ-1", adf)

    assert mock_post.call_args[1]["json"]["body"] is adf

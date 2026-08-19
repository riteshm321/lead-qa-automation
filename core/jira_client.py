import re
from pathlib import Path

import requests


class JiraError(Exception):
    """A Jira API call failed — the response text is included for context."""


_TICKET_KEY_RE = re.compile(r"([A-Z][A-Z0-9]+-\d+)")


def extract_ticket_key(value: str) -> str:
    """Accepts either a bare Jira ticket key ("PROJ-1234") or a full ticket
    URL ("https://yourteam.atlassian.net/browse/PROJ-1234") and returns
    just the key — the comment API only accepts the key, but a link is
    usually what's actually on hand, copied straight from the browser's
    address bar while looking at the ticket.
    """
    value = value.strip()
    match = _TICKET_KEY_RE.search(value.upper())
    return match.group(1) if match else value


def path_to_link_href(path: str) -> str:
    """Best-effort file:// URI for a local/OneDrive-synced path, so a
    linked file name is actually clickable. Only opens correctly on a
    machine where this exact path exists (e.g. the poster's own machine,
    or a teammate syncing the identical OneDrive folder structure) — falls
    back to the plain path text if it can't be turned into a URI at all
    (e.g. a relative path).
    """
    try:
        return Path(path).resolve().as_uri()
    except (ValueError, OSError):
        return path


def _text_to_paragraphs(text: str) -> list[dict]:
    paragraphs = []
    for line in text.split("\n"):
        content = [{"type": "text", "text": line}] if line else []
        paragraphs.append({"type": "paragraph", "content": content})
    return paragraphs


def _text_to_adf(text: str) -> dict:
    return {"type": "doc", "version": 1, "content": _text_to_paragraphs(text)}


def _links_to_adf_list(links: list[tuple[str, str]]) -> dict:
    # links: [(label, href), ...] -> a numbered list of clickable labels,
    # matching "1. Accumulated File" / "2. Lead Report" style.
    items = [
        {
            "type": "listItem",
            "content": [{
                "type": "paragraph",
                "content": [{"type": "text", "text": label, "marks": [{"type": "link", "attrs": {"href": href}}]}],
            }],
        }
        for label, href in links
    ]
    return {"type": "orderedList", "attrs": {"order": 1}, "content": items}


def _table_to_adf(headers: list[str], rows: list[list]) -> dict:
    def _cell(value, is_header: bool) -> dict:
        text = "" if value is None else str(value)
        marks = [{"type": "strong"}] if is_header and text else []
        content = [{"type": "text", "text": text, "marks": marks}] if text else []
        paragraph = {"type": "paragraph", "content": content}
        return {"type": "tableHeader" if is_header else "tableCell", "attrs": {}, "content": [paragraph]}

    header_row = {"type": "tableRow", "content": [_cell(h, True) for h in headers]}
    data_rows = [{"type": "tableRow", "content": [_cell(v, False) for v in row]} for row in rows]
    return {
        "type": "table",
        # "full-width" uses the whole comment pane width instead of ADF's
        # narrower "default" layout — with a wide Pacing Overview table
        # (7+ columns, growing by one every time a new date is added),
        # "default" squeezed every column so tight that nearly every cell
        # wrapped word-by-word, which is what made the posted table
        # unreadable compared to the source spreadsheet.
        "attrs": {"isNumberColumnEnabled": False, "layout": "full-width"},
        "content": [header_row] + data_rows,
    }


def build_comment_body(
    opening_text: str,
    closing_text: str = "",
    file_links: list[tuple[str, str]] | None = None,
    table_headers: list[str] | None = None,
    table_rows: list[list] | None = None,
) -> dict:
    """Build the full ADF comment: opening text, then an optional numbered
    list of file links, then an optional native table, then closing text —
    matching "greeting/summary sentence -> file links -> sign-off" while
    keeping the links and table as real Jira structures, not plain text.
    """
    content = list(_text_to_paragraphs(opening_text))
    if file_links:
        content.append(_links_to_adf_list(file_links))
    if table_headers and table_rows is not None:
        content.append(_table_to_adf(table_headers, table_rows))
    if closing_text:
        content.extend(_text_to_paragraphs(closing_text))
    return {"type": "doc", "version": 1, "content": content}


def _post(base_url: str, email: str, api_token: str, ticket_key: str, adf_body: dict) -> None:
    url = f"{base_url.rstrip('/')}/rest/api/3/issue/{ticket_key}/comment"
    response = requests.post(
        url,
        json={"body": adf_body},
        auth=(email, api_token),
        headers={"Accept": "application/json"},
        timeout=15,
    )
    if response.status_code not in (200, 201):
        raise JiraError(f"Jira returned {response.status_code} for {ticket_key}: {response.text[:300]}")


def post_comment(base_url: str, email: str, api_token: str, ticket_key: str, comment_text: str) -> None:
    """Post plain comment_text as a new comment on a Jira Cloud issue.

    Authenticates as the given email/API token (Jira Cloud Basic Auth), so
    the comment is attributed to that person's own account.
    """
    _post(base_url, email, api_token, ticket_key, _text_to_adf(comment_text))


def post_comment_body(base_url: str, email: str, api_token: str, ticket_key: str, adf_body: dict) -> None:
    """Post a pre-built ADF document (see build_comment_body) as a new
    comment on a Jira Cloud issue."""
    _post(base_url, email, api_token, ticket_key, adf_body)

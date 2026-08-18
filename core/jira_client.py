import re

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


def _text_to_adf(text: str) -> dict:
    # Jira Cloud's v3 comment API requires the body in Atlassian Document
    # Format, not plain text — one paragraph node per line so line breaks
    # in the summary render as line breaks in the posted comment.
    paragraphs = []
    for line in text.split("\n"):
        content = [{"type": "text", "text": line}] if line else []
        paragraphs.append({"type": "paragraph", "content": content})
    return {"type": "doc", "version": 1, "content": paragraphs}


def post_comment(base_url: str, email: str, api_token: str, ticket_key: str, comment_text: str) -> None:
    """Post comment_text as a new comment on a Jira Cloud issue.

    Authenticates as the given email/API token (Jira Cloud Basic Auth), so
    the comment is attributed to that person's own account.
    """
    url = f"{base_url.rstrip('/')}/rest/api/3/issue/{ticket_key}/comment"
    response = requests.post(
        url,
        json={"body": _text_to_adf(comment_text)},
        auth=(email, api_token),
        headers={"Accept": "application/json"},
        timeout=15,
    )
    if response.status_code not in (200, 201):
        raise JiraError(f"Jira returned {response.status_code} for {ticket_key}: {response.text[:300]}")

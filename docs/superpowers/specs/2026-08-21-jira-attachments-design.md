# Jira Attachments (File + Pasted Screenshot) Design

## Goal

Let the user attach a single arbitrary file and/or a single pasted screenshot
(e.g. of the Pacing Overview table) to the Jira ticket comment posted from the
"Post to Jira" section of `pages/2_Run_Check.py`, in addition to the existing
`file://` links and native Pacing Overview table.

## Scope

- **In scope:** one general file attachment (any type), one pasted-screenshot
  attachment, both uploaded via Jira's REST attachments endpoint, both
  triggered by the existing "Post summary to {ticket}" button.
- **Out of scope:** the existing Accumulated File / Lead Report links stay as
  `file://` links only — they are not also uploaded as attachments (explicit
  user decision). Multiple files/screenshots per post is out of scope — one
  of each, replace-by-re-uploading/re-pasting.
- **Out of scope:** embedding the pasted screenshot inline inside the ADF
  comment body (via Jira's media API). It becomes a ticket attachment,
  visible in the ticket's Attachments panel, not inline in the comment text.

## Architecture

Two new inputs render on the existing "Post to Jira" section, alongside the
existing opening/closing message boxes and file-link checkboxes:

1. **General file attachment** — a plain `st.file_uploader` (same widget
   already used elsewhere in this app for New Leads/Purchased Report),
   accepting any single file.
2. **Paste-a-screenshot box** — a small custom Streamlit component that
   listens for a clipboard paste (Ctrl+V) and returns the pasted image's
   bytes to Python.

Both are optional. Clicking "Post summary to {ticket}" does, in order:

1. Post the Jira comment exactly as today (`jira_client.post_comment_body`).
2. For each attachment actually provided (0, 1, or 2 of: general file,
   pasted screenshot), call a new `jira_client.upload_attachment(...)`
   independently. A failure on one does not block the other, and does not
   roll back the already-posted comment — the comment is the primary
   content and always goes through if step 1 succeeded.
3. Report results: `st.success` for the comment post, plus one `st.error`
   per attachment that failed to upload, naming which attachment and why.
4. On a fully successful post (comment + every provided attachment), clear
   the pending-summary/attachment state, same as today's clear-after-post
   behavior, so the next run starts fresh.

## Paste-screenshot component

Implemented as a genuine Streamlit custom component via
`streamlit.components.v1.declare_component`, using Streamlit's official,
documented bidirectional component protocol — not a hand-rolled
`postMessage` hack against undocumented internals. This choice was made
explicitly to avoid two risks flagged during design: (a) adding a
third-party pip package whose bundled frontend assets would need separate
verification under this app's PyInstaller onedir packaging, and (b) relying
on internal Streamlit message formats that could silently break on a future
Streamlit version bump.

- **Frontend:** one small static HTML/JS file vendored into the repo at
  `core/static/paste_component/index.html` (no npm build step, no CDN
  fetch at runtime — the official Streamlit component bridge script,
  `streamlit-component-lib.js`, is vendored as a static file alongside it,
  downloaded once and committed, so the whole component works fully
  offline). It renders a bordered box with placeholder text ("Click here,
  then Ctrl+V to paste a screenshot"), listens for the browser's `paste`
  event, reads `event.clipboardData.items` for an image, converts it to a
  base64 data URL via `FileReader`, and calls `Streamlit.setComponentValue(...)`
  to send that string back to Python.
- **Backend wrapper:** `core/paste_component.py` exposes
  `paste_screenshot(key: str) -> str | None`, wrapping
  `declare_component("paste_screenshot", path=".../paste_component")` and
  returning the base64 data URL (or `None` if nothing has been pasted yet).
- **UI behavior:** once a value is returned, `pages/2_Run_Check.py` decodes
  it, shows an inline preview via `st.image`, and offers a "Clear
  screenshot" button (clears the relevant `st.session_state` key) so the
  user can confirm what will be attached, or replace it by pasting again.
- **Filename:** fixed, auto-generated — `Pacing_Overview_Screenshot.png` —
  since only one screenshot is supported per post.

## Jira attachment upload (`core/jira_client.py`)

New function, following the existing `_post` helper's conventions:

```python
def upload_attachment(
    base_url: str, email: str, api_token: str, ticket_key: str,
    filename: str, file_bytes: bytes,
) -> None:
    """Uploads file_bytes as a named attachment on a Jira Cloud issue.

    Jira's attachments endpoint requires the X-Atlassian-Token: no-check
    header (its CSRF check otherwise rejects the multipart request) and a
    different content type than the JSON comment endpoints use.
    """
    url = f"{base_url.rstrip('/')}/rest/api/3/issue/{ticket_key}/attachments"
    response = requests.post(
        url,
        files={"file": (filename, file_bytes)},
        auth=(email, api_token),
        headers={"X-Atlassian-Token": "no-check", "Accept": "application/json"},
        timeout=30,
    )
    if response.status_code not in (200, 201):
        raise JiraError(f"Jira returned {response.status_code} for {ticket_key}: {response.text[:300]}")
```

## UI wiring (`pages/2_Run_Check.py`)

- New widgets render just above the "Post summary to {ticket}" button:
  - `st.file_uploader("Attach a file (optional)", key="jira_attachment_file")`
  - The paste-screenshot component + preview/clear button described above.
- On button click, after the existing `post_comment_body` call succeeds:
  ```python
  attachment_errors = []
  uploaded_file = st.session_state.get("jira_attachment_file")
  if uploaded_file is not None:
      try:
          jira_client.upload_attachment(
              jira_settings["base_url"], jira_settings["email"], jira_settings["api_token"],
              _pending_summary["ticket_key"], uploaded_file.name, uploaded_file.getvalue(),
          )
      except JiraError as e:
          attachment_errors.append((uploaded_file.name, str(e)))

  screenshot_bytes = st.session_state.get("jira_pasted_screenshot_bytes")
  if screenshot_bytes is not None:
      try:
          jira_client.upload_attachment(
              jira_settings["base_url"], jira_settings["email"], jira_settings["api_token"],
              _pending_summary["ticket_key"], "Pacing_Overview_Screenshot.png", screenshot_bytes,
          )
      except JiraError as e:
          attachment_errors.append(("Pacing_Overview_Screenshot.png", str(e)))

  st.success(f"Posted to {_pending_summary['ticket_key']}.")
  for name, error in attachment_errors:
      st.error(f"Attachment \"{name}\" failed to upload: {error}")
  if not attachment_errors:
      del st.session_state["last_finalized_summary"]
      # also clear jira_attachment_file / jira_pasted_screenshot_bytes state
  ```
  Session state is only fully cleared when there were zero attachment
  errors, matching the "report failures loudly, don't silently lose work"
  decision. If an attachment failed, `last_finalized_summary` is kept (so
  the comment-related UI stays as-is) but the main button's label switches
  to `"🔁 Retry failed attachment(s) for {ticket}"` and its click handler
  only re-runs the attachment-upload loop above — it does not call
  `post_comment_body` again, so retrying never posts a duplicate comment.
  Only attachments that failed the first time are retried; one that already
  succeeded is not re-uploaded.

## Testing

- `core/jira_client.py`: unit tests for `upload_attachment` mocking
  `requests.post`, covering: correct URL/headers/multipart body, success on
  200/201, `JiraError` raised with ticket key and response text on other
  statuses — mirroring the existing `test_post_comment_*` tests.
- `core/paste_component.py`: a thin wrapper around `declare_component`;
  the component's JS itself is not unit-testable under `pytest`, so testing
  is limited to confirming the module imports and the wrapper function
  signature/behavior when component value is `None` (nothing pasted yet).
  Manual verification of actual clipboard paste happens in the browser.
- `pages/2_Run_Check.py`: `AppTest`-based tests confirming the attach/paste
  widgets render, and that `upload_attachment` is called (mocked) with the
  right arguments when a file is present, and that a mocked `JiraError` on
  one attachment surfaces as `st.error` without blocking the comment
  success message. Real file uploads/paste interactions can't be driven by
  `AppTest` (established limitation from earlier work on this app) — those
  code paths are covered by pre-seeding `session_state` with the relevant
  bytes, matching the existing pattern used for other file-upload flows in
  this test suite.

## Open risk, flagged for visibility

Jira Cloud enforces a per-site attachment size limit (commonly 10MB by
default, admin-configurable). No client-side size check is planned for a
first version — an oversized file simply surfaces as a `JiraError` from the
non-2xx response, reported the same as any other attachment failure. If
this proves to be a common real-world failure, a client-side size warning
before upload can be added later.

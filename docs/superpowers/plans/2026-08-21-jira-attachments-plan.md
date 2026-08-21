# Jira Attachments (File + Pasted Screenshot) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (inline execution, single session — chosen because the user asked for immediate implementation and the feature is small). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user attach one general file and/or one pasted screenshot to the Jira ticket comment posted from "Post to Jira" in `pages/2_Run_Check.py`.

**Architecture:** A new `jira_client.upload_attachment()` posts multipart/form-data to Jira's `/attachments` REST endpoint. A new custom Streamlit component (`core/paste_component.py` + a vendored static `index.html`) implements Streamlit's documented iframe messaging contract directly (no third-party package, no CDN fetch) to capture a Ctrl+V-pasted image and return its bytes to Python. `pages/2_Run_Check.py` wires both into the existing "Post summary to {ticket}" button, uploading whatever was provided after the comment posts, reporting per-attachment failures without blocking the comment or each other.

**Tech Stack:** Python, Streamlit (`streamlit.components.v1.declare_component`), `requests`, `pytest` + `streamlit.testing.v1.AppTest`.

## Global Constraints

- No new pip dependency (per spec: avoids PyInstaller packaging risk for third-party component frontend assets).
- One file + one screenshot per post — no multi-attach.
- A failed attachment upload must not block the comment post, and must not block the other attachment.
- The static component directory must be added to `LeadQAAutomation.spec`'s `datas` list so the packaged exe includes it (the `.spec` file is gitignored/local-only per this project's existing convention — edit it locally, it is not committed).
- Fixed screenshot filename: `Pacing_Overview_Screenshot.png`.
- Retrying a failed attachment must never re-post the Jira comment.

---

### Task 1: `jira_client.upload_attachment`

**Files:**
- Modify: `core/jira_client.py`
- Test: `tests/test_jira_client.py`

**Interfaces:**
- Produces: `upload_attachment(base_url: str, email: str, api_token: str, ticket_key: str, filename: str, file_bytes: bytes) -> None`, raising `JiraError` (already defined in this file) on a non-2xx response — same convention as the existing `_post()` helper in this file.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_jira_client.py`, right after `test_post_comment_body_sends_prebuilt_adf_unmodified`:

```python
def test_upload_attachment_posts_multipart_with_required_header():
    mock_response = MagicMock(status_code=200, text="")
    with patch("core.jira_client.requests.post", return_value=mock_response) as mock_post:
        upload_attachment(
            "https://example.atlassian.net", "me@example.com", "token123",
            "PROJ-1", "screenshot.png", b"fake-image-bytes",
        )

    args, kwargs = mock_post.call_args
    assert args[0] == "https://example.atlassian.net/rest/api/3/issue/PROJ-1/attachments"
    assert kwargs["auth"] == ("me@example.com", "token123")
    assert kwargs["headers"]["X-Atlassian-Token"] == "no-check"
    assert kwargs["files"]["file"] == ("screenshot.png", b"fake-image-bytes")


def test_upload_attachment_strips_trailing_slash_from_base_url():
    mock_response = MagicMock(status_code=201, text="")
    with patch("core.jira_client.requests.post", return_value=mock_response) as mock_post:
        upload_attachment(
            "https://example.atlassian.net/", "me@example.com", "token123",
            "PROJ-1", "f.txt", b"data",
        )

    assert mock_post.call_args[0][0] == "https://example.atlassian.net/rest/api/3/issue/PROJ-1/attachments"


def test_upload_attachment_raises_jira_error_on_non_2xx():
    mock_response = MagicMock(status_code=413, text="Attachment too large")
    with patch("core.jira_client.requests.post", return_value=mock_response):
        with pytest.raises(JiraError) as exc_info:
            upload_attachment(
                "https://example.atlassian.net", "me@example.com", "token123",
                "PROJ-1", "big.png", b"data",
            )

    assert "413" in str(exc_info.value)
    assert "PROJ-1" in str(exc_info.value)
```

Update the import line at the top of `tests/test_jira_client.py` to add `upload_attachment`:

```python
from core.jira_client import (
    post_comment, post_comment_body, JiraError, _text_to_adf, extract_ticket_key,
    build_comment_body, path_to_link_href, upload_attachment,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_jira_client.py -k upload_attachment -v`
Expected: FAIL with `ImportError: cannot import name 'upload_attachment'`

- [ ] **Step 3: Implement `upload_attachment`**

Add to `core/jira_client.py`, right after the `_post` function:

```python
def upload_attachment(
    base_url: str, email: str, api_token: str, ticket_key: str,
    filename: str, file_bytes: bytes,
) -> None:
    """Uploads file_bytes as a named attachment on a Jira Cloud issue.

    A separate endpoint from the comment APIs above — Jira requires the
    X-Atlassian-Token: no-check header here (its CSRF check otherwise
    rejects the multipart request) and no JSON Content-Type, since requests
    sets the multipart boundary itself from the `files` argument.
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_jira_client.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/jira_client.py tests/test_jira_client.py
git commit -m "Add Jira attachment upload support to jira_client"
```

---

### Task 2: Paste-screenshot custom component

**Files:**
- Create: `core/static/paste_component/index.html`
- Create: `core/paste_component.py`
- Test: `tests/test_paste_component.py`
- Modify (local only, not committed — `.spec` is gitignored): `LeadQAAutomation.spec`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `paste_screenshot(key: str) -> str | None` in `core/paste_component.py` — returns a base64 data URL string (e.g. `"data:image/png;base64,iVBOR..."`) once the user has pasted an image, or `None` before that.

- [ ] **Step 1: Write the frontend**

Create `core/static/paste_component/index.html`:

```html
<!DOCTYPE html>
<html>
<head>
<style>
  body { margin: 0; font-family: sans-serif; }
  #box {
    box-sizing: border-box;
    width: 100%;
    min-height: 60px;
    border: 2px dashed #999;
    border-radius: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #666;
    font-size: 14px;
    padding: 12px;
    cursor: text;
    outline: none;
  }
  #box:focus { border-color: #4a90d9; color: #333; }
</style>
</head>
<body>
<div id="box" tabindex="0">Click here, then press Ctrl+V to paste a screenshot</div>
<script>
  // Streamlit's documented custom-component iframe protocol (no npm
  // package, no CDN fetch): the frontend announces readiness, may report
  // its own height, and sends a value back to Python via postMessage.
  // See https://docs.streamlit.io/library/components/components-api
  function sendReady() {
    window.parent.postMessage({ type: "streamlit:componentReady", apiVersion: 1 }, "*");
  }
  function setFrameHeight() {
    window.parent.postMessage(
      { type: "streamlit:setFrameHeight", height: document.body.scrollHeight }, "*"
    );
  }
  function sendValue(value) {
    window.parent.postMessage({ type: "streamlit:setComponentValue", value: value, dataType: "json" }, "*");
  }

  const box = document.getElementById("box");
  box.addEventListener("paste", function (event) {
    const items = (event.clipboardData || window.clipboardData).items;
    for (const item of items) {
      if (item.type.indexOf("image") === 0) {
        const blob = item.getAsFile();
        const reader = new FileReader();
        reader.onload = function () {
          box.textContent = "Screenshot pasted — ready to attach.";
          setFrameHeight();
          sendValue(reader.result);
        };
        reader.readAsDataURL(blob);
        event.preventDefault();
        return;
      }
    }
  });

  sendReady();
  setFrameHeight();
</script>
</body>
</html>
```

- [ ] **Step 2: Write the failing test for the Python wrapper**

Create `tests/test_paste_component.py`:

```python
from core.paste_component import paste_screenshot


def test_paste_screenshot_returns_none_by_default(monkeypatch):
    # The component itself can't be driven headlessly (it needs a real
    # browser paste event) — this confirms the wrapper correctly forwards
    # declare_component's return value, including the "nothing pasted yet"
    # default of None.
    monkeypatch.setattr(
        "core.paste_component._paste_screenshot_component",
        lambda key=None, default=None: default,
    )
    assert paste_screenshot(key="test_key") is None


def test_paste_screenshot_returns_component_value(monkeypatch):
    monkeypatch.setattr(
        "core.paste_component._paste_screenshot_component",
        lambda key=None, default=None: "data:image/png;base64,abc123",
    )
    assert paste_screenshot(key="test_key") == "data:image/png;base64,abc123"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_paste_component.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.paste_component'`

- [ ] **Step 4: Implement the Python wrapper**

Create `core/paste_component.py`:

```python
import os

import streamlit.components.v1 as components

_COMPONENT_DIR = os.path.join(os.path.dirname(__file__), "static", "paste_component")

_paste_screenshot_component = components.declare_component("paste_screenshot", path=_COMPONENT_DIR)


def paste_screenshot(key: str) -> str | None:
    """Renders the paste-a-screenshot box and returns the pasted image as a
    base64 data URL (e.g. "data:image/png;base64,...."), or None if nothing
    has been pasted yet in this session."""
    return _paste_screenshot_component(key=key, default=None)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_paste_component.py -v`
Expected: both PASS

- [ ] **Step 6: Register the static directory with PyInstaller (local-only, not committed)**

Edit `LeadQAAutomation.spec` — change:

```python
datas = [('Summary.py', '.'), ('pages', 'pages'), ('aliases', 'aliases')]
```

to:

```python
datas = [('Summary.py', '.'), ('pages', 'pages'), ('aliases', 'aliases'),
          ('core/static', 'core/static')]
```

This file is gitignored (`.spec` in `.gitignore`), so this edit is local-machine-only and is not part of the commit in Step 7 — it must be made by hand on any other machine that builds the exe from this repo.

- [ ] **Step 7: Commit**

```bash
git add core/paste_component.py core/static/paste_component/index.html tests/test_paste_component.py
git commit -m "Add custom Streamlit component for pasting a screenshot"
```

---

### Task 3: Wire attachments into the Jira posting UI

**Files:**
- Modify: `pages/2_Run_Check.py:583-660` (the "Post to Jira" section)
- Test: `tests/test_run_check_page.py`

**Interfaces:**
- Consumes: `jira_client.upload_attachment` (Task 1), `paste_component.paste_screenshot` (Task 2).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_run_check_page.py` (find the existing Jira-posting test(s) for the surrounding pattern — reuse the same `AppTest.from_file` + pre-seeded `session_state` style already used in this file):

```python
def test_jira_post_uploads_provided_attachment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    wb = openpyxl.Workbook()
    wb.active.title = "Accumulated"
    wb.active.append(["Email", "First", "Last", "Company", "CID"])
    wb.save(acc_path)

    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(name="Test Client", accumulated_report_path=acc_path, field_mapping=fm)
    save_profile(profile, get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["last_finalized_summary"] = {
        "client_name": "Test Client", "ticket_key": "PROJ-1", "reporter_name": "Jane",
        "run_date_display": "21-08-26", "accumulated_report_path": acc_path,
        "accumulated_report_link": None, "lead_template_files": [],
    }
    at.session_state["jira_attachment_bytes"] = b"fake-file-bytes"
    at.session_state["jira_attachment_name"] = "notes.txt"
    at.run()
    assert not at.exception

    with patch("core.jira_client.post_comment_body") as mock_post_comment, \
         patch("core.jira_client.upload_attachment") as mock_upload:
        post_button = next(b for b in at.button if "Post summary to" in b.label)
        post_button.click().run()

    assert not at.exception
    mock_post_comment.assert_called_once()
    mock_upload.assert_called_once()
    assert mock_upload.call_args[0][4] == "notes.txt"
    assert mock_upload.call_args[0][5] == b"fake-file-bytes"


def test_jira_post_reports_attachment_failure_without_blocking_comment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    acc_path = str(tmp_path / "accumulated.xlsx")
    wb = openpyxl.Workbook()
    wb.active.title = "Accumulated"
    wb.active.append(["Email", "First", "Last", "Company", "CID"])
    wb.save(acc_path)

    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(name="Test Client", accumulated_report_path=acc_path, field_mapping=fm)
    save_profile(profile, get_clients_dir())

    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.session_state["last_finalized_summary"] = {
        "client_name": "Test Client", "ticket_key": "PROJ-1", "reporter_name": "Jane",
        "run_date_display": "21-08-26", "accumulated_report_path": acc_path,
        "accumulated_report_link": None, "lead_template_files": [],
    }
    at.session_state["jira_attachment_bytes"] = b"fake-file-bytes"
    at.session_state["jira_attachment_name"] = "notes.txt"
    at.run()
    assert not at.exception

    with patch("core.jira_client.post_comment_body") as mock_post_comment, \
         patch("core.jira_client.upload_attachment", side_effect=jira_client.JiraError("boom")):
        post_button = next(b for b in at.button if "Post summary to" in b.label)
        post_button.click().run()

    assert not at.exception
    mock_post_comment.assert_called_once()
    assert any("boom" in e.value for e in at.error)
    # The comment succeeded, so its success message must still show.
    assert any("Posted to PROJ-1" in s.value for s in at.success)
```

Add `from unittest.mock import patch` to the top of `tests/test_run_check_page.py` if not already imported, and confirm `jira_client` (the module, not individual functions) is already imported for the `JiraError` reference — if only individual names are imported, add `from core import jira_client` alongside the existing imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_run_check_page.py -k "jira_post_uploads or jira_post_reports" -v`
Expected: FAIL (attachment session-state keys are read but nothing uploads yet; `mock_upload.assert_called_once()` fails)

- [ ] **Step 3: Implement the UI wiring**

In `pages/2_Run_Check.py`, add the import near the other `core` imports at the top of the file:

```python
from core.paste_component import paste_screenshot
```

Replace the block from the closing-message text area through the end of the success branch (originally `st.text_area("Closing message", ...)` through `st.success(...)`) with:

```python
    st.text_area("Closing message", "Thanks", key="jira_comment_closing", height=60)

    st.caption("Optional attachments (uploaded after the comment posts):")
    _attachment_file = st.file_uploader("Attach a file", key="jira_attachment_upload")
    if _attachment_file is not None:
        st.session_state["jira_attachment_bytes"] = _attachment_file.getvalue()
        st.session_state["jira_attachment_name"] = _attachment_file.name

    st.caption("Paste a screenshot (e.g. of the Pacing Overview table):")
    _pasted_data_url = paste_screenshot(key="jira_paste_screenshot")
    if _pasted_data_url is not None:
        st.session_state["jira_pasted_screenshot"] = _pasted_data_url
    if st.session_state.get("jira_pasted_screenshot"):
        st.image(st.session_state["jira_pasted_screenshot"], width=300)
        if st.button("Clear screenshot"):
            del st.session_state["jira_pasted_screenshot"]
            st.rerun()

    _has_pending_attachment_errors = bool(st.session_state.get("jira_attachment_errors"))
    _post_label = (
        f"🔁 Retry failed attachment(s) for {_pending_summary['ticket_key']}"
        if _has_pending_attachment_errors
        else f"📋 Post summary to {_pending_summary['ticket_key']}"
    )

    if st.button(_post_label, key="jira_post_button"):
        jira_settings = get_jira_settings()
        if not all([jira_settings["base_url"], jira_settings["email"], jira_settings["api_token"]]):
            st.error("Set up your Jira account (site URL, email, API token) in Client Setup first.")
        else:
            try:
                if not _has_pending_attachment_errors:
                    adf_body = jira_client.build_comment_body(
                        opening_text=st.session_state["jira_comment_opening"],
                        closing_text=st.session_state["jira_comment_closing"],
                        file_links=_selected_links,
                        table_headers=list(_pacing_df.columns) if _include_pacing and _pacing_df is not None else None,
                        table_rows=_pacing_df.values.tolist() if _include_pacing and _pacing_df is not None else None,
                    )
                    jira_client.post_comment_body(
                        jira_settings["base_url"], jira_settings["email"], jira_settings["api_token"],
                        _pending_summary["ticket_key"], adf_body,
                    )
                    st.success(f"Posted to {_pending_summary['ticket_key']}.")

                attachment_errors = []
                _prior_errors = st.session_state.get("jira_attachment_errors", set())

                _file_bytes = st.session_state.get("jira_attachment_bytes")
                _file_name = st.session_state.get("jira_attachment_name")
                if _file_bytes is not None and (not _has_pending_attachment_errors or _file_name in _prior_errors):
                    try:
                        jira_client.upload_attachment(
                            jira_settings["base_url"], jira_settings["email"], jira_settings["api_token"],
                            _pending_summary["ticket_key"], _file_name, _file_bytes,
                        )
                    except jira_client.JiraError as e:
                        attachment_errors.append((_file_name, str(e)))

                _screenshot_data_url = st.session_state.get("jira_pasted_screenshot")
                _screenshot_name = "Pacing_Overview_Screenshot.png"
                if _screenshot_data_url is not None and (
                        not _has_pending_attachment_errors or _screenshot_name in _prior_errors):
                    try:
                        _screenshot_bytes = base64.b64decode(_screenshot_data_url.split(",", 1)[1])
                        jira_client.upload_attachment(
                            jira_settings["base_url"], jira_settings["email"], jira_settings["api_token"],
                            _pending_summary["ticket_key"], _screenshot_name, _screenshot_bytes,
                        )
                    except jira_client.JiraError as e:
                        attachment_errors.append((_screenshot_name, str(e)))

                for name, error in attachment_errors:
                    st.error(f"Attachment \"{name}\" failed to upload: {error}")

                if attachment_errors:
                    st.session_state["jira_attachment_errors"] = {name for name, _ in attachment_errors}
                else:
                    st.session_state.pop("jira_attachment_errors", None)
                    st.session_state.pop("jira_attachment_bytes", None)
                    st.session_state.pop("jira_attachment_name", None)
                    st.session_state.pop("jira_pasted_screenshot", None)
                    del st.session_state["last_finalized_summary"]
                    st.rerun()
            except jira_client.JiraError as e:
                st.error(f"Failed to post to Jira: {e}")
```

Add `import base64` to the top of `pages/2_Run_Check.py` alongside the other stdlib imports if not already present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_run_check_page.py -v`
Expected: all PASS

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q --ignore=tests/test_end_to_end_basware.py`
Expected: all PASS (pre-existing Basware fixture-file gap is a known, unrelated issue — see project history)

- [ ] **Step 6: Commit**

```bash
git add pages/2_Run_Check.py tests/test_run_check_page.py
git commit -m "Wire file/screenshot attachments into the Post to Jira flow"
```

---

### Task 4: Update README

**Files:**
- Modify: `README.md` (the Jira posting section, near the existing "Opening message"/"Pacing Overview" bullets from the prior Jira-template work)

- [ ] **Step 1: Add documentation bullets**

In the Jira posting section of `README.md`, after the existing bullet describing the opening message, add:

```markdown
- Optionally attach one general file (any type) via a file picker, and/or one
  pasted screenshot (e.g. of the Pacing Overview table) via a paste box —
  click the box, then press Ctrl+V. Both upload as real Jira attachments
  after the comment posts. A failed attachment upload is reported without
  blocking the comment or the other attachment; the button then changes to
  "Retry failed attachment(s)", which retries only what failed without
  reposting the comment.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Document the Jira file/screenshot attachment feature"
```

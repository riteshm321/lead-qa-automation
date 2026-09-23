# Integrate.com Lead Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a client's verified leadfile be uploaded straight to that
client's Integrate.com Source via API, mirroring the existing Convertr
(`pages/7_Convertr.py`) and Enhancio (`pages/8_Enhancio.py`) upload pages.

**Architecture:** A new `core/integrate_client.py` API client (one function,
`submit_lead`) + `core/integrate_sync.py` dedup helpers (modeled on
`core/enhancio_sync.py` but keyed per-client, not per-allocation), a new
`IntegrateConfig` dataclass on `ClientProfile`, a new Client Setup section
reusing the existing `_render_paired_field_mapping`/
`_render_leadfile_column_mapping` helpers, a new Settings credentials
section, and a new `pages/9_Integrate.py` upload page mirroring
`pages/7_Convertr.py`'s structure (minus reconcile/Jira-post, which are out
of scope — see the spec).

**Tech Stack:** Python, `requests`, Streamlit, `pandas`, pytest +
`streamlit.testing.v1.AppTest`.

## Global Constraints

- Endpoint: `POST https://api.integrate.com/api/v1/contracts/{SID}/leads?callback={callback URL}`,
  headers `X-API-Key`, `X-API-Key-Secret`, `Content-Type: application/vnd.api+json`.
- Request body: `{"data": {"type": "lead", "attributes": {...}}}` — the
  17 accepted attribute names are exactly: `first_name`, `last_name`,
  `email`, `phone`, `asset_title`, `company_name`, `industry`, `job_title`,
  `employee_size`, `job_level`, `job_function`, `CompanyRevenue`, `opt_in`,
  `OptInDate`, `double_optin`, `double_date_optin`, `country`.
- Success response: `{"data": {"id": "<lead-guid>", ...}}`. Error response:
  `{"errors": [{"title": "..."}]}`.
- One SID per client (not per-CID, unlike Convertr/Enhancio).
- API Key/Secret: ONE shared org-wide credential, stored in the local
  `app_settings.json` only (never the shared clients folder) — same
  reasoning as `get_jira_settings`/`get_enhancio_client_id`.
- File upload only as the lead source — no "pull from Accumulated Report".
- No reconcile/polling step, no "Post to Jira" section on the new page —
  out of scope per the spec.
- Every new/changed behavior gets a test; run the affected test file after
  each task, and the full suite (`python -m pytest -q`) before considering
  the plan done.

---

### Task 1: `core/integrate_client.py` — API client

**Files:**
- Create: `core/integrate_client.py`
- Test: `tests/test_integrate_client.py`

**Interfaces:**
- Produces: `IntegrateError(Exception)` (carries the parsed `errors[0].title`
  text when present); `submit_lead(sid: str, api_key: str, api_secret: str, attributes: dict[str, str], callback_url: str = "") -> dict`
  — returns the response body's `"data"` dict on success, raises
  `IntegrateError` on any non-2xx status or an unparseable/unexpected body.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_integrate_client.py
from unittest.mock import patch, MagicMock

import pytest

from core.integrate_client import submit_lead, IntegrateError


def test_submit_lead_posts_the_documented_contract_and_returns_the_new_leads_data():
    mock_response = MagicMock(
        status_code=200,
        json=lambda: {"data": {"id": "lead-guid-123", "type": "lead", "attributes": {"email": "a@x.com"}}},
    )
    with patch("core.integrate_client.requests.post", return_value=mock_response) as mock_post:
        result = submit_lead(
            "d8a9deeb-7bb2-4832-b3d9-1df8a9fe5cab", "key123", "secret456",
            {"first_name": "A", "email": "a@x.com"},
        )

    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.integrate.com/api/v1/contracts/d8a9deeb-7bb2-4832-b3d9-1df8a9fe5cab/leads"
    assert kwargs["headers"]["X-API-Key"] == "key123"
    assert kwargs["headers"]["X-API-Key-Secret"] == "secret456"
    assert kwargs["headers"]["Content-Type"] == "application/vnd.api+json"
    assert kwargs["json"] == {"data": {"type": "lead", "attributes": {"first_name": "A", "email": "a@x.com"}}}
    assert "params" not in kwargs or not kwargs["params"]
    assert result == {"id": "lead-guid-123", "type": "lead", "attributes": {"email": "a@x.com"}}


def test_submit_lead_sends_callback_as_a_query_param_only_when_given():
    mock_response = MagicMock(status_code=200, json=lambda: {"data": {"id": "x"}})
    with patch("core.integrate_client.requests.post", return_value=mock_response) as mock_post:
        submit_lead("sid1", "key", "secret", {"email": "a@x.com"}, callback_url="https://example.com/cb")

    args, kwargs = mock_post.call_args
    assert kwargs["params"] == {"callback": "https://example.com/cb"}


def test_submit_lead_raises_with_integrates_own_error_title_on_failure():
    mock_response = MagicMock(
        status_code=422, json=lambda: {"errors": [{"title": "Invalid email address"}]}, text='{"errors":[...]}')
    with patch("core.integrate_client.requests.post", return_value=mock_response):
        with pytest.raises(IntegrateError, match="Invalid email address"):
            submit_lead("sid1", "key", "secret", {"email": "bad"})


def test_submit_lead_raises_when_the_response_body_is_not_valid_json():
    mock_response = MagicMock(status_code=200, text="<html>gateway error</html>")
    mock_response.json.side_effect = ValueError("no JSON")
    with patch("core.integrate_client.requests.post", return_value=mock_response):
        with pytest.raises(IntegrateError):
            submit_lead("sid1", "key", "secret", {"email": "a@x.com"})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_integrate_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.integrate_client'`

- [ ] **Step 3: Write the implementation**

```python
# core/integrate_client.py
import requests

# Confirmed live, from the account's own home.integrate.com Source ->
# Import -> API tab -- NOT the same endpoint the public Integrate help
# article documents (that one is an older, different API:
# https://api.integrate.com/post/{guid}, urlencoded/simple JSON, no
# X-API-Key headers). This is the current one.
_BASE_URL = "https://api.integrate.com/api/v1"


class IntegrateError(Exception):
    """Raised for any non-success response from an Integrate API call --
    carries the parsed error body's "errors"[0]["title"] text when
    Integrate provided one."""


def _first_error_title(body: dict) -> str:
    errors = (body or {}).get("errors") or []
    if errors:
        first = errors[0]
        return str(first.get("title", first)) if isinstance(first, dict) else str(first)
    return ""


def submit_lead(
    sid: str, api_key: str, api_secret: str, attributes: dict[str, str], callback_url: str = "",
) -> dict:
    """POSTs one lead to this Source (identified by its SID/contract GUID).

    attributes: {Integrate attribute name: value}, e.g. {"first_name": "Joe",
    "email": "j@x.com"} -- sent as-is under "data.attributes", no wrapping
    needed from the caller.

    Raises IntegrateError for any non-2xx response or a body that isn't
    valid JSON (never silently treated as success -- same reasoning as
    core/enhancio_client.py's 200-but-not-JSON handling). Returns the
    response body's "data" dict (the created lead, including its new
    "id") on success.
    """
    url = f"{_BASE_URL}/contracts/{sid}/leads"
    headers = {
        "X-API-Key": api_key,
        "X-API-Key-Secret": api_secret,
        "Content-Type": "application/vnd.api+json",
    }
    payload = {"data": {"type": "lead", "attributes": attributes}}
    params = {"callback": callback_url} if callback_url else {}

    response = requests.post(url, headers=headers, json=payload, params=params, timeout=30)
    try:
        body = response.json()
    except ValueError:
        raise IntegrateError(
            f"Integrate returned {response.status_code} but the response body wasn't valid JSON: "
            f"{response.text[:300]}"
        )

    if not (200 <= response.status_code < 300):
        message = _first_error_title(body) or response.text[:300]
        raise IntegrateError(f"Integrate returned {response.status_code}: {message}")

    return (body or {}).get("data", {})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_integrate_client.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add core/integrate_client.py tests/test_integrate_client.py
git commit -m "Add Integrate.com API client (submit_lead)"
```

---

### Task 2: `core/integrate_sync.py` — dedup helpers

**Files:**
- Create: `core/integrate_sync.py`
- Test: `tests/test_integrate_sync.py`

**Interfaces:**
- Consumes: `core.app_settings.get_shared_root_dir() -> str`,
  `core.atomic_io.atomic_write_json(path, data) -> None` (both existing).
- Produces: `filter_already_uploaded(leads_df, email_column, already_uploaded_emails) -> tuple[pd.DataFrame, pd.DataFrame]`;
  `load_uploaded_emails(client_name: str) -> set[str]`;
  `save_uploaded_emails(client_name: str, emails: set[str]) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_integrate_sync.py
import pandas as pd

from core.app_settings import save_app_settings
from core.integrate_sync import filter_already_uploaded, load_uploaded_emails, save_uploaded_emails


def test_filter_already_uploaded_splits_by_normalized_email():
    df = pd.DataFrame([
        {"Email": "A@x.com", "First": "A"},
        {"Email": "b@x.com", "First": "B"},
    ])
    to_send, already_sent = filter_already_uploaded(df, "Email", {"a@x.com"})
    assert list(to_send["First"]) == ["B"]
    assert list(already_sent["First"]) == ["A"]


def test_save_and_load_uploaded_emails_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})

    assert load_uploaded_emails("Everpure EMEA") == set()
    save_uploaded_emails("Everpure EMEA", {"A@x.com", "b@x.com"})
    assert load_uploaded_emails("Everpure EMEA") == {"a@x.com", "b@x.com"}

    # A second save merges with, doesn't replace, what's already there.
    save_uploaded_emails("Everpure EMEA", {"c@x.com"})
    assert load_uploaded_emails("Everpure EMEA") == {"a@x.com", "b@x.com", "c@x.com"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_integrate_sync.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.integrate_sync'`

- [ ] **Step 3: Write the implementation**

```python
# core/integrate_sync.py
import json
import os

import pandas as pd

from core.app_settings import get_shared_root_dir
from core.atomic_io import atomic_write_json


def _normalize_email(email) -> str:
    return str(email or "").strip().lower()


def filter_already_uploaded(
    leads_df: pd.DataFrame, email_column: str, already_uploaded_emails: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Splits a leadfile into (rows_to_send, rows_already_uploaded) by
    email, so a repeated (or overlapping) upload never resends a lead
    already submitted to this client's Integrate Source. Both preserve
    leads_df's own index.
    """
    is_duplicate = leads_df[email_column].astype(str).map(_normalize_email).isin(already_uploaded_emails)
    return leads_df[~is_duplicate], leads_df[is_duplicate]


def _uploaded_emails_path(client_name: str) -> str:
    root = get_shared_root_dir()
    return os.path.join(root, "integrate_uploaded_emails", f"{client_name}.json") if root else ""


def load_uploaded_emails(client_name: str) -> set[str]:
    """Every email successfully submitted to this client's Integrate
    Source, ever -- across every teammate. Scoped per client (not per
    allocation, unlike Enhancio) since a client maps to exactly one SID.
    """
    path = _uploaded_emails_path(client_name)
    if not path or not os.path.isfile(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_uploaded_emails(client_name: str, emails: set[str]) -> None:
    path = _uploaded_emails_path(client_name)
    if not path:
        return
    existing = load_uploaded_emails(client_name)
    existing.update(_normalize_email(e) for e in emails if _normalize_email(e))
    atomic_write_json(path, sorted(existing))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_integrate_sync.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add core/integrate_sync.py tests/test_integrate_sync.py
git commit -m "Add Integrate.com dedup helpers (integrate_sync)"
```

---

### Task 3: `core/models.py` — `IntegrateConfig`

**Files:**
- Modify: `core/models.py`
- Test: `tests/test_models.py` (create if it doesn't already exist — check
  first with `ls tests/test_models.py`; if the repo has no such file yet,
  create it with just the tests below)

**Interfaces:**
- Consumes: `FieldMapping`, `Optional` (already imported at the top of
  `core/models.py`).
- Produces: `IntegrateConfig` dataclass; `ClientProfile.integrate: IntegrateConfig`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py (append if the file already exists; the import
# line and this one test are all that's needed for this task)
from core.models import ClientProfile, IntegrateConfig


def test_client_profile_defaults_to_a_disabled_integrate_config():
    profile = ClientProfile(name="X", accumulated_report_path="acc.xlsx")
    assert profile.integrate.enabled is False
    assert profile.integrate.sid == ""
    assert profile.integrate.field_mapping == {}
    assert profile.integrate.fixed_field_values == {}
    assert profile.integrate.leadfile_field_mapping is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'IntegrateConfig'`

- [ ] **Step 3: Add `IntegrateConfig` and wire it onto `ClientProfile`**

In `core/models.py`, add this new dataclass directly after `EnhancioConfig`
(before the `@dataclass class ClientProfile:` line):

```python
@dataclass
class IntegrateConfig:
    # Uploads a client-verified leadfile straight to Integrate.com's Lead
    # API (https://api.integrate.com/api/v1/contracts/{sid}/leads) --
    # confirmed live from the account's own Import -> API tab. Unlike
    # Convertr/Enhancio, ONE SID per client (not per-CID), since a client
    # maps to exactly one Integrate Source for this rollout.
    enabled: bool = False
    sid: str = ""
    # Optional -- Integrate's own docs show this as an unrequired query
    # param. This app has no public endpoint to receive it, so it's sent
    # only when explicitly configured, never a made-up placeholder value.
    callback_url: str = ""
    # {leadfile column name: Integrate attribute name}, e.g.
    # {"Email": "email", "First Name": "first_name"}.
    field_mapping: dict[str, str] = field(default_factory=dict)
    # {Integrate attribute name: fixed value} -- for an attribute that's
    # the SAME for every lead this client sends (e.g. "country": "UK"),
    # not read from the leadfile row at all. Same purpose as
    # EnhancioConfig.fixed_field_values, but flat (not per-allocation)
    # since there's only one SID here.
    fixed_field_values: dict[str, str] = field(default_factory=dict)
    # Same purpose/fallback behavior as ConvertrConfig.leadfile_field_mapping.
    leadfile_field_mapping: Optional[FieldMapping] = None
```

Then find the `@dataclass class ClientProfile:` block and add this field
alongside the existing `convertr`/`enhancio` fields (search for
`enhancio: EnhancioConfig` in the file to find the exact spot):

```python
    integrate: IntegrateConfig = field(default_factory=IntegrateConfig)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Run the full model-adjacent suite to check nothing else broke**

Run: `python -m pytest tests/test_client_setup_page.py -q`
Expected: PASS (unchanged — `IntegrateConfig` defaults to disabled, so
existing profiles/tests round-trip identically)

- [ ] **Step 6: Commit**

```bash
git add core/models.py tests/test_models.py
git commit -m "Add IntegrateConfig to ClientProfile"
```

---

### Task 4: `core/app_settings.py` — credential storage

**Files:**
- Modify: `core/app_settings.py`
- Test: `tests/test_app_settings.py` (check with `ls` first; append to it
  if it exists, else create it with just the import and test below)

**Interfaces:**
- Produces: `get_integrate_credentials() -> tuple[str, str]` (API Key, API
  Secret); `save_integrate_credentials(api_key: str, api_secret: str) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app_settings.py
from core.app_settings import get_integrate_credentials, save_integrate_credentials


def test_save_and_get_integrate_credentials_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert get_integrate_credentials() == ("", "")
    save_integrate_credentials("  key123  ", "secret456")
    assert get_integrate_credentials() == ("key123", "secret456")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_app_settings.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_integrate_credentials'`

- [ ] **Step 3: Add the functions**

Append to the end of `core/app_settings.py` (after `save_enhancio_client_id`):

```python
def get_integrate_credentials() -> tuple[str, str]:
    # Unconfirmed whether Integrate's API Key/Secret is genuinely
    # org-wide-shared or needs to be per-client (see the design spec's
    # "Open questions") -- built as ONE shared credential for now, same
    # storage reasoning as get_jira_settings/get_enhancio_client_id: a
    # live API credential belongs in the plain local app_settings.json
    # only, never inside the shared clients folder every teammate can read.
    settings = load_app_settings()
    return settings.get("integrate_api_key", ""), settings.get("integrate_api_secret", "")


def save_integrate_credentials(api_key: str, api_secret: str) -> None:
    updated = load_app_settings()
    updated["integrate_api_key"] = api_key.strip()
    updated["integrate_api_secret"] = api_secret.strip()
    save_app_settings(updated)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_app_settings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/app_settings.py tests/test_app_settings.py
git commit -m "Add Integrate API Key/Secret credential storage"
```

---

### Task 5: `pages/3_Settings.py` — credentials section

**Files:**
- Modify: `pages/3_Settings.py`
- Test: `tests/test_settings_page.py`

**Interfaces:**
- Consumes: `core.app_settings.get_integrate_credentials`,
  `save_integrate_credentials` (from Task 4).

- [ ] **Step 1: Write the failing test**

First check the exact existing import line and `queue_toast_before_rerun`
usage in `pages/3_Settings.py` (read the file's top ~15 lines) so the new
test matches how the Enhancio section's own save-and-rerun test is written
— search `tests/test_settings_page.py` for
`"Save Enhancio Client ID"` to copy that test's exact shape. Then add:

```python
# tests/test_settings_page.py (append)
from core.app_settings import get_integrate_credentials


def test_saving_integrate_credentials_persists_them(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.text_input(key="integrate_api_key_input").set_value("key123").run()
    at.text_input(key="integrate_api_secret_input").set_value("secret456").run()
    next(b for b in at.button if b.label == "Save Integrate credentials").click().run()
    assert not at.exception
    assert get_integrate_credentials() == ("key123", "secret456")
```

(If `_PAGE_PATH` or the `AppTest` import isn't already at the top of
`tests/test_settings_page.py`, add them matching however the file's
existing tests reference the Settings page — read the file first.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_settings_page.py -k integrate_credentials -v`
Expected: FAIL (button/text_input not found — section doesn't exist yet)

- [ ] **Step 3: Add the Settings section**

In `pages/3_Settings.py`, add the import alongside the existing
`get_enhancio_client_id, save_enhancio_client_id` import line:

```python
from core.app_settings import get_integrate_credentials, save_integrate_credentials
```

Then add this new expander directly after the existing
`with st.expander("🔑 Enhancio Client ID (private to this machine)", expanded=False):`
block (matching its indentation/structure exactly):

```python
with st.expander("🔑 Integrate API credentials (private to this machine)", expanded=False):
    st.caption(
        "Used by the 🔗 Integrate page. One shared API Key/Secret for the whole org (from Integrate's "
        "Keys & credentials admin page) — each client just needs its own Source ID (SID), set on Client "
        "Setup. This is a live API credential, so it's stored locally on this machine only, never inside "
        "the shared clients folder above."
    )
    _integrate_key, _integrate_secret = get_integrate_credentials()
    integrate_api_key = st.text_input(
        "Integrate API Key", value=_integrate_key, type="password", key="integrate_api_key_input")
    integrate_api_secret = st.text_input(
        "Integrate API Secret", value=_integrate_secret, type="password", key="integrate_api_secret_input")
    if st.button("Save Integrate credentials", key="integrate_credentials_save"):
        save_integrate_credentials(integrate_api_key, integrate_api_secret)
        queue_toast_before_rerun("Saved.")
        st.rerun()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_settings_page.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 5: Commit**

```bash
git add pages/3_Settings.py tests/test_settings_page.py
git commit -m "Add Integrate API credentials section to Settings"
```

---

### Task 6: `pages/1_Client_Setup.py` — Integrate section

**Files:**
- Modify: `pages/1_Client_Setup.py`
- Test: `tests/test_client_setup_page.py`

**Interfaces:**
- Consumes: `IntegrateConfig` (Task 3), `_render_paired_field_mapping`,
  `_render_leadfile_column_mapping` (both already defined in this file).
- Produces: the saved profile's `.integrate` field, populated from this
  section's inputs.

- [ ] **Step 1: Write the failing test**

Read `tests/test_client_setup_page.py`'s existing Enhancio-section save
test first (search for `enhancio_enabled` or `"This client uploads to
Enhancio"`) to match its exact AppTest interaction style, then add:

```python
# tests/test_client_setup_page.py (append)
def test_saving_integrate_section_persists_sid_and_field_mapping(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    at.text_input(key="client_name_input").set_value("Everpure EMEA").run()
    at.text_input(key="accumulated_report_path_input").set_value(str(tmp_path / "acc.xlsx")).run()

    at.checkbox(key="integrate_enabled").set_value(True).run()
    at.text_input(key="integrate_sid_input").set_value("d8a9deeb-7bb2-4832-b3d9-1df8a9fe5cab").run()
    at.text_area(key="integrate_field_map_cols_input").set_value("Email\nFirst Name").run()
    at.text_area(key="integrate_field_map_targets_input").set_value("email\nfirst_name").run()
    at.text_area(key="integrate_fixed_values_input").set_value("country,UK").run()

    next(b for b in at.button if b.label == "Save client profile").click().run()
    assert not at.exception

    saved = load_profile("Everpure EMEA", get_clients_dir())
    assert saved.integrate.enabled is True
    assert saved.integrate.sid == "d8a9deeb-7bb2-4832-b3d9-1df8a9fe5cab"
    assert saved.integrate.field_mapping == {"Email": "email", "First Name": "first_name"}
    assert saved.integrate.fixed_field_values == {"country": "UK"}
```

(Check the exact `key=` values for `client_name_input`,
`accumulated_report_path_input`, and the "Save client profile" button
label by reading the top of an existing save test in this file — use
whatever the file's own tests actually use; adjust the two lines above to
match if they differ from this guess.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_client_setup_page.py -k integrate_section -v`
Expected: FAIL (checkbox/text_input with those keys don't exist yet)

- [ ] **Step 3: Add the Client Setup section**

In `pages/1_Client_Setup.py`, add `IntegrateConfig` to the existing models
import line (search for `ConvertrConfig, ConvertrCampaignMapping` — add
`IntegrateConfig` alongside it):

```python
    LeadTemplateTab, ComplexAccountConfig, BoxTrackerConfig, ConvertrConfig, ConvertrCampaignMapping,
    EnhancioConfig, EnhancioAllocationMapping, IntegrateConfig,
```

(Match whatever the exact existing multi-line import already contains —
just add `IntegrateConfig` to it.)

Then, directly after the Enhancio section ends (search for where
`enhancio_leadfile_mapping = _render_leadfile_column_mapping(...)` is
followed by the "Fetch allocations"/"Test connection" buttons block, and
insert this new section right after that whole Enhancio block, before
whatever section comes next — read the surrounding code first to place it
at the correct indentation, matching the Convertr/Enhancio sections'
`if <name>_enabled:` structure exactly):

```python
        st.divider()
        st.markdown("**Integrate Upload (optional)**")
        st.caption(
            "Uploads a client-verified leadfile straight to Integrate.com's Lead API. One shared "
            "org-wide API Key/Secret (set once on the ⚙️ Settings page) — this client just needs its "
            "own Source ID (SID), from that Source's URL on home.integrate.com."
        )
        integrate_enabled = st.checkbox(
            "This client uploads to Integrate", value=profile.integrate.enabled if profile else False,
            key="integrate_enabled")
        integrate_sid = ""
        integrate_callback_url = ""
        integrate_field_mapping: dict[str, str] = {}
        integrate_fixed_values: dict[str, str] = {}
        integrate_leadfile_mapping: FieldMapping | None = None
        if integrate_enabled:
            integrate_sid = st.text_input(
                "Integrate Source ID (SID) — the GUID in home.integrate.com/sources/{SID}",
                value=profile.integrate.sid if profile else "", key="integrate_sid_input").strip()
            integrate_callback_url = st.text_input(
                "Callback URL (optional — leave blank unless Integrate told you to set one)",
                value=profile.integrate.callback_url if profile else "", key="integrate_callback_url_input").strip()

            integrate_field_mapping = _render_paired_field_mapping(
                "integrate", "Integrate", profile.integrate.field_mapping if profile else {})

            st.caption(
                "Fixed field values, one per line, format `Attribute,Fixed Value` — for an Integrate "
                "attribute that's the SAME for every lead this client sends (e.g. country), not read "
                "from the leadfile:"
            )
            _existing_integrate_fixed_text = "\n".join(
                f"{attr},{value}"
                for attr, value in (profile.integrate.fixed_field_values.items() if profile else [])
            )
            _integrate_fixed_text = st.text_area(
                "Integrate fixed field values", value=_existing_integrate_fixed_text,
                key="integrate_fixed_values_input", label_visibility="collapsed", height=80)
            for _line in _integrate_fixed_text.splitlines():
                _line = _line.strip()
                if not _line or "," not in _line:
                    continue
                _attr, _value = (p.strip() for p in _line.split(",", 1))
                integrate_fixed_values[_attr] = _value

            integrate_leadfile_mapping = _render_leadfile_column_mapping(
                "integrate", profile.integrate.leadfile_field_mapping if profile else None)
        else:
            st.caption("Integrate upload is disabled for this client.")
```

Finally, in the `ClientProfile(...)` construction near the bottom of the
file (search for `convertr=ConvertrConfig(` to find the exact block), add
a sibling `integrate=IntegrateConfig(...)` argument:

```python
            integrate=IntegrateConfig(
                enabled=integrate_enabled,
                sid=integrate_sid if integrate_enabled else "",
                callback_url=integrate_callback_url if integrate_enabled else "",
                field_mapping=integrate_field_mapping if integrate_enabled else {},
                fixed_field_values=integrate_fixed_values if integrate_enabled else {},
                leadfile_field_mapping=integrate_leadfile_mapping if integrate_enabled else None,
            ),
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_client_setup_page.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 5: Commit**

```bash
git add pages/1_Client_Setup.py tests/test_client_setup_page.py
git commit -m "Add Integrate section to Client Setup"
```

---

### Task 7: `pages/9_Integrate.py` — the upload page

**Files:**
- Create: `pages/9_Integrate.py`
- Test: `tests/test_integrate_page.py`

**Interfaces:**
- Consumes: `core.integrate_client.submit_lead`, `IntegrateError` (Task 1);
  `core.integrate_sync.filter_already_uploaded`, `load_uploaded_emails`,
  `save_uploaded_emails` (Task 2); `core.app_settings.get_integrate_credentials`,
  `get_clients_dir` (Task 4 + existing); `core.models.resolve_field_mapping`
  (existing); `core.profile_store.list_profile_names`, `load_profile`
  (existing); `core.excel_io.read_leadfile` (existing);
  `core.errors.render_error` (existing); `core.branding.configure_page`
  (existing).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_integrate_page.py
import os
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from core.app_settings import get_clients_dir, save_app_settings, save_integrate_credentials
from core.integrate_sync import load_uploaded_emails
from core.models import ClientProfile, FieldMapping, IntegrateConfig
from core.profile_store import save_profile

_PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pages", "9_Integrate.py")


def _save_profile() -> ClientProfile:
    fm = FieldMapping(email="Email", first_name="First", last_name="Last", company="Company", cid="CID")
    profile = ClientProfile(
        name="Everpure EMEA", accumulated_report_path="acc.xlsx", field_mapping=fm,
        integrate=IntegrateConfig(
            enabled=True, sid="d8a9deeb-7bb2-4832-b3d9-1df8a9fe5cab",
            field_mapping={"Email": "email", "First": "first_name", "Last": "last_name"},
            fixed_field_values={"country": "UK"},
        ),
    )
    save_profile(profile, get_clients_dir())
    return profile


def test_warns_when_no_client_has_integrate_enabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    assert not at.exception
    assert any("No client has Integrate enabled" in w.value for w in at.warning)


def test_errors_when_credentials_are_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    _save_profile()
    at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
    at.run()
    next(s for s in at.selectbox if s.label == "Client").set_value("Everpure EMEA").run()
    assert any("Integrate API Key/Secret" in e.value for e in at.error)


def test_uploads_leads_and_saves_dedup_state_incrementally(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_integrate_credentials("key123", "secret456")
    _save_profile()

    leads_csv = tmp_path / "leads.csv"
    pd.DataFrame([
        {"CID": "1", "Email": "a@x.com", "First": "A", "Last": "One"},
        {"CID": "1", "Email": "b@x.com", "First": "B", "Last": "Two"},
    ]).to_csv(leads_csv, index=False)

    submit_calls = []

    def _fake_submit(sid, api_key, api_secret, attributes, callback_url=""):
        submit_calls.append((sid, api_key, api_secret, attributes))
        return {"id": f"lead-{len(submit_calls)}"}

    with patch("core.integrate_client.submit_lead", side_effect=_fake_submit):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Everpure EMEA").run()
        with open(leads_csv, "rb") as f:
            at.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
        next(b for b in at.button if b.label == "Upload to Integrate").click().run()

    assert not at.exception
    assert len(submit_calls) == 2
    assert submit_calls[0][0] == "d8a9deeb-7bb2-4832-b3d9-1df8a9fe5cab"
    assert submit_calls[0][1:3] == ("key123", "secret456")
    assert submit_calls[0][3] == {"email": "a@x.com", "first_name": "A", "last_name": "One", "country": "UK"}
    assert load_uploaded_emails("Everpure EMEA") == {"a@x.com", "b@x.com"}


def test_test_mode_sends_only_the_first_lead(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_integrate_credentials("key123", "secret456")
    _save_profile()

    leads_csv = tmp_path / "leads.csv"
    pd.DataFrame([
        {"CID": "1", "Email": "a@x.com", "First": "A", "Last": "One"},
        {"CID": "1", "Email": "b@x.com", "First": "B", "Last": "Two"},
    ]).to_csv(leads_csv, index=False)

    with patch("core.integrate_client.submit_lead", return_value={"id": "lead-1"}) as mock_submit:
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Everpure EMEA").run()
        at.checkbox(key="integrate_test_mode").set_value(True).run()
        with open(leads_csv, "rb") as f:
            at.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
        next(b for b in at.button if b.label == "Upload to Integrate").click().run()

    assert not at.exception
    assert mock_submit.call_count == 1
    assert load_uploaded_emails("Everpure EMEA") == {"a@x.com"}


def test_a_single_lead_failure_does_not_abort_the_rest_of_the_batch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_integrate_credentials("key123", "secret456")
    _save_profile()

    leads_csv = tmp_path / "leads.csv"
    pd.DataFrame([
        {"CID": "1", "Email": "bad@x.com", "First": "Bad", "Last": "Lead"},
        {"CID": "1", "Email": "good@x.com", "First": "Good", "Last": "Lead"},
    ]).to_csv(leads_csv, index=False)

    from core.integrate_client import IntegrateError

    def _fake_submit(sid, api_key, api_secret, attributes, callback_url=""):
        if attributes["email"] == "bad@x.com":
            raise IntegrateError("Integrate returned 422: Invalid email address")
        return {"id": "lead-ok"}

    with patch("core.integrate_client.submit_lead", side_effect=_fake_submit):
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Everpure EMEA").run()
        with open(leads_csv, "rb") as f:
            at.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()
        next(b for b in at.button if b.label == "Upload to Integrate").click().run()

    assert not at.exception
    assert load_uploaded_emails("Everpure EMEA") == {"good@x.com"}


def test_dedup_skips_a_previously_uploaded_email(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_app_settings({"shared_root_dir": str(tmp_path / "Shared")})
    save_integrate_credentials("key123", "secret456")
    _save_profile()
    from core.integrate_sync import save_uploaded_emails
    save_uploaded_emails("Everpure EMEA", {"a@x.com"})

    leads_csv = tmp_path / "leads.csv"
    pd.DataFrame([{"CID": "1", "Email": "a@x.com", "First": "A", "Last": "One"}]).to_csv(leads_csv, index=False)

    with patch("core.integrate_client.submit_lead") as mock_submit:
        at = AppTest.from_file(_PAGE_PATH, default_timeout=15)
        at.run()
        next(s for s in at.selectbox if s.label == "Client").set_value("Everpure EMEA").run()
        with open(leads_csv, "rb") as f:
            at.get("file_uploader")[0].set_value(("leads.csv", f.read(), "text/csv")).run()

    assert not at.exception
    assert any("already uploaded" in w.value for w in at.warning)
    mock_submit.assert_not_called()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_integrate_page.py -v`
Expected: FAIL (`pages/9_Integrate.py` doesn't exist yet)

- [ ] **Step 3: Write the page**

```python
# pages/9_Integrate.py
import os

import pandas as pd
import streamlit as st

from core.app_settings import get_clients_dir, get_integrate_credentials
from core.branding import configure_page
from core.errors import render_error
from core.excel_io import read_leadfile
from core import integrate_client
from core.integrate_client import IntegrateError
from core.integrate_sync import filter_already_uploaded, load_uploaded_emails, save_uploaded_emails
from core.models import resolve_field_mapping
from core.profile_store import list_profile_names, load_profile

_current_user = configure_page("Integrate")
st.title("🔗 Integrate")


@st.cache_data(show_spinner=False)
def _cached_profile_names(clients_dir: str, dir_mtime: float) -> list[str]:
    # mtime must NOT be underscore-prefixed -- Streamlit excludes any
    # leading-underscore parameter from the cache key hash. Same fix as
    # pages/7_Convertr.py's _cached_profile_names.
    return list_profile_names(clients_dir)


@st.cache_data(show_spinner=False)
def _cached_load_profile(name: str, clients_dir: str, mtime: float):
    return load_profile(name, clients_dir)


def _clients_dir_mtime(clients_dir: str) -> float:
    try:
        return os.path.getmtime(clients_dir)
    except OSError:
        return 0.0


def _profile_file_mtime(name: str, clients_dir: str) -> float:
    try:
        return os.path.getmtime(os.path.join(clients_dir, f"{name}.json"))
    except OSError:
        return 0.0


_clients_dir_now = get_clients_dir()
_profile_names = [
    name for name in _cached_profile_names(_clients_dir_now, _clients_dir_mtime(_clients_dir_now))
    if _cached_load_profile(name, _clients_dir_now, _profile_file_mtime(name, _clients_dir_now)).integrate.enabled
]
if not _profile_names:
    st.warning("No client has Integrate enabled yet. Set it up on the Client Setup page first.")
    st.stop()

client_name = st.selectbox("Client", _profile_names)
profile = _cached_load_profile(client_name, _clients_dir_now, _profile_file_mtime(client_name, _clients_dir_now))
_integrate = profile.integrate
_leadfile_mapping = resolve_field_mapping(_integrate.leadfile_field_mapping, profile.field_mapping)

_api_key, _api_secret = get_integrate_credentials()
if not _api_key or not _api_secret:
    st.error("Set the Integrate API Key/Secret on the ⚙️ Settings page first.")
    st.stop()
if not _integrate.sid:
    st.error("This client has no Integrate Source ID (SID) saved — set one on Client Setup.")
    st.stop()

st.caption(
    "Uploads a client-verified leadfile straight to this client's Integrate Source. A lead already "
    "uploaded before (by email) is skipped automatically, so re-uploading the same or an overlapping "
    "file is safe."
)

_test_mode = st.checkbox(
    "Test mode — upload only 1 lead", key="integrate_test_mode",
    help="Use this for a first-time check before uploading real volume.",
)
_upload_file = st.file_uploader("Verified leadfile", type=["xlsx", "csv"], key="integrate_upload_file")

if _upload_file:
    try:
        leads_df = read_leadfile(_upload_file)
    except Exception as exc:
        render_error(exc)
        st.stop()

    if not _leadfile_mapping or not _leadfile_mapping.email:
        st.error(
            "This client has no leadfile column mapping for Integrate yet — set one under Client "
            "Setup's Integrate section (at least the Email column)."
        )
        st.stop()
    email_column = _leadfile_mapping.email
    if email_column not in leads_df.columns:
        st.error(f"This client's Email column (\"{email_column}\") isn't in the uploaded file.")
        st.stop()

    _already_uploaded = load_uploaded_emails(client_name)
    _send_df, _dup_df = filter_already_uploaded(leads_df, email_column, _already_uploaded)
    if not _dup_df.empty:
        st.warning(f"{len(_dup_df)} lead(s) in this file were already uploaded to Integrate before — skipped.")
    if _test_mode and len(_send_df) > 1:
        st.caption(f"Test mode: only the first lead of {len(_send_df)} will actually be sent.")
        _send_df = _send_df.iloc[:1]

    if not _integrate.field_mapping:
        st.error(
            "This client has no Integrate field mapping configured yet — set one under Client Setup's "
            "Integrate section."
        )
        st.stop()

    if st.button("Upload to Integrate", type="primary"):
        results = []
        for _, lead in _dup_df.iterrows():
            results.append({"Email": lead.get(email_column, ""), "Result": "⏭️ Skipped (already uploaded previously)"})

        _total_to_send = len(_send_df)
        _send_progress = st.progress(0.0, text=f"Uploading 0 / {_total_to_send} lead(s) to Integrate...") \
            if _total_to_send else None
        _sent_so_far = 0
        _newly_uploaded_emails: set[str] = set()

        for _, lead in _send_df.iterrows():
            attributes = {
                integrate_attr: str(lead.get(leadfile_col, "") or "")
                for leadfile_col, integrate_attr in _integrate.field_mapping.items()
            }
            attributes.update(_integrate.fixed_field_values)
            email = lead.get(email_column, "")
            try:
                response = integrate_client.submit_lead(
                    _integrate.sid, _api_key, _api_secret, attributes, callback_url=_integrate.callback_url,
                )
                lead_id = str(response.get("id", ""))
                results.append({"Email": email, "Result": f"✅ Lead ID {lead_id}"})
                # Saved per-lead, not batched to the end of the whole loop --
                # same reasoning as pages/7_Convertr.py's per-CID incremental
                # save: an exception on a LATER lead must never discard an
                # earlier, already-succeeded lead's dedup record.
                save_uploaded_emails(client_name, {str(email)})
            except IntegrateError as exc:
                results.append({"Email": email, "Result": f"❌ {exc}"})
            _sent_so_far += 1
            if _send_progress is not None:
                _send_progress.progress(
                    _sent_so_far / _total_to_send,
                    text=f"Uploading {_sent_so_far} / {_total_to_send} lead(s) to Integrate...")
        if _send_progress is not None:
            _send_progress.empty()

        st.session_state["integrate_upload_results"] = pd.DataFrame(results)

if st.session_state.get("integrate_upload_results") is not None:
    _results_df = st.session_state["integrate_upload_results"]
    _ok = int(_results_df["Result"].str.startswith("✅").sum())
    _failed = int(_results_df["Result"].str.startswith("❌").sum())
    _skipped = int(_results_df["Result"].str.startswith("⏭️").sum())
    _sum_col1, _sum_col2, _sum_col3 = st.columns(3)
    _sum_col1.metric("✅ Uploaded", _ok)
    _sum_col2.metric("❌ Failed", _failed)
    _sum_col3.metric("⏭️ Skipped", _skipped)
    st.dataframe(_results_df, hide_index=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_integrate_page.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add pages/9_Integrate.py tests/test_integrate_page.py
git commit -m "Add Integrate.com lead upload page"
```

---

### Task 8: Full-suite check and app registration

**Files:**
- Check: `launcher.py` or `Summary.py` (wherever `st.navigation()` lists
  pages) — a new `pages/9_*.py` file is picked up automatically by
  Streamlit's default page auto-discovery UNLESS this app explicitly lists
  pages (it does, per the audit history — `st.navigation()` in `Summary.py`).
  Read that file first to confirm.

**Interfaces:**
- None new — this task only wires the new page into navigation if needed
  and runs full verification.

- [ ] **Step 1: Check whether pages are explicitly listed**

Run: `grep -n "st.navigation\|Convertr\|Enhancio" Summary.py`

- [ ] **Step 2: If pages are explicitly listed, add the new page**

If `Summary.py`'s `st.navigation()` call explicitly lists each page (e.g.
`st.Page("pages/8_Enhancio.py", title="Enhancio", icon="🔗")`), add a
matching entry for `pages/9_Integrate.py` right after the Enhancio entry,
matching its exact `title`/`icon` style. If pages are auto-discovered
instead (no explicit list), skip this step — nothing to change.

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest -q`
Expected: every test passes except the 2 pre-existing, unrelated
`tests/test_end_to_end_basware.py` filename-encoding errors (confirmed
present on unmodified `master` too, unrelated to this feature).

- [ ] **Step 4: Manually verify in the browser**

Start the dev server (`preview_start` with the `streamlit-app-dev`
config), log in, click through to the new "Integrate" sidebar link, and
confirm:
- With no client enabled: the "No client has Integrate enabled" warning
  renders.
- After enabling a test client + SID + field mapping on Client Setup and
  saving Integrate credentials on Settings: the Integrate page renders its
  uploader with no exceptions.
(Do not actually POST a real lead to Integrate's live API during this
check — use a fake/placeholder SID for this manual smoke test, or skip
past the "Upload to Integrate" button click.)

- [ ] **Step 5: Commit** (only if Step 2 made a change)

```bash
git add Summary.py
git commit -m "Register the Integrate page in app navigation"
```

## Self-Review Notes

- **Spec coverage:** API contract (Task 1), dedup (Task 2), config model
  (Task 3), credentials (Tasks 4-5), field mapping/SID setup (Task 6),
  upload page with test mode (1-lead-first, gated per Task 7's
  `_test_mode` checkbox) + dedup + per-lead error isolation + incremental
  save (Task 7), navigation/full verification (Task 8). Reconcile/polling
  and "pull from Accumulated" are explicitly out of scope per the spec —
  no task needed for either.
- **Type consistency check:** `submit_lead`'s signature
  (`sid, api_key, api_secret, attributes, callback_url=""`) is used
  identically in Task 1's tests, Task 7's page code, and Task 7's test
  mocks. `IntegrateConfig`'s field names (`sid`, `callback_url`,
  `field_mapping`, `fixed_field_values`, `leadfile_field_mapping`) match
  across Task 3's dataclass, Task 6's Client Setup save code, and Task 7's
  page reads.

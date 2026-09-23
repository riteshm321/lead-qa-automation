# Integrate.com Lead Upload Design

## Goal

Let a client's verified leadfile be uploaded straight to that client's
Integrate.com Source via API, instead of the manual drag-and-drop upload on
`home.integrate.com`'s Import tab — the same "upload page" pattern this app
already has for Convertr (`pages/7_Convertr.py`) and Enhancio
(`pages/8_Enhancio.py`).

## API contract (confirmed live, from the account's own Import → API tab —
not the generic public help article, which documents a different, older
endpoint)

```
POST https://api.integrate.com/api/v1/contracts/{SID}/leads?callback={callback URL}
X-API-Key: {API Key}
X-API-Key-Secret: {API Secret}
Content-Type: application/vnd.api+json

{
  "data": {
    "type": "lead",
    "attributes": {
      "first_name": "", "last_name": "", "email": "", "phone": "",
      "asset_title": "", "company_name": "", "industry": "", "job_title": "",
      "employee_size": "", "job_level": "", "job_function": "",
      "CompanyRevenue": "", "opt_in": "", "OptInDate": "",
      "double_optin": "", "double_date_optin": "", "country": ""
    }
  }
}
```

`{SID}` is the Source's own GUID (the same id in the Source's
`home.integrate.com/sources/{SID}` URL) — one fixed value per client/Source,
not a per-CID mapping like Convertr's `campaign_id`/Enhancio's
`allocation_uid`, since a client maps to exactly one Integrate Source for
this rollout (Everpure EMEA: `d8a9deeb-7bb2-4832-b3d9-1df8a9fe5cab`).

Success: `{"data": {"id": "<lead-guid>", ...}}`. Failure: `{"errors":
[{"title": "..."}]}` — the `title` text is the only reliably-present error
detail, same "trust the HTTP status, extract what text is there" reasoning
already used in `core/convertr_client.py`'s `submit_lead_as_publisher`. No
`callback` URL is sent (this app has no public endpoint to receive one) — the
lead's outcome is read straight from this same synchronous POST response,
never polled separately.

The `callback` query parameter is optional per the sample request (shown
with a placeholder, not marked required) — omitted entirely when blank,
same "don't send it at all" convention as `ConvertrCampaignMapping.campaign_link_id`.

## Scope

- **In scope:** one client (Everpure EMEA) to start, with the Client Setup
  section built generally enough that adding a second client later is just
  filling in its own SID/mapping — the same "enabled per client" opt-in
  Convertr/Enhancio already use.
- **In scope:** file upload only as the lead source (no "pull from
  Accumulated Report" option, unlike Enhancio) — explicit scope decision.
- **In scope:** duplicate-upload prevention by email, and a test-mode
  (1 lead) step before sending the rest — both matching Convertr/Enhancio.
- **In scope:** a configurable field mapping in Client Setup (leadfile
  column → Integrate attribute), covering all 17 attributes the API accepts,
  plus fixed-value attributes (a client-wide constant, e.g. `country`, not
  derived from the leadfile row).
- **Out of scope:** API Key/Secret storage scope (shared org-wide vs.
  per-client) is unconfirmed — built as ONE shared org-wide credential
  (`app_settings.json`, same as the Jira/Enhancio pattern) since that is
  both the simpler default and what the account's "Keys & credentials" admin
  page (org-level, not per-Source) suggests is actually correct. Revisit
  once confirmed with the Integrate admin — moving one config value from
  Settings to per-client Client Setup fields is a small, contained change.
- **Out of scope:** polling/reconciling a lead's later accepted/rejected
  status (unlike Convertr's `get_lead_result`/Enhancio's `get_lead_status`)
  — Integrate's response is synchronous and immediate (the sample response
  echoes the created lead back), and the Source Summary page's own
  Accepted/Rejected/Processing counters remain the system of record for
  anything that resolves later. No `integrate_pending_leads` store.

## Architecture

New files, modeled directly on the existing Convertr/Enhancio pair:

1. **`core/integrate_client.py`** — API client.
   - `IntegrateError(Exception)` — carries Integrate's own `errors[0].title`
     text when present.
   - `submit_lead(sid: str, api_key: str, api_secret: str, attributes: dict[str, str], callback_url: str = "") -> dict`
     — POSTs one lead, JSON:API body/headers as above. Raises
     `IntegrateError` on any non-2xx response or a malformed/non-JSON body
     (same reasoning as `core/enhancio_client.py`'s 200-but-not-JSON fix from
     the recent audit — never silently treat an unparseable body as success).
     Returns the parsed response body's `data` object on success.

2. **`core/integrate_sync.py`** — dedup helpers, modeled on
   `enhancio_sync.py` but keyed per-client only (one SID per client, not
   per-CID allocation):
   - `filter_already_uploaded(leads_df, email_column, already_uploaded_emails) -> (to_send, already_sent)`
   - `load_uploaded_emails(client_name) -> set[str]` /
     `save_uploaded_emails(client_name, emails) -> None` — shared OneDrive
     JSON at `{shared_root}/integrate_uploaded_emails/{client_name}.json`,
     same atomic-write/cross-teammate-visible pattern as Convertr/Enhancio.

3. **`core/models.py`** — new dataclasses on `ClientProfile`:
   ```python
   @dataclass
   class IntegrateConfig:
       enabled: bool = False
       sid: str = ""
       callback_url: str = ""
       # {leadfile column name: Integrate attribute name}, e.g.
       # {"Email": "email", "First Name": "first_name"}.
       field_mapping: dict[str, str] = field(default_factory=dict)
       # {Integrate attribute name: fixed value} -- for attributes that are
       # the SAME for every lead this client sends (e.g. "country": "UK"),
       # same purpose as EnhancioConfig.fixed_field_values.
       fixed_field_values: dict[str, str] = field(default_factory=dict)
       # Same purpose/fallback behavior as ConvertrConfig.leadfile_field_mapping.
       leadfile_field_mapping: Optional[FieldMapping] = None
   ```
   `ClientProfile.integrate: IntegrateConfig = field(default_factory=IntegrateConfig)`.

4. **`core/app_settings.py`** — `get_integrate_credentials() -> tuple[str, str]`
   (API Key, API Secret) / `save_integrate_credentials(api_key, api_secret) -> None`,
   reading/writing the plain local `app_settings.json` only, same as
   `get_jira_settings`/`get_enhancio_client_id`.

5. **`pages/3_Settings.py`** — new "🔗 Integrate API credentials (private to
   this machine)" expander section, same layout as the existing Jira/Enhancio
   sections.

6. **`pages/1_Client_Setup.py`** — new "Integrate" section (same expander
   pattern as the existing Convertr/Enhancio sections): enable checkbox, SID
   text field, optional callback URL field, a dropdown per Integrate
   attribute (populated from the client's own reference leadfile headers —
   same "upload a sample file to populate the dropdown options" UX already
   used for Convertr/Enhancio's field mapping), and a small fixed-value
   editor (attribute name → constant value) for attributes that don't come
   from the leadfile at all.

7. **`pages/9_Integrate.py`** — new page, structurally mirroring
   `pages/7_Convertr.py`:
   - Client picker, filtered to `profile.integrate.enabled` clients only.
   - `st.file_uploader` for the leadfile.
   - Resolve `leadfile_field_mapping` (falls back to `profile.field_mapping`,
     same as Convertr/Enhancio) to find the leadfile's own email/name/company
     columns.
   - Build each row's `attributes` dict from `field_mapping` (leadfile
     column → Integrate attribute) merged with `fixed_field_values`.
   - Filter out already-uploaded emails (`integrate_sync.filter_already_uploaded`),
     reporting the skipped count.
   - Test mode: send exactly 1 lead first (reusing the existing
     `st.session_state`-gated "test mode" checkbox pattern from
     `pages/7_Convertr.py`), require it to succeed before enabling the
     "send the rest" button.
   - Send remaining leads one `submit_lead` call per row — a single lead's
     `IntegrateError` does not abort the batch (same partial-progress
     principle the recent audit applied to Enhancio's `import_leads`):
     accumulate `(row, error)` pairs, keep going.
   - On each lead's success, add its email to the session's "to save" set;
     save incrementally per lead (not only at the end of the whole batch) —
     same reasoning as the audit's Convertr/Enhancio incremental-save fix,
     so a later failure never loses an earlier success's dedup record.
   - Report: success count, and every failure's row + Integrate's own error
     message, in one `st.warning`/`st.dataframe` after the batch completes.

## Data flow

```
leadfile upload
   -> resolve leadfile_field_mapping (email/name/company columns)
   -> filter_already_uploaded (by email, against integrate_uploaded_emails)
   -> [test mode: 1 lead] -> submit_lead -> must succeed to unlock "send rest"
   -> for each remaining row:
        attributes = {integrate_attr: row[leadfile_col] for leadfile_col, integrate_attr in field_mapping}
                      | fixed_field_values
        submit_lead(sid, api_key, api_secret, attributes, callback_url)
        on success: save_uploaded_emails(client_name, {email})  # incremental
        on IntegrateError: record (row, error), continue
   -> st.success(f"{n} sent") + st.warning listing any failures
```

## Error handling

- Missing/blank API Key or Secret in Settings: page shows an error and
  `st.stop()`s before rendering the uploader, same as Convertr's missing
  `enterprise`/credentials check.
- Missing SID for the selected client: same — caught at Client Setup save
  time is nice-to-have, but the Integrate page itself must also guard
  against an enabled-but-blank SID rather than POST to a malformed URL.
- Any single lead's `IntegrateError` (bad field value, duplicate on
  Integrate's own side, network error via `requests`' own exceptions) is
  caught per-row, not batch-aborting — see "Send remaining leads" above.
- A non-JSON or unexpected-shape response body is treated as a hard error
  (never silently "success"), same principle as the recent Enhancio
  `_post` audit fix.

## Testing

- `tests/test_integrate_client.py` — `submit_lead` success parsing, error
  parsing (with and without a JSON body), non-2xx handling — same shape as
  `tests/test_enhancio_client.py`.
- `tests/test_integrate_sync.py` — `filter_already_uploaded` dedup logic,
  `load_uploaded_emails`/`save_uploaded_emails` round-trip — same shape as
  existing Convertr/Enhancio sync tests.
- `tests/test_integrate_page.py` — `AppTest`-based page tests: renders with
  no client enabled, uploads a file and sends a lead (mocked `submit_lead`),
  test-mode gating, per-lead failure doesn't abort the batch, dedup skips an
  already-uploaded email — same style as `tests/test_convertr_page.py`.
- `tests/test_client_setup_page.py` (existing file) — new tests for the
  Integrate section: enabling it, saving a SID, saving a field mapping.

## Open questions (explicitly not blocking this build)

- Whether the API Key/Secret is genuinely org-wide-shared or needs to be
  per-client — user will confirm with their Integrate admin; see "Out of
  scope" above for why the shared-credential default was chosen anyway.

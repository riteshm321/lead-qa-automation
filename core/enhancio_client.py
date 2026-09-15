import requests

# https://developer.enhancio.com/ -- Enhancio's Publisher APIs (Lead
# Management + Campaign groups). Every request after the token exchange
# carries "Authorization: Bearer <access_token>".
_BASE_URL = "https://api-pubnet.enhancio.com"

# Enhancio caps both the Lead Import and Lead Status APIs at 1000 items per
# request -- callers here pass however many leads/lead ids they have, and
# these two functions chunk internally instead of pushing that limit onto
# every caller.
_MAX_BATCH_SIZE = 1000


class EnhancioError(Exception):
    """Raised for any non-success response from an Enhancio API call --
    carries the parsed error body's message when Enhancio provided one."""


def _first_error_message(body: dict) -> str:
    errors = (body or {}).get("errors") or []
    if errors:
        first = errors[0]
        return str(first.get("message", first)) if isinstance(first, dict) else str(first)
    return ""


def _post(url: str, headers: dict, payload: dict | None, action: str) -> dict:
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    try:
        body = response.json()
    except ValueError:
        body = {}
    # Enhancio's envelope can report failure with errors present even on a
    # 200 (result is then omitted per its own docs), so both conditions are
    # checked, not just the HTTP status.
    if response.status_code != 200 or body.get("errors"):
        message = _first_error_message(body) or response.text[:300]
        raise EnhancioError(f"Enhancio returned {response.status_code} {action}: {message}")
    return body


def get_access_token(client_id: str) -> dict:
    """Exchanges the org's shared Connected App Client ID for an access
    token via Enhancio-Managed OAuth2 -- no client secret involved, Enhancio
    holds that server-side for this flow. Returns the full token response
    ({"access_token", "scope", "expires_in", "token_type"}).

    Enhancio's own docs (developer.enhancio.com) show this as a POST, but
    the live API returns 405 Method Not Allowed for POST and only accepts
    GET -- confirmed directly against api-pubnet.enhancio.com. The docs
    example is simply wrong for this endpoint.
    """
    url = f"{_BASE_URL}/user/company/public/external/oauth/token/{client_id}"
    response = requests.get(url, headers={"Content-Type": "application/json"}, timeout=30)
    if response.status_code != 200:
        raise EnhancioError(f"Enhancio token request returned {response.status_code}: {response.text[:300]}")
    return response.json()


def _auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}


def describe_fields(access_token: str, allocation_uid: str) -> list[dict]:
    """Returns this allocation's required lead fields and their allowed
    values ({"fieldLabel", "mandatory", "fieldValues"?} per field) via the
    Describe Fields API, so a caller can discover the exact field labels
    Enhancio expects for a campaign instead of guessing them.
    """
    url = f"{_BASE_URL}/lead-api/v1/describe"
    body = _post(url, _auth_headers(access_token), {"allocationUid": allocation_uid}, "fetching describe fields")
    return body.get("result") or []


def list_publisher_allocations(access_token: str, page: int = 1, size: int = 1000) -> list[dict]:
    """Lists this publisher account's allocations (campaigns) --
    {"campaignName", "uniqueId", "allocationStatus"} per allocation. Used by
    Client Setup's lookup helper so a client's allocationUid never has to be
    hunted down by hand in the Enhancio portal.
    """
    url = f"{_BASE_URL}/external/v1/allocation-details"
    body = _post(url, _auth_headers(access_token), {"page": page, "size": size}, "listing publisher allocations")
    return body.get("result") or []


def import_leads(access_token: str, allocation_uid: str, leads: list[dict]) -> list[dict]:
    """Submits leads to the Lead Import API for one allocation -- leads:
    [{Enhancio field label: value}], e.g. [{"First Name": "Joe", "Email
    Address": "j@x.com"}]. Returns the combined submittedLeads list
    ({"leadId", "status", "email"} per lead) across every batch, in the
    same order submitted.
    """
    submitted: list[dict] = []
    for start in range(0, len(leads), _MAX_BATCH_SIZE):
        chunk = leads[start:start + _MAX_BATCH_SIZE]
        url = f"{_BASE_URL}/lead-api/v1/import"
        body = _post(
            url, _auth_headers(access_token),
            {"leadList": chunk, "allocationUid": allocation_uid}, "importing leads",
        )
        submitted.extend((body.get("result") or {}).get("submittedLeads") or [])
    return submitted


def get_lead_status(access_token: str, lead_ids: list[str]) -> list[dict]:
    """Resolves previously-submitted leads' outcomes via the Lead Status API
    -- {"leadId", "status" ("Accepted"/"Rejected"/...), "email",
    "deliveryStatus"?, "rejectionReason"?, "comments"?} per lead id.
    """
    resolved: list[dict] = []
    for start in range(0, len(lead_ids), _MAX_BATCH_SIZE):
        chunk = lead_ids[start:start + _MAX_BATCH_SIZE]
        url = f"{_BASE_URL}/lead-api/v1/lead-status"
        body = _post(url, _auth_headers(access_token), {"leadIds": chunk}, "fetching lead status")
        resolved.extend((body.get("result") or {}).get("leadList") or [])
    return resolved

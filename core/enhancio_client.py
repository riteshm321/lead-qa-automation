import requests

# https://developer.enhancio.com/ -- Enhancio's Publisher APIs (Lead
# Management + Campaign groups). Every request after the token exchange
# carries "Authorization: Bearer <access_token>".
_BASE_URL = "https://api-pubnet.enhancio.com"

# Every lead-api/campaign route actually requires an "/external/" segment
# right after the host to reach the externally-consumable gateway route --
# Enhancio's own docs omit it entirely for the lead-api group (only the
# campaign group's examples happen to show it), and a request without it
# returns a bare, bodyless 403 as if it were a scope/permission problem.
# Confirmed by comparing against Madison Logic's own working internal
# integration (ML Console's lead delivery config), which uses
# ".../external/lead-api/v1/import" successfully with the SAME OAuth scopes
# this client requests -- the missing "/external/" was the entire problem,
# not a missing Campaign scope.
_LEAD_API_BASE = f"{_BASE_URL}/external/lead-api/v1"

# Enhancio caps both the Lead Import and Lead Status APIs at 1000 items per
# request -- callers here pass however many leads/lead ids they have, and
# these two functions chunk internally instead of pushing that limit onto
# every caller.
_MAX_BATCH_SIZE = 1000


class EnhancioError(Exception):
    """Raised for any non-success response from an Enhancio API call --
    carries the parsed error body's message when Enhancio provided one.

    partial_result, if set, carries whatever {"submitted"/"resolved",
    "errors"} import_leads/get_lead_status had already accumulated from
    EARLIER chunks before THIS chunk's request failed. A >1000-lead/id
    call is split into multiple chunk requests -- without this, a later
    chunk failing discarded every earlier chunk's real, already-accepted
    results, so leads Enhancio had genuinely accepted (with real lead
    IDs) were never returned to the caller at all, risking duplicate
    resubmission and lost tracking. Callers should use partial_result
    instead of assuming nothing at all succeeded."""

    def __init__(self, message: str, partial_result: dict | None = None):
        super().__init__(message)
        self.partial_result = partial_result


def _first_error_message(body: dict) -> str:
    errors = (body or {}).get("errors") or []
    if errors:
        first = errors[0]
        return str(first.get("message", first)) if isinstance(first, dict) else str(first)
    return ""


def _post(url: str, headers: dict, payload: dict | None, action: str, allow_partial: bool = False) -> dict:
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    try:
        body = response.json()
    except ValueError:
        # A 200 with a body that failed to parse as JSON (e.g. a proxy
        # error page, or a genuinely empty body) used to be silently
        # substituted with {} and treated exactly like a real, clean,
        # error-free response -- the caller had zero way to tell that
        # apart from an actually-successful empty result, risking a
        # confusing "nothing accepted, no errors" outcome and possible
        # duplicate resubmission on retry. Treat it as a failure, the
        # same as a non-200 status, instead of masking it as success.
        if response.status_code == 200:
            raise EnhancioError(
                f"Enhancio returned 200 {action} but the response body wasn't valid JSON: "
                f"{response.text[:300]}")
        body = {}
    # Enhancio's envelope can report a full failure with errors present
    # even on a 200 (result is then omitted per its own docs) -- but for
    # batch endpoints (Import Lead, Lead Status) a 200 can also legitimately
    # carry BOTH a real result (the leads that succeeded) AND per-lead
    # errors (the leads that didn't, e.g. duplicates) in the SAME response.
    # Callers that pass allow_partial=True keep that partial result instead
    # of having it discarded just because errors is also non-empty -- this
    # was silently dropping real accepted leads whenever a batch also had
    # any rejected ones. Only a response with no result at all (or a
    # non-200) is treated as a total failure.
    has_result = body.get("result") is not None
    if response.status_code != 200 or (body.get("errors") and not (allow_partial and has_result)):
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
    url = f"{_LEAD_API_BASE}/describe"
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


def import_leads(access_token: str, allocation_uid: str, leads: list[dict]) -> dict:
    """Submits leads to the Lead Import API for one allocation -- leads:
    [{Enhancio field label: value}], e.g. [{"First Name": "Joe", "Email
    Address": "j@x.com"}]. Returns {"submitted": [...], "errors": [...]}
    combined across every batch: submitted has one {"leadId", "status",
    "email"} entry per lead Enhancio actually accepted, in whatever order
    Enhancio returns them (NOT assumed to match the order/count of leads
    sent -- a batch can drop leads, e.g. duplicates, without saying which
    position they were at); errors has every raw per-batch error entry
    Enhancio reported, so a caller can show every distinct reason instead
    of just the first one.

    A single batch can legitimately contain both at once (e.g. 29 accepted
    + 131 duplicates in one call) -- that is not treated as a failure here,
    only surfaced as-is. See _post's allow_partial.
    """
    submitted: list[dict] = []
    errors: list = []
    for start in range(0, len(leads), _MAX_BATCH_SIZE):
        chunk = leads[start:start + _MAX_BATCH_SIZE]
        url = f"{_LEAD_API_BASE}/import"
        try:
            body = _post(
                url, _auth_headers(access_token),
                {"leadList": chunk, "allocationUid": allocation_uid}, "importing leads",
                allow_partial=True,
            )
        except EnhancioError as exc:
            # Preserve whatever earlier chunks already got accepted --
            # see EnhancioError.partial_result.
            exc.partial_result = {"submitted": submitted, "errors": errors}
            raise
        submitted.extend((body.get("result") or {}).get("submittedLeads") or [])
        errors.extend(body.get("errors") or [])
    return {"submitted": submitted, "errors": errors}


def get_lead_status(access_token: str, lead_ids: list[str]) -> list[dict]:
    """Resolves previously-submitted leads' outcomes via the Lead Status API
    -- {"leadId", "status" ("Accepted"/"Rejected"/...), "email",
    "deliveryStatus"?, "rejectionReason"?, "comments"?} per lead id.
    """
    resolved: list[dict] = []
    for start in range(0, len(lead_ids), _MAX_BATCH_SIZE):
        chunk = lead_ids[start:start + _MAX_BATCH_SIZE]
        url = f"{_LEAD_API_BASE}/lead-status"
        try:
            body = _post(
                url, _auth_headers(access_token), {"leadIds": chunk}, "fetching lead status",
                allow_partial=True,
            )
        except EnhancioError as exc:
            # Preserve whatever earlier chunks already resolved -- see
            # EnhancioError.partial_result.
            exc.partial_result = {"resolved": resolved}
            raise
        resolved.extend((body.get("result") or {}).get("leadList") or [])
    return resolved

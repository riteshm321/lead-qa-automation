import requests

# https://support.convertrmedia.com/hc/en-us/articles/4408625579921 --
# Publisher API v2.4. Every Publisher account has access to this by
# default (no per-campaign Admin API key needed, unlike the Campaign
# Webhook v2), authenticated with the account's own username/password.


class ConvertrError(Exception):
    """Raised for any non-success response from a Convertr API call --
    carries the parsed error body's message when Convertr provided one."""


def login(enterprise: str, username: str, password: str) -> dict:
    """Exchanges an account username/password for an access token via
    OAuth2's password grant. Returns the full token response
    ({"access_token", "refresh_token", "expires_in", ...}). The same
    token is used for every other call below.
    """
    url = f"https://{enterprise}.cvtr.io/api/login"
    response = requests.post(url, data={"username": username, "password": password}, timeout=30)
    if response.status_code != 200:
        raise ConvertrError(f"Convertr login returned {response.status_code}: {response.text[:300]}")
    return response.json()


def get_publisher_form_fields(enterprise: str, access_token: str, campaign_id: str) -> list[dict]:
    """Returns this campaign's forms and their field keys (e.g.
    "form[firstName]"), via the Publisher API -- lets a caller discover
    the exact field names a given campaign's form expects instead of
    guessing them.
    """
    url = f"https://{enterprise}.cvtr.io/api/v2.4/publisher/fields/{campaign_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code != 200:
        raise ConvertrError(f"Convertr returned {response.status_code} fetching form fields: {response.text[:300]}")
    return response.json()


def submit_lead_as_publisher(
    enterprise: str, access_token: str, publisher_id: str, campaign_id: str, form_id: str,
    form_data: dict[str, str], link_id: str = "",
) -> dict:
    """POSTs one lead via the Publisher API's Campaign Lead Endpoint.

    form_data: {Convertr form field name (without the "form[]" wrapper --
    this adds it): value}, e.g. {"firstName": "Joe", "email": "j@x.com"}.

    Raises ConvertrError for any non-success response, with Convertr's
    own error message included, since a failed lead post must never be
    silently swallowed.
    """
    url = f"https://{enterprise}.cvtr.io/api/v2.4/publisher/{publisher_id}/forms/{form_id}/campaign/{campaign_id}/leads"
    params = {"linkId": link_id} if link_id else {}
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {f"form[{field}]": value for field, value in form_data.items()}

    response = requests.post(url, params=params, headers=headers, data=payload, timeout=30)
    try:
        body = response.json()
    except ValueError:
        body = {}

    # The HTTP status is the authoritative success signal here -- the
    # response body's own success message/field naming isn't consistent
    # with what Convertr's docs show (observed: "Model was created
    # successfully" instead of the documented "Lead was created
    # successfully", with no reliable "status"/"code" field to check
    # instead), so a 201 alone is trusted rather than also requiring a
    # specific body shape.
    if response.status_code != 201:
        message = body.get("message") or response.text[:300]
        raise ConvertrError(f"Convertr returned {response.status_code}: {message}")
    return body


def get_lead_result(enterprise: str, access_token: str, publisher_id: str, lead_id: str) -> dict:
    """Resolves one previously-submitted lead's outcome via the Publisher
    API's per-lead result endpoint -- there is no bulk "list leads" call
    on this API, so each submitted lead must be polled individually by
    its own id.

    Returns {"status": "valid"} once Convertr has accepted the lead,
    {"status": "invalid", "reasons": [...], "lead_data": {...}} once
    rejected (with Convertr's own failed-job messages and the data it
    received), or {"status": "pending"} while still queued -- callers must
    poll a pending lead again later rather than treat it as decided.
    """
    url = f"https://{enterprise}.cvtr.io/api/v2.1/publisher/{publisher_id}/lead-result/{lead_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 202:
        return {"status": "pending"}
    if response.status_code != 200:
        raise ConvertrError(f"Convertr returned {response.status_code} fetching lead result: {response.text[:300]}")
    raw = response.text.strip()
    if not raw:
        return {"status": "valid"}
    try:
        body = response.json()
    except ValueError:
        # Non-JSON body -- treat the raw text itself as the reason rather
        # than crash trying to parse it.
        return {"status": "invalid", "reasons": [raw], "lead_data": {}}
    if not body:
        # A valid lead's body isn't always zero-length -- observed in
        # practice as the 2-character JSON string '""' (an empty string),
        # which parses to a falsy value here, same as a truly empty body.
        return {"status": "valid"}
    # A non-empty invalid-lead body isn't always the documented
    # {qaReasons, failedJobs, leadData} object either -- sometimes it's
    # just a plain JSON string message. Treat that string itself as the
    # reason rather than assuming dict shape and crashing on it.
    if not isinstance(body, dict):
        return {"status": "invalid", "reasons": [str(body)], "lead_data": {}}
    reasons = list(body.get("failedJobs") or [])
    if not reasons and body.get("qaReasons"):
        reasons = [body["qaReasons"]]
    return {"status": "invalid", "reasons": reasons, "lead_data": body.get("leadData") or {}}

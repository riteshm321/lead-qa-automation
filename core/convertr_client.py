import requests

# https://support.convertrmedia.com/hc/en-us/articles/21218688615453 --
# Campaign Webhook v2. Each campaign authenticates with its own Campaign
# API Key (Admin > Setup > Advanced within that campaign in Convertr),
# passed as a query param -- no OAuth token exchange needed for this path.


class ConvertrError(Exception):
    """Raised for any non-success response from a Convertr API call --
    carries the parsed error body's message when Convertr provided one."""


def _base_url(enterprise: str, campaign_id: str) -> str:
    return f"https://{enterprise}.cvtr.io/webhook/campaign/{campaign_id}"


def get_campaign_form_fields(enterprise: str, campaign_id: str, api_key: str) -> list[dict]:
    """Returns this campaign's forms and their field keys (e.g.
    "form[firstName]"), straight from Convertr -- lets a caller discover
    the exact field names a given campaign's form expects instead of
    guessing them.
    """
    url = f"https://{enterprise}.cvtr.io/webhook/campaign/v2/{campaign_id}/global-form/fields"
    response = requests.get(url, params={"apikey": api_key}, timeout=30)
    if response.status_code != 200:
        raise ConvertrError(f"Convertr returned {response.status_code} fetching form fields: {response.text[:300]}")
    return response.json()


def submit_lead(
    enterprise: str, campaign_id: str, global_form_id: str, api_key: str,
    form_data: dict[str, str], campaign_link_id: str = "", publisher_id: str = "",
) -> dict:
    """POSTs one lead to Convertr's Campaign Lead Post Endpoint.

    form_data: {Convertr form field name (without the "form[]" wrapper --
    this adds it): value}, e.g. {"firstName": "Joe", "email": "j@x.com"}.

    Raises ConvertrError for any non-201 response, with Convertr's own
    error message (e.g. "This form should not contain extra fields",
    "Access denied", "Campaign is inactive") included, since a failed
    lead post must never be silently swallowed.
    """
    url = f"{_base_url(enterprise, campaign_id)}/global-form/{global_form_id}/leads"
    params = {"apikey": api_key}
    if campaign_link_id:
        params["campaignLinkId"] = campaign_link_id
    if publisher_id:
        params["publisherId"] = publisher_id
    payload = {f"form[{field}]": value for field, value in form_data.items()}

    response = requests.post(url, params=params, data=payload, timeout=30)
    try:
        body = response.json()
    except ValueError:
        body = {}

    if response.status_code != 201 or body.get("code") != 201:
        message = body.get("message") or response.text[:300]
        raise ConvertrError(f"Convertr returned {response.status_code}: {message}")
    return body

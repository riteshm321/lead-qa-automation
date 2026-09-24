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

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

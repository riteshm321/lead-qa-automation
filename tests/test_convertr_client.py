from unittest.mock import patch, MagicMock

import pytest

from core.convertr_client import submit_lead, get_campaign_form_fields, ConvertrError


def test_submit_lead_posts_to_the_expected_url_with_form_wrapped_fields():
    mock_response = MagicMock(
        status_code=201, json=lambda: {"code": 201, "message": "Lead was created successfully", "data": 55907})
    with patch("core.convertr_client.requests.post", return_value=mock_response) as mock_post:
        result = submit_lead(
            "amazonbusiness", "44400", "75", "campaign-key-1",
            {"firstName": "Joe", "lastName": "Bloggs", "email": "j@x.com"},
        )

    args, kwargs = mock_post.call_args
    assert args[0] == "https://amazonbusiness.cvtr.io/webhook/campaign/44400/global-form/75/leads"
    assert kwargs["params"] == {"apikey": "campaign-key-1"}
    assert kwargs["data"] == {"form[firstName]": "Joe", "form[lastName]": "Bloggs", "form[email]": "j@x.com"}
    assert result["data"] == 55907


def test_submit_lead_includes_optional_link_and_publisher_ids_only_when_given():
    mock_response = MagicMock(status_code=201, json=lambda: {"code": 201, "message": "ok", "data": 1})
    with patch("core.convertr_client.requests.post", return_value=mock_response) as mock_post:
        submit_lead(
            "amazonbusiness", "44400", "75", "campaign-key-1", {"email": "j@x.com"},
            campaign_link_id="135", publisher_id="12",
        )

    _, kwargs = mock_post.call_args
    assert kwargs["params"] == {"apikey": "campaign-key-1", "campaignLinkId": "135", "publisherId": "12"}


def test_submit_lead_raises_convertr_error_with_the_response_message_on_failure():
    mock_response = MagicMock(
        status_code=401, json=lambda: {"code": 401, "message": "Access denied."}, text='{"code": 401}')
    with patch("core.convertr_client.requests.post", return_value=mock_response):
        with pytest.raises(ConvertrError, match="Access denied"):
            submit_lead("amazonbusiness", "44400", "75", "wrong-key", {"email": "j@x.com"})


def test_submit_lead_raises_convertr_error_when_code_201_but_status_mismatched():
    # Belt-and-suspenders check: both the HTTP status AND the body's own
    # "code" field must say success, in case they ever disagree.
    mock_response = MagicMock(status_code=200, json=lambda: {"code": 400, "message": "Validation failed"})
    with patch("core.convertr_client.requests.post", return_value=mock_response):
        with pytest.raises(ConvertrError, match="Validation failed"):
            submit_lead("amazonbusiness", "44400", "75", "campaign-key-1", {"email": "j@x.com"})


def test_get_campaign_form_fields_calls_the_v2_fields_endpoint():
    mock_response = MagicMock(
        status_code=200,
        json=lambda: [{"formName": "Form", "formId": 75, "fields": [{"key": "form[firstName]"}]}],
    )
    with patch("core.convertr_client.requests.get", return_value=mock_response) as mock_get:
        fields = get_campaign_form_fields("amazonbusiness", "44400", "campaign-key-1")

    args, kwargs = mock_get.call_args
    assert args[0] == "https://amazonbusiness.cvtr.io/webhook/campaign/v2/44400/global-form/fields"
    assert kwargs["params"] == {"apikey": "campaign-key-1"}
    assert fields[0]["formId"] == 75


def test_get_campaign_form_fields_raises_on_non_200():
    mock_response = MagicMock(status_code=404, text="Not Found")
    with patch("core.convertr_client.requests.get", return_value=mock_response):
        with pytest.raises(ConvertrError):
            get_campaign_form_fields("amazonbusiness", "999999", "campaign-key-1")

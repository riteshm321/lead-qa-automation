from unittest.mock import patch, MagicMock

import pytest

from core.convertr_client import (
    login, get_publisher_form_fields, submit_lead_as_publisher, get_lead_result, ConvertrError,
)


def test_login_posts_username_and_password_as_form_body():
    mock_response = MagicMock(
        status_code=200, json=lambda: {"access_token": "tok123", "expires_in": 3600})
    with patch("core.convertr_client.requests.post", return_value=mock_response) as mock_post:
        result = login("amazonbusiness", "me@x.com", "hunter2")

    args, kwargs = mock_post.call_args
    assert args[0] == "https://amazonbusiness.cvtr.io/api/login"
    assert kwargs["data"] == {"username": "me@x.com", "password": "hunter2"}
    assert result["access_token"] == "tok123"


def test_login_raises_on_bad_credentials():
    mock_response = MagicMock(status_code=400, text='{"message": "invalid_grant"}')
    with patch("core.convertr_client.requests.post", return_value=mock_response):
        with pytest.raises(ConvertrError):
            login("amazonbusiness", "me@x.com", "wrong")


def test_get_publisher_form_fields_calls_the_v2_4_publisher_endpoint():
    mock_response = MagicMock(
        status_code=200,
        json=lambda: [{"formName": "Form", "formId": 75, "fields": ["form[firstName]", "form[email]"]}],
    )
    with patch("core.convertr_client.requests.get", return_value=mock_response) as mock_get:
        fields = get_publisher_form_fields("amazonbusiness", "tok123", "44400")

    args, kwargs = mock_get.call_args
    assert args[0] == "https://amazonbusiness.cvtr.io/api/v2.4/publisher/fields/44400"
    assert kwargs["headers"] == {"Authorization": "Bearer tok123"}
    assert fields[0]["formId"] == 75


def test_get_publisher_form_fields_raises_on_non_200():
    mock_response = MagicMock(status_code=404, text="Not Found")
    with patch("core.convertr_client.requests.get", return_value=mock_response):
        with pytest.raises(ConvertrError):
            get_publisher_form_fields("amazonbusiness", "tok123", "999999")


def test_submit_lead_as_publisher_posts_to_the_expected_url_with_form_wrapped_fields():
    mock_response = MagicMock(
        status_code=201, json=lambda: {"data": 367086, "message": "Lead was created successfully", "status": 201})
    with patch("core.convertr_client.requests.post", return_value=mock_response) as mock_post:
        result = submit_lead_as_publisher(
            "amazonbusiness", "tok123", "11003", "44400", "75",
            {"firstName": "Joe", "lastName": "Bloggs", "email": "j@x.com"},
        )

    args, kwargs = mock_post.call_args
    assert args[0] == "https://amazonbusiness.cvtr.io/api/v2.4/publisher/11003/forms/75/campaign/44400/leads"
    assert kwargs["headers"] == {"Authorization": "Bearer tok123"}
    assert kwargs["data"] == {"form[firstName]": "Joe", "form[lastName]": "Bloggs", "form[email]": "j@x.com"}
    assert result["data"] == 367086


def test_submit_lead_as_publisher_includes_link_id_only_when_given():
    mock_response = MagicMock(status_code=201, json=lambda: {"data": 1, "message": "ok", "status": 201})
    with patch("core.convertr_client.requests.post", return_value=mock_response) as mock_post:
        submit_lead_as_publisher(
            "amazonbusiness", "tok123", "11003", "44400", "75", {"email": "j@x.com"}, link_id="135",
        )

    _, kwargs = mock_post.call_args
    assert kwargs["params"] == {"linkId": "135"}


def test_submit_lead_as_publisher_raises_convertr_error_with_the_response_message_on_failure():
    mock_response = MagicMock(
        status_code=401, json=lambda: {"code": 401, "message": "Access denied."}, text='{"code": 401}')
    with patch("core.convertr_client.requests.post", return_value=mock_response):
        with pytest.raises(ConvertrError, match="Access denied"):
            submit_lead_as_publisher("amazonbusiness", "tok123", "11003", "44400", "75", {"email": "j@x.com"})


def test_submit_lead_as_publisher_raises_on_non_201_http_status_even_with_a_message_body():
    mock_response = MagicMock(status_code=400, json=lambda: {"code": 400, "message": "Validation failed"})
    with patch("core.convertr_client.requests.post", return_value=mock_response):
        with pytest.raises(ConvertrError, match="Validation failed"):
            submit_lead_as_publisher("amazonbusiness", "tok123", "11003", "44400", "75", {"email": "j@x.com"})


def test_submit_lead_as_publisher_succeeds_on_201_regardless_of_the_body_shape():
    # Convertr's own success message doesn't reliably match what its docs
    # show ("Model was created successfully" observed vs. documented
    # "Lead was created successfully"), and there's no consistent
    # "status"/"code" field to double-check on success -- so a 201 HTTP
    # status alone must be trusted, not gated on a specific body shape.
    mock_response = MagicMock(
        status_code=201, json=lambda: {"data": 55907, "message": "Model was created successfully"})
    with patch("core.convertr_client.requests.post", return_value=mock_response):
        result = submit_lead_as_publisher("amazonbusiness", "tok123", "11003", "44400", "75", {"email": "j@x.com"})
    assert result["data"] == 55907


def test_get_lead_result_valid_lead_returns_empty_200():
    mock_response = MagicMock(status_code=200, text="")
    with patch("core.convertr_client.requests.get", return_value=mock_response) as mock_get:
        result = get_lead_result("amazonbusiness", "tok123", "11003", "367086")

    args, kwargs = mock_get.call_args
    assert args[0] == "https://amazonbusiness.cvtr.io/api/v2.1/publisher/11003/lead-result/367086"
    assert kwargs["headers"] == {"Authorization": "Bearer tok123"}
    assert result == {"status": "valid"}


def test_get_lead_result_pending_lead_returns_202():
    mock_response = MagicMock(status_code=202, text="The lead has not been processed yet.")
    with patch("core.convertr_client.requests.get", return_value=mock_response):
        result = get_lead_result("amazonbusiness", "tok123", "11003", "367086")
    assert result == {"status": "pending"}


def test_get_lead_result_invalid_lead_includes_reasons_and_lead_data():
    body = {
        "qaReasons": "",
        "failedJobs": ["No values found for field - industry (industry)"],
        "leadData": {"firstName": "Sarah", "email": "sarah@x.com"},
    }
    mock_response = MagicMock(status_code=200, text='{"has": "body"}', json=lambda: body)
    with patch("core.convertr_client.requests.get", return_value=mock_response):
        result = get_lead_result("amazonbusiness", "tok123", "11003", "367086")

    assert result["status"] == "invalid"
    assert result["reasons"] == ["No values found for field - industry (industry)"]
    assert result["lead_data"] == {"firstName": "Sarah", "email": "sarah@x.com"}


def test_get_lead_result_invalid_lead_falls_back_to_qa_reasons_when_no_failed_jobs():
    body = {"qaReasons": "Duplicate", "leadData": {}}
    mock_response = MagicMock(status_code=200, text='{"has": "body"}', json=lambda: body)
    with patch("core.convertr_client.requests.get", return_value=mock_response):
        result = get_lead_result("amazonbusiness", "tok123", "11003", "367086")
    assert result["reasons"] == ["Duplicate"]


def test_get_lead_result_raises_on_unexpected_status():
    mock_response = MagicMock(status_code=401, text="Access denied")
    with patch("core.convertr_client.requests.get", return_value=mock_response):
        with pytest.raises(ConvertrError):
            get_lead_result("amazonbusiness", "bad-token", "11003", "367086")

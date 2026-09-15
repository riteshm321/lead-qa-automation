from unittest.mock import patch, MagicMock

import pytest

from core.enhancio_client import (
    get_access_token, describe_fields, list_publisher_allocations,
    import_leads, get_lead_status, EnhancioError,
)


def test_get_access_token_gets_the_client_id_scoped_token_endpoint():
    # Enhancio's own docs show this as a POST, but the live API returns 405
    # for POST and only accepts GET -- confirmed directly against
    # api-pubnet.enhancio.com.
    mock_response = MagicMock(
        status_code=200,
        json=lambda: {"access_token": "tok123", "scope": "LEAD_WRITE", "expires_in": 36000, "token_type": "Bearer"},
    )
    with patch("core.enhancio_client.requests.get", return_value=mock_response) as mock_get:
        result = get_access_token("CID123")

    args, kwargs = mock_get.call_args
    assert args[0] == "https://api-pubnet.enhancio.com/user/company/public/external/oauth/token/CID123"
    assert kwargs["headers"] == {"Content-Type": "application/json"}
    assert result["access_token"] == "tok123"


def test_get_access_token_raises_on_non_200():
    mock_response = MagicMock(status_code=401, text="invalid client")
    with patch("core.enhancio_client.requests.get", return_value=mock_response):
        with pytest.raises(EnhancioError):
            get_access_token("bad-id")


def test_describe_fields_posts_allocation_uid_and_returns_result():
    mock_response = MagicMock(
        status_code=200,
        json=lambda: {"timestamp": "x", "success": True, "result": [{"fieldLabel": "First Name", "mandatory": "Y"}]},
    )
    with patch("core.enhancio_client.requests.post", return_value=mock_response) as mock_post:
        fields = describe_fields("tok123", "L-22256")

    args, kwargs = mock_post.call_args
    assert args[0] == "https://api-pubnet.enhancio.com/lead-api/v1/describe"
    assert kwargs["headers"]["Authorization"] == "Bearer tok123"
    assert kwargs["json"] == {"allocationUid": "L-22256"}
    assert fields == [{"fieldLabel": "First Name", "mandatory": "Y"}]


def test_list_publisher_allocations_calls_the_allocation_details_endpoint():
    mock_response = MagicMock(
        status_code=200,
        json=lambda: {"success": True, "total": 1,
                       "result": [{"campaignName": "Acme Q1", "uniqueId": "L-22256", "allocationStatus": "AC"}]},
    )
    with patch("core.enhancio_client.requests.post", return_value=mock_response) as mock_post:
        allocations = list_publisher_allocations("tok123")

    args, kwargs = mock_post.call_args
    assert args[0] == "https://api-pubnet.enhancio.com/external/v1/allocation-details"
    assert kwargs["json"] == {"page": 1, "size": 1000}
    assert allocations[0]["uniqueId"] == "L-22256"


def test_import_leads_posts_lead_list_and_allocation_uid():
    mock_response = MagicMock(
        status_code=200,
        json=lambda: {"success": True, "result": {"submittedLeads": [
            {"leadId": "abc123", "status": "Submitted", "email": "j@x.com"},
        ]}},
    )
    with patch("core.enhancio_client.requests.post", return_value=mock_response) as mock_post:
        submitted = import_leads("tok123", "L-22256", [{"First Name": "Joe", "Email Address": "j@x.com"}])

    args, kwargs = mock_post.call_args
    assert args[0] == "https://api-pubnet.enhancio.com/lead-api/v1/import"
    assert kwargs["json"] == {
        "leadList": [{"First Name": "Joe", "Email Address": "j@x.com"}], "allocationUid": "L-22256",
    }
    assert submitted == [{"leadId": "abc123", "status": "Submitted", "email": "j@x.com"}]


def test_import_leads_batches_in_chunks_of_1000():
    leads = [{"Email Address": f"{i}@x.com"} for i in range(1500)]
    mock_response = MagicMock(
        status_code=200, json=lambda: {"success": True, "result": {"submittedLeads": [{"leadId": "1", "status": "Submitted", "email": "x"}]}})
    with patch("core.enhancio_client.requests.post", return_value=mock_response) as mock_post:
        submitted = import_leads("tok123", "L-22256", leads)

    assert mock_post.call_count == 2
    first_call_leads = mock_post.call_args_list[0].kwargs["json"]["leadList"]
    second_call_leads = mock_post.call_args_list[1].kwargs["json"]["leadList"]
    assert len(first_call_leads) == 1000
    assert len(second_call_leads) == 500
    assert len(submitted) == 2  # one submittedLeads entry per batch, from the mocked response


def test_import_leads_raises_enhancio_error_when_response_carries_errors():
    mock_response = MagicMock(
        status_code=200,
        json=lambda: {"success": False, "errors": [{"message": "Campaign doesn't exist", "errorCode": 900}]},
    )
    with patch("core.enhancio_client.requests.post", return_value=mock_response):
        with pytest.raises(EnhancioError, match="Campaign doesn't exist"):
            import_leads("tok123", "bad-alloc", [{"Email Address": "j@x.com"}])


def test_import_leads_raises_on_non_200_http_status():
    mock_response = MagicMock(status_code=500, json=lambda: {}, text="Internal Server Error")
    with patch("core.enhancio_client.requests.post", return_value=mock_response):
        with pytest.raises(EnhancioError):
            import_leads("tok123", "L-22256", [{"Email Address": "j@x.com"}])


def test_get_lead_status_posts_lead_ids_and_returns_lead_list():
    mock_response = MagicMock(
        status_code=200,
        json=lambda: {"success": True, "result": {"leadList": [
            {"leadId": "abc123", "status": "Accepted", "email": "j@x.com"},
            {"leadId": "def456", "status": "Rejected", "email": "b@x.com",
             "deliveryStatus": "V-Failed", "rejectionReason": "Lead Duplicate"},
        ]}},
    )
    with patch("core.enhancio_client.requests.post", return_value=mock_response) as mock_post:
        results = get_lead_status("tok123", ["abc123", "def456"])

    args, kwargs = mock_post.call_args
    assert args[0] == "https://api-pubnet.enhancio.com/lead-api/v1/lead-status"
    assert kwargs["json"] == {"leadIds": ["abc123", "def456"]}
    assert results[1]["rejectionReason"] == "Lead Duplicate"


def test_get_lead_status_batches_in_chunks_of_1000():
    lead_ids = [str(i) for i in range(1200)]
    mock_response = MagicMock(
        status_code=200, json=lambda: {"success": True, "result": {"leadList": [{"leadId": "1", "status": "Accepted", "email": "x"}]}})
    with patch("core.enhancio_client.requests.post", return_value=mock_response) as mock_post:
        get_lead_status("tok123", lead_ids)

    assert mock_post.call_count == 2
    assert len(mock_post.call_args_list[0].kwargs["json"]["leadIds"]) == 1000
    assert len(mock_post.call_args_list[1].kwargs["json"]["leadIds"]) == 200

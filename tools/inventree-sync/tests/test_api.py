from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import Mock

import pytest
import requests

from inventree_sync.api import APIError, InvenTreeClient, _retry_delay
from inventree_sync.config import InvenTreeSettings
from inventree_sync.models import Parameter


def response(payload=None, status=200, headers=None):
    result = Mock(status_code=status, headers=headers or {})
    result.json.return_value = payload
    return result


def category(pk):
    return {"pk": pk, "name": f"Category {pk}", "parent": None}


@pytest.fixture
def transport(monkeypatch, runtime_token):
    session = Mock()
    monkeypatch.setattr(requests, "Session", Mock(return_value=session))
    sleep = Mock()
    monkeypatch.setattr("inventree_sync.api.time.sleep", sleep)
    with InvenTreeClient(InvenTreeSettings("https://inventree.example.com", retries=2)) as client:
        yield client, session, sleep
    session.close.assert_called_once()


def test_unpaginated(transport, runtime_token):
    client, session, _ = transport
    session.get.return_value = response([category(1)])
    assert [item.pk for item in client.iter_categories()] == [1]
    args, kwargs = session.get.call_args
    assert args[0] == "https://inventree.example.com/api/part/category/"
    assert kwargs["headers"]["Authorization"] == f"Token {runtime_token}"
    assert kwargs["verify"] is True
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == (10, 60)
    assert session.trust_env is False


def test_three_pages(transport):
    client, session, _ = transport
    session.get.side_effect = [
        response({"count": 3, "results": [category(1)], "next": "?offset=1"}),
        response({"count": 3, "results": [category(2)], "next": "/api/part/category/?offset=2"}),
        response({"count": 3, "results": [category(3)], "next": None}),
    ]
    assert [c.pk for c in client.iter_categories()] == [1, 2, 3]
    assert session.get.call_count == 3


@pytest.mark.parametrize("status", [401, 403, 400, 404, 301, 302, 307, 308, 501])
def test_immediate_http_failure(transport, status):
    client, session, sleep = transport
    session.get.return_value = response(status=status)
    with pytest.raises(APIError, match=f"HTTP {status}"):
        list(client.iter_categories())
    assert session.get.call_count == 1
    sleep.assert_not_called()
    session.get.return_value.close.assert_called_once()


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_safe_retry(transport, status):
    client, session, sleep = transport
    session.get.side_effect = [response(status=status, headers={"Retry-After": "2"}), response([])]
    assert list(client.iter_parts()) == []
    sleep.assert_called_once_with(2)
    assert session.get.call_count == 2


def test_retry_exhaustion(transport):
    client, session, sleep = transport
    session.get.return_value = response(status=503)
    with pytest.raises(APIError, match="503"):
        list(client.iter_parts())
    assert session.get.call_count == 3
    assert [c.args[0] for c in sleep.call_args_list] == [1, 2]


def test_retry_date_and_invalid_header():
    future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=10))
    assert 8 <= _retry_delay(future, 0) <= 10
    assert _retry_delay("bad", 2) == 4
    with pytest.raises(APIError, match="above 60"):
        _retry_delay("120", 0)


@pytest.mark.parametrize("exception", [requests.Timeout, requests.ConnectionError, requests.RequestException])
def test_transport_errors_do_not_echo_secrets(transport, runtime_token, exception):
    client, session, sleep = transport
    session.get.side_effect = exception(runtime_token)
    with pytest.raises(APIError) as error:
        list(client.iter_parts())
    assert runtime_token not in str(error.value)
    assert error.value.__suppress_context__
    sleep.assert_not_called()


def test_malformed_json(transport, runtime_token):
    client, session, _ = transport
    session.get.return_value = response()
    session.get.return_value.json.side_effect = ValueError(runtime_token)
    with pytest.raises(APIError, match="malformed JSON") as error:
        list(client.iter_parts())
    assert runtime_token not in str(error.value)


@pytest.mark.parametrize("payload", [None, "data", 1, {}, {"results": []}, {"results": {}, "next": None}, {"results": [], "next": 1}, {"results": [], "next": ""}, {"results": [], "next": "?offset=1"}, {"results": [], "next": None, "count": True}, {"results": [], "next": None, "count": 2}])
def test_malformed_pagination(transport, payload):
    client, session, _ = transport
    session.get.return_value = response(payload)
    with pytest.raises(APIError):
        list(client.iter_categories())


@pytest.mark.parametrize("next_url", ["https://evil.example/api/part/category/", "http://inventree.example.com/api/part/category/", "//evil.example/api/part/category/", "/accounts/login/", "/api/part/", "/api/../secret", "/api/%2e%2e/secret", "https://user:secret@inventree.example.com/api/part/category/", "https://inventree.example.com:444/api/part/category/", "?offset=1#fragment", "?offset=1\n", "https://inventree.example.com\\@evil.example/api/part/category/"])
def test_unsafe_next_never_requested(transport, next_url):
    client, session, _ = transport
    session.get.return_value = response({"results": [category(1)], "next": next_url})
    with pytest.raises(APIError, match="pagination URL"):
        list(client.iter_categories())
    assert session.get.call_count == 1


def test_pagination_cycle(transport):
    client, session, _ = transport
    session.get.side_effect = [response({"results": [category(1)], "next": "?offset=1"}), response({"results": [category(2)], "next": "/api/part/category/"})]
    with pytest.raises(APIError, match="cyclic"):
        list(client.iter_categories())
    assert session.get.call_count == 2


def test_duplicate_object(transport):
    client, session, _ = transport
    session.get.side_effect = [response({"results": [category(1)], "next": "?offset=1"}), response({"results": [category(1)], "next": None})]
    with pytest.raises(APIError, match="repeated object pk=1"):
        list(client.iter_categories())


def test_pagination_shape_change(transport):
    client, session, _ = transport
    session.get.side_effect = [response({"results": [category(1)], "next": "?offset=1"}), response([])]
    with pytest.raises(APIError, match="shape changed"):
        list(client.iter_categories())


def test_count_changes(transport):
    client, session, _ = transport
    session.get.side_effect = [response({"count": 2, "results": [category(1)], "next": "?offset=1"}), response({"count": 3, "results": [category(2)], "next": None})]
    with pytest.raises(APIError, match="count"):
        list(client.iter_categories())


def test_parameter_endpoint_and_adapter(transport, fixture_record):
    client, session, _ = transport
    session.get.return_value = response([fixture_record("parameter")])
    assert list(client.iter_part_parameters()) == [Parameter(40, 20, 30, "0603")]
    assert session.get.call_args.args[0].endswith("/api/parameter/?model_type=part.part")


def test_parameter_filter_cannot_disappear(transport, fixture_record):
    client, session, _ = transport
    session.get.return_value = response({"results": [fixture_record("parameter")], "next": "?offset=1"})
    with pytest.raises(APIError, match="pagination URL"):
        list(client.iter_part_parameters())
    assert session.get.call_count == 1


def test_templates_and_parts_are_typed(transport, fixture_record):
    client, session, _ = transport
    session.get.side_effect = [response([fixture_record("part")]), response([fixture_record("template")])]
    assert list(client.iter_parts())[0].ipn == "RES-10K-1%-0603"
    assert list(client.iter_parameter_templates())[0].name == "Package"
    assert session.get.call_args.args[0].endswith("/api/parameter/template/")


def test_deployment_subpath(monkeypatch, runtime_token):
    session = Mock()
    monkeypatch.setattr(requests, "Session", Mock(return_value=session))
    session.get.side_effect = [response({"results": [category(1)], "next": "https://inventree.example.com/tools/api/part/category/?offset=1"}), response({"results": [category(2)], "next": None})]
    with InvenTreeClient(InvenTreeSettings("https://inventree.example.com/tools/")) as client:
        assert len(list(client.iter_categories())) == 2
    assert session.get.call_args_list[0].args[0] == "https://inventree.example.com/tools/api/part/category/"


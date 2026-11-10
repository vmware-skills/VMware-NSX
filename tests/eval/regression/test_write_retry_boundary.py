"""A lost write response must not cause a second mutation; GET may recover.

MockTransport models the server receiving the request before the response is
lost. These are client contract tests, not positive appliance validation.
"""

from types import SimpleNamespace
import httpx
import pytest
from vmware_nsx.connection import NsxClient, NsxApiError


@pytest.fixture
def client(monkeypatch):
    from vmware_nsx import connection

    monkeypatch.setattr(connection.time, "sleep", lambda _: None)
    c = object.__new__(NsxClient)
    c._target = SimpleNamespace(host="appliance.invalid")
    c._target_name = "lab"
    c._headers = lambda: {"Authorization": "Bearer fixture-token"}
    return c


def _response(request, failure):
    if failure == "timeout":
        raise httpx.ReadTimeout("fixture secret must stay private", request=request)
    if failure == "write_error":
        raise httpx.WriteError("fixture secret must stay private", request=request)
    return httpx.Response(failure)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("failure", ["timeout", "write_error", 502, 503, 504])
def test_uncertain_write_is_not_replayed(client, method, failure):
    received = []

    def server(request):
        received.append(request)
        return _response(request, failure) if len(received) == 1 else httpx.Response(200, json={"ok": True})

    with httpx.Client(base_url="https://appliance.invalid", transport=httpx.MockTransport(server)) as http:
        client._client = http
        with pytest.raises(NsxApiError) as exc:
            client._request(method, "/mutation", json_data={"id": "fixture"}, retries=9)
    assert len(received) == 1, "a lost response was followed by another mutation"
    assert "fixture secret" not in str(exc.value)


@pytest.mark.parametrize("failure", ["timeout", "write_error", 502, 503, 504])
def test_read_still_recovers_once(client, failure):
    received = []

    def server(request):
        received.append(request)
        return _response(request, failure) if len(received) == 1 else httpx.Response(200, json={"ok": True})

    with httpx.Client(base_url="https://appliance.invalid", transport=httpx.MockTransport(server)) as http:
        client._client = http
        assert client._request("GET", "/inventory").json() == {"ok": True}
    assert len(received) == 2


def test_read_retry_budget_remains_bounded(client):
    received = []

    def server(request):
        received.append(request)
        return httpx.Response(503)

    with httpx.Client(base_url="https://appliance.invalid", transport=httpx.MockTransport(server)) as http:
        client._client = http
        with pytest.raises(NsxApiError):
            client._request("GET", "/inventory")
    assert len(received) == 2

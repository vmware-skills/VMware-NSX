"""A system proxy bypass must route only the configured origin directly."""

import urllib.request

import httpx
import pytest

from vmware_nsx import connection
from vmware_nsx.config import TargetConfig


@pytest.mark.parametrize("verify", [False, True])
def test_system_proxy_bypass_preserves_tls_options_and_origin_scope(monkeypatch, verify):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda host: host == "target.invalid")
    options, requests, transports = [], [], []

    def response(request):
        requests.append(request)
        return httpx.Response(200, headers={"x-xsrf-token": "test-xsrf"}, json={})

    def direct(**kwargs):
        options.append(kwargs)
        transport = httpx.MockTransport(response)
        transports.append(transport)
        return transport

    monkeypatch.setattr(connection.httpx, "HTTPTransport", direct)
    client = connection.NsxClient(
        TargetConfig(host="target.invalid", username="admin", verify_ssl=verify), "test-password"
    )
    try:
        pass
        assert client._client.get("/evidence").status_code == 200
        assert options == [{"verify": verify, "trust_env": True}]
        assert requests and any(r.method == "POST" for r in requests)
        # Check httpx's routing without sending anything to the unrelated host.
        assert client._client._transport_for_url(httpx.URL("https://other.invalid/")) is not transports[0]
    finally:
        client._client.close()


def test_non_bypassed_target_keeps_normal_proxy_routing(monkeypatch):
    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda host: False)
    monkeypatch.setattr(connection.NsxClient, "_create_session", lambda self: None)

    def unexpected(**kwargs):
        raise AssertionError("unexpected direct transport for a non-bypassed target")

    monkeypatch.setattr(connection.httpx, "HTTPTransport", unexpected)
    client = connection.NsxClient(
        TargetConfig(host="target.invalid", username="admin", verify_ssl=False), "test-password"
    )
    client._client.close()

"""A request error must not send the agent to ``vmware-nsx doctor``.

Same shape as VMware-Monitor 2.4.1 (real hardware, 2026-10-17): every MCP error
carried "Run 'vmware-nsx doctor' to verify connectivity." -- and every HTTP
error message the connection layer raised said "Run 'vmware-nsx doctor' to
check this target." -- also for an unknown target name, a rejected argument, a
404 on an id that does not exist, or a 400 the Manager answered with.
Connectivity is fine in all of those, doctor reports green, and the hint buries
the remedy the message already carries.

The doctor hint stays where doctor can tell the caller something: transport
failures, session creation, 401/403, 5xx, a body that was not JSON (a reverse
proxy answering HTML), and anything unplanned.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from vmware_nsx.config import ConfigError
from vmware_nsx.connection import NsxApiError, NsxClient
from vmware_nsx.mcp_server import _shared

REPO_ROOT = Path(__file__).resolve().parents[3]

REQUEST_ERRORS = [
    ValueError("Target 'x' not found. Available: lab."),
    ValueError("limit must be 1-1000"),
    NsxApiError("HTTP 404", status_code=404, method="GET", path="/policy/api/v1/infra/segments/x"),
    NsxApiError("HTTP 400", status_code=400, method="PATCH", path="/policy/api/v1/infra/segments/x"),
    NsxApiError("HTTP 409", status_code=409, method="PATCH", path="/policy/api/v1/infra/segments/x"),
]

DOCTOR_ERRORS = [
    NsxApiError("could not connect", method="GET", path="/policy/api/v1/infra"),
    NsxApiError("HTTP 400 on login", status_code=400, method="POST", path="/api/session/create"),
    NsxApiError("HTTP 401", status_code=401, method="GET", path="/policy/api/v1/infra"),
    NsxApiError("HTTP 403", status_code=403, method="GET", path="/policy/api/v1/infra"),
    NsxApiError("HTTP 500", status_code=500, method="GET", path="/policy/api/v1/infra"),
    NsxApiError("HTTP 503", status_code=503, method="GET", path="/policy/api/v1/infra"),
    ConnectionError("no X-XSRF-TOKEN"),
    TimeoutError("slow"),
    ConfigError("password missing"),
    json.JSONDecodeError("Expecting value", "<html>", 0),
    UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
    KeyError("results"),
    RuntimeError("?"),
]



def _not_doctor_first(hint: str, exc: BaseException, module) -> None:
    """A request error is not sent to doctor; a plain ValueError only conditionally.

    A generic ValueError may come from parsing the server's answer, so its hint
    must not claim connectivity is fine (review 2026-10-18); it offers doctor
    only if the message names no fix.
    """
    assert hint != module._DOCTOR_HINT
    if type(exc) is ValueError:
        assert hint == module._CHECK_MESSAGE_HINT

@pytest.mark.parametrize("exc", REQUEST_ERRORS, ids=repr)
def test_a_request_error_does_not_send_the_agent_to_doctor(exc) -> None:
    _not_doctor_first(_shared._hint_for(exc), exc, _shared)


@pytest.mark.parametrize("exc", DOCTOR_ERRORS, ids=repr)
def test_connectivity_parse_and_unplanned_errors_keep_the_doctor_hint(exc) -> None:
    assert _shared._hint_for(exc) == _shared._DOCTOR_HINT


# -- through a real tool ----------------------------------------------------


def test_an_unknown_target_through_a_tool_gets_no_doctor_hint() -> None:
    import vmware_nsx.mcp_server.server as srv

    failure = ValueError("Target 'x' not found. Available: lab.")
    with patch.object(srv, "_get_connection", side_effect=failure):
        result = srv.list_segments(target="x")
    assert "not found" in result["error"]
    assert result["hint"] == _shared._CHECK_MESSAGE_HINT


def test_a_transport_failure_through_a_tool_keeps_the_doctor_hint() -> None:
    import vmware_nsx.mcp_server.server as srv

    failure = NsxApiError("NSX Manager could not connect.", method="GET", path="/x")
    with patch.object(srv, "_get_connection", side_effect=failure):
        result = srv.list_segments(target="lab")
    assert result["hint"] == _shared._DOCTOR_HINT


def test_no_tool_module_hands_out_the_doctor_hint_unconditionally() -> None:
    """New tools must route through ``_hint_for``, not paste the constant."""
    tools = sorted((REPO_ROOT / "vmware_nsx" / "mcp_server" / "tools").glob("*.py"))
    assert tools, "no tool modules found"
    offenders = [p.name for p in tools if '"hint": _DOCTOR_HINT' in p.read_text(encoding="utf-8")]
    assert not offenders, offenders


# -- the connection layer's own message --------------------------------------


def _client(status: int) -> NsxClient:
    client = NsxClient.__new__(NsxClient)
    client._target = SimpleNamespace(host="nsx.example", port=443, username="admin", verify_ssl=True)
    client._password = "pw"
    client._username = "admin"
    client._base_url = "https://nsx.example:443"
    client._token = "tok"
    client._client = httpx.Client(
        base_url="https://nsx.example:443",
        transport=httpx.MockTransport(lambda request: httpx.Response(status)),
    )
    return client


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    monkeypatch.setattr("vmware_nsx.connection._RETRY_DELAY_SEC", 0.0)


@pytest.mark.parametrize("status", [400, 404, 409])
def test_a_4xx_message_does_not_name_doctor(status) -> None:
    with pytest.raises(NsxApiError) as info:
        _client(status).get("/policy/api/v1/infra/segments/x")
    assert "doctor" not in str(info.value)


@pytest.mark.parametrize("status", [403, 500])
def test_a_403_or_5xx_message_still_names_doctor(status) -> None:
    with pytest.raises(NsxApiError) as info:
        _client(status).get("/policy/api/v1/infra/segments/x", retries=0)
    assert "vmware-nsx doctor" in str(info.value)


def test_a_refused_delete_is_not_sent_to_doctor() -> None:
    """Review 2026-10-18: NSX-Security was fixed, NSX's delete tools were not."""
    from vmware_nsx.ops.delete_gate import DeleteRefusedError

    exc = DeleteRefusedError("Segment 'web' still has 3 ports attached.", {"blockers": ["x"]})
    out = _shared._delete_error(exc, "Run list_segments ..., or 'vmware-nsx doctor' to check.")
    assert out["hint"] == _shared._FIX_IN_MESSAGE_HINT
    assert out["blast_radius"] == {"blockers": ["x"]}


def test_a_failed_delete_call_keeps_its_specific_hint() -> None:
    exc = NsxApiError("NSX could not connect.", method="DELETE", path="/x")
    hint = "Run list_segments ..., or 'vmware-nsx doctor' to check."
    assert _shared._delete_error(exc, hint)["hint"] == hint

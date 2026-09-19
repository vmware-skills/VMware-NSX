"""A delete that failed must be audited as a failure, not just *read* as one.

Update 2026-09-19 (HLD §7 confirmation gate): the five deletes now return the
family envelope — ``{"action": "preview" | "deleted", "blast_radius"}`` or
``{"error", "hint"}`` — so ``@vmware_tool`` reads their failures without help
and ``report_tool_failure`` is gone from them. The history below is why that
matters, and the tests now pin the envelope and that no tool here returns a
bare string again.

``@vmware_tool`` records a call as failed when an exception reaches it, or when
the returned payload is a dict (or one-element list) carrying a truthy
``error`` key — the family's documented envelope. This skill's five delete
tools return a **string** instead, because a delete has nothing to return but a
sentence. A string is not sniffed, on purpose: a skill that hands back console
text can legitimately emit output beginning with "Error:" as data, and marking
that call failed would be the same lie in the opposite direction.

So a caught delete failure looked exactly like a success:

1. the audit row said ``status=ok`` for a delete that did not happen — in a
   family whose stated purpose is a trustworthy audit trail, an affirmatively
   wrong row is worse than a missing one;
2. the circuit breaker was told ``success=True``, so repeated failures against
   a sick manager could never trip it.

``report_tool_failure`` is the explicit signal for exactly this shape, and it
has to run *inside* the ``@vmware_tool`` call still in flight — which the
decorator order (``@mcp.tool`` → ``@vmware_tool`` → body) already guarantees.

The assertion is on the **audited status**, never on the returned string: the
string was always right, and reading it back would re-test the thing that never
broke.
"""

from __future__ import annotations

import typing
from unittest.mock import patch

import pytest

from vmware_nsx.connection import NsxApiError

# The five deletes, with minimal arguments, the ops function each delegates to,
# and the gate function that measures its blast radius first.
DELETES = [
    ("delete_segment", {"segment_id": "seg-x"}, "vmware_nsx.ops.segment_mgmt.delete_segment",
     "segment_delete_blast_radius"),
    ("delete_tier1_gateway", {"tier1_id": "t1-x"}, "vmware_nsx.ops.segment_mgmt.delete_tier1_gateway",
     "tier1_delete_blast_radius"),
    ("delete_nat_rule", {"tier1_id": "t1-x", "rule_id": "r-x"}, "vmware_nsx.ops.nat_route_mgmt.delete_nat_rule",
     "nat_rule_delete_blast_radius"),
    ("delete_static_route", {"tier1_id": "t1-x", "route_id": "r-x"},
     "vmware_nsx.ops.nat_route_mgmt.delete_static_route", "static_route_delete_blast_radius"),
    ("delete_ip_pool", {"pool_id": "pool-x"}, "vmware_nsx.ops.nat_route_mgmt.delete_ip_pool",
     "ip_pool_delete_blast_radius"),
]
_CLEAR = {"blockers": [], "unmeasured": []}


@pytest.fixture
def audited(monkeypatch):
    """Capture audit rows without touching ~/.vmware/audit.db."""
    rows: list[dict] = []

    class _Recorder:
        def log(self, **kw):
            rows.append(kw)

    monkeypatch.setattr("vmware_policy.guard.get_engine", lambda: _Recorder())
    return rows


def _status(rows: list[dict]) -> str:
    assert len(rows) == 1, f"expected exactly one audit row, got {len(rows)}"
    return rows[0]["status"]


@pytest.mark.parametrize(("tool_name", "kwargs", "ops_path", "_gate"), DELETES)
def test_failed_delete_is_audited_as_a_failure(audited, tool_name, kwargs, ops_path, _gate) -> None:
    import vmware_nsx.mcp_server.server as srv

    failure = NsxApiError("NSX Manager returned HTTP 404.", status_code=404)
    with patch.object(srv, "_get_connection", side_effect=failure):
        result = getattr(srv, tool_name)(**kwargs, confirm=True)

    assert "404" in result["error"]
    assert _status(audited) == "error"


@pytest.mark.parametrize(("tool_name", "kwargs", "ops_path", "gate"), DELETES)
def test_successful_delete_is_still_audited_ok(audited, tool_name, kwargs, ops_path, gate) -> None:
    """The other direction: the signal must not mark good calls failed.

    A guard that reported every call as a failure would pass the test above and
    corrupt the audit trail just as thoroughly, in the other direction.
    """
    import vmware_nsx.mcp_server.server as srv

    with patch.object(srv, "_get_connection", return_value=object()), patch(
        f"vmware_nsx.ops.delete_gate.{gate}", return_value=dict(_CLEAR)
    ), patch(ops_path, return_value={"deleted": True}) as ops:
        result = getattr(srv, tool_name)(**kwargs, confirm=True)

    ops.assert_called_once()
    assert result["action"] == "deleted" and "error" not in result
    assert _status(audited) == "ok"


def test_no_tool_returns_a_bare_string() -> None:
    """A ``-> str`` tool's failure is invisible to ``@vmware_tool``.

    It would be audited ``ok`` and reported to the circuit breaker as a
    success. The five deletes were the only ones and now return the envelope;
    a new string-returning tool would reintroduce the defect silently.
    """
    import vmware_nsx.mcp_server.server as srv

    checked = 0
    string_returning = set()
    for name in dir(srv):
        fn = getattr(srv, name)
        if not getattr(fn, "_is_vmware_tool", False):
            continue
        checked += 1
        hints = typing.get_type_hints(getattr(fn, "__wrapped__", fn))
        if hints.get("return") is str:
            string_returning.add(name)

    assert checked >= 30, f"only {checked} tools scanned — the scan is vacuous"
    assert not string_returning, (
        f"these tools return a bare string: {sorted(string_returning)}. @vmware_tool "
        "cannot see a failure in a string: return the {'error', 'hint'} envelope."
    )

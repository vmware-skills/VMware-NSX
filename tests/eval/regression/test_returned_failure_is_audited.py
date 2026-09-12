"""A delete that failed must be audited as a failure, not just *read* as one.

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

# The five tools whose failure path returns a string, with minimal arguments
# and the ops function each one delegates to.
STRING_RETURNING_DELETES = [
    ("delete_segment", {"segment_id": "seg-x"}, "vmware_nsx.ops.segment_mgmt.delete_segment"),
    ("delete_tier1_gateway", {"tier1_id": "t1-x"}, "vmware_nsx.ops.segment_mgmt.delete_tier1_gateway"),
    ("delete_nat_rule", {"tier1_id": "t1-x", "rule_id": "r-x"}, "vmware_nsx.ops.nat_route_mgmt.delete_nat_rule"),
    ("delete_static_route", {"tier1_id": "t1-x", "route_id": "r-x"}, "vmware_nsx.ops.nat_route_mgmt.delete_static_route"),
    ("delete_ip_pool", {"pool_id": "pool-x"}, "vmware_nsx.ops.nat_route_mgmt.delete_ip_pool"),
]


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


@pytest.mark.parametrize(("tool_name", "kwargs", "ops_path"), STRING_RETURNING_DELETES)
def test_failed_string_delete_is_audited_as_a_failure(audited, tool_name, kwargs, ops_path) -> None:
    import vmware_nsx.mcp_server.server as srv

    failure = NsxApiError("NSX Manager returned HTTP 404.", status_code=404)
    with patch.object(srv, "_get_connection", side_effect=failure):
        result = getattr(srv, tool_name)(**kwargs)

    assert isinstance(result, str) and result.startswith("Error:")
    assert _status(audited) == "error", (
        f"{tool_name} caught the failure and returned a string, so @vmware_tool "
        "saw an ordinary return — it must call report_tool_failure()"
    )


@pytest.mark.parametrize(("tool_name", "kwargs", "ops_path"), STRING_RETURNING_DELETES)
def test_successful_string_delete_is_still_audited_ok(audited, tool_name, kwargs, ops_path) -> None:
    """The other direction: the signal must not mark good calls failed.

    A guard that reported every call as a failure would pass the test above and
    corrupt the audit trail just as thoroughly, in the other direction.
    """
    import vmware_nsx.mcp_server.server as srv

    # Every ops delete returns {"deleted": True, ...} on success, and the Tier-1
    # wrapper only reports a delete the ops layer confirmed (a pre-flight may
    # refuse), so a bare MagicMock return is not a success there.
    with patch.object(srv, "_get_connection", return_value=object()), patch(
        ops_path, return_value={"deleted": True}
    ):
        result = getattr(srv, tool_name)(**kwargs)

    assert "deleted" in result and not result.startswith("Error:")
    assert _status(audited) == "ok"


def test_the_covered_list_matches_the_string_returning_tools() -> None:
    """The parametrised list must not drift from the code it guards.

    A new ``-> str`` tool added without a ``report_tool_failure`` call would
    reintroduce the defect silently, and a fixed list only guards the names
    someone remembered to add.
    """
    import vmware_nsx.mcp_server.server as srv

    string_returning = set()
    for name in dir(srv):
        fn = getattr(srv, name)
        if not getattr(fn, "_is_vmware_tool", False):
            continue
        hints = typing.get_type_hints(getattr(fn, "__wrapped__", fn))
        if hints.get("return") is str:
            string_returning.add(name)

    assert string_returning, "no string-returning tools found — the scan is vacuous"
    assert string_returning == {name for name, _, _ in STRING_RETURNING_DELETES}, (
        f"string-returning tools changed: {sorted(string_returning)}. Every one of "
        "them needs a report_tool_failure() call in its except block, and a row here."
    )

"""Every MCP write tool must land in this skill's own audit log, as the CLI's do.

This repo has two audit sinks and they answer different questions.
``~/.vmware/audit.db`` is the family's shared SQLite trail, written by
``@vmware_tool`` for both surfaces; that one was never broken here and
``test_returned_failure_is_audited.py`` covers it. ``~/.vmware-nsx/audit.log``
is this skill's own JSON-Lines log — the file ``README.md`` advertises as
holding "All operations", the file ``vmware-nsx`` writes on every CLI write via
``cli._audit.log``, and the file an operator on the box actually opens when
asked what changed on the NSX manager.

Nothing on the MCP surface ever wrote to it. So a segment deleted by an agent
was absent from the log a human's identical ``vmware-nsx segment delete`` had
just appeared in, and the sibling repo — whose MCP write tools call
``_audit.log`` in every tool body — had the property this one lacked. That is
CLAUDE.md 形态 #7 exactly: a family pattern present in one repo and missing in
the other.

The write set here is **derived** from the tools' own MCP annotations rather
than hand-listed, so a fourteenth write tool fails this suite until it audits
too. A test naming today's thirteen would stay green while the surface grew
past it. ``test_the_write_set_is_derived_not_inherited`` cross-checks that
derivation against an independent one (the verb the tool's name starts with),
so a write tool that mislabels itself ``readOnlyHint: True`` cannot slip out of
the set the fix and the test share.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from unittest.mock import MagicMock, patch

import pytest

from vmware_nsx.connection import NsxApiError
from vmware_nsx.mcp_server import server as srv

#: Value handed to every required parameter. It has to satisfy the ops layer's
#: ``_validate_id`` (alphanumerics, hyphens, underscores) or the tools would all
#: take their validation-error path and the success branch would go untested.
PROBE = "probe-id"

_PLACEHOLDER: dict[object, object] = {str: PROBE, int: 1, float: 1.0, bool: False}


def _tool_names(read_only: bool) -> frozenset[str]:
    """Tool names whose ``readOnlyHint`` annotation is ``not read_only``."""
    return frozenset(
        t.name
        for t in asyncio.run(srv.mcp.list_tools())
        if getattr(getattr(t, "annotations", None), "readOnlyHint", None) is read_only
    )


WRITE_TOOLS = _tool_names(read_only=False)
READ_TOOLS = _tool_names(read_only=True)

# 形态 #1: an empty derivation reads as "nothing to check" and reports green.
assert WRITE_TOOLS, "no write tools derived from the MCP annotations — this suite would check nothing"
assert READ_TOOLS, "no read tools derived from the MCP annotations — the control would check nothing"


def _minimal_args(fn) -> dict:
    """The parameters ``fn`` has no default for, filled with placeholders."""
    args = {}
    for name, param in inspect.signature(fn).parameters.items():
        if param.default is not inspect.Parameter.empty:
            continue
        args[name] = _PLACEHOLDER.get(param.annotation, PROBE)
    return args


@pytest.fixture
def audit_log(tmp_path, monkeypatch):
    """Redirect the skill audit log into tmp and read it back as dicts."""
    from vmware_nsx.mcp_server import _write_audit
    from vmware_nsx.notify.audit import AuditLogger

    path = tmp_path / "audit.log"
    monkeypatch.setattr(_write_audit, "_audit", AuditLogger(log_file=str(path)))

    def entries() -> list[dict]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    return entries


# ---------------------------------------------------------------------------
# The property
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(WRITE_TOOLS))
def test_every_mcp_write_tool_records_to_the_skill_audit_log(name, audit_log):
    """Calling the write tool leaves exactly one entry naming it and its subject."""
    fn = getattr(srv, name)
    with patch.object(srv, "_get_connection", return_value=MagicMock()):
        fn(**_minimal_args(fn))

    rows = [r for r in audit_log() if r["operation"] == name]
    assert len(rows) == 1, f"{name} wrote {len(rows)} entries to ~/.vmware-nsx/audit.log, expected 1"
    row = rows[0]
    assert row["resource"] == PROBE, f"{name} audited resource={row['resource']!r}, expected the id it acted on"
    assert row["target"] == "default", f"{name} audited target={row['target']!r} for an omitted target"
    assert row["skill"] == "nsx"
    assert row["result"] in {"ok", "error"}, f"{name} audited an unexpected result {row['result']!r}"


def test_the_registered_tool_and_the_module_attribute_are_one_object():
    """No split brain: the audited callable is the one both surfaces reach.

    ``server.py`` re-exports every tool into its own namespace, and tests call
    it there (``srv.delete_segment(...)``). If the audit wrapper were installed
    only on the FastMCP registry, that re-exported name would be the unaudited
    function and half the calls in this repo would bypass the fix.
    """
    for name in sorted(WRITE_TOOLS):
        assert srv.mcp._tool_manager._tools[name].fn is getattr(srv, name), (
            f"{name}: the registry and vmware_nsx.mcp_server.server disagree on which callable it is"
        )


def test_a_successful_write_is_recorded_as_ok(audit_log):
    with patch.object(srv, "_get_connection", return_value=MagicMock()), patch(
        "vmware_nsx.ops.segment_mgmt.create_segment", return_value={"id": "seg-1"}
    ):
        srv.create_segment("seg-1", "Seg One", "/infra/tz/x")
    rows = audit_log()
    assert [r["result"] for r in rows] == ["ok"]
    assert rows[0]["parameters"]["display_name"] == "Seg One"


def test_a_write_that_returns_an_error_envelope_is_recorded_as_error(audit_log):
    """The dict-returning writes catch and return ``{"error", "hint"}``.

    They never raise, so an audit that only noticed exceptions would file a
    create that did not happen as a success — the affirmatively-wrong row that
    is worse than a missing one.
    """
    with patch.object(srv, "_get_connection", return_value=MagicMock()), patch(
        "vmware_nsx.ops.segment_mgmt.create_segment", side_effect=NsxApiError("boom", status_code=400)
    ):
        result = srv.create_segment("seg-1", "Seg One", "/infra/tz/x")
    assert "error" in result
    assert [r["result"] for r in audit_log()] == ["error"]


def test_a_string_returning_delete_that_failed_is_recorded_as_error(audit_log):
    """The five deletes return a sentence, not an envelope.

    ``@vmware_tool`` deliberately does not sniff strings, which is why those
    tools call ``report_tool_failure``. This log has no such signal to read, so
    it reads the contract those tools document: a confirmation sentence, or one
    beginning "Error:".
    """
    with patch.object(srv, "_get_connection", return_value=MagicMock()), patch(
        "vmware_nsx.ops.segment_mgmt.delete_segment", side_effect=NsxApiError("nope", status_code=404)
    ):
        out = srv.delete_segment("seg-1")
    assert out.startswith("Error:")
    assert [r["result"] for r in audit_log()] == ["error"]


def test_a_string_returning_delete_that_succeeded_is_recorded_as_ok(audit_log):
    with patch.object(srv, "_get_connection", return_value=MagicMock()), patch(
        "vmware_nsx.ops.segment_mgmt.delete_segment", return_value={"deleted": True, "segment_id": "seg-1"}
    ):
        out = srv.delete_segment("seg-1")
    assert not out.startswith("Error:")
    assert [r["result"] for r in audit_log()] == ["ok"]


def test_the_audited_subject_is_the_object_never_the_manager():
    """``target`` names the NSX manager, not the thing that changed.

    ``_subject`` skips it, and no tool on today's surface takes ``target``
    first — so removing that guard changes nothing any tool call can observe,
    and the mutation survived the whole suite above. The last paging round hit
    the same shape and drew the same conclusion: a guard that only a future
    caller can exercise still needs an assertion that can fail, not an
    inherited one that cannot.
    """
    from vmware_nsx.mcp_server import _write_audit

    def target_first(target=None, pool_id=None):  # pragma: no cover - a signature, not a call
        ...

    signature = inspect.signature(target_first)
    subject = _write_audit._subject(signature, {"target": "nsx-dc2", "pool_id": "pool-9"})
    assert subject == "pool-9", f"audited the manager name {subject!r} as the changed object"


def test_the_declared_target_is_audited(audit_log):
    with patch.object(srv, "_get_connection", return_value=MagicMock()), patch(
        "vmware_nsx.ops.segment_mgmt.delete_segment", return_value={"deleted": True, "segment_id": "seg-1"}
    ):
        srv.delete_segment("seg-1", target="nsx-dc2")
    assert [r["target"] for r in audit_log()] == ["nsx-dc2"]


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------


def test_read_tools_write_no_audit_entry(audit_log):
    """A read must not start writing rows.

    An audit log that also records every list call is not a stricter audit log;
    it is one nobody reads, and the writes disappear into it.
    """
    for name in sorted(READ_TOOLS):
        fn = getattr(srv, name)
        with patch.object(srv, "_get_connection", return_value=MagicMock()):
            fn(**_minimal_args(fn))
    assert audit_log() == [], "a read-only tool wrote to the write audit log"


def test_the_write_set_is_derived_not_inherited():
    """Two independent derivations of "this tool writes" must agree.

    The fix and the parametrised test above both read ``readOnlyHint``, so a
    write tool that mislabelled itself read-only would be missing from both and
    the suite would never notice. The verb in the tool's name is an independent
    witness.
    """
    verbs = ("create_", "update_", "delete_", "configure_", "apply_", "remove_", "set_")
    by_name = frozenset(
        t.name for t in asyncio.run(srv.mcp.list_tools()) if t.name.startswith(verbs)
    )
    assert by_name == WRITE_TOOLS, (
        "the annotation-derived write set and the name-derived one disagree: "
        f"annotation-only={sorted(WRITE_TOOLS - by_name)}, name-only={sorted(by_name - WRITE_TOOLS)}"
    )


def test_a_broken_audit_sink_does_not_break_the_write(monkeypatch):
    """Audit failure degrades to a warning; it never fails the operation."""
    from vmware_nsx.mcp_server import _write_audit

    exploding = MagicMock()
    exploding.log.side_effect = RuntimeError("disk full")
    monkeypatch.setattr(_write_audit, "_audit", exploding)

    with patch.object(srv, "_get_connection", return_value=MagicMock()), patch(
        "vmware_nsx.ops.segment_mgmt.delete_segment", return_value={"deleted": True, "segment_id": "seg-1"}
    ):
        assert srv.delete_segment("seg-1") == "Segment 'seg-1' deleted."
    assert exploding.log.called

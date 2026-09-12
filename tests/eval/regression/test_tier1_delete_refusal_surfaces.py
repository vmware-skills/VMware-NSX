"""A Tier-1 delete that the pre-flight refused must not be reported as done.

The ops layer refuses — returns ``{"deleted": False, "error": ..., "<kind>_ids":
[...]}`` and makes no DELETE call — while anything still depends on the
gateway. Both wrappers threw that answer away: the MCP tool returned
"Tier-1 gateway '…' deleted." and the CLI printed a green "deleted", exited 0
and wrote ``result="ok"`` to the skill audit log. The refusal was correct and
nobody could see it; an operator would believe the gateway was gone.

The MCP tool keeps its documented string contract (all five deletes on this
surface return a sentence), so the refusal becomes an ``Error:`` sentence that
names the blocking ids, and ``report_tool_failure`` tells ``@vmware_tool`` the
call failed. Asserted on both audit sinks, because the returned text was never
the only thing that lied.

``--dry-run`` had the same gap one step earlier: it previewed a DELETE that the
real run would refuse. It now runs the (read-only) pre-flight and shows what
blocks.

Every case drives the real ops function through a fake client, so the tests
cannot pass on a refusal shape the ops layer does not actually produce.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from tests.eval.regression import _tier1_fake as f

_BLOCKED = {f.SEGMENTS: [{"id": "web-seg", "connectivity_path": f.GW}], f.IPSEC: [{"id": "vpn-1"}]}


@pytest.fixture
def policy_rows(monkeypatch):
    """Capture @vmware_tool's audit rows without touching ~/.vmware/audit.db."""
    rows: list[dict] = []

    class _Recorder:
        def log(self, **kw):
            rows.append(kw)

    monkeypatch.setattr("vmware_policy.guard.get_engine", lambda: _Recorder())
    return rows


@pytest.fixture
def skill_log(tmp_path, monkeypatch):
    """Redirect ~/.vmware-nsx/audit.log (both the MCP and CLI writers) into tmp."""
    from vmware_nsx import cli
    from vmware_nsx.cli import _base
    from vmware_nsx.mcp_server import _write_audit
    from vmware_nsx.notify.audit import AuditLogger

    path = tmp_path / "audit.log"
    sink = AuditLogger(log_file=str(path))
    for owner in (_write_audit, _base, cli):
        monkeypatch.setattr(owner, "_audit", sink)

    def entries() -> list[dict]:
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

    return entries


# ── MCP ──────────────────────────────────────────────────────────────────


def test_mcp_refusal_is_returned_not_reported_as_deleted(policy_rows, skill_log):
    import vmware_nsx.mcp_server.server as srv

    client = f.FakeNsx(collections=_BLOCKED)
    with patch.object(srv, "_get_connection", return_value=client):
        out = srv.delete_tier1_gateway(f.T1)

    assert out.startswith("Error:"), out
    assert "NOT deleted" in out
    assert "web-seg" in out and "vpn-1" in out, "the refusal must name what blocks"
    assert client.deleted == []
    assert [r["status"] for r in policy_rows] == ["error"], "vmware-policy audited the refusal as a success"
    assert [r["result"] for r in skill_log() if r["operation"] == "delete_tier1_gateway"] == ["error"]


def test_mcp_clean_delete_is_still_ok(policy_rows, skill_log):
    import vmware_nsx.mcp_server.server as srv

    client = f.FakeNsx()
    with patch.object(srv, "_get_connection", return_value=client):
        out = srv.delete_tier1_gateway(f.T1)

    assert out == f"Tier-1 gateway '{f.T1}' deleted."
    assert client.deleted[-1] == f.BASE
    assert [r["status"] for r in policy_rows] == ["ok"]
    assert [r["result"] for r in skill_log() if r["operation"] == "delete_tier1_gateway"] == ["ok"]


def test_mcp_only_claims_deleted_when_ops_says_so(policy_rows):
    """Unknown is not a verdict: anything but ``deleted is True`` is not a delete."""
    import vmware_nsx.mcp_server.server as srv

    with patch.object(srv, "_get_connection", return_value=f.FakeNsx()), patch(
        "vmware_nsx.ops.segment_mgmt.delete_tier1_gateway", return_value={"tier1_id": f.T1}
    ):
        out = srv.delete_tier1_gateway(f.T1)
    assert out.startswith("Error:")
    assert [r["status"] for r in policy_rows] == ["error"]


def test_mcp_description_no_longer_promises_a_cascade():
    import vmware_nsx.mcp_server.server as srv

    tool = next(t for t in asyncio.run(srv.mcp.list_tools()) if t.name == "delete_tier1_gateway")
    desc = " ".join(tool.description.split())  # docstring line breaks split phrases
    assert "removes attached segments" not in desc
    assert "refuses" in desc.lower()
    for kind in ("segment", "NAT", "static route", "VPN", "DNS forwarder", "load balancer"):
        assert kind in desc, f"the description does not say {kind!r} blocks the delete"


# ── CLI ──────────────────────────────────────────────────────────────────


def _cli(client, args):
    from vmware_nsx import cli

    with (
        patch.object(cli, "_get_connection", return_value=(client, None)),
        patch.object(cli, "_resolve_target", return_value="test-target"),
        patch.object(cli, "_double_confirm"),
    ):
        return CliRunner().invoke(cli.app, ["gateway", "delete-tier1", f.T1, *args])


def test_cli_refusal_prints_blockers_and_exits_non_zero(skill_log, policy_rows):
    client = f.FakeNsx(collections=_BLOCKED)
    result = _cli(client, [])

    assert result.exit_code != 0, result.output
    assert f"Tier-1 gateway '{f.T1}' deleted." not in result.output
    assert "NOT deleted" in result.output
    assert "web-seg" in result.output and "vpn-1" in result.output
    assert client.deleted == []
    rows = [r for r in skill_log() if r["operation"] == "delete_tier1_gateway"]
    assert [r["result"] for r in rows] == ["error"], "the skill audit log recorded a refused delete as ok"
    assert [r["status"] for r in policy_rows] == ["error"], "@guarded audited the refused delete as ok"


def test_cli_clean_delete_exits_zero(skill_log):
    client = f.FakeNsx()
    result = _cli(client, [])
    assert result.exit_code == 0, result.output
    assert "deleted" in result.output
    assert client.deleted[-1] == f.BASE
    assert [r["result"] for r in skill_log() if r["operation"] == "delete_tier1_gateway"] == ["ok"]


def test_cli_dry_run_shows_the_refusal_it_previews():
    client = f.FakeNsx(collections=_BLOCKED)
    result = _cli(client, ["--dry-run"])
    assert result.exit_code == 0, result.output
    assert "REFUSED" in result.output
    assert "web-seg" in result.output and "vpn-1" in result.output
    assert client.deleted == []


def test_cli_dry_run_on_a_clean_gateway_previews_both_deletes():
    client = f.FakeNsx()
    result = _cli(client, ["--dry-run"])
    assert result.exit_code == 0, result.output
    assert "REFUSED" not in result.output
    assert "locale-services/default" in result.output
    assert client.deleted == []
    assert f.IPSEC in client.reads, "the dry-run did not run the pre-flight"


def test_cli_dry_run_that_cannot_check_does_not_preview_a_delete():
    client = f.FakeNsx(fail={f.IPSEC: f.server_error(f.IPSEC)})
    result = _cli(client, ["--dry-run"])
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert client.deleted == []

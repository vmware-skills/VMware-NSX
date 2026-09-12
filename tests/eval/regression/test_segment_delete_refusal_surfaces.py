"""A segment delete that the port check refused must not be reported as done.

The twin of ``test_tier1_delete_refusal_surfaces.py``. ``delete_segment``
refuses — returns ``{"deleted": False, "error": ..., "port_ids": [...]}`` and
makes no DELETE call — while any port is attached. Both wrappers discarded that
answer: the MCP tool said "Segment '…' deleted." (audited ``ok``), and the CLI
warned about the ports, asked twice for confirmation, then printed a green
"deleted", exited 0 and wrote ``result="ok"``. Its MCP description even
promised the opposite of what happens: "WARNING: this disconnects all attached
VMs". ``--dry-run`` previewed a DELETE the real run would refuse.

Every case drives the real ops function through a fake client, so the tests
cannot pass on a refusal shape the ops layer does not actually produce.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from vmware_nsx.connection import NsxApiError

SEG = "seg-web"
SEG_PATH = f"/policy/api/v1/infra/segments/{SEG}"
PORTS = f"{SEG_PATH}/ports"


class FakeNsx:
    """Answers the three reads a segment delete makes; records every DELETE."""

    def __init__(self, ports: list[dict] | None = None, fail: dict[str, Exception] | None = None) -> None:
        self.ports = list(ports or [])
        self.fail = dict(fail or {})
        self.reads: list[str] = []
        self.deleted: list[str] = []

    def _read(self, path: str) -> None:
        self.reads.append(path)
        if path in self.fail:
            raise self.fail[path]

    def get(self, path: str, *a: Any, **k: Any) -> dict:
        self._read(path)
        if path == SEG_PATH:
            return {"id": SEG, "display_name": "web", "admin_state": "UP"}
        raise NsxApiError(f"GET {path} returned HTTP 404.", status_code=404, method="GET", path=path)

    def get_all(self, path: str, *a: Any, **k: Any) -> list[dict]:
        self._read(path)
        rows = self.ports if path == PORTS else []
        limit = k.get("limit")
        return rows[:limit] if limit else list(rows)

    def get_count(self, path: str, *a: Any, **k: Any) -> int | None:
        self._read(path)
        return len(self.ports) if path == PORTS else 0

    def delete(self, path: str) -> None:
        self.deleted.append(path)


_BUSY = [{"id": "vm-a-vnic0"}, {"id": "vm-b-vnic0"}]


@pytest.fixture
def policy_rows(monkeypatch):
    """Capture vmware-policy's audit rows without touching ~/.vmware/audit.db."""
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
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        return [r for r in rows if r["operation"] == "delete_segment"]

    return entries


# ── ops ──────────────────────────────────────────────────────────────────


def test_ops_refusal_names_the_ports_and_says_nothing_was_deleted():
    from vmware_nsx.ops.segment_mgmt import delete_segment

    out = delete_segment(FakeNsx(ports=_BUSY), SEG)
    assert out["deleted"] is False
    assert out["error"].startswith("Segment has 2 active port(s)")
    assert "vm-a-vnic0" in out["error"] and "Nothing was deleted" in out["error"]


def test_the_port_check_is_read_only():
    from vmware_nsx.ops.segment_mgmt import segment_delete_blockers

    client = FakeNsx(ports=_BUSY)
    assert segment_delete_blockers(client, SEG) == {"port_count": 2, "port_ids": ["vm-a-vnic0", "vm-b-vnic0"]}
    assert segment_delete_blockers(FakeNsx(), SEG) == {}
    assert client.deleted == []


# ── MCP ──────────────────────────────────────────────────────────────────


def test_mcp_refusal_is_returned_not_reported_as_deleted(policy_rows, skill_log):
    import vmware_nsx.mcp_server.server as srv

    client = FakeNsx(ports=_BUSY)
    with patch.object(srv, "_get_connection", return_value=client):
        out = srv.delete_segment(SEG)

    assert out.startswith("Error:"), out
    assert "NOT deleted" in out
    assert "vm-a-vnic0" in out and "vm-b-vnic0" in out, "the refusal must name the attached ports"
    assert client.deleted == []
    assert [r["status"] for r in policy_rows] == ["error"], "vmware-policy audited the refusal as a success"
    assert [r["result"] for r in skill_log()] == ["error"]


def test_mcp_clean_delete_is_still_ok(policy_rows, skill_log):
    import vmware_nsx.mcp_server.server as srv

    client = FakeNsx()
    with patch.object(srv, "_get_connection", return_value=client):
        out = srv.delete_segment(SEG)

    assert out == f"Segment '{SEG}' deleted."
    assert client.deleted == [SEG_PATH]
    assert [r["status"] for r in policy_rows] == ["ok"]
    assert [r["result"] for r in skill_log()] == ["ok"]


def test_mcp_only_claims_deleted_when_ops_says_so(policy_rows):
    import vmware_nsx.mcp_server.server as srv

    with patch.object(srv, "_get_connection", return_value=FakeNsx()), patch(
        "vmware_nsx.ops.segment_mgmt.delete_segment", return_value={"segment_id": SEG}
    ):
        out = srv.delete_segment(SEG)
    assert out.startswith("Error:")
    assert [r["status"] for r in policy_rows] == ["error"]


def test_mcp_description_no_longer_promises_to_disconnect_vms():
    import vmware_nsx.mcp_server.server as srv

    tool = next(t for t in asyncio.run(srv.mcp.list_tools()) if t.name == "delete_segment")
    desc = " ".join(tool.description.split())
    assert "disconnects all attached VMs" not in desc
    assert "refuses" in desc.lower() and "port" in desc


# ── CLI ──────────────────────────────────────────────────────────────────


def _cli(client, args):
    from vmware_nsx import cli

    with (
        patch.object(cli, "_get_connection", return_value=(client, None)),
        patch.object(cli, "_resolve_target", return_value="test-target"),
        patch.object(cli, "_double_confirm"),
    ):
        return CliRunner().invoke(cli.app, ["segment", "delete", SEG, *args])


def test_cli_refusal_prints_ports_and_exits_non_zero(skill_log, policy_rows):
    client = FakeNsx(ports=_BUSY)
    result = _cli(client, [])

    assert result.exit_code != 0, result.output
    assert f"Segment '{SEG}' deleted." not in result.output
    assert "NOT deleted" in result.output
    assert "vm-a-vnic0" in result.output and "vm-b-vnic0" in result.output
    assert client.deleted == []
    assert [r["result"] for r in skill_log()] == ["error"], "the skill audit log recorded a refused delete as ok"
    assert [r["status"] for r in policy_rows] == ["error"], "@guarded audited the refused delete as ok"


def test_cli_clean_delete_exits_zero(skill_log):
    client = FakeNsx()
    result = _cli(client, [])
    assert result.exit_code == 0, result.output
    assert f"Segment '{SEG}' deleted." in result.output
    assert client.deleted == [SEG_PATH]
    assert [r["result"] for r in skill_log()] == ["ok"]


def test_cli_dry_run_shows_the_refusal_it_previews():
    client = FakeNsx(ports=_BUSY)
    result = _cli(client, ["--dry-run"])
    assert result.exit_code == 0, result.output
    assert "REFUSED" in result.output
    assert "vm-a-vnic0" in result.output
    assert client.deleted == []


def test_cli_dry_run_on_an_empty_segment_previews_the_delete():
    client = FakeNsx()
    result = _cli(client, ["--dry-run"])
    assert result.exit_code == 0, result.output
    assert "REFUSED" not in result.output
    assert f"DELETE {SEG_PATH}" in result.output
    assert client.deleted == []

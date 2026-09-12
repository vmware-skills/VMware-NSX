"""A pool whose subnet failed is a failed create — and it must say so.

``create_ip_pool`` PUTs the pool, then each subnet, and records a subnet PUT
that fails in ``subnets_failed`` instead of raising (issue #8: report partial
state rather than hide it). The report existed; nobody acted on it:

* the CLI threw the result away, printed a green "IP pool '…' created.", wrote
  ``result="ok"`` and exited 0 — for a pool with no usable subnet (the CLI
  sends exactly one);
* the MCP tool returned the dict, but with no top-level ``error`` key, so
  vmware-policy and the skill log both audited ``ok``;
* each per-subnet ``error`` was ``str(exc)`` — raw exception text, which for an
  unplanned exception is the kind that carries host:port or a response body.

Maintainer decision (2026-09-11): a failed subnet IS a failure of the
operation. The result keeps ``created: True`` (the pool object exists — hiding
that would leave the user unaware of what to clean up) and gains a top-level
``error`` that says the pool was created, which subnets were not, and how to
clean up. The success result is unchanged, byte for byte.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from vmware_nsx.connection import NsxApiError
from vmware_nsx.ops.nat_route_mgmt import create_ip_pool

POOL = "pool-1"
POOL_PATH = f"/policy/api/v1/infra/ip-pools/{POOL}"
SUBNET0 = f"{POOL_PATH}/ip-subnets/{POOL}-subnet-0"
SUBNET = {"allocation_ranges": [{"start": "10.0.0.10", "end": "10.0.0.20"}], "cidr": "10.0.0.0/24"}
AUTHORED = NsxApiError(
    "NSX Manager returned HTTP 400. The request was rejected. Run 'vmware-nsx doctor' "
    "to check this target. (PUT /policy/api/v1/infra/ip-pools/pool-1/ip-subnets/pool-1-subnet-0)",
    status_code=400,
    method="PUT",
    path=SUBNET0,
)
LEAKY = RuntimeError("https://secret-host.corp:443/policy/api body={'token': 'abc123'}")


class FakeNsx:
    def __init__(self, fail: dict[str, Exception] | None = None) -> None:
        self.fail = dict(fail or {})
        self.puts: list[str] = []

    def put(self, path: str, body: dict[str, Any]) -> dict:
        self.puts.append(path)
        if path in self.fail:
            raise self.fail[path]
        return {"id": path.rsplit("/", 1)[-1]}


@pytest.fixture
def policy_rows(monkeypatch):
    rows: list[dict] = []

    class _Recorder:
        def log(self, **kw):
            rows.append(kw)

    monkeypatch.setattr("vmware_policy.guard.get_engine", lambda: _Recorder())
    return rows


@pytest.fixture
def skill_log(tmp_path, monkeypatch):
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
        return [r for r in rows if r["operation"] == "create_ip_pool"]

    return entries


# ── ops ──────────────────────────────────────────────────────────────────


def test_success_result_is_unchanged():
    out = create_ip_pool(FakeNsx(), POOL, display_name="P", subnets=[SUBNET])
    assert out == {
        "created": True,
        "pool_id": POOL,
        "subnets_created": [f"{POOL}-subnet-0"],
        "subnets_failed": [],
    }


def test_a_failed_subnet_is_a_top_level_error_that_says_the_pool_exists():
    out = create_ip_pool(FakeNsx(fail={SUBNET0: AUTHORED}), POOL, display_name="P", subnets=[SUBNET])
    assert out["created"] is True, "the pool object was created; the result must not hide it"
    assert out["subnets_created"] == []
    assert [s["subnet"] for s in out["subnets_failed"]] == [f"{POOL}-subnet-0"]
    err = out["error"]
    assert err, "a failed subnet must surface as a top-level error"
    assert f"IP pool '{POOL}' WAS created" in err
    assert f"{POOL}-subnet-0" in err
    assert "HTTP 400" in err, "the connection layer's authored reason should reach the user"
    assert "delete_ip_pool" in err and f"vmware-nsx ip-pool delete {POOL}" in err
    assert "create_ip_pool" in err and "vmware-nsx ip-pool create" in err


def test_unplanned_exception_text_is_never_quoted():
    out = create_ip_pool(FakeNsx(fail={SUBNET0: LEAKY}), POOL, display_name="P", subnets=[SUBNET])
    blob = json.dumps(out)
    assert "secret-host" not in blob and "abc123" not in blob
    assert out["subnets_failed"][0]["error"].startswith("RuntimeError")


def test_authored_errors_are_sanitized():
    dirty = NsxApiError("NSX Manager returned HTTP 400.\x1b[31m bad\x00 range", status_code=400)
    out = create_ip_pool(FakeNsx(fail={SUBNET0: dirty}), POOL, display_name="P", subnets=[SUBNET])
    assert "\x1b" not in out["subnets_failed"][0]["error"] and "\x00" not in out["error"]


def test_the_cleanup_it_names_really_exists():
    """形态 #6: the remedy names tools and commands — check them against the real surfaces."""
    import vmware_nsx.mcp_server.server as srv
    from vmware_nsx import cli

    err = create_ip_pool(FakeNsx(fail={SUBNET0: AUTHORED}), POOL, display_name="P", subnets=[SUBNET])["error"]
    tools = {t.name for t in asyncio.run(srv.mcp.list_tools())}
    named_tools = set(re.findall(r"\b(create_ip_pool|delete_ip_pool|\w+_ip_pool\w*)\b", err))
    assert named_tools and named_tools <= tools, f"names a tool that does not exist: {named_tools - tools}"
    for cmd in re.findall(r"vmware-nsx ip-pool (\w+)", err):
        result = CliRunner().invoke(cli.app, ["ip-pool", cmd, "--help"])
        assert result.exit_code == 0, f"'vmware-nsx ip-pool {cmd}' does not exist"


# ── MCP ──────────────────────────────────────────────────────────────────


def _mcp(client):
    import vmware_nsx.mcp_server.server as srv

    with patch.object(srv, "_get_connection", return_value=client):
        return srv.create_ip_pool(POOL, "P", "10.0.0.10", "10.0.0.20", "10.0.0.0/24")


def test_mcp_partial_failure_is_audited_as_error(policy_rows, skill_log):
    out = _mcp(FakeNsx(fail={SUBNET0: AUTHORED}))
    assert out["error"] and "WAS created" in out["error"]
    assert out["subnets_failed"], "the per-subnet detail must still be returned"
    assert [r["status"] for r in policy_rows] == ["error"], "vmware-policy audited a failed subnet as ok"
    assert [r["result"] for r in skill_log()] == ["error"]


def test_mcp_success_is_unchanged(policy_rows, skill_log):
    out = _mcp(FakeNsx())
    assert {k: v for k, v in out.items() if not k.startswith("_")} == {
        "created": True,
        "pool_id": POOL,
        "subnets_created": [f"{POOL}-subnet-0"],
        "subnets_failed": [],
    }
    assert [r["status"] for r in policy_rows] == ["ok"]
    assert [r["result"] for r in skill_log()] == ["ok"]


# ── CLI ──────────────────────────────────────────────────────────────────


def _cli(client):
    from vmware_nsx import cli

    with (
        patch.object(cli, "_get_connection", return_value=(client, None)),
        patch.object(cli, "_resolve_target", return_value="test-target"),
        patch.object(cli, "_double_confirm"),
    ):
        return CliRunner().invoke(cli.app, [
            "ip-pool", "create", POOL, "--name", "P",
            "--start", "10.0.0.10", "--end", "10.0.0.20", "--cidr", "10.0.0.0/24",
        ])


def test_cli_partial_failure_prints_the_error_and_exits_non_zero(skill_log, policy_rows):
    result = _cli(FakeNsx(fail={SUBNET0: AUTHORED}))
    assert result.exit_code == 1, result.output
    assert f"IP pool '{POOL}' created." not in result.output
    out = " ".join(result.output.split())
    assert "WAS created" in out and f"{POOL}-subnet-0" in out
    assert f"vmware-nsx ip-pool delete {POOL}" in out
    assert [r["result"] for r in skill_log()] == ["error"], "the skill audit log recorded a failed subnet as ok"
    assert [r["status"] for r in policy_rows] == ["error"]


def test_cli_prints_nsx_text_literally_not_as_markup():
    bracketed = NsxApiError("NSX Manager returned HTTP 400. [bold]range[/bold] overlaps.", status_code=400)
    result = _cli(FakeNsx(fail={SUBNET0: bracketed}))
    assert "[bold]range[/bold]" in result.output


def test_cli_success_output_is_unchanged(skill_log):
    result = _cli(FakeNsx())
    assert result.exit_code == 0, result.output
    assert result.output == f"IP pool '{POOL}' created.\n"
    assert [r["result"] for r in skill_log()] == ["ok"]

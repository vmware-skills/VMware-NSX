"""Regression evals for GitHub issues #8/#9/#10 (2026-06 NSX pass).

* #8 — create_ip_pool reports partial state on a mid-loop subnet failure
  instead of raising past the first error and leaving a half-built pool.
* #9 — delete_ip_pool exists in ops/CLI/MCP (docstring claimed "create/delete
  … IP pools" but no delete path existed). DELETE hits the right endpoint;
  the CLI dry-run previews without deleting.
* #10 — the three static-route MCP wrappers thread gateway_type to ops, so a
  tier0 call hits the Tier-0 path (server.py previously hardcoded tier-1).
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from vmware_nsx.connection import NsxApiError
from vmware_nsx.ops.nat_route_mgmt import (
    create_ip_pool,
    create_static_route,
    delete_ip_pool,
    delete_static_route,
)


# ── #8: create_ip_pool partial-state reporting ──────────────────────────


def test_create_ip_pool_reports_partial_state_on_subnet_failure() -> None:
    """A subnet PUT failing mid-loop yields a result naming the failed
    subnet, not an exception."""
    client = MagicMock(name="NsxClient")

    # First put = pool object (ok); second put = subnet 0 (ok); third = subnet 1 (boom).
    client.put.side_effect = [
        {"id": "pool-1"},          # pool object
        {"id": "pool-1-subnet-0"},  # subnet 0 ok
        # subnet 1 fails. An NsxApiError, because only the connection layer's
        # authored text reaches the result — raw text of any other exception is
        # reduced to its type (test_ip_pool_partial_failure.py).
        NsxApiError("NSX Manager returned HTTP 400. overlapping allocation range", status_code=400),
    ]

    subnets = [
        {"allocation_ranges": [{"start": "10.0.0.10", "end": "10.0.0.20"}], "cidr": "10.0.0.0/24"},
        {"allocation_ranges": [{"start": "10.0.1.10", "end": "10.0.1.20"}], "cidr": "10.0.1.0/24"},
    ]

    result = create_ip_pool(client, "pool-1", display_name="P", subnets=subnets)

    assert result["created"] is True
    assert result["pool_id"] == "pool-1"
    assert result["subnets_created"] == ["pool-1-subnet-0"]
    assert len(result["subnets_failed"]) == 1
    assert result["subnets_failed"][0]["subnet"] == "pool-1-subnet-1"
    assert "overlapping" in result["subnets_failed"][0]["error"]
    # A failed subnet is a failed create: top-level error, pool still reported.
    assert "WAS created, but 1 of 2 subnet(s) were not" in result["error"]
    assert "1 working subnet(s)" in result["error"]


def test_create_ip_pool_all_subnets_ok_reports_empty_failures() -> None:
    client = MagicMock(name="NsxClient")
    client.put.return_value = {"id": "x"}
    subnets = [
        {"allocation_ranges": [{"start": "10.0.0.10", "end": "10.0.0.20"}], "cidr": "10.0.0.0/24"},
    ]
    result = create_ip_pool(client, "pool-2", display_name="P", subnets=subnets)
    assert result["subnets_created"] == ["pool-2-subnet-0"]
    assert result["subnets_failed"] == []


# ── #9: delete_ip_pool ──────────────────────────────────────────────────


def test_delete_ip_pool_hits_correct_endpoint() -> None:
    client = MagicMock(name="NsxClient")
    result = delete_ip_pool(client, "pool-1")
    client.delete.assert_called_once_with("/policy/api/v1/infra/ip-pools/pool-1")
    assert result == {"deleted": True, "pool_id": "pool-1"}


def test_cli_ip_pool_delete_dry_run_does_not_delete() -> None:
    from typer.testing import CliRunner

    import vmware_nsx.cli as cli

    client = MagicMock(name="NsxClient")
    with patch.object(cli, "_get_connection", return_value=(client, None)):
        result = CliRunner().invoke(cli.app, ["ip-pool", "delete", "pool-1", "--dry-run"])
    assert result.exit_code == 0
    client.delete.assert_not_called()
    assert "pool-1" in result.output


def test_mcp_delete_ip_pool_calls_ops() -> None:
    import vmware_nsx.mcp_server.server as srv

    client = MagicMock(name="NsxClient")
    with (
        patch.object(srv, "_get_connection", return_value=client),
        patch(
            "vmware_nsx.ops.delete_gate.ip_pool_delete_blast_radius",
            return_value={"pool_id": "pool-1", "blockers": [], "unmeasured": []},
        ),
        patch(
            "vmware_nsx.ops.nat_route_mgmt.delete_ip_pool",
            return_value={"deleted": True, "pool_id": "pool-1"},
        ) as mock_delete,
    ):
        result = srv.delete_ip_pool("pool-1", confirm=True)
    mock_delete.assert_called_once()
    assert result["deleted"] == "pool-1"


# ── #10: static-route MCP wrappers thread gateway_type ───────────────────


def test_ops_static_route_tier0_hits_tier0_path() -> None:
    client = MagicMock(name="NsxClient")
    create_static_route(
        client, "gw-0", "route-1",
        network="10.0.0.0/8",
        next_hops=[{"ip_address": "192.168.1.1"}],
        gateway_type="tier0",
    )
    path = client.put.call_args[0][0]
    assert "/tier-0s/gw-0/" in path

    delete_static_route(client, "gw-0", "route-1", gateway_type="tier0")
    del_path = client.delete.call_args[0][0]
    assert "/tier-0s/gw-0/" in del_path


@pytest.mark.parametrize(
    ("tool_name", "kwargs", "expected_path_fragment"),
    [
        ("list_static_routes", {"tier1_id": "gw-0", "gateway_type": "tier0"}, "tier-0s"),
        (
            "create_static_route",
            {"tier1_id": "gw-0", "route_id": "r1", "network": "10.0.0.0/8",
             "next_hop": "192.168.1.1", "gateway_type": "tier0"},
            "tier-0s",
        ),
        ("delete_static_route", {"tier1_id": "gw-0", "route_id": "r1", "gateway_type": "tier0"}, "tier-0s"),
    ],
)
def test_mcp_static_route_wrappers_thread_tier0(tool_name, kwargs, expected_path_fragment) -> None:
    import vmware_nsx.mcp_server.server as srv

    client = MagicMock(name="NsxClient")
    client.put.return_value = {"id": "r1"}
    client.get_all.return_value = []
    with patch.object(srv, "_get_connection", return_value=client):
        getattr(srv, tool_name)(**kwargs)

    # Whichever verb the tool used, the Tier-0 resource must appear in the path.
    called_paths = [
        c.args[0]
        for c in (*client.put.call_args_list, *client.delete.call_args_list, *client.get_all.call_args_list)
        if c.args
    ]
    assert any(expected_path_fragment in p for p in called_paths), (
        f"{tool_name} did not route to {expected_path_fragment}: {called_paths}"
    )


def test_mcp_static_route_wrappers_default_tier1() -> None:
    import vmware_nsx.mcp_server.server as srv

    client = MagicMock(name="NsxClient")
    client.put.return_value = {"id": "r1"}
    with patch.object(srv, "_get_connection", return_value=client):
        srv.create_static_route("gw-1", "r1", "10.0.0.0/8", "192.168.1.1")
    assert "/tier-1s/gw-1/" in client.put.call_args[0][0]

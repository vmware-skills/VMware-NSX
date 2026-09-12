"""NSX-specific regression evals.

踩坑 #19/#34 family — MCP and CLI wrappers passed kwargs their ops
functions don't accept, so four tools failed with TypeError/ValueError on
EVERY invocation (errors swallowed into {"error", "hint"} payloads):

* create_tier1_gateway passed edge_cluster_path= / route_advertisement=
  (ops wants route_advertisement_types: list[str]; edge_cluster_path was
  unsupported until 2026-06-07)
* update_tier1_gateway passed route_advertisement= unconditionally —
  rejected by ops allowed_fields → ValueError on every call
* create_static_route passed next_hop=str (ops wants next_hops: list[dict])
* create_ip_pool passed start_ip/end_ip/cidr/gateway_ip (ops wants
  subnets: list[dict])

Found 2026-06-07 during the Glama TDQS description rewrite. These tests
invoke the real wrapper → real ops path with a mocked NSX client, so any
future signature drift between wrapper and ops fails here, not in prod.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _mock_client() -> MagicMock:
    client = MagicMock(name="NsxClient")
    client.put.return_value = {"id": "created"}
    client.patch.return_value = {"id": "patched"}
    return client


# ── MCP wrapper → ops signature compatibility ──────────────────────────


def test_mcp_create_tier1_gateway_kwargs_match_ops() -> None:
    client = _mock_client()
    with patch("vmware_nsx.mcp_server.server._get_connection", return_value=client):
        from vmware_nsx.mcp_server.server import create_tier1_gateway

        result = create_tier1_gateway(
            tier1_id="t1-regress",
            display_name="Regression GW",
            tier0_path="/infra/tier-0s/t0",
            edge_cluster_path="/infra/sites/default/enforcement-points/default/edge-clusters/ec1",
            route_advertisement="TIER1_CONNECTED, TIER1_NAT",
        )
    assert "error" not in result, f"wrapper→ops call failed: {result}"
    # gateway PUT + locale-service PUT for edge_cluster_path
    assert client.put.call_count == 2
    gw_body = client.put.call_args_list[0].args[1]
    assert gw_body["route_advertisement_types"] == ["TIER1_CONNECTED", "TIER1_NAT"]
    ls_path, ls_body = client.put.call_args_list[1].args
    assert ls_path.endswith("/locale-services/default")
    assert ls_body == {"edge_cluster_path": "/infra/sites/default/enforcement-points/default/edge-clusters/ec1"}


def test_mcp_update_tier1_gateway_filters_none_and_maps_ra() -> None:
    client = _mock_client()
    with patch("vmware_nsx.mcp_server.server._get_connection", return_value=client):
        from vmware_nsx.mcp_server.server import update_tier1_gateway

        result = update_tier1_gateway(
            tier1_id="t1-regress",
            route_advertisement="TIER1_STATIC_ROUTES",
        )
    assert "error" not in result, f"wrapper→ops call failed: {result}"
    body = client.patch.call_args.args[1]
    # None fields must NOT be PATCHed; key must be the ops-level name
    assert body == {"route_advertisement_types": ["TIER1_STATIC_ROUTES"]}


def test_mcp_create_static_route_builds_next_hops() -> None:
    client = _mock_client()
    with patch("vmware_nsx.mcp_server.server._get_connection", return_value=client):
        from vmware_nsx.mcp_server.server import create_static_route

        result = create_static_route(
            tier1_id="t1-regress",
            route_id="r1",
            network="10.0.0.0/8",
            next_hop="192.168.1.254",
        )
    assert "error" not in result, f"wrapper→ops call failed: {result}"
    body = client.put.call_args.args[1]
    assert body["next_hops"] == [{"ip_address": "192.168.1.254", "admin_distance": 1}]


def test_mcp_create_ip_pool_builds_subnets() -> None:
    client = _mock_client()
    with patch("vmware_nsx.mcp_server.server._get_connection", return_value=client):
        from vmware_nsx.mcp_server.server import create_ip_pool

        result = create_ip_pool(
            pool_id="pool-regress",
            display_name="Regression Pool",
            start_ip="192.168.1.10",
            end_ip="192.168.1.100",
            cidr="192.168.1.0/24",
            gateway_ip="192.168.1.1",
        )
    assert "error" not in result, f"wrapper→ops call failed: {result}"
    # pool PUT + one subnet PUT
    assert client.put.call_count == 2
    subnet_body = client.put.call_args_list[1].args[1]
    assert subnet_body["cidr"] == "192.168.1.0/24"
    assert subnet_body["allocation_ranges"] == [{"start": "192.168.1.10", "end": "192.168.1.100"}]
    assert subnet_body["gateway_ip"] == "192.168.1.1"


# ── CLI command → ops signature compatibility (same bug, same fix) ─────


@pytest.fixture()
def cli_env():
    client = _mock_client()
    import vmware_nsx.cli as cli

    with (
        patch.object(cli, "_get_connection", return_value=(client, None)),
        patch.object(cli, "_resolve_target", return_value="test-target"),
        patch.object(cli, "_double_confirm"),
        patch.object(cli, "_audit"),
    ):
        yield cli, client


def test_cli_gateway_create_tier1_kwargs_match_ops(cli_env) -> None:
    cli, client = cli_env
    cli.gateway_create_tier1(
        tier1_id="t1-cli",
        display_name="CLI GW",
        tier0_path="/infra/tier-0s/t0",
        edge_cluster_path=None,
        route_advertisement="TIER1_CONNECTED",
        target=None,
        config=None,
        dry_run=False,
    )
    body = client.put.call_args.args[1]
    assert body["route_advertisement_types"] == ["TIER1_CONNECTED"]


def test_cli_gateway_update_tier1_kwargs_match_ops(cli_env) -> None:
    cli, client = cli_env
    cli.gateway_update_tier1(
        tier1_id="t1-cli",
        display_name="Renamed",
        tier0_path=None,
        route_advertisement=None,
        target=None,
        config=None,
        dry_run=False,
    )
    body = client.patch.call_args.args[1]
    assert body == {"display_name": "Renamed"}


def test_cli_route_create_static_kwargs_match_ops(cli_env) -> None:
    cli, client = cli_env
    cli.route_create_static(
        tier1_id="t1-cli",
        route_id="r1",
        network="10.0.0.0/8",
        next_hop="192.168.1.254",
        target=None,
        config=None,
        dry_run=False,
    )
    body = client.put.call_args.args[1]
    assert body["next_hops"] == [{"ip_address": "192.168.1.254", "admin_distance": 1}]


def test_cli_ip_pool_create_kwargs_match_ops(cli_env) -> None:
    cli, client = cli_env
    cli.ip_pool_create(
        pool_id="pool-cli",
        display_name="CLI Pool",
        start_ip="10.0.0.10",
        end_ip="10.0.0.20",
        cidr="10.0.0.0/24",
        gateway_ip=None,
        target=None,
        config=None,
        dry_run=False,
    )
    subnet_body = client.put.call_args_list[1].args[1]
    assert subnet_body["allocation_ranges"] == [{"start": "10.0.0.10", "end": "10.0.0.20"}]
    assert "gateway_ip" not in subnet_body


# ── Response-shape conformance against NSX 4.2 SDK models ──────────────
#
# 2026-06-08 SDK audit: the read paths below parsed fields that do not
# exist on the official NSX 4.2 response models, silently returning ""/{}
# (sanitize/dict.get swallow the miss).  Each test feeds a mock client a
# response shaped exactly like the SDK model and asserts the ops layer
# extracts the real fields.  Verified against nsx-python-sdk /
# nsx-policy-python-sdk 4.2.0 model_client.py.


def test_transport_node_status_parses_sdk_fields() -> None:
    """TransportNodeStatus: tunnel_status/pnic_status are StatusCount structs;
    mgmt_connection_status is a plain string; node_deployment_state does not exist."""
    from vmware_nsx.ops.health import get_transport_node_status

    client = _mock_client()
    client.get.return_value = {
        "status": "DEGRADED",
        "node_uuid": "tn-1",
        "control_connection_status": {"status": "UP", "up_count": 1, "down_count": 0},
        "mgmt_connection_status": "UP",
        "tunnel_status": {
            "status": "DEGRADED",
            "up_count": 4,
            "down_count": 1,
            "degraded_count": 1,
            "bfd_status": {"bfd_admin_down_count": 0, "bfd_up_count": 4},
        },
        "pnic_status": {"status": "UP", "up_count": 2, "down_count": 0, "degraded_count": 0},
    }

    result = get_transport_node_status(client, "tn-1")

    assert "node_deployment_state" not in result, "field does not exist on TransportNodeStatus"
    assert result["mgmt_connection_status"] == "UP"
    assert result["control_connection_status"] == "UP"
    assert result["tunnel_status"]["status"] == "DEGRADED"
    assert result["tunnel_status"]["up_count"] == 4
    assert result["tunnel_status"]["down_count"] == 1
    assert result["tunnel_status"]["degraded_count"] == 1
    assert result["tunnel_status"]["bfd_status"] == {"bfd_admin_down_count": 0, "bfd_up_count": 4}
    assert result["pnic_status"]["up_count"] == 2
    assert result["pnic_status"]["status"] == "UP"


def test_edge_cluster_member_status_uses_resource_reference() -> None:
    """EdgeClusterMemberStatus.transport_node is a ResourceReference
    (target_id / target_display_name), not a flat transport_node_id."""
    from vmware_nsx.ops.health import get_edge_cluster_status

    client = _mock_client()
    client.get.return_value = {
        "edge_cluster_status": "UP",
        "member_status": [
            {
                "status": "UP",
                "transport_node": {"target_id": "tn-edge-1", "target_display_name": "edge-01"},
            }
        ],
    }

    result = get_edge_cluster_status(client, "ec-1")

    assert result["members"][0]["transport_node_id"] == "tn-edge-1"
    assert result["members"][0]["transport_node_name"] == "edge-01"
    assert result["members"][0]["status"] == "UP"


def test_manager_status_listen_ip_is_plain_string() -> None:
    """ManagementPlaneBaseNodeInfo.mgmt_cluster_listen_ip_address is a plain
    string — not a {ip_address: ...} dict, and not 'mgmt_cluster_listen_addr'."""
    from vmware_nsx.ops.health import get_manager_status

    client = _mock_client()
    client.get.return_value = {
        "cluster_id": "c-1",
        "detailed_cluster_status": {"overall_status": "STABLE", "groups": []},
        "control_cluster_status": {"status": "STABLE"},
        "mgmt_cluster_status": {
            "status": "STABLE",
            "online_nodes": [
                {"uuid": "u-1", "mgmt_cluster_listen_ip_address": "10.0.0.11"}
            ],
        },
    }

    result = get_manager_status(client)

    assert result["nodes"][0]["mgmt_cluster_listen_ip_address"] == "10.0.0.11"


def test_bgp_neighbor_config_and_status_fields() -> None:
    """BgpNeighborConfig uses hold_down_time/keep_alive_time (no 'r');
    PolicyBgpNeighborStatus prefix counters must not be labelled messages_*."""
    from vmware_nsx.ops.networking import get_bgp_neighbors

    client = _mock_client()

    def _get_all(path, params=None, max_items=1000, *, page_size=None, limit=None):
        if path.endswith("/locale-services"):
            return [{"id": "default"}]
        if path.endswith("/bgp/neighbors"):
            return [
                {
                    "id": "n1",
                    "display_name": "peer-1",
                    "neighbor_address": "192.0.2.1",
                    "remote_as_num": "65000",
                    "hold_down_time": 180,
                    "keep_alive_time": 60,
                }
            ]
        return []

    def _get(path, params=None):
        if path.endswith("/bgp/neighbors/status"):
            return {
                "results": [
                    {
                        "neighbor_address": "192.0.2.1",
                        "remote_as_number": "65000",
                        "connection_state": "ESTABLISHED",
                        "time_since_established": 1000,
                        "total_in_prefix_count": 12,
                        "total_out_prefix_count": 7,
                    }
                ]
            }
        return {"local_as_num": "65001", "enabled": True}

    client.get_all.side_effect = _get_all
    client.get.side_effect = _get

    result = get_bgp_neighbors(client, "t0")

    n = result["neighbors"][0]
    assert n["hold_down_time"] == 180
    assert n["keep_alive_time"] == 60
    s = result["neighbor_status"][0]
    assert s["in_prefix_count"] == 12
    assert s["out_prefix_count"] == 7
    assert "messages_received" not in s, "prefix counts are not message counts"
    assert "messages_sent" not in s


def test_bgp_neighbors_empty_locale_services_uses_same_keys() -> None:
    """The no-locale-services early return must use the same response keys
    ('neighbors'/'neighbor_status') as the normal path — the CLI reads
    data.get('neighbors') and agents key off the documented schema."""
    from vmware_nsx.ops.networking import get_bgp_neighbors

    client = _mock_client()
    client.get_all.return_value = []

    result = get_bgp_neighbors(client, "t0-empty")

    assert result["neighbors"] == []
    assert result["neighbor_status"] == []
    assert "bgp_neighbors" not in result
    assert "hint" in result


def test_logical_port_status_reports_honest_realized_state() -> None:
    """SegmentPortState has no 'state' field — report attachment presence,
    realized_bindings count, and transport_node_ids instead of a fake UP/DOWN."""
    from vmware_nsx.ops.troubleshoot import get_logical_port_status

    client = _mock_client()
    client.get_all.return_value = [
        {"id": "p1", "display_name": "port-1", "attachment": {"id": "att-1", "type": "VIF"}, "admin_state": "UP"}
    ]

    def _get(path, params=None):
        if path.endswith("/state"):
            return {
                "attachment": {"id": "att-1"},
                "realized_bindings": [{"binding": {"ip_address": "10.0.0.5"}}],
                "transport_node_ids": ["tn-1"],
            }
        return {"display_name": "seg-1", "admin_state": "UP"}

    client.get.side_effect = _get

    result = get_logical_port_status(client, "seg-1")

    port = result["ports"][0]
    rs = port["realized_state"]
    assert "state" not in rs, "SegmentPortState has no 'state' field"
    assert rs["attached"] is True
    assert rs["realized_bindings_count"] == 1
    assert rs["transport_node_ids"] == ["tn-1"]


def test_get_segment_port_for_vm_uses_fabric_vifs() -> None:
    """fabric VirtualMachine has no virtual_interfaces — VIFs come from
    GET /api/v1/fabric/vifs?owner_vm_id=..., matched on lport_attachment_id.

    Port resolution goes through the Policy search API, not a full scan."""
    from vmware_nsx.ops.troubleshoot import get_segment_port_for_vm

    client = _mock_client()

    def _get(path, params=None):
        if path == "/api/v1/fabric/virtual-machines":
            return {
                "results": [
                    {"external_id": "vm-ext-1", "host_id": "h1", "power_state": "VM_RUNNING"}
                ]
            }
        if path == "/api/v1/fabric/vifs":
            assert params == {"owner_vm_id": "vm-ext-1"}
            return {"results": [{"lport_attachment_id": "att-1", "external_id": "vif-1"}]}
        if path == "/policy/api/v1/search/query":
            assert params == {
                "query": "resource_type:SegmentPort AND attachment.id:att-1"
            }
            return {
                "results": [
                    {
                        "id": "p1",
                        "display_name": "port-1",
                        "path": "/infra/segments/seg-1/ports/p1",
                        "parent_display_name": "Seg 1",
                        "attachment": {"id": "att-1", "type": "PARENT"},
                    }
                ]
            }
        raise AssertionError(f"unexpected GET {path}")

    client.get.side_effect = _get
    # get_all must NOT be used on the search path — enumerating all
    # segments/ports is the O(N×M) scan this fix replaces.
    client.get_all.side_effect = AssertionError("must not scan: use search API")

    result = get_segment_port_for_vm(client, "web-01")

    assert result["found"] is True
    assert result["port_count"] == 1
    assert result["matched_ports"][0]["port_id"] == "p1"
    assert result["matched_ports"][0]["segment_id"] == "seg-1"
    assert result["matched_ports"][0]["segment_name"] == "Seg 1"
    client.get_all.assert_not_called()


def test_get_segment_port_for_vm_falls_back_to_scan_on_empty_search() -> None:
    """If the search API returns nothing/errors, fall back to the full
    segment/port scan so correctness is preserved."""
    from vmware_nsx.ops import troubleshoot
    from vmware_nsx.ops.troubleshoot import get_segment_port_for_vm

    client = _mock_client()

    def _get(path, params=None):
        if path == "/api/v1/fabric/virtual-machines":
            return {
                "results": [
                    {"external_id": "vm-ext-1", "host_id": "h1", "power_state": "VM_RUNNING"}
                ]
            }
        if path == "/api/v1/fabric/vifs":
            return {"results": [{"lport_attachment_id": "att-1", "external_id": "vif-1"}]}
        if path == "/policy/api/v1/search/query":
            return {"results": []}  # search yields nothing -> fall back
        raise AssertionError(f"unexpected GET {path}")

    def _get_all(path, params=None, max_items=1000, *, page_size=None, limit=None):
        if path == "/policy/api/v1/infra/segments":
            return [{"id": "seg-1", "display_name": "Seg 1"}]
        if path.endswith("/ports"):
            return [
                {"id": "p1", "display_name": "port-1", "attachment": {"id": "att-1", "type": "PARENT"}},
                {"id": "p2", "display_name": "port-2", "attachment": {"id": "other", "type": "PARENT"}},
            ]
        return []

    client.get.side_effect = _get
    client.get_all.side_effect = _get_all

    result = get_segment_port_for_vm(client, "web-01")

    assert result["found"] is True
    assert result["port_count"] == 1
    assert result["matched_ports"][0]["port_id"] == "p1"
    assert result["matched_ports"][0]["segment_id"] == "seg-1"
    # the fallback scan was actually exercised (now bounded via page_size/limit)
    client.get_all.assert_any_call(
        "/policy/api/v1/infra/segments",
        page_size=troubleshoot._MAX_SCAN_SEGMENTS,
        limit=troubleshoot._MAX_SCAN_SEGMENTS,
    )


def test_list_alarms_exact_severity_and_pagination() -> None:
    """severity is an EXACT match filter (not 'and above'), and the alarm
    list must follow pagination cursors via get_all."""
    from vmware_nsx.ops.health import list_alarms

    client = _mock_client()
    client.get_all.return_value = [
        {"id": "a1", "severity": "HIGH", "status": "OPEN", "feature_name": "f"}
    ]

    result = list_alarms(client, severity="HIGH")["items"]

    assert client.get_all.called, "must use the paginated helper (cursor loop)"
    path = client.get_all.call_args.args[0]
    params = client.get_all.call_args.kwargs.get("params") or (
        client.get_all.call_args.args[1] if len(client.get_all.call_args.args) > 1 else None
    )
    assert path == "/api/v1/alarms"
    assert params == {"severity": "HIGH"}
    assert result[0]["id"] == "a1"
    assert "and above" not in (list_alarms.__doc__ or ""), "severity filter is exact match"


def test_list_transport_zones_drops_nonexistent_host_switch_name() -> None:
    """PolicyTransportZone has no host_switch_name field."""
    from vmware_nsx.ops.inventory import list_transport_zones

    client = _mock_client()
    client.get_all.return_value = [
        {"id": "tz-1", "display_name": "overlay-tz", "tz_type": "OVERLAY_STANDARD"}
    ]

    result = list_transport_zones(client)["items"]

    assert result[0]["transport_type"] == "OVERLAY_STANDARD"
    assert "host_switch_name" not in result[0]


def test_list_transport_nodes_node_type_from_deployment_info() -> None:
    """node_type must come from node_deployment_info.resource_type
    (HostNode/EdgeNode); top-level resource_type is always 'TransportNode'."""
    from vmware_nsx.ops.inventory import list_transport_nodes

    client = _mock_client()
    client.get_all.return_value = [
        {
            "id": "tn-1",
            "display_name": "esx-01",
            "resource_type": "TransportNode",
            "node_deployment_info": {"resource_type": "HostNode"},
        }
    ]

    result = list_transport_nodes(client)["items"]

    assert result[0]["node_type"] == "HostNode"


def test_reflexive_nat_rule_requires_translated_network() -> None:
    """REFLEXIVE NAT also requires translated_network (NSX API rejects it otherwise)."""
    from vmware_nsx.ops.nat_route_mgmt import create_nat_rule

    client = _mock_client()
    with pytest.raises(ValueError, match="translated_network"):
        create_nat_rule(
            client, "t1", "r1", action="REFLEXIVE", source_network="10.0.0.0/24"
        )
    client.put.assert_not_called()


def test_delete_tier1_gateway_removes_default_locale_service_first() -> None:
    """Policy API refuses deleting a Tier-1 with children; the default
    locale-service (possibly created by create_tier1_gateway) goes first,
    ignoring 404 when absent."""
    from vmware_nsx.connection import NsxApiError
    from vmware_nsx.ops.segment_mgmt import delete_tier1_gateway

    # The pre-flight reads the DNS forwarder with client.get; 404 = none. (A bare
    # MagicMock return would read as "a forwarder is configured" and refuse.)
    no_forwarder = NsxApiError("404", status_code=404, method="GET", path="/dns-forwarder")

    # Case 1: locale-service exists — deleted first, then the gateway.
    client = _mock_client()
    client.get.side_effect = no_forwarder
    result = delete_tier1_gateway(client, "t1-del")
    paths = [c.args[0] for c in client.delete.call_args_list]
    assert paths == [
        "/policy/api/v1/infra/tier-1s/t1-del/locale-services/default",
        "/policy/api/v1/infra/tier-1s/t1-del",
    ]
    assert result["deleted"] is True

    # Case 2: locale-service absent (404) — ignored, gateway still deleted.
    # Since the central _request() translation, the connection layer raises
    # NsxApiError (not httpx.HTTPStatusError) for HTTP error statuses.
    client = _mock_client()
    client.get.side_effect = no_forwarder
    err = NsxApiError("404", status_code=404, method="DELETE", path="/x")
    client.delete.side_effect = [err, None]
    result = delete_tier1_gateway(client, "t1-del")
    assert result["deleted"] is True
    assert client.delete.call_count == 2


# ── 2026-06-08 audit follow-ups: two more CLI→ops mismatches ───────────


def test_cli_configure_tier0_bgp_builds_bgp_config(cli_env) -> None:
    """CLI passed local_as=/neighbor_address=/... kwargs that ops never
    accepted (ops signature: client, tier0_id, locale_service_id,
    bgp_config dict) — TypeError on every invocation since release."""
    cli, client = cli_env
    cli.gateway_configure_tier0_bgp(
        tier0_id="t0-cli",
        local_as=65001,
        enabled=True,
        ecmp=True,
        inter_sr_ibgp=True,
        locale_service_id="default",
        target=None,
        config=None,
        dry_run=False,
    )
    body = client.patch.call_args.args[1]
    assert body["local_as_num"] == "65001"  # ops requires string AS number
    assert body["enabled"] is True and body["ecmp"] is True


def test_cli_list_static_routes_renders_next_hop_dicts(cli_env) -> None:
    """CLI joined next_hops dicts as strings → TypeError whenever a route
    had hops. Render must extract ip_address from each dict."""
    cli, client = cli_env
    client.get_all.return_value = [
        {
            "id": "r1",
            "display_name": "r1",
            "network": "10.0.0.0/8",
            "next_hops": [{"ip_address": "192.168.1.1", "admin_distance": 1}],
        }
    ]
    # must not raise
    cli.networking_list_static_routes(tier1_id="t1-cli", target=None, config=None)

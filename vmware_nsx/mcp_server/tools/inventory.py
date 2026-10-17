"""READ-ONLY inventory tools: segments, gateways, transport zones/nodes, edge clusters."""

from typing import Optional

from vmware_policy import vmware_tool

from vmware_nsx.mcp_server import server
from vmware_nsx.mcp_server._shared import _hint_for, _safe_error, mcp


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def list_segments(
    target: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """[READ] List all NSX network segments with type, subnet, admin state, and port count.

    Returns the result envelope: rows under `items`, plus `returned`, `limit`,
    `total` (the collection's result_count, null when the API omits it),
    `truncated` and `hint`. Check `truncated` before calling this the complete
    set — when true, more rows exist. Every list tool here returns that shape.

    Page it: `limit` is the page size (1-1000, default 50; 0 or negative is
    rejected), `offset` is how many rows to skip, and the response carries
    `next_offset` — pass that back as `offset` and stop when it is null. Do not
    loop on `truncated`: that says this page is not the whole collection, so it
    stays true on the last page of a walk.

    Use this first to resolve a segment_id, then get_segment for its ports and
    linked gateway, or get_logical_port_status for realized state. Distributed
    firewall rules are not here — use vmware-nsx-security.

    Args:
        target: NSX Manager target from config (default if omitted).
        limit: Page size, 1-1000 (default 50).
        offset: Rows to skip; pass the previous response's `next_offset`.
    """
    try:
        from vmware_nsx.ops.inventory import list_segments as _list_segments

        client = server._get_connection(target)
        return _list_segments(client, limit=limit, offset=offset)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def get_segment(segment_id: str, target: Optional[str] = None) -> dict:
    """[READ] Get full details for one network segment, including its attached ports.

    Use after list_segments to inspect one segment. Returns one dict (not the
    list envelope): id, display_name, type, admin_state, subnets,
    transport_zone_path, connectivity_path (linked gateway), vlan_ids,
    port_count, and the first 50 ports only. A segment with attached ports
    cannot be deleted — check port_count before calling delete_segment. For
    per-port realized state use get_logical_port_status; to change the segment
    use update_segment.

    Args:
        segment_id: Segment ID — final component of /infra/segments/<id>, as
            returned by list_segments.
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.inventory import get_segment as _get_segment

        client = server._get_connection(target)
        return _get_segment(client, segment_id)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def list_tier0_gateways(
    target: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """[READ] List all Tier-0 gateways with HA mode and transit subnets.

    Returns the result envelope; check `truncated` before calling it complete.
    Page it: `limit` is the page size (1-1000, default 50; 0 or negative is
    rejected), `offset` is how many rows to skip, and the response carries
    `next_offset` — pass that back as `offset` and stop when it is null. Do not
    loop on `truncated`: that says this page is not the whole collection, so it
    stays true on the last page of a walk.

    Use this first to resolve a tier0_id, then get_tier0_gateway for HA detail
    and the tier0_path that create_tier1_gateway needs, or get_bgp_neighbors for
    peering state. Tier-0s are not created by this skill — only Tier-1s are.

    Args:
        target: NSX Manager target from config (default if omitted).
        limit: Page size, 1-1000 (default 50).
        offset: Rows to skip; pass the previous response's `next_offset`.
    """
    try:
        from vmware_nsx.ops.inventory import list_tier0_gateways as _list_tier0s

        client = server._get_connection(target)
        return _list_tier0s(client, limit=limit, offset=offset)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def get_tier0_gateway(tier0_id: str, target: Optional[str] = None) -> dict:
    """[READ] Get configuration details for one Tier-0 gateway (north-south edge router).

    Use after list_tier0_gateways to inspect HA configuration, or to build the
    tier0_path ("/infra/tier-0s/<id>") that create_tier1_gateway needs. For BGP
    peering state use get_bgp_neighbors instead. Returns one dict (not the list
    envelope): id, display_name, ha_mode, failover_mode, transit_subnets,
    internal_transit_subnets, rd_admin_field. Static config only — it does not
    say whether the gateway is currently forwarding.

    Args:
        tier0_id: Tier-0 gateway ID, as returned by list_tier0_gateways.
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.inventory import get_tier0_gateway as _get_tier0

        client = server._get_connection(target)
        return _get_tier0(client, tier0_id)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def list_tier1_gateways(
    target: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """[READ] List all Tier-1 gateways with linked Tier-0 path and route advertisement.

    Returns the result envelope; check `truncated` before calling it complete.
    Page it: `limit` is the page size (1-1000, default 50; 0 or negative is
    rejected), `offset` is how many rows to skip, and the response carries
    `next_offset` — pass that back as `offset` and stop when it is null. Do not
    loop on `truncated`: that says this page is not the whole collection, so it
    stays true on the last page of a walk.

    Use this first to resolve a tier1_id — create_nat_rule, create_static_route,
    list_nat_rules and update_tier1_gateway all take one. A row with an empty
    tier0_path is standalone and cannot reach north-south. Then
    get_tier1_gateway for detail.

    Args:
        target: NSX Manager target from config (default if omitted).
        limit: Page size, 1-1000 (default 50).
        offset: Rows to skip; pass the previous response's `next_offset`.
    """
    try:
        from vmware_nsx.ops.inventory import list_tier1_gateways as _list_tier1s

        client = server._get_connection(target)
        return _list_tier1s(client, limit=limit, offset=offset)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def get_tier1_gateway(tier1_id: str, target: Optional[str] = None) -> dict:
    """[READ] Get detailed info for one Tier-1 gateway.

    Use after list_tier1_gateways, and always before update_tier1_gateway —
    update is a PATCH, so you need the current values to know what you are
    changing. Returns a single detail dict (not the list envelope): id,
    display_name, tier0_path, failover_mode, route_advertisement_types, type.
    Attached segments are not listed here — use list_segments for those.

    Args:
        tier1_id: Tier-1 gateway ID, as returned by list_tier1_gateways.
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.inventory import get_tier1_gateway as _get_tier1

        client = server._get_connection(target)
        return _get_tier1(client, tier1_id)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def list_transport_zones(
    target: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """[READ] List all NSX transport zones — the overlay/VLAN boundaries segments attach to.

    Page it: `limit` is the page size (1-1000, default 50; 0 or negative is
    rejected), `offset` is how many rows to skip, and the response carries
    `next_offset` — pass that back as `offset` and stop when it is null. Do not
    loop on `truncated`: that says this page is not the whole collection, so it
    stays true on the last page of a walk.

    Use this first when building a segment: create_segment requires a
    transport_zone_path of
    "/infra/sites/default/enforcement-points/default/transport-zones/<id>"
    built from the id returned here. Returns the result envelope; each row has
    id, display_name and transport_type (OVERLAY_STANDARD, VLAN_BACKED, …). A
    VLAN-backed zone needs create_segment's vlan_ids, an overlay zone needs its
    subnet — passing the wrong one is rejected.

    Args:
        target: NSX Manager target from config (default if omitted).
        limit: Page size, 1-1000 (default 50).
        offset: Rows to skip; pass the previous response's `next_offset`.
    """
    try:
        from vmware_nsx.ops.inventory import list_transport_zones as _list_tzs

        client = server._get_connection(target)
        return _list_tzs(client, limit=limit, offset=offset)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def list_transport_nodes(
    target: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """[READ] List all transport nodes (ESXi hosts and Edge nodes) with type and status.

    Returns the result envelope; check `truncated` before calling it complete.
    Page it: `limit` is the page size (1-1000, default 50; 0 or negative is
    rejected), `offset` is how many rows to skip, and the response carries
    `next_offset` — pass that back as `offset` and stop when it is null. Do not
    loop on `truncated`: that says this page is not the whole collection, so it
    stays true on the last page of a walk.

    Use this first to resolve a node_id, then get_transport_node_status for that
    node's tunnels, controller connectivity and pNICs — the summary status here
    does not explain why a node is degraded.

    Args:
        target: NSX Manager target from config (default if omitted).
        limit: Page size, 1-1000 (default 50).
        offset: Rows to skip; pass the previous response's `next_offset`.
    """
    try:
        from vmware_nsx.ops.inventory import list_transport_nodes as _list_tns

        client = server._get_connection(target)
        return _list_tns(client, limit=limit, offset=offset)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def list_edge_clusters(
    target: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """[READ] List all edge clusters with member count and deployment type.

    Returns the result envelope; check `truncated` before calling it complete.
    Page it: `limit` is the page size (1-1000, default 50; 0 or negative is
    rejected), `offset` is how many rows to skip, and the response carries
    `next_offset` — pass that back as `offset` and stop when it is null. Do not
    loop on `truncated`: that says this page is not the whole collection, so it
    stays true on the last page of a walk.

    Use this first to resolve a cluster_id, then get_edge_cluster_status for
    member health. The id is also what create_tier1_gateway's edge_cluster_path
    is built from — a Tier-1 without an edge cluster cannot run NAT.

    Args:
        target: NSX Manager target from config (default if omitted).
        limit: Page size, 1-1000 (default 50).
        offset: Rows to skip; pass the previous response's `next_offset`.
    """
    try:
        from vmware_nsx.ops.inventory import list_edge_clusters as _list_ecs

        client = server._get_connection(target)
        return _list_ecs(client, limit=limit, offset=offset)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}

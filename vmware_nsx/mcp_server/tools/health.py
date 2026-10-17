"""READ-ONLY health tools: alarms, transport node / edge cluster / manager status."""

from typing import Optional

from vmware_policy import vmware_tool

from vmware_nsx.mcp_server import server
from vmware_nsx.mcp_server._shared import _hint_for, _safe_error, mcp


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def list_nsx_alarms(
    severity: str = "MEDIUM",
    target: Optional[str] = None,
    limit: int = 1000,
    offset: int = 0,
) -> dict:
    """[READ] Get active NSX alarms at one severity, with feature, description, and entity.

    Returns the result envelope; check `truncated` before calling it complete.
    Note: the NSX severity filter is an EXACT match — "MEDIUM" returns only
    MEDIUM alarms, not MEDIUM-and-above, so call it once per severity to build a
    full picture.

    Page it: `limit` is the page size (1-1000, 0 or negative is rejected),
    `offset` is how many rows to skip, and the response carries `next_offset` —
    pass that back as `offset` and stop when it is null. Do not loop on
    `truncated`: that says this page is not the whole set, so it stays true on
    the last page of a walk. Unlike the other list tools this one defaults to
    the full 1000, because a health sweep that silently showed the first fifty
    alarms would be worse than a long one.

    Start a health check at get_nsx_manager_status, then come here, then drill
    into the entity the alarm names with get_transport_node_status or
    get_edge_cluster_status.

    Args:
        severity: Exact severity: LOW, MEDIUM, HIGH or CRITICAL (default MEDIUM).
        target: NSX Manager target from config (default if omitted).
        limit: Page size, 1-1000 (default 1000 — every alarm at the severity).
        offset: Alarms to skip; pass the previous response's `next_offset`.
    """
    try:
        from vmware_nsx.ops.health import list_alarms as _list_alarms

        client = server._get_connection(target)
        return _list_alarms(client, severity=severity, limit=limit, offset=offset)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def get_transport_node_status(node_id: str, target: Optional[str] = None) -> dict:
    """[READ] Get realized runtime status of one transport node (ESXi host or Edge node).

    Use after list_transport_nodes when a node looks degraded or overlay tunnels
    are suspect; for cluster-wide edge health use get_edge_cluster_status
    instead. Returns one dict (not the list envelope): node_id, status (UP,
    DEGRADED, DOWN, UNKNOWN), control_connection_status,
    mgmt_connection_status, tunnel_status (up/down/degraded counts, BFD
    counters) and pnic_status. Point-in-time only — no history.

    If tunnels are down on one segment only, follow up with
    get_logical_port_status rather than blaming the node.

    Args:
        node_id: Transport node UUID, as returned by list_transport_nodes.
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.health import get_transport_node_status as _get_tn_status

        client = server._get_connection(target)
        return _get_tn_status(client, node_id)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def get_edge_cluster_status(cluster_id: str, target: Optional[str] = None) -> dict:
    """[READ] Check status of an edge cluster (member health, overall status).

    Use this after list_edge_clusters when north-south traffic, NAT or BGP looks
    broken — Tier-0/Tier-1 stateful services run on these members. Returns one
    dict (not the list envelope): cluster_id, edge_cluster_status, member_count
    and members (transport_node_id, transport_node_name, status). Member status
    only — why a member is degraded comes from get_transport_node_status.

    Args:
        cluster_id: Edge cluster UUID, as returned by list_edge_clusters.
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.health import get_edge_cluster_status as _get_ec_status

        client = server._get_connection(target)
        return _get_ec_status(client, cluster_id)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def get_nsx_manager_status(target: Optional[str] = None) -> dict:
    """[READ] Get NSX Manager cluster status (node health, control/management plane).

    Start any NSX health check here: if the manager cluster is degraded, every
    other reading is suspect. Returns one dict (not the list envelope):
    cluster_id, overall_status, control_cluster_status, mgmt_cluster_status,
    online_node_count and nodes. Only online nodes are listed, so a node missing
    from `nodes` is down rather than absent. Then list_nsx_alarms for what is
    actually firing.

    Args:
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.health import get_manager_status as _get_mgr_status

        client = server._get_connection(target)
        return _get_mgr_status(client)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}

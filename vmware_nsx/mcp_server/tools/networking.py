"""READ-ONLY networking tools: NAT rules, BGP neighbors, static routes, IP pools."""

from typing import Literal, Optional

from vmware_policy import vmware_tool

from vmware_nsx.mcp_server import server
from vmware_nsx.mcp_server._shared import _hint_for, _safe_error, mcp


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def list_nat_rules(
    tier1_id: str,
    target: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """[READ] List NAT rules on a Tier-1 gateway (USER section).

    Returns the result envelope; check `truncated` before calling it complete.
    Page it: `limit` is the page size (1-1000, default 50; 0 or negative is
    rejected), `offset` is how many rows to skip, and the response carries
    `next_offset` — pass that back as `offset` and stop when it is null. Do not
    loop on `truncated`: that says this page is not the whole collection, so it
    stays true on the last page of a walk.

    Get tier1_id from list_tier1_gateways first. Use this before create_nat_rule
    to avoid an id clash, and before delete_nat_rule to confirm what a rule
    does. Only the USER section is listed — NSX-internal NAT is not shown.

    Args:
        tier1_id: Gateway ID, as returned by list_tier1_gateways.
        target: NSX Manager target from config (default if omitted).
        limit: Page size, 1-1000 (default 50).
        offset: Rows to skip; pass the previous response's `next_offset`.
    """
    try:
        from vmware_nsx.ops.networking import list_nat_rules as _list_nat

        client = server._get_connection(target)
        return _list_nat(client, tier1_id, limit=limit, offset=offset)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def get_bgp_neighbors(tier0_id: str, target: Optional[str] = None) -> dict:
    """[READ] Get BGP configuration and neighbor status for a Tier-0 gateway.

    Use this to verify dynamic routing after configure_tier0_bgp, or when
    troubleshooting north-south connectivity. Returns one dict (not the list
    envelope): tier0_id, locale-service info, BGP config (local AS, enabled,
    ECMP), neighbors (peer IP, remote ASN, timers) and realized session status
    (connection_state, in/out prefix counts). Only the gateway's FIRST
    locale-service is read; a gateway with none returns a hint, not an error.

    If sessions are down, check get_edge_cluster_status — BGP runs on the edge
    members. Static routes are listed separately by list_static_routes.

    Args:
        tier0_id: Tier-0 gateway ID, as returned by list_tier0_gateways.
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.networking import get_bgp_neighbors as _get_bgp

        client = server._get_connection(target)
        return _get_bgp(client, tier0_id)
    except Exception as e:
        return [{"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}]


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def list_static_routes(
    tier1_id: str,
    gateway_type: Literal["tier0", "tier1"] = "tier1",
    target: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """[READ] List static routes on a Tier-0 or Tier-1 gateway.

    Returns the result envelope; check `truncated` before calling it complete.
    Page it: `limit` is the page size (1-1000, default 50; 0 or negative is
    rejected), `offset` is how many rows to skip, and the response carries
    `next_offset` — pass that back as `offset` and stop when it is null. Do not
    loop on `truncated`: that says this page is not the whole collection, so it
    stays true on the last page of a walk.

    Use this before create_static_route to avoid an id clash, and before
    delete_static_route to confirm the destination and next hops. gateway_type
    must match where the route actually lives — querying the wrong tier returns
    an empty list, not an error. BGP-learned routes are not here; use
    get_bgp_neighbors.

    Args:
        tier1_id: Gateway ID (Tier-0 or Tier-1, per gateway_type), as returned
            by list_tier0_gateways / list_tier1_gateways.
        gateway_type: Either "tier0" or "tier1" (default "tier1").
        target: NSX Manager target from config (default if omitted).
        limit: Page size, 1-1000 (default 50).
        offset: Rows to skip; pass the previous response's `next_offset`.
    """
    try:
        from vmware_nsx.ops.networking import list_static_routes as _list_routes

        client = server._get_connection(target)
        return _list_routes(
            client, tier1_id, gateway_type=gateway_type, limit=limit, offset=offset
        )
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def list_ip_pools(
    target: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """[READ] List all IP address pools with subnets and usage summary.

    Returns the result envelope; check `truncated` before calling it complete.
    Page it: `limit` is the page size (1-1000, default 50; 0 or negative is
    rejected), `offset` is how many rows to skip, and the response carries
    `next_offset` — pass that back as `offset` and stop when it is null. Do not
    loop on `truncated`: that says this page is not the whole collection, so it
    stays true on the last page of a walk.

    Use this first to resolve a pool_id, then get_ip_pool_usage for the actual
    allocations — the summary here does not tell you which addresses are taken.
    Run it before create_ip_pool to avoid overlapping ranges.

    Args:
        target: NSX Manager target from config (default if omitted).
        limit: Page size, 1-1000 (default 50).
        offset: Rows to skip; pass the previous response's `next_offset`.
    """
    try:
        from vmware_nsx.ops.networking import list_ip_pools as _list_pools

        client = server._get_connection(target)
        return _list_pools(client, limit=limit, offset=offset)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def get_ip_pool_usage(pool_id: str, target: Optional[str] = None) -> dict:
    """[READ] Get current IP allocations for one IP address pool.

    Use this after list_ip_pools to see how much of a pool is consumed — e.g.
    diagnosing TEP address exhaustion, or before delete_ip_pool, which cannot
    proceed while allocations remain. Returns a single dict (not the list
    envelope): pool_id, allocation_count and allocations (id, display_name,
    allocation_ip). An empty allocations list means the pool is unused, not that
    the query failed. On failure returns {"error", "hint"}.

    Args:
        pool_id: IP pool ID, as returned by list_ip_pools.
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.networking import get_ip_pool_usage as _get_usage

        client = server._get_connection(target)
        return _get_usage(client, pool_id)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}

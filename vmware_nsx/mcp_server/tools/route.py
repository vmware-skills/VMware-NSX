"""WRITE tools: static route create / delete."""

from typing import Literal, Optional

from vmware_policy import vmware_tool

from vmware_nsx.mcp_server import server
from vmware_nsx.mcp_server._shared import _DOCTOR_HINT, _delete_error, _safe_error, mcp


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
@vmware_tool(
    risk_level="medium",
    undo=lambda params, result: {
        "tool": "delete_static_route",
        "params": {
            "tier1_id": params.get("tier1_id"),
            "route_id": params.get("route_id"),
            "gateway_type": params.get("gateway_type", "tier1"),
            "target": params.get("target"),
        },
        "skill": "nsx",
        "note": "Inverse of create_static_route: delete the created static route.",
    },
)
def create_static_route(
    tier1_id: str,
    route_id: str,
    network: str,
    next_hop: str,
    gateway_type: Literal["tier0", "tier1"] = "tier1",
    target: Optional[str] = None,
) -> dict:
    """[WRITE] Create a static route on a Tier-0 or Tier-1 gateway via the Policy API.

    Use this for destinations not covered by connected or advertised routes,
    e.g. a VPN or external subnet. Run list_static_routes first to avoid an id
    clash — the same route_id overwrites (PUT). For the Tier-0 to advertise a
    Tier-1's static route upstream, the gateway needs TIER1_STATIC_ROUTES
    advertisement, set via update_tier1_gateway. Returns the created route dict,
    else {"error", "hint"}. Then confirm with list_static_routes;
    delete_static_route is the inverse.

    Args:
        tier1_id: Gateway ID (Tier-0 or Tier-1, per gateway_type), from
            list_tier0_gateways / list_tier1_gateways.
        route_id: Unique id (alphanumerics, hyphens, underscores only).
        network: Destination network in CIDR notation, e.g. "10.0.0.0/8".
        next_hop: Next-hop IPv4 address, e.g. "192.168.1.254".
        gateway_type: Either "tier0" or "tier1" (default "tier1").
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.nat_route_mgmt import create_static_route as _create

        client = server._get_connection(target)
        return _create(
            client, tier1_id, route_id,
            network=network,
            next_hops=[{"ip_address": next_hop}],
            gateway_type=gateway_type,
        )
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _DOCTOR_HINT}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
@vmware_tool(risk_level="high")
def delete_static_route(
    tier1_id: str,
    route_id: str,
    gateway_type: Literal["tier0", "tier1"] = "tier1",
    confirm: bool = False,
    target: Optional[str] = None,
) -> dict:
    """[WRITE] Permanently delete a static route from a Tier-0 or Tier-1 gateway.

    Irreversible: traffic to the route's destination CIDR immediately falls back
    to remaining routes or is dropped. Without confirm=True this only previews:
    it returns blast_radius (the gateway, the route's network and next hops,
    blockers, unmeasured) and deletes nothing. Show that to the user and get
    their decision. Do not set confirm=True on your own because the user asked
    to delete earlier: they have not seen the blast radius yet. gateway_type
    must match where the route lives; a route_id not on that gateway is an
    error, and confirm=True refuses when the routes could not be read. Returns
    {"action": "preview" | "deleted", "blast_radius": ...}, else {"error",
    "hint", "blast_radius"?}.

    Args:
        tier1_id: Gateway that owns the route (Tier-0 or Tier-1, per
            gateway_type), from list_tier0_gateways / list_tier1_gateways.
        route_id: Static route ID to delete, as returned by list_static_routes.
        gateway_type: Either "tier0" or "tier1" (default "tier1").
        confirm: False (default) returns the blast radius and changes nothing. True applies it.
        target: NSX Manager target from config (default if omitted).
    """
    hint = (
        f"Run list_static_routes on '{tier1_id}' to confirm the route_id and that "
        f"gateway_type='{gateway_type}' is right, or 'vmware-nsx doctor' to check "
        "connectivity."
    )
    try:
        from vmware_nsx.ops.delete_gate import preview, refuse_unless_clear, static_route_delete_blast_radius
        from vmware_nsx.ops.nat_route_mgmt import delete_static_route as _delete

        client = server._get_connection(target)
        radius = static_route_delete_blast_radius(client, tier1_id, route_id, gateway_type=gateway_type)
        if confirm is not True:
            return preview(radius)
        refuse_unless_clear("delete_static_route", radius)
        _delete(client, tier1_id, route_id, gateway_type=gateway_type)
        return {"action": "deleted", "deleted": route_id, "blast_radius": radius}
    except Exception as e:
        return _delete_error(e, hint)

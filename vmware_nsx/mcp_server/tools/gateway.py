"""WRITE tools: Tier-1 gateway create / update / delete, Tier-0 BGP config."""

from typing import Optional

from vmware_policy import report_tool_failure, vmware_tool

from vmware_nsx.mcp_server import server
from vmware_nsx.mcp_server._shared import _DOCTOR_HINT, _safe_error, mcp


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
@vmware_tool(
    risk_level="medium",
    undo=lambda params, result: {
        "tool": "delete_tier1_gateway",
        "params": {"tier1_id": params.get("tier1_id"), "target": params.get("target")},
        "skill": "nsx",
        "note": "Inverse of create_tier1_gateway: delete the created Tier-1 gateway.",
    },
)
def create_tier1_gateway(
    tier1_id: str,
    display_name: str,
    tier0_path: Optional[str] = None,
    edge_cluster_path: Optional[str] = None,
    route_advertisement: Optional[str] = None,
    target: Optional[str] = None,
) -> dict:
    """[WRITE] Create a Tier-1 gateway to route segments, optionally uplinked to a Tier-0.

    Use this before create_segment when the segment needs routing; get
    tier0_path from list_tier0_gateways and edge_cluster_path from
    list_edge_clusters first. Without route_advertisement, connected subnets
    stay unreachable from outside until it is set here or via
    update_tier1_gateway. The same tier1_id overwrites (PUT).
    Returns the created gateway dict, else {"error", "hint"}; verify with
    get_tier1_gateway.

    Args:
        tier1_id: Unique id (alphanumerics, hyphens, underscores); becomes
            /infra/tier-1s/<tier1_id>.
        display_name: UI display name.
        tier0_path: Parent Tier-0 path, e.g. "/infra/tier-0s/<t0-id>"; omit for
            a standalone gateway.
        edge_cluster_path: Required for NAT and other stateful services.
        route_advertisement: Comma-separated: TIER1_CONNECTED,
            TIER1_STATIC_ROUTES, TIER1_NAT, TIER1_LB_VIP, TIER1_LB_SNAT,
            TIER1_DNS_FORWARDER_IP, TIER1_IPSEC_LOCAL_ENDPOINT.
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.segment_mgmt import create_tier1_gateway as _create

        client = server._get_connection(target)
        ra_types = (
            [t.strip() for t in route_advertisement.split(",") if t.strip()]
            if route_advertisement
            else None
        )
        return _create(
            client, tier1_id,
            display_name=display_name,
            tier0_path=tier0_path,
            route_advertisement_types=ra_types,
            edge_cluster_path=edge_cluster_path,
        )
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _DOCTOR_HINT}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
@vmware_tool(risk_level="medium")
def update_tier1_gateway(
    tier1_id: str,
    display_name: Optional[str] = None,
    tier0_path: Optional[str] = None,
    route_advertisement: Optional[str] = None,
    target: Optional[str] = None,
) -> dict:
    """[WRITE] Partially update an existing Tier-1 gateway via PATCH.

    Only the fields you pass change. Use get_tier1_gateway first —
    route_advertisement is sent as a whole list, so include every type you want
    kept. Prefer this over create_tier1_gateway for an existing gateway: create
    is a PUT and overwrites everything. Re-applying identical values is
    harmless. Returns the updated gateway dict, else {"error", "hint"}.

    Args:
        tier1_id: Gateway ID to update, as returned by list_tier1_gateways.
        display_name: New display name. Optional.
        tier0_path: New parent Tier-0 path, e.g. "/infra/tier-0s/<t0-id>".
        route_advertisement: Comma-separated types: TIER1_CONNECTED,
            TIER1_STATIC_ROUTES, TIER1_NAT, TIER1_LB_VIP, TIER1_LB_SNAT,
            TIER1_DNS_FORWARDER_IP, TIER1_IPSEC_LOCAL_ENDPOINT.
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.segment_mgmt import update_tier1_gateway as _update

        client = server._get_connection(target)
        updates: dict = {}
        if display_name is not None:
            updates["display_name"] = display_name
        if tier0_path is not None:
            updates["tier0_path"] = tier0_path
        if route_advertisement is not None:
            updates["route_advertisement_types"] = [
                t.strip() for t in route_advertisement.split(",") if t.strip()
            ]
        return _update(client, tier1_id, **updates)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _DOCTOR_HINT}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
@vmware_tool(risk_level="high")
def delete_tier1_gateway(tier1_id: str, target: Optional[str] = None) -> str:
    """[WRITE] Delete a Tier-1 gateway; refuses while anything still depends on it.

    Irreversible; confirm with the user first. Checks first (read-only) and
    refuses, deleting nothing, while any remain: attached segments or
    Tier-1-scoped segments, NAT rules, static routes, service interfaces,
    extra locale-services, IPsec/L2 VPN services, a DNS forwarder, or a load
    balancer service attached to it. It never removes them for you. When clear,
    deletes the "default" locale-service, then the gateway. Returns a
    confirmation string, or an "Error: ..." string naming the blocking ids —
    not a dict.

    Args:
        tier1_id: Gateway ID to delete, as returned by list_tier1_gateways.
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.segment_mgmt import delete_tier1_gateway as _delete

        client = server._get_connection(target)
        out = _delete(client, tier1_id)
        if not (isinstance(out, dict) and out.get("deleted") is True):
            # The pre-flight refused (or said nothing we can read as a delete).
            # A string return is invisible to @vmware_tool, so declare it.
            reason = out.get("error") if isinstance(out, dict) else None
            msg = reason or "the ops layer did not confirm the delete."
            report_tool_failure(msg)
            return f"Error: Tier-1 gateway '{tier1_id}' was NOT deleted. {msg}"
        return f"Tier-1 gateway '{tier1_id}' deleted."
    except Exception as e:
        msg = _safe_error(e, "nsx")
        # This tool returns a string, so @vmware_tool sees an ordinary return
        # and would audit the failed delete as status=ok while telling the
        # circuit breaker the call succeeded. Declare the failure explicitly.
        report_tool_failure(msg)
        return (
            f"Error: the gateway was NOT deleted. {msg} "
            f"Run list_tier1_gateways to confirm '{tier1_id}' exists on this target, "
            f"or 'vmware-nsx doctor' to check connectivity."
        )


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
@vmware_tool(risk_level="medium")
def configure_tier0_bgp(
    tier0_id: str,
    local_as_num: str,
    enabled: bool = True,
    ecmp: bool = True,
    inter_sr_ibgp: bool = True,
    locale_service_id: str = "default",
    target: Optional[str] = None,
) -> dict:
    """[WRITE] Configure BGP settings on a Tier-0 gateway's locale-service.

    Use get_tier0_gateway first to confirm the tier0_id. Sets BGP *settings*
    only (local AS, ECMP, inter-SR iBGP); neighbor creation is a separate Policy
    API object not exposed here, so peering will not come up from this call
    alone. Returns the updated BGP config dict, else {"error", "hint"}. Then
    check get_bgp_neighbors for session state.

    Args:
        tier0_id: Tier-0 gateway ID, as returned by list_tier0_gateways.
        local_as_num: Local AS number as a string, e.g. "65001".
        enabled: Enable or disable BGP on the locale-service (default True).
        ecmp: Enable ECMP for BGP routes (default True).
        inter_sr_ibgp: Enable inter-SR iBGP (default True).
        locale_service_id: Locale-service identifier (default "default").
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.segment_mgmt import configure_tier0_bgp as _configure

        client = server._get_connection(target)
        bgp_config = {
            "local_as_num": local_as_num,
            "enabled": enabled,
            "ecmp": ecmp,
            "inter_sr_ibgp": inter_sr_ibgp,
        }
        return _configure(client, tier0_id, locale_service_id, bgp_config)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _DOCTOR_HINT}

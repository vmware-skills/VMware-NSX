"""WRITE tools: segment create / update / delete."""

from typing import Optional

from vmware_policy import vmware_tool

from vmware_nsx.mcp_server import server
from vmware_nsx.mcp_server._shared import _DOCTOR_HINT, _delete_error, _safe_error, mcp


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
@vmware_tool(
    risk_level="medium",
    undo=lambda params, result: {
        "tool": "delete_segment",
        "params": {"segment_id": params.get("segment_id"), "target": params.get("target")},
        "skill": "nsx",
        "note": "Inverse of create_segment: delete the created segment.",
    },
)
def create_segment(
    segment_id: str,
    display_name: str,
    transport_zone_path: str,
    vlan_ids: Optional[str] = None,
    subnet: Optional[str] = None,
    target: Optional[str] = None,
) -> dict:
    """[WRITE] Create an overlay or VLAN-backed NSX network segment.

    Run list_transport_zones first for transport_zone_path; it decides whether
    subnet or vlan_ids applies — the wrong one is rejected. The same segment_id
    overwrites (PUT). Returns the created segment dict, else {"error", "hint"}.
    A segment with no gateway is isolated: link it with create_tier1_gateway,
    then verify with get_segment.

    Args:
        segment_id: Unique id (alphanumerics, hyphens, underscores only);
            becomes /infra/segments/<segment_id>.
        display_name: UI display name.
        transport_zone_path: Full path, e.g.
            "/infra/sites/default/enforcement-points/default/transport-zones/<tz-id>".
        vlan_ids: VLAN ID(s) for a VLAN-backed zone, e.g. "100,200".
        subnet: Gateway IP in CIDR for an overlay zone, e.g. "192.168.1.1/24" —
            the gateway address, not the network address.
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.segment_mgmt import create_segment as _create

        client = server._get_connection(target)
        parsed_vlan_ids: Optional[list[int]] = None
        if vlan_ids is not None:
            parsed_vlan_ids = [int(v.strip()) for v in vlan_ids.replace("-", ",").split(",") if v.strip()]
        parsed_subnets: Optional[list[dict[str, str]]] = None
        if subnet is not None:
            parsed_subnets = [{"gateway_address": subnet}]
        return _create(
            client, segment_id,
            display_name=display_name,
            transport_zone_path=transport_zone_path,
            vlan_ids=parsed_vlan_ids,
            subnets=parsed_subnets,
        )
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _DOCTOR_HINT}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
@vmware_tool(risk_level="medium")
def update_segment(
    segment_id: str,
    display_name: Optional[str] = None,
    subnet: Optional[str] = None,
    target: Optional[str] = None,
) -> dict:
    """[WRITE] Update an existing network segment (partial update via PATCH).

    Only the fields you pass change. Use get_segment first, and prefer this over
    create_segment for an existing segment: create is a PUT and overwrites
    everything. Changing subnet re-addresses the gateway and can drop traffic
    for attached VMs, so check port_count first. Returns the updated segment
    dict, else {"error", "hint"}.

    Args:
        segment_id: Segment ID to update, as returned by list_segments.
        display_name: New display name. Optional.
        subnet: New gateway CIDR, e.g. "192.168.1.1/24". Optional.
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.segment_mgmt import update_segment as _update

        client = server._get_connection(target)
        update_kwargs: dict = {}
        if display_name is not None:
            update_kwargs["display_name"] = display_name
        if subnet is not None:
            update_kwargs["subnets"] = [{"gateway_address": subnet}]
        return _update(client, segment_id, **update_kwargs)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _DOCTOR_HINT}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
@vmware_tool(risk_level="high")
def delete_segment(segment_id: str, confirm: bool = False, target: Optional[str] = None) -> dict:
    """[WRITE] Delete a network segment; refuses while any port is attached.

    Irreversible. Without confirm=True this only previews: it returns
    blast_radius (the segment's name, gateway, subnets, port_count and
    port_ids, blockers, unmeasured) and deletes nothing. Show that to the user
    and get their decision. Do not set confirm=True on your own because the
    user asked to delete earlier: they have not seen the blast radius yet.

    confirm=True re-measures, then refuses, deleting nothing, while any port
    (a VM vNIC or router interface) is attached — it never disconnects them for
    you — or when the ports could not be read. Returns {"action": "preview" |
    "deleted", "blast_radius": ...}, else {"error", "hint", "blast_radius"?}.

    Args:
        segment_id: Segment ID to delete, as returned by list_segments.
        confirm: False (default) returns the blast radius and changes nothing. True applies it.
        target: NSX Manager target from config (default if omitted).
    """
    hint = (
        f"Run list_segments to confirm '{segment_id}' exists on this target, or "
        "get_logical_port_status to see whether ports are still attached "
        "(a segment with attached ports cannot be deleted)."
    )
    try:
        from vmware_nsx.ops.delete_gate import preview, refuse_unless_clear, segment_delete_blast_radius
        from vmware_nsx.ops.segment_mgmt import delete_segment as _delete

        client = server._get_connection(target)
        radius = segment_delete_blast_radius(client, segment_id)
        if confirm is not True:
            return preview(radius)
        refuse_unless_clear("delete_segment", radius)
        out = _delete(client, segment_id)
        if not (isinstance(out, dict) and out.get("deleted") is True):
            # The ops port check refused (a port attached since the measurement),
            # or said nothing we can read as a delete.
            reason = out.get("error") if isinstance(out, dict) else None
            msg = reason or "the ops layer did not confirm the delete."
            return {"error": f"Segment '{segment_id}' was NOT deleted. {msg}",
                    "hint": hint, "blast_radius": radius}
        return {"action": "deleted", "deleted": segment_id, "blast_radius": radius}
    except Exception as e:
        return _delete_error(e, hint)

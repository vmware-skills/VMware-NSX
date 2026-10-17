"""READ-ONLY troubleshooting tools: logical port status, VM-to-segment mapping."""

from typing import Optional

from vmware_policy import vmware_tool

from vmware_nsx.mcp_server import server
from vmware_nsx.mcp_server._shared import _hint_for, _safe_error, mcp


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def get_logical_port_status(segment_id: str, target: Optional[str] = None) -> dict:
    """[READ] Check realized state of all ports on a segment (first 50 ports).

    Use this after get_segment_port_for_vm has told you which segment a VM sits
    on, or before delete_segment to see whether ports are still attached.
    Returns per-port admin_state, attachment (type/id) and realized state:
    attached, realized_bindings_count, transport_node_ids. NSX does not expose a
    single UP/DOWN flag per segment port — an attached port with realized
    bindings on at least one transport node is healthy. Only the first 50 ports
    are returned.

    If bindings are missing everywhere, check get_transport_node_status.

    Args:
        segment_id: Segment ID whose ports to inspect, as returned by
            list_segments.
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.troubleshoot import get_logical_port_status as _get_port

        client = server._get_connection(target)
        return _get_port(client, segment_id)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
@vmware_tool(risk_level="low")
def get_segment_port_for_vm(vm_display_name: str, target: Optional[str] = None) -> dict:
    """[READ] Find which segment(s) a VM is attached to via its VIF attachments.

    Start here for "why can this VM not reach the network?" — it is the only
    tool mapping a VM name onto NSX topology. Looks the VM up in the fabric
    inventory, fetches its VIFs, and matches segment ports by
    lport_attachment_id. Returns one dict (not the list envelope): VM info
    (external_id, host, power state) and matched_ports (segment id/name, port
    id/name). Matching is on exact display name, and empty matched_ports means
    no VIF is attached, not that the VM is missing.

    Then get_logical_port_status on the segment it names. VM power and placement
    are not managed here — use vmware-aiops.

    Args:
        vm_display_name: VM display name as shown in vCenter/NSX inventory.
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.troubleshoot import get_segment_port_for_vm as _get_vm_seg

        client = server._get_connection(target)
        return _get_vm_seg(client, vm_display_name)
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _hint_for(e)}

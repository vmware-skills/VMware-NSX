"""WRITE tools: IP address pool create / delete."""

from typing import Optional

from vmware_policy import report_tool_failure, vmware_tool

from vmware_nsx.mcp_server import server
from vmware_nsx.mcp_server._shared import _DOCTOR_HINT, _safe_error, mcp


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
@vmware_tool(
    risk_level="medium",
    undo=lambda params, result: {
        "tool": "delete_ip_pool",
        "params": {"pool_id": params.get("pool_id"), "target": params.get("target")},
        "skill": "nsx",
        "note": "Inverse of create_ip_pool: delete the created IP pool.",
    },
)
def create_ip_pool(
    pool_id: str,
    display_name: str,
    start_ip: str,
    end_ip: str,
    cidr: str,
    gateway_ip: Optional[str] = None,
    target: Optional[str] = None,
) -> dict:
    """[WRITE] Create an IP address pool with one static subnet and allocation range.

    IP pools supply addresses to NSX consumers such as tunnel endpoints.
    Run list_ip_pools first to avoid overlapping ranges; start_ip and end_ip
    must both fall inside cidr. The same pool_id overwrites (PUT). Returns
    {"created", "pool_id", "subnets_created", "subnets_failed"}. If the subnet
    failed it also has "error": the pool itself WAS created and needs cleaning
    up (the error says how). Other failures return {"error", "hint"}. Verify
    with get_ip_pool_usage; delete_ip_pool is the inverse.

    Args:
        pool_id: Unique id (alphanumerics, hyphens, underscores only); becomes
            /infra/ip-pools/<pool_id>.
        display_name: UI display name.
        start_ip: First allocatable IPv4 address, e.g. "192.168.1.10".
        end_ip: Last allocatable IPv4 address, e.g. "192.168.1.100".
        cidr: Subnet containing the range, e.g. "192.168.1.0/24".
        gateway_ip: Subnet default gateway, e.g. "192.168.1.1".
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.nat_route_mgmt import create_ip_pool as _create

        client = server._get_connection(target)
        subnet: dict = {
            "allocation_ranges": [{"start": start_ip, "end": end_ip}],
            "cidr": cidr,
        }
        if gateway_ip:
            subnet["gateway_ip"] = gateway_ip
        return _create(
            client, pool_id,
            display_name=display_name,
            subnets=[subnet],
        )
    except Exception as e:
        return {"error": _safe_error(e, "nsx"), "hint": _DOCTOR_HINT}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
@vmware_tool(risk_level="high")
def delete_ip_pool(
    pool_id: str,
    target: Optional[str] = None,
) -> str:
    """[WRITE] Permanently delete an IP address pool.

    Irreversible: consumers such as transport endpoints can no longer allocate,
    and NSX rejects the delete if the pool still has active allocations. Run
    get_ip_pool_usage on the same pool_id first to confirm it is unused, and
    confirm with the user before deleting. Returns a confirmation string, or an
    "Error: ..." string — not a dict.

    Args:
        pool_id: IP pool ID to delete, as returned by list_ip_pools.
        target: NSX Manager target from config (default if omitted).
    """
    try:
        from vmware_nsx.ops.nat_route_mgmt import delete_ip_pool as _delete

        client = server._get_connection(target)
        _delete(client, pool_id)
        return f"IP pool '{pool_id}' deleted."
    except Exception as e:
        msg = _safe_error(e, "nsx")
        # This tool returns a string, so @vmware_tool sees an ordinary return
        # and would audit the failed delete as status=ok while telling the
        # circuit breaker the call succeeded. Declare the failure explicitly.
        report_tool_failure(msg)
        return (
            f"Error: the pool was NOT deleted. {msg} "
            f"Run list_ip_pools to confirm '{pool_id}' exists on this target, or "
            f"'vmware-nsx doctor' to check connectivity."
        )

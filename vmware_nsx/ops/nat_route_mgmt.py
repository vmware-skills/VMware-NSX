"""NSX NAT & route management: create/delete NAT rules, static routes, IP pools."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from vmware_policy import sanitize

if TYPE_CHECKING:
    from vmware_nsx.connection import NsxClient

_log = logging.getLogger("vmware-nsx.nat-route-mgmt")


# The NAT actions this module accepts. The MCP tool's Literal[...] is checked
# against this set by a regression test, so the schema an agent sees and the
# values this code will take cannot drift apart.
VALID_NAT_ACTIONS = frozenset({"SNAT", "DNAT", "REFLEXIVE", "NO_SNAT", "NO_DNAT", "NAT64"})

def _validate_id(resource_id: str) -> str:
    """Validate resource ID contains only safe characters."""
    if not resource_id or not re.match(r"^[a-zA-Z0-9_-]+$", resource_id):
        raise ValueError(
            f"Invalid resource ID: '{resource_id}'. Only alphanumerics, hyphens and "
            "underscores are allowed — no spaces, slashes or dots, so a policy path "
            "like '/infra/tier-1s/t1' is not an ID. Copy an exact ID from "
            "list_tier1_gateways, list_nat_rules, list_static_routes or list_ip_pools."
        )
    return resource_id


# ---------------------------------------------------------------------------
# NAT Rules
# ---------------------------------------------------------------------------


def create_nat_rule(
    client: NsxClient,
    tier1_id: str,
    rule_id: str,
    action: str,
    source_network: str | None = None,
    destination_network: str | None = None,
    translated_network: str | None = None,
) -> dict:
    """Create a NAT rule on a Tier-1 gateway via Policy API (PUT).

    Args:
        client: Authenticated NSX API client.
        tier1_id: Tier-1 gateway identifier.
        rule_id: Unique NAT rule identifier.
        action: NAT action type. One of: SNAT, DNAT, REFLEXIVE,
                NO_SNAT, NO_DNAT, NAT64.
        source_network: Source CIDR for matching (used in SNAT/NO_SNAT).
        destination_network: Destination CIDR for matching (used in DNAT/NO_DNAT).
        translated_network: Translated IP/CIDR (required for
            SNAT/DNAT/REFLEXIVE).

    Returns:
        Created NAT rule dict from NSX API.
    """
    _validate_id(tier1_id)
    _validate_id(rule_id)

    if action not in VALID_NAT_ACTIONS:
        raise ValueError(
            f"Invalid NAT action: '{action}'. Must be one of: "
            f"{', '.join(sorted(VALID_NAT_ACTIONS))}. Pass one of those as "
            "create_nat_rule's action argument (CLI: vmware-nsx nat create-rule "
            "--action SNAT)."
        )

    body: dict[str, Any] = {
        "action": action,
        "enabled": True,
    }

    if source_network:
        body["source_network"] = source_network
    if destination_network:
        body["destination_network"] = destination_network
    if translated_network:
        body["translated_network"] = translated_network

    # Validate required fields based on action
    if action in ("SNAT", "DNAT", "REFLEXIVE") and not translated_network:
        raise ValueError(
            f"translated_network is required for {action} rules. Pass the translated "
            "address as create_nat_rule's translated_network argument — a host IP for "
            "DNAT (e.g. '10.0.1.20'), an IP or CIDR for SNAT (e.g. '203.0.113.5'). "
            "Only NO_SNAT, NO_DNAT and NAT64 may omit it."
        )

    path = (
        f"/policy/api/v1/infra/tier-1s/{tier1_id}"
        f"/nat/USER/nat-rules/{rule_id}"
    )
    result = client.put(path, body)
    _log.info(
        "Created NAT rule %s (%s) on Tier-1 %s",
        rule_id,
        action,
        tier1_id,
    )
    return result


def delete_nat_rule(
    client: NsxClient,
    tier1_id: str,
    rule_id: str,
) -> dict:
    """Delete a NAT rule from a Tier-1 gateway.

    Args:
        client: Authenticated NSX API client.
        tier1_id: Tier-1 gateway identifier.
        rule_id: NAT rule identifier to delete.

    Returns:
        Dict with deletion status.
    """
    _validate_id(tier1_id)
    _validate_id(rule_id)

    path = (
        f"/policy/api/v1/infra/tier-1s/{tier1_id}"
        f"/nat/USER/nat-rules/{rule_id}"
    )
    client.delete(path)
    _log.info("Deleted NAT rule %s from Tier-1 %s", rule_id, tier1_id)
    return {"deleted": True, "tier1_id": tier1_id, "rule_id": rule_id}


# ---------------------------------------------------------------------------
# Static Routes
# ---------------------------------------------------------------------------


def create_static_route(
    client: NsxClient,
    gateway_id: str,
    route_id: str,
    network: str,
    next_hops: list[dict[str, Any]],
    gateway_type: str = "tier1",
) -> dict:
    """Create a static route on a gateway via Policy API (PUT).

    Args:
        client: Authenticated NSX API client.
        gateway_id: Gateway identifier (Tier-0 or Tier-1).
        route_id: Unique static route identifier.
        network: Destination CIDR (e.g., "10.0.0.0/8").
        next_hops: List of next-hop dicts, each containing:
            - ip_address (str): Next-hop IP address.
            - admin_distance (int, optional): Admin distance (default 1).
        gateway_type: Either "tier0" or "tier1" (default "tier1").

    Returns:
        Created static route dict from NSX API.
    """
    _validate_id(gateway_id)
    _validate_id(route_id)

    if not next_hops:
        raise ValueError(
            f"create_static_route needs at least one next hop, got {next_hops!r}. Pass "
            "next_hops as [{'ip_address': '10.0.0.1'}], optionally with "
            "'admin_distance'. Run list_static_routes on this gateway to see the next "
            "hops its existing routes use."
        )

    gw_resource = "tier-0s" if gateway_type == "tier0" else "tier-1s"

    body: dict[str, Any] = {
        "network": network,
        "next_hops": [
            {
                "ip_address": nh["ip_address"],
                "admin_distance": nh.get("admin_distance", 1),
            }
            for nh in next_hops
        ],
    }

    path = (
        f"/policy/api/v1/infra/{gw_resource}/{gateway_id}"
        f"/static-routes/{route_id}"
    )
    result = client.put(path, body)
    _log.info(
        "Created static route %s (%s) on %s %s",
        route_id,
        network,
        gateway_type,
        gateway_id,
    )
    return result


def delete_static_route(
    client: NsxClient,
    gateway_id: str,
    route_id: str,
    gateway_type: str = "tier1",
) -> dict:
    """Delete a static route from a gateway.

    Args:
        client: Authenticated NSX API client.
        gateway_id: Gateway identifier.
        route_id: Static route identifier to delete.
        gateway_type: Either "tier0" or "tier1" (default "tier1").

    Returns:
        Dict with deletion status.
    """
    _validate_id(gateway_id)
    _validate_id(route_id)

    gw_resource = "tier-0s" if gateway_type == "tier0" else "tier-1s"
    path = (
        f"/policy/api/v1/infra/{gw_resource}/{gateway_id}"
        f"/static-routes/{route_id}"
    )
    client.delete(path)
    _log.info(
        "Deleted static route %s from %s %s",
        route_id,
        gateway_type,
        gateway_id,
    )
    return {
        "deleted": True,
        "gateway_id": gateway_id,
        "gateway_type": gateway_type,
        "route_id": route_id,
    }


# ---------------------------------------------------------------------------
# IP Pools
# ---------------------------------------------------------------------------


def create_ip_pool(
    client: NsxClient,
    pool_id: str,
    display_name: str,
    subnets: list[dict[str, Any]],
) -> dict:
    """Create an IP pool via Policy API (PUT).

    Args:
        client: Authenticated NSX API client.
        pool_id: Unique IP pool identifier.
        display_name: Human-readable name.
        subnets: List of subnet dicts, each containing:
            - allocation_ranges (list[dict]): Each with "start" and "end" IPs.
            - cidr (str): Subnet CIDR (e.g., "192.168.1.0/24").
            - gateway_ip (str, optional): Gateway IP for the subnet.

    Returns:
        Dict reporting partial state so a mid-loop subnet failure doesn't
        raise past the first error or leave the caller blind:
            - created (bool): True once the pool object itself was PUT.
            - pool_id (str): The pool identifier.
            - subnets_created (list[str]): IDs of subnets successfully PUT.
            - subnets_failed (list[dict]): One {"subnet", "error"} per subnet
              whose PUT failed (the pool and earlier subnets stay in place —
              this is the less-destructive report-partial-state approach; the
              caller can retry the failed subnets or clean up explicitly).
    """
    _validate_id(pool_id)

    if not subnets:
        raise ValueError(
            f"create_ip_pool needs at least one subnet, got {subnets!r}. Pass subnets "
            "as [{'cidr': '192.168.1.0/24', 'allocation_ranges': [{'start': "
            "'192.168.1.10', 'end': '192.168.1.50'}]}]. Run list_ip_pools to see how "
            "existing pools are shaped."
        )

    # Validate subnet structure
    for sub in subnets:
        if "allocation_ranges" not in sub or "cidr" not in sub:
            raise ValueError(
                f"Subnet entry {sub!r} is missing 'cidr' or 'allocation_ranges'. Each "
                "subnet must be a dict like {'cidr': '192.168.1.0/24', "
                "'allocation_ranges': [{'start': '192.168.1.10', 'end': "
                "'192.168.1.50'}]}. Run list_ip_pools to see existing pool subnets."
            )

    body: dict[str, Any] = {
        "display_name": sanitize(display_name),
    }

    path = f"/policy/api/v1/infra/ip-pools/{pool_id}"
    client.put(path, body)

    # Create IP subnets as sub-resources (IpAddressPoolStaticSubnet). A subnet
    # PUT can fail mid-loop (overlapping range, transient API error); rather
    # than raise — which would leave a half-built pool with no signal of how
    # far we got — record per-subnet outcomes and report partial state.
    subnets_created: list[str] = []
    subnets_failed: list[dict[str, Any]] = []
    for idx, sub in enumerate(subnets):
        subnet_id = f"{pool_id}-subnet-{idx}"
        subnet_body: dict[str, Any] = {
            "resource_type": "IpAddressPoolStaticSubnet",
            "display_name": f"{display_name} subnet {idx}",
            "cidr": sub["cidr"],
            "allocation_ranges": [
                {"start": r["start"], "end": r["end"]}
                for r in sub["allocation_ranges"]
            ],
        }
        if "gateway_ip" in sub:
            subnet_body["gateway_ip"] = sub["gateway_ip"]

        subnet_path = (
            f"/policy/api/v1/infra/ip-pools/{pool_id}"
            f"/ip-subnets/{subnet_id}"
        )
        try:
            client.put(subnet_path, subnet_body)
            subnets_created.append(subnet_id)
        except Exception as exc:  # noqa: BLE001 — report, don't raise past first
            subnets_failed.append({"subnet": subnet_id, "error": _subnet_error_text(exc)})
            # Full detail goes to the operator's log only; the result carries
            # authored text (see _subnet_error_text).
            _log.warning(
                "IP pool %s subnet %s failed: %s",
                pool_id,
                subnet_id,
                exc,
                exc_info=True,
            )

    _log.info(
        "Created IP pool %s (%s): %d/%d subnet(s) created",
        pool_id,
        display_name,
        len(subnets_created),
        len(subnets),
    )
    result: dict[str, Any] = {
        "created": True,
        "pool_id": pool_id,
        "subnets_created": subnets_created,
        "subnets_failed": subnets_failed,
    }
    if subnets_failed:
        # A failed subnet is a failed create (maintainer decision 2026-09-11):
        # a top-level ``error`` makes both audit sinks record it as one, while
        # ``created`` stays True because the pool object does exist.
        result["error"] = _partial_pool_message(pool_id, len(subnets), subnets_created, subnets_failed)
    return result


def _subnet_error_text(exc: Exception) -> str:
    """Why one subnet PUT failed, in text safe to hand back.

    ``NsxApiError`` is the connection layer's own translation — status, hint
    and path, authored and never quoting the transport exception or response
    body — so it passes, sanitized and capped. Anything else is unplanned, and
    its text (written for a traceback) can carry host:port or a response body:
    only its type is reported, the same rule ``_safe_error`` applies on the MCP
    surface.
    """
    from vmware_nsx.connection import NsxApiError

    if isinstance(exc, NsxApiError):
        return sanitize(str(exc), 300)
    return f"{type(exc).__name__}: the subnet request failed (details in the vmware-nsx log)."


def _partial_pool_message(
    pool_id: str, total: int, created: list[str], failed: list[dict[str, Any]]
) -> str:
    reasons = "; ".join(f"{f['subnet']}: {f['error']}" for f in failed)
    return (
        f"IP pool '{pool_id}' WAS created, but {len(failed)} of {total} subnet(s) "
        f"were not ({reasons}). The pool has {len(created)} working subnet(s). "
        "Nothing here adds a subnet to an existing pool, so to finish: delete the "
        f"pool with delete_ip_pool (CLI: vmware-nsx ip-pool delete {pool_id}), fix "
        "the cause above, then run create_ip_pool (CLI: vmware-nsx ip-pool create) "
        "again."
    )


def delete_ip_pool(
    client: NsxClient,
    pool_id: str,
) -> dict:
    """Delete an IP pool via Policy API (DELETE).

    Args:
        client: Authenticated NSX API client.
        pool_id: IP pool identifier to delete.

    Returns:
        Dict with deletion status.
    """
    _validate_id(pool_id)

    path = f"/policy/api/v1/infra/ip-pools/{pool_id}"
    client.delete(path)
    _log.info("Deleted IP pool %s", pool_id)
    return {"deleted": True, "pool_id": pool_id}

"""NSX segment & gateway management: create, update, delete segments and Tier-1 gateways."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from vmware_policy import sanitize

if TYPE_CHECKING:
    from vmware_nsx.connection import NsxClient

_log = logging.getLogger("vmware-nsx.segment-mgmt")


def _validate_id(resource_id: str) -> str:
    """Validate resource ID contains only safe characters."""
    if not resource_id or not re.match(r"^[a-zA-Z0-9_-]+$", resource_id):
        raise ValueError(
            f"Invalid resource ID: '{resource_id}'. Only alphanumerics, hyphens and "
            "underscores are allowed — no spaces, slashes or dots, so a policy path "
            "like '/infra/segments/web' is not an ID. Copy an exact ID from "
            "list_segments, list_tier0_gateways or list_tier1_gateways."
        )
    return resource_id


def parse_vlan_ids(vlan_ids: str) -> list[int | str]:
    """Parse a comma-separated VLAN spec into NSX vlan_ids entries.

    Plain numbers become ints; tokens containing '-' (e.g. "100-200") pass
    through as range strings — the NSX Policy API natively accepts VLAN
    ranges. The old `.replace("-", ",")` parse silently turned the range
    '100-200' into the two discrete VLANs 100 and 200.
    """
    parsed: list[int | str] = []
    for token in vlan_ids.split(","):
        token = token.strip()
        if not token:
            continue
        parsed.append(token if "-" in token else int(token))
    return parsed


# ---------------------------------------------------------------------------
# Segment CRUD
# ---------------------------------------------------------------------------


def create_segment(
    client: NsxClient,
    segment_id: str,
    display_name: str,
    transport_zone_path: str,
    gateway_path: str | None = None,
    subnets: list[dict[str, Any]] | None = None,
    vlan_ids: list[int | str] | None = None,
) -> dict:
    """Create a new network segment via Policy API (PUT).

    Args:
        client: Authenticated NSX API client.
        segment_id: Unique segment identifier.
        display_name: Human-readable name.
        transport_zone_path: Policy path to the transport zone.
        gateway_path: Policy path to Tier-0/Tier-1 gateway (for routed segments).
        subnets: List of subnet dicts, each with "gateway_address" and
                 optionally "dhcp_ranges".
        vlan_ids: List of VLAN IDs (for VLAN-backed segments); entries may
                  be ints or range strings like "100-200".

    Returns:
        Created segment dict from NSX API.
    """
    _validate_id(segment_id)

    body: dict[str, Any] = {
        "display_name": sanitize(display_name),
        "transport_zone_path": transport_zone_path,
    }

    if gateway_path:
        body["connectivity_path"] = gateway_path

    if subnets:
        body["subnets"] = []
        for sub in subnets:
            if "gateway_address" not in sub:
                continue
            entry: dict[str, Any] = {"gateway_address": sub["gateway_address"]}
            if sub.get("dhcp_ranges"):
                entry["dhcp_ranges"] = sub["dhcp_ranges"]
            body["subnets"].append(entry)

    if vlan_ids:
        body["vlan_ids"] = vlan_ids

    path = f"/policy/api/v1/infra/segments/{segment_id}"
    result = client.put(path, body)
    _log.info("Created segment %s (%s)", segment_id, display_name)
    return result


def update_segment(client: NsxClient, segment_id: str, **kwargs: Any) -> dict:
    """Partial-update an existing segment via PATCH.

    Supported kwargs: display_name, admin_state, subnets, vlan_ids,
    connectivity_path, transport_zone_path.

    Args:
        client: Authenticated NSX API client.
        segment_id: Segment identifier to update.
        **kwargs: Fields to update.

    Returns:
        Updated segment dict from NSX API.
    """
    _validate_id(segment_id)

    allowed_fields = {
        "display_name",
        "admin_state",
        "subnets",
        "vlan_ids",
        "connectivity_path",
        "transport_zone_path",
    }
    body: dict[str, Any] = {}
    for key, value in kwargs.items():
        if key not in allowed_fields:
            raise ValueError(
                f"Field '{key}' is not updatable on a segment. Allowed: "
                f"{', '.join(sorted(allowed_fields))}. Pass only those to "
                "update_segment; run get_segment to see the segment's current values."
            )
        body[key] = value

    if not body:
        raise ValueError(
            "update_segment was called with nothing to change. Pass at least one of: "
            f"{', '.join(sorted(allowed_fields))}. Run get_segment first to see the "
            "segment's current values."
        )

    path = f"/policy/api/v1/infra/segments/{segment_id}"
    result = client.patch(path, body)
    _log.info("Updated segment %s: %s", segment_id, list(body.keys()))
    return result


def segment_delete_blockers(client: NsxClient, segment_id: str) -> dict:
    """Attached ports that make a segment delete refuse. Read-only.

    Returns ``{}`` when the segment has no ports, else ``{"port_count": N,
    "port_ids": [...]}`` (at most 10 ids). Probes with a single-item page — one
    attached port is enough to block, so the collection is never drained.
    The dry-run preview calls this too, so it cannot promise a delete the real
    run would refuse.
    """
    _validate_id(segment_id)
    ports_path = f"/policy/api/v1/infra/segments/{segment_id}/ports"
    if not client.get_all(ports_path, page_size=1, limit=1):
        return {}
    # Non-empty: fetch the accurate total and a small id sample (fall back to
    # the sample size if the collection metadata is absent).
    total = client.get_count(ports_path)
    sample = client.get_all(ports_path, page_size=10, limit=10)
    return {
        "port_count": total if total is not None else len(sample),
        "port_ids": [sanitize(str(p.get("id", ""))) for p in sample[:10]],
    }


def segment_refusal_message(blockers: dict) -> str:
    """Teaching text for a segment delete refused by attached ports."""
    ids = blockers["port_ids"]
    more = ", …" if blockers["port_count"] > len(ids) else ""
    return (
        f"Segment has {blockers['port_count']} active port(s) "
        f"[{', '.join(ids)}{more}]. Nothing was deleted. Detach all ports "
        "first (get_segment lists them, get_logical_port_status shows "
        "their state), then retry."
    )


def delete_segment(client: NsxClient, segment_id: str) -> dict:
    """Delete a segment after verifying no ports are attached.

    Checks for existing ports first to prevent orphaned resources.

    Args:
        client: Authenticated NSX API client.
        segment_id: Segment identifier to delete.

    Returns:
        Dict with deletion status; on refusal ``deleted`` is False, ``error``
        names the attached ports and nothing was deleted.
    """
    _validate_id(segment_id)

    blockers = segment_delete_blockers(client, segment_id)
    if blockers:
        return {
            "deleted": False,
            "segment_id": segment_id,
            "error": segment_refusal_message(blockers),
            **blockers,
        }

    path = f"/policy/api/v1/infra/segments/{segment_id}"
    client.delete(path)
    _log.info("Deleted segment %s", segment_id)
    return {"deleted": True, "segment_id": segment_id}


# ---------------------------------------------------------------------------
# Tier-1 Gateway CRUD
# ---------------------------------------------------------------------------


def create_tier1_gateway(
    client: NsxClient,
    tier1_id: str,
    display_name: str,
    tier0_path: str | None = None,
    route_advertisement_types: list[str] | None = None,
    edge_cluster_path: str | None = None,
) -> dict:
    """Create a new Tier-1 gateway via Policy API (PUT).

    Args:
        client: Authenticated NSX API client.
        tier1_id: Unique Tier-1 identifier.
        display_name: Human-readable name.
        tier0_path: Policy path to parent Tier-0 gateway.
        route_advertisement_types: List of route types to advertise
            (e.g., TIER1_CONNECTED, TIER1_STATIC_ROUTES, TIER1_NAT).
        edge_cluster_path: Edge cluster policy path. When given, a
            "default" locale-service is created on the gateway pointing
            at this edge cluster (required for stateful services like NAT).

    Returns:
        Created Tier-1 gateway dict from NSX API.
    """
    _validate_id(tier1_id)

    body: dict[str, Any] = {
        "display_name": sanitize(display_name),
    }

    if tier0_path:
        body["tier0_path"] = tier0_path

    if route_advertisement_types:
        valid_types = {
            "TIER1_CONNECTED",
            "TIER1_STATIC_ROUTES",
            "TIER1_NAT",
            "TIER1_LB_VIP",
            "TIER1_LB_SNAT",
            "TIER1_DNS_FORWARDER_IP",
            "TIER1_IPSEC_LOCAL_ENDPOINT",
        }
        for rt in route_advertisement_types:
            if rt not in valid_types:
                raise ValueError(
                    f"Invalid route advertisement type: '{rt}'. Pass one or more of "
                    "these to create_tier1_gateway / update_tier1_gateway "
                    f"(--advertise on the CLI): {', '.join(sorted(valid_types))}."
                )
        body["route_advertisement_types"] = route_advertisement_types

    path = f"/policy/api/v1/infra/tier-1s/{tier1_id}"
    result = client.put(path, body)

    if edge_cluster_path:
        ls_path = f"{path}/locale-services/default"
        client.put(ls_path, {"edge_cluster_path": edge_cluster_path})

    _log.info("Created Tier-1 gateway %s (%s)", tier1_id, display_name)
    return result


def update_tier1_gateway(
    client: NsxClient,
    tier1_id: str,
    **kwargs: Any,
) -> dict:
    """Partial-update an existing Tier-1 gateway via PATCH.

    Supported kwargs: display_name, tier0_path, route_advertisement_types,
    failover_mode.

    Args:
        client: Authenticated NSX API client.
        tier1_id: Tier-1 gateway identifier to update.
        **kwargs: Fields to update.

    Returns:
        Updated Tier-1 gateway dict from NSX API.
    """
    _validate_id(tier1_id)

    allowed_fields = {
        "display_name",
        "tier0_path",
        "route_advertisement_types",
        "failover_mode",
    }
    body: dict[str, Any] = {}
    for key, value in kwargs.items():
        if key not in allowed_fields:
            raise ValueError(
                f"Field '{key}' is not updatable on a Tier-1 gateway. Allowed: "
                f"{', '.join(sorted(allowed_fields))}. Pass only those to "
                "update_tier1_gateway; run get_tier1_gateway to see current values."
            )
        body[key] = value

    if not body:
        raise ValueError(
            "update_tier1_gateway was called with nothing to change. Pass at least "
            f"one of: {', '.join(sorted(allowed_fields))}. Run get_tier1_gateway "
            "first to see the gateway's current values."
        )

    path = f"/policy/api/v1/infra/tier-1s/{tier1_id}"
    result = client.patch(path, body)
    _log.info("Updated Tier-1 gateway %s: %s", tier1_id, list(body.keys()))
    return result


#: Most ids a refusal lists per kind: enough to act on, without putting hundreds
#: of NAT-rule ids into an agent's context. A full sample is reported as "N+".
_BLOCKER_SAMPLE = 10

#: A walk over a whole collection (segments, LB services) whose members point at
#: their gateway by connectivity_path. The Policy API cannot filter on that
#: field, so the walk must not be capped: a capped walk could miss the one.
_WALK = {"page_size": 1000, "max_items": 1_000_000}
_SAMPLE = {"page_size": _BLOCKER_SAMPLE, "limit": _BLOCKER_SAMPLE}

#: blocker key -> (what it is, where to see / remove it). Order = report order.
_BLOCKER_KINDS: dict[str, tuple[str, str]] = {
    "segment_ids": ("segment", "list_segments shows each segment's gateway; detach or delete it"),
    "tier1_segment_ids": (
        "Tier-1-scoped segment",
        "GET /policy/api/v1/infra/tier-1s/<id>/segments; delete them in NSX",
    ),
    "nat_rule_ids": ("NAT rule", "list_nat_rules, then delete_nat_rule"),
    "static_route_ids": ("static route", "list_static_routes, then delete_static_route"),
    "interface_ids": (
        "service interface",
        "on the 'default' locale-service; NSX UI: the Tier-1's Service Interfaces",
    ),
    "locale_service_ids": (
        "locale-service other than 'default'",
        "this delete removes only 'default'; remove the others in NSX",
    ),
    "ipsec_vpn_service_ids": ("IPsec VPN service", "NSX UI: Networking > VPN"),
    "l2vpn_service_ids": ("L2 VPN service", "NSX UI: Networking > VPN"),
    "dns_forwarder_ids": ("DNS forwarder", "NSX UI: Networking > DNS"),
    "lb_service_ids": (
        "load balancer service",
        "attached by connectivity_path; NSX UI: Networking > Load Balancing",
    ),
}


def _unless_absent(read: Any) -> Any:
    """Run one pre-flight read; a 404 means the section does not exist -> None.

    Any other failure raises: "could not look" must never read as "nothing
    there", because the caller would then delete.
    """
    from vmware_nsx.connection import NsxApiError

    try:
        return read()
    except NsxApiError as exc:
        if exc.status_code != 404:
            raise
        return None


def _ids(rows: Any) -> list[str]:
    return [sanitize(str(r.get("id", ""))) for r in (rows or [])][:_BLOCKER_SAMPLE]


def tier1_delete_blockers(client: NsxClient, tier1_id: str) -> dict[str, list[str]]:
    """What still depends on a Tier-1 and would make its DELETE fail. Read-only.

    Any of these makes the final DELETE fail, and by then the locale-service
    (the edge-cluster binding) is already gone — so they are checked first and
    a refusal changes nothing. Returns ``{"<kind>_ids": [...]}`` for each kind
    present (at most ``_BLOCKER_SAMPLE`` ids each); empty means clear to delete.

    A read that fails raises; a 404 on a dependent collection means the gateway
    (or this NSX) never had that section. Each path is written out in full with
    only the id interpolated, so the spec-conformance test can verify it — a
    misspelt child would otherwise 404 and be read as "none there".
    """
    _validate_id(tier1_id)
    gw_path = f"/infra/tier-1s/{tier1_id}"

    segments = client.get_all("/policy/api/v1/infra/segments", **_WALK)
    # 404 here means this NSX has no native load balancer API at all.
    lb_services = _unless_absent(lambda: client.get_all("/policy/api/v1/infra/lb-services", **_WALK))
    locale_services = _unless_absent(
        lambda: client.get_all(f"/policy/api/v1/infra/tier-1s/{tier1_id}/locale-services", **_WALK)
    )
    # A singleton, not a collection: 404 = none configured, anything else = present.
    dns_forwarder = _unless_absent(
        lambda: client.get(f"/policy/api/v1/infra/tier-1s/{tier1_id}/dns-forwarder")
    )

    blockers = {
        "segment_ids": _ids(s for s in segments if s.get("connectivity_path") == gw_path),
        "tier1_segment_ids": _ids(_unless_absent(
            lambda: client.get_all(f"/policy/api/v1/infra/tier-1s/{tier1_id}/segments", **_SAMPLE)
        )),
        "nat_rule_ids": _ids(_unless_absent(
            lambda: client.get_all(f"/policy/api/v1/infra/tier-1s/{tier1_id}/nat/USER/nat-rules", **_SAMPLE)
        )),
        "static_route_ids": _ids(_unless_absent(
            lambda: client.get_all(f"/policy/api/v1/infra/tier-1s/{tier1_id}/static-routes", **_SAMPLE)
        )),
        "interface_ids": _ids(_unless_absent(
            lambda: client.get_all(
                f"/policy/api/v1/infra/tier-1s/{tier1_id}/locale-services/default/interfaces", **_SAMPLE
            )
        )),
        "locale_service_ids": _ids(ls for ls in (locale_services or []) if ls.get("id") != "default"),
        "ipsec_vpn_service_ids": _ids(_unless_absent(
            lambda: client.get_all(f"/policy/api/v1/infra/tier-1s/{tier1_id}/ipsec-vpn-services", **_SAMPLE)
        )),
        "l2vpn_service_ids": _ids(_unless_absent(
            lambda: client.get_all(f"/policy/api/v1/infra/tier-1s/{tier1_id}/l2vpn-services", **_SAMPLE)
        )),
        "dns_forwarder_ids": (
            [] if dns_forwarder is None
            else [sanitize(str(dns_forwarder.get("id") or "dns-forwarder"))]
        ),
        "lb_service_ids": _ids(lb for lb in (lb_services or []) if lb.get("connectivity_path") == gw_path),
    }
    return {k: v for k, v in blockers.items() if v}


def tier1_refusal_message(tier1_id: str, blockers: dict[str, list[str]]) -> str:
    """Teaching text for a refused Tier-1 delete: what blocks, and where to look."""
    counts = []
    hints = []
    for key, (label, hint) in _BLOCKER_KINDS.items():
        ids = blockers.get(key)
        if not ids:
            continue
        n = f"{len(ids)}+" if len(ids) >= _BLOCKER_SAMPLE else str(len(ids))
        counts.append(f"{n} {label}(s) [{', '.join(ids)}]")
        hints.append(f"{label}: {hint}")
    return (
        f"Tier-1 '{tier1_id}' still has {'; '.join(counts)}. Nothing was deleted. "
        f"Remove or detach them first, then retry. Where to look — {'; '.join(hints)}."
    )


def delete_tier1_gateway(client: NsxClient, tier1_id: str) -> dict:
    """Delete a Tier-1 gateway (removing its default locale-service first).

    The Policy API refuses to delete a Tier-1 that still has children;
    create_tier1_gateway may have created a "default" locale-service for
    the edge cluster binding, so it is deleted first (404 ignored).

    Refuses — without deleting anything — while anything in
    ``tier1_delete_blockers`` remains: those made the final DELETE fail after
    the locale-service was already gone, leaving a gateway with no edge binding.

    Args:
        client: Authenticated NSX API client.
        tier1_id: Tier-1 gateway identifier to delete.

    Returns:
        Dict with deletion status; on refusal ``deleted`` is False, ``error``
        says what blocks and where to look, and the blocking ids are listed
        under ``<kind>_ids``.
    """
    from vmware_nsx.connection import NsxApiError

    _validate_id(tier1_id)

    blockers = tier1_delete_blockers(client, tier1_id)
    if blockers:
        return {
            "deleted": False,
            "tier1_id": tier1_id,
            "error": tier1_refusal_message(tier1_id, blockers),
            **blockers,
        }

    path = f"/policy/api/v1/infra/tier-1s/{tier1_id}"
    try:
        client.delete(f"{path}/locale-services/default")
    except NsxApiError as exc:
        if exc.status_code != 404:
            raise
    client.delete(path)
    _log.info("Deleted Tier-1 gateway %s", tier1_id)
    return {"deleted": True, "tier1_id": tier1_id}


# ---------------------------------------------------------------------------
# Tier-0 BGP Configuration
# ---------------------------------------------------------------------------


def configure_tier0_bgp(
    client: NsxClient,
    tier0_id: str,
    locale_service_id: str,
    bgp_config: dict[str, Any],
) -> dict:
    """Update BGP configuration on a Tier-0 gateway's locale-service.

    Args:
        client: Authenticated NSX API client.
        tier0_id: Tier-0 gateway identifier.
        locale_service_id: Locale-service identifier (typically "default").
        bgp_config: BGP configuration dict. Supported keys:
            - local_as_num (str): Local AS number.
            - enabled (bool): Enable/disable BGP.
            - inter_sr_ibgp (bool): Inter-SR iBGP.
            - ecmp (bool): ECMP enabled.
            - graceful_restart_config (dict): Graceful restart settings.

    Returns:
        Updated BGP config dict from NSX API.
    """
    _validate_id(tier0_id)
    _validate_id(locale_service_id)

    allowed_keys = {
        "local_as_num",
        "enabled",
        "inter_sr_ibgp",
        "ecmp",
        "graceful_restart_config",
    }
    body: dict[str, Any] = {}
    for key, value in bgp_config.items():
        if key not in allowed_keys:
            raise ValueError(
                f"BGP config key '{key}' is not allowed. Must be one of: "
                f"{', '.join(sorted(allowed_keys))}. Pass only those to "
                "configure_tier0_bgp; BGP neighbours are a separate object this "
                "skill does not create."
            )
        body[key] = value

    if not body:
        raise ValueError(
            "configure_tier0_bgp was called with an empty bgp_config. Pass at least "
            f"one of: {', '.join(sorted(allowed_keys))}. Run get_bgp_neighbors to see "
            "the Tier-0's current BGP state first."
        )

    path = (
        f"/policy/api/v1/infra/tier-0s/{tier0_id}"
        f"/locale-services/{locale_service_id}/bgp"
    )
    result = client.patch(path, body)
    _log.info(
        "Updated BGP config on Tier-0 %s / locale-service %s: %s",
        tier0_id,
        locale_service_id,
        list(body.keys()),
    )
    return result

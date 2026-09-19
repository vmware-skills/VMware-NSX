"""The blast-radius gate in front of the five NSX deletes (HLD §7, revised 2026-09-16).

The ops delete functions (``segment_mgmt.delete_segment`` and friends) stay the
executors the CLI calls, with every refusal they already had. This module is
what the MCP tools put in front of them:

* ``*_delete_blast_radius`` reads what a delete would remove and what stands in
  its way (L1). A bare MCP call returns it and deletes nothing (L2).
* ``refuse_unless_clear`` raises :class:`DeleteRefusedError` when the radius has
  a blocker or a field that could not be read (L3). "Could not look" is never
  read as "nothing there".

Only endpoints the repo already calls are read, so the spec-conformance test
keeps holding: NAT rules, static routes and IP pools are found by walking their
collection (the GETs ``list_*`` already make), not by a per-object GET.

The object itself answering 404 is not an unmeasured field — it means there is
nothing to delete, and the ``NsxApiError`` (or a ``ValueError`` naming the list
tool) propagates as the teaching error it already is.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from vmware_policy import sanitize

from vmware_nsx.connection import NsxApiError
from vmware_nsx.ops.networking import get_ip_pool_usage
from vmware_nsx.ops.segment_mgmt import (
    _WALK,
    _validate_id,
    segment_delete_blockers,
    segment_refusal_message,
    tier1_delete_blockers,
    tier1_refusal_message,
)

if TYPE_CHECKING:
    from vmware_nsx.connection import NsxClient

#: Identifiers listed individually in a blast radius; the counts cover the rest.
MAX_LISTED = 16


class DeleteRefusedError(ValueError):
    """A confirmed delete refused: a blocker, or a blast radius that could not be read.

    A ``ValueError`` so ``_safe_error`` passes the teaching text through; it
    carries the radius so the refusal envelope can show what was measured.
    """

    def __init__(self, message: str, blast_radius: dict[str, Any]) -> None:
        super().__init__(message)
        self.blast_radius = blast_radius


class _Unmeasured:
    """Sentinel for a read that failed for a reason other than 404."""


_UNMEASURED = _Unmeasured()


def _read(fn: Callable[[], Any]) -> Any:
    """Run one measurement read. 404 raises (nothing to delete); other API failures -> _UNMEASURED."""
    try:
        return fn()
    except NsxApiError as exc:
        if exc.status_code == 404:
            raise
        return _UNMEASURED


def _read_optional(fn: Callable[[], Any]) -> Any:
    """A dependent read where 404 means "none" rather than "no such object"."""
    try:
        return fn()
    except NsxApiError as exc:
        if exc.status_code == 404:
            return None
        return _UNMEASURED


def _s(value: Any, limit: int = 200) -> str:
    return sanitize(str(value), limit) if value not in (None, "") else ""


def _find(rows: list[dict], object_id: str) -> dict | None:
    return next((r for r in rows if r.get("id") == object_id), None)


def _finish(radius: dict[str, Any], unmeasured: list[str], blockers: list[str]) -> dict[str, Any]:
    return {**radius, "blockers": blockers, "unmeasured": unmeasured}


def refuse_unless_clear(tool: str, radius: dict[str, Any]) -> None:
    """Raise :class:`DeleteRefusedError` unless the radius is fully measured and unblocked."""
    if radius["blockers"]:
        raise DeleteRefusedError(" ".join(radius["blockers"]), radius)
    if radius["unmeasured"]:
        raise DeleteRefusedError(
            f"{tool} refused: could not read {', '.join(radius['unmeasured'])}, so what "
            "the delete would remove is unknown. Nothing was deleted. Run 'vmware-nsx "
            "doctor' to check connectivity and permissions, then preview again.",
            radius,
        )


def preview(radius: dict[str, Any]) -> dict[str, Any]:
    """The L2 response: the blast radius, and nothing changed."""
    if radius["blockers"] or radius["unmeasured"]:
        hint = ("Nothing was deleted. confirm=True will be refused until the blockers "
                "are cleared and every field is measured; show blast_radius to the user.")
    else:
        hint = ("Nothing was deleted. Show blast_radius to the user; to delete, call again "
                "with confirm=True once they have decided.")
    return {"action": "preview", "blast_radius": radius, "hint": hint}


# ---------------------------------------------------------------------------
# Segment
# ---------------------------------------------------------------------------


def segment_delete_blast_radius(client: NsxClient, segment_id: str) -> dict[str, Any]:
    """The segment's identity, gateway, subnets and attached ports."""
    _validate_id(segment_id)
    unmeasured: list[str] = []
    seg = _read(lambda: client.get(f"/policy/api/v1/infra/segments/{segment_id}"))
    if seg is _UNMEASURED:
        unmeasured.append("segment")
        seg = {}
    ports = _read(lambda: segment_delete_blockers(client, segment_id))
    if ports is _UNMEASURED:
        unmeasured.append("ports")
    blockers = [segment_refusal_message(ports)] if ports and ports is not _UNMEASURED else []
    measured_ports = ports if isinstance(ports, dict) else None
    radius = {
        "segment_id": segment_id,
        "display_name": _s(seg.get("display_name")),
        "path": _s(seg.get("path")),
        "gateway": _s(seg.get("connectivity_path")) or None,
        "transport_zone_path": _s(seg.get("transport_zone_path")) or None,
        "subnets": [_s(s.get("gateway_address")) for s in seg.get("subnets") or []][:MAX_LISTED],
        "port_count": None if measured_ports is None else measured_ports.get("port_count", 0),
        "port_ids": [] if measured_ports is None else measured_ports.get("port_ids", []),
    }
    return _finish(radius, unmeasured, blockers)


# ---------------------------------------------------------------------------
# Tier-1 gateway
# ---------------------------------------------------------------------------


def tier1_delete_blast_radius(client: NsxClient, tier1_id: str) -> dict[str, Any]:
    """The gateway, the edge binding its delete removes, and everything that depends on it."""
    _validate_id(tier1_id)
    unmeasured: list[str] = []
    gw = _read(lambda: client.get(f"/policy/api/v1/infra/tier-1s/{tier1_id}"))
    if gw is _UNMEASURED:
        unmeasured.append("tier1_gateway")
        gw = {}
    locale = _read_optional(
        lambda: client.get_all(f"/policy/api/v1/infra/tier-1s/{tier1_id}/locale-services", **_WALK)
    )
    if locale is _UNMEASURED:
        unmeasured.append("locale_services")
        locale = None
    default_ls = _find(locale or [], "default")
    dependents = _read(lambda: tier1_delete_blockers(client, tier1_id))
    if dependents is _UNMEASURED:
        unmeasured.append("dependents")
        dependents = None
    radius = {
        "tier1_id": tier1_id,
        "display_name": _s(gw.get("display_name")),
        "path": _s(gw.get("path")) or f"/infra/tier-1s/{tier1_id}",
        "tier0_path": _s(gw.get("tier0_path")) or None,
        "removes_locale_service": "default" if default_ls else None,
        "edge_cluster_path": _s((default_ls or {}).get("edge_cluster_path")) or None,
        # Up to 10 ids per kind (the ops pre-flight's sample): a count of 10
        # means "10 or more", which is enough to refuse on.
        "dependents": dependents,
        "dependent_counts": None if dependents is None else {k: len(v) for k, v in dependents.items()},
    }
    blockers = [tier1_refusal_message(tier1_id, dependents)] if dependents else []
    return _finish(radius, unmeasured, blockers)


# ---------------------------------------------------------------------------
# NAT rule
# ---------------------------------------------------------------------------


def nat_rule_delete_blast_radius(client: NsxClient, tier1_id: str, rule_id: str) -> dict[str, Any]:
    """The rule's gateway and what it matches and translates."""
    _validate_id(tier1_id)
    _validate_id(rule_id)
    rows = _read(lambda: client.get_all(
        f"/policy/api/v1/infra/tier-1s/{tier1_id}/nat/USER/nat-rules", **_WALK
    ))
    unmeasured = ["nat_rule"] if rows is _UNMEASURED else []
    rule: dict = {}
    if not unmeasured:
        found = _find(rows, rule_id)
        if found is None:
            raise ValueError(
                f"NAT rule '{rule_id}' is not on Tier-1 '{tier1_id}' (USER section). Nothing "
                f"was deleted. Run list_nat_rules on '{tier1_id}' for the exact rule_id."
            )
        rule = found
    radius = {
        "tier1_id": tier1_id,
        "gateway_path": f"/infra/tier-1s/{tier1_id}",
        "rule_id": rule_id,
        "display_name": _s(rule.get("display_name")),
        "action": _s(rule.get("action")) or None,
        "source_network": _s(rule.get("source_network")) or None,
        "destination_network": _s(rule.get("destination_network")) or None,
        "translated_network": _s(rule.get("translated_network")) or None,
        "translated_ports": _s(rule.get("translated_ports")) or None,
        "enabled": rule.get("enabled") if rule else None,
    }
    return _finish(radius, unmeasured, [])


# ---------------------------------------------------------------------------
# Static route
# ---------------------------------------------------------------------------


def static_route_delete_blast_radius(
    client: NsxClient, gateway_id: str, route_id: str, gateway_type: str = "tier1"
) -> dict[str, Any]:
    """The route's gateway, destination network and next hops."""
    _validate_id(gateway_id)
    _validate_id(route_id)
    gw_resource = "tier-0s" if gateway_type == "tier0" else "tier-1s"
    rows = _read(lambda: client.get_all(
        f"/policy/api/v1/infra/{gw_resource}/{gateway_id}/static-routes", **_WALK
    ))
    unmeasured = ["static_route"] if rows is _UNMEASURED else []
    route: dict = {}
    if not unmeasured:
        found = _find(rows, route_id)
        if found is None:
            raise ValueError(
                f"Static route '{route_id}' is not on {gateway_type} gateway '{gateway_id}'. "
                f"Nothing was deleted. Run list_static_routes on '{gateway_id}' with "
                f"gateway_type='{gateway_type}' for the exact route_id (a Tier-0 route "
                "needs gateway_type='tier0')."
            )
        route = found
    radius = {
        "gateway_id": gateway_id,
        "gateway_type": gateway_type,
        "gateway_path": f"/infra/{gw_resource}/{gateway_id}",
        "route_id": route_id,
        "display_name": _s(route.get("display_name")),
        "network": _s(route.get("network")) or None,
        "next_hops": [
            {"ip_address": _s(nh.get("ip_address")), "admin_distance": nh.get("admin_distance", 1)}
            for nh in (route.get("next_hops") or [])[:MAX_LISTED]
        ],
    }
    return _finish(radius, unmeasured, [])


# ---------------------------------------------------------------------------
# IP pool
# ---------------------------------------------------------------------------


def _realized_allocations(pool_usage: Any) -> int | None:
    """NSX's own allocated count (``pool_usage.allocated_ip_allocations``), or None.

    This counts allocations Policy ``ip-allocations`` never lists — e.g. a TEP
    pool's addresses held by transport nodes. Absent or not a non-negative
    integer means the count was not measured, never zero.
    """
    if not isinstance(pool_usage, dict):
        return None
    value = pool_usage.get("allocated_ip_allocations")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def ip_pool_delete_blast_radius(client: NsxClient, pool_id: str) -> dict[str, Any]:
    """The pool's size and every address still allocated from it."""
    _validate_id(pool_id)
    rows = _read(lambda: client.get_all("/policy/api/v1/infra/ip-pools", **_WALK))
    unmeasured: list[str] = []
    pool: dict = {}
    if rows is _UNMEASURED:
        unmeasured.append("ip_pool")
    else:
        found = _find(rows, pool_id)
        if found is None:
            raise ValueError(
                f"IP pool '{pool_id}' does not exist on this target. Nothing was deleted. "
                "Run list_ip_pools for the exact pool_id."
            )
        pool = found
    usage = _read(lambda: get_ip_pool_usage(client, pool_id, limit=MAX_LISTED))
    if usage is _UNMEASURED:
        unmeasured.append("allocations")
        usage = None
    count = None if usage is None else usage["allocation_count"]
    ips = [] if usage is None else [
        a["allocation_ip"] or a["id"] for a in usage["allocations"]
    ][:MAX_LISTED]
    blockers = []
    if count:
        blockers.append(
            f"IP pool '{pool_id}' still has {count} allocated IP(s) "
            f"[{', '.join(ips)}{', …' if count > len(ips) else ''}]. Nothing was deleted. "
            "Release them from their consumers first (get_ip_pool_usage lists them), "
            "then preview again."
        )
    realized = _realized_allocations(pool.get("pool_usage"))
    if realized is None:
        unmeasured.append("pool_usage")
    elif realized and not count:
        blockers.append(
            f"IP pool '{pool_id}' still has {realized} allocated IP(s) by NSX's pool_usage "
            "(allocated_ip_allocations), though none are listed as Policy ip-allocations — "
            "e.g. TEP addresses held by transport nodes. Nothing was deleted. Move those "
            "consumers to another pool first; NSX keeps a released IP counted for its release "
            "delay (2 minutes by default), then preview again."
        )
    radius = {
        "pool_id": pool_id,
        "display_name": _s(pool.get("display_name")),
        "pool_usage": pool.get("pool_usage") if isinstance(pool.get("pool_usage"), dict) else None,
        "allocation_count": count,
        "realized_allocation_count": realized,
        "allocated_ips": ips,
    }
    return _finish(radius, unmeasured, blockers)

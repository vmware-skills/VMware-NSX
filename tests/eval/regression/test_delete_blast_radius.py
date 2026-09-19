"""The five NSX deletes preview by default and state their blast radius (HLD §7, 2026-09-16).

* L1 — every response carries ``blast_radius``: what the delete removes, with
  counts, identifiers, ``blockers`` and ``unmeasured``.
* L2 — a bare call (``confirm`` left at its default ``False``) makes no DELETE.
* L3 — ``confirm=True`` is refused when there is a blocker (attached ports,
  Tier-1 dependents, allocated IPs) or when a read the radius depends on
  failed. "Could not look" is never "nothing there".

Every case drives the real gate and the real ops executor through a fake NSX
client that answers by exact path and records every DELETE, so a refusal is
asserted as "no DELETE was made", not as a message.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from tests.eval.regression import _tier1_fake as t1f
from vmware_nsx.connection import NsxApiError

API = "/policy/api/v1"
SEG = f"{API}/infra/segments/seg-web"
PORTS = f"{SEG}/ports"
T1 = f"{API}/infra/tier-1s/t1-web"
NAT = f"{T1}/nat/USER/nat-rules"
ROUTES_T1 = f"{T1}/static-routes"
ROUTES_T0 = f"{API}/infra/tier-0s/t0-core/static-routes"
POOLS = f"{API}/infra/ip-pools"
ALLOCS = f"{POOLS}/pool-1/ip-allocations"


def _err(path: str, status: int) -> NsxApiError:
    return NsxApiError(f"GET {path} returned HTTP {status}.", status_code=status, method="GET", path=path)


class FakeNsx:
    """Answers GETs by exact path; an unseeded object is a 404, an unseeded collection empty."""

    def __init__(self, objects=None, collections=None, fail=None) -> None:
        self.objects: dict[str, dict] = dict(objects or {})
        self.collections: dict[str, list[dict]] = dict(collections or {})
        self.fail: dict[str, Exception] = dict(fail or {})
        self.deleted: list[str] = []

    def _check(self, path: str) -> None:
        if path in self.fail:
            raise self.fail[path]

    def get(self, path: str, params: Any = None, **_: Any) -> dict:
        self._check(path)
        if params and params.get("page_size") == 1:  # get_count
            return {"result_count": len(self.collections.get(path, []))}
        if path in self.objects:
            return self.objects[path]
        raise _err(path, 404)

    def get_all(self, path: str, *_: Any, **k: Any) -> list[dict]:
        self._check(path)
        rows = list(self.collections.get(path, []))
        return rows[: k["limit"]] if k.get("limit") else rows

    def get_count(self, path: str, *_: Any, **__: Any) -> int:
        self._check(path)
        return len(self.collections.get(path, []))

    def delete(self, path: str) -> None:
        self.deleted.append(path)

    def put(self, *a: Any, **k: Any) -> dict:  # pragma: no cover - a delete must never write
        raise AssertionError("a delete must not PUT")

    patch = post = put


@pytest.fixture
def policy_rows(monkeypatch):
    rows: list[dict] = []

    class _Recorder:
        def log(self, **kw):
            rows.append(kw)

    monkeypatch.setattr("vmware_policy.guard.get_engine", lambda: _Recorder())
    return rows


@pytest.fixture
def skill_log(monkeypatch):
    rows: list[dict] = []

    class _Recorder:
        def log(self, **kw):
            rows.append(kw)

    monkeypatch.setattr("vmware_nsx.mcp_server._write_audit._audit", _Recorder())
    return rows


def _call(client, tool: str, **kwargs):
    import vmware_nsx.mcp_server.server as srv

    with patch.object(srv, "_get_connection", return_value=client):
        return getattr(srv, tool)(**kwargs)


# ── fixtures per tool ───────────────────────────────────────────────────


def _segment(ports=()):
    return FakeNsx(
        objects={SEG: {"id": "seg-web", "display_name": "web", "path": "/infra/segments/seg-web",
                       "connectivity_path": "/infra/tier-1s/t1-web",
                       "subnets": [{"gateway_address": "10.0.1.1/24"}]}},
        collections={PORTS: [{"id": p} for p in ports]},
    )


def _tier1(**collections):
    base = {t1f.LOCALE_SERVICES: [{"id": "default", "edge_cluster_path": "/infra/sites/default/ec-1"}]}
    client = t1f.FakeNsx(collections={**base, **collections},
                         objects={t1f.BASE: {"id": t1f.T1, "display_name": "T1 web",
                                             "tier0_path": "/infra/tier-0s/t0-core"}})
    return client


def _nat():
    return FakeNsx(collections={NAT: [
        {"id": "other", "action": "SNAT"},
        {"id": "dnat-web", "display_name": "web in", "action": "DNAT",
         "destination_network": "203.0.113.10", "translated_network": "10.0.1.20",
         "translated_ports": "443", "enabled": True},
    ]})


def _route(collection=ROUTES_T1):
    return FakeNsx(collections={collection: [
        {"id": "r-default", "display_name": "default", "network": "0.0.0.0/0",
         "next_hops": [{"ip_address": "10.0.0.1", "admin_distance": 1}]},
    ]})


_NO_USAGE = object()


def _pool(allocations=(), realized=None, usage=None):
    """pool-1 with Policy ``allocations``; ``realized`` overrides NSX's allocated count.

    ``pool_usage`` uses NSX's field names (SDK PolicyPoolUsage): allocations
    realized outside Policy ip-allocations (e.g. a TEP pool used by transport
    nodes) show up only in ``allocated_ip_allocations``.
    """
    allocated = len(allocations) if realized is None else realized
    pool_usage = {"total_ips": 50, "allocated_ip_allocations": allocated,
                  "requested_ip_allocations": len(allocations), "available_ips": 50 - allocated}
    row = {"id": "pool-1", "display_name": "TEP pool"}
    if usage is not _NO_USAGE:
        row["pool_usage"] = pool_usage if usage is None else usage
    return FakeNsx(collections={
        POOLS: [{"id": "pool-0"}, row],
        ALLOCS: [{"id": f"a{i}", "allocation_ip": ip} for i, ip in enumerate(allocations)],
    })


# (tool, kwargs, client factory producing a clean target, the DELETE paths expected)
CLEAN = [
    ("delete_segment", {"segment_id": "seg-web"}, lambda: _segment(), [SEG]),
    ("delete_tier1_gateway", {"tier1_id": t1f.T1}, lambda: _tier1(),
     [f"{t1f.BASE}/locale-services/default", t1f.BASE]),
    ("delete_nat_rule", {"tier1_id": "t1-web", "rule_id": "dnat-web"}, _nat, [f"{NAT}/dnat-web"]),
    ("delete_static_route", {"tier1_id": "t1-web", "route_id": "r-default"}, lambda: _route(),
     [f"{ROUTES_T1}/r-default"]),
    ("delete_ip_pool", {"pool_id": "pool-1"}, lambda: _pool(), [f"{POOLS}/pool-1"]),
]
IDS = [c[0] for c in CLEAN]


# ── L2: a bare call deletes nothing ─────────────────────────────────────


@pytest.mark.parametrize(("tool", "kwargs", "make", "_paths"), CLEAN, ids=IDS)
def test_bare_call_previews_and_deletes_nothing(tool, kwargs, make, _paths, skill_log):
    client = make()
    out = _call(client, tool, **kwargs)
    assert out["action"] == "preview", out
    assert client.deleted == []
    br = out["blast_radius"]
    assert br["blockers"] == [] and br["unmeasured"] == []
    assert [r["result"] for r in skill_log] == ["preview"], "a preview must not be logged as a delete"


@pytest.mark.parametrize(("tool", "kwargs", "make", "_paths"), CLEAN, ids=IDS)
def test_confirm_false_is_the_same_as_bare(tool, kwargs, make, _paths):
    client = make()
    assert _call(client, tool, confirm=False, **kwargs)["action"] == "preview"
    assert client.deleted == []


@pytest.mark.parametrize(("tool", "kwargs", "make", "_paths"), CLEAN, ids=IDS)
def test_a_truthy_non_true_confirm_previews(tool, kwargs, make, _paths):
    """Only True acts: a positional target landing in confirm must not delete."""
    client = make()
    assert _call(client, tool, confirm="nsx-dc2", **kwargs)["action"] == "preview"
    assert client.deleted == []


# ── L1 + acting: confirm=True deletes once and says what ─────────────────


@pytest.mark.parametrize(("tool", "kwargs", "make", "paths"), CLEAN, ids=IDS)
def test_confirm_deletes_once_and_returns_the_blast_radius(tool, kwargs, make, paths, policy_rows, skill_log):
    client = make()
    out = _call(client, tool, confirm=True, **kwargs)
    assert out["action"] == "deleted", out
    assert client.deleted == paths
    assert out["blast_radius"]["blockers"] == []
    assert [r["status"] for r in policy_rows] == ["ok"]
    assert [r["result"] for r in skill_log] == ["ok"]


def test_segment_preview_measures_gateway_subnets_and_ports():
    br = _call(_segment(ports=("vm-a-vnic0", "vm-b-vnic0")), "delete_segment", segment_id="seg-web")["blast_radius"]
    assert br["display_name"] == "web"
    assert br["gateway"] == "/infra/tier-1s/t1-web"
    assert br["subnets"] == ["10.0.1.1/24"]
    assert br["port_count"] == 2
    assert br["port_ids"] == ["vm-a-vnic0", "vm-b-vnic0"]


def test_tier1_preview_measures_identity_edge_binding_and_dependents():
    client = _tier1(**{t1f.NAT: [{"id": "snat-1"}], t1f.SEGMENTS: [{"id": "web-seg", "connectivity_path": t1f.GW}]})
    br = _call(client, "delete_tier1_gateway", tier1_id=t1f.T1)["blast_radius"]
    assert br["display_name"] == "T1 web"
    assert br["tier0_path"] == "/infra/tier-0s/t0-core"
    assert br["removes_locale_service"] == "default"
    assert br["edge_cluster_path"] == "/infra/sites/default/ec-1"
    assert br["dependents"] == {"segment_ids": ["web-seg"], "nat_rule_ids": ["snat-1"]}
    assert br["dependent_counts"] == {"segment_ids": 1, "nat_rule_ids": 1}


def test_nat_preview_measures_gateway_and_match():
    br = _call(_nat(), "delete_nat_rule", tier1_id="t1-web", rule_id="dnat-web")["blast_radius"]
    assert br["gateway_path"] == "/infra/tier-1s/t1-web"
    assert (br["action"], br["destination_network"], br["translated_network"], br["translated_ports"]) == (
        "DNAT", "203.0.113.10", "10.0.1.20", "443")
    assert br["enabled"] is True and br["display_name"] == "web in"


def test_route_preview_measures_gateway_network_and_next_hops():
    br = _call(_route(ROUTES_T0), "delete_static_route", tier1_id="t0-core", route_id="r-default",
               gateway_type="tier0")["blast_radius"]
    assert br["gateway_path"] == "/infra/tier-0s/t0-core"
    assert br["network"] == "0.0.0.0/0"
    assert br["next_hops"] == [{"ip_address": "10.0.0.1", "admin_distance": 1}]


def test_pool_preview_measures_usage_and_allocations():
    br = _call(_pool(("10.9.0.5", "10.9.0.6")), "delete_ip_pool", pool_id="pool-1")["blast_radius"]
    assert br["display_name"] == "TEP pool"
    assert br["pool_usage"]["total_ips"] == 50
    assert br["allocation_count"] == 2
    assert br["realized_allocation_count"] == 2
    assert br["allocated_ips"] == ["10.9.0.5", "10.9.0.6"]


# ── L3: blockers refuse, and the refusal reaches the caller ─────────────


def _assert_refused(out, client, policy_rows, skill_log, *needles):
    assert "error" in out, out
    assert client.deleted == [], "a refusal made a DELETE"
    for n in needles:
        assert n in out["error"], (n, out["error"])
    assert "blast_radius" in out, "the refusal must show what it measured"
    assert [r["status"] for r in policy_rows] == ["error"]
    assert [r["result"] for r in skill_log] == ["error"]


def test_segment_with_ports_is_refused_with_the_existing_message(policy_rows, skill_log):
    client = _segment(ports=("vm-a-vnic0", "vm-b-vnic0"))
    preview = _call(client, "delete_segment", segment_id="seg-web")
    assert preview["blast_radius"]["blockers"]
    policy_rows.clear()
    skill_log.clear()
    out = _call(client, "delete_segment", segment_id="seg-web", confirm=True)
    _assert_refused(out, client, policy_rows, skill_log,
                    "Segment has 2 active port(s)", "vm-a-vnic0", "Detach all ports")


def test_tier1_with_dependents_is_refused_and_the_long_message_survives(policy_rows, skill_log):
    kinds = {t1f.SEGMENTS: [{"id": f"seg-{i}", "connectivity_path": t1f.GW} for i in range(12)],
             t1f.NAT: [{"id": f"nat-{i}"} for i in range(12)], t1f.IPSEC: [{"id": "vpn-1"}],
             t1f.ROUTES: [{"id": "r-1"}]}
    client = _tier1(**kinds)
    preview = _call(client, "delete_tier1_gateway", tier1_id=t1f.T1)["blast_radius"]
    assert preview["blockers"] and "Where to look" in preview["blockers"][0]
    policy_rows.clear()
    skill_log.clear()
    out = _call(client, "delete_tier1_gateway", tier1_id=t1f.T1, confirm=True)
    # Past 300 characters: the sanitizer's usual cap would cut the remedy off.
    assert len(out["error"]) > 300
    _assert_refused(out, client, policy_rows, skill_log,
                    "seg-0", "vpn-1", "Nothing was deleted", "Where to look")


def test_pool_with_allocations_is_refused(policy_rows, skill_log):
    client = _pool(("10.9.0.5",))
    assert _call(client, "delete_ip_pool", pool_id="pool-1")["blast_radius"]["blockers"]
    policy_rows.clear()
    skill_log.clear()
    out = _call(client, "delete_ip_pool", pool_id="pool-1", confirm=True)
    _assert_refused(out, client, policy_rows, skill_log, "1 allocated IP", "10.9.0.5", "get_ip_pool_usage")


def test_pool_with_only_realized_allocations_is_refused(policy_rows, skill_log):
    """A TEP pool: no Policy ip-allocations, but NSX counts 3 allocated IPs."""
    client = _pool(realized=3)
    br = _call(client, "delete_ip_pool", pool_id="pool-1")["blast_radius"]
    assert br["allocation_count"] == 0
    assert br["realized_allocation_count"] == 3
    assert br["blockers"] and br["unmeasured"] == []
    policy_rows.clear()
    skill_log.clear()
    out = _call(client, "delete_ip_pool", pool_id="pool-1", confirm=True)
    _assert_refused(out, client, policy_rows, skill_log, "3 allocated IP", "pool_usage", "Nothing was deleted")


@pytest.mark.parametrize("usage", [_NO_USAGE, {}, {"allocated_ip_allocations": "3"},
                                   {"allocated_ip_allocations": True}, {"allocated_ip_allocations": -1},
                                   "not-a-dict"],
                         ids=["absent", "empty", "string", "bool", "negative", "not-a-dict"])
def test_pool_without_a_readable_usage_is_unmeasured_and_refused(usage, policy_rows, skill_log):
    client = _pool(usage=usage)
    br = _call(client, "delete_ip_pool", pool_id="pool-1")["blast_radius"]
    assert "pool_usage" in br["unmeasured"]
    assert br["realized_allocation_count"] is None
    policy_rows.clear()
    skill_log.clear()
    out = _call(client, "delete_ip_pool", pool_id="pool-1", confirm=True)
    _assert_refused(out, client, policy_rows, skill_log, "could not read pool_usage", "Nothing was deleted")


def test_pool_with_both_counts_zero_is_deleted():
    client = _pool(realized=0)
    br = _call(client, "delete_ip_pool", pool_id="pool-1")["blast_radius"]
    assert (br["allocation_count"], br["realized_allocation_count"]) == (0, 0)
    assert br["blockers"] == [] and br["unmeasured"] == []
    out = _call(client, "delete_ip_pool", pool_id="pool-1", confirm=True)
    assert out["action"] == "deleted" and client.deleted == [f"{POOLS}/pool-1"]


# ── L3: an unreadable field refuses ─────────────────────────────────────


UNREADABLE = [
    ("delete_segment", {"segment_id": "seg-web"}, lambda: _segment(), PORTS, "ports"),
    ("delete_segment", {"segment_id": "seg-web"}, lambda: _segment(), SEG, "segment"),
    ("delete_tier1_gateway", {"tier1_id": t1f.T1}, lambda: _tier1(), t1f.IPSEC, "dependents"),
    ("delete_tier1_gateway", {"tier1_id": t1f.T1}, lambda: _tier1(), t1f.LOCALE_SERVICES, "locale_services"),
    ("delete_tier1_gateway", {"tier1_id": t1f.T1}, lambda: _tier1(), t1f.BASE, "tier1_gateway"),
    ("delete_nat_rule", {"tier1_id": "t1-web", "rule_id": "dnat-web"}, _nat, NAT, "nat_rule"),
    ("delete_static_route", {"tier1_id": "t1-web", "route_id": "r-default"}, lambda: _route(), ROUTES_T1,
     "static_route"),
    ("delete_ip_pool", {"pool_id": "pool-1"}, lambda: _pool(), ALLOCS, "allocations"),
    ("delete_ip_pool", {"pool_id": "pool-1"}, lambda: _pool(), POOLS, "ip_pool"),
]


@pytest.mark.parametrize(("tool", "kwargs", "make", "path", "field"), UNREADABLE,
                         ids=[f"{u[0]}-{u[4]}" for u in UNREADABLE])
def test_an_unreadable_field_is_unmeasured_and_refuses(tool, kwargs, make, path, field, policy_rows, skill_log):
    client = make()
    client.fail[path] = _err(path, 500)
    preview = _call(client, tool, **kwargs)
    assert preview["action"] == "preview"
    assert field in preview["blast_radius"]["unmeasured"]
    policy_rows.clear()
    skill_log.clear()
    out = _call(client, tool, confirm=True, **kwargs)
    _assert_refused(out, client, policy_rows, skill_log, f"could not read {field}", "Nothing was deleted")


# ── not found is an error, not a preview of nothing ─────────────────────


@pytest.mark.parametrize(("tool", "kwargs", "make", "needle"), [
    ("delete_nat_rule", {"tier1_id": "t1-web", "rule_id": "nope"}, _nat, "list_nat_rules"),
    ("delete_static_route", {"tier1_id": "t1-web", "route_id": "nope"}, lambda: _route(), "list_static_routes"),
    ("delete_ip_pool", {"pool_id": "nope"}, lambda: _pool(), "list_ip_pools"),
    ("delete_segment", {"segment_id": "nope"}, lambda: _segment(), "404"),
])
def test_a_missing_object_is_an_error_and_deletes_nothing(tool, kwargs, make, needle):
    client = make()
    for confirm in (False, True):
        out = _call(client, tool, confirm=confirm, **kwargs)
        assert needle in out["error"], out
    assert client.deleted == []


# ── the schema advertises the gate ──────────────────────────────────────


@pytest.mark.parametrize("tool", IDS)
def test_schema_defaults_confirm_to_false(tool):
    import vmware_nsx.mcp_server.server as srv

    t = next(t for t in asyncio.run(srv.mcp.list_tools()) if t.name == tool)
    assert t.inputSchema["properties"]["confirm"]["default"] is False
    assert "confirm" not in (t.inputSchema.get("required") or [])
    assert t.inputSchema["properties"]["confirm"]["description"] == (
        "False (default) returns the blast radius and changes nothing. True applies it.")
    desc = " ".join(t.description.split())
    assert "Do not set confirm=True on your own" in desc
    assert t.description.startswith("[WRITE]")

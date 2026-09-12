"""delete_tier1_gateway must refuse BEFORE it changes anything.

It deletes the gateway's "default" locale-service first (the Policy API will
not delete a Tier-1 that still has children), then the gateway. When the
second call failed — a segment still attached, NAT rules or static routes
still under it — the gateway was left without its edge-cluster binding and
nothing was undone. Found 2026-09-11 while checking the docs' claim that
"gateway delete checks for connected segments": it checked nothing.

So the checks run first, and a refusal makes no DELETE call at all. A check
that cannot be completed refuses too: "could not look" is not "nothing there".

The first version checked three dependents. Review found six more that make
the same final DELETE fail — Tier-1-scoped segments, service interfaces on the
default locale-service, IPsec and L2 VPN services, a DNS forwarder, and load
balancer services attached by ``connectivity_path`` — plus locale-services
other than "default", which the delete never removes. Each is checked here in
both directions: present refuses, absent (empty or 404) does not.
"""

from __future__ import annotations

import pytest

from tests.eval.regression import _tier1_fake as f
from vmware_nsx.connection import NsxApiError
from vmware_nsx.ops.segment_mgmt import delete_tier1_gateway, tier1_delete_blockers

# (blocker key, how the fake is seeded, the path that must be read)
_CHILD_COLLECTIONS = [
    ("nat_rule_ids", f.NAT),
    ("static_route_ids", f.ROUTES),
    ("tier1_segment_ids", f.T1_SEGMENTS),
    ("interface_ids", f.INTERFACES),
    ("ipsec_vpn_service_ids", f.IPSEC),
    ("l2vpn_service_ids", f.L2VPN),
]

#: Every GET the pre-flight must make. A new check that is added to the code but
#: not here fails test_every_check_is_made; one listed here but dropped from the
#: code fails the same test from the other side.
_ALL_READS = {
    f.SEGMENTS, f.LB_SERVICES, f.NAT, f.ROUTES, f.T1_SEGMENTS,
    f.LOCALE_SERVICES, f.INTERFACES, f.IPSEC, f.L2VPN, f.DNS_FORWARDER,
}


def test_attached_segment_refuses_and_deletes_nothing():
    client = f.FakeNsx(collections={f.SEGMENTS: [
        {"id": "web-seg", "connectivity_path": f.GW},
        {"id": "other", "connectivity_path": "/infra/tier-1s/another"},
    ]})
    out = delete_tier1_gateway(client, f.T1)
    assert out["deleted"] is False
    assert out["segment_ids"] == ["web-seg"]
    assert client.deleted == []


@pytest.mark.parametrize(("key", "path"), _CHILD_COLLECTIONS)
def test_each_child_collection_refuses_and_deletes_nothing(key, path):
    client = f.FakeNsx(collections={path: [{"id": "blocker-1"}]})
    out = delete_tier1_gateway(client, f.T1)
    assert out["deleted"] is False
    assert out[key] == ["blocker-1"]
    assert "Nothing was deleted" in out["error"]
    assert client.deleted == []


def test_lb_service_attached_by_connectivity_path_refuses():
    client = f.FakeNsx(collections={f.LB_SERVICES: [
        {"id": "lb-web", "connectivity_path": f.GW},
        {"id": "lb-other", "connectivity_path": "/infra/tier-1s/another"},
        {"id": "lb-unattached"},
    ]})
    out = delete_tier1_gateway(client, f.T1)
    assert out["deleted"] is False
    assert out["lb_service_ids"] == ["lb-web"]
    assert client.deleted == []


def test_dns_forwarder_refuses():
    client = f.FakeNsx(objects={f.DNS_FORWARDER: {"id": "dns-fwd", "listener_ip": "10.0.0.53"}})
    out = delete_tier1_gateway(client, f.T1)
    assert out["deleted"] is False
    assert out["dns_forwarder_ids"] == ["dns-fwd"]
    assert client.deleted == []


def test_a_locale_service_other_than_default_refuses():
    """The delete only removes "default"; any other one fails the final DELETE."""
    client = f.FakeNsx(collections={f.LOCALE_SERVICES: [{"id": "default"}, {"id": "edge-b"}]})
    out = delete_tier1_gateway(client, f.T1)
    assert out["deleted"] is False
    assert out["locale_service_ids"] == ["edge-b"]
    assert client.deleted == []


def test_only_the_default_locale_service_is_not_a_blocker():
    client = f.FakeNsx(collections={f.LOCALE_SERVICES: [{"id": "default"}]})
    assert delete_tier1_gateway(client, f.T1)["deleted"] is True


@pytest.mark.parametrize("path", sorted(_ALL_READS - {f.SEGMENTS}))
def test_a_404_on_a_dependent_collection_is_not_a_blocker(path):
    client = f.FakeNsx(fail={path: f.not_found(path)})
    assert delete_tier1_gateway(client, f.T1)["deleted"] is True


@pytest.mark.parametrize("path", sorted(_ALL_READS))
def test_a_check_that_cannot_run_refuses_rather_than_deleting(path):
    client = f.FakeNsx(fail={path: f.server_error(path)})
    with pytest.raises(NsxApiError):
        delete_tier1_gateway(client, f.T1)
    assert client.deleted == []


def test_every_check_is_made():
    client = f.FakeNsx()
    delete_tier1_gateway(client, f.T1)
    assert set(client.reads) == _ALL_READS


def test_blocker_ids_are_sanitized():
    client = f.FakeNsx(collections={f.IPSEC: [{"id": "vpn\x1b[31m-1"}]})
    out = delete_tier1_gateway(client, f.T1)
    assert "\x1b" not in out["ipsec_vpn_service_ids"][0]
    assert "\x1b" not in out["error"]


def test_the_error_names_where_to_look_for_each_kind_present():
    client = f.FakeNsx(
        collections={f.IPSEC: [{"id": "vpn-1"}], f.NAT: [{"id": "snat-1"}]},
    )
    err = delete_tier1_gateway(client, f.T1)["error"]
    assert "IPsec VPN" in err and "NAT rule" in err
    assert "list_nat_rules" in err
    assert "L2 VPN" not in err, "the hint should name only what is actually blocking"


def test_a_capped_sample_says_it_is_a_lower_bound():
    client = f.FakeNsx(collections={f.NAT: [{"id": f"r{i}"} for i in range(40)]})
    out = delete_tier1_gateway(client, f.T1)
    assert len(out["nat_rule_ids"]) == 10
    assert "10+ NAT rule" in out["error"], "a sample of 10 must not be reported as exactly 10"


def test_blockers_are_read_only():
    """The dry-run preview calls this directly; it must never write."""
    client = f.FakeNsx(collections={f.NAT: [{"id": "snat-1"}]})
    assert tier1_delete_blockers(client, f.T1) == {"nat_rule_ids": ["snat-1"]}
    assert client.deleted == []


def test_clean_gateway_still_deletes_locale_service_then_gateway():
    client = f.FakeNsx()
    out = delete_tier1_gateway(client, f.T1)
    assert out["deleted"] is True
    assert client.deleted == [
        "/policy/api/v1/infra/tier-1s/t1-del/locale-services/default",
        "/policy/api/v1/infra/tier-1s/t1-del",
    ]


# ── the conformance test must be able to see every pre-flight read ────────


def test_every_preflight_read_is_checked_against_the_spec():
    """``f"/policy/api/v1{gw_path}/{child}"`` resolved to ``tier-1s/{param}/{param}``.

    The spec-conformance scanner turns anything it cannot resolve into a
    wildcard, and a wildcard matches any literal in the spec, so that loop's
    reads were "verified" whatever child name they used — a typo would have
    404-ed in production and been read as "none there", i.e. a blocker that is
    never seen. Each read must now resolve to a template whose only wildcard is
    the gateway id.
    """
    from tests.eval.regression.test_nsx_spec_conformance import (
        _collect_api_calls,
        _matches_spec,
        _spec_segment_lists,
    )

    calls = [p for loc, p in _collect_api_calls() if loc.startswith("vmware_nsx/ops/segment_mgmt.py")]
    t1 = "/policy/api/v1/infra/tier-1s/{param}"
    expected = {
        "/policy/api/v1/infra/segments",
        "/policy/api/v1/infra/lb-services",
        f"{t1}/nat/USER/nat-rules",
        f"{t1}/static-routes",
        f"{t1}/segments",
        f"{t1}/locale-services",
        f"{t1}/locale-services/default/interfaces",
        f"{t1}/ipsec-vpn-services",
        f"{t1}/l2vpn-services",
        f"{t1}/dns-forwarder",
    }
    missing = expected - set(calls)
    assert not missing, f"pre-flight reads the scanner cannot see literally: {sorted(missing)}"
    assert not [p for p in calls if p.startswith(f"{t1}/{{param}}")], (
        "a Tier-1 child path still resolves to a bare wildcard, so the spec check cannot verify it"
    )
    spec = _spec_segment_lists()
    assert all(_matches_spec(p, spec) for p in expected)
    # Positive control for the negative direction: a misspelt child is rejected.
    assert not _matches_spec(f"{t1}/ipsec-vpn-servicez", spec)
    assert not _matches_spec(f"{t1}/dns-forwarders", spec)

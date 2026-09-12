"""A fake NsxClient for the Tier-1 delete pre-flight tests.

Answers by exact path, so a pre-flight that asks for a path nobody seeded gets
an empty collection (``get_all``) or a 404 (``get``) — the two ways NSX says
"none here" — and a test that seeds a blocker at the wrong path fails instead
of passing by accident. Every DELETE is recorded, which is what the refusal
tests assert on: a refusal must make none.
"""

from __future__ import annotations

from typing import Any

from vmware_nsx.connection import NsxApiError

T1 = "t1-del"
GW = f"/infra/tier-1s/{T1}"
BASE = f"/policy/api/v1{GW}"

SEGMENTS = "/policy/api/v1/infra/segments"
LB_SERVICES = "/policy/api/v1/infra/lb-services"
NAT = f"{BASE}/nat/USER/nat-rules"
ROUTES = f"{BASE}/static-routes"
T1_SEGMENTS = f"{BASE}/segments"
LOCALE_SERVICES = f"{BASE}/locale-services"
INTERFACES = f"{BASE}/locale-services/default/interfaces"
IPSEC = f"{BASE}/ipsec-vpn-services"
L2VPN = f"{BASE}/l2vpn-services"
DNS_FORWARDER = f"{BASE}/dns-forwarder"
#: The gateway object itself — what get_tier1_gateway reads before a CLI delete.
GW_OBJECT_PATH = BASE


def not_found(path: str) -> NsxApiError:
    return NsxApiError(f"GET {path} returned HTTP 404.", status_code=404, method="GET", path=path)


def server_error(path: str) -> NsxApiError:
    return NsxApiError(f"GET {path} returned HTTP 500.", status_code=500, method="GET", path=path)


class FakeNsx:
    def __init__(
        self,
        collections: dict[str, list[dict]] | None = None,
        objects: dict[str, dict] | None = None,
        fail: dict[str, Exception] | None = None,
    ) -> None:
        self.collections = dict(collections or {})
        self.objects = {GW_OBJECT_PATH: {"id": T1, "display_name": "T1"}, **(objects or {})}
        self.fail = dict(fail or {})
        self.deleted: list[str] = []
        self.reads: list[str] = []

    def get_all(self, path: str, *args: Any, **kwargs: Any) -> list[dict]:
        self.reads.append(path)
        if path in self.fail:
            raise self.fail[path]
        rows = self.collections.get(path, [])
        limit = kwargs.get("limit")
        return rows[:limit] if limit else list(rows)

    def get(self, path: str, *args: Any, **kwargs: Any) -> dict:
        self.reads.append(path)
        if path in self.fail:
            raise self.fail[path]
        if path in self.objects:
            return self.objects[path]
        raise not_found(path)

    def delete(self, path: str) -> None:
        self.deleted.append(path)

    def put(self, *a: Any, **k: Any) -> dict:  # pragma: no cover - a delete test must never write
        raise AssertionError("the Tier-1 delete path must not PUT")

    patch = post = put


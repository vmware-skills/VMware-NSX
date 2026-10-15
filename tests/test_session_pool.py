"""HLD §16 D-13(2): calls never share an NSX session; the pool gives each its own.

Every test goes through the real ``ConnectionManager`` with only the client
class replaced by a fake (no network). The fake counts how many calls are using
it at the same moment; more than one is the defect this file exists to catch —
an ``NsxClient`` re-creates its XSRF session in place on a 401, so two calls on
one client race that refresh.
"""

from __future__ import annotations

import threading
import time

import pytest
from vmware_policy.pool import call_scope

from vmware_nsx import connection
from vmware_nsx.config import AppConfig, TargetConfig
from vmware_nsx.connection import ConnectionManager

CLIENT_ATTR = "NsxClient"
PASSWORD_ENV = "VMWARE_NSX_{}_PASSWORD"


class FakeClient:
    created: list[FakeClient] = []
    _lock = threading.Lock()

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.alive = True
        self.closed = False
        self.in_use = 0
        self.overlaps = 0
        with FakeClient._lock:
            FakeClient.created.append(self)

    def use(self, seconds: float = 0.05) -> None:
        with FakeClient._lock:
            self.in_use += 1
            if self.in_use > 1:
                self.overlaps += 1
        time.sleep(seconds)
        with FakeClient._lock:
            self.in_use -= 1

    def is_alive(self) -> bool:
        return self.alive

    is_alive_cached = is_alive

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def mgr(monkeypatch: pytest.MonkeyPatch) -> ConnectionManager:
    FakeClient.created = []
    monkeypatch.setattr(connection, CLIENT_ATTR, FakeClient)
    monkeypatch.setenv("VMWARE_MCP_POOL_SIZE", "2")
    for name in ("A", "B"):
        monkeypatch.setenv(PASSWORD_ENV.format(name), "pw")
    targets = {n: TargetConfig(host=f"{n}.example", username="u") for n in ("a", "b")}
    return ConnectionManager(AppConfig(targets=targets, default_target="a"))


def _run(*fns):
    errors: list[BaseException] = []

    def wrap(fn):
        def body():
            try:
                fn()
            except BaseException as exc:  # surfaced below, never swallowed
                errors.append(exc)

        return body

    threads = [threading.Thread(target=wrap(f)) for f in fns]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert not any(t.is_alive() for t in threads), "a call never finished"
    if errors:
        raise errors[0]


def test_concurrent_calls_on_one_target_get_different_sessions(mgr):
    got: list[FakeClient] = []
    barrier = threading.Barrier(2, timeout=5)

    def call():
        with call_scope():
            client = mgr.connect("a")
            got.append(client)
            barrier.wait()  # both calls hold a session at the same moment
            client.use(0.1)
            assert mgr.connect("a") is client  # same call, same session

    _run(call, call)
    assert len(got) == 2 and got[0] is not got[1]
    assert all(c.overlaps == 0 for c in FakeClient.created)


def test_a_long_call_leaves_the_other_session_usable(mgr):
    holding = threading.Event()
    release = threading.Event()
    long_session: list[FakeClient] = []

    def long_call():
        with call_scope():
            long_session.append(mgr.connect("a"))
            holding.set()
            release.wait(5)

    t = threading.Thread(target=long_call)
    t.start()
    try:
        assert holding.wait(5)
        started = time.monotonic()
        with call_scope():
            other = mgr.connect("a")
            other.use(0.01)
        assert time.monotonic() - started < 1.0
        assert other is not long_session[0]
    finally:
        release.set()
        t.join(5)


def test_calls_on_different_targets_overlap(mgr):
    barrier = threading.Barrier(2, timeout=5)  # times out unless both run at once
    seen: dict[str, FakeClient] = {}

    def call(name):
        def body():
            with call_scope():
                seen[name] = mgr.connect(name)
                barrier.wait()
                seen[name].use(0.05)

        return body

    _run(call("a"), call("b"))
    assert seen["a"] is not seen["b"]


def test_outside_a_call_scope_the_same_session_is_reused(mgr):
    first = mgr.connect("a")
    assert mgr.connect("a") is first
    assert len(FakeClient.created) == 1


def test_a_dead_session_is_closed_and_replaced(mgr):
    first = mgr.connect("a")
    first.alive = False
    second = mgr.connect("a")
    assert second is not first and first.closed and not second.closed

    with call_scope():
        pooled = mgr.connect("a")
    pooled.alive = False
    with call_scope():
        replacement = mgr.connect("a")
    assert replacement is not pooled and pooled.closed


def test_no_target_name_pools_under_the_default_target(mgr):
    default = mgr.connect()
    assert mgr.list_connected() == ["a"]
    assert mgr.connect("a") is default


def test_disconnect_closes_the_targets_sessions(mgr):
    client = mgr.connect("a")
    mgr.disconnect("a")
    assert client.closed and mgr.list_connected() == []


def test_unknown_target_is_refused_before_any_session_is_made(mgr):
    with pytest.raises(ValueError, match="not found"):
        mgr.connect("nope")
    assert FakeClient.created == []


def test_concurrent_first_calls_build_one_manager(monkeypatch):
    from vmware_nsx.mcp_server import server

    built: list[object] = []

    class SlowManager:
        def __init__(self, config):
            time.sleep(0.05)
            built.append(self)

        def connect(self, target):
            return self

    monkeypatch.setattr(server, "_conn_mgr", None)
    monkeypatch.setattr(server, "ConnectionManager", SlowManager)
    monkeypatch.setattr(server, "load_config", lambda: None)
    _run(*[lambda: server._get_connection("a")] * 6)
    assert len(built) == 1


def test_a_pool_timeout_reaches_the_agent_with_its_remedy():
    from vmware_policy.pool import PoolTimeoutError

    from vmware_nsx.mcp_server._shared import _safe_error

    msg = (
        "All 2 sessions to target 'a' stayed busy for 300 s. Retry when the other calls "
        "finish, or raise VMWARE_MCP_POOL_SIZE on the server."
    )
    assert _safe_error(PoolTimeoutError(msg), "some_tool") == msg

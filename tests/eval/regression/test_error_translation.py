"""Regression evals for the 2026-06 NSX hardening pass (踩坑 #37 family).

Mirrors the vmware-aria v1.5.34 fix: HTTP errors are translated centrally
in the connection layer (``NsxApiError`` + one ``_request()``), instead of
each ops function leaking raw httpx tracebacks. Also pins:

* form-body session auth survives special-character passwords (踩坑 #10/#21)
* 503/transport retry-once is GET-only — writes are never auto-replayed
* 401 re-auths exactly once; 403 (RBAC) never re-auths
* re-sent request after re-auth stays inside the protected loop
* get_all() 1000-item safety cap
* MCP _safe_error passes NsxApiError teaching text through; delete tools
  route through _safe_error (no raw exception text in agent context)
* SKILL.md tool table parity with the live FastMCP registry
* CLI: shared error decorator (red line + exit 1, no traceback)
* CLI: VLAN range '100-200' is passed through as a range string
* ops: create_segment keeps documented dhcp_ranges
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from vmware_nsx.connection import NsxApiError, NsxClient

REPO_ROOT = Path(__file__).resolve().parents[3]


# ── helpers ─────────────────────────────────────────────────────────────


def _make_client(handler, *, token: str | None = "xsrf-tok") -> NsxClient:
    """Build an NsxClient wired to an httpx.MockTransport, skipping the
    real __init__ (which would dial out and create a session)."""
    client = NsxClient.__new__(NsxClient)
    client._target = SimpleNamespace(host="nsx.example", port=443, username="admin", verify_ssl=True)
    client._password = "pw"
    client._username = "admin"
    client._base_url = "https://nsx.example:443"
    client._token = token
    client._client = httpx.Client(
        base_url="https://nsx.example:443",
        transport=httpx.MockTransport(handler),
    )
    return client


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    monkeypatch.setattr("vmware_nsx.connection._RETRY_DELAY_SEC", 0.0)


# ── form-body auth (踩坑 #10/#21) ───────────────────────────────────────


def test_session_create_sends_special_char_password_as_raw_form_body() -> None:
    """Password with '!' and ')' must reach NSX as a literal form body —
    urlencode's %21/%29 encoding caused spurious 403s on some NSX builds,
    and Basic-Auth headers are not used at all."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content.decode()
        return httpx.Response(200, headers={"x-xsrf-token": "fresh-tok"})

    client = _make_client(handler, token=None)
    client._password = "p@ss!word)"
    client._create_session()

    assert captured["headers"]["content-type"] == "application/x-www-form-urlencoded"
    assert "authorization" not in captured["headers"], "must not fall back to Basic auth"
    assert "j_username=admin" in captured["body"]
    # '!' and ')' preserved literally (the curl-compatible safe set)
    assert "j_password=p%40ss!word)" in captured["body"]
    assert client._token == "fresh-tok"


def test_session_create_failure_raises_credential_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    client = _make_client(handler, token=None)
    with pytest.raises(NsxApiError) as exc_info:
        client._create_session()
    err = exc_info.value
    assert err.status_code == 403
    # Names the exact loader env-var pattern (NSX_ prefix) + where the
    # username lives, and reaffirms form-body auth handles special chars
    # (踩坑 #10/#21).
    msg = str(err)
    assert "VMWARE_NSX_<TARGET_NAME_UPPER>_PASSWORD" in msg
    assert "config.yaml" in msg
    assert "form-body" in msg


# ── central _request() translation ──────────────────────────────────────


def test_404_raises_teaching_error_without_retry() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(404)

    client = _make_client(handler)
    with pytest.raises(NsxApiError) as exc_info:
        client.get("/policy/api/v1/infra/segments/nope")
    err = exc_info.value
    assert err.status_code == 404
    assert "list" in str(err), "404 must point the user at the list command"
    assert len(calls) == 1, "4xx must NOT be retried"


def test_503_get_retried_exactly_once_then_translated() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503)

    client = _make_client(handler)
    with pytest.raises(NsxApiError) as exc_info:
        client.get("/policy/api/v1/infra")
    assert len(calls) == 2, "transient 503 on GET must be retried exactly once"
    assert exc_info.value.status_code == 503
    assert "not ready" in str(exc_info.value)


def test_503_post_never_retried() -> None:
    """A write that hit a transient gateway error may already have been
    applied server-side — blind re-sends would duplicate the side effect."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503)

    client = _make_client(handler)
    with pytest.raises(NsxApiError):
        client.post("/policy/api/v1/infra/segments/s1", json_data={"id": "s1"})
    assert len(calls) == 1, "writes must NOT be auto-retried"


def test_401_reauths_exactly_once() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(401)

    client = _make_client(handler)
    reauths = []
    client._create_session = lambda: reauths.append(1)  # type: ignore[method-assign]

    with pytest.raises(NsxApiError) as exc_info:
        client.get("/policy/api/v1/infra/segments")
    assert reauths == [1], "401 must trigger exactly one session re-creation"
    assert calls.count("/policy/api/v1/infra/segments") == 2
    assert exc_info.value.status_code == 401


def test_403_is_rbac_denial_not_reauth() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(403)

    client = _make_client(handler)
    reauths = []
    client._create_session = lambda: reauths.append(1)  # type: ignore[method-assign]

    with pytest.raises(NsxApiError) as exc_info:
        client.get("/policy/api/v1/infra/tier-0s")
    assert reauths == [], "403 must NOT re-auth — it is a real permission denial"
    assert len(calls) == 1
    assert "role" in str(exc_info.value), "403 must carry an RBAC hint"


def test_transport_error_after_reauth_is_still_translated() -> None:
    """code-review HIGH from the Aria fix: the re-sent request after
    re-auth must go back through the protected loop, so a connection drop
    there is an NsxApiError, never a raw httpx exception."""
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(401)
        raise httpx.ConnectError("connection dropped mid-reauth")

    client = _make_client(handler)
    client._create_session = lambda: None  # type: ignore[method-assign]

    with pytest.raises(NsxApiError) as exc_info:
        client.post("/policy/api/v1/infra/segments/s1", json_data={})
    assert exc_info.value.status_code is None  # transport failure, no response
    assert "could not connect" in str(exc_info.value)


def test_transport_error_on_get_retried_once_then_translated() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectTimeout("boom")

    client = _make_client(handler)
    with pytest.raises(NsxApiError) as exc_info:
        client.get("/policy/api/v1/infra")
    assert len(calls) == 2
    assert exc_info.value.status_code is None


def test_is_alive_uses_cheap_policy_probe_no_retry() -> None:
    """Liveness must probe a cheap Policy-API GET readable by any role, not
    the privileged /api/v1/cluster/status — a least-privilege account gets
    403 there, and is_alive()->False would tear down + rebuild the session on
    every connect() (踩坑 #21, in sync with VMware-NSX-Security). The infra
    root is used because the default domain may be absent in a plain NSX-T
    deployment, while the infra root always exists. retries=0 = one call."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={})

    client = _make_client(handler)
    assert client.is_alive() is True
    assert len(calls) == 1, "probe must use retries=0 (a single call)"
    method, path = calls[0]
    assert method == "GET"
    assert path == "/policy/api/v1/infra", (
        "liveness probe must use a cheap Policy-API GET (the always-present "
        "infra root), not the privileged /api/v1/cluster/status endpoint"
    )

    # Documented semantics: 5xx=alive, 401/403=dead. A 403 on the probe marks
    # the session dead (rebuild), matching VMware-NSX-Security exactly.
    client_403 = _make_client(lambda r: httpx.Response(403))
    assert client_403.is_alive() is False, "403 = dead session per documented 5xx=alive / 401/403=dead semantics"


def test_is_alive_treats_503_as_alive_and_401_as_dead() -> None:
    client_503 = _make_client(lambda r: httpx.Response(503))
    assert client_503.is_alive() is True, "503 = platform booting, session still good"

    calls = []

    def handler401(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401)

    client_401 = _make_client(handler401)
    client_401._create_session = lambda: None  # type: ignore[method-assign]
    assert client_401.is_alive() is False, "401 = stale session, rebuild the client"


# ── get_all() safety cap ────────────────────────────────────────────────


def test_get_all_stops_at_max_items_cap() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Endless cursor: 100 results per page, forever.
        return httpx.Response(
            200,
            json={"results": [{"i": 1}] * 100, "cursor": "next"},
        )

    client = _make_client(handler)
    results = client.get_all("/policy/api/v1/infra/segments", max_items=250)
    assert len(results) == 250

    # Default cap is 1000
    results = client.get_all("/policy/api/v1/infra/segments")
    assert len(results) == 1000


# ── MCP server: _safe_error + delete tools ──────────────────────────────


def test_safe_error_passes_nsx_api_error_through_and_redacts_generic() -> None:
    from vmware_nsx.mcp_server.server import _safe_error

    teaching = NsxApiError(
        "NSX Manager GET /x returned HTTP 404. Resource not found.",
        status_code=404,
        method="GET",
        path="/x",
    )
    assert "404" in _safe_error(teaching, "test")

    leaky = RuntimeError("https://secret-host:443/internal/path body=...")
    redacted = _safe_error(leaky, "test")
    assert "secret-host" not in redacted
    assert redacted == "RuntimeError: operation failed."


@pytest.mark.parametrize(
    ("tool_name", "kwargs"),
    [
        ("delete_segment", {"segment_id": "seg-x"}),
        ("delete_tier1_gateway", {"tier1_id": "t1-x"}),
        ("delete_nat_rule", {"tier1_id": "t1-x", "rule_id": "r-x"}),
        ("delete_static_route", {"tier1_id": "t1-x", "route_id": "r-x"}),
        ("delete_ip_pool", {"pool_id": "pool-x"}),
    ],
)
def test_delete_tools_route_errors_through_safe_error(tool_name, kwargs) -> None:
    """v1.5.32 audit: four delete tools returned f"Error: {e}" directly,
    bypassing _safe_error and leaking raw exception text to the agent."""
    import vmware_nsx.mcp_server.server as srv

    leaky = RuntimeError("https://secret-host:443/internal leaked body")
    with patch.object(srv, "_get_connection", side_effect=leaky):
        result = getattr(srv, tool_name)(**kwargs)
    assert isinstance(result, dict)
    assert "secret-host" not in str(result), f"{tool_name} leaks raw exception text"
    assert "operation failed" in result["error"]

    teaching = NsxApiError("HTTP 404. Run the list command.", status_code=404)
    with patch.object(srv, "_get_connection", side_effect=teaching):
        result = getattr(srv, tool_name)(**kwargs)
    assert "404" in result["error"], f"{tool_name} must surface NsxApiError teaching text"


# ── SKILL.md ↔ FastMCP registry parity (踩坑 #34) ───────────────────────


def _actual_tools() -> dict[str, bool]:
    """Map tool name → readOnlyHint from the live FastMCP registry."""
    from vmware_nsx.mcp_server.server import mcp

    tools = asyncio.run(mcp.list_tools())
    return {t.name: bool(t.annotations and t.annotations.readOnlyHint) for t in tools}


def test_skill_md_tool_table_matches_live_registry() -> None:
    skill_md = (REPO_ROOT / "skills" / "vmware-nsx" / "SKILL.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\|[^|]*\| `(\w+)` \| (Read|Write) \|", skill_md, re.MULTILINE)
    documented = {name: kind == "Read" for name, kind in rows}
    actual = _actual_tools()

    assert documented, "SKILL.md MCP tool table not found / not parseable"
    missing = set(actual) - set(documented)
    phantom = set(documented) - set(actual)
    assert not phantom, f"SKILL.md documents nonexistent tools: {sorted(phantom)}"
    assert not missing, f"SKILL.md omits real tools: {sorted(missing)}"
    wrong = [n for n in actual if documented[n] != actual[n]]
    assert not wrong, f"SKILL.md Read/Write column wrong for: {sorted(wrong)}"


def test_skill_md_counts_match_live_registry() -> None:
    skill_md = (REPO_ROOT / "skills" / "vmware-nsx" / "SKILL.md").read_text(encoding="utf-8")
    actual = _actual_tools()
    total, reads = len(actual), sum(actual.values())
    writes = total - reads

    heading = re.search(r"## MCP Tools \((\d+) — (\d+) read, (\d+) write\)", skill_md)
    assert heading, "MCP Tools heading with counts not found"
    assert tuple(map(int, heading.groups())) == (total, reads, writes)

    total_line = re.search(r"\*\*Total\*\*: (\d+) tools \((\d+) read-only \+ (\d+) write\)", skill_md)
    assert total_line, "'**Total**: N tools' line not found"
    assert tuple(map(int, total_line.groups())) == (total, reads, writes)

    assert "All write operations support dry-run mode" not in skill_md, (
        "MCP write tools have no dry-run — that claim was false (CLI-only feature)"
    )


# ── no bare raise_for_status outside the connection layer ───────────────


def _cli_source_files() -> list[Path]:
    """CLI source files — the cli/ package (split by group) or legacy cli.py."""
    cli_pkg = REPO_ROOT / "vmware_nsx" / "cli"
    if cli_pkg.is_dir():
        return [p for p in cli_pkg.rglob("*.py") if "__pycache__" not in p.parts]
    return [REPO_ROOT / "vmware_nsx" / "cli.py"]


def _mcp_server_sources() -> list[Path]:
    """Every .py under the MCP server package.

    Asserted non-empty on purpose. The v1.9.0 migration briefly left this as
    ``REPO_ROOT / "vmware_nsx.mcp_server"`` — one path segment containing a
    dot, which does not exist. ``rglob`` on a missing directory yields nothing
    rather than raising, so the scan below silently covered zero files and the
    test kept reporting green. A guard that quietly stops guarding is worse
    than one that fails.
    """
    root = REPO_ROOT / "vmware_nsx" / "mcp_server"
    sources = list(root.rglob("*.py"))
    assert sources, f"no sources found under {root} — the scan below would be vacuous"
    return sources


def test_no_raw_raise_for_status_outside_connection_layer() -> None:
    offenders = []
    for py in [
        *(REPO_ROOT / "vmware_nsx" / "ops").glob("*.py"),
        *_cli_source_files(),
        *(p for p in _mcp_server_sources() if "__pycache__" not in p.parts),
    ]:
        if "raise_for_status" in py.read_text(encoding="utf-8"):
            offenders.append(py.relative_to(REPO_ROOT).as_posix())
    assert not offenders, (
        f"bare raise_for_status() outside connection layer: {offenders} — "
        "all HTTP errors must be translated centrally (踩坑 #37)"
    )


# ── CLI: shared error decorator ─────────────────────────────────────────


def test_cli_translates_nsx_api_error_to_red_line_and_exit_1() -> None:
    from typer.testing import CliRunner

    import vmware_nsx.cli as cli

    err = NsxApiError(
        "NSX Manager GET /policy/api/v1/infra/segments returned HTTP 403. Permission denied.",
        status_code=403,
    )
    with patch.object(cli, "_get_connection", side_effect=err):
        result = CliRunner().invoke(cli.app, ["inventory", "list-segments"])
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "403" in result.output
    assert "Traceback" not in result.output


def test_cli_translates_missing_config_to_exit_1() -> None:
    from typer.testing import CliRunner

    import vmware_nsx.cli as cli

    with patch.object(
        cli,
        "_get_connection",
        side_effect=FileNotFoundError("Config file not found: ~/.vmware-nsx/config.yaml"),
    ):
        result = CliRunner().invoke(cli.app, ["health", "manager-status"])
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "Traceback" not in result.output


def test_every_cli_command_has_error_decorator() -> None:
    """Every @<group>.command() must be wrapped by @_cli_errors so no
    command can leak a raw traceback."""
    src = "\n".join(p.read_text(encoding="utf-8") for p in _cli_source_files())
    blocks = re.findall(r"^(@[a-z_]*app\.command\([^\n]*\)\n)(@_cli_errors\n)?", src, re.MULTILINE)
    undecorated = [b[0].strip() for b in blocks if not b[1]]
    assert not undecorated, f"CLI commands missing @_cli_errors: {undecorated}"


# ── CLI: VLAN range parsing (v1.5.32 bug: '100-200' → [100, 200]) ───────


def test_parse_vlan_ids_keeps_ranges_and_ints() -> None:
    from vmware_nsx.ops.segment_mgmt import parse_vlan_ids

    assert parse_vlan_ids("100") == [100]
    assert parse_vlan_ids("100,200") == [100, 200]
    assert parse_vlan_ids("100-200") == ["100-200"]
    assert parse_vlan_ids("50, 100-200 ,300") == [50, "100-200", 300]


@pytest.mark.parametrize(
    ("vlan_arg", "expected"),
    [("100-200", ["100-200"]), ("100,200", [100, 200])],
)
def test_cli_segment_create_passes_vlan_ranges_through(vlan_arg, expected) -> None:
    import vmware_nsx.cli as cli

    client = MagicMock(name="NsxClient")
    client.put.return_value = {"id": "seg"}
    with (
        patch.object(cli, "_get_connection", return_value=(client, None)),
        patch.object(cli, "_double_confirm"),
        patch.object(cli, "_audit"),
    ):
        cli.segment_create(
            segment_id="vlan-seg",
            display_name="VLAN seg",
            transport_zone="/infra/.../tz",
            vlan_ids=vlan_arg,
            subnet=None,
            target=None,
            config=None,
            dry_run=False,
        )
    body = client.put.call_args.args[1]
    assert body["vlan_ids"] == expected


# ── ops: create_segment keeps dhcp_ranges ───────────────────────────────


def test_create_segment_includes_dhcp_ranges_when_present() -> None:
    from vmware_nsx.ops.segment_mgmt import create_segment

    client = MagicMock(name="NsxClient")
    client.put.return_value = {"id": "seg"}
    create_segment(
        client,
        "seg-dhcp",
        display_name="seg",
        transport_zone_path="/infra/.../tz",
        subnets=[
            {"gateway_address": "10.0.0.1/24", "dhcp_ranges": ["10.0.0.10-10.0.0.100"]},
            {"gateway_address": "10.0.1.1/24"},
        ],
    )
    body = client.put.call_args.args[1]
    assert body["subnets"][0] == {
        "gateway_address": "10.0.0.1/24",
        "dhcp_ranges": ["10.0.0.10-10.0.0.100"],
    }
    assert body["subnets"][1] == {"gateway_address": "10.0.1.1/24"}, "dhcp_ranges key must be absent when not provided"

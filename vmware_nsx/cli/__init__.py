"""CLI entry point for VMware NSX.

Provides read-only inventory/networking/health/troubleshooting queries and
write operations (segment, gateway, NAT, route, IP pool management) with
--dry-run preview and double confirmation for destructive actions.

The Typer ``app`` is assembled here from per-domain command modules
(``cli.inventory``, ``cli.segment``, …). Shared plumbing — the ``_cli_errors``
decorator, option aliases, helpers, and sub-app instances — lives in
``cli._base``; command functions and helpers are re-exported onto this package
so that ``vmware_nsx.cli.<name>`` keeps resolving as before (and tests can
``patch("vmware_nsx.cli._get_connection")``).
"""

from __future__ import annotations

from typing import Annotated

import typer

# Shared plumbing re-exported so commands resolve them via this package
# namespace at call time (notably _get_connection, which tests patch).
from vmware_nsx.cli._base import (  # noqa: F401
    ConfigOption,
    DryRunOption,
    TargetOption,
    _audit,
    _cli_errors,
    _double_confirm,
    _dry_run_print,
    _get_connection,
    _resolve_target,
    console,
    gateway_app,
    health_app,
    inventory_app,
    ip_pool_app,
    mcp_config_app,
    nat_app,
    networking_app,
    route_app,
    segment_app,
    troubleshoot_app,
)

app = typer.Typer(
    name="vmware-nsx",
    help="VMware NSX networking management and operations.",
    no_args_is_help=True,
)

# Import command modules to register their commands onto the sub-apps. These
# modules do `from vmware_nsx import cli` to resolve shared helpers at call
# time; importing them after `app` is defined keeps that reference valid.
from vmware_nsx.cli import (  # noqa: E402
    gateway,
    health,
    inventory,
    ip_pool,
    mcp_config,
    nat,
    networking,
    route,
    segment,
    troubleshoot,
)
import sys
# Registers this skill's environment resolver, so environment-scoped policy
# rules apply to @guarded CLI writes exactly as they do to MCP tools.
import vmware_nsx.policy_environment  # noqa: F401 — imported to register the resolver; do not remove


def _harden_console_encoding() -> None:
    """Never let one unrepresentable glyph kill a command.

    On a console whose encoding cannot carry the characters we print -- cp936 on
    the Chinese Windows boxes this family is tested on, or any ASCII locale --
    ``print`` raises ``UnicodeEncodeError`` and the whole command dies with a
    traceback. ``--help`` died that way in four repos. A mangled dash is a
    cosmetic loss; a dead ``--help`` is an outage, so the error handler is
    relaxed rather than the vocabulary narrowed.

    Best effort: ``reconfigure`` is absent when stdout has been replaced by a
    plain object (pytest capture, some MCP hosts), and losing the hardening
    there is not worth an exception at import.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


_harden_console_encoding()

app.add_typer(inventory_app, name="inventory")
app.add_typer(networking_app, name="networking")
app.add_typer(health_app, name="health")
app.add_typer(troubleshoot_app, name="troubleshoot")
app.add_typer(segment_app, name="segment")
app.add_typer(gateway_app, name="gateway")
app.add_typer(nat_app, name="nat")
app.add_typer(route_app, name="route")
app.add_typer(ip_pool_app, name="ip-pool")
app.add_typer(mcp_config_app, name="mcp-config")

# Re-export command functions onto this package so existing references like
# `vmware_nsx.cli.segment_create` and `cli.gateway_create_tier1` keep working.
inventory_list_segments = inventory.inventory_list_segments
inventory_get_segment = inventory.inventory_get_segment
inventory_list_tier0s = inventory.inventory_list_tier0s
inventory_get_tier0 = inventory.inventory_get_tier0
inventory_list_tier1s = inventory.inventory_list_tier1s
inventory_get_tier1 = inventory.inventory_get_tier1
inventory_list_transport_zones = inventory.inventory_list_transport_zones
inventory_list_transport_nodes = inventory.inventory_list_transport_nodes
inventory_list_edge_clusters = inventory.inventory_list_edge_clusters

networking_list_nat_rules = networking.networking_list_nat_rules
networking_bgp_neighbors = networking.networking_bgp_neighbors
networking_list_static_routes = networking.networking_list_static_routes
networking_list_ip_pools = networking.networking_list_ip_pools
networking_ip_pool_usage = networking.networking_ip_pool_usage

health_alarms = health.health_alarms
health_transport_node_status = health.health_transport_node_status
health_edge_cluster_status = health.health_edge_cluster_status
health_manager_status = health.health_manager_status

troubleshoot_port_status = troubleshoot.troubleshoot_port_status
troubleshoot_vm_segment = troubleshoot.troubleshoot_vm_segment

segment_create = segment.segment_create
segment_update = segment.segment_update
segment_delete = segment.segment_delete

gateway_create_tier1 = gateway.gateway_create_tier1
gateway_update_tier1 = gateway.gateway_update_tier1
gateway_delete_tier1 = gateway.gateway_delete_tier1
gateway_configure_tier0_bgp = gateway.gateway_configure_tier0_bgp

nat_create_rule = nat.nat_create_rule
nat_delete_rule = nat.nat_delete_rule

route_create_static = route.route_create_static
route_delete_static = route.route_delete_static

ip_pool_create = ip_pool.ip_pool_create
ip_pool_delete = ip_pool.ip_pool_delete

mcp_config_generate = mcp_config.mcp_config_generate
mcp_config_list = mcp_config.mcp_config_list
mcp_config_install = mcp_config.mcp_config_install


# ═══════════════════════════════════════════════════════════════════════════════
# INIT
# ═══════════════════════════════════════════════════════════════════════════════


@app.command("init")
@_cli_errors
def init_cmd(
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing config without asking"),
    ] = False,
    skip_test: Annotated[
        bool,
        typer.Option("--skip-test", help="Do not run the doctor connection test at the end"),
    ] = False,
) -> None:
    """Guided first-run setup: write config.yaml + .env, then verify the connection.

    Prompts for an NSX Manager target, stores the password grep-safe (0600 .env,
    never plaintext on disk), and offers to run `vmware-nsx doctor`.
    """
    from vmware_nsx.init_wizard import run_init

    raise typer.Exit(run_init(force=force, skip_test=skip_test))


# ═══════════════════════════════════════════════════════════════════════════════
# DOCTOR
# ═══════════════════════════════════════════════════════════════════════════════


@app.command("doctor")
@_cli_errors
def doctor_cmd(
    skip_auth: Annotated[
        bool,
        typer.Option("--skip-auth", help="Skip NSX authentication check (faster)"),
    ] = False,
) -> None:
    """Check environment, config, connectivity, and NSX manager status."""
    from vmware_nsx.doctor import run_doctor

    exit_code = 0 if run_doctor(skip_auth=skip_auth) else 1
    raise typer.Exit(exit_code)


@app.command("mcp")
@_cli_errors
def mcp_cmd() -> None:
    """Start the MCP server (stdio transport).

    Single-command entry point for MCP clients:
        vmware-nsx mcp

    Equivalent to the legacy `vmware-nsx-mcp` console script.
    """
    import sys

    if sys.version_info < (3, 10):
        msg = (
            f"ERROR: vmware-nsx MCP server requires Python >= 3.10 "
            f"(got {sys.version_info.major}.{sys.version_info.minor}).\n"
            f"Interpreter: {sys.executable}\n"
            "Fix: uv python install 3.12 && "
            "uv tool install --python 3.12 --force vmware-nsx"
        )
        typer.echo(msg, err=True)
        raise typer.Exit(2)

    from vmware_nsx.mcp_server.server import main as _mcp_main

    _mcp_main()


if __name__ == "__main__":
    app()

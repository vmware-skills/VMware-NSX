"""Networking commands (read-only): NAT rules, BGP neighbors, static routes, IP pools."""

from __future__ import annotations

from rich.table import Table

from vmware_nsx import cli
from vmware_nsx.cli._base import (
    ConfigOption,
    LimitOption,
    OffsetOption,
    TargetOption,
    _cli_errors,
    console,
    print_next_page,
    networking_app,
)
from vmware_policy import audited


@networking_app.command("list-nat-rules")
@_cli_errors
@audited("list_nat_rules")
def networking_list_nat_rules(
    tier1_id: str,
    limit: LimitOption = 50,
    offset: OffsetOption = 0,
    target: TargetOption = None,
    config: ConfigOption = None,
) -> None:
    """List NAT rules on a Tier-1 gateway."""
    from vmware_nsx.ops.networking import list_nat_rules

    client, _ = cli._get_connection(target, config)
    _result = list_nat_rules(client, tier1_id, limit=limit, offset=offset)
    rules = _result["items"]
    table = Table(title=f"NAT Rules on '{tier1_id}' ({len(rules)})")
    table.add_column("ID", style="cyan")
    table.add_column("Action")
    table.add_column("Source")
    table.add_column("Destination")
    table.add_column("Translated")
    table.add_column("Enabled")
    for r in rules:
        enabled_style = "green" if r.get("enabled", True) else "red"
        table.add_row(
            r["id"],
            r["action"],
            r.get("source_network", "-"),
            r.get("destination_network", "-"),
            r.get("translated_network", "-"),
            f"[{enabled_style}]{'Yes' if r.get('enabled', True) else 'No'}[/]",
        )
    console.print(table)
    print_next_page(_result)


@networking_app.command("bgp-neighbors")
@_cli_errors
@audited("get_bgp_neighbors")
def networking_bgp_neighbors(
    tier0_id: str,
    target: TargetOption = None,
    config: ConfigOption = None,
) -> None:
    """Show BGP neighbors for a Tier-0 gateway."""
    from vmware_nsx.ops.networking import get_bgp_neighbors

    client, _ = cli._get_connection(target, config)
    data = get_bgp_neighbors(client, tier0_id)
    neighbors = data.get("neighbors", [])
    if not neighbors:
        console.print("[yellow]No BGP neighbors found.[/]")
        return
    # Realized session state, keyed by peer address
    status_by_addr = {
        s.get("neighbor_address"): s for s in data.get("neighbor_status", [])
    }
    table = Table(title=f"BGP Neighbors on '{tier0_id}'")
    table.add_column("Neighbor Address", style="cyan")
    table.add_column("Remote ASN")
    table.add_column("State")
    table.add_column("Hold Time")
    table.add_column("Keep Alive")
    table.add_column("Prefixes In/Out")
    for n in neighbors:
        addr = n.get("neighbor_address", "-")
        s = status_by_addr.get(addr, {})
        state = s.get("connection_state", "UNKNOWN")
        style = "green" if state == "ESTABLISHED" else "red"
        table.add_row(
            addr,
            str(n.get("remote_as_num", "-")),
            f"[{style}]{state}[/]",
            str(n.get("hold_down_time", "-")),
            str(n.get("keep_alive_time", "-")),
            f"{s.get('in_prefix_count', '-')}/{s.get('out_prefix_count', '-')}",
        )
    console.print(table)


@networking_app.command("list-static-routes")
@_cli_errors
@audited("list_static_routes")
def networking_list_static_routes(
    tier1_id: str,
    limit: LimitOption = 50,
    offset: OffsetOption = 0,
    target: TargetOption = None,
    config: ConfigOption = None,
) -> None:
    """List static routes on a Tier-1 gateway."""
    from vmware_nsx.ops.networking import list_static_routes

    client, _ = cli._get_connection(target, config)
    _result = list_static_routes(client, tier1_id, limit=limit, offset=offset)
    routes = _result["items"]
    table = Table(title=f"Static Routes on '{tier1_id}' ({len(routes)})")
    table.add_column("ID", style="cyan")
    table.add_column("Network")
    table.add_column("Next Hops")
    for r in routes:
        # next_hops entries are dicts: {"ip_address", "admin_distance"}
        hops = ", ".join(nh.get("ip_address", "") for nh in r.get("next_hops", []))
        table.add_row(r["id"], r["network"], hops or "-")
    console.print(table)
    print_next_page(_result)


@networking_app.command("list-ip-pools")
@_cli_errors
@audited("list_ip_pools")
def networking_list_ip_pools(
    limit: LimitOption = 50,
    offset: OffsetOption = 0,
    target: TargetOption = None,
    config: ConfigOption = None,
) -> None:
    """List all IP address pools."""
    from vmware_nsx.ops.networking import list_ip_pools

    client, _ = cli._get_connection(target, config)
    _result = list_ip_pools(client, limit=limit, offset=offset)
    pools = _result["items"]
    table = Table(title=f"IP Pools ({len(pools)})")
    table.add_column("ID", style="cyan")
    table.add_column("Display Name")
    table.add_column("Subnets")
    table.add_column("Usage", justify="right")
    for p in pools:
        table.add_row(p["id"], p["display_name"], p.get("subnets", "-"), p.get("usage_summary", "-"))
    console.print(table)
    print_next_page(_result)


@networking_app.command("ip-pool-usage")
@_cli_errors
@audited("get_ip_pool_usage")
def networking_ip_pool_usage(
    pool_id: str,
    target: TargetOption = None,
    config: ConfigOption = None,
) -> None:
    """Show IP pool allocation usage."""
    from vmware_nsx.ops.networking import get_ip_pool_usage

    client, _ = cli._get_connection(target, config)
    usage = get_ip_pool_usage(client, pool_id)
    console.print(f"\n[bold]IP Pool Usage: {pool_id}[/]")
    for k, v in usage.items():
        console.print(f"  [cyan]{k}:[/] {v}")

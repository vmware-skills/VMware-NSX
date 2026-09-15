"""Health commands (read-only): alarms, transport node / edge cluster / manager status."""

from __future__ import annotations

from typing import Annotated

import typer
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
    health_app,
)
from vmware_policy import audited


@health_app.command("alarms")
@_cli_errors
@audited("list_nsx_alarms")
def health_alarms(
    severity: Annotated[
        str,
        typer.Option(
            "--severity",
            help="Severity filter, exact match (not 'and above'): LOW, MEDIUM, HIGH, CRITICAL",
        ),
    ] = "MEDIUM",
    limit: LimitOption = 1000,
    offset: OffsetOption = 0,
    target: TargetOption = None,
    config: ConfigOption = None,
) -> None:
    """Show active NSX alarms at one severity (exact match)."""
    from vmware_nsx.ops.health import list_alarms

    client, _ = cli._get_connection(target, config)
    _result = list_alarms(client, severity=severity, limit=limit, offset=offset)
    alarms = _result["items"]
    if not alarms:
        console.print(f"[green]No active {severity.upper()} alarms.[/]")
        return
    table = Table(title=f"NSX Alarms ({len(alarms)})")
    table.add_column("Severity")
    table.add_column("Feature")
    table.add_column("Description")
    table.add_column("Entity")
    table.add_column("Time")
    for a in alarms:
        sev = a.get("severity", "UNKNOWN")
        sev_style = "red" if sev == "CRITICAL" else "yellow" if sev == "WARNING" else "white"
        table.add_row(
            f"[{sev_style}]{sev}[/]",
            a.get("feature_name", "-"),
            a.get("description", "-"),
            a.get("entity_id", "-"),
            a.get("last_reported_time", "-"),
        )
    console.print(table)
    print_next_page(_result)


@health_app.command("transport-node-status")
@_cli_errors
@audited("get_transport_node_status")
def health_transport_node_status(
    node_id: str,
    target: TargetOption = None,
    config: ConfigOption = None,
) -> None:
    """Check status of a specific transport node."""
    from vmware_nsx.ops.health import get_transport_node_status

    client, _ = cli._get_connection(target, config)
    status = get_transport_node_status(client, node_id)
    for k, v in status.items():
        console.print(f"  [cyan]{k}:[/] {v}")


@health_app.command("edge-cluster-status")
@_cli_errors
@audited("get_edge_cluster_status")
def health_edge_cluster_status(
    cluster_id: str,
    target: TargetOption = None,
    config: ConfigOption = None,
) -> None:
    """Check status of an edge cluster."""
    from vmware_nsx.ops.health import get_edge_cluster_status

    client, _ = cli._get_connection(target, config)
    status = get_edge_cluster_status(client, cluster_id)
    for k, v in status.items():
        console.print(f"  [cyan]{k}:[/] {v}")


@health_app.command("manager-status")
@_cli_errors
@audited("get_nsx_manager_status")
def health_manager_status(
    target: TargetOption = None,
    config: ConfigOption = None,
) -> None:
    """Show NSX Manager cluster status."""
    from vmware_nsx.ops.health import get_manager_status

    client, _ = cli._get_connection(target, config)
    status = get_manager_status(client)
    for k, v in status.items():
        console.print(f"  [cyan]{k}:[/] {v}")

"""Troubleshoot commands (read-only): port status, VM-to-segment mapping."""

from __future__ import annotations

from vmware_nsx import cli
from vmware_nsx.cli._base import (
    ConfigOption,
    TargetOption,
    _cli_errors,
    console,
    troubleshoot_app,
)
from vmware_policy import audited


@troubleshoot_app.command("port-status")
@_cli_errors
@audited("get_logical_port_status")
def troubleshoot_port_status(
    segment_id: str,
    target: TargetOption = None,
    config: ConfigOption = None,
) -> None:
    """Check realized state of all ports on a segment."""
    from vmware_nsx.ops.troubleshoot import get_logical_port_status

    client, _ = cli._get_connection(target, config)
    status = get_logical_port_status(client, segment_id)
    for k, v in status.items():
        console.print(f"  [cyan]{k}:[/] {v}")


@troubleshoot_app.command("vm-segment")
@_cli_errors
@audited("get_segment_port_for_vm")
def troubleshoot_vm_segment(
    vm_display_name: str,
    target: TargetOption = None,
    config: ConfigOption = None,
) -> None:
    """Find which segment a VM is attached to (lookup by display name)."""
    from vmware_nsx.ops.troubleshoot import get_segment_port_for_vm

    client, _ = cli._get_connection(target, config)
    result = get_segment_port_for_vm(client, vm_display_name)
    if not result:
        console.print("[yellow]No segment port found for this VM.[/]")
        return
    for k, v in result.items():
        console.print(f"  [cyan]{k}:[/] {v}")

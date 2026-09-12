"""IP pool management commands (write ops): create, delete."""

from __future__ import annotations

from typing import Annotated

import typer
from vmware_policy import guarded

from vmware_nsx import cli
from vmware_nsx.cli._base import (
    ConfigOption,
    DryRunOption,
    TargetOption,
    _cli_errors,
    _dry_run_print,
    console,
    ip_pool_app,
)


@ip_pool_app.command("create")
@_cli_errors
@guarded('create_ip_pool', risk_level='medium')
def ip_pool_create(
    pool_id: str,
    display_name: Annotated[str, typer.Option("--name", help="Display name")],
    start_ip: Annotated[str, typer.Option("--start", help="Start IP address")],
    end_ip: Annotated[str, typer.Option("--end", help="End IP address")],
    cidr: Annotated[str, typer.Option("--cidr", help="Subnet CIDR, e.g. '192.168.1.0/24'")],
    gateway_ip: Annotated[str | None, typer.Option("--gateway", help="Gateway IP")] = None,
    target: TargetOption = None,
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Create a new IP address pool."""
    from vmware_nsx.ops.nat_route_mgmt import create_ip_pool

    client, _ = cli._get_connection(target, config)
    params = {"display_name": display_name, "start_ip": start_ip, "end_ip": end_ip, "cidr": cidr, "gateway_ip": gateway_ip}
    if dry_run:
        _dry_run_print(
            target=cli._resolve_target(target),
            resource=pool_id,
            operation="create_ip_pool",
            api_call=f"PUT /policy/api/v1/infra/ip-pools/{pool_id}",
            parameters=params,
            resource_label="IP Pool",
        )
        return
    cli._double_confirm("create IP pool", pool_id, cli._resolve_target(target), resource_type="IP Pool")
    subnet: dict = {"allocation_ranges": [{"start": start_ip, "end": end_ip}], "cidr": cidr}
    if gateway_ip:
        subnet["gateway_ip"] = gateway_ip
    out = create_ip_pool(client, pool_id, display_name=display_name, subnets=[subnet])
    if out.get("error"):
        # The pool exists but its subnet does not: a failed create. escape():
        # the reason carries NSX-derived text, which Rich would read as markup.
        from rich.markup import escape

        console.print(f"[bold red]{escape(str(out['error']))}[/]")
        cli._audit.log(
            target=cli._resolve_target(target), operation="create_ip_pool", resource=pool_id,
            parameters=params, after_state={k: out.get(k) for k in ("created", "subnets_created", "subnets_failed")},
            result="error",
        )
        raise typer.Exit(1)
    console.print(f"[green]IP pool '{pool_id}' created.[/]")
    cli._audit.log(target=cli._resolve_target(target), operation="create_ip_pool", resource=pool_id, parameters=params, result="ok")


@ip_pool_app.command("delete")
@_cli_errors
@guarded('delete_ip_pool', risk_level='high')
def ip_pool_delete(
    pool_id: str,
    target: TargetOption = None,
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Delete an IP address pool (destructive!)."""
    from vmware_nsx.ops.nat_route_mgmt import delete_ip_pool

    client, _ = cli._get_connection(target, config)
    if dry_run:
        _dry_run_print(
            target=cli._resolve_target(target),
            resource=pool_id,
            operation="delete_ip_pool",
            api_call=f"DELETE /policy/api/v1/infra/ip-pools/{pool_id}",
            resource_label="IP Pool",
        )
        return
    cli._double_confirm("delete IP pool", pool_id, cli._resolve_target(target), resource_type="IP Pool")
    delete_ip_pool(client, pool_id)
    console.print(f"[green]IP pool '{pool_id}' deleted.[/]")
    cli._audit.log(target=cli._resolve_target(target), operation="delete_ip_pool", resource=pool_id, parameters={}, result="ok")

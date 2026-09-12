"""Static route management commands (write ops): create, delete."""

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
    route_app,
)


@route_app.command("create-static")
@_cli_errors
@guarded('create_static_route', risk_level='medium')
def route_create_static(
    tier1_id: Annotated[str, typer.Option("--tier1", help="Tier-1 gateway ID")],
    route_id: Annotated[str, typer.Option("--route-id", help="Static route ID")],
    network: Annotated[str, typer.Option("--network", help="Destination CIDR, e.g. '10.0.0.0/8'")],
    next_hop: Annotated[str, typer.Option("--next-hop", help="Next hop IP address")],
    target: TargetOption = None,
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Create a static route on a Tier-1 gateway."""
    from vmware_nsx.ops.nat_route_mgmt import create_static_route

    client, _ = cli._get_connection(target, config)
    params = {"network": network, "next_hop": next_hop}
    resource_name = f"{tier1_id}/{route_id}"
    if dry_run:
        _dry_run_print(
            target=cli._resolve_target(target),
            resource=resource_name,
            operation="create_static_route",
            api_call=f"PUT /policy/api/v1/infra/tier-1s/{tier1_id}/static-routes/{route_id}",
            parameters=params,
            resource_label="Static Route",
        )
        return
    cli._double_confirm("create static route", resource_name, cli._resolve_target(target), resource_type="Static Route")
    create_static_route(client, tier1_id, route_id, network=network, next_hops=[{"ip_address": next_hop}])
    console.print(f"[green]Static route '{route_id}' created on '{tier1_id}'.[/]")
    cli._audit.log(target=cli._resolve_target(target), operation="create_static_route", resource=resource_name, parameters=params, result="ok")


@route_app.command("delete-static")
@_cli_errors
@guarded('delete_static_route', risk_level='high')
def route_delete_static(
    tier1_id: Annotated[str, typer.Option("--tier1", help="Tier-1 gateway ID")],
    route_id: Annotated[str, typer.Option("--route-id", help="Static route ID to delete")],
    target: TargetOption = None,
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Delete a static route (destructive!)."""
    from vmware_nsx.ops.nat_route_mgmt import delete_static_route

    client, _ = cli._get_connection(target, config)
    resource_name = f"{tier1_id}/{route_id}"
    if dry_run:
        _dry_run_print(
            target=cli._resolve_target(target),
            resource=resource_name,
            operation="delete_static_route",
            api_call=f"DELETE /policy/api/v1/infra/tier-1s/{tier1_id}/static-routes/{route_id}",
            resource_label="Static Route",
        )
        return
    cli._double_confirm("delete static route", resource_name, cli._resolve_target(target), resource_type="Static Route")
    delete_static_route(client, tier1_id, route_id)
    console.print(f"[green]Static route '{route_id}' deleted from '{tier1_id}'.[/]")
    cli._audit.log(target=cli._resolve_target(target), operation="delete_static_route", resource=resource_name, parameters={}, result="ok")

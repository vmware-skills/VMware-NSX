"""NAT rule management commands (write ops): create, delete."""

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
    nat_app,
)


@nat_app.command("create-rule")
@_cli_errors
@guarded('create_nat_rule', risk_level='medium')
def nat_create_rule(
    tier1_id: Annotated[str, typer.Option("--tier1", help="Tier-1 gateway ID")],
    rule_id: Annotated[str, typer.Option("--rule-id", help="NAT rule ID")],
    action: Annotated[str, typer.Option("--action", help="NAT action: SNAT, DNAT, REFLEXIVE")] = "DNAT",
    source_network: Annotated[str | None, typer.Option("--source", help="Source network CIDR")] = None,
    destination_network: Annotated[str | None, typer.Option("--destination", help="Destination network CIDR")] = None,
    translated_network: Annotated[str, typer.Option("--translated", help="Translated network/IP")] = "",
    target: TargetOption = None,
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Create a NAT rule on a Tier-1 gateway."""
    from vmware_nsx.ops.nat_route_mgmt import create_nat_rule

    client, _ = cli._get_connection(target, config)
    params = {"action": action, "source_network": source_network, "destination_network": destination_network, "translated_network": translated_network}
    resource_name = f"{tier1_id}/{rule_id}"
    if dry_run:
        _dry_run_print(
            target=cli._resolve_target(target),
            resource=resource_name,
            operation="create_nat_rule",
            api_call=f"PUT /policy/api/v1/infra/tier-1s/{tier1_id}/nat/USER/nat-rules/{rule_id}",
            parameters=params,
            resource_label="NAT Rule",
        )
        return
    cli._double_confirm("create NAT rule", resource_name, cli._resolve_target(target), resource_type="NAT Rule")
    create_nat_rule(client, tier1_id, rule_id, action=action, source_network=source_network, destination_network=destination_network, translated_network=translated_network)
    console.print(f"[green]NAT rule '{rule_id}' created on '{tier1_id}'.[/]")
    cli._audit.log(target=cli._resolve_target(target), operation="create_nat_rule", resource=resource_name, parameters=params, result="ok")


@nat_app.command("delete-rule")
@_cli_errors
@guarded('delete_nat_rule', risk_level='high')
def nat_delete_rule(
    tier1_id: Annotated[str, typer.Option("--tier1", help="Tier-1 gateway ID")],
    rule_id: Annotated[str, typer.Option("--rule-id", help="NAT rule ID to delete")],
    target: TargetOption = None,
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Delete a NAT rule (destructive!)."""
    from vmware_nsx.ops.nat_route_mgmt import delete_nat_rule

    client, _ = cli._get_connection(target, config)
    resource_name = f"{tier1_id}/{rule_id}"
    if dry_run:
        _dry_run_print(
            target=cli._resolve_target(target),
            resource=resource_name,
            operation="delete_nat_rule",
            api_call=f"DELETE /policy/api/v1/infra/tier-1s/{tier1_id}/nat/USER/nat-rules/{rule_id}",
            resource_label="NAT Rule",
        )
        return
    cli._double_confirm("delete NAT rule", resource_name, cli._resolve_target(target), resource_type="NAT Rule")
    delete_nat_rule(client, tier1_id, rule_id)
    console.print(f"[green]NAT rule '{rule_id}' deleted from '{tier1_id}'.[/]")
    cli._audit.log(target=cli._resolve_target(target), operation="delete_nat_rule", resource=resource_name, parameters={}, result="ok")

"""Gateway management commands (write ops): Tier-1 create/update/delete, Tier-0 BGP."""

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
    gateway_app,
)


@gateway_app.command("create-tier1")
@_cli_errors
@guarded('create_tier1_gateway', risk_level='medium')
def gateway_create_tier1(
    tier1_id: str,
    display_name: Annotated[str, typer.Option("--name", help="Display name")],
    tier0_path: Annotated[str | None, typer.Option("--tier0", help="Tier-0 gateway path to link")] = None,
    edge_cluster_path: Annotated[str | None, typer.Option("--edge-cluster", help="Edge cluster path")] = None,
    route_advertisement: Annotated[str | None, typer.Option("--advertise", help="Route advertisement types, comma-separated")] = None,
    target: TargetOption = None,
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Create a new Tier-1 gateway."""
    from vmware_nsx.ops.segment_mgmt import create_tier1_gateway

    client, _ = cli._get_connection(target, config)
    params = {"display_name": display_name, "tier0_path": tier0_path, "edge_cluster_path": edge_cluster_path, "route_advertisement": route_advertisement}
    if dry_run:
        _dry_run_print(
            target=cli._resolve_target(target),
            resource=tier1_id,
            operation="create_tier1_gateway",
            api_call=f"PUT /policy/api/v1/infra/tier-1s/{tier1_id}",
            parameters=params,
            resource_label="Tier-1 Gateway",
        )
        return
    cli._double_confirm("create Tier-1 gateway", tier1_id, cli._resolve_target(target), resource_type="Tier-1 Gateway")
    ra_types = [t.strip() for t in route_advertisement.split(",") if t.strip()] if route_advertisement else None
    create_tier1_gateway(client, tier1_id, display_name=display_name, tier0_path=tier0_path, route_advertisement_types=ra_types, edge_cluster_path=edge_cluster_path)
    console.print(f"[green]Tier-1 gateway '{tier1_id}' created.[/]")
    cli._audit.log(target=cli._resolve_target(target), operation="create_tier1_gateway", resource=tier1_id, parameters=params, result="ok")


@gateway_app.command("update-tier1")
@_cli_errors
@guarded('update_tier1_gateway', risk_level='medium')
def gateway_update_tier1(
    tier1_id: str,
    display_name: Annotated[str | None, typer.Option("--name", help="New display name")] = None,
    tier0_path: Annotated[str | None, typer.Option("--tier0", help="New Tier-0 path")] = None,
    route_advertisement: Annotated[str | None, typer.Option("--advertise", help="Route advertisement types")] = None,
    target: TargetOption = None,
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Update an existing Tier-1 gateway."""
    from vmware_nsx.ops.inventory import get_tier1_gateway
    from vmware_nsx.ops.segment_mgmt import update_tier1_gateway

    client, _ = cli._get_connection(target, config)
    before = get_tier1_gateway(client, tier1_id)
    params = {"display_name": display_name, "tier0_path": tier0_path, "route_advertisement": route_advertisement}
    if dry_run:
        _dry_run_print(
            target=cli._resolve_target(target),
            resource=tier1_id,
            operation="update_tier1_gateway",
            api_call=f"PATCH /policy/api/v1/infra/tier-1s/{tier1_id}",
            parameters={k: v for k, v in params.items() if v is not None},
            before_state={"display_name": before.get("display_name"), "tier0_path": before.get("tier0_path")},
            resource_label="Tier-1 Gateway",
        )
        return
    cli._double_confirm("update Tier-1 gateway", tier1_id, cli._resolve_target(target), resource_type="Tier-1 Gateway")
    updates: dict = {}
    if display_name is not None:
        updates["display_name"] = display_name
    if tier0_path is not None:
        updates["tier0_path"] = tier0_path
    if route_advertisement is not None:
        updates["route_advertisement_types"] = [t.strip() for t in route_advertisement.split(",") if t.strip()]
    update_tier1_gateway(client, tier1_id, **updates)
    console.print(f"[green]Tier-1 gateway '{tier1_id}' updated.[/]")
    cli._audit.log(target=cli._resolve_target(target), operation="update_tier1_gateway", resource=tier1_id, parameters=params, result="ok")


@gateway_app.command("delete-tier1")
@_cli_errors
@guarded('delete_tier1_gateway', risk_level='high')
def gateway_delete_tier1(
    tier1_id: str,
    target: TargetOption = None,
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Delete a Tier-1 gateway (destructive!).

    Refuses, deleting nothing, while segments, NAT rules, static routes,
    interfaces, VPN / DNS forwarder / load balancer services still depend on it.
    """
    from rich.markup import escape

    from vmware_nsx.ops.inventory import get_tier1_gateway
    from vmware_nsx.ops.segment_mgmt import (
        delete_tier1_gateway,
        tier1_delete_blockers,
        tier1_refusal_message,
    )

    client, _ = cli._get_connection(target, config)
    before = get_tier1_gateway(client, tier1_id)
    if dry_run:
        # The same read-only pre-flight the real run makes, so the preview
        # cannot promise a delete the real run would refuse.
        blockers = tier1_delete_blockers(client, tier1_id)
        base = f"/policy/api/v1/infra/tier-1s/{tier1_id}"
        _dry_run_print(
            target=cli._resolve_target(target),
            resource=tier1_id,
            operation="delete_tier1_gateway",
            api_call=(
                "none — the pre-check would refuse" if blockers
                else f"DELETE {base}/locale-services/default, then DELETE {base}"
            ),
            before_state={"display_name": before.get("display_name"), "tier0_path": before.get("tier0_path")},
            resource_label="Tier-1 Gateway",
        )
        if blockers:
            # escape(): ids come from NSX, and Rich would swallow "[web-seg]" as markup.
            console.print(f"[bold red]A real run would be REFUSED: {escape(tier1_refusal_message(tier1_id, blockers))}[/]")
        return
    cli._double_confirm("delete Tier-1 gateway", tier1_id, cli._resolve_target(target), resource_type="Tier-1 Gateway")
    out = delete_tier1_gateway(client, tier1_id)
    if out.get("deleted") is not True:
        blockers = {k: v for k, v in out.items() if k.endswith("_ids")}
        console.print(f"[bold red]Tier-1 gateway '{tier1_id}' was NOT deleted. {escape(str(out.get('error', '')))}[/]")
        cli._audit.log(
            target=cli._resolve_target(target), operation="delete_tier1_gateway", resource=tier1_id,
            parameters={}, after_state={"deleted": False, **blockers}, result="error",
        )
        raise typer.Exit(1)
    console.print(f"[green]Tier-1 gateway '{tier1_id}' deleted.[/]")
    cli._audit.log(target=cli._resolve_target(target), operation="delete_tier1_gateway", resource=tier1_id, parameters={}, result="ok")


@gateway_app.command("configure-tier0-bgp")
@_cli_errors
@guarded('configure_tier0_bgp', risk_level='medium')
def gateway_configure_tier0_bgp(
    tier0_id: str,
    local_as: Annotated[int, typer.Option("--local-as", help="Local AS number")],
    enabled: Annotated[bool, typer.Option("--enabled/--disabled", help="Enable or disable BGP")] = True,
    ecmp: Annotated[bool, typer.Option("--ecmp/--no-ecmp", help="Enable ECMP for BGP routes")] = True,
    inter_sr_ibgp: Annotated[bool, typer.Option("--inter-sr-ibgp/--no-inter-sr-ibgp", help="Enable inter-SR iBGP")] = True,
    locale_service_id: Annotated[str, typer.Option("--locale-service", help="Locale-service identifier")] = "default",
    target: TargetOption = None,
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Configure BGP settings (local AS, ECMP, inter-SR iBGP) on a Tier-0 gateway.

    Note: BGP neighbor creation is a separate Policy API object and is not
    exposed by this command. Use 'network bgp-neighbors' to inspect neighbors.
    """
    from vmware_nsx.ops.segment_mgmt import configure_tier0_bgp

    client, _ = cli._get_connection(target, config)
    bgp_config = {"local_as_num": str(local_as), "enabled": enabled, "ecmp": ecmp, "inter_sr_ibgp": inter_sr_ibgp}
    if dry_run:
        _dry_run_print(
            target=cli._resolve_target(target),
            resource=tier0_id,
            operation="configure_tier0_bgp",
            api_call=f"PATCH /policy/api/v1/infra/tier-0s/{tier0_id}/locale-services/{locale_service_id}/bgp",
            parameters=bgp_config,
            resource_label="Tier-0 BGP",
        )
        return
    cli._double_confirm("configure BGP on Tier-0", tier0_id, cli._resolve_target(target), resource_type="Tier-0 BGP")
    configure_tier0_bgp(client, tier0_id, locale_service_id=locale_service_id, bgp_config=bgp_config)
    console.print(f"[green]BGP configured on Tier-0 '{tier0_id}'.[/]")
    cli._audit.log(target=cli._resolve_target(target), operation="configure_tier0_bgp", resource=tier0_id, parameters=bgp_config, result="ok")

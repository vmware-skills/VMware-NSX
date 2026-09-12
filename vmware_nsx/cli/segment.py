"""Segment management commands (write ops): create, update, delete."""

from __future__ import annotations

from typing import Annotated, Any

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
    segment_app,
)


@segment_app.command("create")
@_cli_errors
@guarded('create_segment', risk_level='medium')
def segment_create(
    segment_id: str,
    display_name: Annotated[str, typer.Option("--name", help="Display name")],
    transport_zone: Annotated[str, typer.Option("--tz", help="Transport zone path")],
    vlan_ids: Annotated[str | None, typer.Option("--vlan", help="VLAN ID(s), e.g. '100' or '100-200'")] = None,
    subnet: Annotated[str | None, typer.Option("--subnet", help="Gateway CIDR, e.g. '192.168.1.1/24'")] = None,
    target: TargetOption = None,
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Create a new network segment."""
    from vmware_nsx.ops.segment_mgmt import create_segment, parse_vlan_ids

    client, _ = cli._get_connection(target, config)
    params = {"display_name": display_name, "transport_zone": transport_zone, "vlan_ids": vlan_ids, "subnet": subnet}
    if dry_run:
        _dry_run_print(
            target=cli._resolve_target(target),
            resource=segment_id,
            operation="create_segment",
            api_call=f"PUT /policy/api/v1/infra/segments/{segment_id}",
            parameters=params,
            resource_label="Segment",
        )
        return
    cli._double_confirm("create segment", segment_id, cli._resolve_target(target), resource_type="Segment")
    # '100-200' is a VLAN *range* and must reach NSX as the range string —
    # the old `.replace("-", ",")` parse silently turned it into the two
    # discrete VLANs 100 and 200.
    parsed_vlan_ids: list[int | str] | None = None
    if vlan_ids is not None:
        parsed_vlan_ids = parse_vlan_ids(vlan_ids)
    parsed_subnets: list[dict[str, str]] | None = None
    if subnet is not None:
        parsed_subnets = [{"gateway_address": subnet}]
    create_segment(client, segment_id, display_name=display_name, transport_zone_path=transport_zone, vlan_ids=parsed_vlan_ids, subnets=parsed_subnets)
    console.print(f"[green]Segment '{segment_id}' created.[/]")
    cli._audit.log(target=cli._resolve_target(target), operation="create_segment", resource=segment_id, parameters=params, result="ok")


@segment_app.command("update")
@_cli_errors
@guarded('update_segment', risk_level='medium')
def segment_update(
    segment_id: str,
    display_name: Annotated[str | None, typer.Option("--name", help="New display name")] = None,
    subnet: Annotated[str | None, typer.Option("--subnet", help="New gateway CIDR")] = None,
    target: TargetOption = None,
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Update an existing segment."""
    from vmware_nsx.ops.inventory import get_segment
    from vmware_nsx.ops.segment_mgmt import update_segment

    client, _ = cli._get_connection(target, config)
    before = get_segment(client, segment_id)
    params = {"display_name": display_name, "subnet": subnet}
    if dry_run:
        _dry_run_print(
            target=cli._resolve_target(target),
            resource=segment_id,
            operation="update_segment",
            api_call=f"PATCH /policy/api/v1/infra/segments/{segment_id}",
            parameters={k: v for k, v in params.items() if v is not None},
            before_state={"display_name": before.get("display_name"), "subnet": before.get("subnet")},
            resource_label="Segment",
        )
        return
    cli._double_confirm("update segment", segment_id, cli._resolve_target(target), resource_type="Segment")
    update_kwargs: dict[str, Any] = {}
    if display_name is not None:
        update_kwargs["display_name"] = display_name
    if subnet is not None:
        update_kwargs["subnets"] = [{"gateway_address": subnet}]
    update_segment(client, segment_id, **update_kwargs)
    console.print(f"[green]Segment '{segment_id}' updated.[/]")
    cli._audit.log(target=cli._resolve_target(target), operation="update_segment", resource=segment_id, parameters=params, result="ok")


@segment_app.command("delete")
@_cli_errors
@guarded('delete_segment', risk_level='high')
def segment_delete(
    segment_id: str,
    target: TargetOption = None,
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Delete a segment (destructive!). Refuses, deleting nothing, while ports are attached."""
    from rich.markup import escape

    from vmware_nsx.ops.inventory import get_segment
    from vmware_nsx.ops.segment_mgmt import delete_segment, segment_delete_blockers

    client, _ = cli._get_connection(target, config)
    info = get_segment(client, segment_id)
    if dry_run:
        # The same read-only port check the real run makes, so the preview
        # cannot promise a delete the real run would refuse.
        blockers = segment_delete_blockers(client, segment_id)
        _dry_run_print(
            target=cli._resolve_target(target),
            resource=segment_id,
            operation="delete_segment",
            api_call=(
                "none — ports are attached, a real run would refuse" if blockers
                else f"DELETE /policy/api/v1/infra/segments/{segment_id}"
            ),
            before_state={"port_count": info.get("port_count"), "admin_state": info.get("admin_state")},
            resource_label="Segment",
        )
        if blockers:
            # escape(): ids come from NSX, and Rich would swallow "[...]" as markup.
            console.print(
                f"[bold red]A real run would be REFUSED: {blockers['port_count']} attached port(s) "
                f"{escape(str(blockers['port_ids']))}. Detach them first.[/]"
            )
        return
    port_count = info.get("port_count", 0)
    if port_count and port_count > 0:
        console.print(f"[bold red]WARNING: Segment has {port_count} active ports — the delete will be refused.[/]")
    cli._double_confirm("delete segment", segment_id, cli._resolve_target(target), resource_type="Segment")
    out = delete_segment(client, segment_id)
    if out.get("deleted") is not True:
        console.print(f"[bold red]Segment '{segment_id}' was NOT deleted. {escape(str(out.get('error', '')))}[/]")
        cli._audit.log(
            target=cli._resolve_target(target), operation="delete_segment", resource=segment_id,
            parameters={}, after_state={"deleted": False, "port_ids": out.get("port_ids", [])}, result="error",
        )
        raise typer.Exit(1)
    console.print(f"[green]Segment '{segment_id}' deleted.[/]")
    cli._audit.log(target=cli._resolve_target(target), operation="delete_segment", resource=segment_id, parameters={}, result="ok")

# CLI Reference

Complete command reference for the `vmware-nsx` CLI. Command groups:
`inventory`, `networking`, `health`, `troubleshoot` (read-only) and
`segment`, `gateway`, `nat`, `route`, `ip-pool` (write), plus `doctor`,
`mcp`, and `mcp-config`.

## Global Options

All commands accept these options:

| Option | Description |
|--------|-------------|
| `--target`, `-t <name>` | Target name from `~/.vmware-nsx/config.yaml` (defaults to the configured default target) |
| `--config`, `-c <path>` | Override config file path |
| `--help` | Show command help |

Write commands additionally accept:

| Option | Description |
|--------|-------------|
| `--dry-run` | Print the API call that would be made without executing it |

**Error handling**: operational failures (connection refused, HTTP 4xx/5xx
from NSX Manager, missing config) print a single red `Error: ...` line with
a remediation hint and exit with code 1 — no Python traceback.

---

## Inventory Commands (read-only)

### `inventory list-segments`

List all network segments with type, subnet, admin state, and port count.

```bash
vmware-nsx inventory list-segments
vmware-nsx inventory list-segments --target nsx-prod
```

### `inventory get-segment`

Get detailed info for a specific segment.

```bash
vmware-nsx inventory get-segment app-web-seg
```

| Argument | Required | Description |
|----------|:--------:|-------------|
| `segment_id` | Yes | Segment ID (Policy API ID, not display name) |

### `inventory list-tier0s`

List all Tier-0 gateways with HA mode and transit subnets.

```bash
vmware-nsx inventory list-tier0s
```

### `inventory get-tier0`

Get detailed info for a Tier-0 gateway.

```bash
vmware-nsx inventory get-tier0 tier0-gw
```

### `inventory list-tier1s`

List all Tier-1 gateways with linked Tier-0 path and route advertisement.

```bash
vmware-nsx inventory list-tier1s
```

### `inventory get-tier1`

Get detailed info for a Tier-1 gateway.

```bash
vmware-nsx inventory get-tier1 app-t1
```

### `inventory list-transport-zones`

List all transport zones with type (OVERLAY / VLAN).

```bash
vmware-nsx inventory list-transport-zones
```

### `inventory list-transport-nodes`

List all transport nodes with node type and status.

```bash
vmware-nsx inventory list-transport-nodes
```

### `inventory list-edge-clusters`

List all edge clusters with member count and deployment type.

```bash
vmware-nsx inventory list-edge-clusters
```

---

## Networking Commands (read-only)

### `networking list-nat-rules`

List NAT rules on a Tier-1 gateway.

```bash
vmware-nsx networking list-nat-rules app-t1
```

| Argument | Required | Description |
|----------|:--------:|-------------|
| `tier1_id` | Yes | Tier-1 gateway ID |

### `networking bgp-neighbors`

Show BGP neighbors for a Tier-0 gateway, including realized session state,
remote ASN, hold/keep-alive timers, and prefix counts.

```bash
vmware-nsx networking bgp-neighbors tier0-gw
```

| Argument | Required | Description |
|----------|:--------:|-------------|
| `tier0_id` | Yes | Tier-0 gateway ID |

### `networking list-static-routes`

List static routes on a Tier-1 gateway.

```bash
vmware-nsx networking list-static-routes app-t1
```

### `networking list-ip-pools`

List all IP address pools with usage summary.

```bash
vmware-nsx networking list-ip-pools
```

### `networking ip-pool-usage`

Show IP pool allocation usage.

```bash
vmware-nsx networking ip-pool-usage pool-01
```

| Argument | Required | Description |
|----------|:--------:|-------------|
| `pool_id` | Yes | IP pool ID |

---

## Health Commands (read-only)

### `health alarms`

Show active NSX alarms at one severity (exact match, not "and above").

```bash
vmware-nsx health alarms
vmware-nsx health alarms --severity CRITICAL
```

| Option | Default | Description |
|--------|---------|-------------|
| `--severity` | `MEDIUM` | Exact severity filter: LOW, MEDIUM, HIGH, CRITICAL |

### `health transport-node-status`

Check status of a specific transport node.

```bash
vmware-nsx health transport-node-status <node-id>
```

### `health edge-cluster-status`

Check status of an edge cluster.

```bash
vmware-nsx health edge-cluster-status <cluster-id>
```

### `health manager-status`

Show NSX Manager cluster status.

```bash
vmware-nsx health manager-status
```

---

## Troubleshoot Commands (read-only)

### `troubleshoot port-status`

Check realized state of all ports on a segment.

```bash
vmware-nsx troubleshoot port-status app-web-seg
```

| Argument | Required | Description |
|----------|:--------:|-------------|
| `segment_id` | Yes | Segment ID |

### `troubleshoot vm-segment`

Find which segment a VM is attached to (lookup by display name).

```bash
vmware-nsx troubleshoot vm-segment my-vm-01
```

| Argument | Required | Description |
|----------|:--------:|-------------|
| `vm_display_name` | Yes | VM display name as shown in vSphere |

---

## Segment Management (write)

All write commands require **double confirmation** and support `--dry-run`.

### `segment create`

Create a new overlay or VLAN-backed segment.

```bash
vmware-nsx segment create app-web-seg --name "App Web" --tz <transport-zone-path> --subnet 10.10.1.1/24

# VLAN-backed; --vlan accepts single IDs, lists, and ranges
vmware-nsx segment create vlan-seg --name "VLAN seg" --tz <tz-path> --vlan '100-200' --dry-run
```

| Argument/Option | Required | Description |
|-----------------|:--------:|-------------|
| `segment_id` | Yes | Segment ID |
| `--name` | Yes | Display name |
| `--tz` | Yes | Transport zone path |
| `--vlan` | No | VLAN ID(s): `'100'`, `'100,200'`, or range `'100-200'` (ranges are passed to NSX as range strings, not expanded) |
| `--subnet` | No | Gateway CIDR, e.g. `192.168.1.1/24` |
| `--dry-run` | No | Preview without executing |

### `segment update`

Update an existing segment's display name and/or subnet.

```bash
vmware-nsx segment update app-web-seg --name "New Name"
vmware-nsx segment update app-web-seg --subnet 10.10.2.1/24 --dry-run
```

| Option | Description |
|--------|-------------|
| `--name` | New display name |
| `--subnet` | New gateway CIDR |

### `segment delete`

Delete a segment (destructive). Refuses — exit code 1, nothing deleted,
attached port ids printed — while any port is attached. `--dry-run` runs the
same read-only port check and shows whether a real run would be refused.

```bash
vmware-nsx segment delete app-web-seg --dry-run
vmware-nsx segment delete app-web-seg
```

---

## Gateway Management (write)

### `gateway create-tier1`

Create a new Tier-1 gateway.

```bash
vmware-nsx gateway create-tier1 app-t1 --name "App T1" --tier0 /infra/tier-0s/tier0-gw --edge-cluster <ec-path>
```

| Argument/Option | Required | Description |
|-----------------|:--------:|-------------|
| `tier1_id` | Yes | Tier-1 gateway ID |
| `--name` | Yes | Display name |
| `--tier0` | No | Tier-0 gateway path to link |
| `--edge-cluster` | No | Edge cluster path |
| `--advertise` | No | Route advertisement types, comma-separated (e.g. `TIER1_CONNECTED,TIER1_NAT`) |

### `gateway update-tier1`

Update an existing Tier-1 gateway.

```bash
vmware-nsx gateway update-tier1 app-t1 --advertise TIER1_CONNECTED,TIER1_NAT
```

| Option | Description |
|--------|-------------|
| `--name` | New display name |
| `--tier0` | New Tier-0 path |
| `--advertise` | Route advertisement types |

### `gateway delete-tier1`

Delete a Tier-1 gateway (destructive). Checks first and refuses — exit code 1,
nothing deleted, blocking ids printed — while segments, NAT rules, static
routes, service interfaces, extra locale-services, or VPN / DNS forwarder / LB
services still depend on it. `--dry-run` runs the same read-only check and
shows what blocks. When clear, removes the default locale-service, then the
gateway.

```bash
vmware-nsx gateway delete-tier1 app-t1 --dry-run
vmware-nsx gateway delete-tier1 app-t1
```

### `gateway configure-tier0-bgp`

Configure BGP settings (local AS, ECMP, inter-SR iBGP) on a Tier-0 gateway.
BGP neighbor creation is a separate Policy API object and is not exposed —
use `networking bgp-neighbors` to inspect neighbors.

```bash
vmware-nsx gateway configure-tier0-bgp tier0-gw --local-as 65001 --ecmp
```

| Option | Default | Description |
|--------|---------|-------------|
| `--local-as` | (required) | Local AS number |
| `--enabled/--disabled` | enabled | Enable or disable BGP |
| `--ecmp/--no-ecmp` | ecmp | Enable ECMP for BGP routes |
| `--inter-sr-ibgp/--no-inter-sr-ibgp` | enabled | Enable inter-SR iBGP |
| `--locale-service` | `default` | Locale-service identifier |

---

## NAT Management (write)

### `nat create-rule`

Create a NAT rule on a Tier-1 gateway.

```bash
vmware-nsx nat create-rule --tier1 app-t1 --rule-id snat-1 --action SNAT --source 10.10.1.0/24 --translated 203.0.113.10
```

| Option | Required | Default | Description |
|--------|:--------:|---------|-------------|
| `--tier1` | Yes | - | Tier-1 gateway ID |
| `--rule-id` | Yes | - | NAT rule ID |
| `--action` | No | `DNAT` | NAT action: SNAT, DNAT, REFLEXIVE |
| `--source` | No | - | Source network CIDR |
| `--destination` | No | - | Destination network CIDR |
| `--translated` | No | `""` | Translated network/IP |

### `nat delete-rule`

Delete a NAT rule (destructive).

```bash
vmware-nsx nat delete-rule --tier1 app-t1 --rule-id snat-1 --dry-run
vmware-nsx nat delete-rule --tier1 app-t1 --rule-id snat-1
```

---

## Route Management (write)

### `route create-static`

Create a static route on a Tier-1 gateway.

```bash
vmware-nsx route create-static --tier1 app-t1 --route-id r1 --network 10.0.0.0/8 --next-hop 10.10.1.254
```

| Option | Required | Description |
|--------|:--------:|-------------|
| `--tier1` | Yes | Tier-1 gateway ID |
| `--route-id` | Yes | Static route ID |
| `--network` | Yes | Destination CIDR |
| `--next-hop` | Yes | Next hop IP address |

### `route delete-static`

Delete a static route (destructive).

```bash
vmware-nsx route delete-static --tier1 app-t1 --route-id r1
```

---

## IP Pool Management (write)

### `ip-pool create`

Create a new IP address pool with one allocation range. If NSX rejects the
subnet, the pool is left without it: the command prints why and how to clean up
(`vmware-nsx ip-pool delete <pool_id>`, then create again) and exits 1.

```bash
vmware-nsx ip-pool create pool-01 --name "App Pool" --start 192.168.1.10 --end 192.168.1.100 --cidr 192.168.1.0/24 --gateway 192.168.1.1
```

| Option | Required | Description |
|--------|:--------:|-------------|
| `--name` | Yes | Display name |
| `--start` | Yes | Start IP address |
| `--end` | Yes | End IP address |
| `--cidr` | Yes | Subnet CIDR |
| `--gateway` | No | Gateway IP |

### `ip-pool delete`

Delete an IP address pool (destructive — double-confirm; supports `--dry-run`).

```bash
vmware-nsx ip-pool delete pool-01 --dry-run
vmware-nsx ip-pool delete pool-01
```

| Option | Required | Description |
|--------|:--------:|-------------|
| `--dry-run` | No | Preview the DELETE without performing it |

---

## Diagnostics & MCP

### `doctor`

Check environment, config, connectivity, and NSX Manager status.
Exits 0 when healthy, 1 otherwise.

```bash
vmware-nsx doctor
vmware-nsx doctor --skip-auth   # skip the NSX authentication check (faster)
```

### `mcp`

Start the MCP server (stdio transport). Single-command entry point for MCP
clients — equivalent to the legacy `vmware-nsx-mcp` console script, and
preferred in enterprise networks because it does not re-resolve PyPI.

```bash
vmware-nsx mcp
```

### `mcp-config generate / install / list`

Generate or install MCP server configuration for local AI agents
(goose, cursor, claude-code, continue, vscode-copilot, localcowork, mcp-agent).

```bash
vmware-nsx mcp-config list
vmware-nsx mcp-config generate --agent goose
vmware-nsx mcp-config install --agent claude-code --yes
```

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Operation failed or doctor check failed |
| `2` | MCP server started on unsupported Python (< 3.10) |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `VMWARE_NSX_CONFIG` | Override config file path (used by MCP server) |
| `VMWARE_NSX_<TARGET>_PASSWORD` | Password for a target (e.g., `VMWARE_NSX_NSX_PROD_PASSWORD`) |

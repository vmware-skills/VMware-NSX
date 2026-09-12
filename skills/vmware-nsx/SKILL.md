---
name: vmware-nsx
description: >
  Use this skill when the user needs to inspect or manage VMware NSX networking through NSX Manager — segments, Tier-0/Tier-1 gateways, NAT, static routes/BGP, and IP pools.
  Directly handles: list and inspect segments, gateways, NAT rules, routes and IP pools; check transport node, edge cluster and manager health; find a VM's segment. Changes (create/update/delete segments, Tier-1 gateways, NAT rules, static routes, IP pools, Tier-0 BGP) only when the user explicitly asks for that change.
  Use this skill for "create segment", "set up gateway", "create NAT rule", "check network health", "troubleshoot connectivity" when the context is explicitly NSX, NSX-T, or NSX Manager.
  Do NOT use for networking outside NSX, DFW firewall rules or security groups (use vmware-nsx-security), vSphere distributed port groups or host VMkernel adapters (use vmware-aiops), VM lifecycle (use vmware-aiops), or AVI/ALB load balancing (use vmware-avi).
  For multi-step workflows use vmware-pilot.
installer:
  kind: uv
  package: vmware-nsx-mgmt
allowed-tools:
  - Bash
metadata: {"openclaw":{"requires":{"anyBins":["vmware-nsx","uvx"]},"optional":{"env":["VMWARE_NSX_CONFIG","VMWARE_NSX_<TARGET>_PASSWORD","VMWARE_NSX_<TARGET>_USERNAME","VMWARE_AUDIT_APPROVED_BY"],"bins":["vmware-policy"]},"homepage":"https://github.com/vmware-skills/VMware-NSX","emoji":"🌐","os":["macos","linux"]}}
compatibility: >
  vmware-policy auto-installed as Python dependency (provides @vmware_tool decorator and audit logging). All write operations audited to ~/.vmware/audit.db.
  Credentials: Each NSX Manager target requires a per-target password env var in ~/.vmware-nsx/.env following the pattern VMWARE_NSX_<TARGET_NAME_UPPER>_PASSWORD. Username/password session auth only (client-certificate auth is not implemented). Passwords are never logged or echoed.
  Write operations: CLI write commands require double confirmation and support --dry-run. MCP write tools have no built-in confirmation step — they execute when called and are audit-logged, so the agent must call them only on the user's explicit request; ~/.vmware/rules.yaml deny rules can block them per environment. Segment delete refuses while ports are attached.
  VMWARE_AUDIT_APPROVED_BY is an optional attestation recorded in the audit row; it is not a gate and does not carry credentials.
  No webhooks, no outbound network calls, no guest operations. Local only: stdio MCP + NSX Policy API (HTTPS 443).
  SSL bypass: verify_ssl is on by default; trust a private CA via the SSL_CERT_FILE env var; verify_ssl false only for isolated labs with self-signed certs.
  Transitive dependencies: Only vmware-policy (audit/policy). No post-install scripts or background services.
---

# VMware NSX

> **Disclaimer**: This is a community-maintained open-source project and is **not affiliated with, endorsed by, or sponsored by VMware, Inc. or Broadcom Inc.** "VMware" and "NSX" are trademarks of Broadcom. Source code is publicly auditable at [github.com/vmware-skills/VMware-NSX](https://github.com/vmware-skills/VMware-NSX) under the MIT license.

VMware NSX networking management — 33 MCP tools for segments, gateways, NAT, routing, and IPAM.

> Domain-focused networking skill for NSX-T / NSX 4.x Policy API.
> **Companion skills**: [vmware-nsx-security](https://github.com/vmware-skills/VMware-NSX-Security) (DFW/firewall), [vmware-aiops](https://github.com/vmware-skills/VMware-AIops) (VM lifecycle), [vmware-monitor](https://github.com/vmware-skills/VMware-Monitor) (read-only monitoring), [vmware-storage](https://github.com/vmware-skills/VMware-Storage) (iSCSI/vSAN), [vmware-vks](https://github.com/vmware-skills/VMware-VKS) (Tanzu Kubernetes), [vmware-aria](https://github.com/vmware-skills/VMware-Aria) (metrics/alerts/capacity), [vmware-avi](https://github.com/vmware-skills/VMware-AVI) (AVI/ALB/AKO), [vmware-harden](https://github.com/vmware-skills/VMware-Harden) (compliance baselines).
> | [vmware-pilot](../vmware-pilot/SKILL.md) (workflow orchestration) | [vmware-policy](../vmware-policy/SKILL.md) (audit/policy)

## What This Skill Does

| Category | Tools | Count | Read / Write |
|----------|-------|:-----:|:------------:|
| **Segments** | list, get details, create, update, delete | 5 | 2R / 3W |
| **Tier-0 Gateways** | list, get details, BGP neighbors, configure BGP | 4 | 3R / 1W |
| **Tier-1 Gateways** | list, get details, create, update, delete | 5 | 2R / 3W |
| **NAT** | list rules, create rule, delete rule | 3 | 1R / 2W |
| **Static Routes** | list, create, delete | 3 | 1R / 2W |
| **IP Pools** | list, get usage, create pool, delete pool | 4 | 2R / 2W |
| **Fabric Inventory** | transport zones, transport nodes, edge clusters | 3 | 3R / 0W |
| **Health** | NSX alarms, transport node status, edge cluster status, manager status | 4 | 4R / 0W |
| **Troubleshooting** | logical port status, VM-to-segment lookup | 2 | 2R / 0W |

**Total**: 33 tools (20 read-only + 13 write)

## Quick Install

```bash
uv tool install vmware-nsx-mgmt==1.9.0
vmware-nsx init      # guided setup: writes config + .env (chmod 600, password grep-safe), then verifies
vmware-nsx doctor
```

## When to Use This Skill

- List, create, or modify NSX segments (overlay / VLAN-backed)
- Create or manage Tier-0 / Tier-1 gateways
- Configure NAT rules (SNAT, DNAT, reflexive)
- View or add static routes, check BGP neighbors
- Manage IP pools and subnet allocations
- Check NSX alarms, transport node health, edge cluster status
- Find which segment a VM is connected to
- Troubleshoot logical port status

Use it only when the request is explicitly about NSX (NSX-T / NSX 4.x, NSX Manager). **Writes only on request**: call a create/update/delete tool, NAT/route/IP-pool change, or Tier-0 BGP change only when the user has explicitly asked for that specific change — never as a side step of a read, health check, or troubleshooting task. Diagnose with read tools first and propose the change instead.

**Use companion skills for**:
- Distributed firewall, security groups, DFW rules, IDS/IPS → `vmware-nsx-security`
- vSphere distributed port groups, host VMkernel adapters → `vmware-aiops`
- VM lifecycle, deployment, guest ops → `vmware-aiops`
- vSphere inventory, health, alarms, events → `vmware-monitor`
- Storage: iSCSI, vSAN, datastores → `vmware-storage`
- Tanzu Kubernetes → `vmware-vks`
- Load balancing, AVI/ALB, AKO, Ingress → `vmware-avi`

## Related Skills — Skill Routing

| User Intent | Recommended Skill |
|-------------|-------------------|
| NSX networking: segments, gateways, NAT, routing, IPAM | **vmware-nsx** ← this skill |
| NSX security: DFW rules, security groups, IDS/IPS | **vmware-nsx-security** |
| Read-only vSphere monitoring, alarms, events | **vmware-monitor** |
| VM lifecycle, deployment, guest ops | **vmware-aiops** |
| vSphere distributed port groups, host VMkernel adapters | **vmware-aiops** |
| Storage: iSCSI, vSAN, datastores | **vmware-storage** |
| Tanzu Kubernetes (vSphere 8.x+) | **vmware-vks** |
| Aria Ops: metrics, alerts, capacity planning | **vmware-aria** |
| Multi-step workflows with approval | **vmware-pilot** |
| Compliance baselines (CIS / 等保 / PCI-DSS), drift detection, LLM remediation advisor | **vmware-harden** (`uv tool install vmware-harden`) |
| Load balancer, AVI, ALB, AKO, Ingress | **vmware-avi** (`uv tool install vmware-avi`) |
| Audit log query | **vmware-policy** (`vmware-audit` CLI) |

## Common Workflows

### Create an App Network (Segment + T1 Gateway + NAT)

**Pre-flight (judgment, not blind sequence)**:
- Subnet conflict check: scan `inventory list-segments` and `networking list-ip-pools` for any overlap with the proposed CIDR. Overlapping subnets cause asymmetric routing or silent blackholing — NSX will not warn you.
- Edge cluster capacity: confirm chosen `--edge-cluster` is healthy (`inventory list-edge-clusters` + `health edge-cluster-status <id>`) and not at SR (Service Router) limit. A fully-loaded edge cluster will accept the T1 creation but routing will fail.
- T0 uplink: the parent T0 must already be configured with BGP/static routes upstream — otherwise SNAT works internally but external traffic goes nowhere.
- NAT IP: `--translated` IP must be from a routable address pool announced by T0; using a random IP creates a half-working network.
- **Always `--dry-run` first** — once a segment is attached to running VMs, deleting it requires detaching every port.

**Steps**:
1. `vmware-nsx gateway create-tier1 app-t1 --name app-t1 --edge-cluster <ec-path> --tier0 <t0-path> --dry-run` → review, then run for real
2. `vmware-nsx segment create app-web-seg --name app-web-seg --tz <tz-overlay-path> --subnet <gw-cidr>`
3. `vmware-nsx nat create-rule --tier1 app-t1 --rule-id snat-1 --action SNAT --source <private-cidr> --translated <pub-ip>`
4. Verify end-to-end: `inventory list-segments`, `networking list-nat-rules app-t1`, AND test with a VM attached to the new segment
5. **On failure**: a connection error or HTTP error prints a single teaching line (e.g. 403 → check NSX role privileges; 404 → run the matching list command for the exact ID). Run `vmware-nsx doctor` to verify connectivity and credentials, fix, and re-run the failed step — earlier completed steps are idempotent PUTs and safe to re-apply.

### Check Network Health

**Judgment**: don't just enumerate health endpoints — correlate them. The order below maps cause to symptom: if manager is down, transport nodes will look down too (false positive); fix top-down.

1. `vmware-nsx health manager-status` — if **any** manager node is `DEGRADED` or `DOWN`, stop here and resolve before trusting downstream signals
2. `vmware-nsx inventory list-transport-nodes` then `health transport-node-status <id>` for any node not `UP` — flag nodes down ≥ 5 min; transient blips are normal
3. `vmware-nsx inventory list-edge-clusters` then `health edge-cluster-status <id>` — verify SR placement is balanced; one edge holding 80% of SRs is a single point of failure
4. `vmware-nsx health alarms --severity HIGH` (repeat with `CRITICAL`) — severity filter is exact-match, not "and above"
5. Cross-check with `vmware-monitor` for vSphere host events — a host losing connection to vCenter often masquerades as an NSX problem

### Troubleshoot VM Connectivity

**Judgment**: connectivity failures happen at one of three layers. Identify which layer first, then drill — don't probe randomly.

- **Layer 1 — VM-to-segment**: VM has no segment, wrong vNIC, or port admin-down → `troubleshoot vm-segment` + `troubleshoot port-status`
- **Layer 2 — segment-to-gateway**: segment not attached to T1, T1 not connected to T0 → `inventory get-tier1` shows no Tier-0 path
- **Layer 3 — gateway-to-upstream**: T0 BGP/static missing or SNAT not configured → `networking bgp-neighbors`, `networking list-nat-rules`

**Steps** (stop as soon as the failing layer is identified):
1. Layer 1: `troubleshoot vm-segment my-vm-01` → if no port, check vSphere vNIC binding first
2. Layer 1: `troubleshoot port-status <segment-id>` → admin-down or DFW-blocked? If DFW, jump to vmware-nsx-security
3. Layer 2: `inventory get-tier1 app-t1` → Tier-0 path present and route advertisement enabled? If not, T1↔T0 link broken
4. Layer 3: `networking bgp-neighbors tier0-gw` → all neighbors `ESTABLISHED`? Flapping → upstream issue
5. Layer 3: `networking list-nat-rules app-t1` → SNAT rule covers the source CIDR? Mis-typed CIDR is the most common cause

### Multi-Target Operations

All commands accept `--target <name>` to operate against a specific NSX Manager from your config (default: the first target in config.yaml), e.g. `vmware-nsx inventory list-segments --target nsx-prod`.

## Usage Mode

| Scenario | Recommended | Why |
|----------|:-----------:|-----|
| Local/small models (Ollama, Qwen) | **CLI** | ~2K tokens vs ~8K for MCP |
| Cloud models (Claude, GPT-4o) | Either | MCP gives structured JSON I/O |
| Automated pipelines | **MCP** | Type-safe parameters, structured output |

## MCP Tools (33 — 20 read, 13 write)

All MCP tools accept an optional `target` parameter to select which NSX Manager to connect to.

| Category | Tool | Type | Description |
|----------|------|:----:|-------------|
| Segment | `list_segments` | Read | List all segments with type, subnet, admin state, port count |
| | `get_segment` | Read | Get segment details including ports and subnet config |
| | `create_segment` | Write | Create overlay or VLAN segment with subnet and gateway |
| | `update_segment` | Write | Update segment properties (name, subnets, gateway link) |
| | `delete_segment` | Write | Delete a segment; refuses (listing port ids) while ports are attached |
| Tier-0 GW | `list_tier0_gateways` | Read | List Tier-0 gateways with HA mode and transit subnets |
| | `get_tier0_gateway` | Read | Get Tier-0 details: HA mode, failover, transit subnets |
| | `get_bgp_neighbors` | Read | List BGP neighbor sessions with state, ASN, prefixes |
| | `configure_tier0_bgp` | Write | Configure BGP (local AS, ECMP, inter-SR iBGP) on a Tier-0 |
| Tier-1 GW | `list_tier1_gateways` | Read | List Tier-1 gateways with linked Tier-0 and route advertisement |
| | `get_tier1_gateway` | Read | Get Tier-1 details: Tier-0 link, route advertisement |
| | `create_tier1_gateway` | Write | Create Tier-1 gateway with edge cluster and Tier-0 link |
| | `update_tier1_gateway` | Write | Update Tier-1 properties (route advertisement, Tier-0 link) |
| | `delete_tier1_gateway` | Write | Delete a Tier-1 gateway; refuses (listing blocking ids) while segments, NAT rules, routes, interfaces or VPN / DNS / LB services remain |
| NAT | `list_nat_rules` | Read | List NAT rules on a Tier-1 gateway |
| | `create_nat_rule` | Write | Create SNAT/DNAT/reflexive NAT rule on a gateway |
| | `delete_nat_rule` | Write | Delete a NAT rule |
| Static Routes | `list_static_routes` | Read | List static routes on a Tier-1 gateway |
| | `create_static_route` | Write | Add a static route with network and next-hop |
| | `delete_static_route` | Write | Remove a static route |
| IP Pools | `list_ip_pools` | Read | List IP pools with usage summary |
| | `get_ip_pool_usage` | Read | Show allocation usage for a pool |
| | `create_ip_pool` | Write | Create a new IP address pool with allocation ranges |
| | `delete_ip_pool` | Write | Permanently delete an IP address pool |
| Fabric | `list_transport_zones` | Read | List transport zones with type (OVERLAY/VLAN) |
| | `list_transport_nodes` | Read | List transport nodes with node type and status |
| | `list_edge_clusters` | Read | List edge clusters with member count and deployment type |
| Health | `list_nsx_alarms` | Read | List active NSX alarms filtered by severity |
| | `get_transport_node_status` | Read | Transport node connectivity and config status |
| | `get_edge_cluster_status` | Read | Edge cluster member status and failover config |
| | `get_nsx_manager_status` | Read | NSX Manager cluster health and node roles |
| Troubleshoot | `get_logical_port_status` | Read | Realized state of all ports on a segment |
| | `get_segment_port_for_vm` | Read | Find which segment a VM is connected to by display name |

Write tools require explicit parameters and are audit-logged. Dry-run preview (`--dry-run`) is a CLI feature; MCP write tools execute directly, with no confirmation step of their own — call one only after the user has explicitly asked for that change.

### List results are envelopes — read `truncated` before you summarise

Every list-returning tool above returns `{items, returned, limit, total, truncated, hint}`, not a bare array. Rows live under `items`: empty `items` with `truncated: false` means the query genuinely matched nothing — report that, not a tool failure. `truncated: true` means `items` is not the whole collection — never call it complete. It does **not** mean more rows can be fetched: it stays true on the last page. Page with `next_offset`, stopping when it is `null`; `hint` says which situation you are in. Field semantics, `total` sourcing, and an example payload: `references/capabilities.md`.

## Local & Small Models

Running with local or small models? See [`references/agent-guardrails.md`](references/agent-guardrails.md) for explicit operating rules that keep tool calls reliable.

## CLI Quick Reference

```bash
# Inventory (read-only)
vmware-nsx inventory list-segments [--target <name>]
vmware-nsx inventory get-segment <segment-id>
vmware-nsx inventory list-tier0s
vmware-nsx inventory get-tier0 <tier0-id>
vmware-nsx inventory list-tier1s
vmware-nsx inventory get-tier1 <tier1-id>
vmware-nsx inventory list-transport-zones
vmware-nsx inventory list-transport-nodes
vmware-nsx inventory list-edge-clusters

# Networking (read-only)
vmware-nsx networking list-nat-rules <tier1-id>
vmware-nsx networking bgp-neighbors <tier0-id>
vmware-nsx networking list-static-routes <tier1-id>
vmware-nsx networking list-ip-pools
vmware-nsx networking ip-pool-usage <pool-id>

# Segment management (write; full option lists in references/cli-reference.md)
vmware-nsx segment create <id> --name <name> --tz <tz-path> [--vlan|--subnet] [--dry-run]
vmware-nsx segment update <id> [--name|--subnet] [--dry-run]
vmware-nsx segment delete <id> [--dry-run]

# Gateway management (write)
vmware-nsx gateway create-tier1 <id> --name <name> [--tier0|--edge-cluster] [--dry-run]
vmware-nsx gateway update-tier1 <id> [--name|--tier0|--advertise] [--dry-run]
vmware-nsx gateway delete-tier1 <id> [--dry-run]
vmware-nsx gateway configure-tier0-bgp <tier0-id> --local-as <asn> [--ecmp] [--dry-run]

# NAT (write)
vmware-nsx nat create-rule --tier1 <id> --rule-id <id> --action SNAT --source <cidr> --translated <ip> [--dry-run]
vmware-nsx nat delete-rule --tier1 <id> --rule-id <id> [--dry-run]

# Static routes (write)
vmware-nsx route create-static --tier1 <id> --route-id <id> --network <cidr> --next-hop <ip> [--dry-run]
vmware-nsx route delete-static --tier1 <id> --route-id <id> [--dry-run]

# IP pools (write)
vmware-nsx ip-pool create <pool-id> --name <name> --start <ip> --end <ip> --cidr <cidr> [--dry-run]

# Health & Troubleshooting (read-only)
vmware-nsx health alarms [--severity CRITICAL]
vmware-nsx health transport-node-status <node-id>
vmware-nsx health edge-cluster-status <cluster-id>
vmware-nsx health manager-status
vmware-nsx troubleshoot port-status <segment-id>
vmware-nsx troubleshoot vm-segment <vm-display-name>

# Diagnostics
vmware-nsx doctor [--skip-auth]
```

> Full CLI reference with all options and output formats: see `references/cli-reference.md`

## Troubleshooting

### "Segment not found" when querying

Segment display names and Policy API IDs can differ. Use `vmware-nsx inventory list-segments` to get the exact ID. The Policy API uses the segment `id` field, not `display_name`. Common mistakes: using the display name with spaces instead of the hyphenated ID.

### NAT rule creation fails with "gateway not found"

NAT rules are created on Tier-1 gateways (or Tier-0 for some topologies). Verify the gateway name with `vmware-nsx inventory list-tier1s`. The gateway must have an edge cluster assigned for NAT to function.

### BGP neighbor shows "Connect" or "Active" state

The BGP session is not established. Common causes:
1. Peer IP unreachable from the edge node — check physical uplinks and VLAN config
2. ASN mismatch — compare local and remote ASN in `bgp-neighbors` output
3. Firewall blocking TCP 179 — check edge node firewall rules (not NSX DFW)
4. MD5 password mismatch — verify authentication settings on both sides

### Transport node status "degraded"

A transport node in degraded state has partial connectivity. Steps:
1. Check `vmware-nsx health transport-nodes` for the specific failure reason
2. Common cause: tunnel endpoint (TEP) unreachable — verify underlay MTU (minimum 1600 for Geneve)
3. Check NTP sync between NSX Manager and transport nodes
4. If recently upgraded, verify the host switch config matches NSX Manager expectations

### "Password not found" error

The password environment variable is missing. Variable names follow the pattern `VMWARE_NSX_<TARGET_NAME_UPPER>_PASSWORD` where hyphens become underscores. Example: target `nsx-prod` needs `VMWARE_NSX_NSX_PROD_PASSWORD`. Check your `~/.vmware-nsx/.env` file.

## Safety

- **Read-heavy**: 20 of 33 tools are read-only (list, get, status, health, troubleshoot)
- **Audit logging**: All operations logged to `~/.vmware/audit.db` (SQLite WAL, via vmware-policy) with timestamp, user, target, operation, parameters, and result
- **Double confirmation**: CLI write commands require two separate confirmation prompts before executing
- **Dry-run mode**: All CLI write commands support `--dry-run` to preview API calls without executing (MCP write tools execute directly and are audit-logged)
- **Dependency checks**: Segment delete refuses while ports are attached. Tier-1 delete first checks (read-only) for attached or Tier-1-scoped segments, NAT rules, static routes, service interfaces, extra locale-services, IPsec / L2 VPN services, a DNS forwarder and attached LB services; while any remain it refuses, deletes nothing and lists their ids (`--dry-run` runs the same check). Only a clean gateway has its default locale-service removed and is then deleted
- **Input validation**: resource IDs restricted to letters, digits, `-` and `_`; NAT action checked against the allowed set; required fields checked (translated address for SNAT/DNAT/REFLEXIVE, CIDR + ranges per IP-pool subnet). CIDR/IP syntax and gateway existence are not checked client-side — they are left to NSX Manager's own API validation
- **Prompt injection defense**: NSX object names returned from the API are sanitized via `_sanitize()` — strips control characters, truncates to 500 chars
- **Credential safety**: Passwords loaded only from environment variables (`.env` file), never from `config.yaml`
- **No firewall operations**: Cannot create, modify, or delete DFW rules, security groups, or IDS/IPS policies — that scope belongs to `vmware-nsx-security`

## Setup

```bash
uv tool install vmware-nsx-mgmt==1.9.0
vmware-nsx init      # writes ~/.vmware-nsx/config.yaml + .env (chmod 600), then verifies
vmware-nsx doctor
```

> All tools are automatically audited via vmware-policy. Audit logs: `vmware-audit log --last 20`

> Full setup guide with multi-target config, MCP server setup, and Docker: see `references/setup-guide.md`

## Architecture

```
User (natural language)
  |
AI Agent (Claude Code / Goose / Cursor)
  | reads SKILL.md
vmware-nsx CLI or MCP server (stdio transport)
  | NSX Policy API (REST/JSON over HTTPS)
NSX Manager
  |
Segments / Gateways / NAT / Routes / IP Pools / Transport Nodes
```

## Audit & Safety

All operations are automatically audited via vmware-policy (`@vmware_tool` decorator):
- Every tool call logged to `~/.vmware/audit.db` (SQLite, framework-agnostic)
- Policy rules enforced via `~/.vmware/rules.yaml` (deny rules, maintenance windows, risk levels)
- Risk classification: each tool tagged as low/medium/high/critical
- View recent operations: `vmware-audit log --last 20`
- View denied operations: `vmware-audit log --status denied`

vmware-policy is automatically installed as a dependency — no manual setup needed.

## License

MIT — [github.com/vmware-skills/VMware-NSX](https://github.com/vmware-skills/VMware-NSX)

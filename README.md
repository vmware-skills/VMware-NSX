<!-- mcp-name: io.github.vmware-skills/vmware-nsx -->
# VMware NSX

> **Author**: Wei Zhou, VMware by Broadcom — wei-wz.zhou@broadcom.com
> This is a community-driven project by a VMware engineer, not an official VMware product.
> For official VMware developer tools see [developer.broadcom.com](https://developer.broadcom.com).

[English](README.md) | [中文](README-CN.md)

VMware NSX networking management: segments, gateways, NAT, routing, IPAM — 33 MCP tools, domain-focused.

> NSX Policy API skill for NSX-T 3.0+ and NSX 4.x.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## Companion Skills

| Skill | Scope | Tools | Install |
|-------|-------|:-----:|---------|
| **[vmware-aiops](https://github.com/vmware-skills/VMware-AIops)** ⭐ entry point | VM lifecycle, deployment, guest ops, clusters | 49 | `uv tool install vmware-aiops` |
| **[vmware-monitor](https://github.com/vmware-skills/VMware-Monitor)** | Read-only monitoring, alarms, events, VM info | 27 | `uv tool install vmware-monitor` |
| **[vmware-storage](https://github.com/vmware-skills/VMware-Storage)** | Datastores, iSCSI, vSAN | 11 | `uv tool install vmware-storage` |
| **[vmware-vks](https://github.com/vmware-skills/VMware-VKS)** | Tanzu Namespaces, TKC cluster lifecycle | 20 | `uv tool install vmware-vks` |
| **[vmware-nsx-security](https://github.com/vmware-skills/VMware-NSX-Security)** | DFW microsegmentation, security groups, Traceflow | 21 | `uv tool install vmware-nsx-security` |
| **[vmware-aria](https://github.com/vmware-skills/VMware-Aria)** | Aria Ops metrics, alerts, capacity planning | 28 | `uv tool install vmware-aria` |
| **[vmware-avi](https://github.com/vmware-skills/VMware-AVI)** | AVI/NSX ALB load balancing, AKO | 28 | `uv tool install vmware-avi` |
| **[vmware-harden](https://github.com/vmware-skills/VMware-Harden)** | Compliance baselines, drift detection | 6 | `uv tool install vmware-harden` |

## Quick Install

```bash
# Via PyPI
uv tool install vmware-nsx-mgmt

# Or pip
pip install vmware-nsx-mgmt
```

### Offline / Air-Gapped Install (from source)

This project uses the modern PEP 517 build system (hatchling), so there is **no
`setup.py`** by design — that is expected, not a missing file. If you cloned the
source and hit `ERROR: File "setup.py" or "setup.cfg" not found ... editable mode
currently requires a setuptools-based build`, your `pip` is older than 21.3 and
cannot do an *editable* (`-e`) install with a non-setuptools backend. Editable
mode is a developer convenience, not needed to run the tool — do one of:

```bash
# From the source tree — a normal (non-editable) install builds a wheel:
pip install .              # NOT  pip install -e .

# ...or upgrade pip first, and editable works too:
pip install --upgrade pip && pip install -e .
```

For a **truly air-gapped host**, build the wheels on a connected machine and copy
them over — the target then needs no network:

```bash
# On a connected machine, collect this package + its dependencies as wheels:
pip wheel . -w dist        # → dist/*.whl   (or: uv build, for just this package)

# Copy dist/ to the air-gapped host, then install offline:
pip install --no-index --find-links dist vmware-nsx-mgmt
```

## Configuration

```bash
mkdir -p ~/.vmware-nsx
cp config.example.yaml ~/.vmware-nsx/config.yaml
# Edit with your NSX Manager credentials

echo "VMWARE_NSX_NSX_PROD_PASSWORD=your_password" > ~/.vmware-nsx/.env
chmod 600 ~/.vmware-nsx/.env

# Verify
vmware-nsx doctor
```

## What This Skill Does

| Category | Tools | Count | Read / Write |
|----------|-------|:-----:|:------------:|
| **Segments** | list, get, create, update, delete | 5 | 2R / 3W |
| **Tier-0 Gateways** | list, get, BGP neighbors, configure BGP | 4 | 3R / 1W |
| **Tier-1 Gateways** | list, get, create, update, delete | 5 | 2R / 3W |
| **NAT** | list, create, delete | 3 | 1R / 2W |
| **Static Routes** | list, create, delete | 3 | 1R / 2W |
| **IP Pools** | list, usage, create, delete | 4 | 2R / 2W |
| **Fabric Inventory** | transport zones, transport nodes, edge clusters | 3 | 3R / 0W |
| **Health & Troubleshooting** | alarms, transport node status, edge cluster status, manager status, port status, VM-to-segment | 6 | 6R / 0W |

**Total**: 33 tools (20 read-only + 13 write)

## Common Workflows

### Create an App Network (Segment + T1 Gateway + NAT)

1. Create gateway: `vmware-nsx gateway create-t1 app-t1 --edge-cluster edge-cluster-01 --tier0 tier0-gw`
2. Create segment: `vmware-nsx segment create app-web-seg --name app-web-seg --tz <tz-overlay-path> --subnet 10.10.1.1/24`
3. Add SNAT: `vmware-nsx nat create app-t1 --action SNAT --source 10.10.1.0/24 --translated 172.16.0.10`
4. Verify: `vmware-nsx segment list` and `vmware-nsx nat list app-t1`

Use `--dry-run` to preview any write command first.

### Check Network Health

1. Manager status: `vmware-nsx health manager-status`
2. Transport nodes: `vmware-nsx health transport-nodes`
3. Edge clusters: `vmware-nsx health edge-clusters`
4. Alarms: `vmware-nsx health alarms --severity HIGH` (exact-match filter; query each severity separately)

### Troubleshoot VM Connectivity

1. Find VM's segment: `vmware-nsx troubleshoot vm-segment <vm-display-name>`
2. Check port realized state: `vmware-nsx troubleshoot port-status <segment-id>` (all ports on the segment: attachment, realized bindings, transport nodes)
3. Check routes: `vmware-nsx gateway routes-t1 app-t1`
4. Check BGP: `vmware-nsx gateway bgp-neighbors tier0-gw`

## MCP Tools (33 — 20 read, 13 write)

| Category | Tools | Type |
|----------|-------|------|
| Segments | `list_segments`, `get_segment`, `create_segment`, `update_segment`, `delete_segment` | Read/Write |
| Tier-0 GW | `list_tier0_gateways`, `get_tier0_gateway`, `get_bgp_neighbors`, `configure_tier0_bgp` | Read/Write |
| Tier-1 GW | `list_tier1_gateways`, `get_tier1_gateway`, `create_tier1_gateway`, `update_tier1_gateway`, `delete_tier1_gateway` | Read/Write |
| NAT | `list_nat_rules`, `create_nat_rule`, `delete_nat_rule` | Read/Write |
| Static Routes | `list_static_routes`, `create_static_route`, `delete_static_route` | Read/Write |
| IP Pools | `list_ip_pools`, `get_ip_pool_usage`, `create_ip_pool`, `delete_ip_pool` | Read/Write |
| Fabric | `list_transport_zones`, `list_transport_nodes`, `list_edge_clusters` | Read |
| Health | `list_nsx_alarms` (per-severity, exact match), `get_transport_node_status`, `get_edge_cluster_status`, `get_nsx_manager_status` | Read |
| Troubleshoot | `get_logical_port_status` (realized state of all ports on a segment), `get_segment_port_for_vm` (lookup by VM display name) | Read |

Full per-tool endpoints and methods: `skills/vmware-nsx/references/capabilities.md`.

## CLI

```bash
# Segments
vmware-nsx segment list
vmware-nsx segment get app-web-seg
vmware-nsx segment create app-web-seg --name app-web-seg --tz <tz-overlay-path> --subnet 10.10.1.1/24
vmware-nsx segment delete app-web-seg

# Gateways
vmware-nsx gateway list-t0
vmware-nsx gateway list-t1
vmware-nsx gateway create-t1 app-t1 --edge-cluster edge-cluster-01 --tier0 tier0-gw
vmware-nsx gateway bgp-neighbors tier0-gw
vmware-nsx gateway routes-t1 app-t1

# NAT
vmware-nsx nat list app-t1
vmware-nsx nat create app-t1 --action SNAT --source 10.10.1.0/24 --translated 172.16.0.10
vmware-nsx nat delete-rule --tier1 app-t1 --rule-id rule-01

# Static Routes
vmware-nsx route list app-t1
vmware-nsx route create app-t1 --network 192.168.100.0/24 --next-hop 10.10.1.254

# IP Pools
vmware-nsx ippool list
vmware-nsx ippool create tep-pool
vmware-nsx ippool add-subnet tep-pool --start 192.168.100.10 --end 192.168.100.50 --cidr 192.168.100.0/24

# Health & Troubleshooting
vmware-nsx health alarms --severity HIGH   # exact match: LOW | MEDIUM | HIGH | CRITICAL
vmware-nsx health transport-nodes
vmware-nsx health manager-status
vmware-nsx troubleshoot vm-segment my-vm-01          # VM display name
vmware-nsx troubleshoot port-status app-web-seg      # segment ID

# Diagnostics
vmware-nsx doctor
```

## MCP Server

**After `uv tool install vmware-nsx-mgmt`, start the MCP server with one command** (v1.5.15+):

```bash
# Recommended — single command, no network re-resolve
vmware-nsx mcp

# Or via Docker
docker compose up -d
```

### Agent Configuration

Add to your AI agent's MCP config:

```json
{
  "mcpServers": {
    "vmware-nsx": {
      "command": "vmware-nsx",
      "args": ["mcp"],
      "env": {
        "VMWARE_NSX_CONFIG": "~/.vmware-nsx/config.yaml"
      }
    }
  }
}
```

<details>
<summary>Alternative: uvx (no install) or legacy entry point</summary>

```bash
# Run without installing (requires PyPI access each launch)
uvx --from vmware-nsx-mgmt vmware-nsx mcp

# Legacy entry point (still works, kept for backward compatibility)
vmware-nsx-mcp
```

> **Behind a corporate TLS proxy?** uvx may fail with `invalid peer certificate: UnknownIssuer`.
> Use the recommended `vmware-nsx mcp` form above (no network needed), or set `UV_NATIVE_TLS=true`.

</details>

More agent config templates (Claude Code, Cursor, Goose, Continue, etc.) in [examples/mcp-configs/](examples/mcp-configs/).

## Version Compatibility

| NSX Version | Support | Notes |
|-------------|---------|-------|
| NSX 9.1 | Full | Policy API supported. Note: VDS 7.0+ required (N-VDS removed in NSX 9). |
| NSX 9.0 | Full | Policy API supported. Note: bare-metal agent / physical-server L2 overlay removed. |
| NSX 4.x | Full | Latest Policy API, all features |
| NSX-T 3.2 | Full | All features work |
| NSX-T 3.1 | Full | Minor route table format differences |
| NSX-T 3.0 | Compatible | IP pool subnet API introduced here |
| NSX-T 2.5 | Limited | Policy API incomplete; some tools may fail |
| NSX-V (6.x) | Not supported | Different API (SOAP-based) |

### VCF Compatibility

| VCF Version | Bundled NSX | Support |
|-------------|-------------|---------|
| VCF 9.1 | NSX 9.1 | Full |
| VCF 9.0 | NSX 9.0 | Full |
| VCF 5.x | NSX 4.x | Full |
| VCF 4.3-4.5 | NSX-T 3.1-3.2 | Full |

#### Official Broadcom References

- **SDKs**: <https://developer.broadcom.com/sdks> — VMware NSX for Python SDK (official; future migration target), VCF Python SDK
- **REST APIs**: <https://developer.broadcom.com/xapis> — NSX-T Data Center REST API (this skill uses the Policy API subset)
- **CLI Tools**: <https://developer.broadcom.com/tools> — VCF PowerCLI 9.1 (includes NSX cmdlets)

## Safety

| Feature | Description |
|---------|-------------|
| Read-heavy | 20/33 tools are read-only |
| Double confirmation | CLI write commands require two prompts |
| Dry-run mode | All write commands support `--dry-run` preview |
| Dependency checks | Segment delete refuses while ports are attached; Tier-1 delete refuses, deleting nothing, while segments, NAT rules, static routes, interfaces or VPN / DNS forwarder / LB services still depend on it (`--dry-run` runs the same check). Other deletes are not pre-checked |
| Input validation | CIDR, IP, VLAN IDs, gateway existence validated |
| Audit logging | All operations logged to `~/.vmware-nsx/audit.log` |
| No firewall ops | Cannot create/modify DFW rules or security groups |
| Credential safety | Passwords only from environment variables |
| Prompt injection defense | NSX object names sanitized before output |

## Troubleshooting

| Problem | Cause & Fix |
|---------|-------------|
| "Segment not found" | Policy API uses segment `id`, not `display_name`. Run `segment list` to get the exact ID. |
| NAT creation fails "gateway not found" | NAT requires a Tier-1 (or Tier-0) gateway. Verify with `gateway list-t1`. Gateway must have an edge cluster. |
| BGP neighbor stuck in Connect/Active | Peer unreachable, ASN mismatch, TCP 179 blocked, or MD5 password mismatch. |
| Transport node "degraded" | TEP unreachable (check MTU >= 1600), NTP sync issues, or host switch config mismatch. |
| "Password not found" | Variable naming: `VMWARE_NSX_<TARGET_UPPER>_PASSWORD` (hyphens to underscores). Check `~/.vmware-nsx/.env`. |
| Connection timeout | Use `vmware-nsx doctor --skip-auth` to bypass auth checks on high-latency networks. |

## License

[MIT](LICENSE)

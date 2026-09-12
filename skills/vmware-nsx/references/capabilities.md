# Capabilities

Detailed capability reference for `vmware-nsx`.

## Automation Level Reference

Each operation is classified by autonomy level per the Enterprise Harness Engineering framework:

| Level | Meaning | Agent autonomy | Examples in this skill |
|:-:|---|---|---|
| **L1** | Read-only, raw data | Always auto-run | `list_segments`, `get_segment`, `list_tier0_gateways`, `list_tier1_gateways`, `list_nat_rules`, `list_ip_pools`, `list_static_routes`, alarms/health queries |
| **L2** | Read + analysis / recommendation | Always auto-run | `get_bgp_neighbors`, `get_segment_port_for_vm`, `get_ip_pool_usage`, `get_logical_port_status` — correlation and utilization summaries over raw data |
| **L3** | Single write — user must approve | Only when the user explicitly asked for that change; CLI adds double-confirm + optional `--dry-run`; segment delete refuses while ports are attached; Tier-1 delete refuses while anything still depends on the gateway | `create_segment`, `delete_segment`, `create_nat_rule`, `update_tier1_gateway`, `create_ip_pool`, `configure_tier0_bgp`, static route mutations |
| **L4** | Multi-step plan / apply workflow | Plan generation auto; apply gated by user approval | *(roadmap — multi-segment rollout plans, gateway HA failover sequences)* |
| **L5** | Auto-remediation from learned pattern | Pattern library only; requires `risk:low` + `reversible:true` + `repeatable:true` | *(roadmap — candidates: stale segment cleanup, transport-node refresh)* |

**Notes**:
- L1/L2 tools are always safe for agents to call without confirmation.
- L3 tools always pass through the `@vmware_tool` decorator: policy check (`~/.vmware/rules.yaml` deny rules, per environment) → execute → audit log. MCP write tools have no confirmation step of their own — getting the user's explicit approval is the agent's job; the CLI's double-confirm and `--dry-run` do not apply to MCP calls. Segment delete additionally verifies port count = 0; Tier-1 delete runs the dependency pre-check below and refuses, deleting nothing, while any dependent remains.
- For DFW/security rules see [vmware-nsx-security](https://github.com/vmware-skills/VMware-NSX-Security).

## API Coverage

vmware-nsx uses the **NSX Policy API** (not the Management API) for all operations. The Policy API provides a declarative, intent-based interface that is the recommended path for NSX-T 3.x and NSX 4.x.

### Policy API vs Management API

| Aspect | Policy API (used by this skill) | Management API (not used) |
|--------|--------------------------------|--------------------------|
| Endpoint prefix | `/policy/api/v1/` | `/api/v1/` |
| Model | Declarative, intent-based | Imperative, realized-state |
| Object IDs | User-defined string IDs | System-generated UUIDs |
| Hierarchy | Infra → Tier-0 → Tier-1 → Segment | Flat namespace |
| Transaction support | Hierarchical API (PATCH entire tree) | Individual API calls |
| Recommended by VMware | Yes (primary API since NSX-T 3.0) | Deprecated for new development |

**Why Policy API?** The Policy API allows setting desired state declaratively. NSX Manager reconciles realized state automatically. This is safer for automation — you describe what you want, NSX figures out how to get there.

## Tool Capabilities by Category

The tables below list **every** MCP tool this skill exposes — 33 total (20 read, 13 write).
Tool names are exactly as registered on the MCP server; endpoints and methods are taken
from the corresponding `vmware_nsx/ops/` implementation. Anything not listed here does
not exist.

Classification follows each tool's `[READ]`/`[WRITE]` docstring marker; see README.

### Segments (5 tools — 2 read, 3 write)

| Capability | Tool | API Endpoint | Method |
|------------|------|-------------|--------|
| List all segments | `list_segments` | `/policy/api/v1/infra/segments` | GET |
| Get segment details (includes its ports) | `get_segment` | `/policy/api/v1/infra/segments/{id}` + `/ports` | GET |
| Create segment | `create_segment` | `/policy/api/v1/infra/segments/{id}` | PUT |
| Update segment | `update_segment` | `/policy/api/v1/infra/segments/{id}` | PATCH |
| Delete segment | `delete_segment` | Pre-check (GET): `/policy/api/v1/infra/segments/{id}/ports` — refuses, listing port ids, while any is attached. Then `/policy/api/v1/infra/segments/{id}` | GET, DELETE |

**Note**: there is no standalone segment-port listing tool. Ports are returned by
`get_segment` (attached ports + total count) and, with realized state, by
`get_logical_port_status`.

**Segment types supported**:
- Overlay segments (Geneve encapsulation, requires overlay transport zone)
- VLAN-backed segments (requires VLAN transport zone + VLAN ID)

**Segment features**:
- Subnet configuration (gateway CIDR)
- DHCP configuration (static bindings, relay)
- Connectivity to Tier-1 gateways
- Tags and metadata
- Admin state management

### Tier-0 Gateways (4 tools — 3 read, 1 write)

| Capability | Tool | API Endpoint | Method |
|------------|------|-------------|--------|
| List Tier-0 gateways | `list_tier0_gateways` | `/policy/api/v1/infra/tier-0s` | GET |
| Get Tier-0 details | `get_tier0_gateway` | `/policy/api/v1/infra/tier-0s/{id}` | GET |
| BGP config + neighbor status | `get_bgp_neighbors` | `/policy/api/v1/infra/tier-0s/{id}/locale-services`, then `.../{ls}/bgp`, `.../{ls}/bgp/neighbors`, `.../{ls}/bgp/neighbors/status` | GET |
| Configure BGP on a Tier-0 | `configure_tier0_bgp` | `/policy/api/v1/infra/tier-0s/{id}/locale-services/{ls}/bgp` | PATCH |

**Note**: Tier-0 gateways cannot be created or deleted by this skill — that is a high-impact
infrastructure operation normally done during initial NSX deployment. The only Tier-0 write
tool is `configure_tier0_bgp` (local AS, ECMP, inter-SR iBGP on an existing locale-service).
There is **no** Tier-0 or Tier-1 route-table tool; use `list_static_routes` for configured
static routes and `get_bgp_neighbors` for learned-route peering state.

### Tier-1 Gateways (5 tools — 2 read, 3 write)

| Capability | Tool | API Endpoint | Method |
|------------|------|-------------|--------|
| List Tier-1 gateways | `list_tier1_gateways` | `/policy/api/v1/infra/tier-1s` | GET |
| Get Tier-1 details | `get_tier1_gateway` | `/policy/api/v1/infra/tier-1s/{id}` | GET |
| Create Tier-1 | `create_tier1_gateway` | `/policy/api/v1/infra/tier-1s/{id}`, plus `.../locale-services/default` when an edge cluster is given | PUT |
| Update Tier-1 | `update_tier1_gateway` | `/policy/api/v1/infra/tier-1s/{id}` | PATCH |
| Delete Tier-1 | `delete_tier1_gateway` | Pre-check (GET) — refuses, listing ids, if any remain: `/policy/api/v1/infra/segments` and `/policy/api/v1/infra/lb-services` (by `connectivity_path`); under `.../tier-1s/{id}/`: `segments`, `nat/USER/nat-rules`, `static-routes`, `locale-services` (any but `default`), `locale-services/default/interfaces`, `ipsec-vpn-services`, `l2vpn-services`, `dns-forwarder`. A 404 means none; any other read error aborts without deleting. Then `.../locale-services/default` (best effort), then `/policy/api/v1/infra/tier-1s/{id}` | GET, DELETE |

**Route advertisement types**:
- `TIER1_CONNECTED` — Connected subnets
- `TIER1_NAT` — NAT IP addresses
- `TIER1_STATIC_ROUTES` — Static routes
- `TIER1_LB_VIP` — Load balancer VIPs
- `TIER1_LB_SNAT` — Load balancer SNAT IPs
- `TIER1_DNS_FORWARDER_IP` — DNS forwarder IPs
- `TIER1_IPSEC_LOCAL_ENDPOINT` — IPSec local endpoints

### NAT (3 tools — 1 read, 2 write)

| Capability | Tool | API Endpoint | Method |
|------------|------|-------------|--------|
| List NAT rules | `list_nat_rules` | `/policy/api/v1/infra/tier-1s/{id}/nat/USER/nat-rules` | GET |
| Create NAT rule | `create_nat_rule` | `/policy/api/v1/infra/tier-1s/{id}/nat/USER/nat-rules/{rule}` | PUT |
| Delete NAT rule | `delete_nat_rule` | `/policy/api/v1/infra/tier-1s/{id}/nat/USER/nat-rules/{rule}` | DELETE |

**No get/update NAT tool**: read a single rule by listing the gateway's rules and filtering
client-side; change a rule by re-issuing `create_nat_rule` with the same `rule_id` (the
Policy API PUT is an idempotent upsert).

**NAT action types**:
- `SNAT` — Source NAT (outbound traffic)
- `DNAT` — Destination NAT (inbound traffic)
- `REFLEXIVE` — Stateless bidirectional NAT
- `NO_SNAT` — Exempt from SNAT
- `NO_DNAT` — Exempt from DNAT

**Tier-1 only**: the NAT tools address `/tier-1s/` exclusively — the gateway id parameter is
`tier1_id` and the path is not switched by gateway type. Tier-0 NAT is not reachable through
this skill.

### Static Routes (3 tools — 1 read, 2 write)

| Capability | Tool | API Endpoint | Method |
|------------|------|-------------|--------|
| List static routes | `list_static_routes` | `/policy/api/v1/infra/tier-{0,1}s/{id}/static-routes` | GET |
| Create static route | `create_static_route` | `/policy/api/v1/infra/tier-{0,1}s/{id}/static-routes/{route}` | PUT |
| Delete static route | `delete_static_route` | `/policy/api/v1/infra/tier-{0,1}s/{id}/static-routes/{route}` | DELETE |

Unlike NAT, these three do select `tier-0s` or `tier-1s` from the gateway type argument.

### IP Pools (4 tools — 2 read, 2 write)

| Capability | Tool | API Endpoint | Method |
|------------|------|-------------|--------|
| List pools | `list_ip_pools` | `/policy/api/v1/infra/ip-pools` | GET |
| Get allocations for one pool | `get_ip_pool_usage` | `/policy/api/v1/infra/ip-pools/{id}/ip-allocations` | GET |
| Create pool (with one static subnet) | `create_ip_pool` | `/policy/api/v1/infra/ip-pools/{id}`, then `.../ip-subnets/{subnet}` | PUT |
| Delete pool | `delete_ip_pool` | `/policy/api/v1/infra/ip-pools/{id}` | DELETE |

**Note**: subnet creation is not a separate tool — `create_ip_pool` writes the pool and its
one static subnet + allocation range in a single call. It is two PUTs, not atomic: if the
subnet PUT fails, the pool exists without it and the call returns a top-level `error` saying
so (audited as a failure), with the cleanup — `delete_ip_pool`, then create again.

**IP pool use cases**:
- TEP (Tunnel Endpoint) IP assignment
- SNAT IP pool for gateways
- Load balancer VIP pools
- Custom automation IP management

### Fabric Inventory (3 tools — 3 read, 0 write)

| Capability | Tool | API Endpoint | Method |
|------------|------|-------------|--------|
| List transport zones | `list_transport_zones` | `/policy/api/v1/infra/sites/default/enforcement-points/default/transport-zones` | GET |
| List transport nodes | `list_transport_nodes` | `/api/v1/transport-nodes` | GET |
| List edge clusters | `list_edge_clusters` | `/api/v1/edge-clusters` | GET |

### Health (4 tools — 4 read, 0 write)

| Capability | Tool | API Endpoint | Method |
|------------|------|-------------|--------|
| NSX alarms at one severity | `list_nsx_alarms` | `/api/v1/alarms` | GET |
| Transport node status | `get_transport_node_status` | `/api/v1/transport-nodes/{id}/status` | GET |
| Edge cluster status | `get_edge_cluster_status` | `/api/v1/edge-clusters/{id}/status` | GET |
| Manager cluster status | `get_nsx_manager_status` | `/api/v1/cluster/status` | GET |

### Troubleshooting (2 tools — 2 read, 0 write)

| Capability | Tool | API Endpoint | Method |
|------------|------|-------------|--------|
| Realized state of all ports on a segment | `get_logical_port_status` | `/policy/api/v1/infra/segments/{id}` + `/ports`, then `/ports/{port}/state` per port | GET |
| VM-to-segment lookup by display name | `get_segment_port_for_vm` | `/api/v1/fabric/virtual-machines`, `/api/v1/fabric/vifs`, then `/policy/api/v1/search/query` (falls back to scanning `/policy/api/v1/infra/segments/{id}/ports`) | GET |

**Note**: Health and troubleshooting tools use a mix of Policy API and Management API endpoints. The Management API is used where the Policy API does not yet expose equivalent realized-state or status information (alarms, transport node status, fabric VM/VIF discovery).

### Tool Count Summary

| Category | Tools | Read | Write |
|----------|:-----:|:----:|:-----:|
| Segments | 5 | 2 | 3 |
| Tier-0 Gateways | 4 | 3 | 1 |
| Tier-1 Gateways | 5 | 2 | 3 |
| NAT | 3 | 1 | 2 |
| Static Routes | 3 | 1 | 2 |
| IP Pools | 4 | 2 | 2 |
| Fabric Inventory | 3 | 3 | 0 |
| Health | 4 | 4 | 0 |
| Troubleshooting | 2 | 2 | 0 |
| **Total** | **33** | **20** | **13** |

## NSX Version Compatibility

| NSX Version | Support Level | Notes |
|-------------|--------------|-------|
| NSX 9.1 | Full | Policy API supported. Note: VDS 7.0+ required (N-VDS removed in NSX 9). |
| NSX 9.0 | Full | Policy API supported. Note: bare-metal agent / physical-server L2 overlay removed. |
| NSX 4.2.x | Full | Latest, all features supported |
| NSX 4.1.x | Full | All features supported |
| NSX 4.0.x | Full | Policy API v1 fully available |
| NSX-T 3.2.x | Full | Policy API mature, all features work |
| NSX-T 3.1.x | Full | Minor differences in route table API response format |
| NSX-T 3.0.x | Compatible | IP pool subnet API introduced here; older formats handled |
| NSX-T 2.5.x | Limited | Policy API available but incomplete; some tools may fail |
| NSX-V (6.x) | Not supported | Completely different API (SOAP-based). Use legacy tools |

### VCF (VMware Cloud Foundation) Compatibility

| VCF Version | Bundled NSX | Support |
|-------------|-------------|---------|
| VCF 9.1 | NSX 9.1 | Full |
| VCF 9.0 | NSX 9.0 | Full |
| VCF 5.2 | NSX 4.2.x | Full |
| VCF 5.1 | NSX 4.1.x | Full |
| VCF 5.0 | NSX 4.0.x | Full |
| VCF 4.5 | NSX-T 3.2.x | Full |
| VCF 4.4 | NSX-T 3.2.x | Full |
| VCF 4.3 | NSX-T 3.1.x | Full |

## Scope Boundaries

### What This Skill Does

- Network infrastructure: segments, gateways, routing, NAT, IPAM
- Network health: alarms, transport nodes, edge clusters, manager status
- Network troubleshooting: port status, VM-to-segment mapping

### What This Skill Does NOT Do

| Capability | Responsible Skill |
|------------|-------------------|
| Distributed Firewall (DFW) rules | `vmware-nsx-security` |
| Security groups and policies | `vmware-nsx-security` |
| IDS/IPS configuration | `vmware-nsx-security` |
| URL filtering | `vmware-nsx-security` |
| Service insertion / east-west security | `vmware-nsx-security` |
| VM lifecycle (power, deploy, guest ops) | `vmware-aiops` |
| vSphere inventory and health | `vmware-monitor` |
| Storage (datastores, iSCSI, vSAN) | `vmware-storage` |
| Tanzu Kubernetes | `vmware-vks` |
| Load balancing | Future skill or NSX ALB |
| VPN (IPSec / L2VPN) | Future skill |
| NSX Intelligence / Network Detection and Response | Future skill |

## Rate Limiting and Pagination

- NSX Policy API supports pagination via `cursor` and `page_size` parameters
- Default page size: 1000 objects (configurable)
- List operations automatically paginate through all results
- NSX Manager has built-in rate limiting; the skill respects `429 Too Many Requests` responses with automatic backoff
- Recommendation: for environments with >500 segments or >200 gateways, use targeted `get` operations instead of `list`

### List Result Envelope

Every list-returning tool wraps its rows in the family envelope
(`vmware_policy.paginated`) rather than returning a bare array, so an agent can
tell a complete answer from page one instead of guessing (VMware-AIops issue
#31). Keys: `items`, `returned`, `limit`, `total`, `truncated`, `hint` — always
all six, with explicit `null` where a value is unknown — plus the `next_offset`
extra. Example payload:

```json
{
  "items":       [ ... ],
  "returned":    50,
  "limit":       50,
  "total":       412,
  "truncated":   true,
  "next_offset": 50,
  "hint":        "Showing rows 0-49 of 412. Continue at offset 50 for the next page, or narrow the query with a filter."
}
```

`next_offset` is the stop signal, and `truncated` is not. `truncated` answers
"is `items` the whole collection?", which is still `true` on the last page of a
walk — rows 400-411 of 412 are not 412 rows. A loop driven by `truncated` never
terminates; a loop driven by `next_offset is null` ends on the last page.

`hint` is written for that same distinction. Mid-walk it names the offset to
pass back; on the last page it says there is no next page, and on a page past
the end it says the offset is past the end and to start again at 0. It never
tells you to raise a limit that cannot return another row.

`total` is the collection's `result_count` from the NSX ListResult. It is read
from the pages `get_all` already fetched (via `CollectionTotal`), so it costs no
extra round trip, and it stays `null` — never inferred — when the API omits the
field.

| Tool | Bound | `total` source |
|------|-------|---------------|
| `list_segments` | `limit` (default 50) | `result_count` on `/policy/api/v1/infra/segments` |
| `list_tier0_gateways` | `limit` (default 50) | `result_count` on `/policy/api/v1/infra/tier-0s` |
| `list_tier1_gateways` | `limit` (default 50) | `result_count` on `/policy/api/v1/infra/tier-1s` |
| `list_transport_zones` | `limit` (default 50) | `result_count` on the enforcement-point transport-zones path |
| `list_transport_nodes` | `limit` (default 50) | `result_count` on `/api/v1/transport-nodes` |
| `list_edge_clusters` | `limit` (default 50) | `result_count` on `/api/v1/edge-clusters` |
| `list_nat_rules` | `limit` (default 50) | `result_count` on the Tier-1's `/nat/USER/nat-rules` |
| `list_static_routes` | `limit` (default 50) | `result_count` on the gateway's `/static-routes` |
| `list_ip_pools` | `limit` (default 50) | `result_count` on `/policy/api/v1/infra/ip-pools` |
| `list_nsx_alarms` | none — every alarm at the severity | `result_count` on `/api/v1/alarms`; exceeds `returned` only when the 1000-item client backstop cut the walk short |

Because `total` is normally present, a page filled exactly to the limit is
recognised as complete when it matches the collection size, rather than being
conservatively flagged truncated. When `total` is `null` (older APIs that omit
`result_count`), a page filled exactly to the limit is conservatively flagged
truncated and may in fact be complete. CLI commands unwrap `items` and print
the rows; the envelope is the MCP/library contract.

## Authentication

The skill authenticates to NSX Manager using HTTP Basic Authentication over HTTPS. This is the standard authentication method for the NSX Policy API.

**Supported authentication methods**:
- Local NSX Manager credentials (admin user)
- vIDM-backed credentials (when NSX Manager is integrated with Identity Manager)
- Principal Identity certificates (configure `cert_path` and `key_path` in config.yaml instead of password)

**Session management**: Each API call creates an independent HTTPS request with Basic Auth headers. No persistent sessions are maintained, which simplifies connection pooling and avoids session timeout issues.

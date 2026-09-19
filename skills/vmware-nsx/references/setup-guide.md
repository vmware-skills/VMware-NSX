# Setup Guide

Complete setup and security guide for `vmware-nsx`.

## Prerequisites

- Python 3.10+
- NSX-T 3.0+ or NSX 4.x Manager
- Network access to NSX Manager on port 443 (HTTPS)
- NSX Manager credentials with appropriate role (minimum: `network_engineer` for read-only, `enterprise_admin` for write operations)

## Installation

### Via uv (recommended)

```bash
uv tool install vmware-nsx-mgmt==1.10.0
```

### Via pip

```bash
pip install vmware-nsx-mgmt==1.10.0
```

### From source

```bash
git clone --branch v1.10.0 https://github.com/vmware-skills/VMware-NSX.git
cd VMware-NSX
pip install -e .
```

## Configuration

### 1. Create config directory

```bash
mkdir -p ~/.vmware-nsx
```

### 2. Create config.yaml

```bash
cp config.example.yaml ~/.vmware-nsx/config.yaml
```

Edit `~/.vmware-nsx/config.yaml`:

```yaml
targets:
  nsx-prod:                      # Target name (used in CLI --target flag)
    host: nsx-mgr.example.com    # NSX Manager hostname or IP (or VIP for cluster)
    username: svc-nsx            # NSX Manager service account (least privilege)
    port: 443
    verify_ssl: true             # The default. Keep it on for any real environment
    environment: production      # Which environment this is — see below

  nsx-lab:                       # Isolated lab only
    host: 10.0.0.100
    username: admin
    port: 443
    verify_ssl: false            # Lab NSX Manager with its factory self-signed cert
    environment: lab

default_target: nsx-prod
```

`targets` is a mapping keyed by target name. `default_target` is used when `--target` is not specified; without it, every command must name a target.

**TLS verification**: `verify_ssl` defaults to `true` when omitted. If NSX Manager's certificate is issued by a private/enterprise CA, keep `verify_ssl: true` and point the `SSL_CERT_FILE` environment variable at a PEM bundle that contains that CA (or `SSL_CERT_DIR` at a hashed CA directory) — in your shell, or in the MCP server's `env` block. `SSL_CERT_FILE` replaces the default trust store for that process, so include any other CAs it needs. `verify_ssl: false` disables certificate and hostname checks entirely; use it only for an isolated lab NSX Manager, never for a production target.

**`environment` (optional label)**: policy scopes its rules by this value, so an environment-scoped `deny` rule in `~/.vmware/rules.yaml` can match on it — for example, to freeze state-changing writes on `production`. Any label you like works (`production`, `staging`, `lab`, `dc2-prod`); the target's *name* is not used for it. A target with no label is simply not matched by such a rule. Read-only operations are never affected either way. Run `vmware-audit policy` to see the rules currently in force.

**NSX Manager cluster**: Use the cluster VIP as the `host` value. The VIP automatically routes to the active manager node.

### 3. Create .env for credentials

Passwords are **never stored in config.yaml**. They must be set as environment variables via the `.env` file.

```bash
echo "VMWARE_NSX_NSX_PROD_PASSWORD=your_password" > ~/.vmware-nsx/.env
echo "VMWARE_NSX_NSX_LAB_PASSWORD=lab_password" >> ~/.vmware-nsx/.env
chmod 600 ~/.vmware-nsx/.env
```

**Naming convention**: `VMWARE_NSX_<TARGET_NAME_UPPER>_PASSWORD` where `<TARGET_NAME_UPPER>` is the target `name` from config.yaml, uppercased, with hyphens replaced by underscores.

Examples:
| Target name | Environment variable |
|-------------|---------------------|
| `nsx-prod` | `VMWARE_NSX_NSX_PROD_PASSWORD` |
| `nsx-lab` | `VMWARE_NSX_NSX_LAB_PASSWORD` |
| `nsx01` | `VMWARE_NSX_NSX01_PASSWORD` |

### 4. Verify setup

```bash
vmware-nsx doctor
```

This runs six checks: config file, .env file, targets, network connectivity, authentication, and MCP server module.

Use `--skip-auth` if NSX Manager is temporarily unreachable:

```bash
vmware-nsx doctor --skip-auth
```

## MCP Server Configuration

> **v1.5.15+ recommends the single-command form `vmware-nsx mcp`.** Pre-1.5.15 used
> `vmware-nsx-mcp`, which still works (backward compatible) but the new form
> reuses the already-installed `vmware-nsx` binary on PATH and avoids any PyPI
> re-resolve / TLS-proxy issues.

### Claude Code / Claude Desktop

Add to your MCP config (`~/.claude.json` or Claude Desktop settings):

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

### Cursor

Add to Cursor MCP settings:

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

### Goose

Add to `~/.config/goose/config.yaml`:

```yaml
extensions:
  vmware-nsx:
    type: stdio
    cmd: vmware-nsx
    args: [mcp]
    env:
      VMWARE_NSX_CONFIG: "~/.vmware-nsx/config.yaml"
```

### VS Code Copilot

Add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "vmware-nsx": {
      "type": "stdio",
      "command": "vmware-nsx",
      "args": ["mcp"],
      "env": {
        "VMWARE_NSX_CONFIG": "~/.vmware-nsx/config.yaml"
      }
    }
  }
}
```

### Continue

Add to `~/.continue/config.yaml`:

```yaml
mcpServers:
  - name: vmware-nsx
    command: vmware-nsx
    args: [mcp]
    env:
      VMWARE_NSX_CONFIG: ~/.vmware-nsx/config.yaml
```

### Troubleshooting

| Issue | Solution |
|-------|----------|
| `invalid peer certificate: UnknownIssuer` (uvx) | Corporate TLS proxy not trusted by uv's bundled cert store. Use `vmware-nsx mcp` instead, or `export UV_NATIVE_TLS=true` |
| `command not found: vmware-nsx` | Run `uv tool update-shell` then re-source your shell rc, or use the absolute path returned by `which vmware-nsx-mcp` |

### Docker

```bash
docker compose up -d
```

Or run manually:

```bash
docker run -d \
  -v ~/.vmware-nsx:/root/.vmware-nsx:ro \
  -e VMWARE_NSX_CONFIG=/root/.vmware-nsx/config.yaml \
  vmware-nsx
```

### Password obfuscation at rest

On first load, any plaintext `*_PASSWORD` value in `.env` is automatically
rewritten to a grep-safe `b64:<encoded>` form and decoded transparently at
runtime, so a casual `grep` of the file no longer reveals the password. Values
are read and written through python-dotenv's own parser, so the stored secret
never drifts from what you configured (quotes, inline comments, and trailing
whitespace are handled correctly).

> **This is obfuscation, not encryption.** Anyone who can read the file can
> still decode it. For real secrecy at rest, do not store the password in `.env`
> at all — inject it from a secret manager (HashiCorp Vault, CyberArk, AWS
> Secrets Manager, or a Kubernetes Secret) into the `*_PASSWORD` environment
> variable at process start. The code reads the env var either way.

## Read-Only Operation

To run the agent read-only, give it a read-only NSX service account (RBAC).

## Security Details

> **Disclaimer**: This is a community-maintained open-source project and is **not affiliated with, endorsed by, or sponsored by VMware, Inc. or Broadcom Inc.** "VMware" and "NSX" are trademarks of Broadcom.

### Credential Safety

- Passwords are **only loaded from environment variables** (via `.env` file), never from `config.yaml`
- The `.env` file permissions are checked at startup; a warning is logged if permissions are wider than `600` (owner read/write only)
- The `doctor` command verifies `.env` permissions and reports failures

### Authentication

Authentication is username/password against the NSX session-create API. Credentials are
form-body encoded, so passwords containing special characters are handled correctly.
Per-target passwords come from `~/.vmware-nsx/.env` (`VMWARE_NSX_<TARGET_NAME_UPPER>_PASSWORD`).

> Principal Identity / client-certificate authentication is not currently implemented.

### Audit Logging

All operations are logged to `~/.vmware/audit.db` (SQLite WAL mode, via vmware-policy).

Each audit entry records:
- **timestamp**: UTC ISO 8601
- **target**: Which NSX Manager was acted on
- **operation**: What was done (e.g., `create_segment`, `delete_nat_rule`, `query`)
- **resource**: What resource was affected (segment ID, gateway ID, rule ID)
- **parameters**: Full parameter set passed to the operation
- **before_state / after_state**: State snapshots (when available)
- **result**: Operation outcome
- **user**: OS username who initiated the operation

Example audit entry:

```json
{
  "timestamp": "2026-03-26T10:30:00+00:00",
  "target": "nsx-prod",
  "operation": "create_segment",
  "resource": "app-web-seg",
  "parameters": {"name": "app-web-seg", "gateway": "app-t1", "subnet": "10.10.1.1/24", "transport_zone": "tz-overlay"},
  "before_state": null,
  "after_state": {"id": "app-web-seg", "type": "OVERLAY", "admin_state": "UP"},
  "result": "Segment 'app-web-seg' created successfully.",
  "user": "admin"
}
```

Read-only operations are also logged with `operation: "query"` for complete traceability.

### Double Confirmation on Write Operations

CLI write commands require two separate confirmation prompts before executing:

1. First prompt: "Confirm #1: <action> '<resource>'?" (default: No)
2. Second prompt: "Confirm #2: This is irreversible. <action> '<resource>'?" (default: No)

Both must be answered `y` for the operation to proceed. This applies to all CLI create, update, and delete commands. The five MCP delete tools preview by default: without `confirm=True` they return the blast radius and delete nothing, and `confirm=True` is refused while a blocker remains or a read failed. Other MCP write tools execute when called (and are audit-logged), so the agent must call them only after the user has explicitly asked for that change. Use `~/.vmware/rules.yaml` deny rules to block writes on environments such as `production`.

### Dry-Run Mode

All write commands support `--dry-run` to preview what would happen without making changes:

```bash
vmware-nsx segment create app-web-seg --name app-web-seg --tz <tz-overlay-path> --subnet 10.10.1.1/24 --dry-run

vmware-nsx nat create-rule --tier1 app-t1 --rule-id snat-1 --action SNAT --source 10.10.1.0/24 --translated 172.16.0.10 --dry-run
```

Dry-run prints the target, the API call it would make and its parameters (for updates and deletes, also the object's current state), then exits without changing anything.

### Dependency Checks

- **Segment delete**: Checks for attached ports. If any port is still attached (VMs or router interfaces), the operation is refused — there is no override; detach the ports first
- **Tier-1 gateway delete**: Checks first, read-only: segments attached by `connectivity_path` and Tier-1-scoped segments, NAT rules, static routes, service interfaces on the `default` locale-service, locale-services other than `default`, IPsec / L2 VPN services, a DNS forwarder, and LB services attached to it. While any remain it refuses, deletes nothing and lists their ids; a read that fails with anything but 404 also refuses. `--dry-run` runs the same check. Only a clean gateway has its `default` locale-service and then itself deleted
- **NAT/route operations**: Gateway existence is not pre-checked client-side; NSX Manager's API response decides

### Prompt Injection Defense

NSX object names (segments, gateways, rules) returned from the NSX API are sanitized before output via the `_sanitize()` function:

- Strips C0/C1 control characters (U+0000-U+0008, U+000B, U+000C, U+000E-U+001F, U+007F-U+009F)
- Preserves newlines and tabs
- Truncates to 500 characters maximum

This prevents malicious object names from injecting prompts when the data flows to downstream LLM agents.

### Input Validation

- **Segment/gateway/rule/pool IDs**: Must match `^[A-Za-z0-9_-]+$` (no spaces, slashes, or dots), checked before any API call
- **NAT actions**: Validated against the allowed set (SNAT, DNAT, REFLEXIVE, NO_SNAT, NO_DNAT, NAT64); SNAT/DNAT/REFLEXIVE also require a translated address
- **IP pool subnets**: Each subnet must carry `cidr` and `allocation_ranges`
- **Static route next hops**: At least one required, each as `{"ip_address": ...}`
- **CIDR / IP / VLAN syntax and range checks**: Not done client-side — left to NSX Manager's own API validation

### Transport Security

- The MCP server uses **stdio transport** (local only) — no network listener is opened
- NSX Manager connections use HTTPS on port 443 by default
- SSL certificate verification is on by default (`verify_ssl: true` when the key is omitted) and can be turned off per target
- **Production**: keep `verify_ssl: true`. For a private-CA certificate, set the `SSL_CERT_FILE` (PEM bundle) or `SSL_CERT_DIR` environment variable — there is no per-target CA-path setting in config.yaml. Reserve `verify_ssl: false` for isolated labs

### What This Skill Cannot Do

This skill has **no firewall or security operations**. It cannot:
- Create, modify, or delete DFW (Distributed Firewall) rules
- Manage security groups or security policies
- Configure IDS/IPS
- Manage URL filtering rules
- Configure service insertion

For security operations, use `vmware-nsx-security`.

## Multi-Target Setup

You can configure multiple NSX Manager targets and switch between them:

```yaml
targets:
  nsx-prod:
    host: nsx-prod-vip.example.com
    username: svc-automation
    port: 443
    verify_ssl: true             # private CA: export SSL_CERT_FILE=/etc/pki/tls/certs/nsx-ca-bundle.pem
    environment: production

  nsx-staging:
    host: nsx-staging.example.com
    username: svc-automation
    port: 443
    verify_ssl: true
    environment: staging

  nsx-lab:                       # isolated lab only
    host: 10.0.1.100
    username: admin
    port: 443
    verify_ssl: false            # factory self-signed cert
    environment: lab

default_target: nsx-prod
```

```bash
# Uses default_target (nsx-prod)
vmware-nsx inventory list-segments

# Explicitly target staging
vmware-nsx inventory list-segments --target nsx-staging

# Target lab
vmware-nsx health alarms --target nsx-lab
```

## NSX Manager Roles

Recommended role assignments for the service account used by this skill:

| Use Case | NSX Role | Capabilities |
|----------|---------|-------------|
| Read-only monitoring | `network_engineer` (read-only) | List/get all objects, health, troubleshoot |
| Network automation | `network_engineer` | Create/modify segments, T1 gateways, NAT, routes, IP pools |
| Full operations | `enterprise_admin` | All operations including T0 modifications |

**Least privilege**: For monitoring-only deployments, use a read-only role. Write tools will return permission errors, but all read operations work.

## File Locations

| File | Purpose |
|------|---------|
| `~/.vmware-nsx/config.yaml` | Connection targets and settings |
| `~/.vmware-nsx/.env` | Passwords (chmod 600) |
| `~/.vmware/audit.db` | Operation audit trail (SQLite WAL, via vmware-policy) |

## Combining with Other VMware Skills

vmware-nsx can run alongside other VMware MCP skills simultaneously:

```json
{
  "mcpServers": {
    "vmware-nsx": {
      "command": "vmware-nsx",
      "args": ["mcp"],
      "env": { "VMWARE_NSX_CONFIG": "~/.vmware-nsx/config.yaml" }
    },
    "vmware-nsx-security": {
      "command": "vmware-nsx-security",
      "args": ["mcp"],
      "env": { "VMWARE_NSX_SECURITY_CONFIG": "~/.vmware-nsx-security/config.yaml" }
    },
    "vmware-monitor": {
      "command": "vmware-monitor",
      "args": ["mcp"],
      "env": { "VMWARE_MONITOR_CONFIG": "~/.vmware-monitor/config.yaml" }
    }
  }
}
```

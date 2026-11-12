<!-- mcp-name: io.github.vmware-skills/vmware-nsx -->

# VMware-NSX

Inspect and manage VMware NSX networking through focused tools.

English · [简体中文](README-CN.md)

Community-maintained · MIT · Not an official VMware/Broadcom product.

[![18-second illustrative investigation demo](https://raw.githubusercontent.com/vmware-skills/marketplace/main/assets/demos/vmware-skills-en.gif)](https://github.com/vmware-skills/marketplace/blob/main/assets/demos/vmware-skills-en.mp4)

Synthetic-data animation, not a live recording. [Watch the AI-narrated family introduction (~2 min)](https://github.com/vmware-skills/marketplace/blob/main/assets/demos/vmware-skills-en.mp4)

## Why use it?

- Work with segments, gateways, NAT and IP pools.
- Inspect BGP, routes and fabric health.
- Keep configuration actions explicit and auditable.

## Get started

Install the published CLI and inspect its commands:

```sh
uv tool install vmware-nsx-mgmt==1.15.3
vmware-nsx --help
```

Requires uv and Python >=3.10. Configure targets and credentials locally before remote queries. [Setup guide](skills/vmware-nsx/references/setup-guide.md).

For Claude Code and other host installation paths, see the [family portal](https://github.com/vmware-skills/marketplace).

## Know the boundaries

Includes network configuration writes. VMware NSX permissions and local Policy remain in force; destructive gates do not replace independent authorization.

## Go deeper

- [Capabilities](skills/vmware-nsx/references/capabilities.md)
- [CLI reference](skills/vmware-nsx/references/cli-reference.md)
- [Agent guardrails](skills/vmware-nsx/references/agent-guardrails.md)
- [Detailed usage and architecture](skills/vmware-nsx/references/detailed-guide.md)
- [Canonical skill instructions](skills/vmware-nsx/SKILL.md)

Part of [VMware Skills](https://github.com/vmware-skills/marketplace): 15 skills, 14 MCP servers and one shared Policy library. If it helps your work, star the family portal.

[Issues and feedback](https://github.com/vmware-skills/VMware-NSX/issues) · [MIT](https://opensource.org/license/mit/)

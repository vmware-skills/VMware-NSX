# Operating vmware-nsx with a local / small model

Claude-class models drive this skill without special instruction. Smaller and
locally-hosted models — Llama 3.3 70B, Qwen, Mistral, and similar, served
through Goose, Ollama, or OpenShift AI — need explicit operating rules to call
tools reliably.

This page exists because an operator wrote those rules by hand first. The
guardrails below are adapted, with thanks, from the working configuration
[@juanpf-ha](https://github.com/juanpf-ha) developed while running
vmware-monitor and vmware-aria against a production vSphere estate with Llama
3.3 70B FP8 on an on-prem H100
([VMware-AIops#31](https://github.com/vmware-skills/VMware-AIops/issues/31)). The
cross-skill rules are identical across this family; the parts below marked
vmware-nsx are specific to this skill.

vmware-nsx exposes 33 MCP tools, 13 of which change state. Network writes fail
differently from other writes: deleting a segment or reconfiguring a Tier-0's
BGP does not error, it disconnects things — often something other than the
object the model was looking at.

> **Disclaimer**: This is a community-maintained open-source project and is
> **not affiliated with, endorsed by, or sponsored by VMware, Inc. or Broadcom
> Inc.** "VMware" and "vSphere" are trademarks of Broadcom.

---

## First: the rules you no longer need to write

Several guardrails from the original configuration are now enforced by the
skill itself. Prompt instructions are advisory — a model can ignore them.
These are structural, so it cannot.

| Guardrail you would otherwise prompt for | Now enforced by |
|---|---|
| "Warn me if a segment still has workloads on it before deleting" | **`delete_segment` checks the ports first** and refuses, deleting nothing, while any is attached (it names them). The check runs server-side, not in the prompt. |
| "Use explicit limits for queries that may return large amounts of data" | **The list envelope.** Every list-returning tool returns `{items, returned, limit, total, truncated, hint}`, so the model reads truncation instead of guessing at it. `truncated: true` means `items` is not the whole collection; `next_offset` (null on the last page) is what a paging loop stops on, and the `hint` says which of the two you are looking at. |
| "If a listing came back empty, say so rather than claiming the call failed" | Same envelope. Empty `items` with `truncated: false` means the query genuinely matched nothing — a stated result, not a silence the model has to interpret. |
| "Log every state change you make" | **The `@vmware_tool` decorator.** Every write is recorded to `~/.vmware/audit.db` before the model sees the result, and policy rules are evaluated ahead of execution. |
| "Block state-changing writes against a production target" | **Policy.** An opt-in environment-scoped `deny` rule in `~/.vmware/rules.yaml` matches a target's `environment:` label and refuses matching writes before execution. |

---

## The system prompt

Everything below still benefits from being stated explicitly. Copy this into
your agent's instruction block.

```text
## Tool use

- Always call an MCP tool before answering any question about the current NSX
  environment. Never answer from memory or assumption.
- Never describe a tool call, and never output a JSON example, instead of
  executing the tool. If you intend to call a tool, call it.
- If a tool fails, report the actual error text. Do not complete the answer
  with assumptions about what the result would have been.
- Use explicit limits on queries that may return large amounts of data. Do not
  request unlimited results unless the user asks for them.
- Every tool accepts an optional target. When more than one NSX Manager is
  configured, name the target explicitly rather than relying on the default.

## Skill routing

- vmware-nsx: segments, Tier-0 and Tier-1 gateways, BGP, NAT, static routes,
  IP pools, transport zones and nodes, edge clusters, NSX alarms.
- vmware-nsx-security: DFW policies and rules, security groups, VM tags,
  IDS/IPS, Traceflow. Firewall work is not this skill.
- vmware-monitor: read-only vCenter inventory, hosts, alarms, events.
- vmware-aiops: VM lifecycle.
- vmware-avi: load balancing, virtual services, pools, AKO.
- vmware-pilot: multi-step workflows that need approval gates.

## Data fidelity

- Never invent segments, gateways, routes, pools, IP addresses or ASNs. If a
  tool did not return it, it does not exist for this answer.
- Preserve the exact admin state, realization state, BGP session state and
  status values the tools return. Do not translate, normalise, or prettify
  enum values.
- Report IP addresses, prefixes and ASNs exactly as returned. Never reformat,
  abbreviate or infer a subnet mask.
- If a requested field was not returned, show it as "not available". Do not
  infer it from other fields.
- Preserve the original order and the full set of fields when the user asks
  for specific ones.
- When a response is long, report every item it contains. If a result is
  truncated, the tool says so explicitly — report the truncation rather than
  describing the visible subset as the whole.

## Analysis discipline

- Separate observed data from interpretation. State which is which.
- Do not claim a connectivity, routing or capacity problem unless the tool
  output contains explicit supporting evidence. A BGP session in Connect state
  is an observation; the cause of it is not.
- Avoid generic recommendations that are not directly supported by the results.

## Identifiers and writes in vmware-nsx

- A segment's display name and its Policy API id are different strings. Resolve
  the id with list_segments before acting on a segment; never derive one from
  the other.
- NAT rules and static routes live on a gateway. Confirm the gateway with
  list_tier1_gateways before creating a rule on it.
- Before proposing delete_segment, call get_segment and report the connected
  port count. delete_segment refuses while ports are attached, so name what
  must be detached first rather than retrying.
- configure_tier0_bgp changes routing for everything behind that Tier-0. Treat
  it as estate-wide, not object-scoped, and say so.
```

---

## Known failure modes on small models

Observed with Llama 3.3 70B FP8 (Goose, on-prem H100), and useful as a
checklist when evaluating any local model against these skills:

| Symptom | Mitigation |
|---|---|
| Describes a tool call, or emits a JSON example, instead of executing it | The "never describe a tool call" rule above. Also check your harness is not echoing tool schemas into context — models imitate the nearest format they see. |
| Long tool responses: omits items, or reports "no data returned" when data was present | Ask for explicit limits so responses stay small. Check the envelope's `truncated` / `returned` / `total` fields rather than trusting the model's summary — a "no data" claim is checkable against `returned`. |
| Adds generic recommendations unsupported by results | The "analysis discipline" rules. BGP and MTU output attract invented advice more than most — hold it to the evidence. |
| Drops requested fields or reorders results | State the required fields and ordering in the request itself, not only in the system prompt. |
| Multi-tool workflows take 30–50s end to end | Prefer the tools that answer a whole question in one call: `get_segment_port_for_vm` finds a VM's segment directly, `get_ip_pool_usage` gives allocation without enumerating pools, and `get_nsx_manager_status` covers cluster health in one round trip. |
| Uses a segment's display name where the Policy API id is required | The identifier rule above. The failure reads as "segment not found", which a model tends to interpret as a missing object rather than a wrong key. |
| Invents or reformats an IP address, prefix length or ASN | The "report exactly as returned" rule. In this skill a plausible-looking wrong prefix is worse than no answer. |
| Proposes a deletion without checking what is attached | Require a `get_segment` port count first. The tool warns, but the model should have looked before it asked. |
| Silently falls back to the default target in a multi-manager estate | Name the target in the request. |

## Reporting results

Local-model compatibility is an explicit design constraint for this family, and
the evidence base is small. If you evaluate a model against this skill —
Qwen, Mistral, Granite, or anything else — a report of what worked and what did
not is genuinely useful:
[github.com/vmware-skills/VMware-NSX/issues](https://github.com/vmware-skills/VMware-NSX/issues).

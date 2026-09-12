## v1.9.0 — a refused delete is reported as refused

**Tier-1 delete checks first and deletes nothing when it refuses.** It removed the gateway's
default locale-service and then failed on the gateway itself when anything still depended on it,
leaving a gateway with no edge binding. It now refuses up front while segments (global or
Tier-1-scoped), NAT rules, static routes, interfaces, IPsec or L2 VPN services, a DNS forwarder,
load-balancer services or another locale-service remain, and lists them. `--dry-run` runs the same
check.

**What the check needs.** The account that deletes a Tier-1 now also needs *read* access to every
section the check looks at: all segments and all load-balancer services (read in full — the
Policy API cannot filter them by gateway, so on a large NSX this is a walk over every segment),
and the gateway's NAT rules, static routes, locale-services and interfaces, IPsec and L2 VPN
services and DNS forwarder. A 404 counts as "none there"; **any other failed read — a permission
error included — stops the delete before anything is removed** rather than guessing the gateway
is clear, so an account that could delete a Tier-1 before this release may be stopped now. The
error gives the HTTP status of the read that failed, followed by its path.

**Refusals reach the user.** `delete_tier1_gateway` and `delete_segment` discarded the ops layer's
refusal and printed "deleted"; the audit said `ok`. Both surfaces now report the refusal, audit
`error`, and the CLI exits 1. `create_ip_pool` reported success when its subnet failed; that is
now an error that says the pool exists and how to clean up.

Docs: the setup guide's config examples did not load (`targets` as a list), the first example
disabled TLS verification for a production target, routing claimed "any networking task", and
several safety claims (certificate auth, input range checks, a gateway pre-check) described code
that did not exist. All corrected against the code.

**CLI writes are authorised and audited under their MCP tool names.** A deny rule
in `~/.vmware/rules.yaml` names an operation, and the 13 guarded CLI commands were
checked under their Python function names instead — so a rule against
`delete_segment` stopped the agent and let `segment delete` do the same thing from
a shell. One rule now scopes both surfaces:

| CLI command | Operation name (was) |
|---|---|
| `segment create` | `create_segment` (`segment_create`) |
| `segment update` | `update_segment` (`segment_update`) |
| `segment delete` | `delete_segment` (`segment_delete`) |
| `gateway create-tier1` | `create_tier1_gateway` (`gateway_create_tier1`) |
| `gateway update-tier1` | `update_tier1_gateway` (`gateway_update_tier1`) |
| `gateway delete-tier1` | `delete_tier1_gateway` (`gateway_delete_tier1`) |
| `gateway configure-tier0-bgp` | `configure_tier0_bgp` (`gateway_configure_tier0_bgp`) |
| `nat create-rule` | `create_nat_rule` (`nat_create_rule`) |
| `nat delete-rule` | `delete_nat_rule` (`nat_delete_rule`) |
| `route create-static` | `create_static_route` (`route_create_static`) |
| `route delete-static` | `delete_static_route` (`route_delete_static`) |
| `ip-pool create` | `create_ip_pool` (`ip_pool_create`) |
| `ip-pool delete` | `delete_ip_pool` (`ip_pool_delete`) |

Risk levels were already equal to the MCP tools' and are unchanged. **Audit rows
for these commands carry the new names from this release on**; rows written
before it keep the old ones, so a query over `~/.vmware/audit.db` that spans the
upgrade needs both. A rule you wrote against an old name no longer matches —
rename it to the MCP tool name. A regression test now derives each command's MCP
twin from the ops function both call and fails if the names or risks drift.

**Environment-scoped deny rules now apply to CLI writes.** The skill's environment resolver was
registered only when the MCP server was imported, which the CLI never does — so a
`freeze-production-writes` rule stopped the MCP tool and not the CLI command doing the same
thing. It now lives in `policy_environment.py`, imported by both surfaces. (With vmware-policy
1.13.1 the CLI's `--config` file is the one whose labels are judged.)

**OpenClaw could not show this skill to the model.** `metadata.openclaw.requires` listed
config *file paths* under `requires.config`, which OpenClaw reads as `openclaw.json` keys that
must be truthy — so the skill was "needs setup / not visible to the model" whatever was on disk
(verified on OpenClaw 2026.6.35). `requires.env` named an optional override and `requires.bins`
demanded a CLI that a plugin install (uvx) never has. `requires` is now `anyBins: [<cli>, "uvx"]`;
the variables are still declared, under `optional.env`.

**Install commands in the skill pin this release.** ClawHub reviews SKILL.md and references/,
not the package they install, so an unpinned `uv tool install` vouched for code nobody reviewed.
Every install command for this package in the skill now names this version.

**A config path written as `~/…` now resolves.** Every MCP example config and setup-guide snippet
sets `VMWARE_NSX_CONFIG` to `~/.vmware-nsx/config.yaml`, but MCP clients pass env values verbatim and the
path was used unexpanded, so copying the snippet gave "Config file not found" for a file that was
there. `~` is now expanded in the variable and in `--config`.

## v1.8.16 — one answer per .env, on every platform

`.env` permissions are decided by `vmware_policy.fsperms` instead of POSIX mode
bits. On Windows a single command printed both a red "has permissions 0o666
(should be 600). Run: chmod 600" from this hot path — where `chmod` does nothing
— and a green "this platform does not express file permissions as POSIX mode
bits ... run: icacls" from `doctor`, about the same file in the same run. `doctor`
had been moved to the three-state check and the path that runs on *every* command
had not. An unmeasurable platform is now silent here rather than loudly wrong.

## v1.8.15 — the test suite runs on a non-UTF-8 machine, and the guardrail tests with it


**The suite now runs on a cp936 machine.** Round 3 of the VCF 9 field testing ran
on Windows Server 2025 with locale cp936. Across the family four repos' suites --
1687 tests -- never executed at all, dying at collection reading our own UTF-8
sources, and 101 more failed the same way. Most of those were the tests that
verify the destructive-operation guardrails: the guardrails were fine, the tests
that check them could not open a file. On the UTF-8 CI every one of them was
green. A security test that cannot run is not a security test.

Every text read and write here names its encoding now, `tests/` included -- the
previous round fixed only the package, which is why this came back. A gate in
`family_smoke` scans both trees by AST, and the whole family's suites were re-run
under an ASCII locale to confirm: 15 of 15 green, from 1 of 15.

**`--help` no longer dies on a console that cannot encode it.** On any console
whose encoding cannot carry the characters in our own help text, `--help` exited
with a `UnicodeEncodeError` traceback -- unavailable exactly on the machines
where it is most needed. Four repos were affected; the handler is now relaxed in
all fifteen so a glyph degrades instead of killing the command.

**Its environment resolver no longer answers for other skills.**
`set_environment_resolver` wrote one process-global slot and twelve servers
registered into it at import time, so the last one won for all of them --
measured taking a `freeze-production-writes` rule from DENY to ALLOW on another
skill's production target. Registration is keyed by skill now (requires
vmware-policy 1.12.0).

**The `.env` permission check stopped being permanently red on Windows.** It was
POSIX-only, and `chmod 600` there exits 0 without changing any bits -- so
`doctor` printed a failure on every run with a remedy that could not clear it.
Three states now, via `vmware_policy.fsperms`: only a demonstrated exposure
fails, and "this platform cannot answer" says so and offers `icacls`.

**Unknown tool arguments are refused instead of dropped.** The schema declared
`additionalProperties: false` and the runtime accepted them anyway, so a filter
argument whose name a model guessed wrong returned the *unfiltered* result with
nothing to indicate anything had been discarded. Fixed in vmware-policy 1.12.0
and in force here.

Requires vmware-policy 1.12.0.

## v1.8.14 — gateway_type and NAT action now reach the MCP schema

`create_nat_rule(action=...)` and `gateway_type` on the three static-route tools
were typed `str`. The gateway case had teeth: the implementation chooses with
`"tier-0s" if gateway_type == "tier0" else "tier-1s"`, so anything not spelled
exactly `tier0` silently addressed **tier1** — including on
`delete_static_route`. Both are now `Literal[...]`, so the client rejects a bad
value before it reaches that branch.

`create_nat_rule`'s docstring named three actions while the implementation
accepts six (`SNAT`, `DNAT`, `REFLEXIVE`, `NO_SNAT`, `NO_DNAT`, `NAT64`). An
enum copied from the prose would have turned that documentation gap into a hard
rejection of three working values, so the set is taken from the code and the
docstring is corrected. The set is hoisted to `VALID_NAT_ACTIONS` and a new
regression test pins the schema's enum against it.

## v1.8.13 — an agent's network changes left no trace a human could find

The MCP write tools recorded nothing in `~/.vmware-nsx/audit.log` — the
per-skill trail the README advertises as holding "All operations", the one that
carries before/after state, and the one an operator actually opens. The shared
`audit.db` was always written; this is the other sink. So a segment deleted by
an agent was absent from the file a human's identical CLI command had just
appeared in. The wrapper is derived from each tool's own `readOnlyHint`, so a
new write tool is covered by being written.

The paging hint also told a reader on the last page to raise a limit that cannot
return another row. `truncated` keeps its meaning — it answers whether `items`
is the whole collection, which is still true mid-walk — and `next_offset`
remains the stop signal.

**The `vmware-policy` floor moves to >=1.11.0.** Policy 1.11.0 stops the engine
failing open: on a host whose locale is not UTF-8, reading `rules.yaml` raised a
decode error that was swallowed, and a `freeze-production-writes` rule came back
ALLOW. No new API is used here, so the floor could have stayed — it is raised
because leaving it low means a user resolving 1.10.0 keeps the permissive engine
and the fix never reaches them. One behaviour travels with it: on a host whose
rules file cannot be read, operations move from all-allowed to all-denied.
`VMWARE_POLICY_DISABLED=1` is checked above the rules, so the escape hatch does
not itself depend on them loading.

Also in this release: the suite no longer appends to the operator's real
`~/.vmware/audit.db`. It held over 30,000 rows dominated by tool names nobody
had invoked, including 1,400 entries for a destructive operation that never
happened — an audit trail carrying test fiction cannot answer the question it is
kept for.

## v1.8.12 — the schema an agent reads now carries the descriptions

Parameter descriptions reach the JSON schema for the first time. An MCP client
sees the schema, not the docstring, and this repo's coverage of `description`
and `additionalProperties` was 0% — while nearly every parameter was already
described in an `Args:` block no client ever receives.

Measured on a real VCF 9.1 estate, the gap produced a silent failure with no
error at any stage: a parameter name guessed wrong is discarded and the tool
returns the full unfiltered result; a value guessed wrong (`power_state=
"running"`) returns 0 rows where there were 11.

vmware-policy 1.10.0's `describe_tool_parameters` copies what is already
written, so the docstring is now load-bearing and the two cannot drift apart. It
removes the `Args:` block from the description once copied — both travel in
every `tools/list` response, so leaving it bills the same sentences twice
against the manifest's token budget. `additionalProperties` is closed: an open
schema is room for a model to invent arguments that are then silently
discarded, which is the other half of the same failure.

**The `vmware-policy` floor moves to >=1.10.0.** Older releases have no
`describe_tool_parameters`, and resolving one gives an ImportError at server
start rather than a missing feature.


## v1.8.11 — the list tools can be asked for a page, and for the next one

Found against a real VCF 9.1 estate.

**Ten list tools exposed only `target` on the MCP surface**, with `limit=50`
hardcoded in the ops layer. An agent could not ask for more, or for what came
after. All ten now take `limit` and `offset` on the tool, the op and the CLI,
and return `next_offset` — the value to pass back, or `null` when the collection
ends. `truncated` is deliberately *not* the stop signal: it answers "is this the
whole collection?", which is still true on the last page of a walk, and flipping
it there would buy a terminating loop at the price of the failure the envelope
exists to prevent.

`limit=0`, negatives and anything above the maximum are now rejected with a
message naming the range, rather than clamped or silently read as "unlimited" —
the family had four contradictory meanings for `limit=0`, and negatives reached
Python's negative slicing and quietly dropped rows off the end.

The NSX cursor is deliberately not exposed, though it would be O(1) per page
instead of O(pages): nothing in this repo demonstrates that a cursor survives
between calls, and this family has been burned before by an API layer written
from recollection.

**`verify_ssl: false` needed a package this skill never declared.** On a clean
install, authenticating against a self-signed target — the VCF default — died
with `No module named 'urllib3'`. The import sat behind that branch, so it never
ran in this repo's tests. The code it guarded was already inert: this client is
httpx, which does not use urllib3 and does not raise `InsecureRequestWarning`.
Removed rather than declared.

**`doctor` reported on a different config file from the one the tools load**,
and the Dockerfile could not build the wheel it installs. `server.json` did not
merely start the wrong thing — `uvx vmware-nsx-mgmt` is refused by uv outright,
because the distribution and the console script have different names.

## v1.8.10 — two wrong numbers: the server's own version, and the advertised tool count

Both defects were invisible to the test suites and both were user-facing.

- **The MCP server reported the SDK's version as its own.** `FastMCP` accepts no
  `version` argument and leaves the lowlevel server's at `None`; with it `None`
  the SDK answers `initialize` with its OWN version. Every skill in the family
  therefore told its client it was mcp 1.29.1 — a number that exists for no
  package here, and one that would change with an SDK bump and no code change of
  ours. Verified end to end rather than by reading: unset the field and a probe
  server reports the installed SDK's version; set it and it reports ours.
- **server.json advertised a stale tool count.** That number is what MCP Registry
  publishes and what the plugin manifest and marketplace copy, so one stale
  integer was wrong in three public places. Corrected against the registered
  tools: 31 advertised, 33 real. README and SKILL.md were already right.

Also new: this repo is installable as a Claude Code plugin
(`/plugin install vmware-nsx@vmware-skills`). The skill and its MCP server arrive in
one step; nothing is duplicated, the manifest points at the existing `skills/`
tree. family_smoke gained three gates — the server's reported version, the plugin
manifest's agreement with pyproject, and the advertised tool count against the
live registration.

## v1.8.9 — moved to vmware-skills org + MCP Registry namespace io.github.vmware-skills/vmware-nsx

Repo transferred from github.com/zw008 to github.com/vmware-skills (redirects preserve old links).
MCP Registry server renamed to `io.github.vmware-skills/*`; the old `io.github.zw008/*` entry is deprecated.
All in-repo links updated. No functional code change on this line beyond the org move.

## v1.8.8 — CLI writes now route through policy + audit, exactly like the MCP tools

Every state-changing CLI command is now wrapped by `@guarded`, the CLI counterpart
to the MCP `@vmware_tool` decorator: it runs the same vmware-policy `guard()`
authorization and writes the same `audit_call()` row to `~/.vmware/audit.db`. A
`delete`/`disable`/destructive command run through a shell is now authorized and
recorded exactly like the equivalent MCP tool — closing the gap where CLI writes
bypassed policy and landed only in the legacy per-skill log (HLD I-1/I-8).

- a policy `deny` rule now refuses the operation on the CLI with a teaching line
  naming the rule that fired, not a traceback
- the legacy per-skill audit log is still written this release (dual-write); it is
  removed at 2.0
- **requires vmware-policy >= 1.8.8** (the release that adds the shared `guarded` core)
- a regression test derives the write-command set from the MCP `[WRITE]` markers and
  asserts every one is `@guarded`, so a new write command cannot ship unguarded

Also carries the environment-field docstring correction (an optional label a `deny`
rule may scope to — there is no "warn now / refuse next major" gate).

## v1.8.7 (2026-07-21) — the skill-level read-only switch is removed; read/write authorization is the vCenter account's job (RBAC)

### Removed: `VMWARE_READ_ONLY` / `read_only:` — give the agent a read-only service account instead

The skill-level read-only switch is gone. It was enforced only on the MCP tool
registry, and any agent with a shell (every SKILL.md grants `allowed-tools: Bash`)
could reach the same change one CLI command away — so it withheld the *tool*, not
the *capability*. It was never a real boundary.

To run an agent read-only, give it a **read-only vCenter/NSX service account
(RBAC)**. Writes are then refused at the platform, un-bypassably, regardless of
surface or shell — the one place read/write control cannot be stepped around. A
config still carrying `read_only: true` is ignored, with a one-time warning that
names the replacement (no silent behavior change).

### Removed: approval tiers and the declared-environment gate (via vmware-policy)

The graduated-autonomy approval tiers (`confirm`/`dual`/`review`) and the "declare
an environment or be refused" baseline are removed — they only ever fired on the
rarest configuration while carrying the family's most complex machinery. Opt-in
`deny` rules and the maintenance window remain, and apply identically wherever a
tool runs.

### Added: offline / air-gapped install docs

The README now covers installing from source without editable mode (for older
`pip`) and building wheels to carry onto an air-gapped host — the modern PEP 517
layout has no `setup.py` by design, which is expected, not a missing file.

This release also carries the accumulated fixes staged since 1.8.5.

## v1.8.5 (2026-07-20) — the two fixes v1.8.4 announced now actually work

Four adversarial reviews of v1.8.4 found that both of its headline fixes were
incomplete in ways the release notes did not reflect. This release makes them
real. If you are on 1.8.4, this is the one to take.

### Fixed — a failure that was *returned* was still audited as a success

vmware-policy 1.8.4 added `report_tool_failure()` for tools that catch an
exception and return an error payload instead of raising. **No skill called it.**

Every string-returning tool therefore kept doing exactly what 1.8.4 said it had
stopped doing: writing `status=ok` to `~/.vmware/audit.db` for an operation that
failed, recording an undo token for a change that never happened, and telling the
circuit breaker the call succeeded so repeated failures never tripped it.

The surface this covered is not marginal:

| Skill | What was mis-audited |
|---|---|
| vmware-aiops | 25 of 49 tools, including **every undo-bearing write** — a failed `vm_power_on` left an undo token saying "power it back off" |
| vmware-avi | all 28 tools, including `vs_toggle` and `ako_restart` |
| vmware-storage | all 4 write tools |
| vmware-nsx | the 5 delete tools |

vmware-avi is worth calling out: before 1.8.4 its exceptions propagated and the
audit was correct. 1.8.4 caught them and returned a string, so **that release made
its audit trail worse than it had been.**

Skills whose tools already return dict payloads (vmware-monitor, vmware-vks,
vmware-aria, vmware-log-insight, vmware-harden, vmware-debug, vmware-pilot) were
already detected correctly. They gained a test proving it rather than a redundant
call.

### Fixed — narrowing `OSError` did not close the leak it was meant to close

1.8.4 narrowed the `_safe_error` passthrough because bare `OSError` let TLS and
DNS failures reach the agent with hostnames and certificate subjects in them.
That narrowing had no effect on the error it was written for:

```
ssl.SSLCertVerificationError → ssl.SSLError → OSError, ValueError
```

`ValueError` has been on every allowlist since long before 1.8.4, so a
certificate failure kept passing through — the commonest self-signed-certificate
failure in this family, carrying the hostname it was checked against. An
allowlist structurally cannot express "not this one".

Where `ssl.SSLError` can actually surface — the pyVmomi skills — it is now
reduced *ahead* of the allowlist. In the httpx skills TLS arrives wrapped as
`httpx.ConnectError`, and in vmware-avi as `requests.exceptions.SSLError`, so the
guard cannot fire there; in those skills the leak was the raw exception
interpolated into an already-allowlisted `*ApiError`, and that is now authored
text naming the config target and `verify_ssl` instead of the exception.

The missing-password error — this family's most common first-run failure, whose
entire remedy is the environment variable name it carries — keeps its message
through a narrow `ConfigError(OSError)` rather than the base class. Connection
failures are translated at the connection layer into an authored remedy that
names the target and the setting to change, with the raw detail left on
`__cause__` for the server log.

### Also fixed

- **vmware-vks**: the quickstart documented a password variable the code never
  reads — following `README.md` verbatim produced "Password not found". Five
  places, plus six references to a `doctor` command this CLI has never had, two
  descriptions promising fields the tools do not return, and eight teaching
  messages that `RuntimeError` was masking.
- **vmware-nsx**: an error cited `--route-advertisement`; the flag is `--advertise`.
- **vmware-pilot**: `get_workflow_status` told the model to call `approve` — a
  tool the read-only gate withholds — as the required next step; and a hint
  pointed at a filename that could never appear in that message.
- **vmware-aiops**: `vm_task_status` polling a *failed task* returned
  `{"state": "error", "error": ...}` from a successful read, which the new
  detection read as the call itself failing. The field is now `task_error`.
  **This is a breaking change for anything parsing that payload.**
- Several remedies that were still being cut by the 300-character cap the 1.8.4
  notes claimed to have addressed.

### Known and not fixed

`ConnectionError` remains one type from two sources in several skills — a
skill's own authored message and urllib3's `HTTPSConnectionPool(host=..., port=...)`
share it, and an allowlist cannot separate them. vmware-vks is converted; the
rest need their own domain type and are deferred rather than half-done.

## v1.8.4 (2026-07-20) — errors that teach, and tool descriptions a small model can route from

A capability eval was rolled out across the family and asked two open questions:
when a call fails, is the model told enough to fix it, and can it pick the right
tool from the description alone? Both answers were worse than anyone thought, and
in several places the reason was that the measurement was looking somewhere other
than where the model reads.

### Fixed — teaching messages were being discarded on the way to the agent

`_safe_error` reduces unrecognised exceptions to `"<Class>: operation failed."`
so raw API text, credentials in URLs and internal paths cannot reach an agent.
Its allowlist held only the builtin validation errors — so this skill's **own**
domain exceptions, the ones that exist precisely to carry a corrected next step,
had their messages replaced by their class names.

The effect was invisible from the CLI, which prints those messages in full.

The worst case was shared by nine skills: `config.py` raises exactly one
`OSError`, the missing-password error, whose entire remedy is the environment
variable name it names. An agent hitting an unconfigured target received
`OSError: operation failed.` and had nothing to act on. That is the family's most
common first-run failure, and it landed one release after the documented variable
names were corrected — so the message that would have unstuck the operator was
the one being thrown away.

The rule is now the property it always meant: **every exception this skill raises
on purpose passes through**, and only genuinely unplanned ones are reduced.
`RuntimeError` stays reduced — it is the generic catch-all and in several skills
carries raw upstream text.

### Fixed — error messages now carry the correction

Every message that reported a failure without saying how to recover was
rewritten: it names the offending value, gives an imperative remedy, and names
something concrete to act on — a tool that exists, a real CLI command, a config
file, an environment variable. Recovery becomes an instruction-following problem
rather than an inference one, which is what a weak model can still do.

Three classes of defect surfaced while doing it:

- **Remedies that were never delivered.** `_safe_error` truncates with no
  ellipsis, so a message longer than the cap loses its closing sentence
  silently. One message had been shipping at 396 characters against a 300-char
  cap — its remedy had never once reached an agent. Messages now lead with the
  remedy so a long interpolated value truncates the expendable detail instead.
- **Commands that do not exist.** One skill's error hints named a `doctor`
  subcommand it does not have.
- **Tools that do not exist.** A tool description pointed at two sibling-skill
  tools that had been renamed, and another named a tool that had moved to a
  different skill entirely.

### Improved — tool descriptions state when to use them and what to call next

The description is the API for a small model: an unstated routing rule is a
routing rule that does not exist, and a tool with no stated next hop is one the
model stops at. Descriptions now say when to prefer this tool over a sibling,
what shape comes back, the caveat that bites, and which tool to call after.

**Manifest size did not grow.** Descriptions load into every session, so the
routing clauses were paid for by cutting duplicated reference material —
repeated boilerplate, examples that restated the parameter list, and prose
copies of the pagination contract.

### Note

Every tool and CLI command named anywhere in this release was verified against
the live MCP registry and the live command tree, not against documentation.

## v1.8.3 (2026-07-20) — credentials resolve as a pair; documented env vars now exist

### Added — the per-target username can come from the environment

Adapted from [VMware-AIops#33](https://github.com/vmware-skills/VMware-AIops/pull/33) by
@wright-bench, with thanks. The password already resolved from an env var; the
username did not, so a deployment injecting credentials from a secret store
(systemd `EnvironmentFile`, container secrets, a vault sidecar) could externalise
only half of the pair — and a config-file username paired with an env password
from a different account logs in as nobody.

`<PASSWORD-KEY-PREFIX>_USERNAME` now overrides the `username:` in config.yaml,
using that skill's own password-key convention. Absent, config.yaml still wins;
nothing changes for anyone not setting it.

**Resolved on every access, like the password.** The contributed version read the
username once at load time while the password stayed a property, which
reintroduces exactly the split the override exists to prevent: a sidecar rotating
both halves mid-process moves the password and leaves the username behind. A test
pins that both halves resolve at the same moment.

### Fixed — documented credential variables that the code never read

Rolling the above across the family surfaced a separate defect: four skills
documented a password variable their own loader does not look up. An operator
following the documentation exactly — correct file, correct place, correct-looking
name — got "Password not found".

| Skill | Documented | Actually read |
|---|---|---|
| vmware-nsx | `VMWARE_NSX_<TARGET>_PASSWORD` for target `nsx-prod` → `VMWARE_NSX_PROD_PASSWORD` | `VMWARE_NSX_NSX_PROD_PASSWORD` |
| vmware-nsx-security | `VMWARE_<TARGET>_PASSWORD` | `VMWARE_NSX_SECURITY_<TARGET>_PASSWORD` |
| vmware-aria | `VMWARE_<TARGET>_PASSWORD` | `VMWARE_ARIA_<TARGET>_PASSWORD` |
| vmware-vks | `VMWARE_<TARGET>_PASSWORD` | `VMWARE_VKS_<TARGET>_PASSWORD` |
| vmware-avi | three different forms across three files | `<CONTROLLER>_PASSWORD` |

The prefixes genuinely differ per skill, so nothing could be fixed by
standardising a pattern — each repo's docs were corrected against its own code.
The code was left alone: changing a key would break every existing deployment.

`family_smoke.sh` now compares the credential variables named in each repo's docs
against the ones that repo's code builds, so the two cannot drift apart again.

## v1.8.2 (2026-07-20) — the MCP server moves into the package namespace

### Fixed — co-installing two skills broke all but the last one

Every skill shipped its MCP server as a **top-level `mcp_server` package**. Python
has one top-level namespace, so installing any two of them into one environment let
the second overwrite the first — silently, with no error and no warning.

    uv tool install vmware-aiops   ->  49 tools   (correct)
    uv pip  install vmware-aiops   ->  27 tools   (Monitor's read-only server)

vmware-aiops depends on vmware-monitor, so this was not an edge case: **every pip
install hit it**, and the operator got 27 read-only tools where 49 were expected,
with all 35 write tools missing. Docker images, shared MCP hosts and CI runners that
install more than one skill were affected the same way.

The server now lives at `vmware_<skill>/mcp_server/`, a name only this package can
claim. Introduced 2026-02-26; it survived 70 releases because every test ran against
a single package in its own repo, where the local directory shadows site-packages —
the conflict was invisible by construction.

**Migration.** Console scripts are unchanged: `vmware-<skill>` and
`vmware-<skill>-mcp` work exactly as before, as does `"command": "vmware-<skill>",
"args": ["mcp"]` in an MCP client config. Only a direct `python -m mcp_server`
breaks; use `python -m vmware_<skill>.mcp_server`.

### Added — `references/agent-guardrails.md` in every skill

The operating rules for local and small models (Llama 3.3 70B, Qwen, Mistral via
Goose / Ollama / OpenShift AI) existed in two skills. They now ship in all 13, each
with its own tool counts and failure modes, and are linked from every SKILL.md.

## v1.8.1 (2026-07-19) — read-only mode reaches the surfaces that teach it

v1.8.0 put read-only mode in the code and documented it in the README only.
Every other layer was empty, and each serves a different reader: SKILL.md is what
the agent loads, setup-guide is what an operator reads while configuring, `doctor`
is where they verify it took. The gap had two concrete costs.

An agent read SKILL.md, called a write tool the gate had withheld, and got nothing
back — with no way to learn that the absence was a deliberate lockdown rather than
a fault. It reads as a broken tool, so the model retries or hunts for a workaround.

An operator who set the switch had no way to confirm it. The only signal was a line
in the MCP server's start-up log.

### Added — the feature is now documented where each reader looks

- **SKILL.md** — a short section telling the agent that a missing write tool is a
  lockdown, not a fault: name the blocked operation, do not retry, do not route
  around it.
- **references/setup-guide.md** — the operator's view: how to enable it, the
  precedence chain, and how to verify.
- **references/capabilities.md** — which tools the gate withholds.

### Added — `doctor` reports the read-only state

`vmware-nsx doctor` now shows whether read-only mode is on, **which** of the three
switches decided it, and the value as written. A typo'd value (`ture`) is called
out as a typo rather than reported as a confident ON — it resolves to on, which is
fail-closed but almost never what was meant.

The resolution runs through `vmware_policy.read_only_status()` rather than a local
copy of the precedence chain: a doctor that disagrees with the gate it reports on is
worse than no doctor. Requires `vmware-policy>=1.8.1`.

## v1.8.0 (2026-07-18) — read-only mode, working policy defaults, declared environments

Family release driven by [VMware-AIops#31](https://github.com/vmware-skills/VMware-AIops/issues/31),
where an operator running Llama 3.3 70B (Goose / OpenShift AI, on-prem H100) had to
hand-write 17 prompt guardrails to make tool calling reliable. A prompt is advisory — a
model can ignore it. Every guardrail that could move into the harness has.

### Added
- **Read-only mode.** Set `VMWARE_READ_ONLY=true` (or `VMWARE_<SKILL>_READ_ONLY`, or
  `read_only: true` in config.yaml) and every write tool is removed from the MCP registry
  at start-up. `list_tools()` never offers them, so the model cannot call what it cannot
  see. **Off by default** — nothing changes unless you turn it on. Fail-closed: if the
  mode is requested but cannot be guaranteed, the server refuses to start rather than
  running open.
- **`environment:` on each config target**, declaring which environment it is
  (production / staging / lab). Policy rules scope by this value.

### Added — list results now state whether they are complete

Every `[READ]` list tool returns the family envelope instead of a bare array:

    {"items": [...], "returned": 50, "limit": 50, "total": 213,
     "truncated": true, "hint": "Showing 50 of 213. Raise limit or narrow the query..."}

This closes the reported failure where long responses were summarised as "no data
returned": a bare list gives a model no way to tell a complete answer from page one, so
it guessed. `truncated: false` now positively states completeness — including when
`items` is empty, which means "checked, found none", not "the call failed".

- **10 tool(s) converted** across ops, MCP and CLI. All ten carry a real `total`, read from the ListResult `result_count` the client
  already fetched — no extra round trip. `list_nsx_alarms` reads complete except when
  the 1000-item client backstop cut the walk short, which is exactly when an agent must
  not treat it as the whole alarm picture.

### Changed — migration, read this
- **Approval tiers now actually run.** They shipped in v1.6.0 but the engine only ever
  read `~/.vmware/rules.yaml`, and a fresh install has no such file — so every deny rule,
  maintenance window and approval tier had been inert on every install that never
  hand-authored one. A packaged baseline now loads when you have written no rules of your
  own. Writes at medium risk and above are stamped with their tier in the audit log;
  irreversible work and guest execution against a target declared `production` require a
  named approver via `VMWARE_AUDIT_APPROVED_BY`.
- **`environment:` will become required for writes.** Today a state-changing operation
  against a target that declares none still runs and logs a warning. **The next major
  release refuses it.** Declare it now and that upgrade is a no-op:

      targets:
        prod-vc01:
          host: vc01.corp.local
          environment: production

  Read-only operations are never affected, in this release or the next. Check what applies
  to your targets before upgrading: `vmware-audit policy --operation vm_delete --env <env>`.

### Fixed
- **Policy glob patterns with a leading wildcard silently matched nothing.** A rule written
  `operations: ["*_delete"]` parsed fine, read correctly, and never fired — only a trailing
  `*` was honoured. Now full glob matching, for operations and environments alike.
- Config-path overrides (`VMWARE_<SKILL>_CONFIG`) are honoured when reading `read_only`
  and `environment`, so a setting in a custom config file is no longer silently ignored.

### Notes
- Requires `vmware-policy>=1.8.0`; publish that package first.
- `vmware-audit policy` reports which rules are in force and where they came from —
  including the case where your rules file exists but failed to parse, which previously
  looked identical to "policy is working".

## v1.7.5 (2026-07-13) — internal dead-code cleanup + family version alignment

### Internal
- Removed unused `import os` (doctor) and an unused assignment in the segment
  CLI. No behavior change; MCP tool surface unchanged (33).

## v1.7.4 (2026-07-13) — family version alignment

## v1.7.3 (2026-07-03) — family version alignment

## v1.7.2 (2026-07-02) — list pagination + port-status N+1

### Changed
- **List operations now default to at most 50 items** (previously drained up to
  1000 into agent context) and report the true total via a lightweight count
  probe. `get_all` gained optional `page_size` / `limit`; MCP/CLI signatures are
  unchanged (callers pick up the 50-item default).

### Fixed
- **Port-status & segment-scan round-trip storms.** `get_logical_port_status`
  issued a per-port `/state` GET (up to 51 round-trips per call); the segment-port
  fallback scanned every segment in the estate. Port status is now bounded to
  ≤50 ports, and the fallback is capped at 200 segments with a truncation warning
  (the Policy Search API path is preferred and unchanged).

## v1.7.1 (2026-07-02) — family version alignment

No code changes. Version bump to stay aligned with the v1.7.1 family release
(VMware-AIops + VMware-Monitor large-inventory scale fix — PropertyCollector
batching to stop per-object lazy SOAP round-trips, GitHub issue #31).

## v1.7.0 (2026-06-27) — guided onboarding + teaching auth errors

### Added
- **`vmware-nsx init` — interactive first-run setup wizard.** Prompts for host /
  username / password and writes `config.yaml` + `.env` for you. The password is
  stored grep-safe (`b64:`, never plaintext on disk) and `.env` is locked to
  0600, then the connection is verified. Replaces the manual "mkdir + cp
  config.example.yaml + edit YAML + chmod 600" dance.
- `.env.example` added documenting the per-target password var.

### Changed
- `doctor` now points to `vmware-nsx init` when config/credentials are missing
  (previously suggested a command that did not exist), keeping the manual steps
  as a fallback.
- Authentication and TLS failures now print a teaching message naming the exact
  file and env var to fix (`~/.vmware-nsx/.env` password var, `config.yaml`
  username) plus a `verify_ssl: false` hint for self-signed labs.
- Auth teaching reaffirms special-character passwords are sent via form-body.

## v1.6.1 (2026-06-24)

### Added
- **`.env` passwords are auto-obfuscated to a grep-safe `b64:` form** on first
  load and decoded transparently at runtime — plaintext no longer sits in
  `~/.<skill>/.env` for a casual `grep` to find. Values are read/written through
  python-dotenv's own parser, so the stored secret never drifts from the
  configured one (handles quotes, inline comments, trailing whitespace, and a
  password that literally starts with `b64:`). **Obfuscation, not encryption** —
  for real at-rest secrecy, inject the password from a secret manager instead of
  storing `.env`. New regression suite (10 cases) covers dotenv parity, the
  `b64:`-prefixed edge case, idempotency, and 0600 preservation.

## v1.6.0 (2026-06-22) — trust architecture: undo tokens

### Added
- **Undo-token recording** on create tools (vmware-policy 1.6.0): `create_segment`→`delete_segment`,
  `create_tier1_gateway`→`delete_tier1_gateway`, `create_nat_rule`→`delete_nat_rule`,
  `create_static_route`→`delete_static_route`, `create_ip_pool`→`delete_ip_pool`.
- Inherits harness budget guard, audit accountability fields, and graduated risk tiers.

### Changed
- Requires **vmware-policy >= 1.6.0**.

## v1.5.39 (2026-06-22) — family version alignment

No code changes. Version bump to stay aligned with the v1.5.39 family release
(AIops snapshot-delete async + honest-timeout token-burn fix; Storage datastore-browse timeout fix).

## v1.5.38 (2026-06-12) — backlog finish: cli/server split

### Changed
- Split the oversized `cli.py` (1334 lines) and `mcp_server/server.py` into `cli/*` and
  `mcp_server/tools/*` packages, all under the 800-line cap. Behavior-preserving — 33 tools and 38 CLI
  commands byte-for-byte identical; lazy-import `--help` speed (踩坑 #27) preserved. (#12)

## v1.5.37 (2026-06-12) — backlog: IP-pool lifecycle, tier-0 routes, faster VM lookup

### Fixed
- `create_ip_pool` reports partial state on a mid-loop subnet failure instead of leaving a silent
  half-built pool. (#8)
- VM→segment-port lookup uses the Policy search API instead of an O(segments×ports) full scan. (#11)

### Added
- `delete_ip_pool` (ops + CLI with `--dry-run`/confirm + audited MCP tool) — pools were uncreatable-then-
  unremovable despite the docstring. (#9)
- MCP static-route tools take a `gateway_type` param so Tier-0 routes work (ops already supported it). (#10)

Tool count 32 → 33 (20 read / 13 write).

## v1.5.36 (2026-06-12) — centralized HTTP error translation + SKILL.md accuracy

### Fixed
- **404/5xx no longer reach users as tracebacks (CLI) or opaque "operation failed" (MCP)** — a new
  `NsxApiError` + central `_request()` translates status codes to teaching hints, retries transient
  5xx once on GETs only, and re-auths once on 401 (a real 403 surfaces as a permission error, and
  writes are never blindly re-sent). Four delete tools no longer leak raw exception text.
- **VLAN range parsing fixed** — `segment create --vlan 100-200` created two discrete VLANs instead
  of the range; `dhcp_ranges` on a subnet are no longer silently dropped.
- **`is_alive` liveness probe uses a cheap any-role Policy-API GET** (`/policy/api/v1/infra`) instead
  of the privileged Manager-API path, so least-privilege accounts don't trigger reconnect churn.

### Changed
- SKILL.md / cli-reference regenerated from the live tool registry: **32 tools (20 read / 12 write)**,
  ~11 nonexistent tool names removed, and the false "all writes support dry-run" claim corrected
  (dry-run is CLI-only).

## v1.5.35 (2026-06-10) — security hardening: safe errors; doc accuracy

### Fixed
- **MCP tools route errors through `_safe_error()`** — full detail to the server log, a
  generic/sanitized message to the agent (no NSX response bodies / host:port leakage).
- **Silent `except: pass`** in troubleshoot now logs at debug.
- **Docs corrected**: removed the documented-but-unimplemented certificate-authentication
  section; authentication is username/password via the session-create API (form-body encoded).

This release aligns the whole family back to a single version (1.5.35); vmware-policy and vmware-pilot return to the shared number after sitting at 1.5.22.

## v1.5.32 (2026-06-08) — Response parsing fixed against official NSX 4.2 SDK + 2 CLI repairs

A family-wide spec audit found the status/troubleshooting read paths parsed
fields that don't exist on the official response models (silently returning
empty values), and two CLI commands that never worked.

### Fixed — response parsing (verified against nsx-policy/nsx SDK 4.2 models)
- Transport node status: `tunnel_status`/`pnic_status` StatusCount parsing;
  invented `node_deployment_state`/`pnic_bond_status`/`lcp_connectivity_status`
  removed; `mgmt_connection_status` is a plain string.
- Edge cluster member status via `transport_node.target_id`/`target_display_name`.
- Manager cluster: `mgmt_cluster_listen_ip_address` is a plain string.
- BGP: config fields `hold_down_time`/`keep_alive_time`; prefix counters now
  labeled `in_prefix_count`/`out_prefix_count` (were mislabeled as messages).
- Port status: SegmentPortState has no UP/DOWN field — output now reports
  attachment, realized-bindings count, and transport node IDs honestly.
- VM-to-segment lookup via `GET /api/v1/fabric/vifs?owner_vm_id=` matching
  `lport_attachment_id` (the previously read `virtual_interfaces` field
  doesn't exist — the tool always returned empty matches).
- Inventory: transport zone `host_switch_name` removed (not a Policy TZ field);
  node type from `node_deployment_info.resource_type` (HostNode/EdgeNode).
- Alarms: cursor pagination + exact-match `severity` filter exposed on CLI/MCP.

### Fixed — CLI commands that never worked
- `gateway configure-tier0-bgp` passed kwargs ops never accepted (TypeError on
  every run); reworked to the real BGP-settings capability
  (`--local-as/--enabled/--ecmp/--inter-sr-ibgp`; neighbor creation is a
  separate API and is not exposed).
- `network list-static-routes` crashed rendering next-hop dicts.

### Hardening
- REFLEXIVE NAT rules now require `translated_network`.
- `delete_tier1_gateway` removes the default locale-service first.

### Defense
- New spec-conformance regression: every API call AST-checked against 2530
  official path templates vendored from the NSX 4.2 SDKs
  (`tests/eval/spec/nsx_api_operations.json`).

## v1.5.30 (2026-06-07) — Fix 4 broken gateway/route/pool tools + tool description quality

### Fixed (critical)
Four tools were broken since their introduction — MCP wrappers and CLI commands passed
kwargs their ops functions don't accept, so every invocation failed with
TypeError/ValueError (swallowed into `{"error", "hint"}` payloads):
- `create_tier1_gateway`: passed `edge_cluster_path=`/`route_advertisement=`; now converts
  comma-separated advertisement types to `route_advertisement_types` list, and ops gained
  real `edge_cluster_path` support (creates the "default" locale-service on the gateway).
- `update_tier1_gateway`: passed `None` fields and a key rejected by ops `allowed_fields`
  (ValueError on every call); now sends only non-None fields under correct names.
- `create_static_route`: passed `next_hop=str`; now builds `next_hops=[{"ip_address": ...}]`.
- `create_ip_pool`: passed `start_ip/end_ip/cidr/gateway_ip`; now builds the
  `subnets=[{allocation_ranges, cidr, gateway_ip}]` structure ops expects.
- `get_bgp_neighbors` return annotation corrected `list[dict]` → `dict`.

Same fixes applied to the CLI commands (`gateway create-tier1`, `gateway update-tier1`,
`route create-static`, `ip-pool create`) — 踩坑 #19/#34 pattern.

### Tests
- New `tests/eval/regression/test_nsx_specific.py`: 8 tests exercising the real
  wrapper→ops path with a mocked NSX client; any future signature drift fails CI.

### Improved
- Rewrote 13 MCP tool descriptions (per-parameter formats, return fields, sibling-tool
  routing, PUT/PATCH semantics, audit disclosure) per Glama TDQS review.

## v1.5.29 (2026-05-29) — Family Version Alignment

No NSX-specific changes since v1.5.28. Bumped for family-wide v1.5.29 alignment.

## v1.5.28 (2026-05-20)

**Fix `subclass() arg 1 must be a class` in goose/old mcp environments** —
v1.5.25–1.5.27 replaced `X | None` with `Optional[X]` but kept
`from __future__ import annotations` at the top of `mcp_server/server.py`.
Under mcp 1.10–1.13 (which Goose and some sandboxes pin), `Tool.from_function`
calls `issubclass(param.annotation, Context)` without resolving forward refs,
so string annotations crash the entire server load. Removed
`from __future__ import annotations` from `mcp_server/server.py` so annotations
are real classes; verified all tools load under mcp 1.10 and 1.14.

Traceback location: `mcp/server/fastmcp/tools/base.py:67`. CLAUDE.md 踩坑 #33
updated. family_smoke.sh Check 4b now installs `mcp==1.10.0` to catch this
regression class.

## v1.5.27 (2026-05-20)

**Loosen Python requirement: now supports Python >= 3.10** — v1.5.25/26 fixed
the PEP 604 root cause in MCP tool signatures (Optional[X] instead of X | None),
but kept `requires-python = ">=3.11"` and a 3.11 hard guard in `mcp_cmd`. Both
relaxed to 3.10 so users on Python 3.10 (e.g. Goose default sandbox, Ubuntu
22.04 system python) can install and run directly without a Python upgrade.

- `pyproject.toml`: `requires-python = ">=3.10"` (was `>=3.11`; VMware-VKS
  was `>=3.12`, now also `>=3.10` for family alignment).
- `<pkg>/cli.py` `mcp_cmd()`: version guard now triggers on `< (3, 10)`.
- Behavior on Python 3.10 matches 3.11/3.12 — the Optional[X] fix from v1.5.25
  is what actually enables this; this release just stops blocking installs.

---

## v1.5.26

**Family-wide MCP server fix — Python 3.10 compatibility (踩坑 #33)** — `vmware-nsx mcp`
crashed at decorator time on Python 3.10 with `subclass() arg 1 must be a class`.
Root cause: `mcp_server/server.py` used PEP 604 `X | None` in tool signatures
plus `from __future__ import annotations`; on Python 3.10 + older mcp/pydantic
combos, `typing.get_type_hints()` evaluates `"str | None"` to a
`types.UnionType` instance, which FastMCP/Pydantic then feeds to `issubclass()`.
Reported by a goose user (qwen3.6:27, Python 3.10).

- `mcp_server/server.py`: all `X | None` → `Optional[X]`; ops layer untouched.
- `<pkg>/cli.py` `mcp_cmd()`: hard guard — exits with installation fix command
  if Python < 3.11 (defense in depth, our actual lower bound).
- `pyproject.toml`: `mcp[cli]>=1.10,<2.0` (was `>=1.0`) so uv doesn't pick
  an ancient version that has the same issubclass bug.

**Tooling — family smoke gains MCP schema-build check** — `scripts/family_smoke.sh`
new Check 4b runs `asyncio.run(mcp.list_tools())` per skill, forcing FastMCP to
build Pydantic models for every declared tool. Supports both module-level `mcp`
and `build_server()` factory patterns.

**Docs — CLAUDE.md gains 踩坑 #33 (PEP 604 / Python 3.10) and #34 (CLI/MCP exposure parity).**

---

## v1.5.24 (2026-05-19)

**Family version alignment** — no code changes in this skill. Bumped together
with VMware-AIops and VMware-VKS, which received a pyVmomi 8.x `ManagedObject`
setattr fix (踩坑 #32). `family_smoke.sh` now enforces the no-setattr rule
across all 9 skills.

## v1.5.23 (2026-05-19)

**NSX 9 / VCF 9.0 / 9.1 compatibility declared with caveats.**

- **docs:** README + `references/capabilities.md` version-compatibility tables now list NSX 9.0 / 9.1 and VCF 9.0 / 9.1 explicitly. The Policy API path used by this skill is fully supported in NSX 9.
- **docs:** Added NSX 9 caveats: (a) N-VDS removed — requires VDS 7.0+; (b) Bare-metal NSX agent removed, L2 overlay for physical servers no longer supported. Neither affects this skill's Segment/Gateway/NAT/Route/IPAM tools.
- **docs:** Added `Official Broadcom References` pointing to the [VMware NSX for Python SDK](https://developer.broadcom.com/sdks) as a future migration path (this skill currently uses raw REST requests against the Policy API — works fine in NSX 9 but may benefit from the official SDK later).
- **align:** Family v1.5.23 — all 9 skills tracking VCF 9.0 / 9.1 compatibility declaration.

## v1.5.22 (2026-05-08)

**Family alignment** — no source changes in this skill.

- **align:** Tracks v1.5.22 family bump driven by Smithery onboarding for vmware-avi / vmware-harden / vmware-pilot.

## v1.5.21 (2026-05-08)

**Family alignment** — no source changes in this skill.

- **deps:** Bumped `python-multipart` 0.0.26 → 0.0.27 (transitive, fixes GHSA HIGH DoS via unbounded multipart headers).
- **align:** Tracks v1.5.21 family bump driven by vmware-monitor folder_path feature (community PR #11).

## v1.5.20 (2026-05-08)

**Family alignment** — no source changes in this skill.

- **align:** Tracks v1.5.20 family bump driven by vmware-nsx-security and vmware-aria PyPI README `mcp-name:` ownership marker fix required by MCP Registry validation. Other 7 skills already had the marker; this release re-publishes them to keep the family version aligned per CLAUDE.md policy.
- **registry:** All 9 skills now registered on registry.modelcontextprotocol.io as `isLatest=true`.

## v1.5.19 (2026-05-06)

**Critical fix** — restores broken CLI subcommands for gateway / NAT / route / IP pool management.

- **fix(cli):** Corrected 9 broken imports in `vmware_nsx/cli.py`. Subcommands `gateway create-tier1 / update-tier1 / delete-tier1 / configure-tier0-bgp`, `nat create-rule / delete-rule`, `route create-static / delete-static`, and `ip-pool create` imported from non-existent modules `gateway_mgmt` / `nat_mgmt` / `route_mgmt` / `ip_pool_mgmt`. Actual functions live in `segment_mgmt.py` and `nat_route_mgmt.py`. Previously these commands raised `ModuleNotFoundError` at runtime (yjs review 2026-05-06; CLAUDE.md 踩坑 #27).
- **build:** Bumped `requires-python` from `>=3.10` to `>=3.11` (regression eval suite uses `tomllib` which is Py3.11+ builtin).
- **smoke:** Family `scripts/family_smoke.sh` now adds Check 3b — recursive `--help` on every Typer subcommand to trigger lazy imports. This is the harness change that would have caught this CLI bug before release.
- **align:** Family version bump to v1.5.19.

## v1.5.18 (2026-05-02)

**Family alignment + tooling normalization** — no source changes in this skill.

- **dev:** Added `[dependency-groups] dev` block (PEP 735) so `uv sync --group dev` works. Canonical set: `pytest>=8.0,<10.0`, `pytest-cov`, `ruff`.
- **test:** New `tests/eval/regression/test_release_blockers.py` (5 evals) catches the v1.5.x release blockers — missing `mcp_server` in wheel, AST-detected unimported runtime names (the v1.5.5 NSX `import re` incident is now caught at test time), Typer app load failure, module import errors. Run via `pytest tests/eval/regression/`.
- **note:** A separate cross-skill smoke check verifies that NSX and NSX-Security stay in sync on the form-body auth pattern (v1.4.9 special-character-password fix), so the v1.5.5 sync drift can't recur silently.
- **align:** Family version bump to v1.5.18.

## v1.5.17 (2026-05-01)

**Family alignment** — no source changes in this skill.

This release tracks vmware-pilot v1.5.17 (new `investigate_alert` template + `review_workflow` MCP tool + `parallel_group` step type) and vmware-policy v1.5.17 (L5 pattern matcher integrated into `@vmware_tool`). Both work with the existing skill MCP surface unchanged.

- **align:** Family version bump to v1.5.17.

## v1.5.16 (2026-04-30)

**Enterprise Harness Engineering alignment** — adapted from the Linkloud × addxai framework articles ([part 1](https://mp.weixin.qq.com/s/hz4W7ILHJ1yz_pG0Z1xP-A), [part 2](https://mp.weixin.qq.com/s/F3qYbyB3S8oIqx-Y4BrWNQ)).

- **docs:** "Automation Level Reference" section in `references/capabilities.md` — every tool tagged L1-L5 per the EHE framework.
- **docs:** Common Workflows in `SKILL.md` rewritten with pre-flight judgment (subnet conflict / edge cluster capacity / T0 uplink / NAT IP) and three-layer connectivity troubleshooting framework.
- **align:** Family version bump to v1.5.16.

## v1.5.15 (2026-04-29)

**UX improvements from real user feedback**

- **feat:** New top-level CLI subcommand `vmware-nsx mcp` starts the MCP server. Single command after `uv tool install vmware-nsx-mgmt` — no more `uvx --from`, no PyPI re-resolve, no TLS-proxy issues.
- **feat:** Default `verify_ssl: true` on new targets (was `false`). NSX Manager with default self-signed certs requires explicit `verify_ssl: false` in `config.yaml`.
- **docs:** README, SKILL.md, setup-guide.md, and `examples/mcp-configs/*.json` switched to `command: "vmware-nsx"`, `args: ["mcp"]`. uvx form to fallback with TLS-proxy troubleshooting note.
- **compat:** Legacy `vmware-nsx-mcp` console script kept — existing user configs continue to work.

## v1.5.14 (2026-04-21)

- Align with VMware skill family v1.5.14 (code review follow-up fixes by @yjs-2026)

## v1.5.13 (2026-04-21)

- Align with VMware skill family v1.5.13 (code review bug fixes)

## v1.5.12 (2026-04-17)

- Align with VMware skill family v1.5.12 (security & bug fixes from code review by @yjs-2026)

## v1.5.11 (2026-04-17)

- Align with VMware skill family v1.5.11 (AVI 22.x fixes from @timwangbc)

## v1.5.10 (2026-04-16)

- Security: bump python-multipart 0.0.22→0.0.26 (DoS via large multipart preamble/epilogue)
- Align with VMware skill family v1.5.10

## v1.5.8 (2026-04-15)

- Fix: CRITICAL — 9 MCP tools imported non-existent ops modules (`gateway_mgmt`, `nat_mgmt`, `route_mgmt`, `ip_pool_mgmt`) causing `ModuleNotFoundError` at runtime. Corrected to `segment_mgmt` (gateway functions) and `nat_route_mgmt` (NAT/route/IP pool functions). Tools affected: create/update/delete_tier1_gateway, configure_tier0_bgp, create/delete_nat_rule, create/delete_static_route, create_ip_pool.
- Fix: `configure_tier0_bgp` signature mismatch — MCP layer passed individual BGP neighbor params but ops expects `(client, tier0_id, locale_service_id, bgp_config dict)`. Rewrote MCP signature to match ops contract (local_as_num, enabled, ecmp, inter_sr_ibgp, locale_service_id).
- Fix: SSL warning suppression scope — replaced process-global `warnings.filterwarnings()` with class-targeted `urllib3.disable_warnings(InsecureRequestWarning)`, which no longer accidentally suppresses SSL warnings from other libraries in the same process.
- Align with VMware skill family v1.5.8

## v1.5.7 (2026-04-15)

- Align with VMware skill family v1.5.7 (Pilot `__from_step_N__` fix + VKS SSL/timeout fix)

## v1.5.6 (2026-04-15)

- Align with VMware skill family v1.5.6 (AVI bugfixes + packaging hotfix)

## v1.5.5 (2026-04-15)

- Fix: CRITICAL — missing `import re` in `ops/segment_mgmt.py` and `ops/nat_route_mgmt.py` caused `NameError: name 're' is not defined` at runtime for all segment/NAT/route CRUD operations
- Align with VMware skill family v1.5.5

## v1.5.4 (2026-04-14)

- Fix: CLI `segment create` TypeError — `subnet` (string) was passed to `create_segment()` which expects `subnets` (list of dicts); also parse `vlan_ids` string to `list[int]`
- Fix: CLI `segment update` ValueError — same `subnet` vs `subnets` mismatch in `update_segment()`
- Fix: CLI `health alarms` ImportError — `list_nsx_alarms` renamed to `list_alarms` in ops layer
- Fix: CLI `health manager-status` ImportError — `get_nsx_manager_status` renamed to `get_manager_status` in ops layer
- Fix: MCP server had identical mismatches for all four above (segment create/update, alarms, manager-status)
- Ref: https://github.com/vmware-skills/VMware-NSX/issues/3

## v1.5.0 (2026-04-12)

### Anthropic Best Practices Integration

- **[READ]/[WRITE] tool prefixes**: All MCP tool descriptions now start with [READ] or [WRITE] to clearly indicate operation type
- **Read/write split counts**: SKILL.md MCP Tools section header shows exact read vs write tool counts
- **Negative routing**: Description frontmatter includes "Do NOT use when..." clause to prevent misrouting
- **Broadcom author attestation**: README.md, README-CN.md, and pyproject.toml include VMware by Broadcom author identity (wei-wz.zhou@broadcom.com) to resolve Snyk E005 brand warnings

## v1.4.9 (2026-04-11)

- Fix: 403 auth failure for NSX passwords containing special chars (!, ), etc.)
  Switch /api/session/create from Basic Auth header to form-body credentials
  (j_username/j_password) matching curl behavior; preserve special chars
  unencoded using urllib.parse.quote safe-set to avoid NSX decoding issues.

## v1.4.8 (2026-04-09)

- Security: bump cryptography 46.0.6→46.0.7 (CVE-2026-39892, buffer overflow)
- Security: bump urllib3 2.3.0→2.6.3 (multiple CVEs) [VMware-VKS]
- Security: bump requests 2.32.5→2.33.0 (medium CVE) [VMware-VKS]

## v1.4.7 (2026-04-08)

- Fix: align openclaw metadata with actual runtime requirements
- Fix: standardize audit log path to ~/.vmware/audit.db across all docs
- Fix: update credential env var docs to correct VMWARE_<TARGET>_PASSWORD convention
- Fix: declare .env config and vmware-policy optional dependency in metadata

# Release Notes


## v1.4.6 — 2026-04-06

- fix: remove suspicious content from SKILL.md for ClawHub clean scan

---

## v1.4.5 — 2026-04-03

- **Security**: bump pygments 2.19.2 → 2.20.0 (fix ReDoS CVE in GUID matching regex)
- **Infrastructure**: add uv.lock for reproducible builds and Dependabot security tracking


## v1.4.6 — 2026-04-06

- fix: remove suspicious content from SKILL.md for ClawHub clean scan

---

## v1.4.0 — 2026-03-29

### Architecture: Unified Audit & Policy

- **vmware-policy integration**: All MCP tools now wrapped with `@vmware_tool` decorator
- **Unified audit logging**: Operations logged to `~/.vmware/audit.db` (SQLite WAL), replacing per-skill JSON Lines logs
- **Policy enforcement**: `check_allowed()` with rules.yaml, maintenance windows, risk-level gating
- **Sanitize consolidation**: Replaced local `_sanitize()` with shared `vmware_policy.sanitize()`
- **Risk classification**: Each tool tagged with risk_level (low/medium/high) for confirmation gating
- **Agent detection**: Audit logs identify calling agent (Claude/Codex/local)
- **New family members**: vmware-policy (audit/policy infrastructure) + vmware-pilot (workflow orchestration)


## v1.4.6 — 2026-04-06

- fix: remove suspicious content from SKILL.md for ClawHub clean scan

---

## v1.3.1 — 2026-03-27

### Family expansion: NSX-Security, Aria + hub entry point

- Added vmware-nsx-security and vmware-aria to companion skills routing table
- README updated with complete 7-skill family table
- vmware-aiops is now the family entry point (`vmware-aiops hub status`)


## v1.4.6 — 2026-04-06

- fix: remove suspicious content from SKILL.md for ClawHub clean scan

---

## v1.3.0 — 2026-03-26

### Initial release

- 31 MCP tools: 18 read-only + 13 write operations
- Network inventory: segments, Tier-0/Tier-1 gateways, transport zones/nodes, edge clusters
- Networking: NAT rules, BGP neighbors, static routes, IP pools
- Health: NSX alarms, transport node status, edge cluster status, manager status
- Troubleshooting: logical port status, VM-to-segment lookup
- Write operations: segment/gateway CRUD, NAT/route management, IP pool creation
- Safety: double confirmation + dry-run + audit logging on all write operations
- SKILL.md with progressive disclosure (Anthropic best practices)
- CLI (`vmware-nsx`) with typer — segment/gateway/nat/route/ippool/health/troubleshoot subcommands
- MCP server (31 tools) via stdio transport
- Docker one-command launch
- `vmware-nsx doctor` — 6-check environment diagnostics
- Audit logging (JSON Lines) for all operations
- references/: cli-reference.md, capabilities.md, setup-guide.md
- examples/mcp-configs/: 7 agent config templates (Claude Code, Cursor, Goose, Continue, LocalCowork, mcp-agent, VS Code Copilot)
- README.md and README-CN.md with Companion Skills, Workflows, Troubleshooting

**PyPI**: `uv tool install vmware-nsx-mgmt==1.3.0`
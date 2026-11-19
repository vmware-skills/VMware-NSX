# Shared result contract (unreleased migration)

Requires Policy 1.26.0. Failed MCP calls expose
`structuredContent.vmware_error` with string `error` and string-or-null `hint`.
Legacy text/structured business fields and success values remain available.
No tool names, input defaults or authorization/confirmation gates change.

For tools that accept offset, follow `next_offset` until null. Do not use
`truncated` as a loop condition. Tools without offsets do not gain a fictional
continuation, and cursor APIs retain their cursor semantics.

Shared page envelopes add offset metadata; existing collection/subset semantics are retained.

Release Policy first, then regenerate this component’s lock and validate its packaged dependency before merging/publishing. Source-overlay tests are not a released rollout.

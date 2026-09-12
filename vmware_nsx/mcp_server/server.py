"""MCP server wrapping VMware NSX networking operations.

This module is the thin entry point for the Model Context Protocol (MCP)
server (stdio transport). The tool implementations live under
``vmware_nsx.mcp_server.tools`` (one module per NSX domain) and register themselves onto
the shared ``mcp`` instance defined in ``vmware_nsx.mcp_server._shared``. Each tool
delegates to the corresponding function in the ``vmware_nsx`` package
(ops.inventory, ops.networking, ops.health, ops.troubleshoot,
ops.segment_mgmt, ops.nat_route_mgmt).

Tool categories
---------------
* **Read-only** (no side effects): list_segments, get_segment,
  list_tier0_gateways, get_tier0_gateway, list_tier1_gateways,
  get_tier1_gateway, list_transport_zones,
  list_transport_nodes, list_edge_clusters, list_nat_rules,
  get_bgp_neighbors, list_static_routes, list_ip_pools,
  get_ip_pool_usage, list_nsx_alarms, get_transport_node_status,
  get_edge_cluster_status, get_nsx_manager_status,
  get_logical_port_status, get_segment_port_for_vm

* **Write** (mutate state): create_segment, update_segment,
  delete_segment, create_tier1_gateway, update_tier1_gateway,
  delete_tier1_gateway, configure_tier0_bgp, create_nat_rule,
  delete_nat_rule, create_static_route, delete_static_route,
  create_ip_pool, delete_ip_pool — should be gated by the AI agent's
  confirmation flow.

Security considerations
-----------------------
* **Credential handling**: Credentials are loaded from environment
  variables / ``.env`` file — never passed via MCP messages.
* **Transport**: Uses stdio transport (local only); no network listener.
* **Destructive ops**: Write operations modify NSX networking config;
  confirmation is recommended before execution.

For DFW firewall/microsegmentation, use vmware-nsx-security.
For VM operations, use vmware-aiops.
For monitoring, use vmware-monitor.
"""


import logging
from typing import Any, Optional

from vmware_policy import describe_tool_parameters

from vmware_nsx.config import load_config
from vmware_nsx.connection import ConnectionManager

# Re-exported so callers and tests can keep using ``vmware_nsx.mcp_server.server.<name>``.
from vmware_nsx.mcp_server._shared import _DOCTOR_HINT, _safe_error, mcp

__all__ = ["mcp", "main", "_get_connection", "_safe_error", "_DOCTOR_HINT"]

# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

_conn_mgr: Optional[ConnectionManager] = None


def _get_connection(target: Optional[str] = None) -> Any:
    """Return an NsxClient, lazily initialising the connection manager.

    Tool modules call ``server._get_connection(...)`` (not a local import) so
    that tests can ``patch("vmware_nsx.mcp_server.server._get_connection")`` and have
    every tool pick up the patched callable.
    """
    global _conn_mgr  # noqa: PLW0603
    if _conn_mgr is None:
        # No env-var read here: load_config resolves the path (explicit arg,
        # then $VMWARE_NSX_CONFIG, then the default). This was a third copy of
        # that rule, and copies are how the doctor's copy drifted (形态 #6).
        config = load_config()
        _conn_mgr = ConnectionManager(config)
    return _conn_mgr.connect(target)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------
#
# Importing the tool package executes every ``@mcp.tool`` decorator, registering
# the tools on the shared ``mcp`` instance. This import must follow the
# ``_get_connection`` definition above: the tool modules import this module to
# resolve ``server._get_connection`` at *call* time, so a partially-initialised
# module is fine as long as the helper already exists.

from vmware_nsx.mcp_server import tools  # noqa: E402
from vmware_nsx.mcp_server._write_audit import install_write_audit

# Give every registered write tool this skill's own audit log — the sink the CLI
# surface has always written and the MCP surface never did. Must run BEFORE the
# re-export below, so the names published here are the audited callables and not
# a second, unaudited copy of each tool.
_AUDITED_WRITES = install_write_audit(mcp)

# Re-export every tool callable into this module's namespace so existing
# imports (``from vmware_nsx.mcp_server.server import create_tier1_gateway``) and tests
# (``getattr(srv, "delete_segment")``) keep working after the split.
for _mod in (
    tools.inventory,
    tools.networking,
    tools.health,
    tools.troubleshoot,
    tools.segment,
    tools.gateway,
    tools.nat,
    tools.route,
    tools.ip_pool,
):
    for _name in vars(_mod):
        if not _name.startswith("_"):
            _obj = getattr(_mod, _name)
            if callable(_obj) and getattr(_obj, "__module__", "") == _mod.__name__:
                globals()[_name] = _obj
del _mod, _name, _obj


# ---------------------------------------------------------------------------
# Environment declaration
# ---------------------------------------------------------------------------

# The environment resolver lives in policy_environment so the CLI registers
# it too (its @guarded writes go through the same guard()); importing it here
# registers it for the MCP surface.
from vmware_nsx.policy_environment import _cached_config, _environment_for  # noqa: F401 — imported to register the resolver, and re-exported

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server over stdio."""
    logging.basicConfig(level=logging.INFO)
    mcp.run(transport="stdio")

# The docstrings above are the schema. `describe_tool_parameters` copies each
# `Args:` entry into the JSON schema an agent actually reads, and closes the
# object. Without it every parameter reaches the model as a bare name and a
# type, which is how a wrong guess becomes an unfiltered result or a silent
# zero-row answer instead of an error (real-hardware round, 2026-08-30).
_DESCRIBED_PARAMS = describe_tool_parameters(mcp._tool_manager._tools)

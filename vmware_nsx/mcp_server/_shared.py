"""Shared MCP primitives: the FastMCP instance and the error sanitizer.

Tool modules under ``vmware_nsx.mcp_server.tools`` import ``mcp`` (to register tools),
``_safe_error`` (agent-safe error formatting), and ``_DOCTOR_HINT`` from here.
The connection helper lives in ``vmware_nsx.mcp_server.server`` instead, so that tests can
``patch("vmware_nsx.mcp_server.server._get_connection")`` and have every tool pick it up;
tool modules therefore call ``server._get_connection(...)`` at runtime.
"""

import logging
import ssl

from mcp.server.fastmcp import FastMCP
from vmware_policy import sanitize

from vmware_nsx.config import ConfigError
from vmware_nsx.connection import NsxApiError
from vmware_nsx.ops.delete_gate import DeleteRefusedError
from vmware_nsx import __version__

logger = logging.getLogger("mcp_server")

_DOCTOR_HINT = "Run 'vmware-nsx doctor' to verify connectivity."

#: Longest gate refusal passed to the caller (see ``_safe_error``).
_REFUSAL_MAX = 2000


def _safe_error(exc: Exception, tool: str) -> str:
    """Return an agent-safe error string; log full detail server-side only.

    Raw NSX exception text can carry response bodies, internal paths, or
    host:port pairs. Full traceback goes to stderr (operator-visible); the agent
    sees only a control-char-stripped, length-capped message.

    The rule is a property, not a list: every exception this skill raises on
    purpose passes through, and only genuinely unplanned ones are reduced. That
    covers the builtin validation errors, the connection layer's teaching errors
    (``NsxApiError``), and ``ConnectionError``, which ``connection.py`` raises
    when session creation succeeds but no X-XSRF-TOKEN header comes back —
    a message that names the proxy-stripping cause and the config keys to check.

    The missing-password error — this family's most common first-run failure,
    whose entire remedy is the env var name it carries — arrives as
    ``ConfigError``, a narrow ``OSError`` subclass ``config.py`` raises on
    purpose. Bare ``OSError`` is deliberately *not* here: it would also admit
    ``socket.gaierror`` (the name that failed to resolve) and ``requests``-style
    connection errors (the full ``scheme://host:port/path``), neither of which
    is authored text. ``sanitize`` strips control characters and truncates; it
    redacts nothing, so breadth here is exposure.

    ``FileNotFoundError``, ``PermissionError``, ``TimeoutError`` and
    ``ConnectionError`` stay: each is narrow, each was already reachable through
    the ``OSError`` entry this replaces, and their text describes the operator's
    own environment rather than the manager's response. Two are raised here
    deliberately — ``FileNotFoundError`` for a missing config file, and
    ``ConnectionError`` for the missing X-XSRF-TOKEN case above.

    ``ssl.SSLError`` is reduced *before* the allowlist is consulted, because an
    allowlist structurally cannot say "not this one":
    ``ssl.SSLCertVerificationError`` inherits from ``ValueError`` as well as
    ``OSError``, and ``ValueError`` has been allowed since long before any of
    this. Its message quotes the certificate subject and the hostname. Only
    ``ssl.SSLError`` is pre-checked — ``socket.gaierror`` and
    ``ConnectionRefusedError`` have ``OSError`` as their only base, so removing
    ``OSError`` already reduces them, and naming them here would make the guard
    promise more than it does.

    That pre-check cannot fire on this skill's own transport path, and saying so
    matters more than the guard does: httpx raises ``httpx.ConnectError`` for a
    TLS failure, which is not an ``ssl.SSLError`` subclass, and
    ``connection.py`` translates it into an allowlisted ``NsxApiError``. What
    keeps the certificate subject out of agent context here is that
    ``connection.py`` no longer interpolates the raw exception into that
    message. The pre-check is defence in depth for an ``ssl.SSLError`` arriving
    by some other route, and is verified against a constructed one.

    Anything else is reduced to its type — an unplanned exception's text was
    written for a developer reading a traceback, not for an agent choosing what
    to do next, and it is the one that can carry credentials.
    """
    logger.error("Tool %s failed", tool, exc_info=True)
    if isinstance(exc, ssl.SSLError):
        return f"{type(exc).__name__}: operation failed."
    if isinstance(exc, DeleteRefusedError):
        # A gate refusal is authored text built from sanitized ids, and it
        # names every blocker plus the next step: a Tier-1 with several kinds
        # of dependents runs past 300 characters, and cutting it would cut the
        # remedy. It still passes through ``sanitize``.
        return sanitize(str(exc), _REFUSAL_MAX)
    _passthrough = (
        ValueError,
        FileNotFoundError,
        KeyError,
        PermissionError,
        TimeoutError,
        ConnectionError,
        ConfigError,
        NsxApiError,
    )
    if isinstance(exc, _passthrough):
        return sanitize(str(exc), 300)
    return f"{type(exc).__name__}: operation failed."


def _delete_error(exc: Exception, hint: str) -> dict:
    """The error envelope for a gated delete; a refusal also carries what it measured.

    A dict with ``error`` is what both audit sinks read as a failure, so a
    refusal is audited as one without ``report_tool_failure``.
    """
    out: dict = {"error": _safe_error(exc, "nsx"), "hint": hint}
    radius = getattr(exc, "blast_radius", None)
    if isinstance(radius, dict):
        out["blast_radius"] = radius
    return out


mcp = FastMCP(
    "vmware-nsx",
    instructions=(
        "VMware NSX networking management. "
        "Query and configure network segments, Tier-0/Tier-1 gateways, "
        "NAT rules, static routes, IP pools, transport zones/nodes, "
        "and edge clusters. Check NSX health, alarms, and troubleshoot "
        "connectivity. For DFW firewall/microsegmentation, use vmware-nsx-security. "
        "For VM operations, use vmware-aiops. For monitoring, use vmware-monitor."
    ),
)

# FastMCP takes no version argument and leaves the lowlevel server's at
# None, which makes `initialize` answer with the MCP SDK's version rather
# than ours. Set it so a client can tell which release it is talking to.
mcp._mcp_server.version = __version__

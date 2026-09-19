"""Give the MCP write surface the skill audit log the CLI surface already has.

Two sinks exist and they are not redundant. ``~/.vmware/audit.db`` is the
family's shared SQLite trail that ``@vmware_tool`` writes for every tool call on
every skill; nothing here replaces or duplicates it. ``~/.vmware-nsx/audit.log``
is this skill's own JSON-Lines log — the one ``README.md`` advertises, the one
``cli._audit.log`` appends to on every CLI write, and the one an operator opens
on the box when asked what changed on the NSX manager. Until this module, no
MCP tool had ever written a line to it, so ``vmware-nsx segment delete`` left a
record there and the ``delete_segment`` tool did not.

**Why a registration-time sweep and not a per-tool call.** The sibling repo
closes the same gap by calling ``_audit.log(...)`` in each write tool body. That
works until someone adds tool fourteen, and CLAUDE.md 形态 #7 says that is what
happens: a marker every tool has to remember is a marker some tool will forget,
which is why the family put credential redaction in the shared decorator rather
than in per-tool declarations. Here the property is derived from the same thing
the tool already declares to the client — ``readOnlyHint: False`` — so a new
write tool is audited before anyone has thought about it, whatever route it took
to registration.

The sweep rebinds both the FastMCP registry entry and the attribute on the
module that defined the tool. Rebinding only the registry would leave
``vmware_nsx.mcp_server.server.delete_segment`` — which ``server.py`` re-exports
and much of this repo calls directly — pointing at the unaudited function.
"""

from __future__ import annotations

import functools
import inspect
import logging
import sys
from collections.abc import Callable
from typing import Any

from vmware_policy import PolicyDenied, sanitize

from vmware_nsx.notify.audit import AuditLogger

logger = logging.getLogger("mcp_server.write_audit")

_audit = AuditLogger()

#: Longest parameter value kept in an audit line. A policy path or a comma-joined
#: VLAN spec is short; an unbounded value would let one call dominate the file.
_MAX_VALUE = 300


def _bind(signature: inspect.Signature, args: tuple, kwargs: dict) -> dict[str, Any]:
    """Full name→value mapping for the call, positional arguments included.

    Falls back to keywords alone when binding fails: the real call is about to
    raise its own ``TypeError`` and this should not mask it with a different one.
    """
    try:
        bound = signature.bind_partial(*args, **kwargs)
        bound.apply_defaults()
    except TypeError:
        return dict(kwargs)
    return dict(bound.arguments)


def _subject(signature: inspect.Signature, params: dict[str, Any]) -> str:
    """The id of the object the call acts on.

    Every write tool on this surface takes it as its first parameter
    (``segment_id``, ``tier1_id``, ``pool_id``, ``tier0_id``). ``target`` names
    the *manager*, not the object, and is recorded in its own field, so it is
    skipped rather than allowed to stand in as the subject of a one-argument
    tool that has not been written yet.
    """
    for name in signature.parameters:
        if name == "target":
            continue
        value = params.get(name)
        if value is None:
            continue
        return sanitize(str(value), _MAX_VALUE)
    return ""


def _failed(result: Any) -> bool:
    """Whether a returned value says the write did not happen.

    The writes return the family envelope ``{"error", "hint"}`` — the same key
    ``vmware_policy`` reads. Until the confirmation gate (HLD §7) the five
    deletes returned a sentence, a confirmation or one beginning "Error:"; they
    return the envelope now, and the string branch stays for any write that
    still answers in a sentence. ``@vmware_tool`` refuses to sniff strings for a
    good reason — a skill whose output *is* console text could emit "Error:" as
    data — but nothing this surface returns is console text, and the
    alternative is filing a write that did not happen as ``ok``.
    """
    if isinstance(result, dict):
        return bool(result.get("error"))
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
        return bool(result[0].get("error"))
    if isinstance(result, str):
        return result.startswith("Error:")
    return False


def _outcome(result: Any) -> str:
    """``error``, ``preview`` or ``ok`` for one returned value.

    A gated delete called without ``confirm=True`` returns ``{"action":
    "preview"}`` and changes nothing. Filed as ``ok`` it reads as a deletion
    in a log whose rows are meant to be true, so it is filed the way the CLI
    files its ``--dry-run`` (``dry-run``): as what it was.
    """
    if _failed(result):
        return "error"
    if isinstance(result, dict) and result.get("action") == "preview":
        return "preview"
    return "ok"


def _record(tool: str, signature: inspect.Signature, params: dict[str, Any], result: str) -> None:
    """Append one line, or warn. Audit failure must never fail the operation."""
    recorded = {
        name: sanitize(str(value), _MAX_VALUE) if isinstance(value, str) else value
        for name, value in params.items()
        if name != "target"
    }
    try:
        _audit.log(
            target=str(params.get("target") or "default"),
            operation=tool,
            resource=_subject(signature, params),
            parameters=recorded,
            result=result,
        )
    except Exception:  # degrade to a warning, exactly as audit.py does for OSError
        logger.warning("Could not audit %s to the skill log", tool, exc_info=True)


def _audited(fn: Callable) -> Callable:
    """Wrap ``fn`` so the call appears in the skill audit log either way."""
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        params = _bind(signature, args, kwargs)
        try:
            result = fn(*args, **kwargs)
        except PolicyDenied:
            # A deny rule or maintenance window refused the call. It is neither
            # an ok nor a transport error, and an operator reading the log for
            # "what did the agent try" needs the attempt to be visible.
            _record(fn.__name__, signature, params, "denied")
            raise
        except Exception:
            _record(fn.__name__, signature, params, "error")
            raise
        _record(fn.__name__, signature, params, _outcome(result))
        return result

    return wrapper


def install_write_audit(server: Any) -> list[str]:
    """Wrap every registered write tool so it records to the skill audit log.

    A tool is a write when it told the client so: ``readOnlyHint is False``.
    Tools that left the hint unset are not swept — an unstated hint is not a
    claim, and guessing from the name here would put the guess in the enforcement
    path instead of in the test that cross-checks it.

    Returns the names swept, so a caller (and the import-time binding in
    ``server.py``) has something to assert on rather than a silent no-op.
    """
    audited: list[str] = []
    for name, tool in server._tool_manager._tools.items():
        if getattr(getattr(tool, "annotations", None), "readOnlyHint", None) is not False:
            continue
        wrapped = _audited(tool.fn)
        tool.fn = wrapped
        # Keep the defining module's attribute pointing at the same object, so
        # ``server.py``'s re-export (which runs after this) hands out the audited
        # callable and there is exactly one function per tool in the process.
        owner = sys.modules.get(getattr(tool.fn, "__module__", ""))
        if owner is not None and getattr(owner, name, None) is not None:
            setattr(owner, name, wrapped)
        audited.append(name)
    return audited

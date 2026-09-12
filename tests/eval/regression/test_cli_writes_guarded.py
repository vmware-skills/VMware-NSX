"""Every CLI command that performs a write is wrapped by @guarded (HLD I-1, I-8).

A write CLI command must route through vmware_policy's guard() + audit_call() —
the same enforcement @vmware_tool gives the MCP surface — so ``vmware-nsx segment
delete`` run through Bash is authorized and audited to ~/.vmware/audit.db exactly
like the ``delete_segment`` MCP tool — under that same operation name, so one deny
rule scopes both surfaces. Without @guarded a CLI write bypassed policy
and landed only in the legacy per-skill log (the gap HLD §2.1 documents).

The write set is DERIVED, never hand-listed (踩坑 #43): a tool annotated
``readOnlyHint=False`` is a write; the ops functions its body calls — reached by
a bare name OR ``module.func`` on an ops-module import — are the state-changing
ops; a CLI ``@command`` calling one is a write command and must carry @guarded.
The aliased-import case is not optional here: NSX MCP tools alias their ops
imports (``from vmware_nsx.ops.segment_mgmt import create_tier1_gateway as
_create``), and a derivation that only follows un-aliased names silently skips
every NSX write command — the "label promises more than content" shape.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib

_REPO = pathlib.Path(__file__).resolve().parents[3]
CLI_DIR = _REPO / "vmware_nsx" / "cli"
TOOLS_DIR = _REPO / "vmware_nsx" / "mcp_server" / "tools"
assert CLI_DIR.is_dir(), f"CLI package not found at {CLI_DIR} — the scan would find nothing"
assert TOOLS_DIR.is_dir(), f"MCP tools not found at {TOOLS_DIR} — the derivation would be empty"


def _write_tool_names() -> frozenset[str]:
    from vmware_nsx.mcp_server.server import mcp

    return frozenset(
        t.name
        for t in asyncio.run(mcp.list_tools())
        if getattr(getattr(t, "annotations", None), "readOnlyHint", None) is False
    )


def _ops_refs(tree: ast.AST) -> tuple[dict[str, str], set[str]]:
    """(local name -> REAL ops function name, ops-module aliases).

    An aliased import (``from ops.mod import realname as _alias``) maps
    ``_alias -> realname`` so an aliased call resolves to the same op an
    un-aliased import names. REST skills alias their ops (``... as _create``)
    while the CLI imports the real name; both must derive to the real name or
    the MCP→ops→CLI intersection is empty (the shape that hid all 13 NSX writes).
    """
    func_map: dict[str, str] = {}
    mods: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            parts = n.module.split(".")
            if "ops" in parts:
                if parts[-1] == "ops":
                    mods.update(a.asname or a.name for a in n.names)
                else:
                    for a in n.names:
                        func_map[a.asname or a.name] = a.name
    return func_map, mods


def _ops_calls(node: ast.AST, func_map: dict[str, str], mods: set[str]) -> set[str]:
    """Real ops function names called in ``node`` — via ``f()`` or ``mod.f()``."""
    out: set[str] = set()
    for c in ast.walk(node):
        if not isinstance(c, ast.Call):
            continue
        f = c.func
        if isinstance(f, ast.Name) and f.id in func_map:
            out.add(func_map[f.id])
        elif (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.value.id in mods
        ):
            out.add(f.attr)
    return out


def _write_ops() -> frozenset[str]:
    targets = _write_tool_names()
    ops: set[str] = set()
    for path in sorted(TOOLS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        func_map, mods = _ops_refs(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in targets:
                ops |= _ops_calls(node, func_map, mods)
    return frozenset(ops)


def _decorator_names(node: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for d in node.decorator_list:
        t = d.func if isinstance(d, ast.Call) else d
        if isinstance(t, ast.Name):
            names.add(t.id)
        elif isinstance(t, ast.Attribute):
            names.add(t.attr)
    return names


def _cli_write_commands() -> tuple[list[str], list[str]]:
    """(write commands, of those the ones missing @guarded)."""
    write_ops = _write_ops()
    assert write_ops, "no write ops derived — vacuous"
    writing: list[str] = []
    unguarded: list[str] = []
    for path in sorted(CLI_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        func_map, mods = _ops_refs(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not any(
                isinstance(d, ast.Call)
                and isinstance(getattr(d, "func", None), ast.Attribute)
                and d.func.attr == "command"
                for d in node.decorator_list
            ):
                continue
            if _ops_calls(node, func_map, mods) & write_ops:
                label = f"{path.name}:{node.name}"
                writing.append(label)
                if "guarded" not in _decorator_names(node):
                    unguarded.append(label)
    return writing, unguarded


def test_every_write_cli_command_is_guarded():
    writing, unguarded = _cli_write_commands()
    # The 13 guarded writes: segment create/update/delete, tier-1 create/update/
    # delete, tier-0 BGP, NAT create/delete, static route create/delete, IP pool
    # create/delete.
    assert len(writing) >= 13, (
        f"only {len(writing)} write CLI commands derived ({writing}) — the "
        f"MCP→ops→CLI derivation is likely stale; a check matching almost nothing "
        f"is worse than none."
    )
    assert not unguarded, (
        f"these CLI commands call a [WRITE] ops function but are not @guarded, so "
        f"they bypass policy + audit (HLD I-1): {unguarded}"
    )


def test_high_blast_radius_commands_are_derived_and_guarded():
    """Pin named commands so a broad-but-wrong derivation cannot pass the floor.

    These NSX deletes only appear when the derivation resolves the aliased ops
    imports the MCP tools use (``... as _delete``) back to the real ops name — their
    presence proves that path works and no destructive door slipped the net.
    """
    writing, _ = _cli_write_commands()
    names = {w.split(":", 1)[1] for w in writing}
    for must in ("gateway_delete_tier1", "segment_delete", "nat_delete_rule"):
        assert must in names, (
            f"{must} is no longer derived as a write command — the readOnlyHint→"
            f"ops→command derivation stopped resolving it"
        )


def _op_to_mcp_tools() -> dict[str, set[str]]:
    """Write ops function -> the MCP write tools whose body calls it.

    ``_ops_refs`` resolves aliases per FILE, and NSX tools alias inside each
    function (``... import delete_segment as _delete``). That is only sound
    while no file binds one alias to two different ops — so that is asserted
    rather than assumed: a collision would silently point a twin at the wrong
    tool.
    """
    targets = _write_tool_names()
    out: dict[str, set[str]] = {}
    for path in sorted(TOOLS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bound: dict[str, set[str]] = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and "ops" in n.module.split("."):
                for a in n.names:
                    bound.setdefault(a.asname or a.name, set()).add(a.name)
        collisions = {k: v for k, v in bound.items() if len(v) > 1}
        assert not collisions, (
            f"{path.name} binds one alias to several ops {collisions} — the per-file "
            f"alias map cannot tell them apart; resolve imports per function"
        )
        func_map, mods = _ops_refs(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in targets:
                for op in _ops_calls(node, func_map, mods):
                    out.setdefault(op, set()).add(node.name)
    return out


# Guarded CLI writes with NO MCP twin, each with the reason it stays CLI-only and
# keeps its own operation name. Empty today: every guarded NSX command mirrors
# exactly one MCP write tool. An entry here is a decision, not a default — a
# command landing here silently would be a deny rule that cannot reach it.
_CLI_ONLY_WRITES: dict[str, str] = {}


def test_guarded_cli_writes_carry_their_mcp_tool_name():
    """A deny rule names a tool; it must stop the CLI twin of that tool too (HLD I-3).

    ``@guarded`` defaults the tool name to the function's ``__name__``, so
    ``segment delete`` was guarded as ``segment_delete`` while its MCP twin is
    ``delete_segment`` — a rule denying ``delete_segment`` refused the agent and
    let the same delete through the CLI, and the two surfaces wrote the one
    audit sink under two names. The twin is DERIVED: the MCP write tool that
    calls the same ops function the command calls.
    """
    from vmware_nsx import cli
    from vmware_nsx.mcp_server import server as srv

    op_tools = _op_to_mcp_tools()
    write_ops = frozenset(op_tools)
    checked: list[str] = []
    mismatched: list[str] = []
    for path in sorted(CLI_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        func_map, mods = _ops_refs(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            fn = getattr(cli, node.name, None)
            if not getattr(fn, "_is_guarded", False):
                continue  # unguarded writes are test_every_write_cli_command_is_guarded's finding
            ops = _ops_calls(node, func_map, mods) & write_ops
            twins = set().union(*(op_tools[o] for o in ops)) if ops else set()
            if not twins:
                assert node.name in _CLI_ONLY_WRITES, (
                    f"{node.name} is @guarded but mirrors no MCP write tool — either "
                    f"it calls an op the derivation cannot see, or it is a CLI-only "
                    f"write that needs an explicit _CLI_ONLY_WRITES entry with a reason"
                )
                continue
            assert len(twins) == 1, (
                f"{node.name} maps to several MCP tools {sorted(twins)} — pick "
                f"the one it mirrors explicitly"
            )
            (twin,) = twins
            checked.append(f"{node.name}->{twin}")
            if fn._guarded_tool != twin:
                mismatched.append(f"{node.name}: guarded as {fn._guarded_tool!r}, MCP tool {twin!r}")
            elif fn._risk_level != getattr(srv, twin)._risk_level:
                mismatched.append(
                    f"{node.name}: risk {fn._risk_level!r}, MCP tool {twin!r} "
                    f"risk {getattr(srv, twin)._risk_level!r}"
                )
    # 13 guarded write commands exist today; a derivation that checks fewer has
    # stopped resolving twins.
    assert len(checked) >= 13, f"only {checked} checked — derivation likely stale"
    assert not mismatched, (
        "these CLI writes are guarded under a different name or risk than their "
        "MCP tool, so one deny rule does not scope both surfaces — pass the MCP "
        "tool name to @guarded(...): " + "; ".join(mismatched)
    )

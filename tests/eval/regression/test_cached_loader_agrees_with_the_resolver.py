"""The MCP server's cache and the resolver must not disagree about which file.

Background, 2026-08-30. The config-path precedence — explicit argument, then
``VMWARE_NSX_CONFIG``, then ``CONFIG_FILE`` — was consolidated into
``resolve_config_path``, because it had been written out in three places and no
two of them agreed. A fourth statement of it appeared to remain, in the shared
``vmware_policy.mtime_cached_loader`` that the MCP server wraps ``load_config``
in, and it lives in another package where this skill cannot consolidate it.

Reading it closely, it is **not** a fourth copy of the rule for *which file to
open*: when the variable is unset it passes ``None`` to the loader and lets the
loader resolve. It states the precedence only to decide *when the cache is
stale* — so a disagreement here would produce a stale or over-eager cache, never
a wrong file. That is a much smaller failure than the one being fixed, but it is
still a hot-reload contract quietly broken, and nothing checked it.

So this asserts the two agree, rather than merging them. What it pins:

* the path the cache stats is the path the loader ends up opening, in every
  state of the variable — including the empty string, where "set but empty" must
  not diverge between them;
* the ``default_path`` the server passes is the same ``CONFIG_FILE`` the
  resolver falls back to (if these drifted apart, the cache would stat one file
  while the loader read another, and an edit to the real config would never be
  picked up).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from vmware_policy import mtime_cached_loader

from vmware_nsx.config import CONFIG_FILE, resolve_config_path

_ENV = "VMWARE_NSX_CONFIG"


def _spy():
    """A loader that records the argument it was handed, and nothing else.

    Deliberately not a real config load: this test is about which path is
    chosen, and making it depend on a parseable config file would tie it to the
    schema and stop it running where no config exists.
    """
    seen: list = []

    def loader(path):
        seen.append(path)
        return object()

    return loader, seen


def _effective_load_path(handed) -> Path:
    """The file ``load_config(handed)`` will actually open."""
    return resolve_config_path(handed)


@pytest.mark.unit
def test_with_the_variable_unset_both_settle_on_the_default(monkeypatch, tmp_path):
    monkeypatch.delenv(_ENV, raising=False)
    loader, seen = _spy()
    cached = mtime_cached_loader(_ENV, CONFIG_FILE, loader)

    cached()

    assert seen == [None], "the loader must be left to resolve its own default"
    assert _effective_load_path(seen[0]) == CONFIG_FILE
    # And that is the file the cache is watching.
    assert Path(CONFIG_FILE) == _effective_load_path(seen[0])


@pytest.mark.unit
def test_with_the_variable_set_both_settle_on_that_file(monkeypatch, tmp_path):
    elsewhere = tmp_path / "elsewhere.yaml"
    elsewhere.write_text("targets: {}\n", encoding="utf-8")
    monkeypatch.setenv(_ENV, str(elsewhere))
    loader, seen = _spy()
    cached = mtime_cached_loader(_ENV, CONFIG_FILE, loader)

    cached()

    assert seen == [elsewhere]
    assert _effective_load_path(seen[0]) == elsewhere


@pytest.mark.unit
def test_the_cli_path_and_the_server_path_are_the_same_file(monkeypatch, tmp_path):
    """The property that actually matters — and the one the cache hides.

    ``mtime_cached_loader`` hands the loader the variable's path *explicitly*
    when it is set, so the MCP server opens the right file even if
    ``resolve_config_path`` has no env-var clause at all. Every other assertion
    in this file is therefore satisfied by a resolver that ignores the variable
    completely (verified: that mutation passes them all).

    That is not hypothetical. It is exactly how four sibling skills came to have
    the agent and the human on different vCenters — their servers honoured the
    variable through this loader while their ``load_config`` did not, and
    nothing failed, because the server was never relying on the clause that was
    missing.

    So the assertion is on the *bare* call, the one the CLI and the doctor make.
    """
    elsewhere = tmp_path / "elsewhere.yaml"
    elsewhere.write_text("targets: {}\n", encoding="utf-8")
    monkeypatch.setenv(_ENV, str(elsewhere))
    loader, seen = _spy()
    mtime_cached_loader(_ENV, CONFIG_FILE, loader)()

    assert resolve_config_path() == seen[0] == elsewhere, (
        "the MCP server opens the file named by the variable while a bare "
        "load_config() opens something else — the agent and the CLI are on "
        "different configurations"
    )


@pytest.mark.unit
def test_an_empty_variable_means_unset_to_both(monkeypatch):
    """Set-but-empty is the state where two independent truthiness tests are
    most likely to part company, and it is reachable from a shell that exports
    the name without a value."""
    monkeypatch.setenv(_ENV, "")
    loader, seen = _spy()
    cached = mtime_cached_loader(_ENV, CONFIG_FILE, loader)

    cached()

    assert seen == [None]
    assert _effective_load_path(seen[0]) == CONFIG_FILE
    assert resolve_config_path() == CONFIG_FILE


@pytest.mark.unit
def test_the_server_hands_the_loader_the_resolvers_own_default():
    """If the server's ``default_path`` and the resolver's fallback drifted
    apart, the cache would stat one file while the loader read another, and an
    edit to the real config would never be noticed."""
    import inspect

    # The call site moved out of mcp_server/server.py on 2026-09-11 so the CLI
    # registers the same resolver; this is where it lives now.
    from vmware_nsx import policy_environment

    source = inspect.getsource(policy_environment)
    assert "mtime_cached_loader(\"" + _ENV + "\", CONFIG_FILE, load_config)" in source, (
        "the call site no longer passes CONFIG_FILE as the default; if it now "
        "passes something else, this test must be updated deliberately rather "
        "than the two allowed to drift"
    )
    os.environ.pop(_ENV, None)
    assert resolve_config_path() == CONFIG_FILE


@pytest.mark.unit
def test_changing_the_variable_mid_process_moves_both(monkeypatch, tmp_path):
    """The documented hot-reload contract: the name is re-read on every call.
    If the cache did not follow, the server would keep serving the old file."""
    first, second = tmp_path / "a.yaml", tmp_path / "b.yaml"
    first.write_text("targets: {}\n", encoding="utf-8")
    second.write_text("targets: {}\n", encoding="utf-8")
    loader, seen = _spy()
    cached = mtime_cached_loader(_ENV, CONFIG_FILE, loader)

    monkeypatch.setenv(_ENV, str(first))
    cached()
    monkeypatch.setenv(_ENV, str(second))
    cached()

    assert seen == [first, second]
    assert [_effective_load_path(p) for p in seen] == [first, second]

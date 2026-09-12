"""Configuration management for VMware NSX.

Loads targets and settings from YAML config file + environment variables.
Passwords are NEVER stored in config files — always via environment variables.
"""

from __future__ import annotations

from vmware_policy.fsperms import check_secret_file

import base64
import binascii
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import dotenv_values, load_dotenv, set_key

CONFIG_DIR = Path.home() / ".vmware-nsx"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"

_log = logging.getLogger("vmware-nsx.config")

_PW_KEY_RE = re.compile(r"[A-Z][A-Z0-9_]*_PASSWORD")


def _is_b64_token(value: str) -> tuple[bool, str]:
    """Return ``(True, decoded)`` if ``value`` is a valid ``b64:`` token, else ``(False, "")``.

    Recognises already-encoded values (for idempotency) and decodes on read. A
    value that merely *starts with* ``b64:`` but is not valid base64 (e.g. a real
    password ``b64:hunter2``) is NOT a token — it is treated as plaintext, so such
    a password still round-trips correctly instead of being corrupted.
    """
    if not value.startswith("b64:"):
        return (False, "")
    try:
        return (True, base64.b64decode(value[4:], validate=True).decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return (False, "")


def _decode_secret(value: str) -> str:
    """Decode a ``b64:`` token; any other value passes through unchanged.

    Obfuscation to defeat casual grep — NOT encryption.
    """
    ok, decoded = _is_b64_token(value)
    return decoded if ok else value


def _autoencode_env_file(env_file: Path) -> None:
    """Rewrite plaintext ``*_PASSWORD`` values in .env to grep-safe ``b64:`` form.

    Values are read and written through python-dotenv's own parser/serializer
    (``dotenv_values`` + ``set_key``), so the stored value is exactly what
    ``load_dotenv`` would return — quoting, inline comments, and trailing
    whitespace are handled identically and the secret never drifts from the
    configured one. Idempotent (already-``b64:`` tokens are skipped); only
    ``*_PASSWORD`` keys are touched. Obfuscation, not encryption.
    """
    if not env_file.exists():
        return
    try:
        parsed = dotenv_values(env_file)
    except OSError:
        return

    changed = False
    for key, value in parsed.items():
        if not value or not _PW_KEY_RE.fullmatch(key) or _is_b64_token(value)[0]:
            continue
        encoded = "b64:" + base64.b64encode(value.encode("utf-8")).decode("ascii")
        try:
            set_key(str(env_file), key, encoded, quote_mode="never")
            changed = True
        except OSError as exc:
            _log.warning("Could not auto-encode %s in %s: %s", key, env_file, exc)

    if not changed:
        return
    try:
        os.chmod(env_file, 0o600)
    except OSError:
        pass
    _log.warning(
        "Auto-encoded plaintext password(s) in %s to b64: (grep-safe; "
        "obfuscation, not encryption).",
        env_file,
    )


# Auto-encode any plaintext passwords in .env, then load it into the environment
_autoencode_env_file(ENV_FILE)
load_dotenv(ENV_FILE)


def _check_env_permissions() -> None:
    """Warn if the .env file is readable by anyone but its owner.

    Delegates to ``vmware_policy.fsperms.check_secret_file`` so this hot path and
    ``doctor`` answer the same question the same way. They did not: doctor was
    moved to the three-state check while this stayed on a POSIX mode-bit test, so
    a single command on Windows printed both

        Security warning: <config dir>/.env has permissions 0o666 (should be 600).
        Run: chmod 600 ...                      <- here, red, and chmod is a no-op
        .env permissions | PASS | This platform does not express file
        permissions as POSIX mode bits ... run: icacls ...   <- doctor, green

    about the same file in the same run. The remedy printed here was the one that
    does nothing on the platform being warned about.

    ``unknown`` (a platform with no POSIX mode bits) is deliberately silent here:
    it is not a finding, and doctor is where a nuanced verdict belongs. Only an
    actually-too-open file warns.
    """
    check = check_secret_file(ENV_FILE)
    if check.verdict == "too_open":
        _log.warning("Security warning: %s", check.message)


_check_env_permissions()


class ConfigError(OSError):
    """A configuration problem the operator can fix, safe to show an agent.

    Subclasses ``OSError`` so the CLI paths that already catch ``OSError`` keep
    working. The point of the narrow type is the MCP path: ``_safe_error``
    passes this through verbatim, and passing through bare ``OSError`` also
    passed through TLS, DNS and socket errors carrying hostnames and URLs.
    """


@dataclass(frozen=True)
class TargetConfig:
    """An NSX Manager connection target."""

    host: str
    username: str
    port: int = 443
    verify_ssl: bool = True
    environment: str = ""
    """Which environment this target is, e.g. production / staging / lab.

    An optional label. A ``deny`` rule may scope itself to an environment
    (for example, refusing a tool only where ``environment: production``); a
    target that declares none is simply not matched by such a rule and is
    never refused for lacking a label. See :mod:`vmware_policy.environment`.
    """

    def get_password(self, target_name: str) -> str:
        """Retrieve password from environment variable.

        Convention: VMWARE_NSX_<TARGET>_PASSWORD
        where <TARGET> is upper-cased with hyphens replaced by underscores.
        """
        env_key = f"VMWARE_NSX_{target_name.upper().replace('-', '_')}_PASSWORD"
        pw = os.environ.get(env_key, "")
        if not pw:
            raise ConfigError(
                f"NSX password not found for target '{target_name}'. Set {env_key} "
                "in ~/.vmware-nsx/.env (chmod 600) or export it, then retry. "
                "'vmware-nsx init' writes that file for you."
            )
        return _decode_secret(pw)

    def get_username(self, target_name: str) -> str:
        """Retrieve username from environment variable, falling back to config.

        Convention: VMWARE_NSX_<TARGET>_USERNAME
        where <TARGET> is upper-cased with hyphens replaced by underscores.

        Mirrors :meth:`get_password` so a deployment injecting credentials from
        a secret store can externalise *both* halves of the pair. Like the
        password this is resolved on every call, never cached at load time: a
        rotated username has to take effect at the same moment as the rotated
        password, or the halves drift apart and authenticate as nobody.

        Unlike the password an unset variable is not an error — config.yaml
        always supplies a username — so it falls back to ``self.username``.
        The value is not ``b64:``-decoded; only ``*_PASSWORD`` keys are
        obfuscated at rest, and a username is not a secret.
        """
        env_key = f"VMWARE_NSX_{target_name.upper().replace('-', '_')}_USERNAME"
        return os.environ.get(env_key, "") or self.username


@dataclass(frozen=True)
class AppConfig:
    """Top-level application config."""

    targets: dict[str, TargetConfig] = ()  # type: ignore[assignment]
    default_target: str | None = None

    def get_target(self, name: str) -> TargetConfig | None:
        """Look up a target by name. Returns None if not found."""
        return self.targets.get(name)  # type: ignore[union-attr]

    def environment_for(self, name: str | None) -> str:
        """Return the environment declared by ``name``, or by the default target.

        An empty name means "the caller omitted --target", which resolves to
        ``default_target`` — the same target the connection layer would use, so
        policy and connection never disagree about which host is in play.
        Returns "" when the target is unknown or declares nothing.
        """
        target = self.get_target(name or self.default_target or "")
        return target.environment if target else ""

    def get_target_strict(self, name: str) -> TargetConfig:
        """Look up a target by name. Raises KeyError if not found."""
        cfg = self.get_target(name)
        if cfg is None:
            available = ", ".join(self.targets.keys())  # type: ignore[union-attr]
            raise KeyError(
                f"Target '{name}' not found. Available: {available}. Copy an exact "
                "name from that list, or add the target to ~/.vmware-nsx/config.yaml "
                "with 'vmware-nsx init'."
            )
        return cfg


def resolve_config_path(config_path: Path | None = None) -> Path:
    """Which config file this skill will read: explicit arg, env var, default.

    The single place that precedence lives. It used to be written out here and
    again in :func:`vmware_nsx.doctor.run_doctor`, and the doctor's copy had no
    env-var clause — so with ``VMWARE_NSX_CONFIG`` set it reported on a file the
    tools would never open, and passed (2026-08-30). Two copies of a rule do not
    disagree loudly; they disagree slowly (形态 #6).
    """
    if config_path is not None:
        return Path(config_path).expanduser()
    env_override = os.environ.get("VMWARE_NSX_CONFIG")
    # MCP clients pass env values verbatim, and the setup guides' snippets say
    # "~/.vmware-…/config.yaml" — unexpanded, that path never exists.
    return Path(env_override).expanduser() if env_override else CONFIG_FILE


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load config from YAML file, with env var overrides for passwords."""
    path = resolve_config_path(config_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}. Run 'vmware-nsx init' to create it "
            f"interactively, or copy config.example.yaml to {CONFIG_FILE} and edit "
            "the host and username."
        )

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if isinstance(raw, dict) and "read_only" in raw:
        _log.warning(
            "'read_only' in config is no longer honored (the skill-level read-only "
            "switch was removed in v1.8.7). To run this agent read-only, point it at "
            "a read-only vCenter/NSX service account (RBAC) — enforced at the "
            "platform. Remove the 'read_only' key to silence this warning."
        )

    targets: dict[str, TargetConfig] = {}
    for name, t in raw.get("targets", {}).items():
        targets[name] = TargetConfig(
            host=t["host"],
            username=t.get("username", "admin"),
            port=t.get("port", 443),
            verify_ssl=t.get("verify_ssl", True),
            environment=str(t.get("environment", "") or "").strip(),
        )

    default = raw.get("default_target")
    if default and default not in targets:
        _log.warning("default_target '%s' not found in targets, ignoring", default)
        default = None

    return AppConfig(
        targets=targets,
        default_target=default,
    )

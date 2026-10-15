"""NSX Manager REST API client with session management.

Uses httpx for HTTP communication. Authenticates via POST /api/session/create
with Basic Auth, then reuses X-XSRF-TOKEN for subsequent requests.

Supports both Policy API (/policy/api/v1/) and Management API (/api/v1/).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from vmware_policy.pool import SessionPool

from vmware_nsx.config import AppConfig, TargetConfig, load_config

_log = logging.getLogger("vmware-nsx.connection")

# Transient gateway statuses worth one automatic retry (the manager may be
# busy or a service may still be coming up). Only idempotent GETs are
# retried; 4xx client errors are NOT retried.
_TRANSIENT_STATUS = frozenset({502, 503, 504})
_RETRY_DELAY_SEC = 2.0

# Safety cap for paginated collection — search/filter beats dumping
# unbounded lists into agent context (family "search over list" rule).
_MAX_ITEMS = 1000


class CollectionTotal:
    """Sink for a paginated collection's ``result_count``.

    ``get_all`` stops as soon as its caller has enough rows, so the caller
    never sees the raw pages and cannot read the count itself. Passing a sink
    lets the count reach the result envelope, where a known total is what
    distinguishes a complete page from a possibly-truncated one — without the
    extra round trip ``get_count`` would cost.

    ``value`` stays ``None`` when the API omits ``result_count``.
    """

    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value: int | None = None


class NsxApiError(Exception):
    """An NSX Manager API call returned an error or failed to connect.

    Carries a teaching message (status + path + how to fix) so end users see
    an actionable line instead of a raw httpx traceback. ``status_code`` is
    None for transport/timeout failures (no HTTP response was received).
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        method: str | None = None,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.method = method
        self.path = path


def _is_tls_error(exc: Exception) -> bool:
    """Return True if *exc* (or a cause in its chain) is a TLS/cert failure.

    httpx wraps the underlying ssl.SSLError / ssl.SSLCertVerificationError in a
    ConnectError, so we walk __cause__/__context__ and also fall back to a text
    match on the message ("certificate verify failed", "ssl").
    """
    import ssl

    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, ssl.SSLError):
            return True
        text = str(cur).lower()
        if "certificate verify failed" in text or "ssl" in text or "tls" in text:
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def _hint_for_status(status_code: int) -> str:
    """Return a short, actionable remediation hint for an HTTP error status."""
    if status_code == 404:
        return (
            "No such resource — run the matching list tool (list_segments, "
            "list_tier1_gateways, list_nat_rules, list_static_routes, list_ip_pools) "
            "and copy an exact ID."
        )
    if status_code == 403:
        return (
            "Permission denied — this target's account lacks the NSX role for this "
            "path. Check the username in ~/.vmware-nsx/config.yaml."
        )
    if status_code == 401:
        return (
            "Authentication rejected after re-creating the session — check the "
            "password in ~/.vmware-nsx/.env and the username in config.yaml."
        )
    if status_code == 400:
        return "Bad request — check this call's arguments against the values its Args section allows."
    if status_code in _TRANSIENT_STATUS:
        return "NSX manager not ready — retry shortly, or run get_nsx_manager_status to check it."
    if status_code >= 500:
        return "Server-side error — retry shortly, or run get_nsx_manager_status to check cluster health."
    return "Check the request arguments and retry."


class NsxClient:
    """REST client for a single NSX Manager."""

    _target_name: str = ""
    """Config key this client was built from, e.g. ``prod-nsx``.

    Connection failures name this instead of the host they resolved to: the
    operator edits config by key, and the raw failure text (host:port,
    certificate subject) is not something ``_safe_error`` would redact. Declared
    at class level so instances built with ``__new__`` — the test doubles that
    skip ``__init__`` to avoid dialling out — still render a message.
    """

    def __init__(
        self, target: TargetConfig, password: str, username: str | None = None,
        *, target_name: str = "",
    ) -> None:
        self._target = target
        self._target_name = target_name
        self._password = password
        # Resolved by the caller (ConnectionManager) alongside the password so
        # both halves of the credential come from the same read; falls back to
        # the configured username for direct construction.
        self._username = username or target.username
        self._base_url = f"https://{target.host}:{target.port}"
        self._token: str | None = None


        # No client-level auth — credentials are sent via form body in
        # _create_session(); subsequent requests use session cookie + XSRF token.
        self._client = httpx.Client(
            base_url=self._base_url,
            verify=target.verify_ssl,
            timeout=30.0,
        )
        self._create_session()

    def _create_session(self) -> None:
        """Authenticate via form body and store the XSRF session token.

        NSX Manager's /api/session/create requires j_username and j_password
        as application/x-www-form-urlencoded body parameters.  Python's
        urllib.parse.urlencode encodes '!' → '%21' and ')' → '%29', but some
        NSX versions compare the raw encoded string against the stored password,
        causing spurious 403s for passwords that contain those characters.

        We construct the body manually using urllib.parse.quote() with an
        explicit safe set that preserves the characters curl passes literally
        (RFC 3986 unreserved set plus common sub-delimiters: ! ) * - . _ ~),
        so the on-wire representation matches what curl -d sends.
        """
        from urllib.parse import quote

        # Characters curl preserves unencoded in -d form data
        _SAFE = "!)*-._~"
        body = (
            "j_username="
            + quote(self._username, safe=_SAFE)
            + "&j_password="
            + quote(self._password, safe=_SAFE)
        )
        try:
            resp = self._client.post(
                "/api/session/create",
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            # A TLS/certificate failure (self-signed NSX Managers ship with
            # one) surfaces as a TransportError wrapping an SSL error. Teach
            # the verify_ssl fix rather than leaving a raw stack trace.
            tls_note = (
                " This looks like a self-signed certificate: set verify_ssl: false "
                "for this target."
                if _is_tls_error(exc)
                else ""
            )
            # The raw ``exc`` is deliberately not interpolated. ``_safe_error``
            # passes ``NsxApiError`` through verbatim and ``sanitize`` redacts
            # nothing, so a TLS failure would hand the agent the certificate
            # subject and a DNS failure the resolved host:port. The full chain
            # still reaches the operator: ``_safe_error`` logs it with
            # ``exc_info``, and ``from exc`` keeps the cause attached.
            # Authored text first, config key last — the cap truncates the tail.
            raise NsxApiError(
                "Could not connect to NSX Manager. Check host, port and verify_ssl "
                "for this target in ~/.vmware-nsx/config.yaml, then run "
                f"'vmware-nsx doctor'.{tls_note} Target: '{self._target_name}'",
                method="POST",
                path="/api/session/create",
            ) from exc
        if resp.status_code in (401, 403):
            raise NsxApiError(
                # Kept under 300 characters: ``_safe_error`` truncates there, and
                # an earlier 396-character version lost its closing remedy.
                f"NSX authentication rejected (HTTP {resp.status_code}). Re-run "
                "'vmware-nsx init' to reset this target's credentials, or edit them "
                "directly: password in ~/.vmware-nsx/.env under "
                "VMWARE_NSX_<TARGET_NAME_UPPER>_PASSWORD, username in "
                "~/.vmware-nsx/config.yaml. Special characters are safe (form-body auth).",
                status_code=resp.status_code,
                method="POST",
                path="/api/session/create",
            )
        if resp.status_code >= 400:
            raise NsxApiError(
                f"NSX session creation failed with HTTP {resp.status_code}. "
                "Check the username (~/.vmware-nsx/config.yaml) and password "
                "(~/.vmware-nsx/.env, VMWARE_NSX_<TARGET_NAME_UPPER>_PASSWORD) "
                "for this target.",
                status_code=resp.status_code,
                method="POST",
                path="/api/session/create",
            )
        self._token = resp.headers.get("x-xsrf-token")
        if not self._token:
            raise ConnectionError(
                f"NSX session creation on {self._target.host}:{self._target.port} succeeded "
                "but returned no X-XSRF-TOKEN header. Check that host and port in "
                "~/.vmware-nsx/config.yaml point at the NSX Manager itself — a proxy in "
                "front of it can strip the header. Then run 'vmware-nsx doctor'."
            )
        _log.info("NSX session created for %s", self._target.host)

    def _headers(self) -> dict[str, str]:
        """Request headers with XSRF token."""
        h = {"Accept": "application/json"}
        if self._token:
            h["X-XSRF-TOKEN"] = self._token
        return h

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        retries: int = 1,
    ) -> httpx.Response:
        """Send one request, recovering from auth and transient failures.

        Layered per the error-recovery contract: (1) transport/timeout
        failures and transient gateway statuses (502/503/504) are retried
        once after a short delay — but only for idempotent GETs; a write
        (POST/PUT/PATCH/DELETE) that timed out may already have been applied,
        so blind re-sends are dangerous. (2) a 401 triggers a single session
        re-creation, with the re-issued request inside the same protected
        loop so transport errors after re-auth are still translated. A 403
        is NOT re-authed — it is a real RBAC denial and must surface as a
        permission error. (3) any remaining error status is translated into
        an ``NsxApiError`` carrying a teaching message, so callers never
        surface a raw httpx traceback. 4xx client errors are NOT retried.
        """
        if method != "GET":
            retries = 0
        attempt = 0
        reauthed = False
        while True:
            try:
                resp = self._client.request(method, path, headers=self._headers(), params=params, json=json_data)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt < retries:
                    attempt += 1
                    time.sleep(_RETRY_DELAY_SEC)
                    continue
                # No raw ``exc``: see _create_session — it carries the resolved
                # host:port (and the certificate subject on a TLS failure), and
                # nothing downstream redacts it. Authored text first, the
                # unbounded path last so the 300-char cap eats context, not the
                # remedy.
                raise NsxApiError(
                    "NSX Manager could not connect — check host, port and network "
                    "reachability for this target in ~/.vmware-nsx/config.yaml, then "
                    f"run 'vmware-nsx doctor'. Target: '{self._target_name}' "
                    f"({method} {path})",
                    method=method,
                    path=path,
                ) from exc

            if resp.status_code == 401 and not reauthed:
                # Re-create the session once, then re-issue through the top
                # of the loop so the retry is covered by the same transport-
                # error handling (the `reauthed` flag bounds this to one).
                _log.info("Session expired on %s %s, re-authenticating...", method, path)
                self._create_session()
                reauthed = True
                continue

            if resp.status_code in _TRANSIENT_STATUS and attempt < retries:
                attempt += 1
                time.sleep(_RETRY_DELAY_SEC)
                continue

            if resp.status_code >= 400:
                raise NsxApiError(
                    # Remedy first, unbounded path last. The previous order led
                    # with "{method} {path}" and a comment claiming the message
                    # was short enough that ``_safe_error``'s 300-character cap
                    # could not eat the trailing remedy. That was false for real
                    # ids: a 404 on
                    # /policy/api/v1/infra/tier-1s/tier1-prod-edge/nat/USER/nat-rules/dnat-web-443
                    # measures 316 characters and loses the doctor line — the
                    # toy ids it was checked against (t1-x, r-x) fit at 296. The
                    # status code and the hint are bounded, so they lead; the
                    # path is the only expendable part and now truncates first.
                    f"NSX Manager returned HTTP {resp.status_code}. "
                    f"{_hint_for_status(resp.status_code)} "
                    "Run 'vmware-nsx doctor' to check this target. "
                    f"({method} {path})",
                    status_code=resp.status_code,
                    method=method,
                    path=path,
                )
            return resp

    def get(self, path: str, params: dict[str, Any] | None = None, *, retries: int = 1) -> dict:
        """Single GET request. Returns JSON response.

        Pass retries=0 for probes where an error status is itself the answer
        (e.g. is_alive reading a 503 as "not ready") to skip the back-off.
        """
        resp = self._request("GET", path, params=params, retries=retries)
        return resp.json() if resp.content else {}

    def get_all(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        max_items: int = _MAX_ITEMS,
        *,
        page_size: int | None = None,
        limit: int | None = None,
        total_sink: CollectionTotal | None = None,
    ) -> list[dict]:
        """Paginated GET. Follows cursor until enough results are collected.

        Callers should bound the query rather than draining the whole
        collection into agent context (family "search over list" rule):

        * ``page_size`` — sets the server-side per-page size, so each round
          trip returns at most this many results.
        * ``limit`` — stops following cursors once ``limit`` items have been
          collected. Hitting the requested ``limit`` is expected and silent.
        * ``max_items`` — a safety backstop (default 1000). Truncating here
          logs a warning, since it means the caller under-specified the query.
        * ``total_sink`` — receives the ListResult ``result_count`` carried by
          the pages already fetched, so a caller can state the collection size
          in its result envelope without the extra round trip ``get_count``
          would cost.

        When both ``page_size`` and ``limit`` are omitted, behaviour is
        unchanged: follow every cursor up to the ``max_items`` backstop.
        """
        all_results: list[dict] = []
        params = dict(params) if params else {}
        if page_size is not None:
            params["page_size"] = page_size
        while True:
            data = self.get(path, params=params)
            count = data.get("result_count")
            if total_sink is not None and isinstance(count, int):
                total_sink.value = count
            all_results.extend(data.get("results", []))
            # Requested limit reached — expected, no warning.
            if limit is not None and len(all_results) >= limit:
                return all_results[:limit]
            # Safety backstop reached — the caller should have filtered.
            if len(all_results) >= max_items:
                _log.warning(
                    "get_all(%s) hit the %d-item safety cap; results truncated. "
                    "Use a server-side filter or a limit to narrow the query.",
                    path,
                    max_items,
                )
                return all_results[:max_items]
            cursor = data.get("cursor")
            if not cursor:
                break
            params["cursor"] = cursor
        return all_results

    def get_count(
        self, path: str, params: dict[str, Any] | None = None
    ) -> int | None:
        """Return the server-reported total size of a paginated collection.

        Fetches a single minimal page (``page_size=1``) and reads the
        ListResult ``result_count`` field, so a caller can report an
        accurate total without draining the whole collection just to
        ``len()`` it. Returns None when the field is absent (older APIs);
        callers should fall back to the length of what they did fetch.
        """
        p = dict(params) if params else {}
        p["page_size"] = 1
        data = self.get(path, params=p)
        count = data.get("result_count")
        return count if isinstance(count, int) else None

    def post(self, path: str, json_data: dict[str, Any] | None = None) -> dict:
        """POST request for write operations."""
        resp = self._request("POST", path, json_data=json_data)
        return resp.json() if resp.content else {}

    def put(self, path: str, json_data: dict[str, Any]) -> dict:
        """PUT request (create or replace)."""
        resp = self._request("PUT", path, json_data=json_data)
        return resp.json() if resp.content else {}

    def patch(self, path: str, json_data: dict[str, Any]) -> dict:
        """PATCH request (partial update)."""
        resp = self._request("PATCH", path, json_data=json_data)
        return resp.json() if resp.content else {}

    def delete(self, path: str) -> None:
        """DELETE request."""
        self._request("DELETE", path)

    def is_alive(self) -> bool:
        """Check if the cached client + session are still usable.

        Probes a cheap Policy-API object readable by any role
        (GET /policy/api/v1/infra, the always-present infra root) instead of
        the old /api/v1/cluster/status Manager-API endpoint, which required
        high privileges — a least-privilege service account (which CLAUDE.md
        RECOMMENDS) got 403 there, and since is_alive() returns False on a
        403, every connect() tore down and rebuilt the session = connection
        churn on every command (踩坑 #21, mirroring VMware-NSX-Security).
        The infra root is preferred over /infra/domains/default because the
        default domain is not guaranteed to exist in every plain NSX-T
        deployment, whereas the infra root always is. A reachable manager
        returning 5xx is still "alive": the session works, the platform just
        isn't ready. Only auth failures (401/403) or transport errors mean
        the cached client is stale. retries=0 keeps the probe snappy.
        """
        try:
            self._request("GET", "/policy/api/v1/infra", retries=0)
            return True
        except NsxApiError as exc:
            return exc.status_code is not None and exc.status_code not in (401, 403)
        except Exception:
            return False

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()


class ConnectionManager:
    """Manages connections to multiple NSX Manager targets.

    Clients come from a per-target :class:`~vmware_policy.pool.SessionPool`
    (HLD §16 D-13(2)). An MCP call on a network transport holds one client for
    its whole body, so two calls never share a session (a client re-creates its
    XSRF session in place on a 401). Outside a call (CLI, stdio) each target
    keeps one cached client, as before. Keep in sync with VMware-NSX-Security (踩坑 #21).
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._pool: SessionPool[NsxClient] = SessionPool(
            "vmware-nsx",
            create=self._new_client,
            is_alive=lambda client: client.is_alive(),
            # Closing the httpx client is all a stale client needs: NSX
            # sessions expire on the manager, and close() never dials out.
            close=lambda client: client.close(),
        )

    @classmethod
    def from_config(cls, config: AppConfig | None = None) -> ConnectionManager:
        """Create a ConnectionManager from config, loading defaults if needed."""
        cfg = config or load_config()
        return cls(cfg)

    def connect(self, target_name: str | None = None) -> NsxClient:
        """Get or create an NsxClient for the specified target."""
        name = target_name or self._config.default_target
        if not name:
            configured = ", ".join(self._config.targets) or "none"
            raise ValueError(
                "No target specified and no default_target set in "
                f"~/.vmware-nsx/config.yaml. Pass an explicit target (configured: "
                f"{configured}) or set default_target in config.yaml — "
                "'vmware-nsx init' does both."
            )
        if self._config.get_target(name) is None:
            available = ", ".join(self._config.targets.keys())
            raise ValueError(
                f"Target '{name}' not found. Available: {available}. Copy an exact "
                "name from that list, or add the target to ~/.vmware-nsx/config.yaml "
                "with 'vmware-nsx init'."
            )
        return self._pool.get(name)

    def _new_client(self, name: str) -> NsxClient:
        target_cfg = self._config.get_target(name)
        if target_cfg is None:  # connect() checked; the config is not reloaded
            raise ValueError(f"Target '{name}' not found.")
        # Resolve both halves of the credential together — a username left
        # behind by a rotation would pair with the new password and fail.
        password = target_cfg.get_password(name)
        username = target_cfg.get_username(name)
        return NsxClient(target_cfg, password, username, target_name=name)

    def disconnect(self, target_name: str) -> None:
        """Close the target's clients (busy ones when their calls end)."""
        self._pool.discard(target_name)

    def disconnect_all(self) -> None:
        """Disconnect from all targets."""
        self._pool.close_all()

    def list_targets(self) -> list[str]:
        """List available target names."""
        return list(self._config.targets.keys())

    def list_connected(self) -> list[str]:
        """List currently connected target names."""
        return self._pool.keys()

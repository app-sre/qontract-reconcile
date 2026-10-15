"""LDAP API client with hook system for metrics, logging, and latency tracking."""

from __future__ import annotations

import contextvars
import hashlib
import json
import re
import string
import time
import types
from collections import defaultdict
from collections.abc import Collection, Generator, Iterable
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from operator import itemgetter
from typing import Self
from urllib.parse import urlparse

import structlog
from ldap3 import NONE, ROUND_ROBIN, SAFE_SYNC, Connection, Server, ServerPool
from ldap3.core.exceptions import (
    LDAPAuthMethodNotSupportedResult,
    LDAPBindError,
    LDAPBusyResult,
    LDAPCertificateError,
    LDAPCommunicationError,
    LDAPInappropriateAuthenticationResult,
    LDAPInvalidCredentialsResult,
    LDAPMaximumRetriesError,
    LDAPResponseTimeoutError,
    LDAPSessionTerminatedByServerError,
    LDAPSocketCloseError,
    LDAPSocketOpenError,
    LDAPSocketReceiveError,
    LDAPSocketSendError,
    LDAPStartTLSError,
    LDAPUnavailableResult,
)
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import parse_dn
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import Hooks, RetryConfig, invoke_with_hooks, with_hooks
from qontract_utils.ldap_api.models import LdapGroup, LdapUser
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API

logger = structlog.get_logger(__name__)

_DEFAULT_TIMEOUT = 30
_UNKNOWN_LDAP_ERROR = 99999

# Prometheus metrics
ldap_request = Counter(
    "qontract_reconcile_external_api_ldap_requests_total",
    "Total number of LDAP requests",
    ["method"],
)

ldap_request_duration = Histogram(
    "qontract_reconcile_external_api_ldap_request_duration_seconds",
    "LDAP request duration in seconds",
    ["method"],
    buckets=DEFAULT_BUCKETS_EXTERNAL_API,
)

ldap_quorum_mismatch = Counter(
    "qontract_reconcile_external_api_ldap_quorum_mismatch_total",
    "LDAP quorum mismatches detected between replicas",
    ["method"],
)

# Local storage for latency tracking (tuple stack to support nested calls)
_latency_tracker: contextvars.ContextVar[tuple[float, ...]] = contextvars.ContextVar(
    f"{__name__}.latency_tracker", default=()
)


class LdapApiError(Exception):
    """Raised when an LDAP operation fails."""


class LdapQuorumError(LdapApiError):
    """Raised when replicas disagree on a query result, or quorum cannot be reached.

    Not a transient/retryable failure (not in `_LDAP_FAILOVER_ERRORS`): replica
    disagreement is a data integrity problem to surface, not a connection
    issue to retry past.
    """


@dataclass(frozen=True)
class LdapApiCallContext:
    """Context information passed to API call hooks.

    Attributes:
        method: API method name (e.g., "get_users", "get_group_members")
    """

    method: str


def _metrics_hook(context: LdapApiCallContext) -> None:
    """Built-in Prometheus metrics hook."""
    ldap_request.labels(context.method).inc()


def _latency_start_hook(_context: LdapApiCallContext) -> None:
    """Built-in hook to start latency measurement."""
    _latency_tracker.set((*_latency_tracker.get(), time.perf_counter()))


def _latency_end_hook(context: LdapApiCallContext) -> None:
    """Built-in hook to record latency measurement."""
    stack = _latency_tracker.get()
    if not stack:
        return
    start_time = stack[-1]
    _latency_tracker.set(stack[:-1])
    duration = time.perf_counter() - start_time
    ldap_request_duration.labels(context.method).observe(duration)


def _request_log_hook(context: LdapApiCallContext) -> None:
    """Built-in hook for logging API requests."""
    logger.debug("LDAP request", method=context.method)


# Replica failures include TLS/bind failures; query/configuration errors are fatal.
_LDAP_FAILOVER_ERRORS = (
    LDAPCommunicationError,
    LDAPSocketOpenError,
    LDAPSocketReceiveError,
    LDAPSocketSendError,
    LDAPSocketCloseError,
    LDAPSessionTerminatedByServerError,
    LDAPResponseTimeoutError,
    LDAPMaximumRetriesError,
    LDAPStartTLSError,
    LDAPCertificateError,
    LDAPBindError,
    LDAPInvalidCredentialsResult,
    LDAPInappropriateAuthenticationResult,
    LDAPAuthMethodNotSupportedResult,
    LDAPBusyResult,
    LDAPUnavailableResult,
)

_LDAP_RETRY_CONFIG = RetryConfig(
    on=_LDAP_FAILOVER_ERRORS,
    attempts=3,
    timeout=5.0,
    wait_initial=0.5,
    wait_max=5.0,
    wait_jitter=1.0,
)


# GitHub usernames: alphanumerics and single hyphens, max 39 chars. We only
# validate the character set here (not the full hyphen rules) - a value that
# survives this is safe to compare against real org members.
_GITHUB_USERNAME_RE = re.compile(r"[A-Za-z0-9-]{1,39}")

# Hosts whose first path segment is a GitHub user login. `*.github.io` (Pages),
# custom domains and `gist.github.com` are intentionally excluded: their first
# path segment is not reliably a username.
_GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})

# 389 Directory Server caps a single search response at ~2000 entries by
# default and returns LDAP_SIZELIMIT_EXCEEDED past that. Broad searches must
# follow the RFC 2696 paged-results cookie until the server signals no more
# pages. `_PAGED_RESULTS_CONTROL` is the paged-results control OID.
_LDAP_PAGE_SIZE = 1000
_PAGED_RESULTS_CONTROL = "1.2.840.113556.1.4.319"


def _parse_github_login(social_url: str) -> str | None:
    """Extract a GitHub login from a single `rhatSocialURL` attribute value.

    Values have the form ``<Social>-><URL>`` (e.g.
    ``Github->http://github.com/chassing``). Only a *bare* profile URL -
    ``github.com/<login>`` with exactly one path segment - establishes a login.
    Repo / sub-path URLs (``github.com/<owner>/<repo>``) are rejected: their
    first segment is not reliably the linking user (it may be an organization
    they belong to or another user's repository they contribute to), so trusting
    it would attribute someone else's login to this user. A user who owns a repo
    also links their bare profile, so no genuine login is lost.

    Returns None for any non-GitHub label, non-github.com host (``*.github.io``
    Pages, gist, custom domains), multi-segment path, or empty/malformed login.
    The login is returned with its original casing - callers normalise for
    comparison.
    """
    label, sep, url = social_url.partition("->")
    if not sep or label.strip().lower() != "github":
        return None

    parsed = urlparse(url.strip().rstrip("\x00").strip())
    if parsed.hostname not in _GITHUB_HOSTS:
        return None

    segments = [
        cleaned
        for raw in parsed.path.split("/")
        if (cleaned := raw.strip().rstrip("\x00").strip())
    ]
    if len(segments) != 1:
        return None

    segment = segments[0]
    if not _GITHUB_USERNAME_RE.fullmatch(segment):
        return None
    return segment


def _get_cn_from_dn(dn: str) -> str:
    """Extract CN value from a DN string."""
    rdn = parse_dn(dn)[0]
    if rdn[0].lower() != "cn":
        raise LdapApiError(
            f"Expected CN as first RDN component, got {rdn[0]!r} in {dn!r}"
        )
    return rdn[1]


_HEX_DIGITS = frozenset(string.hexdigits)


def _decode_dn_value(value: str) -> str:
    r"""Decode RFC 4514 escape sequences in a DN attribute value.

    parse_dn() returns attribute values with escapes intact, and a literal
    special character can legitimately be spelled either way (e.g. a comma as
    `\\,` or as the hex-pair escape `\\2C`) - comparing the raw escaped text
    would treat two semantically-identical values as different. Collects
    every decoded byte (literal characters, `\\c`-escaped literals, and
    `\\XX` hex-escaped bytes) into one buffer and UTF-8 decodes it once at the
    end, so a multi-byte character split across consecutive hex escapes is
    reassembled correctly.
    """
    raw = bytearray()
    i = 0
    n = len(value)
    while i < n:
        c = value[i]
        if (
            c == "\\"
            and i + 2 < n
            and value[i + 1] in _HEX_DIGITS
            and value[i + 2] in _HEX_DIGITS
        ):
            raw.append(int(value[i + 1 : i + 3], 16))
            i += 3
        elif c == "\\" and i + 1 < n:
            raw.extend(value[i + 1].encode())
            i += 2
        else:
            raw.extend(c.encode())
            i += 1
    return raw.decode()


def _canonicalize_dn(dn: str) -> tuple[tuple[str, str, str], ...]:
    r"""Build a case-insensitive canonical form of a DN.

    LDAP attribute type names are always case-insensitive, and DN-syntax
    attribute values (e.g. the `cn` RDNs used throughout this module) are too
    for any directory using case-insensitive matching rules - comparing raw
    DN strings can silently miss semantically-identical DNs that differ only
    in case.

    The separator returned by parse_dn (the third tuple element) must be kept
    as part of the key: it is `+` between attribute-value pairs within the
    same multi-valued RDN and `,` (or empty, at the end) between separate
    RDNs. Dropping it would make e.g. `cn=admins+ou=groups,dc=...` (one RDN)
    indistinguishable from `cn=admins,ou=groups,dc=...` (two RDNs).

    Attribute values must be unescaped before lowercasing: two DNs can encode
    the same literal value with different RFC 4514 escape spellings (e.g. a
    comma as `\\,` or `\\2C`), which parse_dn() does not normalize.
    """
    return tuple(
        (
            attr_type.strip().lower(),
            _decode_dn_value(attr_value.strip()).lower(),
            separator,
        )
        for attr_type, attr_value, separator in parse_dn(dn)
    )


@with_hooks(
    hooks=Hooks(
        pre_hooks=[_metrics_hook, _request_log_hook, _latency_start_hook],
        post_hooks=[_latency_end_hook],
    )
)
class LdapApi:
    """Stateless LDAP client using ldap3 with authenticated bind.

    Layer 1 (Pure Communication) per ADR-014.
    Uses hook system (ADR-006) for metrics, logging, latency.

    Supports both anonymous and authenticated (FreeIPA) binds.
    Use as a context manager to manage connection lifecycle.
    All searches use RFC 2696 pagination and raise on any page failure,
    rather than returning partial lookup results.

    Args:
        server_urls: Non-empty list of LDAP replica URLs
        base_dn: Base DN for searches (e.g., "dc=example,dc=com")
        bind_dn: Service account DN for authenticated bind (None for anonymous)
        bind_password: Service account password (None for anonymous)
        start_tls: Enable STARTTLS before binding
        timeout: Per-connection and receive timeout in seconds
        quorum_count: Number of replicas that must agree on a search result
            before it is trusted (see "Quorum verification" in README.md).
            A reachable-but-under-replicated replica can return a "successful"
            response that is silently incomplete or stale; comparing results
            across replicas catches that. 1 disables verification. Falls back
            to 1 (with a warning) if fewer server_urls are configured than
            requested.
        hooks: Optional custom hooks merged with built-in hooks (ADR-006)
    """

    # Set by @with_hooks decorator
    _hooks: Hooks

    def __init__(
        self,
        server_urls: Collection[str],
        base_dn: str,
        bind_dn: str | None = None,
        bind_password: str | None = None,
        *,
        start_tls: bool = True,
        timeout: int = _DEFAULT_TIMEOUT,
        quorum_count: int = 1,
        hooks: Hooks | None = None,  # ruff: ignore[unused-method-argument] - Handled by @with_hooks decorator
    ) -> None:
        if not server_urls or any(not url.strip() for url in server_urls):
            raise ValueError("LDAP server_urls must contain at least one non-empty URL")
        if timeout <= 0:
            raise ValueError("LDAP timeout must be positive")
        if quorum_count < 1:
            raise ValueError("LDAP quorum_count must be at least 1")
        self.base_dn = base_dn
        self._start_tls = start_tls
        self._connected = False
        self._server_urls = list(server_urls)
        if quorum_count > 1 and len(self._server_urls) < quorum_count:
            logger.warning(
                "LDAP quorum_count exceeds configured replicas - disabling quorum verification",
                quorum_count=quorum_count,
                server_count=len(self._server_urls),
            )
            self._quorum_count = 1
        else:
            self._quorum_count = quorum_count
        self._connection = Connection(
            server=ServerPool(
                servers=[
                    Server(url, get_info=NONE, connect_timeout=timeout)
                    for url in server_urls
                ],
                pool_strategy=ROUND_ROBIN,
                active=False,
                exhaust=False,
            ),
            user=bind_dn,
            password=bind_password,
            client_strategy=SAFE_SYNC,
            receive_timeout=timeout,
            raise_exceptions=True,
        )
        attempts = max(_LDAP_RETRY_CONFIG.attempts, len(server_urls))
        self._hooks = Hooks(
            pre_hooks=self._hooks.pre_hooks,
            post_hooks=self._hooks.post_hooks,
            error_hooks=self._hooks.error_hooks,
            retry_hooks=self._hooks.retry_hooks,
            retry_config=self._hooks.retry_config
            or replace(
                _LDAP_RETRY_CONFIG,
                attempts=attempts,
                timeout=attempts * (4 * timeout + _LDAP_RETRY_CONFIG.wait_max),
            ),
        )

    def __enter__(self) -> Self:
        """Own cleanup; connect lazily inside the hook-controlled lookup."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        self._disconnect()

    def _disconnect(self) -> None:
        self._connected = False
        with suppress(LDAPCommunicationError):
            self._connection.unbind()
        if socket := self._connection.socket:
            with suppress(OSError):
                socket.close()
            self._connection.socket = None

    @contextmanager
    def _connection_attempt(self) -> Generator[None]:
        try:
            self._connect()
            yield
        except _LDAP_FAILOVER_ERRORS:
            logger.warning(
                "LDAP replica lookup failed",
                server=self._connection.server.host,
            )
            self._disconnect()
            # ldap3 suppresses failed IPs independently of ServerPool.active;
            # hooks, not that cache, own whether another socket attempt is due.
            self._connection.server.reset_availability()
            raise

    def _connect(self) -> None:
        if self._connected:
            return
        self._connection.open()
        if self._start_tls and not self._connection.server.ssl:
            self._connection.start_tls()
            if not self._connection.tls_started:
                raise LDAPStartTLSError("LDAP STARTTLS did not establish TLS")
        self._connection.bind()
        if not self._connection.bound:
            raise LDAPBindError("LDAP bind did not authenticate the connection")
        self._connected = True

    @staticmethod
    def _check_ldap_response(status: dict) -> None:
        """Check LDAP response status and raise LdapApiError on failure."""
        if (error_code := status.get("result", _UNKNOWN_LDAP_ERROR)) != 0:
            error_desc = status.get("description", "unknown error")
            raise LdapApiError(
                f"LDAP operation failed (error {error_code}: {error_desc})"
            )

    @staticmethod
    def _run_paged_search(
        connection: Connection,
        search_base: str,
        search_filter: str,
        attributes: list[str],
    ) -> list[dict]:
        """Run an LDAP search across all pages, following the paged cookie.

        Uses RFC 2696 paged results so broad searches survive the server's
        per-response size limit (389 DS defaults to ~2000 entries). Aggregates
        the entries from every page. Takes an explicit connection so the same
        logic serves both the primary query and quorum verification queries.
        """
        entries: list[dict] = []
        cookie: bytes | None = None
        while True:
            _, status, page, _ = connection.search(
                search_base,
                search_filter,
                attributes=attributes,
                paged_size=_LDAP_PAGE_SIZE,
                paged_cookie=cookie,
            )
            LdapApi._check_ldap_response(status)
            entries.extend(page)
            cookie = (
                status.get("controls", {})
                .get(_PAGED_RESULTS_CONTROL, {})
                .get("value", {})
                .get("cookie")
            )
            if not cookie:
                break
        return entries

    @staticmethod
    def _result_set_hash(entries: list[dict]) -> str:
        """Hash a complete LDAP result set for quorum comparison.

        Sorts entries by DN and multi-valued attribute values within each
        entry, since LDAP guarantees neither entry order nor the order of
        values within a multi-valued attribute - two replicas holding
        identical data could otherwise hash differently.
        """
        normalized = [
            {
                "dn": entry["dn"],
                "attributes": {
                    name: sorted(values) for name, values in entry["attributes"].items()
                },
            }
            for entry in sorted(entries, key=itemgetter("dn"))
        ]
        return hashlib.sha256(
            json.dumps(normalized, sort_keys=True).encode()
        ).hexdigest()

    def _verify_quorum(
        self,
        primary_entries: list[dict],
        search_base: str,
        search_filter: str,
        attributes: list[str],
        *,
        method_name: str,
    ) -> None:
        """Re-run a search on other replicas and require them to agree.

        Catches a replica that is reachable and returns a "successful"
        response that is nevertheless silently incomplete or stale (e.g. due
        to a broken replication agreement) - a failure mode `ServerPool`
        failover cannot detect, since no exception is raised. A single
        disagreeing replica fails the whole lookup closed rather than
        guessing which replica is right.
        """
        primary_hash = self._result_set_hash(primary_entries)
        primary_host = self._connection.server.host
        confirmations_needed = self._quorum_count - 1
        confirmed = 0

        for _ in range(len(self._server_urls)):
            self._disconnect()
            try:
                with self._connection_attempt():
                    verify_host = self._connection.server.host
                    if verify_host == primary_host:
                        continue
                    verify_entries = self._run_paged_search(
                        self._connection, search_base, search_filter, attributes
                    )
            except (*_LDAP_FAILOVER_ERRORS, LdapApiError):
                logger.warning(
                    "LDAP quorum: verification replica unreachable",
                    method=method_name,
                    server=self._connection.server.host,
                )
                continue

            if primary_hash != self._result_set_hash(verify_entries):
                ldap_quorum_mismatch.labels(method=method_name).inc()
                raise LdapQuorumError(
                    f"LDAP quorum mismatch on {method_name}: {primary_host} and "
                    f"{verify_host} returned different results for the same "
                    "query - replicas may be out of sync (missing/extra entries "
                    "or stale attribute values)"
                )
            confirmed += 1
            if confirmed >= confirmations_needed:
                return

        raise LdapQuorumError(
            f"Cannot achieve quorum for {method_name}: only {confirmed} of "
            f"{confirmations_needed} required replica confirmation(s) succeeded"
        )

    def _paged_search(
        self,
        search_base: str,
        search_filter: str,
        attributes: list[str],
        *,
        method_name: str = "",
    ) -> list[dict]:
        """Run the primary paged search, then verify it against quorum if configured."""
        with self._connection_attempt():
            entries = self._run_paged_search(
                self._connection, search_base, search_filter, attributes
            )
        if self._quorum_count > 1:
            self._verify_quorum(
                entries, search_base, search_filter, attributes, method_name=method_name
            )
        return entries

    def get_users(self, usernames: Iterable[str]) -> list[LdapUser]:
        """Check which usernames exist in LDAP.

        Only searches the active users container (cn=users,cn=accounts under
        base_dn): FreeIPA doesn't hard-delete deprovisioned users, it moves
        them out of this container into a separate preserved-users container.
        Accounts merely disabled via `ipa user-disable` (nsAccountLock=TRUE)
        stay active and remain in this container, so they are still correctly
        reported as existing.

        Args:
            usernames: Usernames to check

        Returns:
            List of LdapUser models for usernames that exist in LDAP

        Raises:
            LdapApiError: If the LDAP search fails
        """
        return self._get_users(tuple(usernames))

    @invoke_with_hooks(lambda: LdapApiCallContext(method="get_users"))
    def _get_users(self, usernames: Collection[str]) -> list[LdapUser]:
        if not usernames:
            return []
        user_filter = "".join(f"(uid={escape_filter_chars(u)})" for u in usernames)
        results = self._paged_search(
            f"cn=users,cn=accounts,{self.base_dn}",
            f"(&(objectclass=person)(|{user_filter}))",
            attributes=["uid"],
            method_name="get_users",
        )

        return [LdapUser(username=r["attributes"]["uid"][0]) for r in results]

    @invoke_with_hooks(
        lambda: LdapApiCallContext(method="get_group_members"),
    )
    def get_group_members(self, groups_dns: Collection[str]) -> list[LdapGroup]:
        """Get members of the specified LDAP groups.

        Attention: groups_dns must be full DNs (e.g., "cn=group1,ou=groups,dc=example,dc=com") as returned by the LDAP "memberOf" attribute.
        """
        if not groups_dns:
            return []

        member_filter = "".join(
            f"(memberOf={escape_filter_chars(dn)})" for dn in sorted(groups_dns)
        )
        # FreeIPA groups can nest other groups or Kerberos service entries as
        # members; restricting to person entries excludes those, matching
        # get_users' filter pattern.
        search_filter = f"(&(objectclass=person)(|{member_filter}))"

        users = self._paged_search(
            self.base_dn,
            search_filter,
            attributes=["uid", "cn", "memberOf"],
            method_name="get_group_members",
        )

        # Map each requested DN's canonical form back to the exact string the
        # caller passed in, so a server-returned memberOf value that differs
        # only in case still matches - a raw string comparison here would
        # silently drop members whose DN representation doesn't match
        # byte-for-byte, even though it's the same DN.
        requested_by_canonical = {_canonicalize_dn(dn): dn for dn in groups_dns}

        groups_and_members: dict[str, dict[str, LdapUser]] = defaultdict(dict)
        for u in users:
            if not (uid_values := u["attributes"].get("uid")):
                # A nested group's own entry has memberOf pointing at its
                # parent and can still match despite the objectclass=person
                # filter in some directory configurations - skip it rather
                # than crash resolution for the group's real (user) members.
                continue
            uid = uid_values[0]
            if not (names := u["attributes"].get("cn")):
                raise LdapApiError(f"LDAP user {uid} has no cn attribute")
            member = LdapUser(username=uid, name=names[0])
            for member_of in u["attributes"]["memberOf"]:
                requested_dn = requested_by_canonical.get(_canonicalize_dn(member_of))
                if requested_dn is not None:
                    groups_and_members[requested_dn].setdefault(uid, member)

        return [
            LdapGroup(
                cn=_get_cn_from_dn(dn),
                dn=dn,
                members=frozenset(members.values()),
            )
            for dn, members in groups_and_members.items()
        ]

    @invoke_with_hooks(
        lambda: LdapApiCallContext(method="check_groups_exist"),
    )
    def check_groups_exist(self, group_cns: Collection[str]) -> set[str]:
        """Return the subset of the given group CNs that exist in LDAP.

        Searches the groups container directly by CN, independent of
        membership. Used to distinguish a confirmed-empty group (exists,
        zero members) from an unresolved one (CN not found) - both look
        identical as "no entry" from get_group_members alone, since that
        method only ever learns about a group by finding a member pointing
        at it via memberOf.

        Args:
            group_cns: Short group CNs to check (e.g. "my-ldap-group")

        Returns:
            The subset of group_cns that exist as group entries in LDAP

        Raises:
            LdapApiError: If the LDAP search fails
        """
        if not group_cns:
            return set()

        cn_filter = "".join(f"(cn={escape_filter_chars(cn)})" for cn in group_cns)
        results = self._paged_search(
            f"cn=groups,cn=accounts,{self.base_dn}",
            f"(|{cn_filter})",
            attributes=["cn"],
            method_name="check_groups_exist",
        )

        return {r["attributes"]["cn"][0] for r in results}

    @invoke_with_hooks(
        lambda: LdapApiCallContext(method="get_github_usernames"),
    )
    def get_github_usernames(self) -> dict[str, list[str]]:
        """Build a GitHub-login -> LDAP uid(s) map from `rhatSocialURL`.

        Searches the active users container for entries whose `rhatSocialURL`
        holds a bare `Github->...github.com/<login>` value and groups the parsed
        GitHub login to every uid that claims it. Values that are not bare
        github.com user URLs are skipped (see `_parse_github_login`).

        Login keys are lowercased (GitHub logins are case-insensitive) and each
        maps to the sorted list of distinct uids seen for it. This layer only
        extracts data: a login claimed by more than one uid is *not* resolved
        here - deciding what to do with such ambiguity is the caller's policy,
        applied to the specific logins it requested rather than to the whole
        directory (see `LdapWorkspaceClient.resolve_github_usernames`).

        The search is paged (RFC 2696) so it survives the directory server's
        per-response size limit - the broad filter can match more entries than
        389 DS returns in a single response.

        Returns:
            Mapping of lowercased GitHub login to the sorted list of LDAP uids
            (org_usernames) that claim it

        Raises:
            LdapApiError: If the LDAP search fails
        """
        results = self._paged_search(
            f"cn=users,cn=accounts,{self.base_dn}",
            "(&(objectclass=person)(rhatSocialURL=Github->*github.com/*))",
            attributes=["uid", "rhatSocialURL"],
            method_name="get_github_usernames",
        )

        by_login: dict[str, set[str]] = defaultdict(set[str])
        for r in results:
            attributes = r["attributes"]
            uid = attributes["uid"][0]
            for value in attributes.get("rhatSocialURL", []):
                if login := _parse_github_login(value):
                    by_login[login.lower()].add(uid)

        return {login: sorted(uids) for login, uids in by_login.items()}

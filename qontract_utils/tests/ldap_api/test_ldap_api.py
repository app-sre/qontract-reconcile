"""Tests for LDAP API client (Layer 1)."""

from __future__ import annotations

import socket

# ruff: file-ignore[unused-function-argument]
from collections.abc import Generator
from unittest.mock import MagicMock, call, patch

import pytest
from ldap3 import ROUND_ROBIN, Connection
from ldap3.core.exceptions import (
    LDAPCertificateError,
    LDAPInvalidCredentialsResult,
    LDAPInvalidFilterError,
    LDAPSocketOpenError,
    LDAPSocketReceiveError,
    LDAPStartTLSError,
)
from ldap3.strategy.base import BaseStrategy
from pydantic import ValidationError
from pytest_mock import MockerFixture
from qontract_utils.hooks import Hooks
from qontract_utils.ldap_api.api import (
    _LDAP_PAGE_SIZE,
    _PAGED_RESULTS_CONTROL,
    LdapApi,
    LdapApiCallContext,
    LdapApiError,
    LdapQuorumError,
    _parse_github_login,
)
from qontract_utils.ldap_api.models import LdapGroup, LdapUser


@pytest.fixture
def mock_ldap3() -> Generator[MagicMock]:
    """Mock ldap3 module."""
    with (
        patch("qontract_utils.ldap_api.api.Server") as mock_server,
        patch("qontract_utils.ldap_api.api.ServerPool") as mock_pool,
        patch("qontract_utils.ldap_api.api.Connection") as mock_connection,
    ):
        # Yield a namespace with both mocks
        mock = MagicMock()
        mock.server = mock_server
        mock.pool = mock_pool
        mock.connection_cls = mock_connection
        mock.connection = mock_connection.return_value
        mock.connection.server = mock_server.return_value
        mock.connection.server.ssl = False
        mock.connection.tls_started = True
        mock.connection.bound = True
        mock.connection.socket = None
        mock.connection.search.return_value = (True, {"result": 0}, [], None)
        yield mock


@pytest.fixture
def ldap_api(mock_ldap3: MagicMock) -> LdapApi:
    """Create LdapApi with mocked ldap3."""
    return LdapApi(
        server_urls=["ldap://ldap.example.com"],
        base_dn="dc=example,dc=com",
        bind_dn="uid=svc-account,cn=users,dc=example,dc=com",
        bind_password="secret",
    )


@pytest.fixture
def ldap_api_anonymous(mock_ldap3: MagicMock) -> LdapApi:
    """Create LdapApi with anonymous bind."""
    return LdapApi(
        server_urls=["ldap://ldap.example.com"],
        base_dn="dc=example,dc=com",
    )


# --- Constructor ---


@pytest.mark.parametrize("replica_count", [1, 2])
@pytest.mark.usefixtures("enable_retry")
def test_retry_reopens_real_candidate_addresses_after_pool_wrap(
    mocker: MockerFixture, replica_count: int
) -> None:
    """Socket failures must not suppress later hook retries of the same address."""
    tcp_socket = mocker.Mock(spec=socket.socket)
    tcp_socket.family = socket.AF_INET
    tcp_socket.connect.side_effect = [
        *[ConnectionRefusedError("connection refused") for _ in range(replica_count)],
        None,
    ]
    mocker.patch(
        "ldap3.core.server.socket.getaddrinfo",
        return_value=[
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("192.0.2.10", 389),
            )
        ],
    )
    mocker.patch("ldap3.strategy.base.socket.socket", return_value=tcp_socket)
    mocker.patch("ldap3.core.pooling.randint", return_value=replica_count - 1)

    def start_tls(connection: Connection) -> None:
        connection.tls_started = True

    def bind(connection: Connection) -> None:
        connection.bound = True

    mocker.patch(
        "ldap3.core.connection.Connection.start_tls",
        autospec=True,
        side_effect=start_tls,
    )
    mocker.patch(
        "ldap3.core.connection.Connection.bind", autospec=True, side_effect=bind
    )
    mocker.patch(
        "ldap3.core.connection.Connection.search",
        return_value=(
            True,
            {"result": 0},
            [{"attributes": {"uid": ["alice"]}}],
            None,
        ),
    )
    api = LdapApi(
        server_urls=[
            f"ldap://replica-{index}.example.com" for index in range(replica_count)
        ],
        base_dn="dc=example,dc=com",
    )
    with api:
        assert api.get_users(["alice"]) == [LdapUser(username="alice")]
    assert tcp_socket.connect.call_count == replica_count + 1


@pytest.fixture
def replica_api(mocker: MockerFixture) -> LdapApi:
    """Use the real pool and connection with all network operations mocked."""

    def open_connection(strategy: BaseStrategy) -> None:
        connection = strategy.connection
        connection.server = connection.server_pool.get_server(connection)

    def start_tls(connection: Connection) -> None:
        connection.tls_started = True

    def bind(connection: Connection) -> None:
        connection.bound = True

    def unbind(connection: Connection) -> None:
        connection.bound = False
        connection.tls_started = False

    mocker.patch(
        "ldap3.strategy.sync.SyncStrategy.open",
        autospec=True,
        side_effect=open_connection,
    )
    mocker.patch(
        "ldap3.core.connection.Connection.start_tls",
        autospec=True,
        side_effect=start_tls,
    )
    mocker.patch(
        "ldap3.core.connection.Connection.bind", autospec=True, side_effect=bind
    )
    mocker.patch(
        "ldap3.core.connection.Connection.unbind", autospec=True, side_effect=unbind
    )
    mocker.patch("ldap3.core.pooling.randint", return_value=1)
    mocker.patch(
        "ldap3.core.server.Server.check_availability",
        side_effect=AssertionError("TCP prechecks must be disabled"),
    )
    mocker.patch(
        "ldap3.core.connection.Connection.search",
        return_value=(True, {"result": 0}, [{"attributes": {"uid": ["alice"]}}], None),
    )
    return LdapApi(
        server_urls=["ldap://replica-a.example.com", "ldap://replica-b.example.com"],
        base_dn="dc=example,dc=com",
        bind_dn="uid=svc,dc=example,dc=com",
        bind_password="secret",
    )


def test_replica_pool_disables_tcp_prechecks(replica_api: LdapApi) -> None:
    pool = replica_api._connection.server_pool
    assert pool is not None
    assert pool.strategy == ROUND_ROBIN
    assert pool.active is False
    assert pool.exhaust is False
    assert [server.host for server in pool] == [
        "replica-a.example.com",
        "replica-b.example.com",
    ]
    assert all(server.connect_timeout == 30 for server in pool)


@pytest.mark.parametrize(
    ("operation", "error"),
    [
        ("open", LDAPSocketOpenError("connection refused")),
        ("start_tls", LDAPStartTLSError("TLS handshake failed")),
        ("start_tls", LDAPCertificateError("certificate rejected")),
        (
            "bind",
            LDAPInvalidCredentialsResult(result=49, description="invalidCredentials"),
        ),
        ("search", LDAPSocketReceiveError("connection reset")),
    ],
)
@pytest.mark.usefixtures("enable_retry")
def test_lookup_fails_over_on_replica_failure(
    mocker: MockerFixture, replica_api: LdapApi, operation: str, error: Exception
) -> None:
    connection = replica_api._connection
    selected_hosts: list[str] = []
    original = getattr(connection, operation)

    def fail_first_replica(*args: object, **kwargs: object) -> object:
        if operation == "open":
            original(*args, **kwargs)
        selected_hosts.append(connection.server.host)
        if connection.server.host == "replica-a.example.com":
            raise error
        return None if operation == "open" else original(*args, **kwargs)

    mocker.patch.object(connection, operation, side_effect=fail_first_replica)
    retry_hook = MagicMock()
    replica_api._hooks.retry_hooks.append(retry_hook)
    with replica_api:
        assert replica_api.get_users(["alice"]) == [LdapUser(username="alice")]
    assert selected_hosts == ["replica-a.example.com", "replica-b.example.com"]
    assert retry_hook.call_count == 1


@pytest.mark.usefixtures("enable_retry")
def test_all_replicas_down_is_bounded(
    mocker: MockerFixture, replica_api: LdapApi
) -> None:
    failed_bind = mocker.patch.object(
        replica_api._connection,
        "bind",
        side_effect=LDAPInvalidCredentialsResult(
            result=49, description="invalidCredentials"
        ),
    )
    with (
        replica_api,
        pytest.raises(LDAPInvalidCredentialsResult, match="invalidCredentials"),
    ):
        replica_api.get_users(["alice"])
    assert failed_bind.call_count == 3


@pytest.mark.usefixtures("enable_retry")
def test_failover_restarts_pagination(
    mocker: MockerFixture, replica_api: LdapApi
) -> None:
    search = mocker.patch.object(
        replica_api._connection,
        "search",
        side_effect=[
            (
                True,
                {
                    "result": 0,
                    "controls": {
                        _PAGED_RESULTS_CONTROL: {
                            "value": {"cookie": b"replica-a-cookie"}
                        }
                    },
                },
                [{"attributes": {"uid": ["partial"]}}],
                None,
            ),
            LDAPSocketReceiveError("connection reset"),
            (True, {"result": 0}, [{"attributes": {"uid": ["alice"]}}], None),
        ],
    )
    with replica_api:
        assert replica_api.get_users(["alice", "partial"]) == [
            LdapUser(username="alice")
        ]
    assert [call.kwargs["paged_cookie"] for call in search.call_args_list] == [
        None,
        b"replica-a-cookie",
        None,
    ]
    assert replica_api._connection.server.host == "replica-b.example.com"


@pytest.mark.usefixtures("enable_retry")
def test_retry_preserves_generator_usernames(
    mocker: MockerFixture, replica_api: LdapApi
) -> None:
    search = mocker.patch.object(
        replica_api._connection,
        "search",
        side_effect=[
            LDAPSocketReceiveError("connection reset"),
            (True, {"result": 0}, [{"attributes": {"uid": ["alice"]}}], None),
        ],
    )
    with replica_api:
        assert replica_api.get_users(name for name in ["alice"]) == [
            LdapUser(username="alice")
        ]
    assert all("(uid=alice)" in call.args[1] for call in search.call_args_list)


@pytest.mark.usefixtures("enable_retry")
def test_invalid_query_does_not_rotate_replicas(
    mocker: MockerFixture, replica_api: LdapApi
) -> None:
    search = mocker.patch.object(
        replica_api._connection,
        "search",
        side_effect=LDAPInvalidFilterError("invalid filter"),
    )
    with replica_api, pytest.raises(LDAPInvalidFilterError, match="invalid filter"):
        replica_api.get_users(["alice"])
    assert search.call_count == 1
    assert replica_api._connection.server.host == "replica-a.example.com"


def test_failed_open_closes_partial_socket(
    mocker: MockerFixture, replica_api: LdapApi
) -> None:
    socket = MagicMock()
    replica_api._connection.socket = socket
    mocker.patch.object(
        replica_api._connection,
        "open",
        side_effect=LDAPSocketOpenError("connection refused"),
    )
    with replica_api, pytest.raises(LDAPSocketOpenError, match="connection refused"):
        replica_api.get_users(["alice"])
    socket.close.assert_called_once()
    assert replica_api._connection.socket is None


@pytest.mark.parametrize("server_urls", [[], [""], [" "]])
def test_rejects_empty_replica_configuration(server_urls: list[str]) -> None:
    with pytest.raises(ValueError, match="at least one non-empty URL"):
        LdapApi(server_urls=server_urls, base_dn="dc=example,dc=com")


def test_retry_budget_covers_replica_list(replica_api: LdapApi) -> None:
    api = LdapApi(
        server_urls=[f"ldap://replica-{index}.example.com" for index in range(5)],
        base_dn="dc=example,dc=com",
        timeout=2,
    )
    assert api._hooks.retry_config is not None
    assert api._hooks.retry_config.attempts == 5
    assert api._hooks.retry_config.timeout == 65


def test_ldaps_does_not_issue_start_tls(
    mocker: MockerFixture, replica_api: LdapApi
) -> None:
    api = LdapApi(
        server_urls=["ldaps://a.example.com", "ldaps://b.example.com"],
        base_dn="dc=example,dc=com",
    )
    start_tls = mocker.patch.object(
        api._connection,
        "start_tls",
        side_effect=AssertionError("LDAPS must not issue STARTTLS"),
    )
    with api:
        assert api.get_users(["alice"]) == [LdapUser(username="alice")]
    start_tls.assert_not_called()


@pytest.mark.usefixtures("enable_retry")
def test_single_replica_retries_remain_bounded(
    mocker: MockerFixture, replica_api: LdapApi
) -> None:
    mocker.patch("ldap3.core.pooling.randint", return_value=0)
    api = LdapApi(server_urls=["ldap://only.example.com"], base_dn="dc=example,dc=com")
    search = mocker.patch.object(
        api._connection,
        "search",
        side_effect=LDAPSocketReceiveError("connection reset"),
    )
    with api, pytest.raises(LDAPSocketReceiveError, match="connection reset"):
        api.get_users(["alice"])
    assert search.call_count == 3
    assert api._connection.server.host == "only.example.com"


def test_ldap_api_stores_base_dn(ldap_api: LdapApi) -> None:
    """Test constructor stores base_dn."""
    assert ldap_api.base_dn == "dc=example,dc=com"


def test_ldap_api_creates_server(mock_ldap3: MagicMock, ldap_api: LdapApi) -> None:
    """Test constructor creates ldap3 Server."""
    from ldap3 import NONE

    mock_ldap3.server.assert_called_once_with(
        "ldap://ldap.example.com", get_info=NONE, connect_timeout=30
    )


def test_ldap_api_creates_connection_with_credentials(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test constructor creates ldap3 Connection with bind credentials."""
    mock_ldap3.connection_cls.assert_called_once_with(
        server=mock_ldap3.pool.return_value,
        user="uid=svc-account,cn=users,dc=example,dc=com",
        password="secret",
        client_strategy="SAFE_SYNC",
        receive_timeout=30,
        raise_exceptions=True,
    )


def test_ldap_api_creates_connection_anonymous(
    mock_ldap3: MagicMock, ldap_api_anonymous: LdapApi
) -> None:
    """Test constructor creates ldap3 Connection with anonymous bind."""
    mock_ldap3.connection_cls.assert_called_once_with(
        server=mock_ldap3.pool.return_value,
        user=None,
        password=None,
        client_strategy="SAFE_SYNC",
        receive_timeout=30,
        raise_exceptions=True,
    )


# --- Context Manager ---


@pytest.mark.usefixtures("enable_retry")
def test_initial_tls_failure_is_retried(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    mock_ldap3.connection.start_tls.side_effect = [
        LDAPStartTLSError("TLS handshake failed"),
        (True, None, None, None),
    ]
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0},
        [{"attributes": {"uid": ["alice"]}}],
        None,
    )
    with ldap_api:
        assert ldap_api.get_users(["alice"]) == [LdapUser(username="alice")]
    assert mock_ldap3.connection.start_tls.call_count == 2


def test_ldap_api_context_manager_binds(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """The first lookup binds within the retry boundary."""
    with ldap_api:
        ldap_api.get_users(["alice"])
        mock_ldap3.connection.bind.assert_called_once()


def test_ldap_api_context_manager_unbinds(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test __exit__ calls connection.unbind()."""
    with ldap_api:
        pass
    mock_ldap3.connection.unbind.assert_called_once()


def test_ldap_api_context_manager_start_tls(mock_ldap3: MagicMock) -> None:
    """The first lookup establishes TLS before binding."""
    api = LdapApi(
        server_urls=["ldap://ldap.example.com"],
        base_dn="dc=example,dc=com",
        bind_dn="uid=svc,dc=example,dc=com",
        bind_password="secret",
        start_tls=True,
    )
    with api:
        api.get_users(["alice"])
    mock_ldap3.connection.assert_has_calls(
        [call.start_tls(), call.bind()],
        any_order=False,
    )


def test_ldap_api_context_manager_start_tls_by_default(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Lookups use STARTTLS by default."""
    with ldap_api:
        ldap_api.get_users(["alice"])
        mock_ldap3.connection.start_tls.assert_called_once()


# --- get_users ---


def test_get_users_returns_ldap_user_models(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_users returns list of LdapUser models."""
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            {"attributes": {"uid": ["alice"]}},
            {"attributes": {"uid": ["bob"]}},
        ],
        None,
    )

    with ldap_api:
        result = ldap_api.get_users(["alice", "bob", "charlie"])

    assert {u.username for u in result} == {"alice", "bob"}
    assert all(isinstance(u, LdapUser) for u in result)


def test_get_users_builds_correct_filter(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_users constructs the correct LDAP filter."""
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [],
        None,
    )

    with ldap_api:
        ldap_api.get_users(["alice", "bob"])

    call_args = mock_ldap3.connection.search.call_args
    assert call_args[0][0] == "cn=users,cn=accounts,dc=example,dc=com"
    filter_str = call_args[0][1]
    assert "(objectclass=person)" in filter_str
    assert "(uid=alice)" in filter_str
    assert "(uid=bob)" in filter_str


def test_get_users_scopes_search_to_active_users_container(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_users only searches the active users container.

    FreeIPA moves deprovisioned accounts out of cn=users,cn=accounts into a
    separate preserved-users container, but accounts merely disabled via
    `ipa user-disable` (nsAccountLock=TRUE) stay active and remain in this
    container. Scoping the search here -- rather than filtering on
    nsAccountLock -- avoids treating a disabled-but-still-employed user as
    deprovisioned.
    """
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [{"attributes": {"uid": ["alice"]}}],
        None,
    )

    with ldap_api:
        result = ldap_api.get_users(["alice"])

    call_args = mock_ldap3.connection.search.call_args
    assert call_args[0][0] == "cn=users,cn=accounts,dc=example,dc=com"
    assert {u.username for u in result} == {"alice"}


def test_get_users_escapes_special_characters(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_users escapes LDAP filter special characters to prevent injection."""
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [],
        None,
    )

    with ldap_api:
        ldap_api.get_users(["user*", "user)(uid=*)", "user\\evil"])

    filter_str = mock_ldap3.connection.search.call_args[0][1]
    # Special chars must be escaped -- raw values must NOT appear in filter
    assert "(uid=user*)" not in filter_str  # * must be escaped
    assert "(uid=user)(uid=*)" not in filter_str  # ) and ( must be escaped
    assert "(uid=user\\evil)" not in filter_str  # \ must be escaped
    # Escaped versions should be present
    assert "(uid=user\\2a)" in filter_str  # * -> \2a
    assert "\\29" in filter_str  # ) -> \29
    assert "\\28" in filter_str  # ( -> \28
    assert "\\5c" in filter_str  # \ -> \5c


def test_get_users_empty_input(mock_ldap3: MagicMock, ldap_api: LdapApi) -> None:
    """Test get_users with empty input returns empty list."""
    with ldap_api:
        result = ldap_api.get_users([])

    assert result == []
    mock_ldap3.connection.search.assert_not_called()


def test_get_users_search_failure_raises_error(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_users raises LdapApiError on search failure."""
    mock_ldap3.connection.search.return_value = (
        False,
        {"result": 53, "description": "Server Unwilling to Perform"},
        [],
        None,
    )

    with ldap_api, pytest.raises(LdapApiError, match="LDAP operation failed"):
        ldap_api.get_users(["alice"])


# --- Hooks ---


def test_ldap_api_pre_hooks_includes_builtins(mock_ldap3: MagicMock) -> None:
    """Test that built-in hooks (metrics, logging, latency) are included."""
    api = LdapApi(
        server_urls=["ldap://ldap.example.com"],
        base_dn="dc=example,dc=com",
    )
    # Should have metrics, request_log, latency_start
    assert len(api._hooks.pre_hooks) >= 3


def test_ldap_api_custom_hooks_merged(mock_ldap3: MagicMock) -> None:
    """Test custom hooks are merged with built-in hooks."""
    custom_hook = MagicMock()
    api = LdapApi(
        server_urls=["ldap://ldap.example.com"],
        base_dn="dc=example,dc=com",
        hooks=Hooks(pre_hooks=[custom_hook]),
    )
    assert custom_hook in api._hooks.pre_hooks
    assert len(api._hooks.pre_hooks) == 4  # 3 builtin + 1 custom


def test_get_users_calls_hooks(mock_ldap3: MagicMock, ldap_api: LdapApi) -> None:
    """Test get_users triggers pre/post hooks with correct context."""
    pre_hook = MagicMock()
    ldap_api._hooks = Hooks(pre_hooks=[pre_hook])
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [],
        None,
    )

    with ldap_api:
        ldap_api.get_users(["alice"])

    pre_hook.assert_called_once()
    context = pre_hook.call_args[0][0]
    assert isinstance(context, LdapApiCallContext)
    assert context.method == "get_users"


def test_ldap_user_model_frozen() -> None:
    """Test LdapUser is immutable."""
    user = LdapUser(username="alice")
    assert user.username == "alice"
    with pytest.raises(ValidationError, match="frozen"):
        user.username = "bob"  # type: ignore[misc]


def test_ldap_group_model_frozen() -> None:
    """Test LdapGroup is immutable."""
    group = LdapGroup(
        cn="admins",
        dn="cn=admins,dc=example,dc=com",
        members=frozenset({LdapUser(username="alice")}),
    )
    assert group.cn == "admins"
    assert group.dn == "cn=admins,dc=example,dc=com"
    assert group.members == frozenset({LdapUser(username="alice")})
    with pytest.raises(ValidationError, match="frozen"):
        group.dn = "other"  # type: ignore[misc]


def test_get_users_retries_on_transient_error(
    mock_ldap3: MagicMock, ldap_api: LdapApi, enable_retry: None
) -> None:
    """Test get_users retries on transient network errors only."""
    from ldap3.core.exceptions import LDAPCommunicationError

    # First call: transient error, second call: success
    mock_ldap3.connection.search.side_effect = [
        LDAPCommunicationError("connection reset"),
        (
            True,
            {"result": 0, "description": "success"},
            [{"attributes": {"uid": ["alice"]}}],
            None,
        ),
    ]

    with ldap_api:
        result = ldap_api.get_users(["alice"])

    assert {u.username for u in result} == {"alice"}
    assert mock_ldap3.connection.search.call_count == 2


def test_get_users_does_not_retry_on_logical_error(
    mock_ldap3: MagicMock, ldap_api: LdapApi, enable_retry: None
) -> None:
    """Test get_users does NOT retry on logical errors like noSuchObject."""
    # noSuchObject (error 32) is a logical error, should NOT be retried
    mock_ldap3.connection.search.return_value = (
        False,
        {"result": 32, "description": "noSuchObject"},
        [],
        None,
    )

    with ldap_api, pytest.raises(LdapApiError, match="LDAP operation failed"):
        ldap_api.get_users(["alice"])

    # Should have been called only once (no retry)
    assert mock_ldap3.connection.search.call_count == 1


def test_get_users_calls_post_hooks(mock_ldap3: MagicMock, ldap_api: LdapApi) -> None:
    """Test get_users triggers post hooks after API call."""
    post_hook = MagicMock()
    ldap_api._hooks = Hooks(post_hooks=[post_hook])
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [],
        None,
    )

    with ldap_api:
        ldap_api.get_users(["alice"])

    post_hook.assert_called_once()
    context = post_hook.call_args[0][0]
    assert isinstance(context, LdapApiCallContext)
    assert context.method == "get_users"


def test_get_users_search_failure_error_message(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test LdapApiError includes error code and description."""
    mock_ldap3.connection.search.return_value = (
        False,
        {"result": 49, "description": "invalidCredentials"},
        [],
        None,
    )

    with ldap_api, pytest.raises(LdapApiError, match="49.*invalidCredentials"):
        ldap_api.get_users(["alice"])


def test_ldap_api_call_context_immutable() -> None:
    """Test LdapApiCallContext is frozen."""
    context = LdapApiCallContext(method="get_users")
    with pytest.raises(AttributeError):
        context.method = "other"  # type: ignore[misc]


# --- get_group_members ---


@pytest.mark.parametrize("duplicate_name", ["ALICE EXAMPLE", " Alice Example "])
def test_get_group_members_deduplicates_uid_and_retains_first_name(
    duplicate_name: str, mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Repeated LDAP records do not inflate group size when CN differs."""
    group_dns = [
        "cn=team-a,cn=groups,cn=accounts,dc=example,dc=com",
        "cn=team-b,cn=groups,cn=accounts,dc=example,dc=com",
    ]
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            {"attributes": {"uid": ["alice"], "cn": [name], "memberOf": group_dns}}
            for name in ("Alice Example", duplicate_name)
        ],
        None,
    )
    with ldap_api:
        groups = ldap_api.get_group_members(group_dns)
    assert {group.dn for group in groups} == set(group_dns)
    for group in groups:
        assert [(member.username, member.name) for member in group.members] == [
            ("alice", "Alice Example")
        ]


def test_get_group_members_preserves_person_name(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    group_dn = "cn=team,cn=groups,cn=accounts,dc=example,dc=com"
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            {
                "attributes": {
                    "uid": ["alice"],
                    "cn": ["Alice Example"],
                    "memberOf": [group_dn],
                }
            }
        ],
        None,
    )
    with ldap_api:
        groups = ldap_api.get_group_members([group_dn])
    assert next(iter(groups[0].members)).name == "Alice Example"
    assert "cn" in mock_ldap3.connection.search.call_args.kwargs["attributes"]


def test_get_group_members_rejects_missing_person_name(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    group_dn = "cn=team,cn=groups,cn=accounts,dc=example,dc=com"
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [{"attributes": {"uid": ["alice"], "cn": [], "memberOf": [group_dn]}}],
        None,
    )
    with ldap_api, pytest.raises(LdapApiError, match="alice has no cn attribute"):
        ldap_api.get_group_members([group_dn])


def test_get_group_members_returns_groups_with_members(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_group_members returns LdapGroup models with CN, DN, and members."""
    group1_dn = "cn=admins,ou=groups,dc=example,dc=com"
    group2_dn = "cn=devs,ou=groups,dc=example,dc=com"
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            {
                "attributes": {
                    "uid": ["alice"],
                    "cn": ["alice"],
                    "memberOf": [group1_dn, group2_dn],
                }
            },
            {"attributes": {"uid": ["bob"], "cn": ["bob"], "memberOf": [group1_dn]}},
        ],
        None,
    )

    with ldap_api:
        result = ldap_api.get_group_members([group1_dn, group2_dn])

    groups_by_cn = {g.cn: g for g in result}
    assert set(groups_by_cn) == {"admins", "devs"}
    assert groups_by_cn["admins"].dn == group1_dn
    assert {u.username for u in groups_by_cn["admins"].members} == {"alice", "bob"}
    assert groups_by_cn["devs"].dn == group2_dn
    assert {u.username for u in groups_by_cn["devs"].members} == {"alice"}


def test_get_group_members_empty_input(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_group_members with empty input returns empty list."""
    with ldap_api:
        result = ldap_api.get_group_members([])

    assert result == []
    mock_ldap3.connection.search.assert_not_called()


def test_get_group_members_builds_correct_filter(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_group_members constructs the correct LDAP filter."""
    group_dn = "cn=admins,ou=groups,dc=example,dc=com"
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [],
        None,
    )

    with ldap_api:
        ldap_api.get_group_members([group_dn])

    call_args = mock_ldap3.connection.search.call_args
    assert call_args[0][0] == "dc=example,dc=com"
    filter_str = call_args[0][1]
    assert f"(memberOf={group_dn})" in filter_str


def test_get_group_members_restricts_to_person_entries(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_group_members restricts the search to person entries.

    FreeIPA groups can nest other groups or Kerberos service entries as
    members - without an objectclass restriction, such an entry would match
    the memberOf filter too, and reading its (nonexistent) uid attribute
    would crash the whole group resolution.
    """
    group_dn = "cn=admins,ou=groups,dc=example,dc=com"
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [],
        None,
    )

    with ldap_api:
        ldap_api.get_group_members([group_dn])

    filter_str = mock_ldap3.connection.search.call_args[0][1]
    assert "(objectclass=person)" in filter_str


def test_get_group_members_skips_nested_group_without_uid(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_group_members skips a matching entry that has no uid.

    A nested group's own LDAP entry can have memberOf pointing at its parent
    group, so it can still match the search even with the objectclass=person
    filter in some directory configurations - this must not crash resolution
    for the rest of the group's real (user) members.
    """
    group_dn = "cn=admins,ou=groups,dc=example,dc=com"
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            {"attributes": {"memberOf": [group_dn]}},  # nested group, no uid
            {"attributes": {"uid": ["alice"], "cn": ["alice"], "memberOf": [group_dn]}},
        ],
        None,
    )

    with ldap_api:
        result = ldap_api.get_group_members([group_dn])

    assert len(result) == 1
    assert {u.username for u in result[0].members} == {"alice"}


def test_get_group_members_search_failure_raises_error(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_group_members raises LdapApiError on search failure."""
    mock_ldap3.connection.search.return_value = (
        False,
        {"result": 53, "description": "Server Unwilling to Perform"},
        [],
        None,
    )

    with ldap_api, pytest.raises(LdapApiError, match="LDAP operation failed"):
        ldap_api.get_group_members(["cn=admins,ou=groups,dc=example,dc=com"])


def test_get_group_members_ignores_unrelated_memberships(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_group_members only includes requested groups, not all memberOf values."""
    requested_dn = "cn=admins,ou=groups,dc=example,dc=com"
    other_dn = "cn=other,ou=groups,dc=example,dc=com"
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            {
                "attributes": {
                    "uid": ["alice"],
                    "cn": ["alice"],
                    "memberOf": [requested_dn, other_dn],
                }
            },
        ],
        None,
    )

    with ldap_api:
        result = ldap_api.get_group_members([requested_dn])

    assert len(result) == 1
    assert result[0].cn == "admins"
    assert result[0].dn == requested_dn


def test_get_group_members_calls_hooks(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_group_members triggers hooks with correct context."""
    pre_hook = MagicMock()
    ldap_api._hooks = Hooks(pre_hooks=[pre_hook])
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [],
        None,
    )

    with ldap_api:
        ldap_api.get_group_members(["cn=admins,ou=groups,dc=example,dc=com"])

    pre_hook.assert_called_once()
    context = pre_hook.call_args[0][0]
    assert isinstance(context, LdapApiCallContext)
    assert context.method == "get_group_members"


def test_get_group_members_retries_on_transient_error(
    mock_ldap3: MagicMock, ldap_api: LdapApi, enable_retry: None
) -> None:
    """Test get_group_members retries on transient network errors."""
    from ldap3.core.exceptions import LDAPCommunicationError

    group_dn = "cn=admins,ou=groups,dc=example,dc=com"
    mock_ldap3.connection.search.side_effect = [
        LDAPCommunicationError("connection reset"),
        (
            True,
            {"result": 0, "description": "success"},
            [
                {
                    "attributes": {
                        "uid": ["alice"],
                        "cn": ["alice"],
                        "memberOf": [group_dn],
                    }
                }
            ],
            None,
        ),
    ]

    with ldap_api:
        result = ldap_api.get_group_members([group_dn])

    assert len(result) == 1
    assert result[0].cn == "admins"
    assert mock_ldap3.connection.search.call_count == 2


def test_get_group_members_members_are_ldap_user_models(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_group_members returns LdapUser instances as members."""
    group_dn = "cn=team,ou=groups,dc=example,dc=com"
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            {"attributes": {"uid": ["alice"], "cn": ["alice"], "memberOf": [group_dn]}},
        ],
        None,
    )

    with ldap_api:
        result = ldap_api.get_group_members([group_dn])

    member = next(iter(result[0].members))
    assert isinstance(member, LdapUser)
    assert member.username == "alice"


def test_get_group_members_escapes_special_characters(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_group_members escapes LDAP filter special characters in DNs."""
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [],
        None,
    )

    dn_with_parens = "cn=group(test),ou=groups,dc=example,dc=com"
    with ldap_api:
        ldap_api.get_group_members([dn_with_parens])

    filter_str = mock_ldap3.connection.search.call_args[0][1]
    assert f"(memberOf={dn_with_parens})" not in filter_str
    assert "\\28" in filter_str  # ( -> \28
    assert "\\29" in filter_str  # ) -> \29


def test_get_group_members_matches_differently_cased_member_of(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_group_members matches a memberOf value differing only in case.

    A raw string comparison would silently drop the member and make a real
    group look confirmed-empty.
    """
    requested_dn = "cn=admins,ou=groups,dc=example,dc=com"
    differently_cased_member_of = "CN=Admins,OU=Groups,DC=Example,DC=Com"
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            {
                "attributes": {
                    "uid": ["alice"],
                    "cn": ["alice"],
                    "memberOf": [differently_cased_member_of],
                }
            },
        ],
        None,
    )

    with ldap_api:
        result = ldap_api.get_group_members([requested_dn])

    assert len(result) == 1
    # The returned dn/cn reflect the originally requested DN, not the
    # server's differently-cased representation.
    assert result[0].dn == requested_dn
    assert result[0].cn == "admins"
    assert {u.username for u in result[0].members} == {"alice"}


def test_get_group_members_ignores_unrelated_differently_cased_member_of(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test canonicalized matching does not become overly permissive.

    An unrelated group (even if cased differently) is still excluded.
    """
    requested_dn = "cn=admins,ou=groups,dc=example,dc=com"
    unrelated_dn = "CN=Other,OU=Groups,DC=Example,DC=Com"
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            {
                "attributes": {
                    "uid": ["alice"],
                    "cn": ["alice"],
                    "memberOf": [unrelated_dn],
                }
            },
        ],
        None,
    )

    with ldap_api:
        result = ldap_api.get_group_members([requested_dn])

    assert result == []


def test_get_group_members_distinguishes_multi_valued_rdn_from_separate_rdns(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Canonicalization must preserve RDN boundaries.

    A multi-valued RDN (`cn=admins+ou=groups,...`, one RDN made of two
    attribute-value pairs joined by `+`) is structurally different from two
    separate RDNs (`cn=admins,ou=groups,...`, joined by `,`) - collapsing both
    to the same canonical key would silently merge two distinct groups'
    memberships.
    """
    multi_valued_rdn_dn = "cn=admins+ou=groups,dc=example,dc=com"
    separate_rdns_dn = "cn=admins,ou=groups,dc=example,dc=com"
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            {
                "attributes": {
                    "uid": ["alice"],
                    "cn": ["alice"],
                    "memberOf": [multi_valued_rdn_dn],
                }
            },
            {
                "attributes": {
                    "uid": ["bob"],
                    "cn": ["bob"],
                    "memberOf": [separate_rdns_dn],
                }
            },
        ],
        None,
    )

    with ldap_api:
        result = ldap_api.get_group_members([multi_valued_rdn_dn, separate_rdns_dn])

    by_dn = {group.dn: group for group in result}
    assert len(result) == 2
    assert {u.username for u in by_dn[multi_valued_rdn_dn].members} == {"alice"}
    assert {u.username for u in by_dn[separate_rdns_dn].members} == {"bob"}


def test_get_group_members_matches_equivalent_dn_escape_encodings(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    r"""Canonicalization must decode RFC 4514 escapes before comparing.

    A literal comma in an attribute value can be spelled as a backslash
    escape (`\\,`) or as a hex-pair escape (`\\2C`) - both represent the same
    literal string, but parse_dn() preserves whichever spelling was used. A
    raw (post-lowercase) string comparison would treat the two spellings as
    different DNs and silently drop the member.
    """
    requested_dn = r"cn=sales\,admins,ou=groups,dc=example,dc=com"
    differently_escaped_member_of = r"cn=sales\2Cadmins,ou=groups,dc=example,dc=com"
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            {
                "attributes": {
                    "uid": ["alice"],
                    "cn": ["alice"],
                    "memberOf": [differently_escaped_member_of],
                }
            },
        ],
        None,
    )

    with ldap_api:
        result = ldap_api.get_group_members([requested_dn])

    assert len(result) == 1
    assert result[0].dn == requested_dn
    assert {u.username for u in result[0].members} == {"alice"}


# --- check_groups_exist ---


def test_check_groups_exist_returns_existing_cns(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test check_groups_exist returns the subset of CNs found in LDAP."""
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            {"attributes": {"cn": ["admins"]}},
            {"attributes": {"cn": ["devs"]}},
        ],
        None,
    )

    with ldap_api:
        result = ldap_api.check_groups_exist(["admins", "devs", "ghost-group"])

    assert result == {"admins", "devs"}


def test_check_groups_exist_empty_input(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test check_groups_exist with empty input returns empty set without searching."""
    with ldap_api:
        result = ldap_api.check_groups_exist([])

    assert result == set()
    mock_ldap3.connection.search.assert_not_called()


def test_check_groups_exist_none_found(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test check_groups_exist returns empty set when no requested CN exists."""
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [],
        None,
    )

    with ldap_api:
        result = ldap_api.check_groups_exist(["ghost-group"])

    assert result == set()


def test_check_groups_exist_searches_groups_container(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test check_groups_exist searches the groups container, not base_dn directly."""
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [],
        None,
    )

    with ldap_api:
        ldap_api.check_groups_exist(["admins"])

    call_args = mock_ldap3.connection.search.call_args
    assert call_args[0][0] == "cn=groups,cn=accounts,dc=example,dc=com"
    assert "(cn=admins)" in call_args[0][1]


def test_check_groups_exist_search_failure_raises_error(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test check_groups_exist raises LdapApiError on search failure."""
    mock_ldap3.connection.search.return_value = (
        False,
        {"result": 53, "description": "Server Unwilling to Perform"},
        [],
        None,
    )

    with ldap_api, pytest.raises(LdapApiError, match="LDAP operation failed"):
        ldap_api.check_groups_exist(["admins"])


def test_check_groups_exist_escapes_special_characters(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test check_groups_exist escapes LDAP filter special characters in CNs."""
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [],
        None,
    )

    with ldap_api:
        ldap_api.check_groups_exist(["group(test)"])

    filter_str = mock_ldap3.connection.search.call_args[0][1]
    assert "(cn=group(test))" not in filter_str
    assert "\\28" in filter_str  # ( -> \28
    assert "\\29" in filter_str  # ) -> \29


def test_check_groups_exist_calls_hooks(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test check_groups_exist triggers hooks with correct context."""
    pre_hook = MagicMock()
    ldap_api._hooks = Hooks(pre_hooks=[pre_hook])
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [],
        None,
    )

    with ldap_api:
        ldap_api.check_groups_exist(["admins"])

    pre_hook.assert_called_once()
    context = pre_hook.call_args[0][0]
    assert isinstance(context, LdapApiCallContext)
    assert context.method == "check_groups_exist"


@pytest.mark.parametrize(
    "method", ["get_users", "get_group_members", "check_groups_exist"]
)
def test_ldap_search_methods_paginate_across_pages(
    mock_ldap3: MagicMock, ldap_api: LdapApi, method: str
) -> None:
    """All lookup methods consume every page and forward the server cookie."""
    group_dn = "cn=admins,cn=groups,cn=accounts,dc=example,dc=com"
    mock_ldap3.connection.search.side_effect = [
        (
            True,
            {
                "result": 0,
                "controls": {_PAGED_RESULTS_CONTROL: {"value": {"cookie": cookie}}},
            },
            [{"attributes": {"uid": [uid], "cn": [cn], "memberOf": [group_dn]}}],
            None,
        )
        for uid, cn, cookie in [
            ("alice", "admins", b"next-page"),
            ("bob", "devs", b""),
        ]
    ]

    with ldap_api:
        match method:
            case "get_users":
                assert ldap_api.get_users(["alice", "bob"]) == [
                    LdapUser(username="alice"),
                    LdapUser(username="bob"),
                ]
            case "get_group_members":
                assert ldap_api.get_group_members([group_dn]) == [
                    LdapGroup(
                        cn="admins",
                        dn=group_dn,
                        members=frozenset(
                            {
                                LdapUser(username="alice", name="admins"),
                                LdapUser(username="bob", name="devs"),
                            }
                        ),
                    )
                ]
            case "check_groups_exist":
                assert ldap_api.check_groups_exist(["admins", "devs"]) == {
                    "admins",
                    "devs",
                }

    first_call, second_call = mock_ldap3.connection.search.call_args_list
    assert first_call.kwargs["paged_size"] == _LDAP_PAGE_SIZE
    assert first_call.kwargs["paged_cookie"] is None
    assert second_call.kwargs["paged_size"] == _LDAP_PAGE_SIZE
    assert second_call.kwargs["paged_cookie"] == b"next-page"


@pytest.mark.parametrize(
    "method",
    ["get_users", "get_group_members", "check_groups_exist", "get_github_usernames"],
)
def test_ldap_search_methods_fail_closed_on_later_page_error(
    mock_ldap3: MagicMock, ldap_api: LdapApi, method: str
) -> None:
    """A later page error must raise rather than return partial results."""
    group_dn = "cn=admins,cn=groups,cn=accounts,dc=example,dc=com"
    mock_ldap3.connection.search.side_effect = [
        (
            True,
            {
                "result": 0,
                "controls": {
                    _PAGED_RESULTS_CONTROL: {"value": {"cookie": b"next-page"}}
                },
            },
            [
                {
                    "attributes": {
                        "uid": ["alice"],
                        "cn": ["admins"],
                        "memberOf": [group_dn],
                        "rhatSocialURL": ["Github->https://github.com/alice-gh"],
                    }
                }
            ],
            None,
        ),
        (False, {"result": 4, "description": "sizeLimitExceeded"}, [], None),
    ]

    with ldap_api, pytest.raises(LdapApiError, match="sizeLimitExceeded"):
        match method:
            case "get_users":
                ldap_api.get_users(["alice"])
            case "get_group_members":
                ldap_api.get_group_members([group_dn])
            case "check_groups_exist":
                ldap_api.check_groups_exist(["admins"])
            case "get_github_usernames":
                ldap_api.get_github_usernames()


# --- _parse_github_login ---


@pytest.mark.parametrize(
    ("social_url", "expected"),
    [
        # Canonical form as stored in FreeIPA
        ("Github->http://github.com/chassing", "chassing"),
        # https and www variants
        ("Github->https://github.com/chassing", "chassing"),
        ("Github->https://www.github.com/chassing", "chassing"),
        # Trailing slash -> single (bare) path segment is still a profile
        ("Github->https://github.com/chassing/", "chassing"),
        # Casing of the login is preserved (callers normalise)
        ("Github->https://github.com/ChAsSiNg", "ChAsSiNg"),
        # Label matching is case-insensitive / whitespace-tolerant
        ("github->https://github.com/chassing", "chassing"),
        (" GitHub -> https://github.com/chassing ", "chassing"),
        # Hyphenated login (valid GitHub username)
        ("Github->https://github.com/red-hat", "red-hat"),
    ],
)
def test_parse_github_login_valid(social_url: str, expected: str) -> None:
    """Test _parse_github_login extracts the login from valid github.com URLs."""
    assert _parse_github_login(social_url) == expected


@pytest.mark.parametrize(
    "social_url",
    [
        # Non-GitHub social label
        "Twitter->https://twitter.com/chassing",
        "LinkedIn->https://github.com/chassing",  # wrong label, right host
        # Missing separator
        "https://github.com/chassing",
        # Empty login (no path segment)
        "Github->https://github.com/",
        "Github->https://github.com",
        # Repo / sub-path URLs: the first segment is NOT reliably the linking
        # user's profile (it may be an org they contribute to or another user's
        # repo), so only bare `github.com/<login>` establishes a login.
        "Github->https://github.com/chassing/repo",
        "Github->https://github.com/openshift/cluster-kube-apiserver-operator",
        "Github->https://github.com/util-linux/util-linux",
        # Excluded hosts: Pages, gist, custom domain
        "Github->https://chassing.github.io/",
        "Github->https://gist.github.com/chassing",
        "Github->https://example.com/chassing",
        # Login with invalid characters (underscore not allowed)
        "Github->https://github.com/bad_name",
        # Empty string
        "",
    ],
)
def test_parse_github_login_invalid(social_url: str) -> None:
    """Test _parse_github_login returns None for non-github.com user URLs."""
    assert _parse_github_login(social_url) is None


def test_parse_github_login_strips_null_bytes() -> None:
    """Test _parse_github_login tolerates trailing null bytes (seen in LDAP values)."""
    assert _parse_github_login("Github->https://github.com/chassing\x00") == "chassing"


# --- get_github_usernames ---


def test_get_github_usernames_builds_mapping(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_github_usernames maps parsed logins (lowercased) to uid lists."""
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            {
                "attributes": {
                    "uid": ["alice"],
                    "rhatSocialURL": ["Github->https://github.com/AliceGH"],
                }
            },
            {
                "attributes": {
                    "uid": ["bob"],
                    "rhatSocialURL": [
                        "Twitter->https://twitter.com/bob",
                        "Github->http://github.com/bob-gh",
                    ],
                }
            },
        ],
        None,
    )

    with ldap_api:
        result = ldap_api.get_github_usernames()

    # Keys are lowercased logins; values are the distinct uids per login.
    assert result == {"alicegh": ["alice"], "bob-gh": ["bob"]}


def test_get_github_usernames_scopes_and_filters(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_github_usernames searches the active users container with a filter."""
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [],
        None,
    )

    with ldap_api:
        ldap_api.get_github_usernames()

    call_args = mock_ldap3.connection.search.call_args
    assert call_args[0][0] == "cn=users,cn=accounts,dc=example,dc=com"
    filter_str = call_args[0][1]
    assert "(objectclass=person)" in filter_str
    assert "rhatSocialURL=Github->*github.com/*" in filter_str
    assert call_args[1]["attributes"] == ["uid", "rhatSocialURL"]


def test_get_github_usernames_skips_unparseable_values(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_github_usernames drops users whose social URLs aren't github.com logins."""
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            {
                "attributes": {
                    "uid": ["carol"],
                    "rhatSocialURL": ["Github->https://gist.github.com/carol"],
                }
            },
            {"attributes": {"uid": ["dave"], "rhatSocialURL": []}},
        ],
        None,
    )

    with ldap_api:
        result = ldap_api.get_github_usernames()

    assert result == {}


def test_get_github_usernames_groups_uids_per_login(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """All uids that claim a login (case-insensitively) are grouped, not dropped.

    The api layer only extracts data; deciding what to do with an ambiguous
    login (>1 uid) is the caller's policy, scoped to the logins it actually
    requested, so this layer returns every uid it saw.
    """
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            # Two distinct users claim the same GitHub login (case-insensitive)
            {
                "attributes": {
                    "uid": ["alice"],
                    "rhatSocialURL": ["Github->https://github.com/shared-gh"],
                }
            },
            {
                "attributes": {
                    "uid": ["mallory"],
                    "rhatSocialURL": ["Github->https://github.com/Shared-GH"],
                }
            },
            {
                "attributes": {
                    "uid": ["bob"],
                    "rhatSocialURL": ["Github->https://github.com/bob-gh"],
                }
            },
        ],
        None,
    )

    with ldap_api:
        result = ldap_api.get_github_usernames()

    # Login key is lowercased; the two claimants are grouped and sorted.
    assert result == {"shared-gh": ["alice", "mallory"], "bob-gh": ["bob"]}


def test_get_github_usernames_keeps_duplicate_same_uid(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """A login repeated for the SAME uid (any casing) yields a single uid."""
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            {
                "attributes": {
                    "uid": ["alice"],
                    "rhatSocialURL": [
                        "Github->https://github.com/AliceGH",
                        "Github->https://github.com/alicegh",
                    ],
                }
            },
        ],
        None,
    )

    with ldap_api:
        result = ldap_api.get_github_usernames()

    # Login lowercased; the single uid is not duplicated.
    assert result == {"alicegh": ["alice"]}


def test_get_github_usernames_ignores_repo_urls(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Repo / sub-path URLs never establish a login (misattribution fix).

    A user whose only GitHub link is a repo they contribute to must not have
    that repo's owner attributed to them, otherwise the owner would resolve to
    the wrong Red Hat identity. Only bare `github.com/<login>` counts.
    """
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [
            # Only contributes to someone else's repo -> nothing extracted
            {
                "attributes": {
                    "uid": ["carol"],
                    "rhatSocialURL": [
                        "Github->https://github.com/openshift/cluster-kube-apiserver-operator"
                    ],
                }
            },
            # Bare profile -> extracted
            {
                "attributes": {
                    "uid": ["dave"],
                    "rhatSocialURL": ["Github->https://github.com/dave-gh"],
                }
            },
        ],
        None,
    )

    with ldap_api:
        result = ldap_api.get_github_usernames()

    assert result == {"dave-gh": ["dave"]}


def test_get_github_usernames_paginates_across_pages(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """The broad search is paged: results from every page are aggregated.

    389 Directory Server caps a single search at ~2000 entries and returns
    LDAP_SIZELIMIT_EXCEEDED past that, so the mapping must follow the paged
    results cookie until the server signals no more pages.
    """
    mock_ldap3.connection.search.side_effect = [
        (
            True,
            {
                "result": 0,
                "description": "success",
                "controls": {
                    _PAGED_RESULTS_CONTROL: {"value": {"cookie": b"next-page"}}
                },
            },
            [
                {
                    "attributes": {
                        "uid": ["alice"],
                        "rhatSocialURL": ["Github->https://github.com/AliceGH"],
                    }
                }
            ],
            None,
        ),
        (
            True,
            {
                "result": 0,
                "description": "success",
                "controls": {_PAGED_RESULTS_CONTROL: {"value": {"cookie": b""}}},
            },
            [
                {
                    "attributes": {
                        "uid": ["bob"],
                        "rhatSocialURL": ["Github->https://github.com/bob-gh"],
                    }
                }
            ],
            None,
        ),
    ]

    with ldap_api:
        result = ldap_api.get_github_usernames()

    # Entries from both pages are merged.
    assert result == {"alicegh": ["alice"], "bob-gh": ["bob"]}
    assert mock_ldap3.connection.search.call_count == 2

    first_call, second_call = mock_ldap3.connection.search.call_args_list
    # First page requests a fresh cursor; second page forwards the cookie.
    assert first_call[1]["paged_size"] == _LDAP_PAGE_SIZE
    assert first_call[1]["paged_cookie"] is None
    assert second_call[1]["paged_size"] == _LDAP_PAGE_SIZE
    assert second_call[1]["paged_cookie"] == b"next-page"


def test_get_github_usernames_search_failure_raises_error(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_github_usernames raises LdapApiError on search failure."""
    mock_ldap3.connection.search.return_value = (
        False,
        {"result": 53, "description": "Server Unwilling to Perform"},
        [],
        None,
    )

    with ldap_api, pytest.raises(LdapApiError, match="LDAP operation failed"):
        ldap_api.get_github_usernames()


def test_get_github_usernames_calls_hooks(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test get_github_usernames triggers hooks with correct context."""
    pre_hook = MagicMock()
    ldap_api._hooks = Hooks(pre_hooks=[pre_hook])
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0, "description": "success"},
        [],
        None,
    )

    with ldap_api:
        ldap_api.get_github_usernames()

    pre_hook.assert_called_once()
    context = pre_hook.call_args[0][0]
    assert isinstance(context, LdapApiCallContext)
    assert context.method == "get_github_usernames"


# --- Quorum verification (APPSRE-15561) ---

_ALICE_ENTRY = {
    "dn": "uid=alice,cn=users,cn=accounts,dc=example,dc=com",
    "attributes": {"uid": ["alice"], "cn": ["Alice"], "memberOf": []},
}
_BOB_ENTRY = {
    "dn": "uid=bob,cn=users,cn=accounts,dc=example,dc=com",
    "attributes": {"uid": ["bob"], "cn": ["Bob"], "memberOf": []},
}


@pytest.fixture
def quorum_api(mocker: MockerFixture) -> LdapApi:
    """Same real-pool/mocked-network setup as replica_api, with quorum_count=2."""

    def open_connection(strategy: BaseStrategy) -> None:
        connection = strategy.connection
        connection.server = connection.server_pool.get_server(connection)

    def start_tls(connection: Connection) -> None:
        connection.tls_started = True

    def bind(connection: Connection) -> None:
        connection.bound = True

    def unbind(connection: Connection) -> None:
        connection.bound = False
        connection.tls_started = False

    mocker.patch(
        "ldap3.strategy.sync.SyncStrategy.open",
        autospec=True,
        side_effect=open_connection,
    )
    mocker.patch(
        "ldap3.core.connection.Connection.start_tls",
        autospec=True,
        side_effect=start_tls,
    )
    mocker.patch(
        "ldap3.core.connection.Connection.bind", autospec=True, side_effect=bind
    )
    mocker.patch(
        "ldap3.core.connection.Connection.unbind", autospec=True, side_effect=unbind
    )
    mocker.patch("ldap3.core.pooling.randint", return_value=1)
    mocker.patch(
        "ldap3.core.server.Server.check_availability",
        side_effect=AssertionError("TCP prechecks must be disabled"),
    )
    return LdapApi(
        server_urls=["ldap://replica-a.example.com", "ldap://replica-b.example.com"],
        base_dn="dc=example,dc=com",
        bind_dn="uid=svc,dc=example,dc=com",
        bind_password="secret",
        quorum_count=2,
    )


def test_quorum_match_returns_primary_results(
    mocker: MockerFixture, quorum_api: LdapApi
) -> None:
    """Identical results from both replicas pass verification."""
    search = mocker.patch.object(
        quorum_api._connection,
        "search",
        side_effect=[
            (True, {"result": 0}, [_ALICE_ENTRY], None),
            (True, {"result": 0}, [_ALICE_ENTRY], None),
        ],
    )
    with quorum_api:
        assert quorum_api.get_users(["alice"]) == [LdapUser(username="alice")]
    assert search.call_count == 2


def test_quorum_mismatch_missing_entries_raises(
    mocker: MockerFixture, quorum_api: LdapApi
) -> None:
    """A replica missing entries the primary found fails closed."""
    mocker.patch.object(
        quorum_api._connection,
        "search",
        side_effect=[
            (True, {"result": 0}, [_ALICE_ENTRY, _BOB_ENTRY], None),
            (True, {"result": 0}, [_ALICE_ENTRY], None),
        ],
    )
    with quorum_api, pytest.raises(LdapQuorumError, match="quorum mismatch"):
        quorum_api.get_users(["alice", "bob"])


def test_quorum_mismatch_stale_attribute_raises(
    mocker: MockerFixture, quorum_api: LdapApi
) -> None:
    """Same entries on both replicas but differing attribute values fail closed."""
    stale_alice = {
        "dn": _ALICE_ENTRY["dn"],
        "attributes": {
            "uid": ["alice"],
            "cn": ["Alice"],
            "memberOf": ["cn=old-group,..."],
        },
    }
    mocker.patch.object(
        quorum_api._connection,
        "search",
        side_effect=[
            (True, {"result": 0}, [_ALICE_ENTRY], None),
            (True, {"result": 0}, [stale_alice], None),
        ],
    )
    with quorum_api, pytest.raises(LdapQuorumError, match="quorum mismatch"):
        quorum_api.get_users(["alice"])


def test_quorum_mismatch_not_retried(
    mocker: MockerFixture, quorum_api: LdapApi
) -> None:
    """LdapQuorumError propagates without triggering the outer failover retry."""
    search = mocker.patch.object(
        quorum_api._connection,
        "search",
        side_effect=[
            (True, {"result": 0}, [_ALICE_ENTRY, _BOB_ENTRY], None),
            (True, {"result": 0}, [_ALICE_ENTRY], None),
        ],
    )
    with quorum_api, pytest.raises(LdapQuorumError):
        quorum_api.get_users(["alice", "bob"])
    assert search.call_count == 2


def test_quorum_verification_server_unreachable_tries_next(
    mocker: MockerFixture,
) -> None:
    """A dead verification replica is skipped in favor of the next one."""

    def open_connection(strategy: BaseStrategy) -> None:
        connection = strategy.connection
        connection.server = connection.server_pool.get_server(connection)

    def start_tls(connection: Connection) -> None:
        connection.tls_started = True

    def bind(connection: Connection) -> None:
        connection.bound = True

    def unbind(connection: Connection) -> None:
        connection.bound = False
        connection.tls_started = False

    mocker.patch(
        "ldap3.strategy.sync.SyncStrategy.open",
        autospec=True,
        side_effect=open_connection,
    )
    mocker.patch(
        "ldap3.core.connection.Connection.start_tls",
        autospec=True,
        side_effect=start_tls,
    )
    mocker.patch(
        "ldap3.core.connection.Connection.bind", autospec=True, side_effect=bind
    )
    mocker.patch(
        "ldap3.core.connection.Connection.unbind", autospec=True, side_effect=unbind
    )
    mocker.patch("ldap3.core.pooling.randint", return_value=1)
    mocker.patch(
        "ldap3.core.server.Server.check_availability",
        side_effect=AssertionError("TCP prechecks must be disabled"),
    )
    api = LdapApi(
        server_urls=[
            "ldap://replica-a.example.com",
            "ldap://replica-b.example.com",
            "ldap://replica-c.example.com",
        ],
        base_dn="dc=example,dc=com",
        bind_dn="uid=svc,dc=example,dc=com",
        bind_password="secret",
        quorum_count=2,
    )
    search = mocker.patch.object(
        api._connection,
        "search",
        side_effect=[
            (True, {"result": 0}, [_ALICE_ENTRY], None),
            LDAPSocketReceiveError("connection reset"),
            (True, {"result": 0}, [_ALICE_ENTRY], None),
        ],
    )
    with api:
        assert api.get_users(["alice"]) == [LdapUser(username="alice")]
    assert search.call_count == 3


def test_quorum_all_verification_servers_unreachable_raises(
    mocker: MockerFixture, quorum_api: LdapApi
) -> None:
    """If no replica can confirm the primary result, fail closed."""
    mocker.patch.object(
        quorum_api._connection,
        "search",
        side_effect=[
            (True, {"result": 0}, [_ALICE_ENTRY], None),
            LDAPSocketReceiveError("connection reset"),
        ],
    )
    with quorum_api, pytest.raises(LdapQuorumError, match="Cannot achieve quorum"):
        quorum_api.get_users(["alice"])


def test_quorum_disabled_by_default_single_query(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Default quorum_count=1 performs no verification query."""
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0},
        [_ALICE_ENTRY],
        None,
    )
    with ldap_api:
        assert ldap_api.get_users(["alice"]) == [LdapUser(username="alice")]
    assert mock_ldap3.connection.search.call_count == 1


def test_quorum_degrades_with_too_few_servers(
    mocker: MockerFixture, mock_ldap3: MagicMock
) -> None:
    """quorum_count > number of configured servers disables quorum with a warning."""
    mock_ldap3.connection.search.return_value = (
        True,
        {"result": 0},
        [_ALICE_ENTRY],
        None,
    )
    warning = mocker.patch("qontract_utils.ldap_api.api.logger.warning")
    api = LdapApi(
        server_urls=["ldap://ldap.example.com"],
        base_dn="dc=example,dc=com",
        quorum_count=2,
    )
    with api:
        assert api.get_users(["alice"]) == [LdapUser(username="alice")]
    assert mock_ldap3.connection.search.call_count == 1
    warning.assert_called_once()


@pytest.mark.parametrize(
    "call",
    [
        lambda api: api.get_users(["alice"]),
        lambda api: api.get_group_members(["cn=group1,dc=example,dc=com"]),
        lambda api: api.check_groups_exist(["group1"]),
        lambda api: api.get_github_usernames(),
    ],
)
def test_quorum_applies_to_all_search_methods(
    mocker: MockerFixture, quorum_api: LdapApi, call: object
) -> None:
    """Every public search method is verified against a second replica."""
    mocker.patch.object(
        quorum_api._connection,
        "search",
        side_effect=[
            (True, {"result": 0}, [_ALICE_ENTRY, _BOB_ENTRY], None),
            (True, {"result": 0}, [_ALICE_ENTRY], None),
        ],
    )
    with quorum_api, pytest.raises(LdapQuorumError):
        call(quorum_api)  # type: ignore[operator]

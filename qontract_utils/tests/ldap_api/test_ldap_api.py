"""Tests for LDAP API client (Layer 1)."""

# ruff: noqa: ARG001
from collections.abc import Generator
from unittest.mock import MagicMock, call, patch

import pytest
from pydantic import ValidationError
from qontract_utils.hooks import Hooks
from qontract_utils.ldap_api.api import LdapApi, LdapApiCallContext, LdapApiError
from qontract_utils.ldap_api.models import LdapGroupMembers, LdapUser


@pytest.fixture
def mock_ldap3() -> Generator[MagicMock, None, None]:
    """Mock ldap3 module."""
    with (
        patch("qontract_utils.ldap_api.api.Server") as mock_server,
        patch("qontract_utils.ldap_api.api.Connection") as mock_connection,
    ):
        # Yield a namespace with both mocks
        mock = MagicMock()
        mock.server = mock_server
        mock.connection_cls = mock_connection
        mock.connection = mock_connection.return_value
        yield mock


@pytest.fixture
def ldap_api(mock_ldap3: MagicMock) -> LdapApi:
    """Create LdapApi with mocked ldap3."""
    return LdapApi(
        server_url="ldap://ldap.example.com",
        base_dn="dc=example,dc=com",
        bind_dn="uid=svc-account,cn=users,dc=example,dc=com",
        bind_password="secret",
    )


@pytest.fixture
def ldap_api_anonymous(mock_ldap3: MagicMock) -> LdapApi:
    """Create LdapApi with anonymous bind."""
    return LdapApi(
        server_url="ldap://ldap.example.com",
        base_dn="dc=example,dc=com",
    )


# --- Constructor ---


def test_ldap_api_stores_base_dn(ldap_api: LdapApi) -> None:
    """Test constructor stores base_dn."""
    assert ldap_api.base_dn == "dc=example,dc=com"


def test_ldap_api_creates_server(mock_ldap3: MagicMock, ldap_api: LdapApi) -> None:
    """Test constructor creates ldap3 Server."""
    from ldap3 import NONE

    mock_ldap3.server.assert_called_once_with("ldap://ldap.example.com", get_info=NONE)


def test_ldap_api_creates_connection_with_credentials(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test constructor creates ldap3 Connection with bind credentials."""
    mock_ldap3.connection_cls.assert_called_once_with(
        server=mock_ldap3.server.return_value,
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
        server=mock_ldap3.server.return_value,
        user=None,
        password=None,
        client_strategy="SAFE_SYNC",
        receive_timeout=30,
        raise_exceptions=True,
    )


# --- Context Manager ---


def test_ldap_api_context_manager_binds(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test __enter__ calls connection.bind()."""
    with ldap_api:
        mock_ldap3.connection.bind.assert_called_once()


def test_ldap_api_context_manager_unbinds(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test __exit__ calls connection.unbind()."""
    with ldap_api:
        pass
    mock_ldap3.connection.unbind.assert_called_once()


def test_ldap_api_context_manager_start_tls(mock_ldap3: MagicMock) -> None:
    """Test __enter__ calls start_tls() when enabled."""
    api = LdapApi(
        server_url="ldap://ldap.example.com",
        base_dn="dc=example,dc=com",
        bind_dn="uid=svc,dc=example,dc=com",
        bind_password="secret",
        start_tls=True,
    )
    with api:
        pass
    mock_ldap3.connection.assert_has_calls(
        [call.start_tls(), call.bind()],
        any_order=False,
    )


def test_ldap_api_context_manager_no_start_tls_by_default(
    mock_ldap3: MagicMock, ldap_api: LdapApi
) -> None:
    """Test __enter__ does NOT call start_tls() by default."""
    with ldap_api:
        mock_ldap3.connection.start_tls.assert_not_called()


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
    assert call_args[0][0] == "dc=example,dc=com"
    filter_str = call_args[0][1]
    assert "(objectclass=person)" in filter_str
    assert "(uid=alice)" in filter_str
    assert "(uid=bob)" in filter_str


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

    with ldap_api, pytest.raises(LdapApiError, match="LDAP search failed"):
        ldap_api.get_users(["alice"])


# --- Hooks ---


def test_ldap_api_pre_hooks_includes_builtins(mock_ldap3: MagicMock) -> None:
    """Test that built-in hooks (metrics, logging, latency) are included."""
    api = LdapApi(
        server_url="ldap://ldap.example.com",
        base_dn="dc=example,dc=com",
    )
    # Should have metrics, request_log, latency_start
    assert len(api._hooks.pre_hooks) >= 3


def test_ldap_api_custom_hooks_merged(mock_ldap3: MagicMock) -> None:
    """Test custom hooks are merged with built-in hooks."""
    custom_hook = MagicMock()
    api = LdapApi(
        server_url="ldap://ldap.example.com",
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


def test_ldap_group_members_model_frozen() -> None:
    """Test LdapGroupMembers is immutable."""
    group = LdapGroupMembers(
        dn="cn=admins,dc=example,dc=com", members=frozenset({"alice"})
    )
    assert group.dn == "cn=admins,dc=example,dc=com"
    assert group.members == frozenset({"alice"})
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

    with ldap_api, pytest.raises(LdapApiError, match="LDAP search failed"):
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

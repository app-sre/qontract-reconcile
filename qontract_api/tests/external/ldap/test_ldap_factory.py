"""Tests for LdapWorkspaceClient factory."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from qontract_api.config import LdapSettings, Settings
from qontract_api.external.ldap.ldap_factory import create_ldap_workspace_client
from qontract_api.external.ldap.ldap_workspace_client import LdapWorkspaceClient
from qontract_api.external.ldap.schemas import LdapDirectSecret


def _build_secret() -> LdapDirectSecret:
    return LdapDirectSecret(
        secret_manager_url="https://vault.example.com",
        path="app-sre/creds/ldap",
        field="bind_password",
        server_urls=["ldap://freeipa.example.com", "ldap://replica.example.com"],
        base_dn="dc=example,dc=com",
    )


@patch("qontract_api.external.ldap.ldap_factory.LdapApi")
def test_creates_ldap_api_with_credentials(mock_ldap_api: MagicMock) -> None:
    """Test factory resolves credentials from Vault and passes to LdapApi."""
    secret_manager = MagicMock()
    secret_manager.read_all.return_value = {
        "bind_dn": "uid=svc,dc=example,dc=com",
        "bind_password": "secret123",
    }

    create_ldap_workspace_client(
        secret=_build_secret(),
        cache=MagicMock(),
        secret_manager=secret_manager,
        settings=Settings(ldap=LdapSettings()),
    )

    mock_ldap_api.assert_called_once_with(
        server_urls=["ldap://freeipa.example.com", "ldap://replica.example.com"],
        base_dn="dc=example,dc=com",
        bind_dn="uid=svc,dc=example,dc=com",
        bind_password="secret123",
        start_tls=True,
        quorum_count=2,
    )


@patch("qontract_api.external.ldap.ldap_factory.LdapApi")
def test_passes_configured_quorum_count(mock_ldap_api: MagicMock) -> None:
    """The settings.ldap.quorum_count value flows through to LdapApi."""
    secret_manager = MagicMock()
    secret_manager.read_all.return_value = {
        "bind_dn": "uid=svc,dc=example,dc=com",
        "bind_password": "secret123",
    }

    create_ldap_workspace_client(
        secret=_build_secret(),
        cache=MagicMock(),
        secret_manager=secret_manager,
        settings=Settings(ldap=LdapSettings(quorum_count=3)),
    )

    assert mock_ldap_api.call_args.kwargs["quorum_count"] == 3


@patch("qontract_api.external.ldap.ldap_factory.LdapApi")
def test_returns_workspace_client(mock_ldap_api: MagicMock) -> None:
    """Test factory returns a LdapWorkspaceClient instance."""
    secret_manager = MagicMock()
    secret_manager.read_all.return_value = {
        "bind_dn": "uid=svc,dc=example,dc=com",
        "bind_password": "secret123",
    }

    result = create_ldap_workspace_client(
        secret=_build_secret(),
        cache=MagicMock(),
        secret_manager=secret_manager,
        settings=Settings(ldap=LdapSettings()),
    )

    assert isinstance(result, LdapWorkspaceClient)


@patch("qontract_api.external.ldap.ldap_factory.LdapApi")
def test_cache_key_prefix_is_deterministic(mock_ldap_api: MagicMock) -> None:
    """The replica set and base DN define a deterministic cache namespace."""
    secret_manager = MagicMock()
    secret_manager.read_all.return_value = {
        "bind_dn": "uid=svc,dc=example,dc=com",
        "bind_password": "secret123",
    }
    cache = MagicMock()
    settings = Settings(ldap=LdapSettings())

    client1 = create_ldap_workspace_client(
        secret=_build_secret(),
        cache=cache,
        secret_manager=secret_manager,
        settings=settings,
    )
    client2 = create_ldap_workspace_client(
        secret=_build_secret(),
        cache=cache,
        secret_manager=secret_manager,
        settings=settings,
    )

    assert client1.cache_key_prefix == client2.cache_key_prefix
    assert client1.cache_key_prefix != ""


@patch("qontract_api.external.ldap.ldap_factory.LdapApi")
def test_replica_order_does_not_change_cache_namespace(
    mock_ldap_api: MagicMock,
) -> None:
    secret_manager = MagicMock()
    secret_manager.read_all.return_value = {
        "bind_dn": "uid=svc",
        "bind_password": "secret",
    }
    clients = [
        create_ldap_workspace_client(
            secret=LdapDirectSecret(
                secret_manager_url="https://vault.example.com",
                path="app-sre/creds/ldap",
                server_urls=urls,
                base_dn="dc=example,dc=com",
            ),
            cache=MagicMock(),
            secret_manager=secret_manager,
            settings=Settings(),
        )
        for urls in (
            ["ldap://a.example.com", "ldap://b.example.com"],
            ["ldap://b.example.com", "ldap://a.example.com"],
            ["ldap://c.example.com"],
        )
    ]
    assert clients[0].cache_key_prefix == clients[1].cache_key_prefix
    assert clients[0].cache_key_prefix != clients[2].cache_key_prefix


@pytest.mark.parametrize("urls", [[], [""], [" "]])
def test_secret_rejects_empty_replica_urls(urls: list[str]) -> None:
    with pytest.raises(ValidationError, match="server_urls"):
        LdapDirectSecret(
            secret_manager_url="https://vault.example.com",
            path="app-sre/creds/ldap",
            server_urls=urls,
            base_dn="dc=example,dc=com",
        )

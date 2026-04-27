"""Tests for LdapWorkspaceClient factory."""

from unittest.mock import MagicMock, patch

from qontract_api.config import LdapSettings, Settings
from qontract_api.external.ldap.ldap_factory import create_ldap_workspace_client
from qontract_api.external.ldap.ldap_workspace_client import LdapWorkspaceClient
from qontract_api.external.ldap.schemas import LdapDirectSecret


def _build_secret() -> LdapDirectSecret:
    return LdapDirectSecret(
        secret_manager_url="https://vault.example.com",
        path="app-sre/creds/ldap",
        field="bind_password",
        server_url="ldap://freeipa.example.com",
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
        server_url="ldap://freeipa.example.com",
        base_dn="dc=example,dc=com",
        bind_dn="uid=svc,dc=example,dc=com",
        bind_password="secret123",
        start_tls=True,
    )


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
    """Test factory generates deterministic cache key prefix from server_url + base_dn."""
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

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from qontract_api_client.schemas import (
    LdapGroupMember,
    LdapGroupMembersResponse,
    LdapGroupResult,
)

from reconcile.gql_definitions.common.ldap_settings import LdapSettingsV1
from reconcile.gql_definitions.fragments.membership_source import (
    MembershipProviderSourceV1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils.membershipsources.ldap_resolver import (
    create_ldap_membership_resolver,
    create_ldap_membership_resolver_sync,
)

_MOD = "reconcile.utils.membershipsources.ldap_resolver"


def _ldap_settings(*, with_credentials: bool = True) -> LdapSettingsV1:
    return LdapSettingsV1(
        serverUrl="ldap://freeipa.example.com",
        baseDn="dc=example,dc=com",
        credentials=VaultSecret(
            path="secret/ldap/bind",
            field="password",
            version=None,
            format=None,
            url=None,
        )
        if with_credentials
        else None,
    )


def test_create_ldap_membership_resolver_does_not_raise_eagerly() -> None:
    """Building the resolver must not require credentials up front.

    Callers (e.g. slack-usergroups-api) always pass ldap_settings, even for
    roles with no LDAP memberSources - the credentials check must only
    happen if the resolver is actually invoked.
    """
    create_ldap_membership_resolver(
        _ldap_settings(with_credentials=False), "https://vault.example.com"
    )


@pytest.mark.asyncio
async def test_resolve_raises_when_credentials_missing() -> None:
    resolver = create_ldap_membership_resolver(
        _ldap_settings(with_credentials=False), "https://vault.example.com"
    )
    with pytest.raises(RuntimeError, match="LDAP credentials not found"):
        await resolver(
            "corp-ldap", MembershipProviderSourceV1(provider="ldap"), {"team-a"}
        )


@pytest.mark.asyncio
async def test_resolve_calls_endpoint_and_maps_result() -> None:
    resolver = create_ldap_membership_resolver(
        _ldap_settings(), "https://vault.example.com"
    )

    with patch(f"{_MOD}.ldap_group_members", new_callable=AsyncMock) as mock_client:
        mock_client.return_value = LdapGroupMembersResponse(
            groups=[
                LdapGroupResult(
                    group="team-a",
                    members=[
                        LdapGroupMember(
                            org_username="alice", github_username="alicegh"
                        ),
                        LdapGroupMember(org_username="bob"),
                    ],
                )
            ]
        )
        result = await resolver(
            "corp-ldap", MembershipProviderSourceV1(provider="ldap"), {"team-a"}
        )

    assert ("corp-ldap", "team-a") in result
    assert {m.org_username for m in result["corp-ldap", "team-a"]} == {"alice", "bob"}
    mock_client.assert_called_once()
    request = mock_client.call_args[0][0]
    assert request.groups == ["team-a"]
    assert request.secret.server_url == "ldap://freeipa.example.com"
    assert request.secret.base_dn == "dc=example,dc=com"
    assert request.secret.secret_manager_url == "https://vault.example.com"


@pytest.mark.asyncio
async def test_resolve_omits_unresolved_groups() -> None:
    """A group absent from the response (unresolved) stays absent in the result."""
    resolver = create_ldap_membership_resolver(
        _ldap_settings(), "https://vault.example.com"
    )

    with patch(f"{_MOD}.ldap_group_members", new_callable=AsyncMock) as mock_client:
        mock_client.return_value = LdapGroupMembersResponse(groups=[])
        result = await resolver(
            "corp-ldap", MembershipProviderSourceV1(provider="ldap"), {"ghost-team"}
        )

    assert result == {}


def test_create_ldap_membership_resolver_sync_wraps_async_resolver() -> None:
    """The sync factory is dependency-injected - ldap_settings and
    secret_manager_url come from the caller, never fetched from global
    state inside ldap_resolver.py."""
    with patch(f"{_MOD}.ldap_group_members", new_callable=AsyncMock) as mock_client:
        mock_client.return_value = LdapGroupMembersResponse(
            groups=[
                LdapGroupResult(
                    group="team-a", members=[LdapGroupMember(org_username="alice")]
                )
            ]
        )
        resolve = create_ldap_membership_resolver_sync(
            _ldap_settings(), "https://vault.example.com"
        )
        result = resolve(
            "corp-ldap", MembershipProviderSourceV1(provider="ldap"), {"team-a"}
        )

    assert {m.org_username for m in result["corp-ldap", "team-a"]} == {"alice"}

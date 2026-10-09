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
                            name="alice",
                            org_username="alice",
                            github_username="alicegh",
                        ),
                        LdapGroupMember(name="bob", org_username="bob"),
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
async def test_resolve_raises_for_unresolved_group() -> None:
    """A group absent from the response (unresolved) must fail closed.

    The endpoint omits a group entirely when it doesn't exist in LDAP; the
    resolver must not treat that omission as if the group were confirmed
    empty, since that would silently remove real members from whatever
    role/usergroup depends on it.
    """
    resolver = create_ldap_membership_resolver(
        _ldap_settings(), "https://vault.example.com"
    )

    with patch(f"{_MOD}.ldap_group_members", new_callable=AsyncMock) as mock_client:
        mock_client.return_value = LdapGroupMembersResponse(groups=[])
        with pytest.raises(RuntimeError, match="ghost-team"):
            await resolver(
                "corp-ldap", MembershipProviderSourceV1(provider="ldap"), {"ghost-team"}
            )


@pytest.mark.asyncio
async def test_resolve_confirmed_empty_group_does_not_raise() -> None:
    """A group present in the response with no members is confirmed empty,
    not unresolved - this must not raise."""
    resolver = create_ldap_membership_resolver(
        _ldap_settings(), "https://vault.example.com"
    )

    with patch(f"{_MOD}.ldap_group_members", new_callable=AsyncMock) as mock_client:
        mock_client.return_value = LdapGroupMembersResponse(
            groups=[LdapGroupResult(group="empty-team", members=[])]
        )
        result = await resolver(
            "corp-ldap", MembershipProviderSourceV1(provider="ldap"), {"empty-team"}
        )

    assert result == {("corp-ldap", "empty-team"): []}


@pytest.mark.asyncio
async def test_resolve_raises_naming_only_the_unresolved_groups() -> None:
    """When some requested groups resolve and others don't, only the
    unresolved ones are named in the error - a partial failure must not be
    reported as if every group were missing."""
    resolver = create_ldap_membership_resolver(
        _ldap_settings(), "https://vault.example.com"
    )

    with patch(f"{_MOD}.ldap_group_members", new_callable=AsyncMock) as mock_client:
        mock_client.return_value = LdapGroupMembersResponse(
            groups=[LdapGroupResult(group="team-a", members=[])]
        )
        with pytest.raises(RuntimeError) as exc_info:
            await resolver(
                "corp-ldap",
                MembershipProviderSourceV1(provider="ldap"),
                {"team-a", "ghost-team"},
            )

    assert "ghost-team" in str(exc_info.value)
    assert "team-a" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_resolve_preserves_requested_group_casing() -> None:
    """The result key must use the requested spelling, not the stored one.

    LDAP CN matching is case-insensitive, so the endpoint can return a group
    using its stored spelling (e.g. "team-a") even though the caller
    requested a different casing (e.g. "Team-A", as configured in
    app-interface). resolve_role() looks members up by the *requested*
    spelling, so returning the stored spelling here would make a genuinely
    resolved group look both missing (spurious fail-closed RuntimeError) and,
    if that check didn't exist, silently empty.
    """
    resolver = create_ldap_membership_resolver(
        _ldap_settings(), "https://vault.example.com"
    )

    with patch(f"{_MOD}.ldap_group_members", new_callable=AsyncMock) as mock_client:
        mock_client.return_value = LdapGroupMembersResponse(
            groups=[
                LdapGroupResult(
                    group="team-a",  # stored spelling, different case
                    members=[LdapGroupMember(name="alice", org_username="alice")],
                )
            ]
        )
        result = await resolver(
            "corp-ldap", MembershipProviderSourceV1(provider="ldap"), {"Team-A"}
        )

    assert ("corp-ldap", "Team-A") in result
    assert {m.org_username for m in result["corp-ldap", "Team-A"]} == {"alice"}


@pytest.mark.asyncio
async def test_resolve_rejects_case_duplicate_group_names() -> None:
    """Two requested spellings normalizing to the same LDAP CN are rejected
    up front, before the endpoint is even called.

    `groups` is batched across every role sharing a provider name
    (build_resolver_jobs), so two roles configuring the same LDAP group with
    different casing (e.g. "Team-A" and "team-a") can land in the same
    request set. Mapping both to a single result key is ambiguous (which
    spelling wins?) - reject explicitly instead of silently picking one.
    """
    resolver = create_ldap_membership_resolver(
        _ldap_settings(), "https://vault.example.com"
    )

    with patch(f"{_MOD}.ldap_group_members", new_callable=AsyncMock) as mock_client:
        with pytest.raises(RuntimeError, match="Team-A"):
            await resolver(
                "corp-ldap",
                MembershipProviderSourceV1(provider="ldap"),
                {"Team-A", "team-a"},
            )
        mock_client.assert_not_called()


def test_create_ldap_membership_resolver_sync_wraps_async_resolver() -> None:
    """The sync factory is dependency-injected - ldap_settings and
    secret_manager_url come from the caller, never fetched from global
    state inside ldap_resolver.py."""
    with patch(f"{_MOD}.ldap_group_members", new_callable=AsyncMock) as mock_client:
        mock_client.return_value = LdapGroupMembersResponse(
            groups=[
                LdapGroupResult(
                    group="team-a",
                    members=[LdapGroupMember(name="alice", org_username="alice")],
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

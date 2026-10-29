"""Tests for the github-username-sync integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from collections.abc import Generator

import pytest
from qontract_api_client.schemas import (
    FileSyncResponse,
    FileSyncStatus,
    FileSyncUpdate,
    GithubAccountType,
    GithubUserInfo,
    GithubUsersValidateResponse,
    LdapOrgGithubUser,
    LdapOrgGithubUsernamesResponse,
)
from qontract_utils.vcs import Provider

from reconcile.github_username_sync.integration import (
    GithubUsernameSyncIntegration,
    GithubUsernameSyncParams,
    _find_default_github_secret,
    _find_vcs_secret,
    compute_updates,
)
from reconcile.github_username_sync.models import GithubUsernameUpdate
from reconcile.gql_definitions.common.github_orgs import GithubOrgV1
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.github_username_sync.users import (
    GithubUsernameSyncUsersQueryData,
    UserV1,
)
from reconcile.typed_queries.vcs import Vcs
from reconcile.utils.mr.labels import SHOW_SELF_SERVICEABLE_IN_REVIEW_QUEUE

# --- compute_updates ---


def _make_user(org_username: str, github_username: str) -> UserV1:
    return UserV1(
        path=f"/access/users/{org_username}.yml",
        org_username=org_username,
        github_username=github_username,
    )


def test_compute_updates_flags_drifted_user() -> None:
    """A genuinely different LDAP-linked login is proposed as an update."""
    users = [_make_user("alice", "alice-old")]

    updates = compute_updates(users, {"alice": "alice-new"})

    assert updates == [
        GithubUsernameUpdate(
            org_username="alice",
            path="data/access/users/alice.yml",
            current_github_username="alice-old",
            github_username="alice-new",
        )
    ]


def test_compute_updates_normalizes_path_to_repo_root() -> None:
    """The GraphQL schema-relative path is normalized to the repo-root path
    expected by the VCS API, mirroring ldap-users-api's PathSpec normalization.
    """
    users = [_make_user("alice", "alice-old")]

    updates = compute_updates(users, {"alice": "alice-new"})

    assert updates[0].path == "data/access/users/alice.yml"


def test_compute_updates_corrects_case_only_difference() -> None:
    """A case-only mismatch IS corrected - the mapping now carries GitHub's own
    canonical casing (validated via the GitHub API), not LDAP's lowercased login.
    """
    users = [_make_user("bob", "bob123")]

    updates = compute_updates(users, {"bob": "Bob123"})

    assert updates == [
        GithubUsernameUpdate(
            org_username="bob",
            path="data/access/users/bob.yml",
            current_github_username="bob123",
            github_username="Bob123",
        )
    ]


def test_compute_updates_skips_in_sync_user() -> None:
    """A user whose value already matches LDAP produces no update."""
    users = [_make_user("carol", "carol-gh")]

    updates = compute_updates(users, {"carol": "carol-gh"})

    assert updates == []


def test_compute_updates_skips_user_without_ldap_mapping() -> None:
    """A user with no LDAP-linked GitHub account is left untouched."""
    users = [_make_user("dave", "dave-gh")]

    updates = compute_updates(users, {})

    assert updates == []


def test_compute_updates_mixed_users() -> None:
    """Only the genuinely drifted users among several are flagged."""
    users = [
        _make_user("alice", "alice-old"),
        _make_user("bob", "bob123"),
        _make_user("carol", "carol-gh"),
        _make_user("dave", "dave-gh"),
    ]
    github_map = {"alice": "alice-new", "bob": "Bob123", "carol": "carol-gh"}

    updates = compute_updates(users, github_map)

    assert [u.org_username for u in updates] == ["alice", "bob"]


# --- _find_vcs_secret ---


def _make_vcs(name: str, url: str) -> Vcs:
    return Vcs(
        name=name,
        url=url,
        token=VaultSecret(
            path="secret/vcs/token", field="token", version=1, format=None, url=None
        ),
        provider=Provider.GITLAB,
    )


def test_find_vcs_secret_found() -> None:
    """_find_vcs_secret finds the matching VCS instance by URL prefix."""
    vcs_instances = [
        _make_vcs("gitlab-cee", "https://gitlab.cee.redhat.com"),
        _make_vcs("github", "https://github.com"),
    ]

    secret = _find_vcs_secret(
        "https://vault.example.com",
        vcs_instances,
        "https://gitlab.cee.redhat.com/service/app-interface",
    )

    assert secret.secret_manager_url == "https://vault.example.com"
    assert secret.path == "secret/vcs/token"
    assert secret.field == "token"


def test_find_vcs_secret_not_found() -> None:
    """_find_vcs_secret raises ValueError when no VCS instance matches."""
    vcs_instances = [_make_vcs("github", "https://github.com")]

    with pytest.raises(ValueError, match="No VCS instance found"):
        _find_vcs_secret(
            "https://vault.example.com",
            vcs_instances,
            "https://gitlab.cee.redhat.com/service/app-interface",
        )


# --- _find_default_github_secret ---


def _make_github_org(
    name: str, *, default: bool | None, vault_path: str = "secret/github/token"
) -> GithubOrgV1:
    return GithubOrgV1(
        name=name,
        token=VaultSecret(
            path=vault_path, field="token", version=1, format=None, url=None
        ),
        default=default,
        managedTeams=None,
    )


def test_find_default_github_secret_found() -> None:
    """_find_default_github_secret finds the org flagged as default."""
    github_orgs = [
        _make_github_org("other-org", default=False, vault_path="secret/other"),
        _make_github_org("app-sre", default=True, vault_path="secret/app-sre"),
    ]

    with patch(f"{_MOD}.get_github_orgs", return_value=github_orgs):
        secret = _find_default_github_secret("https://vault.example.com")

    assert secret.secret_manager_url == "https://vault.example.com"
    assert secret.path == "secret/app-sre"
    assert secret.field == "token"


def test_find_default_github_secret_not_found() -> None:
    """_find_default_github_secret raises ValueError when no org is flagged default."""
    github_orgs = [_make_github_org("other-org", default=False)]

    with (
        patch(f"{_MOD}.get_github_orgs", return_value=github_orgs),
        pytest.raises(ValueError, match="No default GitHub org configured"),
    ):
        _find_default_github_secret("https://vault.example.com")


# --- async_run ---

_MOD = "reconcile.github_username_sync.integration"
_APP_REPO = "https://gitlab.example.com/service/app-interface"


def _ldap_settings() -> MagicMock:
    settings = MagicMock()
    settings.server_urls = ["ldap://freeipa.example.com", "ldap://replica.example.com"]
    settings.base_dn = "dc=example,dc=com"
    settings.credentials = VaultSecret(
        path="secret/ldap", field="all", version=1, format=None, url=None
    )
    return settings


def _ldap_response(mapping: dict[str, str]) -> LdapOrgGithubUsernamesResponse:
    return LdapOrgGithubUsernamesResponse(
        users=[
            LdapOrgGithubUser(org_username=org, github_username=gh)
            for org, gh in mapping.items()
        ]
    )


def _vcs_instances() -> list[Vcs]:
    return [_make_vcs("gitlab", "https://gitlab.example.com")]


def _users_data(users: list[UserV1]) -> GithubUsernameSyncUsersQueryData:
    return GithubUsernameSyncUsersQueryData(users=users)


def _github_orgs() -> list[GithubOrgV1]:
    return [_make_github_org("app-sre", default=True)]


def _github_validate_response(logins: list[str]) -> GithubUsersValidateResponse:
    """A GitHub validate response where every requested login exists verbatim.

    Use this when the test doesn't care about case correction, only that the
    LDAP-linked login round-trips through GitHub validation unchanged.
    """
    return GithubUsersValidateResponse(
        users=[
            GithubUserInfo(login=login, type_=GithubAccountType.USER)
            for login in logins
        ]
    )


@pytest.fixture(autouse=True)
def _patch_secret_manager_url() -> Generator[None]:
    """Patch the secret_manager_url property for all integration instances."""
    with patch.object(
        GithubUsernameSyncIntegration,
        "secret_manager_url",
        new_callable=lambda: property(lambda self: "https://vault.example.com"),
    ):
        yield


def _make_integration(auto_merge_threshold: int = 10) -> GithubUsernameSyncIntegration:
    return GithubUsernameSyncIntegration(
        GithubUsernameSyncParams(
            app_interface_repo_url=_APP_REPO,
            labels=["github-username-sync"],
            auto_merge_threshold=auto_merge_threshold,
        )
    )


@pytest.fixture
def integration() -> GithubUsernameSyncIntegration:
    """Create integration instance with the default auto-merge threshold."""
    return _make_integration()


@pytest.mark.asyncio
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.query_users")
async def test_async_run_no_users_returns_early(
    mock_query: MagicMock,
    mock_gql: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    integration: GithubUsernameSyncIntegration,
) -> None:
    """If GraphQL returns no users, return immediately without touching LDAP settings."""
    mock_query.return_value = _users_data([])

    await integration.async_run(dry_run=False)

    mock_settings.assert_not_called()


@pytest.mark.asyncio
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.query_users")
async def test_async_run_missing_ldap_credentials(
    mock_query: MagicMock,
    mock_gql: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    integration: GithubUsernameSyncIntegration,
) -> None:
    """If LDAP credentials are missing, raise RuntimeError."""
    mock_query.return_value = _users_data([_make_user("alice", "alice-old")])
    settings = MagicMock()
    settings.credentials = None
    mock_settings.return_value = settings

    with pytest.raises(RuntimeError, match="LDAP credentials not found"):
        await integration.async_run(dry_run=False)


@pytest.mark.asyncio
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.ldap_org_github_usernames", new_callable=AsyncMock)
@patch(f"{_MOD}.query_users")
async def test_async_run_empty_ldap_result_returns_early(
    mock_query: MagicMock,
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    integration: GithubUsernameSyncIntegration,
) -> None:
    """An empty LDAP mapping is harmless here (unlike ldap-users-api): no updates
    and no abort - every user is simply reported as unresolved and left untouched.
    """
    mock_query.return_value = _users_data([_make_user("alice", "alice-old")])
    mock_settings.return_value = _ldap_settings()
    mock_ldap.return_value = _ldap_response({})

    await integration.async_run(dry_run=False)

    mock_vcs.assert_not_called()


@pytest.mark.asyncio
@patch(f"{_MOD}.github_users_validate", new_callable=AsyncMock)
@patch(f"{_MOD}.get_github_orgs")
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.ldap_org_github_usernames", new_callable=AsyncMock)
@patch(f"{_MOD}.query_users")
async def test_async_run_reports_unresolved_users(
    mock_query: MagicMock,
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    mock_github_orgs: MagicMock,
    mock_validate: AsyncMock,
    integration: GithubUsernameSyncIntegration,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Per the design doc, users with no unambiguous LDAP-linked GitHub account
    are reported (not silently dropped), whether or not any update is produced.
    """
    mock_query.return_value = _users_data([
        _make_user("alice", "alice-old"),
        _make_user("bob", "bob-gh"),
    ])
    mock_settings.return_value = _ldap_settings()
    mock_ldap.return_value = _ldap_response({"alice": "alice-new"})
    mock_github_orgs.return_value = _github_orgs()
    mock_validate.return_value = _github_validate_response(["alice-new"])

    with caplog.at_level(logging.WARNING):
        await integration.async_run(dry_run=True)

    assert any(
        "bob" in record.message and "unambiguous" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
@patch(f"{_MOD}.github_users_validate", new_callable=AsyncMock)
@patch(f"{_MOD}.get_github_orgs")
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.ldap_org_github_usernames", new_callable=AsyncMock)
@patch(f"{_MOD}.query_users")
async def test_async_run_no_drifted_users_returns_early(
    mock_query: MagicMock,
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    mock_github_orgs: MagicMock,
    mock_validate: AsyncMock,
    integration: GithubUsernameSyncIntegration,
) -> None:
    """If every user is already in sync with LDAP, do nothing."""
    mock_query.return_value = _users_data([_make_user("alice", "alice-gh")])
    mock_settings.return_value = _ldap_settings()
    mock_ldap.return_value = _ldap_response({"alice": "alice-gh"})
    mock_github_orgs.return_value = _github_orgs()
    mock_validate.return_value = _github_validate_response(["alice-gh"])

    await integration.async_run(dry_run=False)

    mock_vcs.assert_not_called()


@pytest.mark.asyncio
@patch(f"{_MOD}.github_users_validate", new_callable=AsyncMock)
@patch(f"{_MOD}.get_github_orgs")
@patch(f"{_MOD}.build_github_username_update_operations", new_callable=AsyncMock)
@patch(f"{_MOD}.vcs_file_sync", new_callable=AsyncMock)
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.ldap_org_github_usernames", new_callable=AsyncMock)
@patch(f"{_MOD}.query_users")
async def test_async_run_dry_run_stops_after_logging(
    mock_query: MagicMock,
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    mock_file_sync: AsyncMock,
    mock_build: AsyncMock,
    mock_github_orgs: MagicMock,
    mock_validate: AsyncMock,
    integration: GithubUsernameSyncIntegration,
) -> None:
    """Dry-run exits right after logging proposed updates: no VCS instance lookup,
    no Unleash check, and no file fetch/sync at all.
    """
    mock_query.return_value = _users_data([_make_user("alice", "alice-old")])
    mock_settings.return_value = _ldap_settings()
    mock_ldap.return_value = _ldap_response({"alice": "alice-new"})
    mock_github_orgs.return_value = _github_orgs()
    mock_validate.return_value = _github_validate_response(["alice-new"])

    await integration.async_run(dry_run=True)

    mock_vcs.assert_not_called()
    mock_toggle.assert_not_called()
    mock_build.assert_not_called()
    mock_file_sync.assert_not_called()


@pytest.mark.asyncio
@patch(f"{_MOD}.github_users_validate", new_callable=AsyncMock)
@patch(f"{_MOD}.get_github_orgs")
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.ldap_org_github_usernames", new_callable=AsyncMock)
@patch(f"{_MOD}.query_users")
async def test_async_run_corrects_case_via_github_validation(
    mock_query: MagicMock,
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    mock_github_orgs: MagicMock,
    mock_validate: AsyncMock,
    integration: GithubUsernameSyncIntegration,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A case-only mismatch is corrected using GitHub's canonical login, which
    LDAP alone (always lowercased) could never provide.
    """
    mock_query.return_value = _users_data([_make_user("alice", "alicesmith")])
    mock_settings.return_value = _ldap_settings()
    mock_ldap.return_value = _ldap_response({"alice": "alicesmith"})
    mock_github_orgs.return_value = _github_orgs()
    mock_validate.return_value = _github_validate_response(["AliceSmith"])

    with caplog.at_level(logging.INFO):
        await integration.async_run(dry_run=True)

    mock_validate.assert_awaited_once()
    assert mock_validate.call_args.args[0].usernames == ["alicesmith"]
    assert any(
        "'alicesmith' -> 'AliceSmith'" in record.message for record in caplog.records
    )


@pytest.mark.asyncio
@patch(f"{_MOD}.github_users_validate", new_callable=AsyncMock)
@patch(f"{_MOD}.get_github_orgs")
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.ldap_org_github_usernames", new_callable=AsyncMock)
@patch(f"{_MOD}.query_users")
async def test_async_run_skips_nonexistent_github_account(
    mock_query: MagicMock,
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    mock_github_orgs: MagicMock,
    mock_validate: AsyncMock,
    integration: GithubUsernameSyncIntegration,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An LDAP-linked login that doesn't exist on GitHub (stale/wrong data) is
    not proposed as an update - and is reported, not silently dropped.
    """
    mock_query.return_value = _users_data([_make_user("alice", "alice-old")])
    mock_settings.return_value = _ldap_settings()
    mock_ldap.return_value = _ldap_response({"alice": "mnovak1"})
    mock_github_orgs.return_value = _github_orgs()
    mock_validate.return_value = _github_validate_response([])  # 404 on GitHub

    with caplog.at_level(logging.WARNING):
        await integration.async_run(dry_run=True)

    mock_vcs.assert_not_called()
    assert any(
        "mnovak1" in record.message and "does not exist" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
@patch(f"{_MOD}.github_users_validate", new_callable=AsyncMock)
@patch(f"{_MOD}.get_github_orgs")
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.ldap_org_github_usernames", new_callable=AsyncMock)
@patch(f"{_MOD}.query_users")
async def test_async_run_requests_user_account_type_only(
    mock_query: MagicMock,
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    mock_github_orgs: MagicMock,
    mock_validate: AsyncMock,
    integration: GithubUsernameSyncIntegration,
) -> None:
    """The integration requests only personal accounts (not organizations) from
    the GitHub validation endpoint - an org-linked rhatSocialURL must not be
    treated as a valid github_username.
    """
    mock_query.return_value = _users_data([_make_user("alice", "alice-old")])
    mock_settings.return_value = _ldap_settings()
    mock_ldap.return_value = _ldap_response({"alice": "app-sre"})
    mock_github_orgs.return_value = _github_orgs()
    mock_validate.return_value = _github_validate_response([])  # filtered server-side

    await integration.async_run(dry_run=True)

    request = mock_validate.call_args.args[0]
    assert request.account_type == GithubAccountType.USER


@pytest.mark.asyncio
@patch(f"{_MOD}.github_users_validate", new_callable=AsyncMock)
@patch(f"{_MOD}.get_github_orgs")
@patch(f"{_MOD}.build_github_username_update_operations", new_callable=AsyncMock)
@patch(f"{_MOD}.vcs_file_sync", new_callable=AsyncMock)
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.ldap_org_github_usernames", new_callable=AsyncMock)
@patch(f"{_MOD}.query_users")
async def test_async_run_creates_mr_for_single_update(
    mock_query: MagicMock,
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    mock_file_sync: AsyncMock,
    mock_build: AsyncMock,
    mock_github_orgs: MagicMock,
    mock_validate: AsyncMock,
    integration: GithubUsernameSyncIntegration,
) -> None:
    """A single drifted user produces exactly one MR with one file operation,
    with auto-merge off since the Unleash toggle defaults to False.
    """
    mock_query.return_value = _users_data([_make_user("alice", "alice-old")])
    mock_settings.return_value = _ldap_settings()
    mock_vcs.return_value = _vcs_instances()
    mock_ldap.return_value = _ldap_response({"alice": "alice-new"})
    mock_github_orgs.return_value = _github_orgs()
    mock_validate.return_value = _github_validate_response(["alice-new"])
    mock_build.return_value = [
        FileSyncUpdate(
            path="/access/users/alice.yml", content="...", commit_message="x"
        ),
    ]
    mock_file_sync.return_value = FileSyncResponse(
        status=FileSyncStatus.MR_CREATED,
        mr_url="https://gitlab.example.com/mr/1",
    )

    await integration.async_run(dry_run=False)

    mock_file_sync.assert_called_once()
    call_request = mock_file_sync.call_args.args[0]
    assert call_request.repo_url == _APP_REPO
    assert call_request.title == "[github_username_sync] sync github_username from LDAP"
    assert len(call_request.file_operations) == 1
    assert call_request.auto_merge is False


@pytest.mark.asyncio
@patch(f"{_MOD}.github_users_validate", new_callable=AsyncMock)
@patch(f"{_MOD}.get_github_orgs")
@patch(f"{_MOD}.build_github_username_update_operations", new_callable=AsyncMock)
@patch(f"{_MOD}.vcs_file_sync", new_callable=AsyncMock)
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.ldap_org_github_usernames", new_callable=AsyncMock)
@patch(f"{_MOD}.query_users")
async def test_async_run_batches_multiple_users_into_single_mr(
    mock_query: MagicMock,
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    mock_file_sync: AsyncMock,
    mock_build: AsyncMock,
    mock_github_orgs: MagicMock,
    mock_validate: AsyncMock,
    integration: GithubUsernameSyncIntegration,
) -> None:
    """Multiple drifted users produce a single batched MR, not one per user, and
    an in-sync user in the same run is excluded from it.
    """
    mock_query.return_value = _users_data([
        _make_user("alice", "alice-old"),
        _make_user("bob", "bob-old"),
        _make_user("carol", "carol-gh"),
    ])
    mock_settings.return_value = _ldap_settings()
    mock_vcs.return_value = _vcs_instances()
    mock_ldap.return_value = _ldap_response({
        "alice": "alice-new",
        "bob": "bob-new",
        "carol": "carol-gh",
    })
    mock_github_orgs.return_value = _github_orgs()
    mock_validate.return_value = _github_validate_response([
        "alice-new",
        "bob-new",
        "carol-gh",
    ])
    mock_build.return_value = [
        FileSyncUpdate(
            path="/access/users/alice.yml", content="...", commit_message="x"
        ),
        FileSyncUpdate(path="/access/users/bob.yml", content="...", commit_message="x"),
    ]
    mock_file_sync.return_value = FileSyncResponse(
        status=FileSyncStatus.MR_CREATED,
        mr_url="https://gitlab.example.com/mr/1",
    )

    await integration.async_run(dry_run=False)

    mock_file_sync.assert_called_once()
    call_request = mock_file_sync.call_args.args[0]
    assert len(call_request.file_operations) == 2
    assert "alice" in call_request.description
    assert "bob" in call_request.description
    assert "carol" not in call_request.description

    build_call = mock_build.call_args
    assert {u.org_username for u in build_call.kwargs["updates"]} == {"alice", "bob"}


@pytest.mark.asyncio
@pytest.mark.parametrize("auto_merge_threshold", [1, 10])
@patch(f"{_MOD}.github_users_validate", new_callable=AsyncMock)
@patch(f"{_MOD}.get_github_orgs")
@patch(f"{_MOD}.build_github_username_update_operations", new_callable=AsyncMock)
@patch(f"{_MOD}.vcs_file_sync", new_callable=AsyncMock)
@patch(f"{_MOD}.get_feature_toggle_state", return_value=True)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.ldap_org_github_usernames", new_callable=AsyncMock)
@patch(f"{_MOD}.query_users")
async def test_async_run_auto_merge_enabled_below_threshold(
    mock_query: MagicMock,
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    mock_file_sync: AsyncMock,
    mock_build: AsyncMock,
    mock_github_orgs: MagicMock,
    mock_validate: AsyncMock,
    auto_merge_threshold: int,
) -> None:
    """At or below the threshold, auto-merge follows the Unleash toggle and labels
    are unchanged.
    """
    integration = _make_integration(auto_merge_threshold=auto_merge_threshold)
    mock_query.return_value = _users_data([_make_user("alice", "alice-old")])
    mock_settings.return_value = _ldap_settings()
    mock_vcs.return_value = _vcs_instances()
    mock_ldap.return_value = _ldap_response({"alice": "alice-new"})
    mock_github_orgs.return_value = _github_orgs()
    mock_validate.return_value = _github_validate_response(["alice-new"])
    mock_build.return_value = [
        FileSyncUpdate(
            path="/access/users/alice.yml", content="...", commit_message="x"
        ),
    ]
    mock_file_sync.return_value = FileSyncResponse(
        status=FileSyncStatus.MR_CREATED,
        mr_url="https://gitlab.example.com/mr/1",
    )

    await integration.async_run(dry_run=False)

    call_request = mock_file_sync.call_args.args[0]
    assert call_request.auto_merge is True
    assert call_request.labels == ["github-username-sync"]
    assert SHOW_SELF_SERVICEABLE_IN_REVIEW_QUEUE not in call_request.labels


@pytest.mark.asyncio
@patch(f"{_MOD}.github_users_validate", new_callable=AsyncMock)
@patch(f"{_MOD}.get_github_orgs")
@patch(f"{_MOD}.build_github_username_update_operations", new_callable=AsyncMock)
@patch(f"{_MOD}.vcs_file_sync", new_callable=AsyncMock)
@patch(f"{_MOD}.get_feature_toggle_state", return_value=True)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.ldap_org_github_usernames", new_callable=AsyncMock)
@patch(f"{_MOD}.query_users")
async def test_async_run_auto_merge_suppressed_above_threshold(
    mock_query: MagicMock,
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    mock_file_sync: AsyncMock,
    mock_build: AsyncMock,
    mock_github_orgs: MagicMock,
    mock_validate: AsyncMock,
) -> None:
    """Above the threshold, auto-merge is suppressed and the review-queue label is
    added, even with the Unleash toggle on.
    """
    integration = _make_integration(auto_merge_threshold=1)
    mock_query.return_value = _users_data([
        _make_user("alice", "alice-old"),
        _make_user("bob", "bob-old"),
    ])
    mock_settings.return_value = _ldap_settings()
    mock_vcs.return_value = _vcs_instances()
    mock_ldap.return_value = _ldap_response({
        "alice": "alice-new",
        "bob": "bob-new",
    })
    mock_github_orgs.return_value = _github_orgs()
    mock_validate.return_value = _github_validate_response(["alice-new", "bob-new"])
    mock_build.return_value = [
        FileSyncUpdate(
            path="/access/users/alice.yml", content="...", commit_message="x"
        ),
        FileSyncUpdate(path="/access/users/bob.yml", content="...", commit_message="x"),
    ]
    mock_file_sync.return_value = FileSyncResponse(
        status=FileSyncStatus.MR_CREATED,
        mr_url="https://gitlab.example.com/mr/1",
    )

    await integration.async_run(dry_run=False)

    call_request = mock_file_sync.call_args.args[0]
    assert call_request.auto_merge is False
    assert SHOW_SELF_SERVICEABLE_IN_REVIEW_QUEUE in call_request.labels


@pytest.mark.asyncio
@patch(f"{_MOD}.github_users_validate", new_callable=AsyncMock)
@patch(f"{_MOD}.get_github_orgs")
@patch(f"{_MOD}.build_github_username_update_operations", new_callable=AsyncMock)
@patch(f"{_MOD}.vcs_file_sync", new_callable=AsyncMock)
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.ldap_org_github_usernames", new_callable=AsyncMock)
@patch(f"{_MOD}.query_users")
async def test_async_run_no_file_ops_skips_mr(
    mock_query: MagicMock,
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    mock_file_sync: AsyncMock,
    mock_build: AsyncMock,
    mock_github_orgs: MagicMock,
    mock_validate: AsyncMock,
    integration: GithubUsernameSyncIntegration,
) -> None:
    """If the MR builder produces no operations (e.g. all files 404), skip the MR."""
    mock_query.return_value = _users_data([_make_user("alice", "alice-old")])
    mock_settings.return_value = _ldap_settings()
    mock_vcs.return_value = _vcs_instances()
    mock_ldap.return_value = _ldap_response({"alice": "alice-new"})
    mock_github_orgs.return_value = _github_orgs()
    mock_validate.return_value = _github_validate_response(["alice-new"])
    mock_build.return_value = []

    await integration.async_run(dry_run=False)

    mock_file_sync.assert_not_called()


@pytest.mark.asyncio
@patch(f"{_MOD}.github_users_validate", new_callable=AsyncMock)
@patch(f"{_MOD}.get_github_orgs")
@patch(f"{_MOD}.build_github_username_update_operations", new_callable=AsyncMock)
@patch(f"{_MOD}.vcs_file_sync", new_callable=AsyncMock)
@patch(f"{_MOD}.get_feature_toggle_state", return_value=False)
@patch(f"{_MOD}.get_vcs_instances")
@patch(f"{_MOD}.get_ldap_settings")
@patch(f"{_MOD}.gql")
@patch(f"{_MOD}.ldap_org_github_usernames", new_callable=AsyncMock)
@patch(f"{_MOD}.query_users")
async def test_async_run_handles_mr_exists_status(
    mock_query: MagicMock,
    mock_ldap: AsyncMock,
    mock_gql: MagicMock,
    mock_settings: MagicMock,
    mock_vcs: MagicMock,
    mock_toggle: MagicMock,
    mock_file_sync: AsyncMock,
    mock_build: AsyncMock,
    mock_github_orgs: MagicMock,
    mock_validate: AsyncMock,
    integration: GithubUsernameSyncIntegration,
) -> None:
    """An already-existing MR (idempotent re-run) does not raise."""
    mock_query.return_value = _users_data([_make_user("alice", "alice-old")])
    mock_settings.return_value = _ldap_settings()
    mock_vcs.return_value = _vcs_instances()
    mock_ldap.return_value = _ldap_response({"alice": "alice-new"})
    mock_github_orgs.return_value = _github_orgs()
    mock_validate.return_value = _github_validate_response(["alice-new"])
    mock_build.return_value = [
        FileSyncUpdate(
            path="/access/users/alice.yml", content="...", commit_message="x"
        ),
    ]
    mock_file_sync.return_value = FileSyncResponse(
        status=FileSyncStatus.MR_EXISTS,
        mr_url="https://gitlab.example.com/mr/1",
    )

    await integration.async_run(dry_run=False)

    mock_file_sync.assert_called_once()

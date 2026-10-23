"""Tests for LdapWorkspaceClient (Layer 2 - caching + locking for direct LDAP)."""

from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.ldap_api import LdapApi
from qontract_utils.ldap_api.models import LdapGroup, LdapUser

from qontract_api.cache.base import CacheBackend
from qontract_api.config import LdapSettings, Settings
from qontract_api.exceptions import ValidationError
from qontract_api.external.ldap.ldap_workspace_client import (
    CachedGithubUsernames,
    CachedGroupMembers,
    CachedUserCheck,
    LdapWorkspaceClient,
)
from qontract_api.external.ldap.schemas import (
    LdapGroupMember,
    LdapGroupResult,
    LdapUserStatus,
)


@pytest.fixture
def mock_api() -> MagicMock:
    """Create mock LdapApi."""
    api = MagicMock(spec=LdapApi)
    api.base_dn = "dc=example,dc=com"
    return api


@pytest.fixture
def mock_cache() -> MagicMock:
    """Create mock CacheBackend."""
    m = MagicMock(spec=CacheBackend)
    m.get_obj.return_value = None
    m.lock.return_value.__enter__ = MagicMock()
    m.lock.return_value.__exit__ = MagicMock(return_value=False)
    return m


@pytest.fixture
def ldap_settings() -> Settings:
    """Create test settings."""
    return Settings(ldap=LdapSettings(users_cache_ttl=300))


@pytest.fixture
def workspace_client(
    mock_api: MagicMock,
    mock_cache: MagicMock,
    ldap_settings: Settings,
) -> LdapWorkspaceClient:
    """Create LdapWorkspaceClient with mocked dependencies."""
    return LdapWorkspaceClient(
        api=mock_api,
        cache=mock_cache,
        settings=ldap_settings,
        cache_key_prefix="test-prefix",
    )


def test_check_users_exist_calls_api(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    """Test check_users_exist delegates to LdapApi.get_users."""
    mock_api.get_users.return_value = [LdapUser(username="alice")]

    result = workspace_client.check_users_exist(["alice", "bob"])

    assert sorted(result, key=lambda u: u.username) == [
        LdapUserStatus(username="alice", exists=True),
        LdapUserStatus(username="bob", exists=False),
    ]
    mock_api.get_users.assert_called_once()


def test_check_users_exist_cache_hit(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test check_users_exist returns cached data on cache hit."""
    cached = CachedUserCheck(result=[LdapUserStatus(username="alice", exists=True)])
    mock_cache.get_obj.return_value = cached

    result = workspace_client.check_users_exist(["alice"])

    assert result == [LdapUserStatus(username="alice", exists=True)]
    mock_api.get_users.assert_not_called()


def test_check_users_exist_double_check_locking(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test check_users_exist uses double-check locking pattern."""
    # First get_obj returns None (cache miss), second returns cached data (after lock)
    cached = CachedUserCheck(result=[LdapUserStatus(username="alice", exists=True)])
    mock_cache.get_obj.side_effect = [None, cached]

    result = workspace_client.check_users_exist(["alice"])

    # Should return cached data without calling API
    assert result == [LdapUserStatus(username="alice", exists=True)]
    mock_api.get_users.assert_not_called()
    mock_cache.lock.assert_called_once()


def test_check_users_exist_acquires_lock_on_miss(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test check_users_exist acquires distributed lock on cache miss."""
    mock_api.get_users.return_value = []

    workspace_client.check_users_exist(["alice"])

    mock_cache.lock.assert_called_once()


def test_check_users_exist_caches_result(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
    ldap_settings: Settings,
) -> None:
    """Test check_users_exist stores result in cache with TTL."""
    mock_api.get_users.return_value = [LdapUser(username="alice")]

    workspace_client.check_users_exist(["alice", "bob"])

    mock_cache.set_obj.assert_called_once()
    call_args = mock_cache.set_obj.call_args
    assert call_args[1]["ttl"] == ldap_settings.ldap.users_cache_ttl


def test_check_users_exist_context_manager(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    """Test check_users_exist uses LdapApi as context manager."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.get_users.return_value = []

    workspace_client.check_users_exist(["alice"])

    mock_api.__enter__.assert_called_once()
    mock_api.__exit__.assert_called_once()


def test_check_users_exist_empty_input(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test check_users_exist with empty input returns empty list."""
    result = workspace_client.check_users_exist([])

    assert result == []
    mock_api.get_users.assert_not_called()
    mock_cache.get_obj.assert_not_called()


# --- resolve_github_usernames ---


def test_resolve_github_usernames_calls_api_and_matches(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    """Test resolve_github_usernames delegates to LdapApi and returns matches."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.get_github_usernames.return_value = {
        "alicegh": ["alice"],
        "bob": ["bob"],
    }

    result = workspace_client.resolve_github_usernames(["AliceGH", "bob"])

    assert result == {"AliceGH": "alice", "bob": "bob"}
    mock_api.get_github_usernames.assert_called_once()


def test_resolve_github_usernames_case_insensitive(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    """Test resolve_github_usernames matches logins case-insensitively."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.get_github_usernames.return_value = {"alicegh": ["alice"]}

    # Requested with different casing than stored in LDAP
    result = workspace_client.resolve_github_usernames(["alicegh"])

    # The requested login is echoed back (not the LDAP casing), mapped to uid
    assert result == {"alicegh": "alice"}


def test_resolve_github_usernames_omits_unresolved(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    """Test resolve_github_usernames omits logins not found in LDAP."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.get_github_usernames.return_value = {"alicegh": ["alice"]}

    result = workspace_client.resolve_github_usernames(["AliceGH", "unknown"])

    assert result == {"AliceGH": "alice"}


def test_resolve_github_usernames_empty_input(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test resolve_github_usernames with empty input returns empty and skips work."""
    result = workspace_client.resolve_github_usernames([])

    assert result == {}
    mock_api.get_github_usernames.assert_not_called()
    mock_cache.get_obj.assert_not_called()


def test_resolve_github_usernames_cache_hit(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test resolve_github_usernames serves the map from cache without an API call."""
    mock_cache.get_obj.return_value = CachedGithubUsernames(
        mapping={"alicegh": ["alice"]}
    )

    result = workspace_client.resolve_github_usernames(["AliceGH"])

    assert result == {"AliceGH": "alice"}
    mock_api.get_github_usernames.assert_not_called()


def test_resolve_github_usernames_caches_map_with_ttl(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
    ldap_settings: Settings,
) -> None:
    """Test resolve_github_usernames caches the full map with the configured TTL."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.get_github_usernames.return_value = {"alicegh": ["alice"]}

    workspace_client.resolve_github_usernames(["AliceGH"])

    mock_cache.set_obj.assert_called_once()
    call_args = mock_cache.set_obj.call_args
    assert call_args[1]["ttl"] == ldap_settings.ldap.github_usernames_cache_ttl


def test_resolve_github_usernames_double_check_locking(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test resolve_github_usernames uses double-check locking on cache miss."""
    cached = CachedGithubUsernames(mapping={"alicegh": ["alice"]})
    mock_cache.get_obj.side_effect = [None, cached]

    result = workspace_client.resolve_github_usernames(["AliceGH"])

    assert result == {"AliceGH": "alice"}
    mock_api.get_github_usernames.assert_not_called()
    mock_cache.lock.assert_called_once()


def test_resolve_github_usernames_skips_and_logs_ambiguous_requested(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """A requested login mapping to >1 uid is skipped and logged once.

    LDAP result order must not decide identity, so an ambiguous requested login
    is omitted from the result. The warning names the requested login and all
    candidate uids so it is actionable.
    """
    mock_cache.get_obj.return_value = CachedGithubUsernames(
        mapping={"shared-gh": ["alice", "mallory"], "bob-gh": ["bob"]}
    )

    with patch(
        "qontract_api.external.ldap.ldap_workspace_client.logger"
    ) as mock_logger:
        result = workspace_client.resolve_github_usernames(["Shared-GH", "bob-gh"])

    # Ambiguous login dropped; unambiguous one resolved.
    assert result == {"bob-gh": "bob"}
    mock_logger.warning.assert_called_once()
    _, kwargs = mock_logger.warning.call_args
    assert kwargs["github_login"] == "Shared-GH"
    assert kwargs["uids"] == ["alice", "mallory"]


def test_resolve_github_usernames_no_log_for_non_requested_ambiguous(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Ambiguity outside the requested logins produces no warning.

    The directory holds many ambiguous logins (orgs/repos claimed by several
    associates) that are irrelevant to the org being reconciled. Only requested
    logins are considered, so those never spam the logs.
    """
    mock_cache.get_obj.return_value = CachedGithubUsernames(
        mapping={
            "example-org": ["carol", "dave"],  # ambiguous, but not requested
            "alicegh": ["alice"],
        }
    )

    with patch(
        "qontract_api.external.ldap.ldap_workspace_client.logger"
    ) as mock_logger:
        result = workspace_client.resolve_github_usernames(["AliceGH"])

    assert result == {"AliceGH": "alice"}
    mock_logger.warning.assert_not_called()


# --- get_org_username_to_github_map ---


def test_get_org_username_to_github_map_resolves_unambiguous(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Each uid with exactly one linked login, shared with no one else, resolves."""
    mock_cache.get_obj.return_value = CachedGithubUsernames(
        mapping={"alice-gh": ["alice"], "bob-gh": ["bob"]}
    )

    result = workspace_client.get_org_username_to_github_map()

    assert result == {"alice": "alice-gh", "bob": "bob-gh"}


def test_get_org_username_to_github_map_excludes_uid_with_shared_login(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """A uid's own multi-login ambiguity must not be masked by a login it shares.

    Alice links both "alice-gh" and "shared-gh"; Bob also links "shared-gh".
    "shared-gh" is ambiguous (two uids), but Alice's own set {"alice-gh",
    "shared-gh"} is independently ambiguous (two distinct logins) and must be
    skipped on that basis alone - regardless of what happens to "shared-gh".
    """
    mock_cache.get_obj.return_value = CachedGithubUsernames(
        mapping={
            "alice-gh": ["alice"],
            "shared-gh": ["alice", "bob"],
        }
    )

    result = workspace_client.get_org_username_to_github_map()

    assert result == {}


def test_get_org_username_to_github_map_excludes_uid_with_multiple_logins(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """A uid claiming multiple distinct logins is ambiguous.

    This holds even if neither login is itself shared with another uid.
    """
    mock_cache.get_obj.return_value = CachedGithubUsernames(
        mapping={"carol-gh-1": ["carol"], "carol-gh-2": ["carol"]}
    )

    result = workspace_client.get_org_username_to_github_map()

    assert result == {}


def test_get_org_username_to_github_map_logs_both_ambiguity_reasons(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
) -> None:
    """Both ambiguity conditions are logged with their own warning."""
    mock_cache.get_obj.return_value = CachedGithubUsernames(
        mapping={
            "shared-gh": ["alice", "bob"],
            "carol-gh-1": ["carol"],
            "carol-gh-2": ["carol"],
        }
    )

    with patch(
        "qontract_api.external.ldap.ldap_workspace_client.logger"
    ) as mock_logger:
        result = workspace_client.get_org_username_to_github_map()

    assert result == {}
    warning_calls = mock_logger.warning.call_args_list
    assert any(call.kwargs.get("github_login") == "shared-gh" for call in warning_calls)
    assert any(call.kwargs.get("org_username") == "carol" for call in warning_calls)


# --- get_group_members ---


def test_get_group_members_preserves_person_name(
    workspace_client: LdapWorkspaceClient, mock_api: MagicMock
) -> None:
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.check_groups_exist.return_value = {"team"}
    mock_api.get_group_members.return_value = [
        LdapGroup(
            cn="team",
            dn="cn=team,cn=groups,cn=accounts,dc=example,dc=com",
            members=frozenset({LdapUser(username="alice", name="Alice Example")}),
        )
    ]
    result = workspace_client.get_group_members(
        ["team"], include_github_usernames=False
    )
    assert result[0].members[0].name == "Alice Example"


def test_get_group_members_rejects_missing_person_name(
    workspace_client: LdapWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.check_groups_exist.return_value = {"team"}
    mock_api.get_group_members.return_value = [
        LdapGroup(
            cn="team", dn="cn=team,...", members=frozenset({LdapUser(username="alice")})
        )
    ]
    with pytest.raises(ValidationError, match="alice.*has no name"):
        workspace_client.get_group_members(["team"], include_github_usernames=False)
    mock_cache.set_obj.assert_not_called()


def test_get_group_members_resolves_existing_group(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    """Test get_group_members resolves a group's members via check + fetch."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.check_groups_exist.return_value = {"team-a"}
    mock_api.get_group_members.return_value = [
        LdapGroup(
            cn="team-a",
            dn="cn=team-a,cn=groups,cn=accounts,dc=example,dc=com",
            members=frozenset({
                LdapUser(name="alice", username="alice"),
                LdapUser(name="bob", username="bob"),
            }),
        )
    ]
    mock_api.get_github_usernames.return_value = {}

    result = workspace_client.get_group_members(["team-a"])

    assert result == [
        LdapGroupResult(
            group="team-a",
            members=[
                LdapGroupMember(name="alice", org_username="alice"),
                LdapGroupMember(name="bob", org_username="bob"),
            ],
        )
    ]
    mock_api.check_groups_exist.assert_called_once_with(["team-a"])
    mock_api.get_group_members.assert_called_once_with([
        "cn=team-a,cn=groups,cn=accounts,dc=example,dc=com"
    ])


def test_get_group_members_confirmed_empty_group(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    """A group that exists but has no members is present with an empty member list."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.check_groups_exist.return_value = {"empty-team"}
    mock_api.get_group_members.return_value = []  # no members found for any group
    mock_api.get_github_usernames.return_value = {}

    result = workspace_client.get_group_members(["empty-team"])

    assert result == [LdapGroupResult(group="empty-team", members=[])]


def test_get_group_members_omits_unresolved_group(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    """A group CN that doesn't exist in LDAP is omitted, not returned as empty."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.check_groups_exist.return_value = set()  # "ghost-team" does not exist
    mock_api.get_group_members.return_value = []
    mock_api.get_github_usernames.return_value = {}

    result = workspace_client.get_group_members(["ghost-team"])

    assert result == []
    mock_api.get_group_members.assert_called_once_with([])


def test_get_group_members_enriches_with_github_username(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    """Test get_group_members enriches members with github_username by default."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.check_groups_exist.return_value = {"team-a"}
    mock_api.get_group_members.return_value = [
        LdapGroup(
            cn="team-a",
            dn="cn=team-a,...",
            members=frozenset({LdapUser(name="alice", username="alice")}),
        )
    ]
    mock_api.get_github_usernames.return_value = {"alicegh": ["alice"]}

    result = workspace_client.get_group_members(["team-a"])

    assert result == [
        LdapGroupResult(
            group="team-a",
            members=[
                LdapGroupMember(
                    name="alice", org_username="alice", github_username="alicegh"
                )
            ],
        )
    ]


def test_get_group_members_skips_github_enrichment_when_disabled(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    """Test get_group_members does not call get_github_usernames when disabled."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.check_groups_exist.return_value = {"team-a"}
    mock_api.get_group_members.return_value = [
        LdapGroup(
            cn="team-a",
            dn="cn=team-a,...",
            members=frozenset({LdapUser(name="alice", username="alice")}),
        )
    ]

    result = workspace_client.get_group_members(
        ["team-a"], include_github_usernames=False
    )

    assert result == [
        LdapGroupResult(
            group="team-a",
            members=[LdapGroupMember(name="alice", org_username="alice")],
        )
    ]
    mock_api.get_github_usernames.assert_not_called()


def test_get_group_members_skips_and_logs_ambiguous_github_username(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
) -> None:
    """An org_username claiming >1 GitHub login is enriched with None, and logged."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.check_groups_exist.return_value = {"team-a"}
    mock_api.get_group_members.return_value = [
        LdapGroup(
            cn="team-a",
            dn="cn=team-a,...",
            members=frozenset({LdapUser(name="alice", username="alice")}),
        )
    ]
    # alice's rhatSocialURL ambiguously resolves to two different github logins
    mock_api.get_github_usernames.return_value = {
        "alice-gh-1": ["alice"],
        "alice-gh-2": ["alice"],
    }

    with patch(
        "qontract_api.external.ldap.ldap_workspace_client.logger"
    ) as mock_logger:
        result = workspace_client.get_group_members(["team-a"])

    assert result == [
        LdapGroupResult(
            group="team-a",
            members=[LdapGroupMember(name="alice", org_username="alice")],
        )
    ]
    mock_logger.warning.assert_called_once()
    _, kwargs = mock_logger.warning.call_args
    assert kwargs["org_username"] == "alice"
    assert kwargs["github_logins"] == ["alice-gh-1", "alice-gh-2"]


@pytest.mark.parametrize("include_unique_login", [False, True])
def test_get_group_members_skips_shared_github_login(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
    *,
    include_unique_login: bool,
) -> None:
    """A login claimed by multiple LDAP uids must not identify either one.

    When the shared uid also has its own additional login (include_unique_login),
    that uid is independently ambiguous too - it has two distinct logins of its
    own and must not fall back to the other one once the shared login is dropped.
    """
    mock_api.check_groups_exist.return_value = {"team-a"}
    mock_api.get_group_members.return_value = [
        LdapGroup(
            cn="team-a",
            dn="cn=team-a,cn=groups,cn=accounts,dc=example,dc=com",
            members=frozenset({
                LdapUser(name="alice", username="alice"),
                LdapUser(name="bob", username="bob"),
            }),
        )
    ]
    mapping = {"shared-gh": ["alice", "bob"]}
    if include_unique_login:
        mapping["alice-gh"] = ["alice"]
    mock_api.get_github_usernames.return_value = mapping

    with patch(
        "qontract_api.external.ldap.ldap_workspace_client.logger"
    ) as mock_logger:
        result = workspace_client.get_group_members(["team-a"])

    assert result == [
        LdapGroupResult(
            group="team-a",
            members=[
                LdapGroupMember(name="alice", org_username="alice"),
                LdapGroupMember(name="bob", org_username="bob"),
            ],
        )
    ]
    warning_calls = [call.kwargs for call in mock_logger.warning.call_args_list]
    assert {"github_login": "shared-gh", "uids": ["alice", "bob"]} in warning_calls
    if include_unique_login:
        assert mock_logger.warning.call_count == 2
        assert {
            "org_username": "alice",
            "github_logins": ["alice-gh", "shared-gh"],
        } in warning_calls
    else:
        assert mock_logger.warning.call_count == 1


def test_get_group_members_fail_closed_on_oversized_group(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """A group exceeding max_group_size raises instead of being truncated."""
    workspace_client.settings = Settings(ldap=LdapSettings(max_group_size=1))
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.check_groups_exist.return_value = {"big-team"}
    mock_api.get_group_members.return_value = [
        LdapGroup(
            cn="big-team",
            dn="cn=big-team,...",
            members=frozenset({
                LdapUser(name="alice", username="alice"),
                LdapUser(name="bob", username="bob"),
            }),
        )
    ]
    mock_api.get_github_usernames.return_value = {}

    with pytest.raises(ValidationError, match="big-team"):
        workspace_client.get_group_members(["big-team"])

    # a failed (oversized) resolution must never be cached (the github-usernames
    # map itself is a separate, legitimate cache entry populated as a side effect)
    cached_keys = [call.args[0] for call in mock_cache.set_obj.call_args_list]
    assert not any(
        key.startswith("ldap:test-prefix:groups:members:") for key in cached_keys
    )


def test_get_group_members_cache_hit(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test get_group_members returns cached data on cache hit."""
    cached = CachedGroupMembers(groups=[LdapGroupResult(group="team-a", members=[])])
    mock_cache.get_obj.return_value = cached

    result = workspace_client.get_group_members(["team-a"])

    assert result == [LdapGroupResult(group="team-a", members=[])]
    mock_api.check_groups_exist.assert_not_called()


def test_get_group_members_double_check_locking(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
) -> None:
    """Test get_group_members uses double-check locking pattern."""
    cached = CachedGroupMembers(groups=[LdapGroupResult(group="team-a", members=[])])
    mock_cache.get_obj.side_effect = [None, cached]

    result = workspace_client.get_group_members(["team-a"])

    assert result == [LdapGroupResult(group="team-a", members=[])]
    mock_api.check_groups_exist.assert_not_called()
    mock_cache.lock.assert_called_once()


def test_get_group_members_caches_result_with_ttl(
    workspace_client: LdapWorkspaceClient,
    mock_cache: MagicMock,
    mock_api: MagicMock,
    ldap_settings: Settings,
) -> None:
    """Test get_group_members stores the result in cache with the configured TTL."""
    mock_api.__enter__ = MagicMock(return_value=mock_api)
    mock_api.__exit__ = MagicMock(return_value=False)
    mock_api.check_groups_exist.return_value = {"team-a"}
    mock_api.get_group_members.return_value = []
    mock_api.get_github_usernames.return_value = {}

    workspace_client.get_group_members(["team-a"])

    groups_call = next(
        call
        for call in mock_cache.set_obj.call_args_list
        if call.args[0].startswith("ldap:test-prefix:groups:members:")
    )
    assert groups_call.kwargs["ttl"] == ldap_settings.ldap.groups_cache_ttl


def test_get_group_members_empty_input(
    workspace_client: LdapWorkspaceClient,
    mock_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Test get_group_members with empty input returns empty list without calls."""
    result = workspace_client.get_group_members([])

    assert result == []
    mock_api.check_groups_exist.assert_not_called()
    mock_cache.get_obj.assert_not_called()

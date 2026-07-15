from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from reconcile.container_registry_mirror.mirror_spec import MirrorSpec
from reconcile.container_registry_mirror.quay import OrgKey, QuayMirror

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


# Fixture data mimicking the structure returned by queries.get_quay_repos().
# Each app has quayRepos -> org -> items with optional mirror definitions.
def _quay_repos_fixture(
    mirror_url: str = "docker.io/upstream/image",
    public: bool = False,
    pull_credentials: dict | None = None,
    tags: list[str] | None = None,
    tags_exclude: list[str] | None = None,
    org_name: str = "test-org",
    instance_name: str = "quay.io",
    instance_url: str = "https://quay.io",
    repo_name: str = "test-image",
) -> list[dict]:
    mirror = {
        "url": mirror_url,
        "pullCredentials": pull_credentials,
        "tags": tags,
        "tagsExclude": tags_exclude,
    }
    return [
        {
            "quayRepos": [
                {
                    "org": {
                        "name": org_name,
                        "instance": {
                            "name": instance_name,
                            "url": instance_url,
                        },
                    },
                    "items": [
                        {
                            "name": repo_name,
                            "public": public,
                            "mirror": mirror,
                        }
                    ],
                }
            ]
        }
    ]


def _quay_repos_no_mirror() -> list[dict]:
    """App with a repo that has no mirror definition."""
    return [
        {
            "quayRepos": [
                {
                    "org": {
                        "name": "test-org",
                        "instance": {
                            "name": "quay.io",
                            "url": "https://quay.io",
                        },
                    },
                    "items": [
                        {
                            "name": "no-mirror-repo",
                            "public": False,
                            "mirror": None,
                        }
                    ],
                }
            ]
        }
    ]


def _quay_orgs_fixture(
    org_name: str = "test-org",
    instance_name: str = "quay.io",
) -> dict:
    """Mimics the QUAY_ORG_CATALOG_QUERY response for push credentials."""
    return {
        "quay_orgs": [
            {
                "name": org_name,
                "pushCredentials": {
                    "path": "secret/quay/push",
                    "field": "token",
                    "version": 1,
                    "format": None,
                },
                "instance": {
                    "name": instance_name,
                    "url": "https://quay.io",
                },
            }
        ]
    }


@pytest.fixture()
def mock_gql(mocker: MockerFixture) -> MagicMock:
    mock = mocker.patch("reconcile.container_registry_mirror.quay.gql")
    return mock


@pytest.fixture()
def mock_queries(mocker: MockerFixture) -> MagicMock:
    mock = mocker.patch("reconcile.container_registry_mirror.quay.queries")
    return mock


@pytest.fixture()
def mock_secret_reader(mocker: MockerFixture) -> MagicMock:
    mock = mocker.patch(
        "reconcile.container_registry_mirror.quay.SecretReader",
        autospec=True,
    )
    # Default: push credentials return user:token, pull credentials
    # return user:token. Tests can override as needed.
    instance = mock.return_value
    instance.read_all.return_value = {"user": "push_user", "token": "push_token"}
    return instance


@pytest.fixture()
def quay_mirror(
    mock_gql: MagicMock, mock_queries: MagicMock, mock_secret_reader: MagicMock
) -> QuayMirror:
    """Construct a QuayMirror with all external dependencies mocked."""
    mock_gql.get_api.return_value.query.return_value = _quay_orgs_fixture()
    return QuayMirror()


class TestDiscoverMirrors:
    """discover_mirrors() should transform the quay_repos GraphQL
    response into a list of MirrorSpec instances."""

    def test_basic_discovery(
        self, quay_mirror: QuayMirror, mock_queries: MagicMock
    ) -> None:
        mock_queries.get_quay_repos.return_value = _quay_repos_fixture()

        specs = quay_mirror.discover_mirrors()

        assert len(specs) == 1
        spec = specs[0]
        assert isinstance(spec, MirrorSpec)
        assert spec.source_url == "docker.io/upstream/image"
        assert spec.destination_url == "https://quay.io/test-org/test-image"

    def test_destination_credentials_populated(
        self, quay_mirror: QuayMirror, mock_queries: MagicMock
    ) -> None:
        """Each MirrorSpec should have destination credentials resolved
        from the org's push secret."""
        mock_queries.get_quay_repos.return_value = _quay_repos_fixture()

        specs = quay_mirror.discover_mirrors()

        assert specs[0].destination_creds == "push_user:push_token"

    def test_tag_filters_propagated(
        self, quay_mirror: QuayMirror, mock_queries: MagicMock
    ) -> None:
        mock_queries.get_quay_repos.return_value = _quay_repos_fixture(
            tags=["^v[0-9]+"],
            tags_exclude=["^sha256"],
        )

        specs = quay_mirror.discover_mirrors()

        assert specs[0].tag_include == ["^v[0-9]+"]
        assert specs[0].tag_exclude == ["^sha256"]

    def test_skips_repos_with_no_mirror(
        self, quay_mirror: QuayMirror, mock_queries: MagicMock
    ) -> None:
        """Repos without a mirror definition should not produce a
        MirrorSpec."""
        mock_queries.get_quay_repos.return_value = _quay_repos_no_mirror()

        specs = quay_mirror.discover_mirrors()

        assert len(specs) == 0

    def test_skips_no_quay_repos(
        self, quay_mirror: QuayMirror, mock_queries: MagicMock
    ) -> None:
        """Apps with no quayRepos key should be skipped gracefully."""
        mock_queries.get_quay_repos.return_value = [{"quayRepos": None}]

        specs = quay_mirror.discover_mirrors()

        assert len(specs) == 0

    def test_filters_by_repository_urls(
        self, quay_mirror: QuayMirror, mock_queries: MagicMock
    ) -> None:
        """When repository_urls is set, only matching mirror sources
        should produce specs."""
        quay_mirror.repository_urls = {"docker.io/upstream/wanted"}
        mock_queries.get_quay_repos.return_value = _quay_repos_fixture(
            mirror_url="docker.io/upstream/unwanted"
        )

        specs = quay_mirror.discover_mirrors()

        assert len(specs) == 0

    def test_excludes_by_repository_urls(
        self, quay_mirror: QuayMirror, mock_queries: MagicMock
    ) -> None:
        """When exclude_repository_urls is set, matching mirror sources
        should be excluded."""
        quay_mirror.exclude_repository_urls = {"docker.io/upstream/image"}
        mock_queries.get_quay_repos.return_value = _quay_repos_fixture()

        specs = quay_mirror.discover_mirrors()

        assert len(specs) == 0


class TestShouldSkipMirror:
    """should_skip_mirror blocks docker.io sources from being mirrored
    to public Quay repositories."""

    def test_docker_to_public_blocked(self, quay_mirror: QuayMirror) -> None:
        result = quay_mirror.should_skip_mirror(
            source_registry="docker.io",
            source_url="docker.io/library/nginx",
            destination_url="quay.io/org/nginx",
            destination_public=True,
        )
        assert result is True

    def test_docker_to_private_allowed(self, quay_mirror: QuayMirror) -> None:
        result = quay_mirror.should_skip_mirror(
            source_registry="docker.io",
            source_url="docker.io/library/nginx",
            destination_url="quay.io/org/nginx",
            destination_public=False,
        )
        assert result is False

    def test_non_docker_to_public_allowed(self, quay_mirror: QuayMirror) -> None:
        result = quay_mirror.should_skip_mirror(
            source_registry="gcr.io",
            source_url="gcr.io/project/image",
            destination_url="quay.io/org/image",
            destination_public=True,
        )
        assert result is False

    def test_public_none_allowed(self, quay_mirror: QuayMirror) -> None:
        """When destination_public is None (field not present in schema),
        the mirror should not be skipped."""
        result = quay_mirror.should_skip_mirror(
            source_registry="docker.io",
            source_url="docker.io/library/nginx",
            destination_url="quay.io/org/nginx",
            destination_public=None,
        )
        assert result is False


class TestResolveSourceCredentials:
    """resolve_source_credentials reads pull credentials from Vault
    and returns them in skopeo format."""

    def test_returns_none_for_no_credentials(self, quay_mirror: QuayMirror) -> None:
        result = quay_mirror.resolve_source_credentials(None)
        assert result is None

    def test_returns_user_token_string(
        self, quay_mirror: QuayMirror, mock_secret_reader: MagicMock
    ) -> None:
        mock_secret_reader.read_all.return_value = {
            "user": "pull_user",
            "token": "pull_token",
        }
        secret_ref = {
            "path": "secret/pull",
            "field": "token",
            "version": 1,
            "format": None,
        }

        result = quay_mirror.resolve_source_credentials(secret_ref)

        assert result == "pull_user:pull_token"
        mock_secret_reader.read_all.assert_called_with(secret_ref)


class TestResolveDestinationCredentials:
    """resolve_destination_credentials returns pre-fetched push
    credentials for the given org key."""

    def test_returns_credentials_for_org(self, quay_mirror: QuayMirror) -> None:
        org_key = OrgKey("quay.io", "test-org")
        result = quay_mirror.resolve_destination_credentials(org_key)
        assert result == "push_user:push_token"

    def test_missing_org_raises_key_error(self, quay_mirror: QuayMirror) -> None:
        """An org with no push credentials should raise KeyError,
        surfacing misconfiguration."""
        org_key = OrgKey("quay.io", "nonexistent-org")
        with pytest.raises(KeyError):
            quay_mirror.resolve_destination_credentials(org_key)


class TestGetPushCredsEdgeCases:
    """Edge cases in _get_push_creds that are not exercised by the
    default fixture."""

    def test_org_without_push_credentials_skipped(
        self,
        mock_gql: MagicMock,
        mock_queries: MagicMock,
        mock_secret_reader: MagicMock,
    ) -> None:
        """Orgs with pushCredentials=None are read-only and should
        not appear in the push_creds dict."""
        mock_gql.get_api.return_value.query.return_value = {
            "quay_orgs": [
                {
                    "name": "read-only-org",
                    "pushCredentials": None,
                    "instance": {"name": "quay.io", "url": "https://quay.io"},
                }
            ]
        }
        mirror = QuayMirror()
        org_key = OrgKey("quay.io", "read-only-org")
        assert org_key not in mirror.push_creds

    def test_empty_graphql_result(
        self,
        mock_gql: MagicMock,
        mock_queries: MagicMock,
        mock_secret_reader: MagicMock,
    ) -> None:
        """When the GraphQL query returns None, push_creds should be
        an empty dict."""
        mock_gql.get_api.return_value.query.return_value = None
        mirror = QuayMirror()
        assert mirror.push_creds == {}

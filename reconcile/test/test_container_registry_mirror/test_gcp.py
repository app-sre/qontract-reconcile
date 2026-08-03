from __future__ import annotations

import base64
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

from reconcile.container_registry_mirror.gcp import GcpMirror
from reconcile.container_registry_mirror.mirror_spec import MirrorSpec
from reconcile.gql_definitions.fragments.container_image_mirror import (
    ContainerImageMirror,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.gcp.gcp_docker_repos import (
    AppArtifactRegistryMirrorsItemsV1,
    AppArtifactRegistryMirrorsV1,
    AppArtifactRegistryMirrorsV1_GcpProjectV1,
    AppGcrReposItemsV1,
    AppGcrReposV1,
    AppV1,
    GcpDockerReposQueryData,
    GcpProjectV1,
)
from reconcile.gql_definitions.gcp.gcp_projects import (
    GcpProjectsQueryData,
)
from reconcile.gql_definitions.gcp.gcp_projects import (
    GcpProjectV1 as ProjectCredV1,
)


def _vault_secret(
    path: str = "secret/gcp/push",
    field: str = "token",
) -> VaultSecret:
    # VaultSecret uses Pydantic aliases: the Python attribute is
    # q_format but construction requires the alias "format".
    return VaultSecret(
        path=path,
        field=field,
        version=1,
        format=None,
    )


def _mirror(
    url: str = "docker.io/upstream/image",
    pull_credentials: VaultSecret | None = None,
    tags: list[str] | None = None,
    tags_exclude: list[str] | None = None,
) -> ContainerImageMirror:
    # ContainerImageMirror uses Pydantic aliases: Python attributes
    # are pull_credentials and tags_exclude, but construction requires
    # the aliases pullCredentials and tagsExclude.
    return ContainerImageMirror(
        url=url,
        pullCredentials=pull_credentials,
        tags=tags,
        tagsExclude=tags_exclude,
    )


def _gcr_repos_query_data(
    project_name: str = "my-gcp-project",
    repo_name: str = "my-image",
    mirror: ContainerImageMirror | None = None,
    ar_items: list | None = None,
) -> GcpDockerReposQueryData:
    """Build a GcpDockerReposQueryData with sensible defaults."""
    gcr_items = []
    if mirror is not None:
        gcr_items.append(AppGcrReposItemsV1(name=repo_name, mirror=mirror))

    gcr_repos = [
        AppGcrReposV1(
            project=GcpProjectV1(name=project_name),
            items=gcr_items,
        )
    ]

    return GcpDockerReposQueryData(
        apps=[
            AppV1(
                gcrRepos=gcr_repos,
                artifactRegistryMirrors=ar_items,
            )
        ]
    )


def _ar_repos_query_data(
    project_name: str = "my-gcp-project",
    image_url: str = "us-docker.pkg.dev/my-gcp-project/repo/image",
    mirror: ContainerImageMirror | None = None,
) -> GcpDockerReposQueryData:
    """Build query data with Artifact Registry mirrors."""
    ar_items = []
    if mirror is not None:
        ar_items.append(
            AppArtifactRegistryMirrorsItemsV1(
                imageURL=image_url,
                mirror=mirror,
            )
        )

    ar_mirrors = [
        AppArtifactRegistryMirrorsV1(
            project=AppArtifactRegistryMirrorsV1_GcpProjectV1(
                name=project_name,
            ),
            items=ar_items,
        )
    ]

    return GcpDockerReposQueryData(
        apps=[
            AppV1(
                gcrRepos=None,
                artifactRegistryMirrors=ar_mirrors,
            )
        ]
    )


def _projects_query_data(
    project_name: str = "my-gcp-project",
) -> GcpProjectsQueryData:
    """Build GcpProjectsQueryData for push credential resolution."""
    return GcpProjectsQueryData(
        gcp_projects=[
            ProjectCredV1(
                name=project_name,
                gcrPushCredentials=_vault_secret(),
                artifactPushCredentials=_vault_secret(
                    path="secret/gcp/ar-push",
                ),
            )
        ]
    )


@pytest.fixture()
def mock_gql(mocker: MockerFixture) -> MagicMock:
    mock = mocker.patch("reconcile.container_registry_mirror.gcp.gql")
    return mock


@pytest.fixture()
def mock_queries(mocker: MockerFixture) -> MagicMock:
    mock = mocker.patch("reconcile.container_registry_mirror.gcp.queries")
    return mock


@pytest.fixture()
def mock_secret_reader(mocker: MockerFixture) -> MagicMock:
    mock = mocker.patch(
        "reconcile.container_registry_mirror.gcp.SecretReader",
        autospec=True,
    )
    instance = mock.return_value
    # Default: return base64-encoded token matching GCP storage format.
    b64_token = base64.b64encode(b"decoded_push_token").decode()
    instance.read_all.return_value = {
        "user": "push_user",
        "token": b64_token,
    }
    return instance


@pytest.fixture()
def mock_gcp_repos(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("reconcile.container_registry_mirror.gcp.gql_gcp_repos")


@pytest.fixture()
def mock_gcp_projects(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("reconcile.container_registry_mirror.gcp.gql_gcp_projects")


@pytest.fixture()
def gcp_mirror(
    mock_gql: MagicMock,
    mock_queries: MagicMock,
    mock_secret_reader: MagicMock,
    mock_gcp_projects: MagicMock,
) -> GcpMirror:
    """Construct a GcpMirror with all external dependencies mocked."""
    mock_gcp_projects.query.return_value = _projects_query_data()
    return GcpMirror()


class TestDiscoverMirrors:
    """discover_mirrors() should transform the gcp_docker_repos GraphQL
    response into a list of MirrorSpec instances."""

    def test_gcr_repo_discovery(
        self,
        gcp_mirror: GcpMirror,
        mock_gcp_repos: MagicMock,
    ) -> None:
        mock_gcp_repos.query.return_value = _gcr_repos_query_data(
            mirror=_mirror(),
        )

        specs = gcp_mirror.discover_mirrors()

        assert len(specs) == 1
        spec = specs[0]
        assert isinstance(spec, MirrorSpec)
        assert spec.source_url == "docker.io/upstream/image"
        assert spec.destination_url == "gcr.io/my-gcp-project/my-image"

    def test_ar_repo_discovery(
        self,
        gcp_mirror: GcpMirror,
        mock_gcp_repos: MagicMock,
    ) -> None:
        """Artifact Registry mirrors use image_url directly as the
        destination, not a constructed gcr.io path."""
        mock_gcp_repos.query.return_value = _ar_repos_query_data(
            mirror=_mirror(),
        )

        specs = gcp_mirror.discover_mirrors()

        assert len(specs) == 1
        assert specs[0].destination_url == (
            "us-docker.pkg.dev/my-gcp-project/repo/image"
        )

    def test_tag_filters_propagated(
        self,
        gcp_mirror: GcpMirror,
        mock_gcp_repos: MagicMock,
    ) -> None:
        mock_gcp_repos.query.return_value = _gcr_repos_query_data(
            mirror=_mirror(tags=["^v[0-9]+"], tags_exclude=["^sha256"]),
        )

        specs = gcp_mirror.discover_mirrors()

        assert specs[0].tag_include == ["^v[0-9]+"]
        assert specs[0].tag_exclude == ["^sha256"]

    def test_skips_gcr_repo_with_no_mirror(
        self,
        gcp_mirror: GcpMirror,
        mock_gcp_repos: MagicMock,
    ) -> None:
        """GCR repos with mirror=None should not produce a MirrorSpec."""
        mock_gcp_repos.query.return_value = _gcr_repos_query_data(
            mirror=None,
        )

        specs = gcp_mirror.discover_mirrors()

        assert len(specs) == 0

    def test_empty_apps(
        self,
        gcp_mirror: GcpMirror,
        mock_gcp_repos: MagicMock,
    ) -> None:
        """When apps is None, no specs should be returned."""
        mock_gcp_repos.query.return_value = GcpDockerReposQueryData(
            apps=None,
        )

        specs = gcp_mirror.discover_mirrors()

        assert len(specs) == 0


class TestShouldSkipMirror:
    """GCP has no public/private distinction in its schema, so
    should_skip_mirror always returns False."""

    def test_always_returns_false(self, gcp_mirror: GcpMirror) -> None:
        result = gcp_mirror.should_skip_mirror(
            source_registry="docker.io",
            source_url="docker.io/library/nginx",
            destination_url="gcr.io/project/nginx",
            destination_public=None,
        )
        assert result is False

    def test_returns_false_even_with_public_true(self, gcp_mirror: GcpMirror) -> None:
        """Even if destination_public were somehow True, GCP
        implementation should not skip."""
        result = gcp_mirror.should_skip_mirror(
            source_registry="docker.io",
            source_url="docker.io/library/nginx",
            destination_url="gcr.io/project/nginx",
            destination_public=True,
        )
        assert result is False


class TestResolveSourceCredentials:
    """resolve_source_credentials reads pull credentials from Vault."""

    def test_returns_none_for_no_credentials(self, gcp_mirror: GcpMirror) -> None:
        result = gcp_mirror.resolve_source_credentials(None)
        assert result is None

    def test_returns_user_token_string(
        self, gcp_mirror: GcpMirror, mock_secret_reader: MagicMock
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

        result = gcp_mirror.resolve_source_credentials(secret_ref)

        assert result == "pull_user:pull_token"


class TestResolveDestinationCredentials:
    """resolve_destination_credentials returns pre-fetched credentials
    with base64-decoded tokens."""

    def test_gcr_credentials(self, gcp_mirror: GcpMirror) -> None:
        """GCR destinations use the gcr_ prefix for credential lookup."""
        result = gcp_mirror.resolve_destination_credentials(
            "gcr.io/my-gcp-project/image"
        )
        # Token was base64-encoded in Vault; should be decoded now.
        assert "decoded_push_token" in result
        assert result.startswith("push_user:")

    def test_ar_credentials(self, gcp_mirror: GcpMirror) -> None:
        """Artifact Registry destinations (pkg.dev) use the ar_ prefix."""
        result = gcp_mirror.resolve_destination_credentials(
            "us-docker.pkg.dev/my-gcp-project/repo/image"
        )
        assert "decoded_push_token" in result

    def test_missing_project_raises_key_error(self, gcp_mirror: GcpMirror) -> None:
        with pytest.raises(KeyError):
            gcp_mirror.resolve_destination_credentials(
                "gcr.io/nonexistent-project/image"
            )

    def test_short_url_raises_key_error(self, gcp_mirror: GcpMirror) -> None:
        """A destination URL with no path segments should raise KeyError
        because the project name cannot be extracted."""
        with pytest.raises(KeyError, match="Cannot extract project"):
            gcp_mirror.resolve_destination_credentials("noslash")


class TestDiscoverMirrorsWithPullCredentials:
    """discover_mirrors should resolve pull credentials when present
    on the mirror definition."""

    def test_pull_credentials_resolved(
        self,
        gcp_mirror: GcpMirror,
        mock_gcp_repos: MagicMock,
        mock_secret_reader: MagicMock,
    ) -> None:
        mock_secret_reader.read_all.return_value = {
            "user": "pull_user",
            "token": "pull_token",
        }
        mock_gcp_repos.query.return_value = _gcr_repos_query_data(
            mirror=_mirror(pull_credentials=_vault_secret(path="secret/pull")),
        )

        specs = gcp_mirror.discover_mirrors()

        assert len(specs) == 1
        assert specs[0].source_creds == "pull_user:pull_token"


class TestGetPushCredsWithoutGcr:
    """When a GCP project has no GCR push credentials (fully migrated
    to Artifact Registry), only the ar_ prefixed credential should
    be stored."""

    def test_no_gcr_creds(
        self,
        mock_gql: MagicMock,
        mock_queries: MagicMock,
        mock_secret_reader: MagicMock,
        mock_gcp_projects: MagicMock,
    ) -> None:
        # Build a project with gcrPushCredentials=None.
        mock_gcp_projects.query.return_value = GcpProjectsQueryData(
            gcp_projects=[
                ProjectCredV1(
                    name="ar-only-project",
                    gcrPushCredentials=None,
                    artifactPushCredentials=_vault_secret(
                        path="secret/gcp/ar-push",
                    ),
                )
            ]
        )
        mirror = GcpMirror()

        assert "gcr_ar-only-project" not in mirror.push_creds
        assert "ar_ar-only-project" in mirror.push_creds

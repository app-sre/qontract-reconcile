from unittest.mock import create_autospec

import pytest
from pytest_mock import MockerFixture, MockFixture

from reconcile.gcp_image_mirror import ImageSyncItem, QuayMirror
from reconcile.gql_definitions.fragments.container_image_mirror import (
    ContainerImageMirror,
)
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
from reconcile.utils.gql import GqlApi

TEST_PROJECT_NAME = "foo"
AR_IMAGE_URL = f"us-docker.pkg.dev/{TEST_PROJECT_NAME}/terraform-repo-executor"


@pytest.fixture()
def qr_project() -> ContainerImageMirror:
    return ContainerImageMirror(
        url="quay.io/app-sre/qontract-reconcile",
        pullCredentials=None,
        tags=None,
        tagsExclude=None,
    )


@pytest.fixture()
def tf_repo_project() -> ContainerImageMirror:
    return ContainerImageMirror(
        url="quay.io/app-sre/terraform-repo-executor",
        pullCredentials=None,
        tags=None,
        tagsExclude=None,
    )


@pytest.fixture()
def repo_query_gql(
    qr_project: ContainerImageMirror, tf_repo_project: ContainerImageMirror
) -> GcpDockerReposQueryData:
    return GcpDockerReposQueryData(
        apps=[
            AppV1(
                gcrRepos=[
                    AppGcrReposV1(
                        project=GcpProjectV1(name=TEST_PROJECT_NAME),
                        items=[
                            AppGcrReposItemsV1(
                                mirror=qr_project, name="qontract-reconcile"
                            )
                        ],
                    )
                ],
                artifactRegistryMirrors=[
                    AppArtifactRegistryMirrorsV1(
                        project=AppArtifactRegistryMirrorsV1_GcpProjectV1(
                            name=TEST_PROJECT_NAME
                        ),
                        items=[
                            AppArtifactRegistryMirrorsItemsV1(
                                mirror=tf_repo_project, imageURL=AR_IMAGE_URL
                            )
                        ],
                    )
                ],
            )
        ]
    )


@pytest.fixture()
def expected_sync_results(
    qr_project: ContainerImageMirror, tf_repo_project: ContainerImageMirror
) -> list[ImageSyncItem]:
    return [
        ImageSyncItem(
            mirror=qr_project,
            destination_url=f"gcr.io/{TEST_PROJECT_NAME}/qontract-reconcile",
            org_name=TEST_PROJECT_NAME,
        ),
        ImageSyncItem(
            mirror=tf_repo_project,
            destination_url=AR_IMAGE_URL,
            org_name=TEST_PROJECT_NAME,
        ),
    ]


@pytest.fixture()
def setup_mocks(mocker: MockFixture) -> None:
    mocked_gql_api = create_autospec(GqlApi)
    mocker.patch("reconcile.gcp_image_mirror.gql").get_api.return_value = mocked_gql_api
    mocked_queries = mocker.patch("reconcile.gcp_image_mirror.queries")
    mocked_queries.get_app_interface_settings.return_value = {}
    mocker.patch.object(QuayMirror, "_get_push_creds").return_value = {}


def test_gcp_mirror_session(setup_mocks: None, mocker: MockerFixture) -> None:
    mocked_request = mocker.patch("reconcile.gcp_image_mirror.requests")

    with QuayMirror() as gcr_mirror:
        assert gcr_mirror.session == mocked_request.Session.return_value

    mocked_request.Session.return_value.close.assert_called_once_with()


def test_process_repos_to_sync(
    setup_mocks: None,
    repo_query_gql: GcpDockerReposQueryData,
    expected_sync_results: list[ImageSyncItem],
) -> None:
    with QuayMirror() as gcp_image_mirror:
        assert (
            gcp_image_mirror.process_repos_to_sync(repo_query_gql)
            == expected_sync_results
        )

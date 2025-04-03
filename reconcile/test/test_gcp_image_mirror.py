from pytest_mock import MockerFixture

from reconcile.gcp_image_mirror import QuayMirror


def test_gcp_mirror_session(mocker: MockerFixture) -> None:
    mocker.patch("reconcile.gcr_mirror.gql")
    mocker.patch("reconcile.gcr_mirror.queries")
    mocked_request = mocker.patch("reconcile.gcr_mirror.requests")

    with QuayMirror() as gcr_mirror:
        assert gcr_mirror.session == mocked_request.Session.return_value

    mocked_request.Session.return_value.close.assert_called_once_with()


# TODO query_repos_to_sync against AR, GCP

# TODO _get_push_creds test

# TODO get_sync_tasks test

# how do i mock the GQL api?

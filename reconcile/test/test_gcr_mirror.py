from pytest_mock import MockerFixture

from reconcile.gcr_mirror import QuayMirror


def test_gcr_mirror_session(mocker: MockerFixture) -> None:
    mocker.patch("reconcile.gcr_mirror.gql")
    mocker.patch("reconcile.gcr_mirror.queries")
    mocked_request = mocker.patch("reconcile.gcr_mirror.requests")

    with QuayMirror() as gcr_mirror:
        assert gcr_mirror.session == mocked_request.Session.return_value

    mocked_request.Session.return_value.close.assert_called_once_with()

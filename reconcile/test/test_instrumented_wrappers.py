from unittest.mock import create_autospec

from prometheus_client import Counter
from pytest_mock import MockerFixture
from requests import Session
from sretoolbox.container import (
    Image,
    Skopeo,
)

from reconcile.utils.instrumented_wrappers import (
    InstrumentedImage,
    InstrumentedSession,
    InstrumentedSkopeo,
)


def test_instrumented_image(mocker: MockerFixture) -> None:
    mocked_get_manifest = mocker.patch.object(Image, "_get_manifest")
    mocked_metrics = mocker.patch("reconcile.utils.instrumented_wrappers.metrics")
    image = InstrumentedImage("aregistry/animage:atag")

    result = image._get_manifest()

    assert result == mocked_get_manifest.return_value
    mocked_get_manifest.assert_called_once_with()
    mocked_metrics.registry_reachouts.labels.assert_called_once_with(
        integration="",
        shard=1,
        shard_id=0,
        registry="docker.io",
    )
    mocked_metrics.registry_reachouts.labels.return_value.inc.assert_called_once_with()


def test_instrumented_skopeo(mocker: MockerFixture) -> None:
    mocked_copy = mocker.patch.object(Skopeo, "copy")
    mocked_metrics = mocker.patch("reconcile.utils.instrumented_wrappers.metrics")
    skopeo = InstrumentedSkopeo()

    result = skopeo.copy(
        "source",
        "dest",
        source_creds="creds",
    )

    assert result == mocked_copy.return_value
    mocked_copy.assert_called_once_with(
        "source",
        "dest",
        source_creds="creds",
    )
    mocked_metrics.copy_count.labels.assert_called_once_with(
        integration="",
        shard=1,
        shard_id=0,
    )
    mocked_metrics.copy_count.labels.return_value.inc.assert_called_once_with()


def test_instrumented_session(mocker: MockerFixture) -> None:
    mocked_request = mocker.patch.object(Session, "request")
    counter = create_autospec(Counter)
    session = InstrumentedSession(counter)

    result = session.request(
        "GET",
        "https://gitlab.example.com",
        params={"k", "v"},
    )

    assert result == mocked_request.return_value
    mocked_request.assert_called_once_with(
        "GET",
        "https://gitlab.example.com",
        params={"k", "v"},
    )
    counter.inc.assert_called_once_with()

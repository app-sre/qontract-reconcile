import datetime
from typing import Any
from unittest.mock import call, create_autospec

import pytest
from deepdiff import DeepHash
from pytest_mock import MockerFixture

from reconcile.utils.early_exit_cache import (
    CacheKey,
    CacheStatus,
    CacheValue,
    EarlyExitCache,
)
from reconcile.utils.state import State

INTEGRATION_NAME = "some-integration"
INTEGRATION_VERSION = "some-integration-version"
CACHE_SOURCE = {"k": "v"}
CACHE_SOURCE_DIGEST = DeepHash(CACHE_SOURCE)[CACHE_SOURCE]

DRY_RUN_CACHE_KEY = CacheKey(
    integration=INTEGRATION_NAME,
    integration_version=INTEGRATION_VERSION,
    dry_run=True,
    cache_source=CACHE_SOURCE,
)

DRY_RUN_CACHE_VALUE = CacheValue(
    payload={"k1": "v1"},
    log_output="some-log-output-1",
    applied_count=0,
)

NO_DRY_RUN_CACHE_KEY = CacheKey(
    integration=INTEGRATION_NAME,
    integration_version=INTEGRATION_VERSION,
    dry_run=False,
    cache_source=CACHE_SOURCE,
)


NO_DRY_RUN_CACHE_VALUE = CacheValue(
    payload={"k2": "v2"},
    log_output="some-log-output-2",
    applied_count=1,
)


@pytest.fixture
def state() -> Any:
    return create_autospec(State)


def test_early_exit_cache_build(
    mocker: MockerFixture,
    state: Any,
    secret_reader: Any,
) -> None:
    mocked_init_state = mocker.patch(
        "reconcile.utils.early_exit_cache.init_state",
        return_value=state,
    )

    with EarlyExitCache.build(secret_reader):
        pass

    mocked_init_state.assert_called_once_with("early-exit-cache", secret_reader)
    state.cleanup.assert_called_once_with()


@pytest.fixture
def early_exit_cache(state: Any) -> EarlyExitCache:
    return EarlyExitCache(state)


@pytest.mark.parametrize(
    "integration, integration_version, dry_run, cache_source, expected",
    [
        (
            INTEGRATION_NAME,
            INTEGRATION_VERSION,
            False,
            CACHE_SOURCE,
            f"{INTEGRATION_NAME}/{INTEGRATION_VERSION}/no-dry-run/latest",
        ),
        (
            INTEGRATION_NAME,
            INTEGRATION_VERSION,
            True,
            CACHE_SOURCE,
            f"{INTEGRATION_NAME}/{INTEGRATION_VERSION}/dry-run/{CACHE_SOURCE_DIGEST}",
        ),
    ],
)
def test_cache_key_string(
    integration: str,
    integration_version: str,
    dry_run: bool,
    cache_source: Any,
    expected: str,
) -> None:
    cache_key = CacheKey(
        integration=integration,
        integration_version=integration_version,
        dry_run=dry_run,
        cache_source=cache_source,
    )
    assert str(cache_key) == expected


@pytest.fixture
def cache_value() -> CacheValue:
    return CacheValue(
        payload={"k": "v"},
        log_output="some-log-output",
        applied_count=1,
    )


@pytest.mark.parametrize(
    "cache_key, cache_value",
    [
        (DRY_RUN_CACHE_KEY, DRY_RUN_CACHE_VALUE),
        (NO_DRY_RUN_CACHE_KEY, NO_DRY_RUN_CACHE_VALUE),
    ],
)
def test_early_exit_cache_get(
    early_exit_cache: EarlyExitCache,
    state: Any,
    cache_key: CacheKey,
    cache_value: CacheValue,
) -> None:
    state.get.return_value = cache_value.dict()

    value = early_exit_cache.get(cache_key)

    assert value == cache_value
    state.get.assert_called_once_with(str(cache_key))


@pytest.fixture
def mock_datetime(mocker: MockerFixture) -> Any:
    mocked_datetime = mocker.patch(
        "reconcile.utils.early_exit_cache.datetime",
    )
    mocked_datetime.fromtimestamp.side_effect = datetime.datetime.fromtimestamp
    return mocked_datetime


@pytest.mark.parametrize(
    "cache_key, cache_value",
    [
        (DRY_RUN_CACHE_KEY, DRY_RUN_CACHE_VALUE),
        (NO_DRY_RUN_CACHE_KEY, NO_DRY_RUN_CACHE_VALUE),
    ],
)
def test_early_exit_cache_set(
    mock_datetime: Any,
    early_exit_cache: EarlyExitCache,
    state: Any,
    cache_key: CacheKey,
    cache_value: CacheValue,
) -> None:
    now = datetime.datetime.now(tz=datetime.UTC)
    mock_datetime.now.return_value = now

    early_exit_cache.set(cache_key, cache_value, 100)

    expected_expire_at = str(int((now + datetime.timedelta(seconds=100)).timestamp()))
    state.add.assert_called_once_with(
        str(cache_key),
        cache_value.dict(),
        metadata={
            "expire-at": expected_expire_at,
            "cache-source-digest": CACHE_SOURCE_DIGEST,
        },
        force=True,
    )


@pytest.mark.parametrize(
    "cache_key",
    [
        DRY_RUN_CACHE_KEY,
        NO_DRY_RUN_CACHE_KEY,
    ],
)
def test_early_exit_cache_head_miss(
    early_exit_cache: EarlyExitCache,
    state: Any,
    cache_key: CacheKey,
) -> None:
    state.head.return_value = (False, {})

    status = early_exit_cache.head(cache_key)

    assert status == CacheStatus.MISS
    state.head.assert_called_once_with(str(cache_key))


def test_early_exit_cache_head_no_dry_run_miss(
    early_exit_cache: EarlyExitCache,
    state: Any,
) -> None:
    state.head.return_value = (
        True,
        {
            "cache-source-digest": "different-digest",
        },
    )

    status = early_exit_cache.head(NO_DRY_RUN_CACHE_KEY)

    assert status == CacheStatus.MISS
    state.head.assert_called_once_with(str(NO_DRY_RUN_CACHE_KEY))


@pytest.mark.parametrize(
    "cache_key, expire_at_offset",
    [
        (DRY_RUN_CACHE_KEY, -1),
        (NO_DRY_RUN_CACHE_KEY, -1),
        (DRY_RUN_CACHE_KEY, 0),
        (NO_DRY_RUN_CACHE_KEY, 0),
    ],
)
def test_early_exit_cache_head_expired(
    mock_datetime: Any,
    early_exit_cache: EarlyExitCache,
    state: Any,
    cache_key: CacheKey,
    expire_at_offset: int,
) -> None:
    now = datetime.datetime.now(tz=datetime.UTC)
    mock_datetime.now.return_value = now
    state.head.return_value = (
        True,
        {
            "expire-at": str(int(now.timestamp()) + expire_at_offset),
            "cache-source-digest": CACHE_SOURCE_DIGEST,
        },
    )

    status = early_exit_cache.head(cache_key)

    assert status == CacheStatus.EXPIRED
    state.head.assert_called_once_with(str(cache_key))


def test_early_exit_cache_head_dry_run_stale(
    mock_datetime: Any,
    early_exit_cache: EarlyExitCache,
    state: Any,
) -> None:
    now = datetime.datetime.now(tz=datetime.UTC)
    mock_datetime.now.return_value = now
    state.head.side_effect = [
        (
            True,
            {
                "expire-at": str(int(now.timestamp()) + 1),
            },
        ),
        (
            True,
            {
                "cache-source-digest": "different-digest",
            },
        ),
    ]

    status = early_exit_cache.head(DRY_RUN_CACHE_KEY)

    assert status == CacheStatus.STALE
    state.head.assert_has_calls(
        [
            call(str(DRY_RUN_CACHE_KEY)),
            call(DRY_RUN_CACHE_KEY.no_dry_run_path()),
        ],
    )


def test_early_exit_cache_head_no_dry_run_hit(
    mock_datetime: Any,
    early_exit_cache: EarlyExitCache,
    state: Any,
) -> None:
    now = datetime.datetime.now(tz=datetime.UTC)
    mock_datetime.now.return_value = now
    state.head.return_value = (
        True,
        {
            "expire-at": str(int(now.timestamp()) + 1),
            "cache-source-digest": CACHE_SOURCE_DIGEST,
        },
    )

    status = early_exit_cache.head(NO_DRY_RUN_CACHE_KEY)

    assert status == CacheStatus.HIT
    state.head.assert_called_once_with(str(NO_DRY_RUN_CACHE_KEY))


def test_early_exit_cache_head_dry_run_hit(
    mock_datetime: Any,
    early_exit_cache: EarlyExitCache,
    state: Any,
) -> None:
    now = datetime.datetime.now(tz=datetime.UTC)
    mock_datetime.now.return_value = now
    state.head.side_effect = [
        (
            True,
            {
                "expire-at": str(int(now.timestamp()) + 1),
            },
        ),
        (
            True,
            {
                "cache-source-digest": CACHE_SOURCE_DIGEST,
            },
        ),
    ]

    status = early_exit_cache.head(DRY_RUN_CACHE_KEY)

    assert status == CacheStatus.HIT
    state.head.assert_has_calls(
        [
            call(str(DRY_RUN_CACHE_KEY)),
            call(DRY_RUN_CACHE_KEY.no_dry_run_path()),
        ],
    )

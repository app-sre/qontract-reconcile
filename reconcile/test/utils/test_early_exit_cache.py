import datetime
from typing import Any
from unittest.mock import create_autospec

import pytest
from deepdiff import DeepHash
from pytest_mock import MockerFixture

from reconcile.utils.early_exit_cache import (
    CacheKey,
    CacheStatus,
    CacheValue,
    EarlyExitCache,
)
from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.state import State


@pytest.fixture
def state() -> Any:
    return create_autospec(State)


@pytest.fixture
def secret_reader() -> Any:
    return create_autospec(SecretReaderBase)


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
    "integration, integration_version, dry_run, cache_desired_state, expected",
    [
        (
            "some-integration",
            "some-version",
            False,
            "state",
            f"some-integration/some-version/no-dry-run/{DeepHash('state')['state']}",
        ),
        (
            "some-integration",
            "some-version",
            True,
            "state",
            f"some-integration/some-version/dry-run/{DeepHash('state')['state']}",
        ),
    ],
)
def test_cache_key_string(
    integration: str,
    integration_version: str,
    dry_run: bool,
    cache_desired_state: Any,
    expected: str,
) -> None:
    cache_key = CacheKey(
        integration=integration,
        integration_version=integration_version,
        dry_run=dry_run,
        cache_desired_state=cache_desired_state,
    )

    assert str(cache_key) == expected


@pytest.fixture
def cache_key() -> CacheKey:
    return CacheKey(
        integration="some-integration",
        integration_version="some-integration-version",
        dry_run=False,
        cache_desired_state={"k": "v"},
    )


@pytest.fixture
def cache_value() -> CacheValue:
    return CacheValue(
        desired_state={"k": "v"},
        log_output="some-log-output",
        applied_count=1,
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


def test_early_exit_cache_set(
    mocker: MockerFixture,
    early_exit_cache: EarlyExitCache,
    state: Any,
    cache_key: CacheKey,
    cache_value: CacheValue,
) -> None:
    mock_datetime = mocker.patch(
        "reconcile.utils.early_exit_cache.datetime",
    )
    now = datetime.datetime.now(tz=datetime.UTC)
    mock_datetime.now.return_value = now

    early_exit_cache.set(cache_key, cache_value, 100)

    expected_expire_at = str(int((now + datetime.timedelta(seconds=100)).timestamp()))
    state.add.assert_called_once_with(
        str(cache_key),
        cache_value.dict(),
        metadata={"expire-at": expected_expire_at},
        force=True,
    )


def test_early_exit_cache_head_miss(
    early_exit_cache: EarlyExitCache,
    state: Any,
    cache_key: CacheKey,
) -> None:
    state.head.return_value = (False, {})

    status = early_exit_cache.head(cache_key)

    assert status == CacheStatus.MISS


@pytest.mark.parametrize(
    "expire_at_offset, expected_status",
    [
        (-1, CacheStatus.EXPIRED),
        (0, CacheStatus.EXPIRED),
        (1, CacheStatus.HIT),
    ],
)
def test_early_exit_cache_head(
    mocker: MockerFixture,
    early_exit_cache: EarlyExitCache,
    state: Any,
    cache_key: CacheKey,
    expire_at_offset: int,
    expected_status: CacheStatus,
) -> None:
    now = datetime.datetime.now(tz=datetime.UTC)
    mock_datetime = mocker.patch(
        "reconcile.utils.early_exit_cache.datetime",
    )
    mock_datetime.now.return_value = now
    mock_datetime.fromtimestamp.side_effect = datetime.datetime.fromtimestamp
    state.head.return_value = (
        True,
        {"expire-at": str(int(now.timestamp()) + expire_at_offset)},
    )

    status = early_exit_cache.head(cache_key)

    assert status == expected_status

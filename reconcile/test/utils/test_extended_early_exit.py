import logging
from logging import Logger
from typing import Any
from unittest.mock import MagicMock, call, create_autospec

import pytest
from pydantic import BaseModel
from pytest_mock import MockerFixture

from reconcile.utils.early_exit_cache import (
    CacheKey,
    CacheStatus,
    CacheValue,
    EarlyExitCache,
)
from reconcile.utils.extended_early_exit import (
    ExtendedEarlyExitRunnerResult,
    extended_early_exit_run,
)
from reconcile.utils.secret_reader import SecretReaderBase

INTEGRATION = "some-integration"
INTEGRATION_VERSION = "some-integration-version"
SHORT_TTL_SECONDS = 10
TTLS_SECONDS = 100


@pytest.fixture
def logger() -> Logger:
    return logging.getLogger("some-logger")


class TestRunnerParams(BaseModel):
    some_param: str


RUNNER_PARAMS = TestRunnerParams(some_param="some-value")


@pytest.fixture
def early_exit_cache() -> Any:
    return create_autospec(EarlyExitCache)


CACHE_DESIRED_STATE = {"k": "v"}


@pytest.mark.parametrize(
    "cache_status, applied_count, expected_ttl",
    [
        (CacheStatus.MISS, 0, TTLS_SECONDS),
        (CacheStatus.MISS, 1, SHORT_TTL_SECONDS),
        (CacheStatus.EXPIRED, 0, TTLS_SECONDS),
        (CacheStatus.EXPIRED, 1, SHORT_TTL_SECONDS),
    ],
)
def test_extended_early_exit_run_miss_or_expired_when_no_dry_run(
    mocker: MockerFixture,
    logger: Logger,
    secret_reader: SecretReaderBase,
    early_exit_cache: Any,
    cache_status: CacheStatus,
    applied_count: int,
    expected_ttl: int,
) -> None:
    mock_early_exit_cache = mocker.patch(
        "reconcile.utils.extended_early_exit.EarlyExitCache",
        autospec=True,
    )
    mock_early_exit_cache.build.return_value.__enter__.return_value = early_exit_cache
    early_exit_cache.head.return_value = cache_status
    runner = MagicMock()
    desired_state = {"k": "v2"}
    runner.return_value = ExtendedEarlyExitRunnerResult(
        desired_state=desired_state,
        applied_count=applied_count,
    )

    extended_early_exit_run(
        integration=INTEGRATION,
        integration_version=INTEGRATION_VERSION,
        dry_run=False,
        cache_desired_state=CACHE_DESIRED_STATE,
        short_ttl_seconds=SHORT_TTL_SECONDS,
        ttl_seconds=TTLS_SECONDS,
        logger=logger,
        runner=runner,
        runner_params=RUNNER_PARAMS,
        secret_reader=secret_reader,
    )

    early_exit_cache.head.assert_called_once_with(
        CacheKey(
            integration=INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=False,
            cache_desired_state=CACHE_DESIRED_STATE,
        )
    )
    runner.assert_called_once_with(**RUNNER_PARAMS.dict())
    early_exit_cache.set.assert_called_once_with(
        CacheKey(
            integration=INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=False,
            cache_desired_state=CACHE_DESIRED_STATE,
        ),
        CacheValue(
            desired_state=desired_state,
            log_output="",
            applied_count=applied_count,
        ),
        expected_ttl,
    )


@pytest.mark.parametrize(
    "cache_status",
    [
        CacheStatus.MISS,
        CacheStatus.EXPIRED,
    ],
)
def test_extended_early_exit_run_miss_or_expired_in_dry_run_but_hit_in_no_dry_run(
    mocker: MockerFixture,
    logger: Logger,
    secret_reader: SecretReaderBase,
    early_exit_cache: Any,
    cache_status: CacheStatus,
) -> None:
    mock_early_exit_cache = mocker.patch(
        "reconcile.utils.extended_early_exit.EarlyExitCache",
        autospec=True,
    )
    mock_early_exit_cache.build.return_value.__enter__.return_value = early_exit_cache
    early_exit_cache.head.side_effect = [
        cache_status,
        CacheStatus.HIT,
    ]
    runner = MagicMock()

    extended_early_exit_run(
        integration=INTEGRATION,
        integration_version=INTEGRATION_VERSION,
        dry_run=True,
        cache_desired_state=CACHE_DESIRED_STATE,
        short_ttl_seconds=SHORT_TTL_SECONDS,
        ttl_seconds=TTLS_SECONDS,
        logger=logger,
        runner=runner,
        runner_params=RUNNER_PARAMS,
        secret_reader=secret_reader,
    )

    early_exit_cache.head.assert_has_calls([
        call(
            CacheKey(
                integration=INTEGRATION,
                integration_version=INTEGRATION_VERSION,
                dry_run=True,
                cache_desired_state=CACHE_DESIRED_STATE,
            )
        ),
        call(
            CacheKey(
                integration=INTEGRATION,
                integration_version=INTEGRATION_VERSION,
                dry_run=False,
                cache_desired_state=CACHE_DESIRED_STATE,
            )
        ),
    ])
    runner.assert_not_called()
    early_exit_cache.set.assert_not_called()


@pytest.mark.parametrize(
    "cache_status",
    [
        CacheStatus.MISS,
        CacheStatus.EXPIRED,
    ],
)
def test_extended_early_exit_run_miss_or_expired_in_both_dry_run_and_no_dry_run(
    mocker: MockerFixture,
    logger: Logger,
    secret_reader: SecretReaderBase,
    early_exit_cache: Any,
    cache_status: CacheStatus,
) -> None:
    mock_early_exit_cache = mocker.patch(
        "reconcile.utils.extended_early_exit.EarlyExitCache",
        autospec=True,
    )
    mock_early_exit_cache.build.return_value.__enter__.return_value = early_exit_cache
    early_exit_cache.head.return_value = cache_status
    runner = MagicMock()
    desired_state = {"k": "v2"}
    runner.return_value = ExtendedEarlyExitRunnerResult(
        desired_state=desired_state,
        applied_count=0,
    )

    extended_early_exit_run(
        integration=INTEGRATION,
        integration_version=INTEGRATION_VERSION,
        dry_run=True,
        cache_desired_state=CACHE_DESIRED_STATE,
        short_ttl_seconds=SHORT_TTL_SECONDS,
        ttl_seconds=TTLS_SECONDS,
        logger=logger,
        runner=runner,
        runner_params=RUNNER_PARAMS,
        secret_reader=secret_reader,
    )

    early_exit_cache.head.assert_has_calls([
        call(
            CacheKey(
                integration=INTEGRATION,
                integration_version=INTEGRATION_VERSION,
                dry_run=True,
                cache_desired_state=CACHE_DESIRED_STATE,
            )
        ),
        call(
            CacheKey(
                integration=INTEGRATION,
                integration_version=INTEGRATION_VERSION,
                dry_run=False,
                cache_desired_state=CACHE_DESIRED_STATE,
            )
        ),
    ])
    runner.assert_called_once_with(**RUNNER_PARAMS.dict())
    early_exit_cache.set.assert_called_once_with(
        CacheKey(
            integration=INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=True,
            cache_desired_state=CACHE_DESIRED_STATE,
        ),
        CacheValue(
            desired_state=desired_state,
            log_output="",
            applied_count=0,
        ),
        TTLS_SECONDS,
    )


@pytest.mark.parametrize(
    "dry_run",
    [
        True,
        False,
    ],
)
def test_extended_early_exit_run_hit(
    mocker: MockerFixture,
    logger: Logger,
    secret_reader: SecretReaderBase,
    early_exit_cache: Any,
    dry_run: bool,
) -> None:
    mock_early_exit_cache = mocker.patch(
        "reconcile.utils.extended_early_exit.EarlyExitCache",
        autospec=True,
    )
    mock_early_exit_cache.build.return_value.__enter__.return_value = early_exit_cache
    early_exit_cache.head.return_value = CacheStatus.HIT
    runner = MagicMock()

    extended_early_exit_run(
        integration=INTEGRATION,
        integration_version=INTEGRATION_VERSION,
        dry_run=dry_run,
        cache_desired_state=CACHE_DESIRED_STATE,
        short_ttl_seconds=SHORT_TTL_SECONDS,
        ttl_seconds=TTLS_SECONDS,
        logger=logger,
        runner=runner,
        runner_params=RUNNER_PARAMS,
        secret_reader=secret_reader,
    )

    early_exit_cache.head.assert_called_once_with(
        CacheKey(
            integration=INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=dry_run,
            cache_desired_state=CACHE_DESIRED_STATE,
        )
    )
    runner.assert_not_called()
    early_exit_cache.set.assert_not_called()

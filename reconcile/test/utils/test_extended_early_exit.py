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
    logger = logging.getLogger("some-logger")
    logger.setLevel(logging.INFO)
    return logger


@pytest.fixture
def mock_logger() -> Any:
    return create_autospec(Logger)


class TestRunnerParams(BaseModel):
    some_param: str


RUNNER_PARAMS = TestRunnerParams(some_param="some-value")


@pytest.fixture
def early_exit_cache() -> Any:
    return create_autospec(EarlyExitCache)


CACHE_SOURCE = {"k": "v"}


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
    info_log_output = "some-log-output"
    warning_log_output = "some-warning-output"
    error_log_output = "some-error-output"
    expected_log_output = (
        "\n".join([
            info_log_output,
            warning_log_output,
            error_log_output,
        ])
        + "\n"
    )

    def runner_side_effect(**_: Any) -> ExtendedEarlyExitRunnerResult:
        logger.info(info_log_output)
        logger.warning(warning_log_output)
        logger.error(error_log_output)
        return ExtendedEarlyExitRunnerResult(
            payload=desired_state,
            applied_count=applied_count,
        )

    runner.side_effect = runner_side_effect

    extended_early_exit_run(
        integration=INTEGRATION,
        integration_version=INTEGRATION_VERSION,
        dry_run=False,
        cache_source=CACHE_SOURCE,
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
            cache_source=CACHE_SOURCE,
        )
    )
    runner.assert_called_once_with(**RUNNER_PARAMS.dict())
    early_exit_cache.set.assert_called_once_with(
        CacheKey(
            integration=INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=False,
            cache_source=CACHE_SOURCE,
        ),
        CacheValue(
            payload=desired_state,
            log_output=expected_log_output,
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
    mock_logger: Any,
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
    expected_log_output = "some-log-output"
    early_exit_cache.get.return_value = CacheValue(
        payload=CACHE_SOURCE,
        log_output=expected_log_output,
        applied_count=1,
    )
    runner = MagicMock()

    extended_early_exit_run(
        integration=INTEGRATION,
        integration_version=INTEGRATION_VERSION,
        dry_run=True,
        cache_source=CACHE_SOURCE,
        short_ttl_seconds=SHORT_TTL_SECONDS,
        ttl_seconds=TTLS_SECONDS,
        logger=mock_logger,
        runner=runner,
        runner_params=RUNNER_PARAMS,
        secret_reader=secret_reader,
        log_cached_log_output=True,
    )

    early_exit_cache.head.assert_has_calls([
        call(
            CacheKey(
                integration=INTEGRATION,
                integration_version=INTEGRATION_VERSION,
                dry_run=True,
                cache_source=CACHE_SOURCE,
            )
        ),
        call(
            CacheKey(
                integration=INTEGRATION,
                integration_version=INTEGRATION_VERSION,
                dry_run=False,
                cache_source=CACHE_SOURCE,
            )
        ),
    ])
    early_exit_cache.get.assert_called_once_with(
        CacheKey(
            integration=INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=False,
            cache_source=CACHE_SOURCE,
        )
    )
    mock_logger.info.assert_called_once_with(expected_log_output)
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
        payload=desired_state,
        applied_count=0,
    )

    extended_early_exit_run(
        integration=INTEGRATION,
        integration_version=INTEGRATION_VERSION,
        dry_run=True,
        cache_source=CACHE_SOURCE,
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
                cache_source=CACHE_SOURCE,
            )
        ),
        call(
            CacheKey(
                integration=INTEGRATION,
                integration_version=INTEGRATION_VERSION,
                dry_run=False,
                cache_source=CACHE_SOURCE,
            )
        ),
    ])
    runner.assert_called_once_with(**RUNNER_PARAMS.dict())
    early_exit_cache.set.assert_called_once_with(
        CacheKey(
            integration=INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=True,
            cache_source=CACHE_SOURCE,
        ),
        CacheValue(
            payload=desired_state,
            log_output="",
            applied_count=0,
        ),
        TTLS_SECONDS,
    )


def test_extended_early_exit_run_hit_when_not_dry_run(
    mocker: MockerFixture,
    logger: Logger,
    secret_reader: SecretReaderBase,
    early_exit_cache: Any,
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
        dry_run=False,
        cache_source=CACHE_SOURCE,
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
            cache_source=CACHE_SOURCE,
        )
    )
    runner.assert_not_called()
    early_exit_cache.set.assert_not_called()


def test_extended_early_exit_run_hit_when_dry_run(
    mocker: MockerFixture,
    mock_logger: Any,
    secret_reader: SecretReaderBase,
    early_exit_cache: Any,
) -> None:
    mock_early_exit_cache = mocker.patch(
        "reconcile.utils.extended_early_exit.EarlyExitCache",
        autospec=True,
    )
    mock_early_exit_cache.build.return_value.__enter__.return_value = early_exit_cache
    early_exit_cache.head.return_value = CacheStatus.HIT
    early_exit_cache.get.return_value = CacheValue(
        payload=CACHE_SOURCE,
        log_output="log-output",
        applied_count=1,
    )
    runner = MagicMock()

    extended_early_exit_run(
        integration=INTEGRATION,
        integration_version=INTEGRATION_VERSION,
        dry_run=True,
        cache_source=CACHE_SOURCE,
        short_ttl_seconds=SHORT_TTL_SECONDS,
        ttl_seconds=TTLS_SECONDS,
        logger=mock_logger,
        runner=runner,
        runner_params=RUNNER_PARAMS,
        secret_reader=secret_reader,
        log_cached_log_output=True,
    )

    early_exit_cache.head.assert_called_once_with(
        CacheKey(
            integration=INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=True,
            cache_source=CACHE_SOURCE,
        )
    )
    early_exit_cache.get.assert_called_once_with(
        CacheKey(
            integration=INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=True,
            cache_source=CACHE_SOURCE,
        )
    )
    mock_logger.info.assert_called_once_with("log-output")
    runner.assert_not_called()
    early_exit_cache.set.assert_not_called()


def test_extended_early_exit_run_when_error(
    mocker: MockerFixture,
    mock_logger: Any,
    secret_reader: SecretReaderBase,
    early_exit_cache: Any,
) -> None:
    mock_early_exit_cache = mocker.patch(
        "reconcile.utils.extended_early_exit.EarlyExitCache",
        autospec=True,
    )
    mock_early_exit_cache.build.return_value.__enter__.return_value = early_exit_cache
    early_exit_cache.head.return_value = CacheStatus.MISS
    runner = MagicMock()
    runner.side_effect = Exception("some-error")

    with pytest.raises(Exception) as exception:
        extended_early_exit_run(
            integration=INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=False,
            cache_source=CACHE_SOURCE,
            short_ttl_seconds=SHORT_TTL_SECONDS,
            ttl_seconds=TTLS_SECONDS,
            logger=mock_logger,
            runner=runner,
            secret_reader=secret_reader,
            log_cached_log_output=True,
        )

    assert str(exception.value) == "some-error"
    runner.assert_called_once_with()
    early_exit_cache.set.assert_not_called()

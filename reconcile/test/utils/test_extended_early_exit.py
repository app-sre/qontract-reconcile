import logging
from logging import Logger
from typing import Any
from unittest.mock import MagicMock, call, create_autospec

import pytest
from pytest_mock import MockerFixture

from reconcile.utils.early_exit_cache import (
    CacheHeadResult,
    CacheKey,
    CacheStatus,
    CacheValue,
    EarlyExitCache,
)
from reconcile.utils.extended_early_exit import (
    ExtendedEarlyExitAppliedCountGauge,
    ExtendedEarlyExitCounter,
    ExtendedEarlyExitRunnerResult,
    extended_early_exit_run,
)
from reconcile.utils.secret_reader import SecretReaderBase

INTEGRATION = "some_integration"
EXPECTED_INTEGRATION = "some-integration"
INTEGRATION_VERSION = "some-integration-version"
SHORT_TTL_SECONDS = 0
TTLS_SECONDS = 100
RUNNER_PARAMS = {"some_param": "some-value"}
CACHE_SOURCE = {"k": "v"}
SHARD = "some-shard"
LATEST_CACHE_SOURCE_DIGEST = "some-digest"


@pytest.fixture
def logger() -> Logger:
    logger = logging.getLogger("some-logger")
    logger.setLevel(logging.INFO)
    return logger


@pytest.fixture
def mock_logger() -> Any:
    return create_autospec(Logger)


@pytest.fixture
def early_exit_cache() -> Any:
    return create_autospec(EarlyExitCache)


@pytest.mark.parametrize(
    "cache_status, dry_run, applied_count, expected_ttl",
    [
        (CacheStatus.MISS, True, 0, TTLS_SECONDS),
        (CacheStatus.MISS, False, 0, TTLS_SECONDS),
        (CacheStatus.MISS, False, 1, SHORT_TTL_SECONDS),
        (CacheStatus.EXPIRED, True, 0, TTLS_SECONDS),
        (CacheStatus.EXPIRED, False, 0, TTLS_SECONDS),
        (CacheStatus.EXPIRED, False, 1, SHORT_TTL_SECONDS),
    ],
)
def test_extended_early_exit_run_miss_or_expired(
    mocker: MockerFixture,
    logger: Logger,
    secret_reader: SecretReaderBase,
    early_exit_cache: Any,
    cache_status: CacheStatus,
    dry_run: bool,
    applied_count: int,
    expected_ttl: int,
) -> None:
    mock_early_exit_cache = mocker.patch(
        "reconcile.utils.extended_early_exit.EarlyExitCache",
        autospec=True,
    )
    mock_early_exit_cache.build.return_value.__enter__.return_value = early_exit_cache
    early_exit_cache.head.return_value = CacheHeadResult(
        status=cache_status,
        latest_cache_source_digest=LATEST_CACHE_SOURCE_DIGEST,
    )
    mock_inc_counter = mocker.patch("reconcile.utils.extended_early_exit.inc_counter")
    mock_set_gauge = mocker.patch("reconcile.utils.extended_early_exit.set_gauge")
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
        dry_run=dry_run,
        cache_source=CACHE_SOURCE,
        shard=SHARD,
        ttl_seconds=TTLS_SECONDS,
        logger=logger,
        runner=runner,
        runner_params=RUNNER_PARAMS,
        secret_reader=secret_reader,
    )

    expected_cache_key = CacheKey(
        integration=EXPECTED_INTEGRATION,
        integration_version=INTEGRATION_VERSION,
        dry_run=dry_run,
        cache_source=CACHE_SOURCE,
        shard=SHARD,
    )
    early_exit_cache.head.assert_called_once_with(expected_cache_key)
    runner.assert_called_once_with(**RUNNER_PARAMS)
    early_exit_cache.set.assert_called_once_with(
        expected_cache_key,
        CacheValue(
            payload=desired_state,
            log_output=expected_log_output,
            applied_count=applied_count,
        ),
        expected_ttl,
        LATEST_CACHE_SOURCE_DIGEST,
    )
    mock_inc_counter.assert_called_once_with(
        ExtendedEarlyExitCounter(
            integration=EXPECTED_INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=dry_run,
            cache_status=cache_status.value,
            shard=SHARD,
        ),
    )
    mock_set_gauge.assert_called_once_with(
        ExtendedEarlyExitAppliedCountGauge(
            integration=EXPECTED_INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=dry_run,
            cache_status=cache_status.value,
            shard=SHARD,
        ),
        applied_count,
    )


@pytest.mark.parametrize(
    "dry_run",
    [
        True,
        False,
    ],
)
def test_extended_early_exit_run_hit_when_not_log_cached_log_output(
    mocker: MockerFixture,
    mock_logger: Any,
    secret_reader: SecretReaderBase,
    early_exit_cache: Any,
    dry_run: bool,
) -> None:
    mock_early_exit_cache = mocker.patch(
        "reconcile.utils.extended_early_exit.EarlyExitCache",
        autospec=True,
    )
    mock_early_exit_cache.build.return_value.__enter__.return_value = early_exit_cache
    early_exit_cache.head.return_value = CacheHeadResult(
        status=CacheStatus.HIT,
        latest_cache_source_digest=LATEST_CACHE_SOURCE_DIGEST,
    )
    mock_inc_counter = mocker.patch("reconcile.utils.extended_early_exit.inc_counter")
    mock_set_gauge = mocker.patch("reconcile.utils.extended_early_exit.set_gauge")
    runner = MagicMock()

    extended_early_exit_run(
        integration=INTEGRATION,
        integration_version=INTEGRATION_VERSION,
        dry_run=dry_run,
        cache_source=CACHE_SOURCE,
        shard=SHARD,
        ttl_seconds=TTLS_SECONDS,
        logger=mock_logger,
        runner=runner,
        runner_params=RUNNER_PARAMS,
        secret_reader=secret_reader,
        log_cached_log_output=False,
    )

    expected_cache_key = CacheKey(
        integration=EXPECTED_INTEGRATION,
        integration_version=INTEGRATION_VERSION,
        dry_run=dry_run,
        cache_source=CACHE_SOURCE,
        shard=SHARD,
    )
    early_exit_cache.head.assert_called_once_with(expected_cache_key)
    runner.assert_not_called()
    early_exit_cache.get.assert_not_called()
    mock_logger.info.assert_not_called()
    early_exit_cache.set.assert_not_called()

    mock_inc_counter.assert_called_once_with(
        ExtendedEarlyExitCounter(
            integration=EXPECTED_INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=dry_run,
            cache_status=CacheStatus.HIT.value,
            shard=SHARD,
        ),
    )
    mock_set_gauge.assert_called_once_with(
        ExtendedEarlyExitAppliedCountGauge(
            integration=EXPECTED_INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=dry_run,
            cache_status=CacheStatus.HIT.value,
            shard=SHARD,
        ),
        0,
    )


@pytest.mark.parametrize(
    "dry_run",
    [
        True,
        False,
    ],
)
def test_extended_early_exit_run_hit_when_log_cached_log_output(
    mocker: MockerFixture,
    mock_logger: Any,
    secret_reader: SecretReaderBase,
    early_exit_cache: Any,
    dry_run: bool,
) -> None:
    mock_early_exit_cache = mocker.patch(
        "reconcile.utils.extended_early_exit.EarlyExitCache",
        autospec=True,
    )
    mock_early_exit_cache.build.return_value.__enter__.return_value = early_exit_cache
    early_exit_cache.head.return_value = CacheHeadResult(
        status=CacheStatus.HIT,
        latest_cache_source_digest=LATEST_CACHE_SOURCE_DIGEST,
    )
    early_exit_cache.get.return_value = CacheValue(
        payload=CACHE_SOURCE,
        log_output="log-output1\nlog-output2\n",
        applied_count=1,
    )
    mock_inc_counter = mocker.patch("reconcile.utils.extended_early_exit.inc_counter")
    mock_set_gauge = mocker.patch("reconcile.utils.extended_early_exit.set_gauge")
    runner = MagicMock()

    extended_early_exit_run(
        integration=INTEGRATION,
        integration_version=INTEGRATION_VERSION,
        dry_run=dry_run,
        cache_source=CACHE_SOURCE,
        shard=SHARD,
        ttl_seconds=TTLS_SECONDS,
        logger=mock_logger,
        runner=runner,
        runner_params=RUNNER_PARAMS,
        secret_reader=secret_reader,
        log_cached_log_output=True,
    )

    expected_cache_key = CacheKey(
        integration=EXPECTED_INTEGRATION,
        integration_version=INTEGRATION_VERSION,
        dry_run=dry_run,
        cache_source=CACHE_SOURCE,
        shard=SHARD,
    )
    expected_delete_args = expected_cache_key.build_cli_delete_args()
    mock_logger.info.assert_has_calls([
        call(
            "logging cached log output, to delete cache, use "
            "qontract-cli --config config.toml early-exit-cache delete %s",
            expected_delete_args,
        ),
        call("log-output1"),
        call("log-output2"),
    ])
    early_exit_cache.head.assert_called_once_with(expected_cache_key)
    early_exit_cache.get.assert_called_once_with(expected_cache_key)
    runner.assert_not_called()
    early_exit_cache.set.assert_not_called()

    mock_inc_counter.assert_called_once_with(
        ExtendedEarlyExitCounter(
            integration=EXPECTED_INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=dry_run,
            cache_status=CacheStatus.HIT.value,
            shard=SHARD,
        ),
    )
    mock_set_gauge.assert_called_once_with(
        ExtendedEarlyExitAppliedCountGauge(
            integration=EXPECTED_INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=dry_run,
            cache_status=CacheStatus.HIT.value,
            shard=SHARD,
        ),
        0,
    )


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
    early_exit_cache.head.return_value = CacheHeadResult(
        status=CacheStatus.MISS,
        latest_cache_source_digest=LATEST_CACHE_SOURCE_DIGEST,
    )
    mock_inc_counter = mocker.patch("reconcile.utils.extended_early_exit.inc_counter")
    mock_set_gauge = mocker.patch("reconcile.utils.extended_early_exit.set_gauge")
    runner = MagicMock()
    runner.side_effect = Exception("some-error")

    with pytest.raises(Exception) as exception:
        extended_early_exit_run(
            integration=INTEGRATION,
            integration_version=INTEGRATION_VERSION,
            dry_run=False,
            cache_source=CACHE_SOURCE,
            shard=SHARD,
            ttl_seconds=TTLS_SECONDS,
            logger=mock_logger,
            runner=runner,
            secret_reader=secret_reader,
            log_cached_log_output=True,
        )

    assert str(exception.value) == "some-error"
    runner.assert_called_once_with()
    early_exit_cache.set.assert_not_called()
    mock_inc_counter.assert_not_called()
    mock_set_gauge.assert_not_called()

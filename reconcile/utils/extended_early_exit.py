import logging
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from io import StringIO
from logging import Logger

from pydantic import BaseModel

from reconcile.utils.early_exit_cache import (
    CacheKey,
    CacheStatus,
    CacheValue,
    EarlyExitCache,
)
from reconcile.utils.metrics import (
    CounterMetric,
    GaugeMetric,
    inc_counter,
    normalize_integration_name,
    set_gauge,
)
from reconcile.utils.secret_reader import SecretReaderBase


class ExtendedEarlyExitRunnerResult(BaseModel):
    payload: object
    applied_count: int


class ExtendedEarlyExitBaseMetric(BaseModel):
    integration: str
    integration_version: str
    dry_run: bool
    cache_status: str
    shard: str


class ExtendedEarlyExitCounter(ExtendedEarlyExitBaseMetric, CounterMetric):
    @classmethod
    def name(cls) -> str:
        return "qontract_reconcile_extended_early_exit"


class ExtendedEarlyExitAppliedCountGauge(ExtendedEarlyExitBaseMetric, GaugeMetric):
    @classmethod
    def name(cls) -> str:
        return "qontract_reconcile_extended_early_exit_applied_count"


def _publish_metrics(
    cache_key: CacheKey,
    cache_status: CacheStatus,
    applied_count: int,
) -> None:
    inc_counter(
        ExtendedEarlyExitCounter(
            integration=cache_key.integration,
            integration_version=cache_key.integration_version,
            dry_run=cache_key.dry_run,
            cache_status=cache_status.value,
            shard=cache_key.shard,
        ),
    )
    set_gauge(
        ExtendedEarlyExitAppliedCountGauge(
            integration=cache_key.integration,
            integration_version=cache_key.integration_version,
            dry_run=cache_key.dry_run,
            cache_status=cache_status.value,
            shard=cache_key.shard,
        ),
        applied_count,
    )


def _ttl_seconds(
    applied_count: int,
    ttl_seconds: int,
) -> int:
    """
    Pick the ttl based on the applied count.
    If the applied count is greater than 0, then we want to set ttl to 0 so that the next run will not hit the cache,
    this will allow us to easy debug reconcile loops, as we will be able to see the logs of the next run,
    and check cached value for more details.

    :param applied_count: The number of resources that were applied
    :param ttl_seconds: A ttl in seconds
    :return: The ttl in seconds
    """
    return 0 if applied_count > 0 else ttl_seconds


@contextmanager
def log_stream_handler(
    logger: Logger,
) -> Generator[StringIO, None, None]:
    """
    Add a stream handler to the logger, and return the stream generator, automatically remove the handler when done.

    :param logger: A logger
    :return: A stream generator
    """
    with StringIO() as log_stream:
        log_handler = logging.StreamHandler(log_stream)
        logger.addHandler(log_handler)
        try:
            yield log_stream
        finally:
            logger.removeHandler(log_handler)


def _log_cached_log_output(
    cache: EarlyExitCache,
    key: CacheKey,
    logger: Logger,
) -> None:
    log_output = cache.get(key).log_output
    logger.info(
        "logging cached log output, to delete cache, use cli command "
        "`qontract-cli --config config.toml early-exit-cache delete $ARGS` or "
        "comment on merge request `/cache delete $ARGS`, "
        "replace `$ARGS` with `%s`",
        key.build_cli_delete_args(),
    )
    for line in log_output.splitlines():
        logger.info(line)


def extended_early_exit_run(
    integration: str,
    integration_version: str,
    dry_run: bool,
    cache_source: object,
    shard: str,
    ttl_seconds: int,
    logger: Logger,
    runner: Callable[..., ExtendedEarlyExitRunnerResult],
    runner_params: Mapping | None = None,
    secret_reader: SecretReaderBase | None = None,
    log_cached_log_output: bool = False,
) -> None:
    """
    Run the runner based on the cache status. Early exit when cache hit.
    Runner log output will be extracted and stored in cache value,
    and will be logged when hit if log_cached_log_output is True,
    this is mainly used to show all log output from different integrations in one place (CI).
    When runner returns no applies (applied_count is 0), the ttl will be set to ttl_seconds,
    otherwise it will be set to 0.

    :param integration: The integration name
    :param integration_version: The integration version
    :param dry_run: True if the run is in dry run mode, False otherwise
    :param cache_source: The cache source, usually the static desired state
    :param shard: The shard name
    :param ttl_seconds: A ttl in seconds
    :param logger: A Logger
    :param runner: A runner can return ExtendedEarlyExitRunnerResult when called
    :param runner_params: Runner params, will be spread into kwargs when calling runner
    :param secret_reader: A secret reader
    :param log_cached_log_output: Whether to log the cached log output when there is a cache hit
    :return: None
    """
    with EarlyExitCache.build(secret_reader) as cache:
        key = CacheKey(
            integration=normalize_integration_name(integration),
            integration_version=integration_version,
            dry_run=dry_run,
            cache_source=cache_source,
            shard=shard,
        )
        cache_result = cache.head(key)
        logger.debug(
            "Early exit cache head result for key=%s: status: %s, latest cache source digest: %s",
            key,
            cache_result.status,
            cache_result.latest_cache_source_digest,
        )

        if cache_result.status == CacheStatus.HIT:
            if log_cached_log_output:
                _log_cached_log_output(cache, key, logger)
            _publish_metrics(
                cache_key=key,
                cache_status=cache_result.status,
                applied_count=0,
            )
            return

        with log_stream_handler(logger) as log_stream:
            result = runner(**(runner_params or {}))
            log_output = log_stream.getvalue()

        value = CacheValue(
            payload=result.payload,
            log_output=log_output,
            applied_count=result.applied_count,
        )
        ttl = _ttl_seconds(result.applied_count, ttl_seconds)
        logger.debug(
            "Set early exit cache for key=%s with ttl=%d and latest_cache_source_digest=%s",
            key,
            ttl,
            cache_result.latest_cache_source_digest,
        )
        cache.set(key, value, ttl, cache_result.latest_cache_source_digest)
        _publish_metrics(
            cache_key=key,
            cache_status=cache_result.status,
            applied_count=result.applied_count,
        )

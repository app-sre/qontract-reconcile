import logging
from collections.abc import Callable, Generator
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
from reconcile.utils.secret_reader import SecretReaderBase


class ExtendedEarlyExitRunnerResult(BaseModel):
    desired_state: object
    applied_count: int


def _log_cached_log_output(
    cache: EarlyExitCache,
    key: CacheKey,
    logger: Logger,
) -> None:
    value = cache.get(key)
    logger.info(value.log_output)


def _no_dry_run_cache_hit(
    cache: EarlyExitCache,
    integration: str,
    integration_version: str,
    cache_desired_state: object,
    logger: Logger,
    log_cached_log_output: bool,
) -> bool:
    """
    Check if the cache has a hit for the no-dry-run key.
    This is used in dry run mode mostly run in CI,
    if the cache has a hit for the no-dry-run key,
    then we want to early exit.

    :param cache: The early exit cache
    :param integration: The integration name
    :param integration_version: The integration version
    :param cache_desired_state: The desired state
    :param logger: A logger
    :param log_cached_log_output: True if we want to log the cached log output, False otherwise
    :return: True if the cache has a hit for the no-dry-run key, False otherwise
    """
    key = CacheKey(
        integration=integration,
        integration_version=integration_version,
        dry_run=False,
        cache_desired_state=cache_desired_state,
    )
    hit = cache.head(key) == CacheStatus.HIT
    if hit and log_cached_log_output:
        _log_cached_log_output(cache, key, logger)
    return hit


def _ttl_seconds(
    applied_count: int,
    short_ttl_seconds: int,
    ttl_seconds: int,
) -> int:
    """
    Pick the ttl based on the applied count.
    If the applied count is greater than 0, then we want to set a short ttl so that the next run will not hit the cache,
    this will allow us to easy debug reconcile loops, as we will be able to see the logs of the next run,
    and check cached value for more details.

    :param applied_count: The number of resources that were applied
    :param short_ttl_seconds: A short ttl in seconds
    :param ttl_seconds: A ttl in seconds
    :return: The ttl in seconds
    """
    return short_ttl_seconds if applied_count > 0 else ttl_seconds


@contextmanager
def log_stream_handler(
    logger: Logger,
) -> Generator[StringIO, None, None]:
    """
    Add a stream handler to the logger, and return the stream generator, automatically remove the handler when done.

    :param logger: A logger
    :return: A stream generator
    """
    log_stream = StringIO()
    log_handler = logging.StreamHandler(log_stream)
    logger.addHandler(log_handler)
    try:
        yield log_stream
    finally:
        logger.removeHandler(log_handler)


def extended_early_exit_run(
    integration: str,
    integration_version: str,
    dry_run: bool,
    cache_desired_state: object,
    short_ttl_seconds: int,
    ttl_seconds: int,
    logger: Logger,
    runner: Callable[..., ExtendedEarlyExitRunnerResult],
    runner_params: BaseModel | None = None,
    secret_reader: SecretReaderBase | None = None,
    log_cached_log_output: bool = False,
) -> None:
    """
    Run the runner based on the cache status. Early exit when cache hit.
    If not hit in dry-run mode, will check no-dry-run cache additionally.
    Runner log output will be extracted and stored in cache value,
    and will be logged when hit if log_cached_log_output is True,
    this is mainly used to show all log output from different integrations in one place (CI).
    When runner returns no applies (applied_count is 0), the ttl will be set to ttl_seconds,
    otherwise it will be set to short_ttl_seconds.

    :param integration: The integration name
    :param integration_version: The integration version
    :param dry_run: True if the run is in dry run mode, False otherwise
    :param cache_desired_state: The desired state
    :param short_ttl_seconds: A short ttl in seconds
    :param ttl_seconds: A ttl in seconds
    :param logger: A Logger
    :param runner: A runner can return ExtendedEarlyExitRunnerResult when called
    :param runner_params: Runner params
    :param secret_reader: A secret reader
    :param log_cached_log_output: Whether to log the cached log output when there is a cache hit
    :return: None
    """
    with EarlyExitCache.build(secret_reader) as cache:
        key = CacheKey(
            integration=integration,
            integration_version=integration_version,
            dry_run=dry_run,
            cache_desired_state=cache_desired_state,
        )
        cache_status = cache.head(key)

        if cache_status == CacheStatus.HIT:
            if log_cached_log_output:
                _log_cached_log_output(cache, key, logger)
            return

        if dry_run and _no_dry_run_cache_hit(
            cache,
            integration,
            integration_version,
            cache_desired_state,
            logger,
            log_cached_log_output,
        ):
            return

        with log_stream_handler(logger) as log_stream:
            result = runner(**runner_params.dict())
            log_output = log_stream.getvalue()

        value = CacheValue(
            desired_state=result.desired_state,
            log_output=log_output,
            applied_count=result.applied_count,
        )
        ttl = _ttl_seconds(result.applied_count, short_ttl_seconds, ttl_seconds)
        cache.set(key, value, ttl)

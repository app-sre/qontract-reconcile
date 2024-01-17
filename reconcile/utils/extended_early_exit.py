from collections.abc import Callable
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


def _no_dry_run_cache_hit(
    cache: EarlyExitCache,
    integration: str,
    integration_version: str,
    cache_desired_state: object,
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
    :return: True if the cache has a hit for the no-dry-run key, False otherwise
    """
    key = CacheKey(
        integration=integration,
        integration_version=integration_version,
        dry_run=False,
        cache_desired_state=cache_desired_state,
    )
    return cache.head(key) == CacheStatus.HIT


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
) -> None:
    """
    Run the runner based on the cache status.

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
            return

        if dry_run and _no_dry_run_cache_hit(
            cache,
            integration,
            integration_version,
            cache_desired_state,
        ):
            return

        result = runner(**runner_params.dict())
        value = CacheValue(
            desired_state=result.desired_state,
            log_output="",
            applied_count=result.applied_count,
        )
        ttl = _ttl_seconds(result.applied_count, short_ttl_seconds, ttl_seconds)
        cache.set(key, value, ttl)

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import Enum
from functools import cached_property
from typing import Any, Self

from deepdiff import DeepHash
from pydantic import BaseModel

from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.state import State, init_state

STATE_INTEGRATION = "early-exit-cache"
EXPIRE_AT_METADATA_KEY = "expire-at"
CACHE_SOURCE_DIGEST_METADATA_KEY = "cache-source-digest"


class CacheKey(BaseModel):
    integration: str
    integration_version: str
    dry_run: bool
    cache_source: object

    def __str__(self) -> str:
        return "/".join([
            self.integration,
            self.integration_version,
            "dry-run" if self.dry_run else "no-dry-run",
            self.cache_source_digest if self.dry_run else "latest",
        ])

    @cached_property
    def cache_source_digest(self) -> str:
        return DeepHash(self.cache_source)[self.cache_source]

    def no_dry_run_path(self) -> str:
        return "/".join([
            self.integration,
            self.integration_version,
            "no-dry-run",
            "latest",
        ])

    class Config:
        frozen = True
        keep_untouched = (cached_property,)


class CacheValue(BaseModel):
    payload: object
    log_output: str
    applied_count: int


class CacheStatus(Enum):
    MISS = "MISS"
    HIT = "HIT"
    EXPIRED = "EXPIRED"  # TTL expired
    STALE = "STALE"  # latest cache source digest is different, which means there are new applied changes


class EarlyExitCache:
    def __init__(self, state: State):
        self.state = state

    @classmethod
    def build(
        cls,
        secret_reader: SecretReaderBase | None = None,
    ) -> Self:
        state = init_state(STATE_INTEGRATION, secret_reader)
        return cls(state)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        self.state.cleanup()

    def get(self, key: CacheKey) -> CacheValue:
        value = self.state.get(str(key))
        return CacheValue.parse_obj(value)

    def set(self, key: CacheKey, value: CacheValue, ttl_seconds: int) -> None:
        expire_at = datetime.now(tz=UTC) + timedelta(seconds=ttl_seconds)
        metadata = {
            EXPIRE_AT_METADATA_KEY: str(int(expire_at.timestamp())),
            CACHE_SOURCE_DIGEST_METADATA_KEY: key.cache_source_digest,
        }
        self.state.add(
            str(key),
            value.dict(),
            metadata=metadata,
            force=True,
        )

    @staticmethod
    def _is_latest(
        key: CacheKey,
        metadata: Mapping[str, str],
    ) -> bool:
        latest_cache_source_digest = metadata.get(CACHE_SOURCE_DIGEST_METADATA_KEY)
        return key.cache_source_digest == latest_cache_source_digest

    def _is_stale(self, key: CacheKey) -> bool:
        """
        Check if the cache is stale, a dry run cache is stale if the matching no dry run cache is no longer the latest.
        When there is no matching no dry run cache, it is considered as not stale.

        :param key: CacheKey
        :return: whether the cache is stale
        """
        if not key.dry_run:
            return False

        exists, metadata = self.state.head(key.no_dry_run_path())
        if not exists:
            return False

        return not self._is_latest(key, metadata)

    def head(self, key: CacheKey) -> CacheStatus:
        """
        Get the cache status for the given key.
        Additionally, for dry run key, it will use matching no dry run key to check stale.

        :param key: CacheKey
        :return: CacheStatus
        """
        exists, metadata = self.state.head(str(key))
        if not exists:
            return CacheStatus.MISS

        if not key.dry_run and not self._is_latest(key, metadata):
            return CacheStatus.MISS

        expire_at = datetime.fromtimestamp(
            int(metadata[EXPIRE_AT_METADATA_KEY]),
            tz=UTC,
        )
        now = datetime.now(UTC)
        if now >= expire_at:
            return CacheStatus.EXPIRED

        if self._is_stale(key):
            return CacheStatus.STALE

        return CacheStatus.HIT

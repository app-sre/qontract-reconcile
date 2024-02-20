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
LATEST_CACHE_SOURCE_DIGEST_METADATA_KEY = "latest-cache-source-digest"


class CacheKeyWithDigest(BaseModel):
    integration: str
    integration_version: str
    dry_run: bool
    cache_source_digest: str
    shard: str

    def __str__(self) -> str:
        return self.dry_run_path() if self.dry_run else self.no_dry_run_path()

    def dry_run_path(self) -> str:
        """
        /<integration>/<integration_version>/dry-run(/<shard>)/<cache_source_digest>
        """
        return "/".join(
            [
                self.integration,
                self.integration_version,
                "dry-run",
            ]
            + ([self.shard] if self.shard else [])
            + [
                self.cache_source_digest,
            ]
        )

    def no_dry_run_path(self) -> str:
        """
        /<integration>/<integration_version>/no-dry-run(/<shard>)/latest
        """
        return "/".join(
            [
                self.integration,
                self.integration_version,
                "no-dry-run",
            ]
            + ([self.shard] if self.shard else [])
            + [
                "latest",
            ]
        )

    def build_cli_delete_args(self) -> str:
        args = [
            f"--integration {self.integration}",
            f"--integration-version {self.integration_version}",
            "--dry-run" if self.dry_run else "--no-dry-run",
            f"--cache-source-digest {self.cache_source_digest}",
        ]
        if self.shard:
            args.append(f"--shard {self.shard}")
        return " ".join(args)

    class Config:
        frozen = True


class CacheKey(BaseModel):
    integration: str
    integration_version: str
    dry_run: bool
    cache_source: object
    shard: str

    def __str__(self) -> str:
        return str(self.cache_key_with_digest)

    @cached_property
    def cache_source_digest(self) -> str:
        """
        Calculate a consistent hash of the cache source, use @cached_property to avoid recalculating

        :return: hash of the cache source
        """
        return DeepHash(self.cache_source)[self.cache_source]

    @cached_property
    def cache_key_with_digest(self) -> CacheKeyWithDigest:
        return CacheKeyWithDigest(
            integration=self.integration,
            integration_version=self.integration_version,
            dry_run=self.dry_run,
            cache_source_digest=self.cache_source_digest,
            shard=self.shard,
        )

    def dry_run_path(self) -> str:
        """
        /<integration>/<integration_version>/dry-run(/<shard>)/<cache_source_digest>
        """
        return self.cache_key_with_digest.dry_run_path()

    def no_dry_run_path(self) -> str:
        """
        /<integration>/<integration_version>/no-dry-run(/<shard>)/latest
        """
        return self.cache_key_with_digest.no_dry_run_path()

    def build_cli_delete_args(self) -> str:
        """
        Generate delete command arguments.
        :return: delete command arguments
        """
        return self.cache_key_with_digest.build_cli_delete_args()

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


class CacheHeadResult(BaseModel):
    status: CacheStatus
    latest_cache_source_digest: str


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

    def set(
        self,
        key: CacheKey,
        value: CacheValue,
        ttl_seconds: int,
        latest_cache_source_digest: str,
    ) -> None:
        """
        Set the cache value for the given key.

        :param key: cache key
        :param value: cache value
        :param ttl_seconds: time to live in seconds
        :param latest_cache_source_digest: latest cache source digest, used to check stale for dry run cache
        :return: None
        """
        expire_at = datetime.now(tz=UTC) + timedelta(seconds=ttl_seconds)
        metadata = {
            EXPIRE_AT_METADATA_KEY: str(int(expire_at.timestamp())),
            CACHE_SOURCE_DIGEST_METADATA_KEY: key.cache_source_digest,
            LATEST_CACHE_SOURCE_DIGEST_METADATA_KEY: latest_cache_source_digest,
        }
        self.state.add(
            str(key),
            value.dict(),
            metadata=metadata,
            force=True,
        )

    def head(self, key: CacheKey) -> CacheHeadResult:
        """
        Get the cache status and latest cache source digest for the given key.
        Additionally, for dry run key, it will use latest cache source digest to check stale.

        :param key: CacheKey
        :return: CacheHeadResult
        """
        return self._head_dry_run(key) if key.dry_run else self._head_no_dry_run(key)

    def delete(self, key: CacheKeyWithDigest) -> None:
        """
        Delete the cache value for the given key.

        :param key: CacheKey
        :return: None
        """
        self.state.rm(str(key))

    @staticmethod
    def _is_stale(
        metadata: Mapping[str, str],
        latest_cache_source_digest: str,
    ) -> bool:
        cached_latest_cache_source_digest = (
            metadata.get(LATEST_CACHE_SOURCE_DIGEST_METADATA_KEY) or ""
        )
        return cached_latest_cache_source_digest != latest_cache_source_digest

    @staticmethod
    def _is_expired(metadata: Mapping[str, str]) -> bool:
        expire_at = datetime.fromtimestamp(
            int(metadata[EXPIRE_AT_METADATA_KEY]),
            tz=UTC,
        )
        now = datetime.now(UTC)
        return now >= expire_at

    def _head_dry_run_status(
        self,
        key: CacheKey,
        latest_cache_source_digest: str,
    ) -> CacheStatus:
        exists, metadata = self.state.head(key.dry_run_path())
        if not exists:
            return CacheStatus.MISS
        if self._is_expired(metadata):
            return CacheStatus.EXPIRED
        if self._is_stale(metadata, latest_cache_source_digest):
            return CacheStatus.STALE
        return CacheStatus.HIT

    def _head_dry_run(self, key: CacheKey) -> CacheHeadResult:
        _, latest_metadata = self.state.head(key.no_dry_run_path())
        latest_cache_source_digest = (
            latest_metadata.get(CACHE_SOURCE_DIGEST_METADATA_KEY) or ""
        )
        return CacheHeadResult(
            status=self._head_dry_run_status(key, latest_cache_source_digest),
            latest_cache_source_digest=latest_cache_source_digest,
        )

    def _head_no_dry_run_status(
        self,
        key: CacheKey,
        exists: bool,
        metadata: Mapping[str, str],
        latest_cache_source_digest: str,
    ) -> CacheStatus:
        if not exists or key.cache_source_digest != latest_cache_source_digest:
            return CacheStatus.MISS
        if self._is_expired(metadata):
            return CacheStatus.EXPIRED
        return CacheStatus.HIT

    def _head_no_dry_run(self, key: CacheKey) -> CacheHeadResult:
        exists, metadata = self.state.head(key.no_dry_run_path())
        latest_cache_source_digest = (
            metadata.get(CACHE_SOURCE_DIGEST_METADATA_KEY) or ""
        )
        return CacheHeadResult(
            status=self._head_no_dry_run_status(
                key,
                exists,
                metadata,
                latest_cache_source_digest,
            ),
            latest_cache_source_digest=latest_cache_source_digest,
        )

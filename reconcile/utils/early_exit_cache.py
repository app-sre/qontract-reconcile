from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Self

from deepdiff import DeepHash
from pydantic import BaseModel

from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.state import State, init_state

STATE_INTEGRATION = "early-exit-cache"
EXPIRE_AT_METADATA_KEY = "expire-at"


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
            DeepHash(self.cache_source)[self.cache_source],
        ])


class CacheValue(BaseModel):
    payload: object
    log_output: str
    applied_count: int


class CacheStatus(Enum):
    MISS = "MISS"
    HIT = "HIT"
    EXPIRED = "EXPIRED"


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
        metadata = {EXPIRE_AT_METADATA_KEY: str(int(expire_at.timestamp()))}
        self.state.add(
            str(key),
            value.dict(),
            metadata=metadata,
            force=True,
        )

    def head(self, key: CacheKey) -> CacheStatus:
        exists, metadata = self.state.head(str(key))
        if not exists:
            return CacheStatus.MISS

        expire_at = datetime.fromtimestamp(
            int(metadata[EXPIRE_AT_METADATA_KEY]),
            tz=UTC,
        )
        now = datetime.now(UTC)
        return CacheStatus.HIT if now < expire_at else CacheStatus.EXPIRED

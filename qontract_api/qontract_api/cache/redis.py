"""Redis/Valkey cache backend implementation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from qontract_api.cache.base import CacheBackend

if TYPE_CHECKING:
    from valkey.asyncio import Valkey


class RedisCacheBackend(CacheBackend):
    """Redis/Valkey cache backend."""

    def __init__(self, redis_client: Valkey) -> None:
        """Initialize Redis/Valkey cache backend."""
        self.client = redis_client

    async def get(self, key: str) -> Any | None:
        """Get value from cache."""
        value = await self.client.get(key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set value in cache with optional TTL in seconds."""
        serialized = json.dumps(value) if not isinstance(value, str) else value
        if ttl:
            await self.client.setex(key, ttl, serialized)
        else:
            await self.client.set(key, serialized)

    async def delete(self, key: str) -> None:
        """Delete key from cache."""
        await self.client.delete(key)

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        return bool(await self.client.exists(key))

    async def close(self) -> None:
        """Close Redis connection."""
        await self.client.aclose()

    async def ping(self) -> bool:
        """Check if Redis/Valkey is reachable."""
        try:
            await self.client.ping()
            return True
        except OSError:
            # Network/connection errors
            return False

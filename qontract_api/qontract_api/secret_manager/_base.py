from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from qontract_utils.secret_reader import Secret, SecretBackend

    from qontract_api.cache import CacheBackend


class SecretManager:
    def __init__(
        self, cache: CacheBackend, secret_backends: Iterable[SecretBackend]
    ) -> None:
        self.cache = cache
        self.secret_backends = {backend.url: backend for backend in secret_backends}

    @staticmethod
    def _cache_key(secret: Secret) -> str:
        return f"secret:{secret.url}:{secret.path}:{secret.field or ''}:{secret.version or '1'}"

    def read(self, secret: Secret) -> str:
        cache_key = self._cache_key(secret)
        cached_value = self.cache.get(cache_key)
        if cached_value is not None:
            return cached_value

        with self.cache.lock(cache_key):
            # Re-check cache after acquiring lock
            if cached_value := self.cache.get(cache_key):
                return cached_value

            value = self.secret_backends[secret.url].read(secret)
            # TODO : TTL from config
            self.cache.set(cache_key, value, 5)
        return value

    def read_all(self, secret: Secret) -> dict[str, Any]:
        """Read all fields from a secret path."""
        return self.secret_backends[secret.url].read_all(secret)

    def write(
        self, secret: Secret, data: dict[str, str], *, force: bool = False
    ) -> None:
        """Write all fields to a secret path, invalidating the cached value.

        Write-through-then-invalidate: the cache entry is deleted (not
        repopulated) after a successful backend write, so a failed backend
        call never leaves a stale cache entry. The cache key is locked for
        the duration so a concurrent read() cannot repopulate the cache with
        pre-write data in the gap between the write and the invalidation.
        """
        cache_key = self._cache_key(secret)
        with self.cache.lock(cache_key):
            self.secret_backends[secret.url].write(secret, data, force=force)
            self.cache.delete(cache_key)

    def delete(self, secret: Secret) -> None:
        """Delete a secret path, invalidating the cached value."""
        cache_key = self._cache_key(secret)
        with self.cache.lock(cache_key):
            self.secret_backends[secret.url].delete(secret)
            self.cache.delete(cache_key)

    def list(self, secret: Secret) -> list[str]:
        """List secret keys directly under a path (uncached, matches read_all)."""
        return self.secret_backends[secret.url].list(secret)

    def close(self) -> None:
        for secret_backend in self.secret_backends.values():
            secret_backend.close()

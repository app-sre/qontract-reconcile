from qontract_utils.secret_reader import Secret, SecretBackend

from qontract_api.cache import CacheBackend


class SecretManager:
    def __init__(self, cache: CacheBackend, secret_backend: SecretBackend) -> None:
        self.cache = cache
        self.secret_backend = secret_backend

    def read(self, secret: Secret) -> str:
        cache_key = f"secret:{secret.path}:{secret.version or '1'}"
        cached_value = self.cache.get(cache_key)
        if cached_value is not None:
            return cached_value

        with self.cache.lock(cache_key):
            # Re-check cache after acquiring lock
            if cached_value := self.cache.get(cache_key):
                return cached_value

            value = self.secret_backend.read(secret)
            # TODO : TTL from config
            self.cache.set(cache_key, value, 5)
        return value

    def close(self) -> None:
        self.secret_backend.close()

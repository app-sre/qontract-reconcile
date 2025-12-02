"""Secret backend abstraction for qontract-api.

Provides pluggable secret backends (Vault, AWS KMS, Google Secret Manager)
with a consistent interface for reading secrets.

Following the same pattern as CacheBackend - singleton instances with
thread-safe factory methods.
"""

from qontract_utils.secret_reader.base import (
    SecretAccessForbiddenError,
    SecretBackend,
    SecretBackendError,
    SecretNotFoundError,
)

__all__ = [
    "SecretAccessForbiddenError",
    "SecretBackend",
    "SecretBackendError",
    "SecretNotFoundError",
]

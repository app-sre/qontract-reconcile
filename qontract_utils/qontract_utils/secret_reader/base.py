"""Abstract base class for secret backends.

Provides a pluggable interface for different secret management systems
(HashiCorp Vault, AWS KMS, Google Secret Manager, etc.).

Similar to CacheBackend pattern:
- Singleton per backend type
- Thread-safe factory method
- Abstract interface for concrete implementations
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

if TYPE_CHECKING:
    from qontract_utils.hooks import Hooks
    from qontract_utils.secret_reader.providers.vault import VaultSecretBackendSettings


class SecretNotFoundError(Exception):
    """Secret not found at specified path."""


class SecretAccessForbiddenError(Exception):
    """Access denied to secret (permissions issue)."""


class SecretBackendError(Exception):
    """Generic secret backend error (connection, authentication, etc.)."""


class Secret(Protocol):
    @property
    def path(self) -> str: ...
    @property
    def field(self) -> str | None: ...
    @property
    def version(self) -> int | None: ...

    @property
    def url(self) -> str: ...


class SecretBackend(ABC):
    """Abstract base class for secret backends.

    Provides thread-safe singleton instances per backend URL. Multiple
    instances of the same backend type (e.g., two Vault servers) are
    fully supported — each URL gets its own singleton.

    Singleton Pattern (double-checked locking):
    - get_instance() provides thread-safe singleton per backend URL
    - reset_singleton() for testing cleanup

    Required Instance Variables:
    - url (str): Backend server URL (enforced via abstract property)

    Example:
        # Initialize Vault backend
        backend = SecretBackend.get_instance(
            backend_type="vault",
            server="https://vault.example.com",
            role_id="my-role",
            secret_id="my-secret",
        )

        # Read secret
        token = backend.read("slack/workspace-1/token")

        # Read specific field from structured secret
        access_key = backend.read("aws/account1/creds", field="access_key_id")

        # Read specific version (Vault KV v2)
        old_token = backend.read("slack/ws1/token", version=5)

        # Read all fields
        creds = backend.read_all("aws/account1/creds")
    """

    # Singleton instances keyed by backend URL
    _instances: ClassVar[dict[str, SecretBackend]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @property
    @abstractmethod
    def url(self) -> str:
        """Backend server URL (e.g., 'https://vault.example.com').

        Concrete implementations must provide this property.
        """

    @classmethod
    def get_instance(
        cls,
        backend_type: str,
        backend_settings: VaultSecretBackendSettings,
        hooks: Hooks | None = None,
    ) -> SecretBackend:
        """Get singleton secret backend instance (thread-safe factory).

        Uses double-checked locking for thread safety. Each backend URL
        gets its own singleton — multiple instances of the same backend
        type (e.g., two Vault servers) are supported.

        Args:
            backend_type: Backend type ("vault", "aws_kms", "google")
            backend_settings: Backend-specific settings (contains the server URL)
            hooks: Optional hooks for metrics/logging

        Returns:
            Singleton SecretBackend instance for the specified backend URL

        Raises:
            ValueError: If backend_type is not supported
        """
        instance_key = backend_settings.server

        # Fast path: Check if instance exists (no lock needed)
        if instance_key in cls._instances:
            return cls._instances[instance_key]

        # Slow path: Create new instance (thread-safe)
        with cls._lock:
            # Double-check after acquiring lock (another thread may have created it)
            if instance_key not in cls._instances:
                match backend_type:
                    case "vault":
                        from qontract_utils.secret_reader.providers.vault import (  # noqa: PLC0415
                            VaultSecretBackend,
                            VaultSecretBackendSettings,
                        )

                        assert isinstance(
                            backend_settings, VaultSecretBackendSettings
                        )  # for mypy
                        cls._instances[instance_key] = VaultSecretBackend(
                            backend_settings, hooks=hooks
                        )
                    case _:
                        msg = f"Unsupported secret backend: {backend_type}"
                        raise ValueError(msg)

        return cls._instances[instance_key]

    @classmethod
    def reset_singleton(cls, url: str | None = None) -> None:
        """Reset singleton instance(s) - primarily for testing.

        Args:
            url: Specific backend URL to reset (None = reset all)
        """
        with cls._lock:
            if url:
                if url in cls._instances:
                    cls._instances[url].close()
                    del cls._instances[url]
            else:
                for instance in cls._instances.values():
                    instance.close()
                cls._instances.clear()

    @abstractmethod
    def read(self, secret: Secret) -> str:
        """Read secret from path.

        Args:
            secret: Secret object with path, an optional field, and optional version

        Returns:
            Secret value as string

        Raises:
            SecretNotFoundError: Secret not found at path
            SecretAccessForbiddenError: Access denied to secret
            ValueError: Secret has multiple fields but field not specified

        Examples:
            # Simple single-field secret
            token = backend.read("slack/workspace-1/token")

            # Structured secret with field
            access_key = backend.read("aws/account1/creds", field="access_key_id")

            # Specific version (Vault KV v2)
            old_token = backend.read("slack/ws1/token", version=3)
        """

    @abstractmethod
    def read_all(self, secret: Secret) -> dict[str, Any]:
        """Read all fields from secret path.

        Args:
            secret: Secret object with path and optional version

        Returns:
            Dict with all secret fields (field name -> value)

        Raises:
            SecretNotFoundError: Secret not found at path
            SecretAccessForbiddenError: Access denied to secret

        Example:
            # Read all fields from AWS credentials secret
            creds = backend.read_all("aws/account1/creds")
            # Returns: {"access_key_id": "AKIATEST", "secret_access_key": "secret123"}

            # Read specific version
            old_creds = backend.read_all("aws/account1/creds", version=5)
        """

    @abstractmethod
    def write(
        self, secret: Secret, data: dict[str, str], *, force: bool = False
    ) -> None:
        """Write all fields to secret path, replacing any existing data there.

        `secret.field`/`.version` are not used - the whole path is written at once.

        Args:
            secret: Secret object identifying the path (and backend url) to write to
            data: Field name -> value mapping to write
            force: If True, write even if the current data is identical (by default,
                an identical write is skipped to avoid unnecessary backend version
                churn, e.g. new KV versions on every reconciliation run)

        Raises:
            SecretAccessForbiddenError: Access denied to secret
        """

    @abstractmethod
    def delete(self, secret: Secret) -> None:
        """Delete the secret at path.

        `secret.field`/`.version` are not used - the whole path is deleted.

        Args:
            secret: Secret object identifying the path (and backend url) to delete

        Raises:
            SecretAccessForbiddenError: Access denied to secret
        """

    @abstractmethod
    def list(self, secret: Secret) -> list[str]:
        """List secret keys directly under path.

        `secret.field`/`.version` are not used.

        Args:
            secret: Secret object identifying the path (and backend url) to list

        Returns:
            List of key names directly under path (directory-like entries end in
            "/"). Empty list if path does not exist.

        Raises:
            SecretAccessForbiddenError: Access denied to path
        """

    def close(self) -> None:  # noqa: B027
        """Close backend connections and cleanup resources.

        Optional method for backends that need explicit cleanup
        (e.g., stopping background threads, closing connections).

        Default implementation does nothing. Backends override as needed.
        """

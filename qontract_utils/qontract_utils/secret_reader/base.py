"""Abstract base class for secret backends.

Provides a pluggable interface for different secret management systems
(HashiCorp Vault, AWS KMS, Google Secret Manager, etc.).

Similar to CacheBackend pattern:
- Singleton per backend type
- Thread-safe factory method
- Abstract interface for concrete implementations
"""

import threading
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Protocol


class SecretNotFoundError(Exception):
    """Secret not found at specified path."""


class SecretAccessForbiddenError(Exception):
    """Access denied to secret (permissions issue)."""


class SecretBackendError(Exception):
    """Generic secret backend error (connection, authentication, etc.)."""


class Secret(Protocol):
    path: str
    field: str | None
    version: int | None


class SecretBackend(ABC):
    """Abstract base class for secret backends.

    Provides thread-safe singleton instances per backend type (e.g., "vault",
    "aws_kms", "google"). Each backend implementation must override read()
    and read_all() methods.

    Singleton Pattern (double-checked locking):
    - get_instance() provides thread-safe singleton per backend type
    - reset_singleton() for testing cleanup

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

    # Singleton instances per backend type
    _instances: ClassVar[dict[str, "SecretBackend"]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod  # TODO: backend specific parameters e.g. VaultSettings, AWSKMSSettings
    def get_instance(cls, backend_type: str, **kwargs: Any) -> "SecretBackend":
        """Get singleton secret backend instance (thread-safe factory).

        Uses double-checked locking for thread safety. Each backend type
        (vault, aws_kms, google) has its own singleton instance.

        Args:
            backend_type: Backend type ("vault", "aws_kms", "google")
            **kwargs: Backend-specific initialization parameters
                     For Vault: server, role_id, secret_id, kube_auth_role, etc.

        Returns:
            Singleton SecretBackend instance for the specified backend type

        Raises:
            ValueError: If backend_type is not supported

        Example:
            # Vault with AppRole auth
            vault_backend = SecretBackend.get_instance(
                backend_type="vault",
                server="https://vault.example.com",
                role_id="qontract-api",
                secret_id="xxxyyy",
            )

            # Vault with Kubernetes auth
            vault_backend = SecretBackend.get_instance(
                backend_type="vault",
                server="https://vault.example.com",
                kube_auth_role="qontract-api",
            )
        """
        # Fast path: Check if instance exists (no lock needed)
        if backend_type in cls._instances:
            return cls._instances[backend_type]

        # Slow path: Create new instance (thread-safe)
        with cls._lock:
            # Double-check after acquiring lock (another thread may have created it)
            if backend_type not in cls._instances:
                # Factory: Create backend based on type
                match backend_type:
                    case "vault":
                        # Import moved inside to avoid circular imports
                        from qontract_utils.secret_reader.providers.vault import (  # noqa: PLC0415
                            VaultSecretBackend,
                        )

                        cls._instances[backend_type] = VaultSecretBackend(**kwargs)
                    case _:
                        msg = f"Unsupported secret backend: {backend_type}"
                        raise ValueError(msg)

        return cls._instances[backend_type]

    @classmethod
    def reset_singleton(cls, backend_type: str | None = None) -> None:
        """Reset singleton instance(s) - primarily for testing.

        Args:
            backend_type: Specific backend type to reset (None = reset all)

        Example:
            # Reset all singletons
            SecretBackend.reset_singleton()

            # Reset only Vault singleton
            SecretBackend.reset_singleton("vault")
        """
        with cls._lock:
            if backend_type:
                # Reset specific backend
                if backend_type in cls._instances:
                    cls._instances[backend_type].close()
                    del cls._instances[backend_type]
            else:
                # Reset all backends
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

    def close(self) -> None:  # noqa: B027
        """Close backend connections and cleanup resources.

        Optional method for backends that need explicit cleanup
        (e.g., stopping background threads, closing connections).

        Default implementation does nothing. Backends override as needed.
        """

"""HashiCorp Vault secret backend using python-hvac.

Implements SecretBackend interface for Vault KV v2 secrets engine.

Features:
- AppRole authentication (role_id + secret_id)
- Kubernetes authentication (service account token)
- Auto-refresh of authentication token (background thread)
- KV v2 version support (read specific versions or latest)
- Thread-safe operations
"""

import contextvars
import pathlib
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import hvac
import structlog
from hvac.exceptions import Forbidden, InvalidPath
from prometheus_client import Counter, Histogram
from pydantic import BaseModel

from qontract_utils.hooks import (
    DEFAULT_RETRY_CONFIG,
    NO_RETRY_CONFIG,
    RetryConfig,
    invoke_with_hooks,
)
from qontract_utils.secret_reader.base import (
    Secret,
    SecretAccessForbiddenError,
    SecretBackend,
    SecretBackendError,
    SecretNotFoundError,
)

logger = structlog.get_logger(__name__)

# KV secrets engine versions
KV_VERSION_1 = 1
KV_VERSION_2 = 2

# Kubernetes service account token path (standard location in K8s pods)
DEFAULT_KUBE_SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"  # noqa: S105


class VaultSecret(BaseModel):
    kv_version: int
    mount_point: str
    read_path: str


class VaultSecretBackendSettings(BaseModel):
    server: str
    role_id: str | None = None
    secret_id: str | None = None
    kube_auth_role: str | None = None
    kube_auth_mount: str = "kubernetes"
    kube_sa_token_path: str = DEFAULT_KUBE_SA_TOKEN_PATH
    auto_refresh: bool = True


@dataclass(frozen=True)
class VaultApiCallContext:
    """Context information passed to API call hooks.

    Attributes:
        method: API method name (e.g., "schedules.get")
        id: Vault server
    """

    method: str
    id: str


# Prometheus metrics
vault_request = Counter(
    # Following naming convention (qontract_reconcile_external_api_<component>_requests_total) to
    # automatically include this metric in dashboards
    "qontract_reconcile_external_api_vault_requests_total",
    "Total number of Vault API requests",
    ["method", "server"],
)

vault_request_duration = Histogram(
    "qontract_reconcile_external_api_vault_request_duration_seconds",
    "Vault API request duration in seconds",
    ["method", "server"],
)

# Local storage for latency tracking
_latency_tracker = contextvars.ContextVar("latency_tracker", default=0.0)


def _metrics_hook(context: VaultApiCallContext) -> None:
    """Built-in Prometheus metrics hook.

    Records all API calls with method and server labels.
    """
    vault_request.labels(context.method, context.id).inc()


def _latency_start_hook(_context: VaultApiCallContext) -> None:
    """Built-in hook to start latency measurement.

    Stores the start time in local storage.
    """
    _latency_tracker.set(time.perf_counter())


def _latency_end_hook(context: VaultApiCallContext) -> None:
    """Built-in hook to record latency measurement.

    Calculates duration from start time and records to Prometheus histogram.
    """
    duration = time.perf_counter() - _latency_tracker.get()
    vault_request_duration.labels(context.method, context.id).observe(duration)
    _latency_tracker.set(0.0)


def _request_log_hook(context: VaultApiCallContext) -> None:
    """Built-in hook for logging API requests."""
    logger.debug("API request", method=context.method)


class VaultSecretBackend(SecretBackend):
    """HashiCorp Vault secret backend using python-hvac.

    Supports both AppRole and Kubernetes authentication. Auto-refreshes
    auth token every 10 minutes in background thread.

    Reads from Vault KV v2 secrets engine with version support.

    Args:
        server: Vault server URL (e.g., "https://vault.example.com")
        role_id: AppRole role_id (required for AppRole auth)
        secret_id: AppRole secret_id (required for AppRole auth)
        kube_auth_role: Kubernetes auth role (required for K8s auth)
        kube_auth_mount: Kubernetes auth mount point (default: "kubernetes")
        kube_sa_token_path: Path to K8s service account token
        auto_refresh: Enable auto-refresh of auth token (default: True)

    Raises:
        ValueError: If neither AppRole nor K8s auth credentials provided
        SecretBackendError: If Vault authentication fails

    Example:
        # AppRole auth
        backend = VaultSecretBackend(
            server="https://vault.example.com",
            role_id="my-role-id",
            secret_id="my-secret-id",
        )

        # Kubernetes auth
        backend = VaultSecretBackend(
            server="https://vault.example.com",
            kube_auth_role="qontract-api",
        )

        # Read secret
        token = backend.read("slack/workspace-1/token")

        # Read specific version
        old_token = backend.read("slack/workspace-1/token", version=3)

        # Read structured secret
        access_key = backend.read("aws/account1/creds", field="access_key_id")
    """

    def __init__(
        self,
        settings: VaultSecretBackendSettings,
        pre_hooks: Iterable[Callable[[VaultApiCallContext], None]] | None = None,
        post_hooks: Iterable[Callable[[VaultApiCallContext], None]] | None = None,
        error_hooks: Iterable[Callable[[VaultApiCallContext], None]] | None = None,
        retry_hooks: Iterable[Callable[[VaultApiCallContext, int], None]] | None = None,
        retry_config: RetryConfig | None = DEFAULT_RETRY_CONFIG,
    ) -> None:
        """Initialize Vault secret backend.

        Args:
            settings: Vault secret backend settings
        """
        self._settings = settings
        self._client = hvac.Client(url=settings.server)
        self._kv_version_cache: dict[str, int] = {}  # Cache KV version per mount point
        self._auth_lock = threading.Lock()  # Lock for authentication operations
        self._closed = False
        self._refresh_interval = 300  # 5 minutes

        # Setup hook system - always include built-in hooks
        self._pre_hooks: list[Callable[[VaultApiCallContext], None]] = [
            _metrics_hook,
            _latency_start_hook,
            _request_log_hook,
        ]
        if pre_hooks:
            self._pre_hooks.extend(pre_hooks)
        self._post_hooks: list[Callable[[VaultApiCallContext], None]] = [
            _latency_end_hook
        ]
        if post_hooks:
            self._post_hooks.extend(post_hooks)
        self._error_hooks: list[Callable[[VaultApiCallContext], None]] = []
        if error_hooks:
            self._error_hooks.extend(error_hooks)
        self._retry_hooks: list[Callable[[VaultApiCallContext, int], None]] = []
        if retry_hooks:
            self._retry_hooks.extend(retry_hooks)
        self._retry_config = retry_config

        # Initial authentication
        self._authenticate()

        # Start auto-refresh thread
        if settings.auto_refresh:
            self._refresh_thread = threading.Thread(
                target=self._auto_refresh_loop, daemon=True
            )
            self._refresh_thread.start()

    @property
    def url(self) -> str:
        """Vault server URL."""
        return self._settings.server

    @invoke_with_hooks(
        lambda self: VaultApiCallContext(
            method="auth.approle.login", id=self._settings.server
        )
    )
    def _approle_login(self) -> None:
        """Perform AppRole authentication API call."""
        self._client.auth.approle.login(
            role_id=self._settings.role_id,
            secret_id=self._settings.secret_id,
        )

    @invoke_with_hooks(
        lambda self: VaultApiCallContext(
            method="auth.kubernetes.login", id=self._settings.server
        )
    )
    def _kube_login(self, jwt: str) -> None:
        """Perform Kubernetes authentication API call."""
        self._client.auth.kubernetes.login(
            role=self._settings.kube_auth_role,
            jwt=jwt,
            mount_point=self._settings.kube_auth_mount,
        )

    def _authenticate(self) -> None:
        """Authenticate with Vault using AppRole or Kubernetes auth.

        Raises:
            ValueError: If no auth credentials provided
            SecretBackendError: If authentication fails
        """
        if self._settings.role_id and self._settings.secret_id:
            # AppRole authentication
            logger.debug("Authenticating to Vault using AppRole")
            self._approle_login()
        elif self._settings.kube_auth_role:
            # Kubernetes authentication
            logger.debug("Authenticating to Vault using Kubernetes auth")
            jwt = pathlib.Path(self._settings.kube_sa_token_path).read_text(
                encoding="utf-8"
            )
            self._kube_login(jwt)
        else:
            msg = (
                "Must provide either AppRole credentials (role_id + secret_id) "
                "or Kubernetes auth credentials (kube_auth_role)"
            )
            raise ValueError(msg)

        # Verify authentication succeeded
        if not self._client.is_authenticated():
            raise SecretBackendError("Vault authentication failed")

        logger.info("Successfully authenticated to Vault")

    @invoke_with_hooks(
        lambda self: VaultApiCallContext(
            method="secrets.kv.v2.read_configuration", id=self._settings.server
        ),
        retry_config=NO_RETRY_CONFIG,
    )
    def _read_kv_config(self, mount_point: str) -> None:
        """Read KV v2 configuration API call.

        Note: This method intentionally uses NO_RETRY_CONFIG because it's used for
        KV version detection via try/except. Any exception (InvalidPath, Forbidden, etc.)
        indicates KV v1, so retries would be counterproductive.
        """
        self._client.secrets.kv.v2.read_configuration(mount_point)

    def _compile_vault_secret(self, path: str) -> VaultSecret:
        """Compile a VaultSecret object from the given secret path."""
        mount_point, read_path = path.split("/", 1)
        # Check cache first
        if mount_point in self._kv_version_cache:
            return VaultSecret(
                kv_version=self._kv_version_cache[mount_point],
                mount_point=mount_point,
                read_path=read_path,
            )

        # Try to read KV v2 configuration
        # If this succeeds, it's a KV v2 engine
        # If it fails (any exception), assume KV v1
        try:
            self._read_kv_config(mount_point)
            kv_version = KV_VERSION_2
        except Exception:  # noqa: BLE001
            # Broad exception catch is intentional here:
            # - InvalidPath: mount doesn't exist or is KV v1
            # - Forbidden: no permission (assume v1 as fallback)
            # - Any other error: assume v1 as safe default
            kv_version = KV_VERSION_1

        # Cache the detected version
        self._kv_version_cache[mount_point] = kv_version
        logger.debug(f"Detected KV v{kv_version} for mount point '{mount_point}'")
        return VaultSecret(
            kv_version=kv_version,
            mount_point=mount_point,
            read_path=read_path,
        )

    def _auto_refresh_loop(self) -> None:
        """Background thread to periodically refresh Vault auth token.

        Runs every 10 minutes, re-authenticates to get fresh token.
        Logs errors but doesn't crash thread to allow recovery.
        """
        while not self._closed:
            time.sleep(self._refresh_interval)
            if not self._closed:
                with self._auth_lock:
                    try:
                        logger.debug("Auto-refreshing Vault token")
                        self._authenticate()
                    except Exception:
                        # Log error but don't crash thread
                        # Next iteration will try again
                        logger.exception("Failed to refresh Vault token")

    def read(self, secret: Secret) -> str:
        """Read secret from Vault KV.

        Automatically detects KV v1 or v2 based on mount point configuration.

        Args:
            secret: Secret object with path, field, and optional version

        Returns:
            Secret value as string

        Raises:
            SecretNotFoundError: Secret or field not found
            SecretAccessForbiddenError: Access denied to secret
            ValueError: Secret has multiple fields but field not specified

        Examples:
            # Single-field secret (returns the value)
            token = backend.read("slack/workspace-1/token")

            # Multi-field secret (field required)
            access_key = backend.read("aws/account1/creds", field="access_key_id")

            # Specific version (KV v2 only)
            old_token = backend.read("slack/ws1/token", version=3)
        """
        # Read all fields from Vault
        data = self.read_all(secret)

        # Extract field value
        if secret.field:
            if secret.field not in data:
                raise SecretNotFoundError(
                    f"Field '{secret.field}' not found in secret {secret.path}. "
                    f"Available fields: {list(data.keys())}"
                )
            return data[secret.field]

        # If no field specified and secret has single field, return it
        if len(data) == 1:
            return next(iter(data.values()))

        # Multiple fields but no field specified - error
        msg = (
            f"Secret {secret.path} has multiple fields {list(data.keys())}. "
            "Specify field parameter to select one."
        )
        raise ValueError(msg)

    @invoke_with_hooks(
        lambda self: VaultApiCallContext(
            method="secrets.kv.v2.read_secret_version",
            id=self._settings.server,
        )
    )
    def _read_kv_v2_secret(
        self, path: str, mount_point: str, version: int | None
    ) -> dict[str, Any]:
        """Read KV v2 secret API call."""
        response = self._client.secrets.kv.v2.read_secret_version(
            path=path,
            mount_point=mount_point,
            version=version,
        )
        return response["data"]["data"]

    @invoke_with_hooks(
        lambda self: VaultApiCallContext(
            method="secrets.kv.v1.read_secret", id=self._settings.server
        )
    )
    def _read_kv_v1_secret(self, path: str, mount_point: str) -> dict[str, Any]:
        """Read KV v1 secret API call."""
        response = self._client.secrets.kv.v1.read_secret(
            path=path, mount_point=mount_point
        )
        return response["data"]

    def read_all(self, secret: Secret) -> dict[str, Any]:
        """Read all fields from Vault secret.

        Automatically detects KV v1 or v2 based on mount point configuration.

        Args:
            path: Secret path WITHOUT mount prefix
            version: Optional version number for KV v2 (None = latest, ignored for KV v1)

        Returns:
            Dict with all secret fields (field name -> value)

        Raises:
            SecretNotFoundError: Secret not found
            SecretAccessForbiddenError: Access denied to secret

        Example:
            # Read all fields
            creds = backend.read_all("aws/account1/creds")
            # Returns: {"access_key_id": "AKIATEST", "secret_access_key": "secret123"}

            # Read specific version (KV v2 only)
            old_creds = backend.read_all("aws/account1/creds", version=5)
        """
        vault_secret = self._compile_vault_secret(secret.path)

        logger.debug(
            f"Reading all Vault secret fields: path={secret.path}, version={secret.version}, kv_version={vault_secret.kv_version}"
        )

        # Read from Vault (KV v1 or v2)
        # hvac.Client is thread-safe for authenticated operations
        try:
            if vault_secret.kv_version == KV_VERSION_2:
                return self._read_kv_v2_secret(
                    vault_secret.read_path, vault_secret.mount_point, secret.version
                )

            # KV v1 - no versioning support
            return self._read_kv_v1_secret(
                vault_secret.read_path, vault_secret.mount_point
            )
        except InvalidPath as e:
            raise SecretNotFoundError(f"Secret not found: {secret.path}") from e
        except Forbidden as e:
            raise SecretAccessForbiddenError(f"Access denied: {secret.path}") from e

    def close(self) -> None:
        """Close Vault client and stop auto-refresh thread.

        Sets _closed flag to signal refresh thread to stop.
        The hvac client itself doesn't need explicit closing.
        """
        with self._auth_lock:
            logger.debug("Closing Vault secret backend")
            self._closed = True
            # hvac Client doesn't need explicit close

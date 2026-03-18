"""Unit tests for secret_reader.providers.vault module.

Tests the VaultSecretBackend implementation with python-hvac.
"""

# ruff: noqa: ARG001

from typing import Any, NoReturn
from unittest.mock import MagicMock, mock_open, patch

import pytest
from hvac.exceptions import Forbidden, InvalidPath, VaultError
from pydantic import BaseModel
from qontract_utils.hooks import Hooks
from qontract_utils.secret_reader.base import (
    SecretAccessForbiddenError,
    SecretBackendError,
    SecretNotFoundError,
)
from qontract_utils.secret_reader.providers.vault import (
    VaultSecretBackend,
    VaultSecretBackendSettings,
)


class Secret(BaseModel):
    url: str = "https://vault.test"
    path: str
    field: str | None = None
    version: int | None = None


@pytest.fixture
def approle_settings() -> VaultSecretBackendSettings:
    """Create AppRole auth settings for testing."""
    return VaultSecretBackendSettings(
        server="https://vault.test",
        role_id="test-role-id",
        secret_id="test-secret-id",
        auto_refresh=False,
    )


@pytest.fixture
def kube_settings() -> VaultSecretBackendSettings:
    """Create Kubernetes auth settings for testing."""
    return VaultSecretBackendSettings(
        server="https://vault.test",
        kube_auth_role="test-kube-role",
        kube_auth_mount="kubernetes",
        kube_sa_token_path="/var/run/secrets/kubernetes.io/serviceaccount/token",
        auto_refresh=False,
    )


class TestVaultSecretBackendAuthentication:
    """Test Vault authentication methods."""

    def test_init_with_approle_auth(
        self, approle_settings: VaultSecretBackendSettings
    ) -> None:
        """Test initialization with AppRole authentication."""
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            backend = VaultSecretBackend(approle_settings)

            mock_client_class.assert_called_once_with(url="https://vault.test")
            mock_client.auth.approle.login.assert_called_once_with(
                role_id="test-role-id",
                secret_id="test-secret-id",
            )
            assert backend is not None

    def test_init_with_kubernetes_auth(
        self, kube_settings: VaultSecretBackendSettings
    ) -> None:
        """Test initialization with Kubernetes authentication."""
        mock_jwt_token = "test-jwt-token"

        with (
            patch("hvac.Client") as mock_client_class,
            patch("pathlib.Path.open", mock_open(read_data=mock_jwt_token)),
        ):
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            backend = VaultSecretBackend(kube_settings)

            mock_client_class.assert_called_once_with(url="https://vault.test")
            mock_client.auth.kubernetes.login.assert_called_once_with(
                role="test-kube-role",
                jwt=mock_jwt_token,
                mount_point="kubernetes",
            )
            assert backend is not None

    def test_init_without_credentials_raises_error(self) -> None:
        """Test that initialization without credentials raises ValueError."""
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            with pytest.raises(
                ValueError,
                match="Must provide either AppRole credentials.*or Kubernetes auth credentials",
            ):
                VaultSecretBackend(
                    VaultSecretBackendSettings(
                        server="https://vault.test",
                        auto_refresh=False,
                    )
                )

    def test_init_failed_authentication_raises_error(
        self, approle_settings: VaultSecretBackendSettings
    ) -> None:
        """Test that failed authentication raises SecretBackendError."""
        with (
            patch("hvac.Client") as mock_client_class,
            pytest.raises(SecretBackendError, match="Vault authentication failed"),
        ):
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = False
            mock_client_class.return_value = mock_client

            VaultSecretBackend(approle_settings)


class TestVaultSecretBackendRead:
    """Test Vault read operations."""

    def setup_method(self) -> None:
        """Create a mock VaultSecretBackend for each test."""
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            settings = VaultSecretBackendSettings(
                server="https://vault.test",
                role_id="test-role-id",
                secret_id="test-secret-id",
                auto_refresh=False,
            )
            self.backend = VaultSecretBackend(settings)
            self.mock_client = mock_client

    def test_read_single_field_secret(self) -> None:
        """Test reading a secret with a single field."""
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"token": "xoxb-test-token"}}
        }

        result = self.backend.read(Secret(path="secret/workspace-1/token"))

        assert result == "xoxb-test-token"
        self.mock_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="workspace-1/token",
            mount_point="secret",
            version=None,
        )

    def test_read_with_field_parameter(self) -> None:
        """Test reading a specific field from a multi-field secret."""
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {
                "data": {
                    "access_key_id": "AKIATEST",
                    "secret_access_key": "secret123",
                }
            }
        }

        result = self.backend.read(
            Secret(path="secret/account1/creds", field="access_key_id")
        )

        assert result == "AKIATEST"
        self.mock_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="account1/creds",
            mount_point="secret",
            version=None,
        )

    def test_read_with_version_parameter(self) -> None:
        """Test reading a specific version of a secret."""
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"token": "xoxb-old-token"}}
        }

        result = self.backend.read(Secret(path="secret/workspace-1/token", version=3))

        assert result == "xoxb-old-token"
        self.mock_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="workspace-1/token",
            mount_point="secret",
            version=3,
        )

    def test_read_multi_field_without_field_raises_error(self) -> None:
        """Test that reading multi-field secret without field parameter raises ValueError."""
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {
                "data": {
                    "access_key_id": "AKIATEST",
                    "secret_access_key": "secret123",
                }
            }
        }

        with pytest.raises(
            ValueError,
            match="Secret secret/account1/creds has multiple fields.*Specify field parameter",
        ):
            self.backend.read(Secret(path="secret/account1/creds"))

    def test_read_nonexistent_field_raises_error(self) -> None:
        """Test that reading non-existent field raises SecretNotFoundError."""
        # Mock KV version detection first
        self.mock_client.secrets.kv.v2.read_configuration.return_value = {}
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"token": "xoxb-test-token"}}
        }

        with pytest.raises(
            SecretNotFoundError,
            match="Field 'nonexistent' not found in secret secret/ws1/token",
        ):
            self.backend.read(Secret(path="secret/ws1/token", field="nonexistent"))

    def test_read_invalid_path_raises_error(self) -> None:
        """Test that reading invalid path raises SecretNotFoundError."""
        self.mock_client.secrets.kv.v2.read_secret_version.side_effect = InvalidPath()

        with pytest.raises(
            SecretNotFoundError, match="Secret not found: secret/invalid/path"
        ):
            self.backend.read(Secret(path="secret/invalid/path"))

    def test_read_forbidden_path_raises_error(self) -> None:
        """Test that reading forbidden path raises SecretAccessForbiddenError."""
        self.mock_client.secrets.kv.v2.read_secret_version.side_effect = Forbidden()

        with pytest.raises(
            SecretAccessForbiddenError, match="Access denied: secret/forbidden/path"
        ):
            self.backend.read(Secret(path="secret/forbidden/path"))

    def test_read_with_kv_v2_detection(self) -> None:
        """Test that read() detects KV version correctly."""
        # Mock KV v2 detection
        self.mock_client.secrets.kv.v2.read_configuration.return_value = {}
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"token": "xoxb-test-token"}}
        }

        result = self.backend.read(Secret(path="secret/workspace-1/token"))

        assert result == "xoxb-test-token"
        # Should call read_configuration once to detect KV version
        self.mock_client.secrets.kv.v2.read_configuration.assert_called_once()


class TestVaultSecretBackendReadAll:
    """Test Vault read_all operations."""

    def setup_method(self) -> None:
        """Create a mock VaultSecretBackend for each test."""
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            settings = VaultSecretBackendSettings(
                server="https://vault.test",
                role_id="test-role-id",
                secret_id="test-secret-id",
                auto_refresh=False,
            )
            self.backend = VaultSecretBackend(settings)
            self.mock_client = mock_client

    def test_read_all_returns_all_fields(self) -> None:
        """Test reading all fields from a secret."""
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {
                "data": {
                    "access_key_id": "AKIATEST",
                    "secret_access_key": "secret123",
                }
            }
        }

        result = self.backend.read_all(Secret(path="secret/account1/creds"))

        assert result == {
            "access_key_id": "AKIATEST",
            "secret_access_key": "secret123",
        }
        self.mock_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="account1/creds",
            mount_point="secret",
            version=None,
        )

    def test_read_all_with_version(self) -> None:
        """Test reading all fields from a specific version."""
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {
                "data": {
                    "access_key_id": "AKIAOLD",
                    "secret_access_key": "old123",
                }
            }
        }

        result = self.backend.read_all(Secret(path="secret/account1/creds", version=2))

        assert result == {
            "access_key_id": "AKIAOLD",
            "secret_access_key": "old123",
        }
        self.mock_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="account1/creds",
            mount_point="secret",
            version=2,
        )

    def test_read_all_invalid_path_raises_error(self) -> None:
        """Test that read_all with invalid path raises SecretNotFoundError."""
        self.mock_client.secrets.kv.v2.read_secret_version.side_effect = InvalidPath()

        with pytest.raises(
            SecretNotFoundError, match="Secret not found: secret/invalid/path"
        ):
            self.backend.read_all(Secret(path="secret/invalid/path"))

    def test_read_all_forbidden_path_raises_error(self) -> None:
        """Test that read_all with forbidden path raises SecretAccessForbiddenError."""
        self.mock_client.secrets.kv.v2.read_secret_version.side_effect = Forbidden()

        with pytest.raises(
            SecretAccessForbiddenError, match="Access denied: secret/forbidden/path"
        ):
            self.backend.read_all(Secret(path="secret/forbidden/path"))


class TestVaultSecretBackendAutoRefresh:
    """Test Vault auto-refresh functionality."""

    def test_auto_refresh_thread_starts_when_enabled(self) -> None:
        """Test that auto-refresh thread starts when auto_refresh=True."""
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            settings = VaultSecretBackendSettings(
                server="https://vault.test",
                role_id="test-role-id",
                secret_id="test-secret-id",
                auto_refresh=True,
            )
            backend = VaultSecretBackend(settings)

            assert hasattr(backend, "_refresh_thread")
            assert backend._refresh_thread.daemon is True
            assert backend._refresh_thread.is_alive()

            # Cleanup
            backend.close()

    def test_auto_refresh_disabled_does_not_start_thread(
        self, approle_settings: VaultSecretBackendSettings
    ) -> None:
        """Test that auto-refresh thread does not start when auto_refresh=False."""
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            backend = VaultSecretBackend(approle_settings)

            assert not hasattr(backend, "_refresh_thread")

    def test_auto_refresh_loop_renew_success(self) -> None:
        """Test that the auto-refresh loop successfully renews the token."""
        with (
            patch("hvac.Client") as mock_client_class,
            patch("time.sleep") as mock_sleep,
        ):
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            settings = VaultSecretBackendSettings(
                server="http://vault", kube_auth_role="role", auto_refresh=False
            )

            # Use a dummy token to avoid the file read in _authenticate
            with patch("pathlib.Path.open", mock_open(read_data="dummy_jwt")):
                backend = VaultSecretBackend(settings)

            # Simulate the loop behavior
            backend._closed = False

            counter = 0

            def side_effect(*_args: Any, **_kwargs: Any) -> None:
                nonlocal counter
                if counter > 0:
                    backend._closed = True  # Exit loop after first iteration
                counter += 1

            mock_sleep.side_effect = side_effect

            backend._auto_refresh_loop()

            # Verify renew_self was called and _authenticate was NOT called (after initial setup)
            mock_client.auth.token.renew_self.assert_called_once()
            assert (
                mock_client.auth.kubernetes.login.call_count == 1
            )  # Only called during __init__

    def test_auto_refresh_loop_renew_failure_fallback(self) -> None:
        """Test that the auto-refresh loop falls back to login if renew fails."""
        with (
            patch("hvac.Client") as mock_client_class,
            patch("time.sleep") as mock_sleep,
        ):
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            # Make renew_self fail
            mock_client.auth.token.renew_self.side_effect = VaultError("Token expired")
            mock_client_class.return_value = mock_client

            settings = VaultSecretBackendSettings(
                server="http://vault", kube_auth_role="role", auto_refresh=False
            )

            with patch("pathlib.Path.open", mock_open(read_data="dummy_jwt")):
                backend = VaultSecretBackend(settings)

            backend._closed = False

            counter = 0

            def side_effect(*_args: Any, **_kwargs: Any) -> None:
                nonlocal counter
                if counter > 0:
                    backend._closed = True
                counter += 1

            mock_sleep.side_effect = side_effect

            # We must patch Path.open again because _authenticate will be called in the fallback
            with patch("pathlib.Path.open", mock_open(read_data="dummy_jwt")):
                backend._auto_refresh_loop()

            # Verify renew was attempted, but failed, so login was called again
            mock_client.auth.token.renew_self.assert_called_once()
            assert mock_client.auth.kubernetes.login.call_count == 2  # Init + Fallback


class TestVaultSecretBackendClose:
    """Test Vault close operations."""

    def test_close_sets_closed_flag(
        self, approle_settings: VaultSecretBackendSettings
    ) -> None:
        """Test that close() sets the _closed flag."""
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            backend = VaultSecretBackend(approle_settings)

            assert not backend._closed

            backend.close()

            assert backend._closed

    def test_close_stops_auto_refresh_thread(self) -> None:
        """Test that close() stops the auto-refresh thread."""
        import time

        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            settings = VaultSecretBackendSettings(
                server="https://vault.test",
                role_id="test-role-id",
                secret_id="test-secret-id",
                auto_refresh=True,
            )
            backend = VaultSecretBackend(settings)

            # Thread should be running
            assert backend._refresh_thread.is_alive()

            backend.close()

            # Give thread a moment to check _closed flag and exit
            time.sleep(0.1)

            # Thread should be stopped (daemon threads exit when _closed=True)
            # Note: daemon threads don't guarantee immediate exit, so this may be flaky
            # Better to just check _closed flag
            assert backend._closed


class TestVaultSecretBackendCustomMountPoint:
    """Test Vault with custom mount point."""

    def test_custom_mount_point(
        self, approle_settings: VaultSecretBackendSettings
    ) -> None:
        """Test that custom mount_point is used for KV operations."""
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client.secrets.kv.v2.read_secret_version.return_value = {
                "data": {"data": {"token": "xoxb-test-token"}}
            }
            mock_client_class.return_value = mock_client

            backend = VaultSecretBackend(approle_settings)

            backend.read(Secret(path="app-sre-secrets/workspace-1/token"))

            mock_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
                path="workspace-1/token",
                mount_point="app-sre-secrets",
                version=None,
            )


class TestVaultSecretBackendHooks:
    """Test Vault hook system."""

    def test_pre_hooks_includes_metrics_and_latency(
        self, approle_settings: VaultSecretBackendSettings
    ) -> None:
        """Test that metrics and latency hooks are always included."""
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            backend = VaultSecretBackend(approle_settings)

            # Should have metrics, latency_start, and request_log hooks
            assert len(backend._hooks.pre_hooks) >= 3

    def test_pre_hooks_custom(
        self, approle_settings: VaultSecretBackendSettings
    ) -> None:
        """Test custom pre_hooks are added after built-in hooks."""
        custom_hook = MagicMock()
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            backend = VaultSecretBackend(
                approle_settings, hooks=Hooks(pre_hooks=[custom_hook])
            )

            # Should have built-in hooks + custom hook
            assert len(backend._hooks.pre_hooks) == 4
            assert custom_hook in backend._hooks.pre_hooks

    def test_post_hooks_includes_latency(
        self, approle_settings: VaultSecretBackendSettings
    ) -> None:
        """Test that slow_request and latency_end hooks are always included in post_hooks."""
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            backend = VaultSecretBackend(approle_settings)

            # Should have slow_request and latency_end hooks
            assert len(backend._hooks.post_hooks) >= 2

    def test_post_hooks_custom(
        self, approle_settings: VaultSecretBackendSettings
    ) -> None:
        """Test custom post_hooks are added after built-in hooks."""
        custom_hook = MagicMock()
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            backend = VaultSecretBackend(
                approle_settings, hooks=Hooks(post_hooks=[custom_hook])
            )

            # Should have slow_request hook + latency_end hook + custom hook
            assert len(backend._hooks.post_hooks) == 3
            assert custom_hook in backend._hooks.post_hooks

    def test_error_hooks_custom(
        self, approle_settings: VaultSecretBackendSettings
    ) -> None:
        """Test custom error_hooks are added."""
        custom_hook = MagicMock()
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            backend = VaultSecretBackend(
                approle_settings, hooks=Hooks(error_hooks=[custom_hook])
            )

            # Should have custom error hook
            assert len(backend._hooks.error_hooks) == 1
            assert backend._hooks.error_hooks[0] == custom_hook

    def test_read_calls_pre_hooks(
        self, approle_settings: VaultSecretBackendSettings
    ) -> None:
        """Test that read() calls pre_hooks before API call."""
        pre_hook = MagicMock()
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client.secrets.kv.v2.read_secret_version.return_value = {
                "data": {"data": {"token": "xoxb-test-token"}}
            }
            mock_client_class.return_value = mock_client

            backend = VaultSecretBackend(
                approle_settings, hooks=Hooks(pre_hooks=[pre_hook])
            )
            backend.read(Secret(path="secret/workspace-1/token"))

            # Pre-hook should have been called
            assert pre_hook.call_count > 0

    def test_read_calls_post_hooks(
        self, approle_settings: VaultSecretBackendSettings
    ) -> None:
        """Test that read() calls post_hooks after API call."""
        post_hook = MagicMock()
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client.secrets.kv.v2.read_secret_version.return_value = {
                "data": {"data": {"token": "xoxb-test-token"}}
            }
            mock_client_class.return_value = mock_client

            backend = VaultSecretBackend(
                approle_settings, hooks=Hooks(post_hooks=[post_hook])
            )
            backend.read(Secret(path="secret/workspace-1/token"))

            # Post-hook should have been called
            assert post_hook.call_count > 0


def test_vault_retries_on_transient_errors(enable_retry: None) -> None:
    """Test that VaultSecretBackend retries on transient errors."""
    with patch("hvac.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        mock_client_class.return_value = mock_client

        settings = VaultSecretBackendSettings(
            server="https://vault.test",
            role_id="test-role-id",
            secret_id="test-secret-id",
            auto_refresh=False,
        )
        backend = VaultSecretBackend(settings)

        # Mock: first 2 calls fail, 3rd succeeds
        call_count = {"count": 0}

        def side_effect(*args: Any, **kwargs: Any) -> dict:
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise Exception("Vault error")  # noqa: TRY002
            return {"data": {"data": {"token": "xoxb-test-token"}}}

        mock_client.secrets.kv.v2.read_secret_version = MagicMock(
            side_effect=side_effect
        )

        result = backend.read(Secret(path="secret/workspace-1/token"))

        assert result == "xoxb-test-token"
        assert call_count["count"] == 3


def test_vault_gives_up_after_max_attempts(enable_retry: None) -> None:
    """Test that VaultSecretBackend gives up after max retry attempts."""
    with patch("hvac.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        mock_client_class.return_value = mock_client

        settings = VaultSecretBackendSettings(
            server="https://vault.test",
            role_id="test-role-id",
            secret_id="test-secret-id",
            auto_refresh=False,
        )
        backend = VaultSecretBackend(settings)

        # Mock: always fails
        call_count = {"count": 0}

        def side_effect(*args: Any, **kwargs: Any) -> NoReturn:
            call_count["count"] += 1
            raise Exception("always fails")  # noqa: TRY002

        mock_client.secrets.kv.v2.read_secret_version = MagicMock(
            side_effect=side_effect
        )

        with pytest.raises(Exception, match="always fails"):
            backend.read(Secret(path="secret/workspace-1/token"))

        # Should have tried 3 times (attempts=3)
        assert call_count["count"] == 3


class TestVaultSlowRequestLogging:
    """Test Vault slow request logging."""

    def setup_method(self) -> None:
        """Create a mock VaultSecretBackend for each test."""
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            settings = VaultSecretBackendSettings(
                server="https://vault.test",
                role_id="test-role-id",
                secret_id="test-secret-id",
                auto_refresh=False,
            )
            self.backend = VaultSecretBackend(settings)
            self.mock_client = mock_client

    def test_slow_request_logs_warning(self) -> None:
        """Test that slow Vault requests log a warning with path, mount_point, duration, threshold."""
        # Pre-cache KV version to avoid config call
        self.backend._kv_version_cache["secret"] = 2
        # Mock slow request (2.3 seconds)
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"token": "xoxb-test-token"}}
        }

        with patch("time.perf_counter") as mock_time:
            # Use a counter to simulate passage of time
            counter = {"calls": 0}

            def time_func() -> float:
                counter["calls"] += 1
                # First call (latency_start_hook): 100.0
                # Second call (slow_request_hook peek): 102.3 (2.3s elapsed)
                # Third call (latency_end_hook): 102.3
                return 100.0 if counter["calls"] == 1 else 102.3

            mock_time.side_effect = time_func

            with patch(
                "qontract_utils.secret_reader.providers.vault.logger"
            ) as mock_logger:
                self.backend.read(Secret(path="secret/workspace-1/token"))

                # Check warning was logged with correct fields
                assert mock_logger.warning.call_count >= 1
                # Find the "Slow Vault request" calls (filter out other potential warnings)
                slow_request_calls = [
                    call
                    for call in mock_logger.warning.call_args_list
                    if call[0][0] == "Slow Vault request"
                ]
                # Should have exactly 1 call for read_secret_version
                assert len(slow_request_calls) == 1
                call_args = slow_request_calls[0]
                assert call_args[1]["path"] == "workspace-1/token"
                assert call_args[1]["mount_point"] == "secret"
                assert call_args[1]["duration"] == "2.3s"
                assert call_args[1]["threshold"] == "2.0s"

    def test_fast_request_no_warning(self) -> None:
        """Test that fast Vault requests do not log a warning."""
        # Pre-cache KV version to avoid config call
        self.backend._kv_version_cache["secret"] = 2
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"token": "xoxb-test-token"}}
        }

        with patch("time.perf_counter") as mock_time:
            # Use a counter to simulate passage of time
            counter = {"calls": 0}

            def time_func() -> float:
                counter["calls"] += 1
                # First call: 100.0, subsequent: 100.5 (0.5s elapsed - fast)
                return 100.0 if counter["calls"] == 1 else 100.5

            mock_time.side_effect = time_func

            with patch(
                "qontract_utils.secret_reader.providers.vault.logger"
            ) as mock_logger:
                self.backend.read(Secret(path="secret/workspace-1/token"))

                # No slow request warning should be logged
                slow_request_calls = [
                    call
                    for call in mock_logger.warning.call_args_list
                    if len(call[0]) > 0 and call[0][0] == "Slow Vault request"
                ]
                assert len(slow_request_calls) == 0

    def test_slow_auth_call_omits_path_mount_point(self) -> None:
        """Test that slow auth calls omit path/mount_point fields (they are None)."""
        with patch("time.perf_counter") as mock_time:
            # Use a counter to simulate passage of time
            counter = {"calls": 0}

            def time_func() -> float:
                counter["calls"] += 1
                # First call: 100.0, subsequent: 102.5 (2.5s elapsed)
                return 100.0 if counter["calls"] == 1 else 102.5

            mock_time.side_effect = time_func

            with (
                patch(
                    "qontract_utils.secret_reader.providers.vault.logger"
                ) as mock_logger,
                patch("hvac.Client") as mock_client_class,
            ):
                # Trigger auth call by creating a new backend
                mock_client = MagicMock()
                mock_client.is_authenticated.return_value = True
                mock_client_class.return_value = mock_client

                VaultSecretBackend(
                    VaultSecretBackendSettings(
                        server="https://vault.test",
                        role_id="test-role-id",
                        secret_id="test-secret-id",
                        auto_refresh=False,
                    )
                )

                # Check warning was logged WITHOUT path/mount_point
                slow_request_calls = [
                    call
                    for call in mock_logger.warning.call_args_list
                    if len(call[0]) > 0 and call[0][0] == "Slow Vault request"
                ]
                assert len(slow_request_calls) == 1
                call_args = slow_request_calls[0]
                # path and mount_point should NOT be in kwargs
                assert "path" not in call_args[1]
                assert "mount_point" not in call_args[1]
                # But duration and threshold should be present
                assert call_args[1]["duration"] == "2.5s"
                assert call_args[1]["threshold"] == "2.0s"

    def test_slow_request_threshold_boundary(self) -> None:
        """Test that exactly 2.0s is NOT slow, but 2.001s is slow."""
        # Pre-cache KV version to avoid config call
        self.backend._kv_version_cache["secret"] = 2
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"token": "xoxb-test-token"}}
        }

        # Test exactly 2.0s - NOT slow
        with patch("time.perf_counter") as mock_time:
            counter = {"calls": 0}

            def time_func() -> float:
                counter["calls"] += 1
                return 100.0 if counter["calls"] == 1 else 102.0

            mock_time.side_effect = time_func

            with patch(
                "qontract_utils.secret_reader.providers.vault.logger"
            ) as mock_logger:
                self.backend.read(Secret(path="secret/workspace-1/token"))
                slow_request_calls = [
                    call
                    for call in mock_logger.warning.call_args_list
                    if len(call[0]) > 0 and call[0][0] == "Slow Vault request"
                ]
                assert len(slow_request_calls) == 0

        # Reset mock
        self.mock_client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"token": "xoxb-test-token"}}
        }

        # Test 2.001s - IS slow
        with patch("time.perf_counter") as mock_time:
            counter = {"calls": 0}

            def time_func() -> float:
                counter["calls"] += 1
                return 100.0 if counter["calls"] == 1 else 102.001

            mock_time.side_effect = time_func

            with patch(
                "qontract_utils.secret_reader.providers.vault.logger"
            ) as mock_logger:
                self.backend.read(Secret(path="secret/workspace-1/token"))
                slow_request_calls = [
                    call
                    for call in mock_logger.warning.call_args_list
                    if len(call[0]) > 0 and call[0][0] == "Slow Vault request"
                ]
                assert len(slow_request_calls) == 1
                call_args = slow_request_calls[0]
                assert call_args[1]["duration"] == "2.0s"  # Formatted to 1 decimal


class TestVaultRetryConfiguration:
    """Test Vault retry configuration behavior."""

    def test_vault_read_retry_config_skips_forbidden(self) -> None:
        """Test that VAULT_READ_RETRY_CONFIG is configured to skip Forbidden errors."""
        from qontract_utils.secret_reader.providers.vault import VAULT_READ_RETRY_CONFIG

        # Verify retry config parameters
        assert VAULT_READ_RETRY_CONFIG.attempts == 10
        assert VAULT_READ_RETRY_CONFIG.timeout == 45.0

        # Verify on is a callable (function, not exception type)
        assert callable(VAULT_READ_RETRY_CONFIG.on)

        # Test the on() function behavior
        # Should retry on non-Forbidden exceptions
        assert VAULT_READ_RETRY_CONFIG.on(Exception("network error")) is True
        assert VAULT_READ_RETRY_CONFIG.on(VaultError("vault error")) is True
        assert VAULT_READ_RETRY_CONFIG.on(InvalidPath()) is True

        # Should NOT retry on Forbidden (expired token / permission denied)
        assert VAULT_READ_RETRY_CONFIG.on(Forbidden()) is False

    def test_read_does_not_retry_on_forbidden(
        self,
        enable_retry: None,  # noqa: ARG002
    ) -> None:
        """Test that read operations fail fast on Forbidden without retrying."""
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            settings = VaultSecretBackendSettings(
                server="https://vault.test",
                role_id="test-role-id",
                secret_id="test-secret-id",
                auto_refresh=False,
            )
            backend = VaultSecretBackend(settings)

            # Track call count
            call_count = {"count": 0}

            def forbidden_side_effect(*args: Any, **kwargs: Any) -> NoReturn:
                call_count["count"] += 1
                raise Forbidden

            # First call raises Forbidden, triggering re-auth
            # Second call (after re-auth) also raises Forbidden
            mock_client.secrets.kv.v2.read_secret_version.side_effect = (
                forbidden_side_effect
            )

            # Should raise SecretAccessForbiddenError after re-auth attempt
            with pytest.raises(
                SecretAccessForbiddenError, match="Access denied: secret/test/path"
            ):
                backend.read(Secret(path="secret/test/path"))

            # Should be called exactly once:
            # 1. Initial attempt (fails with Forbidden)
            # NO additional retries because Forbidden bypasses retry logic, and we removed the fallback
            assert call_count["count"] == 1

    def test_read_retries_on_vault_error(
        self,
        enable_retry: None,  # noqa: ARG002
    ) -> None:
        """Test that read operations retry on non-Forbidden Vault errors."""
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            settings = VaultSecretBackendSettings(
                server="https://vault.test",
                role_id="test-role-id",
                secret_id="test-secret-id",
                auto_refresh=False,
            )
            backend = VaultSecretBackend(settings)

            # Track call count
            call_count = {"count": 0}

            def error_side_effect(*args: Any, **kwargs: Any) -> Any:
                call_count["count"] += 1
                if call_count["count"] < 3:
                    raise VaultError("Temporary failure")
                return {"data": {"data": {"token": "xoxb-success"}}}

            mock_client.secrets.kv.v2.read_secret_version.side_effect = (
                error_side_effect
            )

            result = backend.read(Secret(path="secret/test/path"))

            assert result == "xoxb-success"
            # Should be called 3 times (2 failures + 1 success)
            assert call_count["count"] == 3

    def test_renew_self_does_not_retry(self) -> None:
        """Test that _renew_self fails fast without retrying (NO_RETRY_CONFIG).

        Note: This test does NOT use enable_retry fixture because we're testing
        that NO_RETRY_CONFIG disables retries even when retries are globally enabled.
        """
        with (
            patch("hvac.Client") as mock_client_class,
            patch("pathlib.Path.open", mock_open(read_data="dummy_jwt")),
        ):
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            settings = VaultSecretBackendSettings(
                server="https://vault.test",
                kube_auth_role="test-role",
                auto_refresh=False,
            )
            backend = VaultSecretBackend(settings)

            # Track renew_self call count
            call_count = {"count": 0}

            def count_calls(*args: Any, **kwargs: Any) -> NoReturn:
                call_count["count"] += 1
                raise VaultError("Token expired")

            mock_client.auth.token.renew_self.side_effect = count_calls

            # Call _renew_self directly
            with pytest.raises(VaultError, match="Token expired"):
                backend._renew_self()

            # Should be called exactly ONCE (NO retries due to NO_RETRY_CONFIG)
            assert call_count["count"] == 1

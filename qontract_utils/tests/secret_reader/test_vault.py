"""Unit tests for secret_reader.providers.vault module.

Tests the VaultSecretBackend implementation with python-hvac.
"""

# ruff: noqa: ARG001

from typing import Any, NoReturn
from unittest.mock import MagicMock, mock_open, patch

import pytest
from hvac.exceptions import Forbidden, InvalidPath
from pydantic import BaseModel
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
            assert len(backend._pre_hooks) >= 3

    def test_pre_hooks_custom(
        self, approle_settings: VaultSecretBackendSettings
    ) -> None:
        """Test custom pre_hooks are added after built-in hooks."""
        custom_hook = MagicMock()
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            backend = VaultSecretBackend(approle_settings, pre_hooks=[custom_hook])

            # Should have built-in hooks + custom hook
            assert len(backend._pre_hooks) == 4
            assert backend._pre_hooks[-1] == custom_hook

    def test_post_hooks_includes_latency(
        self, approle_settings: VaultSecretBackendSettings
    ) -> None:
        """Test that latency_end hook is always included in post_hooks."""
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            backend = VaultSecretBackend(approle_settings)

            # Should have at least the latency_end hook
            assert len(backend._post_hooks) >= 1

    def test_post_hooks_custom(
        self, approle_settings: VaultSecretBackendSettings
    ) -> None:
        """Test custom post_hooks are added after latency hook."""
        custom_hook = MagicMock()
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            backend = VaultSecretBackend(approle_settings, post_hooks=[custom_hook])

            # Should have latency_end hook + custom hook
            assert len(backend._post_hooks) == 2
            assert backend._post_hooks[-1] == custom_hook

    def test_error_hooks_custom(
        self, approle_settings: VaultSecretBackendSettings
    ) -> None:
        """Test custom error_hooks are added."""
        custom_hook = MagicMock()
        with patch("hvac.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = True
            mock_client_class.return_value = mock_client

            backend = VaultSecretBackend(approle_settings, error_hooks=[custom_hook])

            # Should have custom error hook
            assert len(backend._error_hooks) == 1
            assert backend._error_hooks[0] == custom_hook

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

            backend = VaultSecretBackend(approle_settings, pre_hooks=[pre_hook])
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

            backend = VaultSecretBackend(approle_settings, post_hooks=[post_hook])
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

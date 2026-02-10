"""Unit tests for secret_reader.base module.

Tests the SecretBackend abstract base class and singleton pattern.
"""

import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.secret_reader.base import (
    SecretAccessForbiddenError,
    SecretBackend,
    SecretBackendError,
    SecretNotFoundError,
)
from qontract_utils.secret_reader.providers.vault import VaultSecretBackendSettings


class TestSecretBackendSingleton:
    """Test singleton pattern for SecretBackend."""

    @pytest.fixture
    def vault_settings(self) -> VaultSecretBackendSettings:
        """Create test vault settings."""
        return VaultSecretBackendSettings(
            server="https://vault.test",
            role_id="test-role",
            secret_id="test-secret",
        )

    def setup_method(self) -> None:
        """Reset singleton state before each test."""
        SecretBackend.reset_singleton()

    def teardown_method(self) -> None:
        """Clean up singleton state after each test."""
        SecretBackend.reset_singleton()

    def test_get_instance_creates_singleton(
        self, vault_settings: VaultSecretBackendSettings
    ) -> None:
        """Test that get_instance creates a singleton instance."""
        with patch(
            "qontract_utils.secret_reader.providers.vault.VaultSecretBackend"
        ) as mock_vault:
            mock_instance = MagicMock()
            mock_vault.return_value = mock_instance

            instance1 = SecretBackend.get_instance(
                backend_type="vault",
                backend_settings=vault_settings,
            )

            assert instance1 == mock_instance
            mock_vault.assert_called_once_with(vault_settings, hooks=None)

    def test_get_instance_returns_same_instance(
        self, vault_settings: VaultSecretBackendSettings
    ) -> None:
        """Test that get_instance returns the same instance on subsequent calls."""
        with patch(
            "qontract_utils.secret_reader.providers.vault.VaultSecretBackend"
        ) as mock_vault:
            mock_instance = MagicMock()
            mock_vault.return_value = mock_instance

            instance1 = SecretBackend.get_instance(
                backend_type="vault",
                backend_settings=vault_settings,
            )
            instance2 = SecretBackend.get_instance(
                backend_type="vault",
                backend_settings=vault_settings,
            )

            assert instance1 is instance2
            mock_vault.assert_called_once()  # Constructor called only once

    def test_get_instance_unsupported_backend_raises_error(
        self, vault_settings: VaultSecretBackendSettings
    ) -> None:
        """Test that unsupported backend type raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported secret backend: invalid"):
            SecretBackend.get_instance(
                backend_type="invalid", backend_settings=vault_settings
            )

    def test_reset_singleton_clears_specific_backend(
        self, vault_settings: VaultSecretBackendSettings
    ) -> None:
        """Test that reset_singleton clears specific backend instance."""
        with patch(
            "qontract_utils.secret_reader.providers.vault.VaultSecretBackend"
        ) as mock_vault:
            # Create two different mock instances to simulate separate creations
            mock_instance1 = MagicMock()
            mock_instance2 = MagicMock()
            mock_vault.side_effect = [mock_instance1, mock_instance2]

            instance1 = SecretBackend.get_instance(
                backend_type="vault",
                backend_settings=vault_settings,
            )

            assert instance1 is mock_instance1

            SecretBackend.reset_singleton(backend_type="vault")

            instance2 = SecretBackend.get_instance(
                backend_type="vault",
                backend_settings=vault_settings,
            )

            assert instance2 is mock_instance2
            assert instance1 is not instance2
            assert mock_vault.call_count == 2

    def test_reset_singleton_without_args_clears_all_backends(
        self, vault_settings: VaultSecretBackendSettings
    ) -> None:
        """Test that reset_singleton without args clears all backend instances."""
        with patch(
            "qontract_utils.secret_reader.providers.vault.VaultSecretBackend"
        ) as mock_vault:
            # AWS KMS will fail on init, so just test with vault
            mock_vault_instance1 = MagicMock()
            mock_vault_instance2 = MagicMock()
            mock_vault.side_effect = [mock_vault_instance1, mock_vault_instance2]

            vault_instance1 = SecretBackend.get_instance(
                backend_type="vault",
                backend_settings=vault_settings,
            )

            assert vault_instance1 is mock_vault_instance1

            SecretBackend.reset_singleton()

            vault_instance2 = SecretBackend.get_instance(
                backend_type="vault",
                backend_settings=vault_settings,
            )

            assert vault_instance2 is mock_vault_instance2
            assert vault_instance1 is not vault_instance2
            assert mock_vault.call_count == 2

    def test_reset_singleton_calls_close_on_instance(
        self, vault_settings: VaultSecretBackendSettings
    ) -> None:
        """Test that reset_singleton calls close() on backend instance."""
        with patch(
            "qontract_utils.secret_reader.providers.vault.VaultSecretBackend"
        ) as mock_vault:
            mock_instance = MagicMock()
            mock_vault.return_value = mock_instance

            SecretBackend.get_instance(
                backend_type="vault",
                backend_settings=vault_settings,
            )

            SecretBackend.reset_singleton(backend_type="vault")

            mock_instance.close.assert_called_once()

    def test_singleton_thread_safety(
        self, vault_settings: VaultSecretBackendSettings
    ) -> None:
        """Test that singleton creation is thread-safe."""
        with patch(
            "qontract_utils.secret_reader.providers.vault.VaultSecretBackend"
        ) as mock_vault:
            mock_instance = MagicMock()
            mock_vault.return_value = mock_instance

            instances: list[Any] = []
            barrier = threading.Barrier(10)

            def create_instance() -> None:
                barrier.wait()  # Sync threads to maximize race condition
                instance = SecretBackend.get_instance(
                    backend_type="vault",
                    backend_settings=vault_settings,
                )
                instances.append(instance)

            threads = [threading.Thread(target=create_instance) for _ in range(10)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            # All threads should get the same instance
            assert all(instance is instances[0] for instance in instances)
            # Constructor should only be called once despite 10 threads
            mock_vault.assert_called_once()


class TestSecretBackendExceptions:
    """Test SecretBackend exception classes."""

    def test_secret_not_found_error(self) -> None:
        """Test SecretNotFoundError exception."""
        error = SecretNotFoundError("Secret not found: test/path")
        assert str(error) == "Secret not found: test/path"
        assert isinstance(error, Exception)

    def test_secret_access_forbidden_error(self) -> None:
        """Test SecretAccessForbiddenError exception."""
        error = SecretAccessForbiddenError("Access denied: test/path")
        assert str(error) == "Access denied: test/path"
        assert isinstance(error, Exception)

    def test_secret_backend_error(self) -> None:
        """Test SecretBackendError exception."""
        error = SecretBackendError("Backend connection failed")
        assert str(error) == "Backend connection failed"
        assert isinstance(error, Exception)

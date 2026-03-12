from typing import Any
from unittest.mock import MagicMock, patch

import hvac.exceptions
from qontract_utils.secret_reader.providers.vault import (
    VaultSecretBackend,
    VaultSecretBackendSettings,
)


@patch("qontract_utils.secret_reader.providers.vault.hvac.Client")
@patch("qontract_utils.secret_reader.providers.vault.time.sleep")
def test_auto_refresh_loop_renew_success(
    mock_sleep: MagicMock, mock_hvac_client_class: MagicMock
) -> None:
    """Test that the auto-refresh loop successfully renews the token."""
    mock_client = MagicMock()
    mock_hvac_client_class.return_value = mock_client

    settings = VaultSecretBackendSettings(
        server="http://vault", kube_auth_role="role", auto_refresh=False
    )

    # Use a dummy token to avoid the file read in _authenticate
    with patch("pathlib.Path.read_text", return_value="dummy_jwt"):
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


@patch("qontract_utils.secret_reader.providers.vault.hvac.Client")
@patch("qontract_utils.secret_reader.providers.vault.time.sleep")
def test_auto_refresh_loop_renew_failure_fallback(
    mock_sleep: MagicMock, mock_hvac_client_class: MagicMock
) -> None:
    """Test that the auto-refresh loop falls back to login if renew fails."""
    mock_client = MagicMock()
    # Make renew_self fail
    mock_client.auth.token.renew_self.side_effect = hvac.exceptions.VaultError(
        "Token expired"
    )
    mock_hvac_client_class.return_value = mock_client

    settings = VaultSecretBackendSettings(
        server="http://vault", kube_auth_role="role", auto_refresh=False
    )

    with patch("pathlib.Path.read_text", return_value="dummy_jwt"):
        backend = VaultSecretBackend(settings)

    backend._closed = False

    counter = 0

    def side_effect(*_args: Any, **_kwargs: Any) -> None:
        nonlocal counter
        if counter > 0:
            backend._closed = True
        counter += 1

    mock_sleep.side_effect = side_effect

    # We must patch pathlib again because _authenticate will be called in the fallback
    with patch("pathlib.Path.read_text", return_value="dummy_jwt"):
        backend._auto_refresh_loop()

    # Verify renew was attempted, but failed, so login was called again
    mock_client.auth.token.renew_self.assert_called_once()
    assert mock_client.auth.kubernetes.login.call_count == 2  # Init + Fallback

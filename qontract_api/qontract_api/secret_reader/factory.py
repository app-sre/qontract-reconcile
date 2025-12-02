"""Secret backend factory.

Provides get_secret_backend() factory for creating SecretBackend instances.
Environment variable backend for development mode.
"""

from qontract_utils.secret_reader.base import SecretBackend

from qontract_api.config import settings


def get_secret_backend() -> SecretBackend:
    """Get secret backend instance.

    Creates SecretBackend singleton based on settings.
    In production: Vault with AppRole or Kubernetes auth.
    In development: Falls back to environment variables.

    Returns:
        SecretBackend instance
    """
    return SecretBackend.get_instance(
        backend_type=settings.secrets.backend_type,
        server=settings.secrets.vault_server,
        role_id=settings.secrets.vault_role_id or None,
        secret_id=settings.secrets.vault_secret_id or None,
        kube_auth_role=settings.secrets.vault_kube_auth_role or None,
        kube_auth_mount=settings.secrets.vault_kube_auth_mount,
        kube_sa_token_path=settings.secrets.vault_kube_sa_token_path,
        auto_refresh=settings.secrets.vault_auto_refresh,
    )

"""Secret Manager factory."""

from qontract_utils.secret_reader.base import SecretBackend

from qontract_api.cache import CacheBackend
from qontract_api.config import settings
from qontract_api.secret_manager._base import SecretManager


def get_secret_manager(cache: CacheBackend) -> SecretManager:
    # TODO: hooks!!!
    secret_backend = SecretBackend.get_instance(
        backend_type=settings.secrets.backend_type,
        server=settings.secrets.vault_server,
        role_id=settings.secrets.vault_role_id or None,
        secret_id=settings.secrets.vault_secret_id or None,
        kube_auth_role=settings.secrets.vault_kube_auth_role or None,
        kube_auth_mount=settings.secrets.vault_kube_auth_mount,
        kube_sa_token_path=settings.secrets.vault_kube_sa_token_path,
        auto_refresh=settings.secrets.vault_auto_refresh,
    )
    return SecretManager(cache=cache, secret_backend=secret_backend)

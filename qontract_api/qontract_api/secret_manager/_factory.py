"""Secret Manager factory."""

from qontract_utils.secret_reader.base import SecretBackend

from qontract_api.cache import CacheBackend
from qontract_api.config import settings
from qontract_api.secret_manager._base import SecretManager


def get_secret_manager(cache: CacheBackend) -> SecretManager:
    secret_backends = []
    for provider in settings.secrets.providers:
        # TODO: hooks!!!
        match provider.backend_type:
            case "vault":
                from qontract_utils.secret_reader.providers.vault import (  # noqa: PLC0415
                    VaultSecretBackendSettings,
                )

                secret_backends.append(
                    SecretBackend.get_instance(
                        backend_type="vault",
                        backend_settings=VaultSecretBackendSettings(
                            server=provider.url,
                            role_id=provider.role_id,
                            secret_id=provider.secret_id,
                            kube_auth_role=provider.kube_auth_role,
                            kube_auth_mount=provider.kube_auth_mount,
                            kube_sa_token_path=provider.kube_sa_token_path,
                            auto_refresh=provider.auto_refresh,
                        ),
                    )
                )
            case _:
                msg = f"Unsupported secret backend: {provider.backend_type}"
                raise ValueError(msg)

    return SecretManager(cache=cache, secret_backends=secret_backends)

from reconcile.external_resources.model import ExternalResourcesInventory
from reconcile.external_resources.secrets_sync import VaultSecretsReconciler
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.external_resources import get_namespaces, get_settings
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "external_resources_secrets_sync"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def run(dry_run: bool, thread_pool_size: int) -> None:
    """Integration that syncs External Resources Outputs Secrets from Vault into
    the target clusters
    """
    vault_settings = get_app_interface_vault_settings()
    secrets_reader = create_secret_reader(use_vault=vault_settings.vault)
    er_settings = get_settings()[0]
    namespaces = [ns for ns in get_namespaces() if ns.external_resources]
    er_inventory = ExternalResourcesInventory(namespaces)

    reconciler = VaultSecretsReconciler(
        ri=ResourceInventory(),
        secrets_reader=secrets_reader,
        vault_path=er_settings.vault_secrets_path,
        thread_pool_size=thread_pool_size,
        dry_run=dry_run,
    )
    reconciler.sync_secrets(er_inventory.values())

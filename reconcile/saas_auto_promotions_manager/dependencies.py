from typing import Self

from reconcile.openshift_saas_deploy import (
    QONTRACT_INTEGRATION as OPENSHIFT_SAAS_DEPLOY,
)
from reconcile.saas_auto_promotions_manager.meta import QONTRACT_INTEGRATION
from reconcile.saas_auto_promotions_manager.utils.saas_files_inventory import (
    SaasFilesInventory,
)
from reconcile.typed_queries.app_interface_repo_url import get_app_interface_repo_url
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.github_orgs import get_github_orgs
from reconcile.typed_queries.gitlab_instances import get_gitlab_instances
from reconcile.typed_queries.saas_files import get_saas_files
from reconcile.utils.promotion_state import PromotionState
from reconcile.utils.secret_reader import SecretReaderBase, create_secret_reader
from reconcile.utils.state import State, init_state
from reconcile.utils.unleash import get_feature_toggle_state
from reconcile.utils.vcs import VCS


class Dependencies:
    """
    Dependencies class to hold all the external dependencies (API clients, state, etc.) for SAPM.
    Dependency inversion simplifies setting up tests and centralizes dependency management.
    """

    def __init__(
        self,
        secret_reader: SecretReaderBase,
        deployment_state: PromotionState,
        vcs: VCS,
        saas_file_inventory: SaasFilesInventory,
        saas_deploy_state: State,
        sapm_state: State,
    ):
        self.secret_reader = secret_reader
        self.deployment_state = deployment_state
        self.vcs = vcs
        self.saas_file_inventory = saas_file_inventory
        self.saas_deploy_state = saas_deploy_state
        self.sapm_state = sapm_state

    @classmethod
    def create(
        cls,
        dry_run: bool,
        thread_pool_size: int,
        env_name: str | None = None,
        app_name: str | None = None,
    ) -> Self:
        vault_settings = get_app_interface_vault_settings()
        allow_deleting_mrs = get_feature_toggle_state(
            integration_name=f"{QONTRACT_INTEGRATION}-allow-deleting-mrs",
            default=False,
        )
        allow_opening_mrs = get_feature_toggle_state(
            integration_name=f"{QONTRACT_INTEGRATION}-allow-opening-mrs",
            default=False,
        )
        secret_reader = create_secret_reader(use_vault=vault_settings.vault)
        vcs = VCS(
            secret_reader=secret_reader,
            github_orgs=get_github_orgs(),
            gitlab_instances=get_gitlab_instances(),
            app_interface_repo_url=get_app_interface_repo_url(),
            dry_run=dry_run,
            allow_deleting_mrs=allow_deleting_mrs,
            allow_opening_mrs=allow_opening_mrs,
        )
        saas_files = get_saas_files(env_name=env_name, app_name=app_name)
        saas_inventory = SaasFilesInventory(
            saas_files=saas_files,
            secret_reader=secret_reader,
            thread_pool_size=thread_pool_size,
        )
        saas_deploy_state = init_state(
            integration=OPENSHIFT_SAAS_DEPLOY, secret_reader=secret_reader
        )
        deployment_state = PromotionState(
            state=saas_deploy_state,
        )
        sapm_state = init_state(
            integration=QONTRACT_INTEGRATION, secret_reader=secret_reader
        )
        return cls(
            secret_reader=secret_reader,
            deployment_state=deployment_state,
            vcs=vcs,
            saas_file_inventory=saas_inventory,
            saas_deploy_state=saas_deploy_state,
            sapm_state=sapm_state,
        )

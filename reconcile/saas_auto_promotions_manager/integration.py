from collections.abc import Callable
from typing import Optional

from sretoolbox.utils import threaded

from reconcile.openshift_saas_deploy import (
    QONTRACT_INTEGRATION as OPENSHIFT_SAAS_DEPLOY,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request_manager import (
    MergeRequestManager,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    Renderer,
)
from reconcile.saas_auto_promotions_manager.publisher import Publisher
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber
from reconcile.saas_auto_promotions_manager.utils.saas_files_inventory import (
    SaasFilesInventory,
)
from reconcile.saas_auto_promotions_manager.utils.vcs import VCS
from reconcile.typed_queries.app_interface_repo_url import get_app_interface_repo_url
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.github_orgs import get_github_orgs
from reconcile.typed_queries.gitlab_instances import get_gitlab_instances
from reconcile.typed_queries.saas_files import get_saas_files
from reconcile.utils.defer import defer
from reconcile.utils.promotion_state import PromotionState
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.state import init_state
from reconcile.utils.unleash import get_feature_toggle_state

QONTRACT_INTEGRATION = "saas-auto-promotions-manager"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class SaasAutoPromotionsManager:
    def __init__(
        self,
        deployment_state: PromotionState,
        vcs: VCS,
        saas_file_inventory: SaasFilesInventory,
        merge_request_manager: MergeRequestManager,
        thread_pool_size: int,
        dry_run: bool,
    ):
        self._deployment_state = deployment_state
        self._vcs = vcs
        self._saas_file_inventory = saas_file_inventory
        self._merge_request_manager = merge_request_manager
        self._thread_pool_size = thread_pool_size
        self._dry_run = dry_run

    def _fetch_publisher_state(
        self,
        publisher: Publisher,
    ) -> None:
        publisher.fetch_commit_shas_and_deployment_info(
            vcs=self._vcs,
            deployment_state=self._deployment_state,
        )

    def _fetch_publisher_real_world_states(self) -> None:
        threaded.run(
            self._fetch_publisher_state,
            self._saas_file_inventory.publishers,
            thread_pool_size=self._thread_pool_size,
        )

    def _compute_desired_subscriber_states(self) -> None:
        for subscriber in self._saas_file_inventory.subscribers:
            subscriber.compute_desired_state()

    def _get_subscribers_with_diff(self) -> list[Subscriber]:
        return [s for s in self._saas_file_inventory.subscribers if s.has_diff()]

    def reconcile(self) -> None:
        self._deployment_state.cache_commit_shas_from_s3()
        self._fetch_publisher_real_world_states()
        self._compute_desired_subscriber_states()
        subscribers_with_diff = self._get_subscribers_with_diff()
        self._merge_request_manager.fetch_sapm_managed_open_merge_requests()
        self._merge_request_manager.housekeeping()
        self._merge_request_manager.create_promotion_merge_requests(
            subscribers=subscribers_with_diff
        )


def init_external_dependencies(
    dry_run: bool,
) -> tuple[PromotionState, VCS, SaasFilesInventory, MergeRequestManager]:
    """
    Lets initialize everything that involves calls to external dependencies:
    - VCS -> Gitlab / Github queries
    - SaaSFileInventory -> qontract-server GQL query
    - DeploymentState -> S3 queries
    - MergeRequestManager -> Managing SAPM MRs with app-interface
    """
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
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=Renderer(),
    )
    saas_files = get_saas_files()
    saas_inventory = SaasFilesInventory(saas_files=saas_files)
    deployment_state = PromotionState(
        state=init_state(integration=OPENSHIFT_SAAS_DEPLOY, secret_reader=secret_reader)
    )
    return deployment_state, vcs, saas_inventory, merge_request_manager


@defer
def run(
    dry_run: bool,
    thread_pool_size: int,
    defer: Optional[Callable] = None,
) -> None:
    (
        deployment_state,
        vcs,
        saas_inventory,
        merge_request_manager,
    ) = init_external_dependencies(dry_run=dry_run)
    if defer:
        defer(vcs.cleanup)

    integration = SaasAutoPromotionsManager(
        deployment_state=deployment_state,
        vcs=vcs,
        saas_file_inventory=saas_inventory,
        merge_request_manager=merge_request_manager,
        thread_pool_size=thread_pool_size,
        dry_run=dry_run,
    )

    integration.reconcile()

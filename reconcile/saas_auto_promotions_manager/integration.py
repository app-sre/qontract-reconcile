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
from reconcile.saas_auto_promotions_manager.subscriber import (
    ConfigHash,
    Subscriber,
)
from reconcile.saas_auto_promotions_manager.utils.deployment_state import (
    DeploymentState,
)
from reconcile.saas_auto_promotions_manager.utils.saas_files_inventory import (
    SaasFilesInventory,
)
from reconcile.saas_auto_promotions_manager.utils.vcs import VCS
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.github_orgs import get_github_orgs
from reconcile.typed_queries.gitlab_instances import get_gitlab_instances
from reconcile.typed_queries.saas_files_for_auto_promotions import (
    get_saas_files_for_auto_promotions,
)
from reconcile.utils.defer import defer
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.state import init_state

QONTRACT_INTEGRATION = "saas-auto-promotions-manager"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class SaasAutoPromotionsManager:
    def __init__(
        self,
        deployment_state: DeploymentState,
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
        subscribers_with_diff: list[Subscriber] = []
        for subscriber in self._saas_file_inventory.subscribers:
            current_hashes: list[ConfigHash] = []
            for s in subscriber.config_hashes_by_channel_name.values():
                for el in s:
                    current_hashes.append(el)
            if (
                set(subscriber.desired_hashes) == set(current_hashes)
                and subscriber.desired_ref == subscriber.ref
            ):
                # There is no change that requires a promotion
                continue
            subscribers_with_diff.append(subscriber)
        return subscribers_with_diff

    def reconcile(self) -> None:
        self._fetch_publisher_real_world_states()
        self._compute_desired_subscriber_states()
        subscribers_with_diff = self._get_subscribers_with_diff()
        self._merge_request_manager.fetch_sapm_managed_open_merge_requests()
        self._merge_request_manager.housekeeping()
        for subscriber in subscribers_with_diff:
            self._merge_request_manager.process_subscriber(subscriber=subscriber)


def init_external_dependencies(
    dry_run: bool,
) -> tuple[DeploymentState, VCS, SaasFilesInventory, MergeRequestManager]:
    """
    Lets initialize everything that involves calls to external dependencies:
    - VCS -> Gitlab / Github queries
    - SaaSFileInventory -> qontract-server GQL query
    - DeploymentState -> S3 queries
    - MergeRequestManager -> Managing SAPM MRs with app-interface
    """
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    gitlab_instances = get_gitlab_instances()
    vcs = VCS(
        secret_reader=secret_reader,
        github_orgs=get_github_orgs(),
        gitlab_instances=gitlab_instances,
        dry_run=dry_run,
    )
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=Renderer(),
    )
    saas_files = get_saas_files_for_auto_promotions()
    saas_inventory = SaasFilesInventory(saas_files=saas_files)
    deployment_state = DeploymentState(
        state=init_state(integration=OPENSHIFT_SAAS_DEPLOY, secret_reader=secret_reader)
    )
    return deployment_state, vcs, saas_inventory, merge_request_manager


@defer
def run(
    dry_run: bool,
    thread_pool_size: int,
    defer: Optional[Callable] = None,
) -> None:
    # TODO: We enforce dry-run for now for testing period
    dry_run = True
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

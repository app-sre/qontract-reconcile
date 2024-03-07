from collections.abc import Callable
from typing import Optional

from sretoolbox.utils import threaded

from reconcile.openshift_saas_deploy import (
    QONTRACT_INTEGRATION as OPENSHIFT_SAAS_DEPLOY,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request_manager_v2 import (
    MergeRequestManagerV2,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.mr_parser import (
    MRParser,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.reconciler import (
    Reconciler,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    Renderer,
)
from reconcile.saas_auto_promotions_manager.publisher import Publisher
from reconcile.saas_auto_promotions_manager.s3_exporter import S3Exporter
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber
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
from reconcile.utils.defer import defer
from reconcile.utils.promotion_state import PromotionState
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.state import State, init_state
from reconcile.utils.unleash import get_feature_toggle_state
from reconcile.utils.vcs import VCS

QONTRACT_INTEGRATION = "saas-auto-promotions-manager"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class SaasAutoPromotionsManager:
    def __init__(
        self,
        deployment_state: PromotionState,
        vcs: VCS,
        saas_file_inventory: SaasFilesInventory,
        merge_request_manager_v2: MergeRequestManagerV2,
        s3_exporter: S3Exporter,
        thread_pool_size: int,
        dry_run: bool,
    ):
        self._deployment_state = deployment_state
        self._vcs = vcs
        self._saas_file_inventory = saas_file_inventory
        self._merge_request_manager_v2 = merge_request_manager_v2
        self._s3_exporter = s3_exporter
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
        self._merge_request_manager_v2.reconcile(subscribers=subscribers_with_diff)
        self._s3_exporter.export_publisher_data(
            publishers=self._saas_file_inventory.publishers
        )


def init_external_dependencies(
    dry_run: bool,
    env_name: Optional[str] = None,
    app_name: Optional[str] = None,
) -> tuple[
    PromotionState,
    VCS,
    SaasFilesInventory,
    MergeRequestManagerV2,
    S3Exporter,
    State,
    State,
]:
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
    mr_parser = MRParser(vcs=vcs)
    merge_request_manager_v2 = MergeRequestManagerV2(
        vcs=vcs,
        reconciler=Reconciler(),
        mr_parser=mr_parser,
        renderer=Renderer(),
    )
    saas_files = get_saas_files(env_name=env_name, app_name=app_name)
    saas_inventory = SaasFilesInventory(saas_files=saas_files)
    saas_deploy_state = init_state(
        integration=OPENSHIFT_SAAS_DEPLOY, secret_reader=secret_reader
    )
    deployment_state = PromotionState(
        state=saas_deploy_state,
    )
    sapm_state = init_state(
        integration=QONTRACT_INTEGRATION, secret_reader=secret_reader
    )
    s3_exporter = S3Exporter(
        state=sapm_state,
        dry_run=dry_run,
    )
    return (
        deployment_state,
        vcs,
        saas_inventory,
        merge_request_manager_v2,
        s3_exporter,
        saas_deploy_state,
        sapm_state,
    )


@defer
def run(
    dry_run: bool,
    thread_pool_size: int,
    env_name: Optional[str] = None,
    app_name: Optional[str] = None,
    defer: Optional[Callable] = None,
) -> None:
    (
        deployment_state,
        vcs,
        saas_inventory,
        merge_request_manager_v2,
        s3_exporter,
        saas_deploy_state,
        sapm_state,
    ) = init_external_dependencies(
        dry_run=dry_run, env_name=env_name, app_name=app_name
    )
    if defer:
        defer(vcs.cleanup)
        defer(saas_deploy_state.cleanup)
        defer(sapm_state.cleanup)

    integration = SaasAutoPromotionsManager(
        deployment_state=deployment_state,
        vcs=vcs,
        saas_file_inventory=saas_inventory,
        merge_request_manager_v2=merge_request_manager_v2,
        s3_exporter=s3_exporter,
        thread_pool_size=thread_pool_size,
        dry_run=dry_run,
    )

    integration.reconcile()

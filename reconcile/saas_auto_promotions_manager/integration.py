from collections.abc import Callable

from sretoolbox.utils import threaded

from reconcile.saas_auto_promotions_manager.dependencies import Dependencies
from reconcile.saas_auto_promotions_manager.merge_request_manager.batcher import Batcher
from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request_manager_v2 import (
    MergeRequestManagerV2,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.mr_parser import (
    MRParser,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    Renderer,
)
from reconcile.saas_auto_promotions_manager.meta import QONTRACT_INTEGRATION
from reconcile.saas_auto_promotions_manager.publisher import Publisher
from reconcile.saas_auto_promotions_manager.s3_exporter import S3Exporter
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber
from reconcile.utils.defer import defer
from reconcile.utils.promotion_state import PromotionState
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.vcs import VCS


class SaasAutoPromotionsManagerParams(PydanticRunParams):
    thread_pool_size: int
    env_name: str | None
    app_name: str | None


class SaasAutoPromotionsManager(
    QontractReconcileIntegration[SaasAutoPromotionsManagerParams]
):
    def _fetch_publisher_state(
        self,
        publisher: Publisher,
        vcs: VCS,
        deployment_state: PromotionState,
    ) -> None:
        publisher.fetch_commit_shas_and_deployment_info(
            vcs=vcs,
            deployment_state=deployment_state,
        )

    def _fetch_publisher_real_world_states(
        self, dependencies: Dependencies, thread_pool_size: int
    ) -> None:
        threaded.run(
            lambda publisher: self._fetch_publisher_state(
                publisher,
                dependencies.vcs,
                dependencies.deployment_state,
            ),
            dependencies.saas_file_inventory.publishers,
            thread_pool_size=thread_pool_size,
        )

    def _compute_desired_subscriber_states(self, dependencies: Dependencies) -> None:
        for subscriber in dependencies.saas_file_inventory.subscribers:
            subscriber.compute_desired_state()

    def _get_subscribers_with_diff(
        self, dependencies: Dependencies
    ) -> list[Subscriber]:
        return [s for s in dependencies.saas_file_inventory.subscribers if s.has_diff()]

    def reconcile(
        self, dependencies: Dependencies, thread_pool_size: int, dry_run: bool
    ) -> None:
        dependencies.deployment_state.cache_commit_shas_from_s3()
        self._fetch_publisher_real_world_states(dependencies, thread_pool_size)
        self._compute_desired_subscriber_states(dependencies)
        subscribers_with_diff = self._get_subscribers_with_diff(dependencies)

        mr_parser = MRParser(vcs=dependencies.vcs)
        merge_request_manager_v2 = MergeRequestManagerV2(
            vcs=dependencies.vcs,
            reconciler=Batcher(),
            mr_parser=mr_parser,
            renderer=Renderer(),
        )
        merge_request_manager_v2.reconcile(subscribers=subscribers_with_diff)

        s3_exporter = S3Exporter(
            state=dependencies.sapm_state,
            dry_run=dry_run,
        )
        s3_exporter.export_publisher_data(
            publishers=dependencies.saas_file_inventory.publishers
        )

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    @defer
    def run(
        self,
        dry_run: bool,
        defer: Callable | None = None,
    ) -> None:
        deps = Dependencies.create(
            dry_run=dry_run,
            thread_pool_size=self.params.thread_pool_size,
            env_name=self.params.env_name,
            app_name=self.params.app_name,
        )
        if defer:
            defer(deps.vcs.cleanup)
            defer(deps.saas_deploy_state.cleanup)
            defer(deps.sapm_state.cleanup)
        self.reconcile(
            deps, thread_pool_size=self.params.thread_pool_size, dry_run=dry_run
        )

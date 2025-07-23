from __future__ import annotations

from typing import TYPE_CHECKING

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
from reconcile.saas_auto_promotions_manager.s3_exporter import S3Exporter
from reconcile.utils.defer import defer
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from reconcile.saas_auto_promotions_manager.publisher import Publisher
    from reconcile.saas_auto_promotions_manager.subscriber import Subscriber


class SaasAutoPromotionsManagerParams(PydanticRunParams):
    thread_pool_size: int
    env_name: str | None
    app_name: str | None


class SaasAutoPromotionsManager(
    QontractReconcileIntegration[SaasAutoPromotionsManagerParams]
):
    @classmethod
    def create(
        cls,
        dry_run: bool,
        thread_pool_size: int,
        env_name: str | None = None,
        app_name: str | None = None,
    ) -> SaasAutoPromotionsManager:
        dependencies = Dependencies.create(
            dry_run=dry_run,
            thread_pool_size=thread_pool_size,
            env_name=env_name,
            app_name=app_name,
        )
        params = SaasAutoPromotionsManagerParams(
            thread_pool_size=thread_pool_size,
            env_name=env_name,
            app_name=app_name,
        )
        return cls(dependencies=dependencies, params=params)

    def __init__(
        self, dependencies: Dependencies, params: SaasAutoPromotionsManagerParams
    ):
        super().__init__(params)
        self._dependencies = dependencies

    def _fetch_publisher_state(
        self,
        publisher: Publisher,
    ) -> None:
        publisher.fetch_commit_shas_and_deployment_info(
            vcs=self._dependencies.vcs,
            deployment_state=self._dependencies.deployment_state,
        )

    def _fetch_publisher_real_world_states(self, thread_pool_size: int) -> None:
        threaded.run(
            self._fetch_publisher_state,
            self._dependencies.saas_file_inventory.publishers,
            thread_pool_size=thread_pool_size,
        )

    def _compute_desired_subscriber_states(self) -> None:
        for subscriber in self._dependencies.saas_file_inventory.subscribers:
            subscriber.compute_desired_state()

    def _get_subscribers_with_diff(self) -> list[Subscriber]:
        return [
            s
            for s in self._dependencies.saas_file_inventory.subscribers
            if s.has_diff()
        ]

    def reconcile(self, thread_pool_size: int, dry_run: bool) -> None:
        self._dependencies.deployment_state.cache_commit_shas_from_s3()
        self._fetch_publisher_real_world_states(thread_pool_size)
        self._compute_desired_subscriber_states()
        subscribers_with_diff = self._get_subscribers_with_diff()

        mr_parser = MRParser(vcs=self._dependencies.vcs)
        merge_request_manager_v2 = MergeRequestManagerV2(
            vcs=self._dependencies.vcs,
            reconciler=Batcher(),
            mr_parser=mr_parser,
            renderer=Renderer(),
        )
        merge_request_manager_v2.reconcile(subscribers=subscribers_with_diff)

        s3_exporter = S3Exporter(
            state=self._dependencies.sapm_state,
            dry_run=dry_run,
        )
        s3_exporter.export_publisher_data(
            publishers=self._dependencies.saas_file_inventory.publishers
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
        if defer:
            defer(self._dependencies.vcs.cleanup)
            defer(self._dependencies.saas_deploy_state.cleanup)
            defer(self._dependencies.sapm_state.cleanup)
        self.reconcile(thread_pool_size=self.params.thread_pool_size, dry_run=dry_run)

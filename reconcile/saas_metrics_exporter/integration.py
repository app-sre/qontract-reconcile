from collections.abc import Callable
from dataclasses import dataclass

from sretoolbox.utils import threaded

from reconcile.saas_metrics_exporter.channel import Channel, SaasTarget, build_channels
from reconcile.saas_metrics_exporter.metrics import SaasCommitDistanceGauge
from reconcile.typed_queries.app_interface_repo_url import get_app_interface_repo_url
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.github_orgs import get_github_orgs
from reconcile.typed_queries.gitlab_instances import get_gitlab_instances
from reconcile.typed_queries.saas_files import get_saas_files
from reconcile.utils import metrics
from reconcile.utils.defer import defer
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.vcs import VCS

QONTRACT_INTEGRATION = "saas_metrics_exporter"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)
QONTRACT_TF_PREFIX = "qrsme"


@dataclass
class Distance:
    publisher: SaasTarget
    subscriber: SaasTarget
    channel: Channel
    distance: int = 0


class SaasMetricsExporterParams(PydanticRunParams):
    thread_pool_size: int
    env_name: str | None
    app_name: str | None


class SaasMetricsExporter(QontractReconcileIntegration[SaasMetricsExporterParams]):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION.replace("_", "-")

    def _calculate_commit_distance(self, distance: Distance) -> None:
        if distance.subscriber.ref == distance.publisher.ref:
            return 0

        commits = self._vcs.get_commits_between(
            repo_url=distance.publisher.repo_url,
            auth_code=distance.publisher.auth_code,
            commit_from=distance.subscriber.ref,
            commit_to=distance.publisher.ref,
        )
        distance.distance = len(commits)

    @defer
    def run(
        self,
        dry_run: bool,
        defer: Callable | None = None,
    ) -> None:
        saas_files = get_saas_files(
            env_name=self.params.env_name, app_name=self.params.app_name
        )
        vault_settings = get_app_interface_vault_settings()
        secret_reader = create_secret_reader(use_vault=vault_settings.vault)
        self._vcs = VCS(
            secret_reader=secret_reader,
            github_orgs=get_github_orgs(),
            gitlab_instances=get_gitlab_instances(),
            app_interface_repo_url=get_app_interface_repo_url(),
            dry_run=dry_run,
        )
        if defer:
            defer(self._vcs.cleanup)

        channels = build_channels(saas_files=saas_files)
        distances: list[Distance] = []

        for channel in channels:
            for subscriber in channel.subscribers:
                for publisher in channel.publishers:
                    distances.append(
                        Distance(
                            publisher=publisher,
                            subscriber=subscriber,
                            channel=channel,
                        )
                    )

        threaded.run(
            self._calculate_commit_distance,
            distances,
            thread_pool_size=self.params.thread_pool_size,
        )

        for distance in distances:
            metrics.set_gauge(
                metric=SaasCommitDistanceGauge(
                    channel=distance.channel.name,
                    publisher="",
                    subscriber="",
                ),
                value=float(distance.distance),
            )

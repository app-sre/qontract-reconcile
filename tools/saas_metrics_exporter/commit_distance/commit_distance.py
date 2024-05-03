from collections.abc import Iterable
from dataclasses import dataclass

from sretoolbox.utils import threaded

from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils import metrics
from reconcile.utils.vcs import VCS
from tools.saas_metrics_exporter.commit_distance.channel import (
    Channel,
    SaasTarget,
    build_channels,
)
from tools.saas_metrics_exporter.commit_distance.metrics import SaasCommitDistanceGauge


@dataclass
class Distance:
    publisher: SaasTarget
    subscriber: SaasTarget
    channel: Channel
    distance: int = 0


class CommitDistance:
    def __init__(self, vcs: VCS):
        self._vcs = vcs

    def _calculate_commit_distance(self, distance: Distance) -> None:
        if distance.subscriber.ref == distance.publisher.ref:
            return

        commits = self._vcs.get_commits_between(
            repo_url=distance.publisher.repo_url,
            auth_code=distance.publisher.auth_code,
            commit_from=distance.subscriber.ref,
            commit_to=distance.publisher.ref,
        )
        distance.distance = len(commits)

    def export(self, saas_files: Iterable[SaasFile], thread_pool_size: int) -> None:
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
            thread_pool_size=thread_pool_size,
        )

        for distance in distances:
            metrics.set_gauge(
                metric=SaasCommitDistanceGauge(
                    channel=distance.channel.name,
                    app=distance.publisher.app_name,
                    env=distance.publisher.env_name,
                    publisher=distance.publisher.target_name,
                    publisher_namespace=distance.publisher.namespace_name,
                    subscriber=distance.subscriber.target_name,
                    subscriber_namespace=distance.subscriber.namespace_name,
                ),
                value=float(distance.distance),
            )

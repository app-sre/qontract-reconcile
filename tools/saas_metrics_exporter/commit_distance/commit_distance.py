from collections.abc import Iterable
from dataclasses import dataclass

from sretoolbox.utils import threaded

from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils.secret_reader import HasSecret
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


@dataclass
class CommitDistanceMetric:
    value: float
    metric: SaasCommitDistanceGauge


@dataclass
class ThreadData:
    repo_url: str
    auth_code: HasSecret | None
    ref_from: str
    ref_to: str
    distance: int = 0

    def __hash__(self) -> int:
        return hash((self.repo_url, self.ref_from, self.ref_to))


class CommitDistanceFetcher:
    def __init__(self, vcs: VCS):
        self._vcs = vcs

    def _data_key(self, repo_url: str, ref_from: str, ref_to: str) -> str:
        return f"{repo_url}/{ref_from}/{ref_to}"

    def _calculate_commit_distance(self, data: ThreadData) -> None:
        if data.ref_from == data.ref_to:
            data.distance = 0
            return

        commits = self._vcs.get_commits_between(
            repo_url=data.repo_url,
            auth_code=data.auth_code,
            commit_from=data.ref_from,
            commit_to=data.ref_to,
        )
        data.distance = len(commits)

    def _populate_distances(
        self, distances: Iterable[Distance], thread_data: Iterable[ThreadData]
    ) -> None:
        m = {
            self._data_key(
                repo_url=d.repo_url, ref_from=d.ref_from, ref_to=d.ref_to
            ): d.distance
            for d in thread_data
        }
        for distance in distances:
            distance.distance = m[
                self._data_key(
                    repo_url=distance.publisher.repo_url,
                    ref_from=distance.subscriber.ref,
                    ref_to=distance.publisher.ref,
                )
            ]

    def fetch(
        self, saas_files: Iterable[SaasFile], thread_pool_size: int
    ) -> list[CommitDistanceMetric]:
        channels = build_channels(saas_files=saas_files)
        distances: list[Distance] = []
        thread_data: set[ThreadData] = set()

        for channel in channels:
            for subscriber in channel.subscribers:
                for publisher in channel.publishers:
                    thread_data.add(
                        ThreadData(
                            repo_url=publisher.repo_url,
                            auth_code=publisher.auth_code,
                            ref_from=subscriber.ref,
                            ref_to=publisher.ref,
                        )
                    )
                    distances.append(
                        Distance(
                            publisher=publisher,
                            subscriber=subscriber,
                            channel=channel,
                        )
                    )

        threaded.run(
            self._calculate_commit_distance,
            thread_data,
            thread_pool_size=thread_pool_size,
        )

        self._populate_distances(distances=distances, thread_data=thread_data)

        commit_distance_metrics = [
            CommitDistanceMetric(
                value=float(distance.distance),
                metric=SaasCommitDistanceGauge(
                    channel=distance.channel.name,
                    app=distance.publisher.app_name,
                    publisher=distance.publisher.target_name,
                    publisher_namespace=distance.publisher.namespace_name,
                    subscriber=distance.subscriber.target_name,
                    subscriber_namespace=distance.subscriber.namespace_name,
                ),
            )
            for distance in distances
        ]

        return commit_distance_metrics

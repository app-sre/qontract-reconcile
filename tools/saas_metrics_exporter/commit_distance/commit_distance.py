from collections.abc import Iterable
from dataclasses import dataclass, field

from sretoolbox.utils import threaded

from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils.secret_reader import HasSecret
from reconcile.utils.vcs import VCS
from tools.saas_metrics_exporter.commit_distance.channel import (
    SaasTarget,
    build_channels,
)
from tools.saas_metrics_exporter.commit_distance.metrics import SaasCommitDistanceGauge


@dataclass
class CommitDistanceMetric:
    value: float
    metric: SaasCommitDistanceGauge


@dataclass(frozen=True)
class DistanceKey:
    repo_url: str
    auth_code: HasSecret | None = field(hash=False, compare=False)
    ref_from: str
    ref_to: str


class CommitDistanceFetcher:
    def __init__(self, vcs: VCS):
        self._vcs = vcs

    def _calculate_commit_distance(self, key: DistanceKey) -> tuple[DistanceKey, int]:
        if key.ref_from == key.ref_to:
            return key, 0

        commits = self._vcs.get_commits_between(
            repo_url=key.repo_url,
            auth_code=key.auth_code,
            commit_from=key.ref_from,
            commit_to=key.ref_to,
        )
        return key, len(commits)

    @staticmethod
    def _build_distance_key(
        publisher: SaasTarget, subscriber: SaasTarget
    ) -> DistanceKey:
        return DistanceKey(
            repo_url=publisher.repo_url,
            auth_code=publisher.auth_code,
            ref_from=subscriber.ref,
            ref_to=publisher.ref,
        )

    def fetch(
        self,
        saas_files: Iterable[SaasFile],
        thread_pool_size: int,
    ) -> list[CommitDistanceMetric]:
        channels = build_channels(saas_files=saas_files)

        distance_keys = {
            self._build_distance_key(publisher=publisher, subscriber=subscriber)
            for channel in channels
            for subscriber in channel.subscribers
            for publisher in channel.publishers
        }

        distance_by_key = dict(
            threaded.run(
                self._calculate_commit_distance,
                distance_keys,
                thread_pool_size=thread_pool_size,
            )
        )

        commit_distance_metrics = [
            CommitDistanceMetric(
                value=float(
                    distance_by_key[
                        self._build_distance_key(
                            publisher=publisher,
                            subscriber=subscriber,
                        )
                    ]
                ),
                metric=SaasCommitDistanceGauge(
                    channel=channel.name,
                    app=publisher.app_name,
                    publisher=publisher.target_name,
                    publisher_namespace=publisher.namespace_name,
                    subscriber=subscriber.target_name,
                    subscriber_namespace=subscriber.namespace_name,
                ),
            )
            for channel in channels
            for subscriber in channel.subscribers
            for publisher in channel.publishers
        ]

        return commit_distance_metrics

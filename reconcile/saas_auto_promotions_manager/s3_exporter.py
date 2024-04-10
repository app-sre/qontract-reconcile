from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from reconcile.saas_auto_promotions_manager.publisher import Publisher
from reconcile.utils.state import State


class DeploymentState(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    MISSING = "missing"


@dataclass
class PublisherData:
    commit_sha: str
    deployment_state: DeploymentState

    @staticmethod
    def from_publisher(publisher: Publisher) -> PublisherData:
        """
        Note, this data structure is a bit clumsy for this case, as for historic reasons we store deployment info
        per channel and not per publisher.
        We have a directed graph with n-n relationships, subscriber -> channel -> publisher.
        This makes sense for the auto-promotion calculation, but can be misleading for the export,
        as a publisher holds a deployment info per channel. We can consider the publisher deployment
        state failed, if any of its channels failed.
        """
        deployment_state = DeploymentState.SUCCESS
        failed = False
        missing = False
        for info in publisher.deployment_info_by_channel.values():
            if not info:
                missing = True
            elif not info.success:
                failed = True

        if failed:
            deployment_state = DeploymentState.FAILED
        elif missing:
            deployment_state = DeploymentState.MISSING

        return PublisherData(
            commit_sha=publisher.commit_sha,
            deployment_state=deployment_state,
        )


class S3Exporter:
    """
    Export publisher deployment data to S3.
    """

    def __init__(self, state: State, dry_run: bool = True):
        self._state = state
        self._dry_run = dry_run

    def export_publisher_data(self, publishers: Iterable[Publisher]) -> None:
        data: dict[str, dict] = {}
        for publisher in publishers:
            publisher_data = PublisherData.from_publisher(publisher)
            key = f"{publisher.app_name}/{publisher.saas_name}/{publisher.resource_template_name}/{publisher.target_name}/{publisher.cluster_name}/{publisher.namespace_name}/{publisher.publish_job_logs}"
            data[key] = {
                "commit_sha": publisher_data.commit_sha,
                "deployment_state": publisher_data.deployment_state.value,
            }

        if not self._dry_run:
            self._state.add(
                key="publisher-data.json",
                value=data,
                force=True,
            )

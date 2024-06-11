from dataclasses import dataclass
from datetime import datetime

from reconcile.utils.promotion_state import PromotionState
from reconcile.utils.secret_reader import HasSecret
from reconcile.utils.vcs import VCS


@dataclass
class DeploymentInfo:
    """
    Isolate our logic from utils model.
    Unlike utils, we strictly require saas_file
    and target_config_hash to be set.
    """

    success: bool
    saas_file: str
    target_config_hash: str
    check_in: datetime | None


class Publisher:
    """
    Hold all information about a saas publisher target.
    Contains logic to fetch the current state of a publisher.
    """

    def __init__(
        self,
        ref: str,
        repo_url: str,
        uid: str,
        saas_name: str,
        saas_file_path: str,
        app_name: str,
        namespace_name: str,
        resource_template_name: str,
        target_name: str | None,
        cluster_name: str,
        auth_code: HasSecret | None,
        publish_job_logs: bool | None,
        has_subscriber: bool = True,
    ):
        self._ref = ref
        self._repo_url = repo_url
        self._auth_code = auth_code
        self.channels: set[str] = set()
        self.commit_sha: str = ""
        self.deployment_info_by_channel: dict[str, DeploymentInfo | None] = {}
        self.uid = uid
        self.saas_name = saas_name
        self.saas_file_path = saas_file_path
        self.app_name = app_name
        self.namespace_name = namespace_name
        self.resource_template_name = resource_template_name
        self.target_name = target_name if target_name else "None"
        self.cluster_name = cluster_name
        self.publish_job_logs = bool(publish_job_logs)
        self.has_subscriber = has_subscriber

    def fetch_commit_shas_and_deployment_info(
        self, vcs: VCS, deployment_state: PromotionState
    ) -> None:
        self.commit_sha = vcs.get_commit_sha(
            auth_code=self._auth_code,
            ref=self._ref,
            repo_url=self._repo_url,
        )
        for channel in self.channels:
            self.deployment_info_by_channel[channel] = None
            promotion_data = deployment_state.get_promotion_data(
                sha=self.commit_sha,
                channel=channel,
                target_uid=self.uid,
            )
            if not (
                promotion_data
                and promotion_data.saas_file
                and promotion_data.target_config_hash
            ):
                continue

            check_in = (
                datetime.fromisoformat(promotion_data.check_in)
                if promotion_data.check_in
                else None
            )
            self.deployment_info_by_channel[channel] = DeploymentInfo(
                success=promotion_data.success,
                saas_file=promotion_data.saas_file,
                target_config_hash=promotion_data.target_config_hash,
                check_in=check_in,
            )

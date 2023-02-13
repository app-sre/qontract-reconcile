from collections import defaultdict
from typing import Optional

from pydantic import (
    BaseModel,
    Extra,
)

from reconcile.utils.state import State


class DeploymentInfo(BaseModel):
    """
    A class that strictly corresponds to the json stored in S3
    """

    success: bool
    target_config_hash: str
    saas_file: str

    class Config:
        smart_union = True
        extra = Extra.forbid


class DeploymentState:
    """
    A wrapper around a reconcile.utils.state.State object.
    This is dedicated to retrieving information about
    deployments from S3.
    """

    def __init__(self, state: State):
        self._state = state
        self._commits_by_channel: dict[str, set[str]] = defaultdict(set)
        self._fetch_deployment_list()

    def _fetch_deployment_list(self) -> None:
        all_keys = self._state.ls()
        for commit in all_keys:
            if not commit.startswith("/promotions/"):
                continue
            parts = commit.split("/")
            self._commits_by_channel[parts[2]].add(parts[3])

    def get_deployment_info(self, sha: str, channel: str) -> Optional[DeploymentInfo]:
        if sha not in self._commits_by_channel[channel]:
            return None
        key = f"promotions/{channel}/{sha}"
        data = self._state.get(key)
        return DeploymentInfo(**data)

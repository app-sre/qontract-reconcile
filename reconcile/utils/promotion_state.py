from collections import defaultdict
from typing import Optional

from pydantic import (
    BaseModel,
    Extra,
)

from reconcile.utils.state import State


class PromotionInfo(BaseModel):
    """
    A class that strictly corresponds to the json stored in S3
    """

    success: bool
    target_config_hash: str
    saas_file: str

    class Config:
        smart_union = True
        extra = Extra.forbid


class PromotionState:
    """
    A wrapper around a reconcile.utils.state.State object.
    This is dedicated to storing and retrieving information
    about promotions on S3.
    """

    def __init__(self, state: State):
        self._state = state
        self._commits_by_channel: dict[str, set[str]] = defaultdict(set)
        self._fetch_promotions_list()

    def _fetch_promotions_list(self) -> None:
        all_keys = self._state.ls()
        for commit in all_keys:
            # Format: /promotions/{channel}/{commit-sha}
            if not commit.startswith("/promotions/"):
                continue
            _, _, channel_name, commit_sha = commit.split("/")
            self._commits_by_channel[channel_name].add(commit_sha)

    def get_promotion_info(self, sha: str, channel: str) -> Optional[PromotionInfo]:
        if sha not in self._commits_by_channel[channel]:
            return None
        key = f"promotions/{channel}/{sha}"
        data = self._state.get(key)
        return PromotionInfo(**data)

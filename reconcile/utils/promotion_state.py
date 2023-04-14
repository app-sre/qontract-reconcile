import logging
from collections import defaultdict
from typing import Optional

from pydantic import (
    BaseModel,
    Extra,
)

from reconcile.utils.state import State


class PromotionData(BaseModel):
    """
    A class that strictly corresponds to the json stored in S3.

    Note, that currently we also accomodate for missing
    saas_file and target_config_hash because of saasherder
    requirements.
    """

    success: bool
    target_config_hash: Optional[str]
    saas_file: Optional[str]

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

    def cache_commit_shas_from_s3(self) -> None:
        """
        Caching commit shas locally - this is used
        to lookup locally if a key exists on S3
        before querying.
        """
        all_keys = self._state.ls()
        for commit in all_keys:
            # Format: /promotions/{channel}/{commit-sha}
            if not commit.startswith("/promotions/"):
                continue
            _, _, channel_name, commit_sha = commit.split("/")
            self._commits_by_channel[channel_name].add(commit_sha)

    def get_promotion_data(
        self, sha: str, channel: str, local_lookup: bool = True
    ) -> Optional[PromotionData]:
        if local_lookup and sha not in self._commits_by_channel[channel]:
            # Lets reduce unecessary calls to S3
            return None
        key = f"promotions/{channel}/{sha}"
        try:
            data = self._state.get(key)
        except KeyError:
            return None
        return PromotionData(**data)

    def publish_promotion_data(
        self, sha: str, channel: str, data: PromotionData
    ) -> None:
        state_key = f"promotions/{channel}/{sha}"
        self._state.add(state_key, data.dict(), force=True)
        logging.info("Uploaded %s to %s", data, state_key)

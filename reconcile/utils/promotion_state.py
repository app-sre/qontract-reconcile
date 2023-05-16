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
            # for backwards compatibility - remove this after a while
            if commit.startswith("/promotions/"):
                # Format: /promotions/{channel}/{commit-sha}
                _, _, channel_name, commit_sha = commit.split("/")
                self._commits_by_channel[channel_name].add(commit_sha)
            # / for backwards compatibility - remove this after a while

            # Format: /deployments/{channel}/{saas-target-uid}/{commit-sha}
            if not commit.startswith("/deployments/"):
                continue
            _, _, channel_name, saas_target_uid, commit_sha = commit.split("/")
            self._commits_by_channel[f"{channel_name}/{saas_target_uid}"].add(
                commit_sha
            )

    def get_promotion_data(
        self, sha: str, channel: str, saas_target_uid: str, local_lookup: bool = True
    ) -> Optional[PromotionData]:
        if (
            local_lookup
            and sha not in self._commits_by_channel[channel]
            and sha not in self._commits_by_channel[f"{channel}/{saas_target_uid}"]
        ):
            # Lets reduce unecessary calls to S3
            return None

        # for backwards compatibility - remove this after a while
        key = f"promotions/{channel}/{sha}"
        try:
            data = self._state.get(key)
            return PromotionData(**data)
        except KeyError:
            pass
        # / for backwards compatibility - remove this after a while

        key = f"deployments/{channel}/{saas_target_uid}/{sha}"
        try:
            data = self._state.get(key)
            return PromotionData(**data)
        except KeyError:
            return None

    def publish_promotion_data(
        self, sha: str, channel: str, saas_target_uid: str, data: PromotionData
    ) -> None:
        state_key = f"deployments/{channel}/{saas_target_uid}/{sha}"
        self._state.add(state_key, data.dict(), force=True)
        logging.info("Uploaded %s to %s", data, state_key)

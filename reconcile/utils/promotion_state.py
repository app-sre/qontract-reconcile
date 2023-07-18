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

    def _target_key(self, channel: str, target_uid: str) -> str:
        return f"{channel}/{target_uid}"

    def cache_commit_shas_from_s3(self) -> None:
        """
        Caching commit shas locally - this is used
        to lookup locally if a key exists on S3
        before querying.
        """
        all_keys = self._state.ls()
        for commit in all_keys:
            # BACKWARDS-COMPAT BLOCK
            # Format: /promotions/{channel}/{commit-sha}
            if commit.startswith("/promotions/"):
                # Keep this for backwards-compatibility with v1 promotions
                # We wait a couple of months to be sure all pipelines have
                # been triggered since.
                # This can be deleted after 30.09.2023
                _, _, channel_name, commit_sha = commit.split("/")
                self._commits_by_channel[channel_name].add(commit_sha)
            # / BACKWARDS-COMPAT BLOCK

            # Format: /promotions_v2/{channel}/{publisher-target-uid}/{commit-sha}
            if not commit.startswith("/promotions_v2/"):
                continue
            _, _, channel_name, publisher_uid, commit_sha = commit.split("/")
            key = self._target_key(channel=channel_name, target_uid=publisher_uid)
            self._commits_by_channel[key].add(commit_sha)

    def get_promotion_data(
        self, sha: str, channel: str, target_uid: str = "", local_lookup: bool = True
    ) -> Optional[PromotionData]:
        cache_key_v1 = channel
        cache_key_v2 = self._target_key(channel=channel, target_uid=target_uid)
        if (
            local_lookup
            and sha not in self._commits_by_channel[cache_key_v1]
            and sha not in self._commits_by_channel[cache_key_v2]
        ):
            # Lets reduce unecessary calls to S3
            return None

        # BACKWARDS-COMPAT BLOCK
        # Keep for backwards-compatibility with v1 promotions
        # We wait a couple of months to be sure all pipelines have
        # been triggered since.
        # This can be deleted after 30.09.2023
        path_v1 = f"promotions/{channel}/{sha}"
        try:
            data = self._state.get(path_v1)
            return PromotionData(**data)
        except KeyError:
            pass
        # / BACKWARDS-COMPAT BLOCK

        path_v2 = f"promotions_v2/{channel}/{target_uid}/{sha}"
        try:
            data = self._state.get(path_v2)
            return PromotionData(**data)
        except KeyError:
            return None

    def publish_promotion_data(
        self, sha: str, channel: str, target_uid: str, data: PromotionData
    ) -> None:
        # TODO: this will be deprecated once we fully moved to promotions_v2
        state_key = f"promotions/{channel}/{sha}"
        self._state.add(state_key, data.dict(), force=True)
        logging.info("Uploaded %s to %s", data, state_key)

        state_key_v2 = f"promotions_v2/{channel}/{target_uid}/{sha}"
        self._state.add(state_key_v2, data.dict(), force=True)
        logging.info("Uploaded %s to %s", data, state_key_v2)

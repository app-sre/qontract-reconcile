import logging
from collections import defaultdict

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

    # The success is primarily used for SAPM auto-promotions
    success: bool
    target_config_hash: str | None
    saas_file: str | None
    check_in: str | None
    # Whether this promotion has ever succeeded
    # Note, this shouldnt be overridden on subsequent promotions of same ref
    # This attribute is primarily used by saasherder validations
    has_succeeded_once: bool | None

    class Config:
        smart_union = True
        extra = Extra.forbid


class PromotionState:
    """
    A wrapper around a reconcile.utils.state.State object.
    This is dedicated to storing and retrieving information
    about promotions on S3.

    Note, that PromotionsState holds 2 caches.
    One cache for the promotion data that has already been fetched.
    Another cache for commit sha lookup, i.e., checking if a commit sha
    exists in S3 before making any API calls to it.
    """

    def __init__(self, state: State):
        self._state = state
        self._commits_by_channel: dict[str, set[str]] = defaultdict(set)
        self._promotion_data_cache: dict[str, PromotionData | None] = {}

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
            # Format: /promotions_v2/{channel}/{publisher-target-uid}/{commit-sha}
            if not commit.startswith("/promotions_v2/"):
                continue
            _, _, channel_name, publisher_uid, commit_sha = commit.split("/")
            key = self._target_key(channel=channel_name, target_uid=publisher_uid)
            self._commits_by_channel[key].add(commit_sha)

    def get_promotion_data(
        self,
        sha: str,
        channel: str,
        target_uid: str = "",
        pre_check_sha_exists: bool = True,
        use_cache: bool = False,
    ) -> PromotionData | None:
        """
        Fetch promotion data from S3.

        @param use_cache: Each fetched promotion data is cached locally. Setting this
        flag to True will use the cache if the data is already fetched.

        @param pre_check_sha_exists: If set to True, we will check if the commit sha exists
        in local cache and if not will exit before making any API calls. Note, that this requires
        a prior call to cache_commit_shas_from_s3 to populate the local commit cache.
        """
        cache_key_v2 = self._target_key(channel=channel, target_uid=target_uid)
        if pre_check_sha_exists and sha not in self._commits_by_channel[cache_key_v2]:
            # Lets reduce unecessary calls to S3
            return None

        path_v2 = f"promotions_v2/{channel}/{target_uid}/{sha}"
        if use_cache and path_v2 in self._promotion_data_cache:
            return self._promotion_data_cache[path_v2]

        data = self._state.get(path_v2)
        promotion_data = PromotionData(**data)
        self._promotion_data_cache[path_v2] = promotion_data
        return promotion_data

    def publish_promotion_data(
        self, sha: str, channel: str, target_uid: str, data: PromotionData
    ) -> None:
        state_key_v2 = f"promotions_v2/{channel}/{target_uid}/{sha}"
        self._state.add(state_key_v2, data.dict(), force=True)
        logging.info("Uploaded %s to %s", data, state_key_v2)

import logging
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from gitlab.exceptions import GitlabGetError
from gitlab.v4.objects import ProjectMergeRequest

from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request import (
    SAPMMR,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    CHANNELS_REF,
    CONTENT_HASH,
    PROMOTION_DATA_SEPARATOR,
    SAPM_LABEL,
    SAPM_VERSION,
    VERSION_REF,
    Renderer,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber
from reconcile.saas_auto_promotions_manager.utils.vcs import VCS


@dataclass
class OpenMergeRequest:
    raw: ProjectMergeRequest
    content_hash: str
    channels: str


class MergeRequestManager:
    """
    Manager for SAPM merge requests. This class
    is responsible for housekeeping (closing old/bad MRs) and
    opening new MRs for subscribers with a state diff.

    The idea is that for every channel combination there exists
    maximum one open MR in app-interface. I.e., all changes for
    a channel combination are batched in a single MR. A content hash in the
    description is used to identify the content of that MR. If a
    channel combination receives new content before an already open MR
    is merged, then the manager will first close the old MR and then
    open a new MR with the new content. We might need to change this
    batching approach in the future to have even less promotion MRs,
    but for now this is sufficient.
    """

    def __init__(self, vcs: VCS, renderer: Renderer):
        self._vcs = vcs
        self._renderer = renderer
        self._version_ref_regex = re.compile(rf"{VERSION_REF}: (.*)$", re.MULTILINE)
        self._content_hash_regex = re.compile(rf"{CONTENT_HASH}: (.*)$", re.MULTILINE)
        self._channels_regex = re.compile(rf"{CHANNELS_REF}: (.*)$", re.MULTILINE)
        self._open_mrs: list[OpenMergeRequest] = []
        self._open_mrs_with_problems: list[OpenMergeRequest] = []
        self._open_raw_mrs: list[ProjectMergeRequest] = []

    def _apply_regex(self, pattern: re.Pattern, promotion_data: str) -> str:
        matches = pattern.search(promotion_data)
        if not matches:
            return ""
        groups = matches.groups()
        if len(groups) != 1:
            return ""
        return groups[0]

    def fetch_sapm_managed_open_merge_requests(self) -> None:
        all_open_mrs = self._vcs.get_open_app_interface_merge_requests()
        self._open_raw_mrs = [
            mr for mr in all_open_mrs if SAPM_LABEL in mr.attributes.get("labels")
        ]

    def housekeeping(self) -> None:
        """
        Close bad MRs:
        - bad description format
        - old SAPM version
        - merge conflict

        --> if we bump the SAPM version, we automatically close
        old open MRs and replace them with new ones.
        """
        seen: set[tuple[str, str, str]] = set()
        for mr in self._open_raw_mrs:
            attrs = mr.attributes
            desc = attrs.get("description")
            has_conflicts = attrs.get("has_conflicts", False)
            if has_conflicts:
                logging.info(
                    "Merge-conflict detected. Closing %s",
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, "Closing this MR because of a merge-conflict."
                )
                continue
            parts = desc.split(PROMOTION_DATA_SEPARATOR)
            if not len(parts) == 2:
                logging.info(
                    "Bad data separator format. Closing %s",
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, "Closing this MR because of bad data separator format."
                )
                continue
            promotion_data = parts[1]

            version_ref = self._apply_regex(
                pattern=self._version_ref_regex, promotion_data=promotion_data
            )
            if not version_ref:
                logging.info(
                    "Bad %s format. Closing %s",
                    VERSION_REF,
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, f"Closing this MR because of bad {VERSION_REF} format."
                )
                continue

            if version_ref != SAPM_VERSION:
                logging.info(
                    "Old MR version detected: %s. Closing %s",
                    version_ref,
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr,
                    f"Closing this MR because it has an outdated SAPM version {version_ref}",
                )
                continue

            content_hash = self._apply_regex(
                pattern=self._content_hash_regex, promotion_data=promotion_data
            )
            if not content_hash:
                logging.info(
                    "Bad %s format. Closing %s",
                    CONTENT_HASH,
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, f"Closing this MR because of bad {CONTENT_HASH} format."
                )
                continue

            channels_ref = self._apply_regex(
                pattern=self._channels_regex, promotion_data=promotion_data
            )
            if not channels_ref:
                logging.info(
                    "Bad %s format. Closing %s",
                    CHANNELS_REF,
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, f"Closing this MR because of bad {CHANNELS_REF} format."
                )
                continue

            key = (version_ref, channels_ref, content_hash)
            if key in seen:
                logging.info(
                    "Duplicate MR detected. Closing %s",
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr,
                    "Closing this MR because there is already another MR open with identical content.",
                )
                continue
            seen.add(key)

            self._open_mrs.append(
                OpenMergeRequest(
                    raw=mr,
                    content_hash=content_hash,
                    channels=channels_ref,
                )
            )

    def _aggregate_subscribers_per_channel_combo(
        self, subscribers: Iterable[Subscriber]
    ) -> dict[str, list[Subscriber]]:
        subscribers_per_channel_combo: dict[str, list[Subscriber]] = defaultdict(list)
        for subscriber in subscribers:
            channel_combo = ",".join([c.name for c in subscriber.channels])
            subscribers_per_channel_combo[channel_combo].append(subscriber)
        return subscribers_per_channel_combo

    def _merge_request_already_exists(self, channels: str, content_hash: str) -> bool:
        return any(
            True
            for mr in self._open_mrs
            if mr.content_hash == content_hash and mr.channels == channels
        )

    def create_promotion_merge_requests(
        self, subscribers: Iterable[Subscriber]
    ) -> None:
        """
        Open new MR for channel combinations with new content.
        If there is new content, close any existing MR for that
        channel combination.
        """
        subscribers_per_channel_combo = self._aggregate_subscribers_per_channel_combo(
            subscribers=subscribers
        )
        for channel_combo, subs in subscribers_per_channel_combo.items():
            combined_content_hash = Subscriber.combined_content_hash(subscribers=subs)
            if self._merge_request_already_exists(
                content_hash=combined_content_hash, channels=channel_combo
            ):
                logging.info(
                    "There is already an open merge request for channel(s) %s - skipping",
                    channel_combo,
                )
                continue
            for mr in self._open_mrs:
                if mr.channels != channel_combo:
                    continue
                if mr.content_hash != combined_content_hash:
                    logging.info(
                        "Closing MR %s because it has out-dated content",
                        mr.raw.attributes.get("web_url", "NO_WEBURL"),
                    )
                    self._vcs.close_app_interface_mr(
                        mr=mr.raw,
                        comment="Closing this MR because it has out-dated content.",
                    )
            content_by_path: dict[str, str] = {}
            has_error = False
            for sub in subs:
                if sub.target_file_path not in content_by_path:
                    try:
                        content_by_path[
                            sub.target_file_path
                        ] = self._vcs.get_file_content_from_app_interface_master(
                            file_path=sub.target_file_path
                        )
                    except GitlabGetError as e:
                        if e.response_code == 404:
                            logging.error(
                                "The saas file %s does not exist anylonger. Most likely qontract-server data not in synch. This should resolve soon on its own.",
                                sub.target_file_path,
                            )
                            has_error = True
                            break
                        raise e
                content_by_path[
                    sub.target_file_path
                ] = self._renderer.render_merge_request_content(
                    subscriber=sub,
                    current_content=content_by_path[sub.target_file_path],
                )
            if has_error:
                continue

            description = self._renderer.render_description(
                content_hash=combined_content_hash,
                channels=channel_combo,
            )
            title = self._renderer.render_title(channels=channel_combo)
            logging.info(
                "Open MR for update in channel(s) %s",
                channel_combo,
            )
            self._vcs.open_app_interface_merge_request(
                mr=SAPMMR(
                    sapm_label=SAPM_LABEL,
                    content_by_path=content_by_path,
                    title=title,
                    description=description,
                )
            )

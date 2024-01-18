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
    CONTENT_HASHES,
    IS_BATCHABLE,
    PROMOTION_DATA_SEPARATOR,
    SAPM_LABEL,
    SAPM_VERSION,
    VERSION_REF,
    Renderer,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber
from reconcile.utils.vcs import VCS, MRCheckStatus

ITEM_SEPARATOR = ","


@dataclass
class OpenMergeRequest:
    raw: ProjectMergeRequest
    content_hashes: str
    channels: str
    failed_mr_check: bool
    is_batchable: bool


class MergeRequestManager:
    """
    Manager for SAPM merge requests. This class
    is responsible for housekeeping (closing old/bad MRs) and
    opening new MRs for subscribers with a state diff.

    The idea is that for every channel combination there exists
    maximum one open MR in app-interface. I.e., all changes for
    a channel combination at a minumum are batched in a single MR.
    The MR description is used to store current state for SAPM.
    Channels can also be batched together into a single MR to reduce the overall
    amount of MRs.
    """

    def __init__(self, vcs: VCS, renderer: Renderer):
        self._vcs = vcs
        self._renderer = renderer
        self._version_ref_regex = re.compile(rf"{VERSION_REF}: (.*)$", re.MULTILINE)
        self._content_hash_regex = re.compile(rf"{CONTENT_HASHES}: (.*)$", re.MULTILINE)
        self._channels_regex = re.compile(rf"{CHANNELS_REF}: (.*)$", re.MULTILINE)
        self._is_batchable_regex = re.compile(rf"{IS_BATCHABLE}: (.*)$", re.MULTILINE)
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

    def _fetch_sapm_managed_open_merge_requests(self) -> None:
        all_open_mrs = self._vcs.get_open_app_interface_merge_requests()
        self._open_raw_mrs = [
            mr for mr in all_open_mrs if SAPM_LABEL in mr.attributes.get("labels")
        ]

    def _parse_raw_mrs(self) -> None:
        """
        We store state in MR descriptions.
        This function parses the state and stores a list of valid, parsed open MRs (current state).
        If any issue is encountered during parsing, we consider this MR
        to be broken and close it. Information we want to parse includes:
        - SAPM_VERSION -> Close if it doesnt match current version
        - CHANNELS
        - CONTENT_HASHES
        - IS_BATCHABLE flag
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

            content_hashes = self._apply_regex(
                pattern=self._content_hash_regex, promotion_data=promotion_data
            )
            if not content_hashes:
                logging.info(
                    "Bad %s format. Closing %s",
                    CONTENT_HASHES,
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, f"Closing this MR because of bad {CONTENT_HASHES} format."
                )
                continue

            channels_refs = self._apply_regex(
                pattern=self._channels_regex, promotion_data=promotion_data
            )
            if not channels_refs:
                logging.info(
                    "Bad %s format. Closing %s",
                    CHANNELS_REF,
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, f"Closing this MR because of bad {CHANNELS_REF} format."
                )
                continue

            key = (version_ref, channels_refs, content_hashes)
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

            is_batchable_str = self._apply_regex(
                pattern=self._is_batchable_regex, promotion_data=promotion_data
            )
            if is_batchable_str not in set(["True", "False"]):
                logging.info(
                    "Bad %s format. Closing %s",
                    IS_BATCHABLE,
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, f"Closing this MR because of bad {IS_BATCHABLE} format."
                )
                continue

            mr_check_status = self._vcs.get_gitlab_mr_check_status(mr)

            self._open_mrs.append(
                OpenMergeRequest(
                    raw=mr,
                    content_hashes=content_hashes,
                    channels=channels_refs,
                    failed_mr_check=mr_check_status == MRCheckStatus.FAILED,
                    is_batchable=bool(is_batchable_str),
                )
            )

    def _unbatch_failed_mrs(self) -> None:
        """
        We optimistically batch MRs together that didnt run through MR check yet.
        Vast majority of auto-promotion MRs are succeeding checks, so we can stay optimistic.
        In the rare case of an MR failing the check, we want to unbatch it.
        I.e., we open a dedicated MR for each channel in the batched MR, mark the new MRs as non-batchable
        and close the old batched MR. By doing so, we ensure that unrelated MRs are not blocking each other.
        Unbatched MRs are marked and will never be batched again.
        """
        # TODO: implemented in follow-up MR
        pass

    def housekeeping(self) -> None:
        self._fetch_sapm_managed_open_merge_requests()
        self._parse_raw_mrs()
        self._unbatch_failed_mrs()

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
            if content_hash in mr.content_hashes and channels in mr.channels
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
                if channel_combo not in mr.channels:
                    continue
                if combined_content_hash not in mr.content_hashes:
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
                        content_by_path[sub.target_file_path] = (
                            self._vcs.get_file_content_from_app_interface_master(
                                file_path=sub.target_file_path
                            )
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
                content_by_path[sub.target_file_path] = (
                    self._renderer.render_merge_request_content(
                        subscriber=sub,
                        current_content=content_by_path[sub.target_file_path],
                    )
                )
            if has_error:
                continue

            description = self._renderer.render_description(
                content_hashes=combined_content_hash,
                channels=channel_combo,
                is_batchable=True,
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

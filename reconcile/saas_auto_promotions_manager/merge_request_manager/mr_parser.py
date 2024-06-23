import logging
import re
from collections.abc import Iterable

from gitlab.v4.objects import ProjectMergeRequest

from reconcile.saas_auto_promotions_manager.merge_request_manager.open_merge_requests import (
    MRKind,
    OpenBatcherMergeRequest,
    OpenSchedulerMergeRequest,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    CHANNELS_REF,
    CONTENT_HASHES,
    IS_BATCHABLE,
    MR_KIND_REF,
    PROMOTION_DATA_SEPARATOR,
    SAPM_VERSION,
    VERSION_REF,
)
from reconcile.utils.vcs import VCS, MRCheckStatus

ITEM_SEPARATOR = ","


class MRParser:
    """
    We store state in MR descriptions.

    This class parses open MRs and ensures they are compatible with our logic.
    I.e., this class fetches the current state.
    """

    def __init__(self, vcs: VCS):
        self._vcs = vcs
        self._version_ref_regex = re.compile(rf"{VERSION_REF}: (.*)$", re.MULTILINE)
        self._content_hash_regex = re.compile(rf"{CONTENT_HASHES}: (.*)$", re.MULTILINE)
        self._channels_regex = re.compile(rf"{CHANNELS_REF}: (.*)$", re.MULTILINE)
        self._is_batchable_regex = re.compile(rf"{IS_BATCHABLE}: (.*)$", re.MULTILINE)
        self._mr_kind_regex = re.compile(rf"{MR_KIND_REF}: (.*)$", re.MULTILINE)
        self._open_batcher_mrs: list[OpenBatcherMergeRequest] = []
        self._open_scheduler_mrs: list[OpenSchedulerMergeRequest] = []

    def get_open_batcher_mrs(self) -> list[OpenBatcherMergeRequest]:
        return self._open_batcher_mrs

    def get_open_scheduler_mrs(self) -> list[OpenSchedulerMergeRequest]:
        return self._open_scheduler_mrs

    def _apply_regex(self, pattern: re.Pattern, promotion_data: str) -> str:
        matches = pattern.search(promotion_data)
        if not matches:
            return ""
        groups = matches.groups()
        if len(groups) != 1:
            return ""
        return groups[0]

    def fetch_mrs(self, label: str) -> None:
        """
        This function parses the state of valid, parsed open MRs (current state).
        If any issue is encountered during parsing, we consider this MR
        to be broken and close it. Information we want to parse includes:
        - SAPM_VERSION -> Close if it doesnt match current version
        - CHANNELS
        - CONTENT_HASHES
        - IS_BATCHABLE flag
        - MR has merge conflicts
        """
        all_open_mrs = self._vcs.get_open_app_interface_merge_requests()
        sapm_mrs = [
            mr for mr in all_open_mrs if label in mr.attributes.get("labels", [])
        ]
        open_batcher_mrs: list[ProjectMergeRequest] = []
        open_scheduler_mrs: list[ProjectMergeRequest] = []

        for mr in sapm_mrs:
            attrs = mr.attributes
            desc = str(attrs.get("description", ""))
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
                    f"Closing this MR because it has an outdated SAPM version {version_ref}.",
                )
                continue

            mr_kind_str = self._apply_regex(
                pattern=self._mr_kind_regex, promotion_data=promotion_data
            )
            if not mr_kind_str or mr_kind_str not in {
                MRKind.BATCHER.value,
                MRKind.SCHEDULER.value,
            }:
                logging.info(
                    "Bad %s format. Closing %s",
                    MR_KIND_REF,
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, f"Closing this MR because of bad {MR_KIND_REF} format."
                )
                continue

            mr_kind = MRKind(mr_kind_str)
            if mr_kind == MRKind.BATCHER:
                open_batcher_mrs.append(mr)
            elif mr_kind == MRKind.SCHEDULER:
                open_scheduler_mrs.append(mr)

        self._handle_open_batcher_mrs(open_batcher_mrs)

    def _handle_open_batcher_mrs(self, mrs: Iterable[ProjectMergeRequest]) -> None:
        seen: set[tuple[str, str]] = set()
        for mr in mrs:
            attrs = mr.attributes
            desc = str(attrs.get("description", ""))
            parts = desc.split(PROMOTION_DATA_SEPARATOR)
            promotion_data = parts[1]
            has_conflicts = bool(attrs.get("has_conflicts", False))
            if has_conflicts:
                logging.info(
                    "Merge-conflict detected. Closing %s",
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, "Closing this MR because of a merge-conflict."
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

            key = (channels_refs, content_hashes)
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

            self._open_batcher_mrs.append(
                OpenBatcherMergeRequest(
                    raw=mr,
                    content_hashes=set(content_hashes.split(ITEM_SEPARATOR)),
                    channels=set(channels_refs.split(ITEM_SEPARATOR)),
                    failed_mr_check=mr_check_status == MRCheckStatus.FAILED,
                    is_batchable=is_batchable_str == "True",
                )
            )

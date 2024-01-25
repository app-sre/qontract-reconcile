import logging
import re
from dataclasses import dataclass

from gitlab.v4.objects import ProjectMergeRequest

from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    CHANNELS_REF,
    CONTENT_HASHES,
    IS_BATCHABLE,
    PROMOTION_DATA_SEPARATOR,
    SAPM_VERSION,
    VERSION_REF,
)
from reconcile.utils.vcs import VCS, MRCheckStatus


@dataclass
class OpenMergeRequest:
    raw: ProjectMergeRequest
    content_hashes: set[str]
    channels: set[str]
    failed_mr_check: bool
    is_batchable: bool


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

    def _apply_regex(self, pattern: re.Pattern, promotion_data: str) -> str:
        matches = pattern.search(promotion_data)
        if not matches:
            return ""
        groups = matches.groups()
        if len(groups) != 1:
            return ""
        return groups[0]

    def _fetch_sapm_managed_open_merge_requests(
        self, label: str
    ) -> list[ProjectMergeRequest]:
        all_open_mrs = self._vcs.get_open_app_interface_merge_requests()
        return [mr for mr in all_open_mrs if label in mr.attributes.get("labels")]

    def retrieve_open_mrs(self, label: str) -> list[OpenMergeRequest]:
        """
        This function parses the state and returns a list of valid, parsed open MRs (current state).
        If any issue is encountered during parsing, we consider this MR
        to be broken and close it. Information we want to parse includes:
        - SAPM_VERSION -> Close if it doesnt match current version
        - CHANNELS
        - CONTENT_HASHES
        - IS_BATCHABLE flag
        - MR has merge conflicts
        """
        open_mrs: list[OpenMergeRequest] = []
        seen: set[tuple[str, str, str]] = set()
        for mr in self._fetch_sapm_managed_open_merge_requests(label=label):
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
                    f"Closing this MR because it has an outdated SAPM version {version_ref}.",
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

            open_mrs.append(
                OpenMergeRequest(
                    raw=mr,
                    content_hashes=set(content_hashes.split(ITEM_SEPARATOR)),
                    channels=set(channels_refs.split(ITEM_SEPARATOR)),
                    failed_mr_check=mr_check_status == MRCheckStatus.FAILED,
                    is_batchable=is_batchable_str == "True",
                )
            )
        return open_mrs

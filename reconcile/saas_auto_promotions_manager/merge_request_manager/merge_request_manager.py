import logging
import re
from dataclasses import dataclass

from gitlab.exceptions import GitlabGetError
from gitlab.v4.objects import ProjectMergeRequest

from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request import (
    SAPMMR,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    CONTENT_HASH,
    FILE_PATH,
    NAMESPACE_REF,
    PROMOTION_DATA_SEPARATOR,
    SAPM_LABEL,
    Renderer,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber
from reconcile.saas_auto_promotions_manager.utils.vcs import VCS


@dataclass
class OpenMergeRequest:
    raw: ProjectMergeRequest
    content_hash: str
    target_file_path: str
    namespace_ref: str


class MergeRequestManager:
    def __init__(self, vcs: VCS, renderer: Renderer):
        self._vcs = vcs
        self._renderer = renderer
        self._namespace_ref_regex = re.compile(rf"{NAMESPACE_REF}: (.*)$", re.MULTILINE)
        self._target_file_path_regex = re.compile(rf"{FILE_PATH}: (.*)$", re.MULTILINE)
        self._content_hash_regex = re.compile(rf"{CONTENT_HASH}: (.*)$", re.MULTILINE)
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

            namespace_ref = self._apply_regex(
                pattern=self._namespace_ref_regex, promotion_data=promotion_data
            )
            if not namespace_ref:
                logging.info(
                    "Bad %s format. Closing %s",
                    NAMESPACE_REF,
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, f"Closing this MR because of bad {NAMESPACE_REF} format."
                )
                continue

            target_file_path = self._apply_regex(
                pattern=self._target_file_path_regex, promotion_data=promotion_data
            )
            if not target_file_path:
                logging.info(
                    "Bad %s format. Closing %s",
                    FILE_PATH,
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, f"Closing this MR because of bad {FILE_PATH} format."
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

            key = (target_file_path, namespace_ref, content_hash)
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
                    target_file_path=target_file_path,
                    namespace_ref=namespace_ref,
                )
            )

    def _get_open_mrs_for_same_target(
        self, subscriber: Subscriber
    ) -> list[OpenMergeRequest]:
        return [
            mr
            for mr in self._open_mrs
            if mr.namespace_ref == subscriber.namespace_file_path
            and mr.target_file_path == subscriber.target_file_path
        ]

    def process_subscriber(self, subscriber: Subscriber) -> None:
        open_mrs_for_same_target = self._get_open_mrs_for_same_target(
            subscriber=subscriber
        )
        has_open_mr_with_same_content = False
        for open_mr in open_mrs_for_same_target:
            if open_mr.content_hash != subscriber.content_hash():
                logging.info(
                    "Closing MR %s because it has out-dated content",
                    open_mr.raw.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr=open_mr.raw,
                    comment="Closing this MR because it has out-dated content.",
                )
            else:
                has_open_mr_with_same_content = True
        if has_open_mr_with_same_content:
            logging.info(
                "We already have an open MR for path: %s namespace: %s ref: %s target_hashes: %s - skipping",
                subscriber.target_file_path,
                subscriber.namespace_file_path,
                subscriber.desired_ref,
                subscriber.desired_hashes,
            )
            return
        try:
            content_on_master = self._vcs.get_file_content_from_app_interface_master(
                file_path=subscriber.target_file_path
            )
        except GitlabGetError as e:
            if e.response_code == 404:
                logging.error(
                    "The saas file %s does not exist anylonger. qontract-server data not in synch. This should resolve soon on its own.",
                    subscriber.target_file_path,
                )
                return
            raise e
        content = self._renderer.render_merge_request_content(
            subscriber=subscriber,
            current_content=content_on_master,
        )
        description = self._renderer.render_description(subscriber=subscriber)
        title = self._renderer.render_title(subscriber=subscriber)
        logging.info(
            "Open MR for path: %s namespace: %s ref: %s target_hashes: %s",
            subscriber.target_file_path,
            subscriber.namespace_file_path,
            subscriber.desired_ref,
            subscriber.desired_hashes,
        )
        self._vcs.open_app_interface_merge_request(
            mr=SAPMMR(
                sapm_label=SAPM_LABEL,
                content=content,
                title=title,
                description=description,
                file_path=subscriber.target_file_path,
            )
        )

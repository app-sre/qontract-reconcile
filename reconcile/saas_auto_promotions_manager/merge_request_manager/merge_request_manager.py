import logging
import re
from dataclasses import dataclass

from gitlab.exceptions import GitlabGetError
from gitlab.v4.objects import ProjectMergeRequest

from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request import (
    SAPMMR,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    PROMOTION_DATA_SEPARATOR,
    Renderer,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber
from reconcile.saas_auto_promotions_manager.utils.vcs import VCS

SAPM_LABEL = "SAPM"
NAMESPACE_REF = "namespace_ref"
CONTENT_HASH = "content_hash"
TARGET_FILE_PATH = "target_file_path"


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
        self._target_file_path_regex = re.compile(
            rf"{TARGET_FILE_PATH}: (.*)$", re.MULTILINE
        )
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
        for mr in self._open_raw_mrs:
            attrs = mr.attributes
            desc = attrs.get("description")
            has_conflicts = attrs.get("has_conflicts", False)
            if has_conflicts:
                logging.info(
                    "merge-conflict detected. Closing %s",
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(mr)
                continue
            parts = desc.split(PROMOTION_DATA_SEPARATOR)
            if not len(parts) == 2:
                logging.info(
                    "bad description format. Closing %s",
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(mr)
                continue
            promotion_data = parts[1]

            namespace_ref = self._apply_regex(
                pattern=self._namespace_ref_regex, promotion_data=promotion_data
            )
            if not namespace_ref:
                logging.info(
                    "bad description format. Closing %s",
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(mr)
                continue

            target_file_path = self._apply_regex(
                pattern=self._target_file_path_regex, promotion_data=promotion_data
            )
            if not target_file_path:
                logging.info(
                    "bad description format. Closing %s",
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(mr)
                continue

            content_hash = self._apply_regex(
                pattern=self._content_hash_regex, promotion_data=promotion_data
            )
            if not content_hash:
                logging.info(
                    "bad description format. Closing %s",
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(mr)
                continue

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
        open_mrs = self._get_open_mrs_for_same_target(subscriber=subscriber)
        has_open_mr_with_same_content = False
        for open_mr in open_mrs:
            if open_mr.content_hash == subscriber.content_hash():
                if has_open_mr_with_same_content:
                    logging.info(
                        "Closing MR %s because there already is an open MR with same content for this target",
                        open_mr.raw.attributes.get("web_url", "NO_WEBURL"),
                    )
                    self._vcs.close_app_interface_mr(mr=open_mr.raw)
                has_open_mr_with_same_content = True
            else:
                logging.info(
                    "Closing MR %s because it has out-dated state",
                    open_mr.raw.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(mr=open_mr.raw)
        if has_open_mr_with_same_content:
            return
        try:
            content_on_master = self._vcs.get_file_content_from_app_interface_master(
                file_path=subscriber.target_file_path
            )
        except GitlabGetError as e:
            if e.response_code == 404:
                logging.info(
                    "The saas file %s does not exist anylonger. qontract-server data not in synch, but should resolve soon on its own.",
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
            )
        )

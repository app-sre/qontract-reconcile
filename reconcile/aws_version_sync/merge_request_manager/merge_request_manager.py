import logging
import re
from dataclasses import dataclass

from gitlab.exceptions import GitlabGetError
from gitlab.v4.objects import ProjectMergeRequest

from reconcile.aws_version_sync.merge_request_manager.merge_request import (
    AVS_LABEL,
    AVSInfo,
    Parser,
    ParserError,
    ParserVersionError,
    Renderer,
)
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import (
    AUTO_MERGE,
    SHOW_SELF_SERVICEABLE_IN_REVIEW_QUEUE,
)
from reconcile.utils.vcs import VCS


@dataclass
class OpenMergeRequest:
    raw: ProjectMergeRequest
    avs_info: AVSInfo


class AVSMR(MergeRequestBase):
    name = "AVS"

    def __init__(
        self, title: str, description: str, path: str, content: str, labels: list[str]
    ):
        super().__init__()
        self._title = title
        self._description = description
        self._path = path
        self._content = content
        self.labels = labels

    @property
    def title(self) -> str:
        return self._title

    @property
    def description(self) -> str:
        return self._description

    def process(self, gitlab_cli: GitLabApi) -> None:
        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=f"data{self._path}",
            commit_message="aws version sync",
            content=self._content,
        )


class MergeRequestManager:
    """
    Manager for AVS merge requests. This class
    is responsible for housekeeping (closing old/bad MRs) and
    opening new MRs for external resources that have new versions.

    For each external resource, there are exist just one MR to update
    the version number in the App-Interface. Old or obsolete MRs are
    closed automatically.
    """

    def __init__(
        self, vcs: VCS, renderer: Renderer, parser: Parser, auto_merge_enabled: bool
    ):
        self._vcs = vcs
        self._open_mrs: list[OpenMergeRequest] = []
        self._open_mrs_with_problems: list[OpenMergeRequest] = []
        self._open_raw_mrs: list[ProjectMergeRequest] = []
        self._renderer = renderer
        self._parser = parser
        self._auto_merge_enabled = auto_merge_enabled

    def _apply_regex(self, pattern: re.Pattern, promotion_data: str) -> str:
        matches = pattern.search(promotion_data)
        if not matches:
            return ""
        groups = matches.groups()
        if len(groups) != 1:
            return ""
        return groups[0]

    def fetch_avs_managed_open_merge_requests(self) -> None:
        all_open_mrs = self._vcs.get_open_app_interface_merge_requests()
        self._open_raw_mrs = [mr for mr in all_open_mrs if AVS_LABEL in mr.labels]

    def housekeeping(self) -> None:
        """
        Close bad MRs:
        - bad description format
        - old AVS version
        - merge conflict

        --> if we bump the AVS version, we automatically close
        old open MRs and replace them with new ones.
        """
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
            try:
                avs_info = self._parser.parse(description=desc)
            except ParserVersionError:
                logging.info(
                    "Old MR version detected! Closing %s",
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, "Closing this MR because it has an outdated AVS version"
                )
                continue
            except ParserError:
                logging.info(
                    "Bad MR description format. Closing %s",
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, "Closing this MR because of bad description format."
                )
                continue

            self._open_mrs.append(OpenMergeRequest(raw=mr, avs_info=avs_info))

    def _merge_request_already_exists(
        self,
        provider: str,
        account_id: str,
        resource_provider: str,
        resource_identifier: str,
        resource_engine: str,
    ) -> OpenMergeRequest | None:
        for mr in self._open_mrs:
            if (
                mr.avs_info.provider == provider
                and mr.avs_info.account_id == account_id
                and mr.avs_info.resource_provider == resource_provider
                and mr.avs_info.resource_identifier == resource_identifier
                and mr.avs_info.resource_engine == resource_engine
            ):
                return mr

        return None

    def create_avs_merge_request(
        self,
        namespace_file: str,
        provider: str,
        provisioner_ref: str,
        provisioner_uid: str,
        resource_provider: str,
        resource_identifier: str,
        resource_engine: str,
        resource_engine_version: str,
    ) -> None:
        """Open new MR (if not already present) for an external resource and close any outdated before."""
        if mr := self._merge_request_already_exists(
            provider=provider,
            account_id=provisioner_uid,
            resource_provider=resource_provider,
            resource_identifier=resource_identifier,
            resource_engine=resource_engine,
        ):
            if mr.avs_info.resource_engine_version == resource_engine_version:
                # an MR for this external resource already exists
                return None
            logging.info(
                "Found an outdated MR for '%s' - closing it.", resource_identifier
            )
            self._vcs.close_app_interface_mr(
                mr.raw, "Closing this MR because it's outdated."
            )
            # don't open a new MR right now, because the deletion of the old MRs could be
            # disabled. In this case, we would end up with multiple open MRs for the
            # same external resource.
            return None

        try:
            content = self._vcs.get_file_content_from_app_interface_master(
                file_path=namespace_file
            )
        except GitlabGetError as e:
            if e.response_code == 404:
                logging.error(
                    "The file %s does not exist anylonger. Most likely qontract-server data not in synch. This should resolve soon on its own.",
                    namespace_file,
                )
                return None
            raise e
        content = self._renderer.render_merge_request_content(
            current_content=content,
            provider=provider,
            provisioner_ref=provisioner_ref,
            resource_provider=resource_provider,
            resource_identifier=resource_identifier,
            resource_engine_version=resource_engine_version,
        )

        description = self._renderer.render_description(
            provider=provider,
            account_id=provisioner_uid,
            resource_provider=resource_provider,
            resource_identifier=resource_identifier,
            resource_engine=resource_engine,
            resource_engine_version=resource_engine_version,
        )
        title = self._renderer.render_title(resource_identifier=resource_identifier)
        logging.info("Open MR for %s (%s)", resource_identifier, resource_engine)
        mr_labels = [AVS_LABEL]
        if self._auto_merge_enabled:
            mr_labels.append(AUTO_MERGE)
        else:
            mr_labels.append(SHOW_SELF_SERVICEABLE_IN_REVIEW_QUEUE)
        self._vcs.open_app_interface_merge_request(
            mr=AVSMR(
                path=namespace_file,
                title=title,
                description=description,
                content=content,
                labels=mr_labels,
            )
        )

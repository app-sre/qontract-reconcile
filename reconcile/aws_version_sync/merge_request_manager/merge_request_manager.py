import logging

from gitlab.exceptions import GitlabGetError
from pydantic import BaseModel

from reconcile.aws_version_sync.merge_request_manager.merge_request import (
    AVS_LABEL,
    AVSInfo,
    Parser,
    Renderer,
)
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.merge_request_manager.merge_request_manager import (
    MergeRequestManagerBase,
)
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.vcs import VCS


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


class MrData(BaseModel):
    namespace_file: str
    provider: str
    provisioner_ref: str
    provisioner_uid: str
    resource_provider: str
    resource_identifier: str
    resource_engine: str
    resource_engine_version: str


class MergeRequestManager(MergeRequestManagerBase[AVSInfo]):
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
        super().__init__(vcs, parser, AVS_LABEL)
        self._renderer = renderer
        self._auto_merge_enabled = auto_merge_enabled

    def create_merge_request(
        self,
        data: MrData,
    ) -> None:
        """Open new MR (if not already present) for an external resource and close any outdated before."""
        if not self._housekeeping_ran:
            self.housekeeping()

        namespace_file = data.namespace_file
        provider = data.provider
        provisioner_ref = data.provisioner_ref
        provisioner_uid = data.provisioner_uid
        resource_provider = data.resource_provider
        resource_identifier = data.resource_identifier
        resource_engine = data.resource_engine
        resource_engine_version = data.resource_engine_version

        if mr := self._merge_request_already_exists({
            "provider": provider,
            "account_id": provisioner_uid,
            "resource_provider": resource_provider,
            "resource_identifier": resource_identifier,
            "resource_engine": resource_engine,
        }):
            if mr.mr_info.resource_engine_version == resource_engine_version:
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
            content = self._vcs.get_file_content_from_app_interface_ref(
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
        self._vcs.open_app_interface_merge_request(
            mr=AVSMR(
                path=namespace_file,
                title=title,
                description=description,
                content=content,
                labels=mr_labels,
            )
        )

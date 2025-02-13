import hashlib
import json
import logging
from collections.abc import Sequence
from typing import Any, TypeAlias

from gitlab.exceptions import GitlabGetError
from pydantic import BaseModel

from reconcile.endpoints_discovery.merge_request import (
    INTEGRATION,
    INTEGRATION_REF,
    LABEL,
    EPDInfo,
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


class EndpointsDiscoveryMR(MergeRequestBase):
    name = "endpoints-discovery"

    def __init__(self, title: str, description: str, labels: list[str]):
        super().__init__()
        self._title = title
        self._description = description
        self.labels = labels
        self._commits: list[tuple[str, str, str]] = []

    @property
    def title(self) -> str:
        return self._title

    @property
    def description(self) -> str:
        return self._description

    def add_commit(self, path: str, content: str, msg: str) -> None:
        self._commits.append((path, content, msg))

    def process(self, gitlab_cli: GitLabApi) -> None:
        for path, content, msg in self._commits:
            gitlab_cli.update_file(
                branch_name=self.branch,
                file_path=path,
                commit_message=msg,
                content=content,
            )


class Endpoint(BaseModel):
    # the current endpoint name to change or delete. It doesn't matter for new endpoints
    name: str
    # the endpoint data will be generated and rendered from the endpoint template resource
    # see EndpointsDiscoveryIntegrationParams.endpoint_tmpl_resource
    data: dict[str, Any] = {}

    @property
    def hash(self) -> str:
        return hashlib.sha256(
            json.dumps(self.dict(), sort_keys=True).encode()
        ).hexdigest()


EndpointsToAdd: TypeAlias = list[Endpoint]
EndpointsToChange: TypeAlias = list[Endpoint]
EndpointsToDelete: TypeAlias = list[Endpoint]


class App(BaseModel):
    name: str
    path: str
    endpoints_to_add: EndpointsToAdd = EndpointsToAdd()
    endpoints_to_change: EndpointsToChange = EndpointsToChange()
    endpoints_to_delete: EndpointsToDelete = EndpointsToDelete()

    @property
    def hash(self) -> str:
        return hashlib.sha256(
            f"""
                {self.path}
                {[i.hash for i in sorted(self.endpoints_to_add, key=lambda i: i.name)]}
                {[i.hash for i in sorted(self.endpoints_to_change, key=lambda i: i.name)]}
                {[i.hash for i in sorted(self.endpoints_to_delete, key=lambda i: i.name)]}
            """.encode()
        ).hexdigest()


def hash_apps(apps: Sequence[App]) -> str:
    return hashlib.sha256(
        ",".join(app.hash for app in sorted(apps, key=lambda i: i.name)).encode()
    ).hexdigest()


class MergeRequestManager(MergeRequestManagerBase[EPDInfo]):
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
        super().__init__(vcs, parser, LABEL)
        self._renderer = renderer
        self._auto_merge_enabled = auto_merge_enabled

    def create_merge_request(self, apps: Sequence[App]) -> None:
        """Open new MR (if not already present) for apps and close any outdated before."""
        if not self._housekeeping_ran:
            self.housekeeping()

        apps_hash = hash_apps(apps)
        # we support only one MR at a time for all apps
        if mr := self._merge_request_already_exists({INTEGRATION_REF: INTEGRATION}):
            if mr.mr_info.hash == apps_hash:
                logging.info(
                    f"Found an open MR for {INTEGRATION} and it's up-to-date - doing nothing."
                )
                return None
            logging.info(f"Found an outdated MR for {INTEGRATION} - closing it.")
            self._vcs.close_app_interface_mr(
                mr.raw, "Closing this MR because it's outdated."
            )
            # don't open a new MR right now, because the deletion of the old MRs could be
            # disabled. In this case, we would end up with multiple open MRs for the
            # same external resource.
            return None

        if not apps:
            return None

        endpoints_discovery_mr = EndpointsDiscoveryMR(
            title=self._renderer.render_title(),
            description=self._renderer.render_description(hash=apps_hash),
            labels=[LABEL] + ([AUTO_MERGE] if self._auto_merge_enabled else []),
        )
        for app in apps:
            try:
                content = self._vcs.get_file_content_from_app_interface_ref(
                    file_path=app.path
                )
            except GitlabGetError as e:
                if e.response_code == 404:
                    logging.error(
                        "The file %s does not exist anylonger. Most likely qontract-server data not in synch. This should resolve soon on its own.",
                        app.path,
                    )
                    return None
                raise e
            content = self._renderer.render_merge_request_content(
                current_content=content,
                endpoints_to_add=[item.data for item in app.endpoints_to_add],
                endpoints_to_change={
                    item.name: item.data for item in app.endpoints_to_change
                },
                endpoints_to_delete=[item.name for item in app.endpoints_to_delete],
            )
            endpoints_discovery_mr.add_commit(
                path=f"data/{app.path.lstrip('/')}",
                content=content,
                msg=f"endpoints-discovery: update application endpoints for {app.name}",
            )

        logging.info("Open MR for %d app(s)", len(apps))
        self._vcs.open_app_interface_merge_request(mr=endpoints_discovery_mr)

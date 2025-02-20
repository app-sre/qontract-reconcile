from gitlab.exceptions import GitlabGetError

from reconcile.fleet_labeler.merge_request import FleetLabelerUpdates
from reconcile.utils.vcs import VCS as VCSBase


class Gitlab404Error(Exception):
    pass


class VCS:
    """
    Thin abstractions of reconcile.utils.vcs module to reduce coupling and simplify tests.
    """

    def __init__(self, vcs: VCSBase):
        self._vcs = vcs

    def get_file_content_from_main(self, path: str) -> str:
        try:
            return self._vcs.get_file_content_from_app_interface_ref(
                file_path=path, ref="main"
            )
        except GitlabGetError as e:
            if e.response_code != 404:
                raise
            raise Gitlab404Error(
                f"File at ${path} does not exist yet in main branch. Maybe it is just being created with this MR?"
            ) from e

    def open_merge_request(self, path: str, content: str) -> None:
        mr = FleetLabelerUpdates(path=path, content=content)
        # Note, that VCS is initialized with dry-run flag already
        self._vcs.open_app_interface_merge_request(mr)

import logging
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from gitlab.v4.objects import ProjectMergeRequest
from pydantic import BaseModel

from reconcile.utils.merge_request_manager.parser import (
    Parser,
    ParserError,
    ParserVersionError,
)
from reconcile.utils.vcs import VCS

T = TypeVar("T", bound=BaseModel)


@dataclass
class OpenMergeRequest(Generic[T]):
    raw: ProjectMergeRequest
    mr_info: T


class MergeRequestManagerBase(Generic[T]):
    """ """

    def __init__(self, vcs: VCS, parser: Parser, mr_label: str):
        self._vcs = vcs
        self._parser = parser
        self._mr_label = mr_label
        self._open_mrs: list[OpenMergeRequest] = []
        self._open_mrs_with_problems: list[OpenMergeRequest] = []
        self._housekeeping_ran = False

    @abstractmethod
    def create_merge_request(self, data: Any) -> None:
        pass

    def _merge_request_already_exists(
        self,
        expected_data: dict[str, Any],
    ) -> OpenMergeRequest | None:
        for mr in self._open_mrs:
            mr_info_dict = mr.mr_info.dict()
            if all(mr_info_dict.get(k) == expected_data.get(k) for k in expected_data):
                return mr

        return None

    def _fetch_managed_open_merge_requests(self) -> list[ProjectMergeRequest]:
        all_open_mrs = self._vcs.get_open_app_interface_merge_requests()
        return [mr for mr in all_open_mrs if self._mr_label in mr.labels]

    def housekeeping(self) -> None:
        """
        Close bad MRs:
        - bad description format
        - wrong version
        - merge conflict

        --> if we update the template output, we automatically close
        old open MRs and replace them with new ones.
        """
        for mr in self._fetch_managed_open_merge_requests():
            attrs = mr.attributes
            desc = str(attrs.get("description") or "")
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
                mr_info = self._parser.parse(description=desc)
            except ParserVersionError:
                logging.info(
                    "Old MR version detected! Closing %s",
                    mr.attributes.get("web_url", "NO_WEBURL"),
                )
                self._vcs.close_app_interface_mr(
                    mr, "Closing this MR because it has an outdated integration version"
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
            self._open_mrs.append(OpenMergeRequest(raw=mr, mr_info=mr_info))
        self._housekeeping_ran = True

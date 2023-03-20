from dataclasses import dataclass
from typing import (
    Optional,
    Protocol,
)

from reconcile.utils.gql import GqlApi


@dataclass
class Approver:
    """
    Minimalistic wrapper for approver sources to be used in ChangeTypeContexts.
    Since we might load different approver contexts via GraphQL query classes,
    a wrapper enables us to deal with different dataclasses representing an
    approver.
    """

    org_username: str
    tag_on_merge_requests: Optional[bool] = False


class ApproverResolver(Protocol):
    def lookup_approver_by_path(self, path: str) -> Optional[Approver]:
        ...


class GqlApproverResolver:
    def __init__(self, gqlapis: list[GqlApi]):
        self.gqlapis = gqlapis

    def lookup_approver_by_path(self, path: str) -> Optional[Approver]:
        for gqlapi in self.gqlapis:
            approver = self._lookup_approver_by_path(gqlapi, path)
            if approver:
                return approver
        return None

    def _lookup_approver_by_path(self, gqlapi: GqlApi, path: str) -> Optional[Approver]:
        approvers = gqlapi.query(
            """
            query Approvers($path: String) {
                user: users_v1(path: $path) {
                    org_username
                    tag_on_merge_requests
                }
                bot: bots_v1(path: $path) {
                    org_username
                }
            }
            """,
            {"path": path},
        )
        if approvers.get("user"):
            return Approver(
                approvers["user"][0]["org_username"],
                approvers["user"][0]["tag_on_merge_requests"],
            )
        if approvers.get("bot"):
            return Approver(approvers["bot"][0]["org_username"], False)
        return None


class ApproverReachability(Protocol):
    def render_for_mr_report(self) -> str:
        ...


@dataclass
class SlackGroupApproverReachability:
    slack_group: str
    workspace: str

    def render_for_mr_report(self) -> str:
        return f"Slack group {self.slack_group}/{self.workspace}"


@dataclass
class GitlabGroupApproverReachability:
    gitlab_group: str

    def render_for_mr_report(self) -> str:
        return f"GitLab group {self.gitlab_group}"

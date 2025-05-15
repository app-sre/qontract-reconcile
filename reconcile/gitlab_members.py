import logging
from collections.abc import Callable
from typing import Any

from gitlab.v4.objects import (
    Group,
    GroupMember,
)
from pydantic import BaseModel

from reconcile import queries
from reconcile.gql_definitions.common.pagerduty_instances import (
    query as pagerduty_instances_query,
)
from reconcile.gql_definitions.common.users import query as users_query
from reconcile.gql_definitions.fragments.user import User
from reconcile.gql_definitions.gitlab_members.gitlab_instances import GitlabInstanceV1
from reconcile.gql_definitions.gitlab_members.gitlab_instances import (
    query as gitlab_instances_query,
)
from reconcile.gql_definitions.gitlab_members.permissions import (
    PermissionGitlabGroupMembershipV1,
)
from reconcile.gql_definitions.gitlab_members.permissions import (
    query as permissions_query,
)
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.differ import diff_mappings
from reconcile.utils.exceptions import AppInterfaceSettingsError
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.pagerduty_api import (
    PagerDutyMap,
    get_pagerduty_map,
    get_usernames_from_pagerduty,
)
from reconcile.utils.secret_reader import SecretReader

QONTRACT_INTEGRATION = "gitlab-members"


class GitlabUser(BaseModel):
    user: str
    access_level: int


class CurrentStateSpec(BaseModel):
    members: dict[str, GroupMember]

    class Config:
        arbitrary_types_allowed = True


class DesiredStateSpec(BaseModel):
    members: dict[str, GitlabUser]

    class Config:
        arbitrary_types_allowed = True


CurrentState = dict[str, CurrentStateSpec]
DesiredState = dict[str, DesiredStateSpec]


def get_current_state(
    instance: GitlabInstanceV1, gl: GitLabApi, gitlab_groups_map: dict[str, Group]
) -> CurrentState:
    """Get current gitlab group members for all managed groups."""
    return {
        g: CurrentStateSpec(
            members={u.username: u for u in gl.get_group_members(gitlab_groups_map[g])},
        )
        for g in instance.managed_groups
    }


def add_or_update_user(
    desired_state_spec: DesiredStateSpec, gitlab_user: GitlabUser
) -> None:
    existing_user = desired_state_spec.members.get(gitlab_user.user)
    if not existing_user:
        desired_state_spec.members[gitlab_user.user] = gitlab_user
    else:
        existing_user.access_level = max(
            existing_user.access_level, gitlab_user.access_level
        )


def get_desired_state(
    instance: GitlabInstanceV1,
    pagerduty_map: PagerDutyMap,
    permissions: list[PermissionGitlabGroupMembershipV1],
    all_users: list[User],
) -> DesiredState:
    """Fetch all desired gitlab users from app-interface."""
    desired_group_members: DesiredState = {
        g: build_desired_state_spec(g, permissions, pagerduty_map, all_users)
        for g in instance.managed_groups
    }
    return desired_group_members


def build_desired_state_spec(
    group_name: str,
    permissions: list[PermissionGitlabGroupMembershipV1],
    pagerduty_map: PagerDutyMap,
    all_users: list[User],
) -> DesiredStateSpec:
    desired_state_spec = DesiredStateSpec(members={})
    for p in permissions:
        if p.group == group_name:
            p_access_level = GitLabApi.get_access_level(p.access)
            for r in p.roles or []:
                for u in (r.users or []) + (r.bots or []):
                    gu = GitlabUser(user=u.org_username, access_level=p_access_level)
                    add_or_update_user(desired_state_spec, gu)
            if p.pagerduty:
                usernames_from_pagerduty = get_usernames_from_pagerduty(
                    p.pagerduty,
                    all_users,
                    group_name,
                    pagerduty_map,
                    get_username_method=lambda u: u.org_username,
                )
                for u in usernames_from_pagerduty:
                    gu = GitlabUser(user=u, access_level=p_access_level)
                    add_or_update_user(desired_state_spec, gu)
    return desired_state_spec


def get_permissions(query_func: Callable) -> list[PermissionGitlabGroupMembershipV1]:
    """Get all permissions from app-interface."""
    return [
        p
        for p in permissions_query(query_func=query_func).permissions
        if isinstance(p, PermissionGitlabGroupMembershipV1)
    ]


def get_gitlab_instance(query_func: Callable) -> GitlabInstanceV1:
    """Get a GitLab instance."""
    if instances := gitlab_instances_query(query_func=query_func).instances:
        if len(instances) != 1:
            raise AppInterfaceSettingsError("More than one gitlab instance found!")
        return instances[0]
    raise AppInterfaceSettingsError("No gitlab instance found!")


def get_managed_groups_map(group_names: list[str], gl: GitLabApi) -> dict[str, Group]:
    gitlab_groups = {group_name: gl.get_group(group_name) for group_name in group_names}
    return gitlab_groups


@defer
def run(
    dry_run: bool,
    defer: Callable | None = None,
) -> None:
    gqlapi = gql.get_api()
    # queries
    instance = get_gitlab_instance(gqlapi.query)
    permissions = get_permissions(gqlapi.query)
    all_users = users_query(query_func=gqlapi.query).users or []
    pagerduty_instances = pagerduty_instances_query(
        query_func=gqlapi.query
    ).pagerduty_instances

    # APIs
    secret_reader = SecretReader(queries.get_secret_reader_settings())
    # this will be address later. requires a refactoring of GitLapApi - APPSRE-6611
    settings = queries.get_app_interface_settings()
    gl = GitLabApi(
        instance={
            "url": instance.url,
            "token": SecretReader.to_dict(instance.token),
            "sslVerify": instance.ssl_verify,
        },
        settings=settings,
    )
    if defer:
        defer(gl.cleanup)
    pagerduty_map = get_pagerduty_map(
        secret_reader, pagerduty_instances=pagerduty_instances
    )
    managed_groups_map = get_managed_groups_map(instance.managed_groups, gl)
    current_state = get_current_state(instance, gl, managed_groups_map)
    desired_state = get_desired_state(instance, pagerduty_map, permissions, all_users)
    for group_name in instance.managed_groups:
        reconcile_gitlab_members(
            current_state_spec=current_state.get(group_name),
            desired_state_spec=desired_state.get(group_name),
            group=managed_groups_map.get(group_name),
            gl=gl,
            dry_run=dry_run,
        )


def reconcile_gitlab_members(
    current_state_spec: CurrentStateSpec | None,
    desired_state_spec: DesiredStateSpec | None,
    group: Group | None,
    gl: GitLabApi,
    dry_run: bool,
) -> None:
    if current_state_spec and desired_state_spec and group:
        diff_data = diff_mappings(
            current=current_state_spec.members,
            desired=desired_state_spec.members,
            equal=lambda current, desired: current.access_level == desired.access_level,
        )
        for key, gitlab_user in diff_data.add.items():
            logging.info([
                key,
                "add_user_to_group",
                group.name,
                gl.get_access_level_string(gitlab_user.access_level),
            ])
            if not dry_run:
                gl.add_group_member(group, gitlab_user)
        for key, group_member in diff_data.delete.items():
            logging.info([
                key,
                "remove_user_from_group",
                group.name,
            ])
            if not dry_run:
                gl.remove_group_member(group, group_member.id)
        for key, diff_pair in diff_data.change.items():
            logging.info([
                key,
                "change_access",
                group.name,
                gl.get_access_level_string(diff_pair.desired.access_level),
            ])
            if not dry_run:
                gl.change_access(diff_pair.current, diff_pair.desired.access_level)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    gqlapi = gql.get_api()
    return {
        "instance": get_gitlab_instance(gqlapi.query).dict(),
        "permissions": [p.dict() for p in get_permissions(gqlapi.query)],
    }

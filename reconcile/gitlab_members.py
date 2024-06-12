import enum
import logging
from collections.abc import Callable
from typing import Any

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
    access_level: str


State = dict[str, list[GitlabUser]]


class Action(enum.Enum):
    add_user_to_group = enum.auto()
    remove_user_from_group = enum.auto()
    change_access = enum.auto()


class Diff(BaseModel):
    action: Action
    group: str
    user: str
    access_level: str


def get_current_state(instance: GitlabInstanceV1, gl: GitLabApi) -> State:
    """Get current gitlab group members for all managed groups."""
    return {
        g: [
            GitlabUser(user=u["user"], access_level=u["access_level"])
            for u in gl.get_group_members(g)
        ]
        for g in instance.managed_groups
    }


def add_or_update_user(
    group_members: State, group_name: str, gitlab_user: GitlabUser
) -> None:
    existing_users = [
        gu for gu in group_members[group_name] if gu.user == gitlab_user.user
    ]
    if not existing_users:
        group_members[group_name].append(gitlab_user)
    else:
        existing_user = existing_users[0]
        if GitLabApi.get_access_level(
            existing_user.access_level
        ) < GitLabApi.get_access_level(gitlab_user.access_level):
            existing_user.access_level = gitlab_user.access_level


def get_desired_state(
    instance: GitlabInstanceV1,
    pagerduty_map: PagerDutyMap,
    permissions: list[PermissionGitlabGroupMembershipV1],
    all_users: list[User],
) -> State:
    """Fetch all desired gitlab users from app-interface."""
    desired_group_members: State = {g: [] for g in instance.managed_groups}
    for g in desired_group_members:
        for p in permissions:
            if p.group == g:
                for r in p.roles or []:
                    for u in (r.users or []) + (r.bots or []):
                        gu = GitlabUser(user=u.org_username, access_level=p.access)
                        add_or_update_user(desired_group_members, g, gu)
                if p.pagerduty:
                    usernames_from_pagerduty = get_usernames_from_pagerduty(
                        p.pagerduty,
                        all_users,
                        g,
                        pagerduty_map,
                        get_username_method=lambda u: u.org_username,
                    )
                    for u in usernames_from_pagerduty:
                        gu = GitlabUser(user=u, access_level=p.access)
                        add_or_update_user(desired_group_members, g, gu)

    return desired_group_members


def calculate_diff(current_state: State, desired_state: State) -> list[Diff]:
    """Compare current and desired state and return all differences."""
    diff: list[Diff] = []
    diff += subtract_states(desired_state, current_state, Action.add_user_to_group)
    diff += subtract_states(current_state, desired_state, Action.remove_user_from_group)
    diff += check_access(current_state, desired_state)
    return diff


def subtract_states(
    from_state: State, subtract_state: State, action: Action
) -> list[Diff]:
    """Return diff objects for items in from_state but not in subtract_state."""
    result = []
    for f_group, f_users in from_state.items():
        s_group = subtract_state[f_group]
        for f_user in f_users:
            found = False
            for s_user in s_group:
                if f_user.user != s_user.user:
                    continue
                found = True
                break
            if not found:
                result.append(
                    Diff(
                        action=action,
                        group=f_group,
                        user=f_user.user,
                        access_level=f_user.access_level,
                    )
                )
    return result


def check_access(current_state: State, desired_state: State) -> list[Diff]:
    """Return diff objects for item where access level is different."""
    result = []
    for d_group, d_users in desired_state.items():
        c_group = current_state[d_group]
        for d_user in d_users:
            for c_user in c_group:
                if d_user.user == c_user.user:
                    if d_user.access_level != c_user.access_level:
                        result.append(
                            Diff(
                                action=Action.change_access,
                                group=d_group,
                                user=c_user.user,
                                access_level=d_user.access_level,
                            )
                        )
                    break
    return result


def act(diff: Diff, gl: GitLabApi) -> None:
    """Apply a diff object."""
    if diff.action == Action.remove_user_from_group:
        gl.remove_group_member(diff.group, diff.user)
    if diff.action == Action.add_user_to_group:
        gl.add_group_member(diff.group, diff.user, diff.access_level)
    if diff.action == Action.change_access:
        gl.change_access(diff.group, diff.user, diff.access_level)


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

    # act
    current_state = get_current_state(instance, gl)
    desired_state = get_desired_state(instance, pagerduty_map, permissions, all_users)
    diffs = calculate_diff(current_state, desired_state)

    for diff in diffs:
        logging.info(diff)

        if not dry_run:
            act(diff, gl)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    gqlapi = gql.get_api()
    return {
        "instance": get_gitlab_instance(gqlapi.query).dict(),
        "permissions": [p.dict() for p in get_permissions(gqlapi.query)],
    }

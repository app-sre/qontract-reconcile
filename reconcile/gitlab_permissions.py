import itertools
import logging
from dataclasses import dataclass
from typing import Any, cast

from gitlab.exceptions import GitlabGetError
from gitlab.v4.objects import (
    Project,
    SharedProject,
)
from sretoolbox.utils import threaded

from reconcile import queries
from reconcile.utils import batches
from reconcile.utils.defer import defer
from reconcile.utils.differ import diff_mappings
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.unleash import get_feature_toggle_state

QONTRACT_INTEGRATION = "gitlab-permissions"
APP_SRE_GROUP_NAME = "app-sre"
GROUP_ACCESS = "maintainer"
PAGE_SIZE = 100


@dataclass
class GroupSpec:
    group_name: str
    group_access_level: int


class GroupAccessLevelError(Exception):
    pass


class GroupPermissionHandler:
    def __init__(
        self, gl: GitLabApi, group_name: str, access: str, dry_run: bool
    ) -> None:
        self.gl = gl
        self.dry_run = dry_run
        self.access_level_string = access
        self.access_level = self.gl.get_access_level(access)
        self.group = self.gl.get_group(group_name)

    def run(self, repos: list[str]) -> None:
        # filter projects belonging to the same group and remove it from the state data
        filtered_project_repos = self.filter_group_owned_projects(repos)
        desired_state = {
            project_repo_url: GroupSpec(self.group.name, self.access_level)
            for project_repo_url in filtered_project_repos
        }
        # get all projects shared with group
        shared_projects = self.group.shared_projects.list(iterator=True)
        current_state = {
            project.web_url: self.extract_group_spec(cast(SharedProject, project))
            for project in shared_projects
        }
        self.reconcile(desired_state, current_state)

    def filter_group_owned_projects(self, repos: list[str]) -> set[str]:
        # get only the projects that are owned by  group and its sub groups
        query = {"with_shared": False, "include_subgroups": True}
        group_owned_projects = self.group.projects.list(
            query_parameters=query,
            iterator=True,
        )
        group_owned_repo_list = {project.web_url for project in group_owned_projects}
        return set(repos) - group_owned_repo_list

    def extract_group_spec(self, project: SharedProject) -> GroupSpec:
        return next(
            GroupSpec(
                group_name=self.group.name,
                group_access_level=group["group_access_level"],
            )
            for group in project.shared_with_groups
            if group["group_id"] == self.group.id
        )

    def can_share_project(self, project: Project) -> bool:
        # check if user have access greater or equal access to be shared with the group
        try:
            user = project.members_all.get(id=self.gl.user.id)
        except GitlabGetError:
            return False
        return user.access_level >= self.access_level

    def reconcile(
        self,
        desired_state: dict[str, GroupSpec],
        current_state: dict[str, GroupSpec],
    ) -> None:
        # gather list of app-interface managed repos
        instance = queries.get_gitlab_instance()
        managed_repos = {
            f"{instance['url']}/{project_request['group']}/{r}"
            for project_request in instance.get("projectRequests", [])
            for r in project_request.get("projects", [])
        }

        # get the diff data
        diff_data = diff_mappings(
            current=current_state,
            desired=desired_state,
            equal=lambda current, desired: current.group_access_level
            == desired.group_access_level,
        )
        errors: list[Exception] = []
        for repo in diff_data.add:
            project = self.gl.get_project(repo)
            if not project and repo in managed_repos:
                logging.info(
                    f"New app-interface managed repository {repo} hasn't been created yet - skipping"
                )
                continue
            if not self.can_share_project(project):
                errors.append(
                    GroupAccessLevelError(
                        f"{repo} is not shared with {self.gl.user.username} as {self.access_level_string}"
                    )
                )
                continue
            logging.info([
                "share",
                repo,
                self.group.name,
                self.access_level_string,
            ])
            if not self.dry_run:
                self.gl.share_project_with_group(
                    project=project,
                    group_id=self.group.id,
                    access_level=self.access_level,
                )
        for repo in diff_data.change:
            project = self.gl.get_project(repo)
            if not self.can_share_project(project):
                errors.append(
                    GroupAccessLevelError(
                        f"{repo} is not shared with {self.gl.user.username} as {self.access_level_string}"
                    )
                )
                continue
            logging.info([
                "reshare",
                repo,
                self.group.name,
                self.access_level_string,
            ])
            if not self.dry_run:
                self.gl.share_project_with_group(
                    project=project,
                    group_id=self.group.id,
                    access_level=self.access_level,
                    reshare=True,
                )
        if errors:
            raise ExceptionGroup("Reconcile errors occurred", errors)


def get_members_to_add(repo, gl, app_sre):
    maintainers = get_all_app_sre_maintainers(repo, gl, app_sre)
    if maintainers is None:
        return []
    if gl.user.username not in maintainers:
        logging.error(f"'{repo}' is not shared with {gl.user.username} as 'Maintainer'")
        return []
    members_to_add = [
        {"user": u, "repo": repo} for u in app_sre if u.username not in maintainers
    ]
    return members_to_add


def get_all_app_sre_maintainers(repo, gl, app_sre):
    app_sre_user_ids = [user.id for user in app_sre]
    chunks = batches.batched(app_sre_user_ids, PAGE_SIZE)
    app_sre_maintainers = (
        gl.get_project_maintainers(repo, query=create_user_ids_query(chunk))
        for chunk in chunks
    )
    return list(itertools.chain.from_iterable(app_sre_maintainers))


def create_user_ids_query(ids):
    return {"user_ids": ",".join(str(id) for id in ids)}


@defer
def run(dry_run, thread_pool_size=10, defer=None):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    gl = GitLabApi(instance, settings=settings)
    if defer:
        defer(gl.cleanup)
    repos = queries.get_repos(server=gl.server, exclude_manage_permissions=True)
    share_with_group_enabled = get_feature_toggle_state(
        "gitlab-permissions-share-with-group",
        default=False,
    )
    if share_with_group_enabled:
        group_permission_handler = GroupPermissionHandler(
            gl=gl, group_name=APP_SRE_GROUP_NAME, access=GROUP_ACCESS, dry_run=dry_run
        )
        group_permission_handler.run(repos=repos)
    else:
        share_project_with_group_members(gl, repos, thread_pool_size, dry_run)


def share_project_with_group_members(
    gl: GitLabApi, repos: list[str], thread_pool_size: int, dry_run: bool
) -> None:
    app_sre = gl.get_app_sre_group_users()
    results = threaded.run(
        get_members_to_add, repos, thread_pool_size, gl=gl, app_sre=app_sre
    )
    members_to_add = list(itertools.chain.from_iterable(results))
    for m in members_to_add:
        logging.info(["add_maintainer", m["repo"], m["user"].username])
        if not dry_run:
            gl.add_project_member(m["repo"], m["user"])


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    instance = queries.get_gitlab_instance()
    return {
        "instance": instance,
        "repos": queries.get_repos(server=instance["url"]),
    }

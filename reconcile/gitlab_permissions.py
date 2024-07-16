import itertools
import logging
from dataclasses import dataclass
from typing import Any

from gitlab.v4.objects import Project
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
        # get repos not owned by the group
        # repo_to_project_mapping = {
        #     repo:self.gl.get_project(repo)
        #     for repo in repos
        # }
        
        # non_group_owned_projects = {
        #     repo:repo_to_project_mapping[repo]
        #     for repo in repo_to_project_mapping
        #     if self.gl.group.id != repo_to_project_mapping[repo].
        # }
        non_group_owned_project_repos = {
            repo
            for repo in repos
            if not self.gl.is_group_project_owner(
                group_name=self.group.name, repo_url=repo
            )
        }
        #testing
        non_group_owned_project_repos= {"https://gitlab.cee.redhat.com/mekhan/app-interface"}
        #testing
        desired_state = {
            project_repo_url: GroupSpec(self.group.name, self.access_level)
            for project_repo_url in non_group_owned_project_repos
        }
        shared_projects = self.gl.get_shared_projects(self.group)
        current_state = {
            project_repo_url: GroupSpec(
                shared_projects[project_repo_url]["group_name"],
                shared_projects[project_repo_url]["group_access_level"],
            )
            for project_repo_url in shared_projects
        }
        self.reconcile(desired_state, current_state)

    def can_share_project(self, project: Project) -> bool:
        # check if user have access greater or equal access required
        user = project.members_all.get(id=self.gl.user.id)
        return user.access_level >= self.access_level

    def reconcile(
        self,
        desired_state: dict[str, GroupSpec],
        current_state: dict[str, GroupSpec],
    ) -> None:
        # get the diff data
        diff_data = diff_mappings(
            current=current_state,
            desired=desired_state,
            equal=lambda current, desired: current.group_access_level
            == desired.group_access_level,
        )

        for repo in diff_data.add:
            project = self.gl.get_project(repo)
            logging.debug(self.gl.get_project("https://gitlab.cee.redhat.com/app-sre/terraform-repo-tekton").__dict__)
            if not self.can_share_project(project):
                logging.error(
                    "%s is not shared with %s as %s",
                    repo,
                    self.gl.user.username,
                    self.access_level_string,
                )
                return None
            logging.info([
                f"share_group_{self.group.name}_as_{self.access_level_string}",
                repo,
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
                logging.error(
                    "%s is not shared with %s as %s",
                    repo,
                    self.gl.user.username,
                    self.group.name,
                )
                return None
            logging.info([
                f"reshare_group_{self.group.name}_as_{self.access_level_string}",
                repo,
            ])
            if not self.dry_run:
                self.gl.share_project_with_group(
                    project=project,
                    group_id=self.group.id,
                    access_level=self.access_level,
                    reshare=True,
                )


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

import logging
import os
import re
from collections.abc import (
    Iterable,
    Set,
)
from functools import cached_property
from operator import (
    attrgetter,
    itemgetter,
)
from typing import (
    Any,
    Optional,
    TypedDict,
)
from urllib.parse import urlparse

import gitlab
import urllib3
from gitlab.v4.objects import (
    CurrentUser,
    Group,
    Project,
    ProjectIssue,
    ProjectMergeRequest,
    ProjectMergeRequestNote,
)
from sretoolbox.utils import retry

from reconcile.utils.metrics import gitlab_request
from reconcile.utils.secret_reader import SecretReader

# The following line will suppress
# `InsecureRequestWarning: Unverified HTTPS request is being made`
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


MR_DESCRIPTION_COMMENT_ID = 0

# The default value is there for unit test
INTEGRATION_NAME = os.getenv("INTEGRATION_NAME", "")
DEFAULT_MAIN_BRANCH = "master"


class MRState:
    """
    Data class to help users selecting the correct Merge Request state.
    """

    # Values taken from https://docs.gitlab.com/ee/api/merge_requests.html
    OPENED = "opened"
    CLOSED = "closed"
    LOCKED = "locked"
    MERGED = "merged"
    ALL = "all"


class MRStatus:
    """
    Data class to help users selecting the correct Merge Request status.
    """

    # Values taken from https://docs.gitlab.com/ee/api/merge_requests.html#single-merge-request-response-notes
    UNCHECKED = "unchecked"
    CHECKING = "checking"
    CAN_BE_MERGED = "can_be_merged"
    CANNOT_BE_MERGED = "cannot_be_merged"
    CANNOT_BE_MERGED_RECHECK = "cannot_be_merged_recheck"


GROUP_BOT_NAME_REGEX = re.compile(r"group_.+_bot_.+")


class GLGroupMember(TypedDict):
    user: str
    access_level: str


class GitLabApi:  # pylint: disable=too-many-public-methods
    def __init__(
        self,
        instance,
        project_id=None,
        settings=None,
        secret_reader=None,
        project_url=None,
        saas_files=None,
        timeout=30,
    ):
        self.server = instance["url"]
        if not secret_reader:
            secret_reader = SecretReader(settings=settings)
        token = secret_reader.read(instance["token"])
        ssl_verify = instance["sslVerify"]
        if ssl_verify is None:
            ssl_verify = True
        self.gl = gitlab.Gitlab(
            self.server, private_token=token, ssl_verify=ssl_verify, timeout=timeout
        )
        self._auth()
        self.user: CurrentUser = self.gl.user
        if project_id is None:
            # When project_id is not provide, we try to get the project
            # using the project_url
            if project_url is not None:
                parsed_project_url = urlparse(project_url)
                name_with_namespace = parsed_project_url.path.strip("/")
                gitlab_request.labels(integration=INTEGRATION_NAME).inc()
                self.project = self.gl.projects.get(name_with_namespace)
        else:
            gitlab_request.labels(integration=INTEGRATION_NAME).inc()
            self.project = self.gl.projects.get(project_id)
        self.saas_files = saas_files

    @cached_property
    def project_main_branch(self) -> str:
        return next(
            (b.name for b in self.project.branches.list() if b.default),
            DEFAULT_MAIN_BRANCH,
        )

    @property
    def main_branch(self) -> str:
        return self.project_main_branch if self.project else DEFAULT_MAIN_BRANCH

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cleanup()

    def cleanup(self):
        """
        Close gl session.
        """
        self.gl.session.close()

    @retry()
    def _auth(self):
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        self.gl.auth()

    def create_branch(self, new_branch, source_branch):
        data = {"branch": new_branch, "ref": source_branch}
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        self.project.branches.create(data)

    def delete_branch(self, branch):
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        self.project.branches.delete(branch)

    def create_commit(self, branch_name, commit_message, actions):
        """
        actions is a list of 'action' dictionaries. The 'action' dict is
        documented here: https://docs.gitlab.com/ee/api/commits.html
                         #create-a-commit-with-multiple-files-and-actions
        """

        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        self.project.commits.create({
            "branch": branch_name,
            "commit_message": commit_message,
            "actions": actions,
        })

    def create_file(self, branch_name, file_path, commit_message, content):
        data = {
            "branch": branch_name,
            "commit_message": commit_message,
            "actions": [
                {"action": "create", "file_path": file_path, "content": content}
            ],
        }
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        self.project.commits.create(data)

    def delete_file(self, branch_name, file_path, commit_message):
        data = {
            "branch": branch_name,
            "commit_message": commit_message,
            "actions": [{"action": "delete", "file_path": file_path}],
        }
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        self.project.commits.create(data)

    def update_file(self, branch_name, file_path, commit_message, content):
        data = {
            "branch": branch_name,
            "commit_message": commit_message,
            "actions": [
                {"action": "update", "file_path": file_path, "content": content}
            ],
        }
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        self.project.commits.create(data)

    def create_mr(
        self,
        source_branch,
        target_branch,
        title,
        remove_source_branch=True,
        labels=None,
    ):
        if labels is None:
            labels = []
        data = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "remove_source_branch": str(remove_source_branch),
            "labels": labels,
        }
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        return self.project.mergerequests.create(data)

    def mr_exists(self, title: str) -> bool:
        mrs = self.get_merge_requests(state=MRState.OPENED)
        # since we are using a naming convention for these MRs
        # we can determine if a pending MR exists based on the title
        return any(mr.title == title for mr in mrs)

    @retry()
    def get_project_maintainers(self, repo_url: str | None = None) -> list[str] | None:
        if repo_url is None:
            project = self.project
        else:
            project = self.get_project(repo_url)
        if project is None:
            return None
        members = self.get_items(project.members.all)
        return [m.username for m in members if m.access_level >= 40]

    def get_app_sre_group_users(self):
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        app_sre_group = self.gl.groups.get("app-sre")
        return self.get_items(app_sre_group.members.list)

    def get_group_if_exists(self, group_name: str) -> Group | None:
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        try:
            return self.gl.groups.get(group_name)
        except gitlab.exceptions.GitlabGetError:
            return None

    @staticmethod
    def _is_bot_username(username: str) -> bool:
        """crudely checking for the username

        as gitlab-python require a major upgrade to use the billable members apis
        https://python-gitlab.readthedocs.io/en/stable/gl_objects/groups.html#id11 lists the api
        billable_membersis the attribute that provides billable members of groups

        the second api is https://python-gitlab.readthedocs.io/en/stable/gl_objects/group_access_tokens.html
        which provides a list of access tokens as well as their assigned users

        those apis are not avaliable in python-gitlab v1.x
        """
        return GROUP_BOT_NAME_REGEX.match(username) is not None

    def get_group_members(self, group_name: str) -> list[GLGroupMember]:
        group = self.get_group_if_exists(group_name)
        if group is None:
            logging.error(group_name + " group not found")
            return []
        else:
            return [
                {
                    "user": m.username,
                    "access_level": self.get_access_level_string(m.access_level),
                }
                for m in self.get_items(group.members.list)
                if not self._is_bot_username(m.username)
            ]

    def add_project_member(self, repo_url, user, access="maintainer"):
        project = self.get_project(repo_url)
        if project is None:
            return
        access_level = self.get_access_level(access)
        try:
            project.members.create({"user_id": user.id, "access_level": access_level})
        except gitlab.exceptions.GitlabCreateError:
            member = project.members.get(user.id)
            member.access_level = access_level
            member.save()

    def add_group_member(self, group_name, username, access):
        group = self.get_group_if_exists(group_name)
        if not group:
            logging.error(group_name + " group not found")
        else:
            user = self.get_user(username)
            access_level = self.get_access_level(access)
            if user is not None:
                gitlab_request.labels(integration=INTEGRATION_NAME).inc()
                try:
                    group.members.create({
                        "user_id": user.id,
                        "access_level": access_level,
                    })
                except gitlab.exceptions.GitlabCreateError:
                    gitlab_request.labels(integration=INTEGRATION_NAME).inc()
                    member = group.members.get(user.id)
                    member.access_level = access_level

    def remove_group_member(self, group_name, username):
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        group = self.gl.groups.get(group_name)
        user = self.get_user(username)
        if user is not None:
            gitlab_request.labels(integration=INTEGRATION_NAME).inc()
            group.members.delete(user.id)

    def change_access(self, group, username, access):
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        group = self.gl.groups.get(group)
        user = self.get_user(username)
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        member = group.members.get(user.id)
        member.access_level = self.get_access_level(access)
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        member.save()

    @staticmethod
    def get_access_level_string(access_level):
        if access_level == gitlab.OWNER_ACCESS:
            return "owner"
        if access_level == gitlab.MAINTAINER_ACCESS:
            return "maintainer"
        if access_level == gitlab.DEVELOPER_ACCESS:
            return "developer"
        if access_level == gitlab.REPORTER_ACCESS:
            return "reporter"
        if access_level == gitlab.GUEST_ACCESS:
            return "guest"

    @staticmethod
    def get_access_level(access):
        access = access.lower()
        if access == "owner":
            return gitlab.OWNER_ACCESS
        if access == "maintainer":
            return gitlab.MAINTAINER_ACCESS
        if access == "developer":
            return gitlab.DEVELOPER_ACCESS
        if access == "reporter":
            return gitlab.REPORTER_ACCESS
        if access == "guest":
            return gitlab.GUEST_ACCESS

    def get_group_id_and_projects(self, group_name: str) -> tuple[str, list[str]]:
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        group = self.gl.groups.get(group_name)
        return group.id, [p.name for p in self.get_items(group.projects.list)]

    def create_project(self, group_id, project):
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        self.gl.projects.create({"name": project, "namespace_id": group_id})

    def get_project_url(self, group, project):
        return f"{self.server}/{group}/{project}"

    @retry()
    def get_project(self, repo_url: str) -> Project | None:
        repo = repo_url.replace(self.server + "/", "")
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        try:
            project = self.gl.projects.get(repo)
        except gitlab.exceptions.GitlabGetError:
            logging.warning(f"{repo_url} not found")
            project = None
        return project

    def get_issues(self, state):
        return self.get_items(self.project.issues.list, state=state)

    def get_merge_request(self, mr_id):
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        return self.project.mergerequests.get(mr_id)

    def get_merge_requests(self, state):
        return self.get_items(self.project.mergerequests.list, state=state)

    def get_merge_request_label_events(self, mr: ProjectMergeRequest):
        return self.get_items(mr.resourcelabelevents.list)

    def get_merge_request_pipelines(self, mr: ProjectMergeRequest) -> list[dict]:
        return sorted(
            self.get_items(mr.pipelines), key=lambda x: x["created_at"], reverse=True
        )

    @staticmethod
    def get_merge_request_changed_paths(
        merge_request: ProjectMergeRequest,
    ) -> list[str]:
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        changes = merge_request.changes()["changes"]
        changed_paths = set()
        for change in changes:
            old_path = change["old_path"]
            new_path = change["new_path"]
            changed_paths.add(old_path)
            changed_paths.add(new_path)
        return list(changed_paths)

    @staticmethod
    def get_merge_request_author_username(
        merge_request: ProjectMergeRequest,
    ) -> str:
        return merge_request.author["username"]

    @staticmethod
    def get_merge_request_comments(
        merge_request: ProjectMergeRequest,
        include_description: bool = False,
    ) -> list[dict[str, Any]]:
        comments = []
        if include_description:
            comments.append({
                "username": merge_request.author["username"],
                "body": merge_request.description,
                "created_at": merge_request.created_at,
                "id": MR_DESCRIPTION_COMMENT_ID,
            })
        for note in GitLabApi.get_items(merge_request.notes.list):
            if note.system:
                continue
            comments.append({
                "username": note.author["username"],
                "body": note.body,
                "created_at": note.created_at,
                "id": note.id,
                "note": note,
            })
        return comments

    @staticmethod
    def delete_comment(note: ProjectMergeRequestNote) -> None:
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        note.delete()

    def delete_merge_request_comments(
        self,
        merge_request: ProjectMergeRequest,
        startswith: str,
    ) -> None:
        comments = self.get_merge_request_comments(merge_request)
        for c in comments:
            body = c["body"] or ""
            if c["username"] == self.user.username and body.startswith(startswith):
                self.delete_comment(c["note"])

    @retry()
    def get_project_labels(self) -> Set[str]:
        return {ln.name for ln in self.get_items(self.project.labels.list)}

    @staticmethod
    def add_label_to_merge_request(
        merge_request: ProjectMergeRequest,
        label: str,
    ) -> None:
        # merge_request maybe stale, refresh it to reduce the possibility of labels overwriting
        GitLabApi.refresh_labels(merge_request)

        labels = merge_request.labels
        if label in labels:
            return
        labels.append(label)
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        merge_request.save()

    @staticmethod
    def add_labels_to_merge_request(
        merge_request: ProjectMergeRequest,
        labels: Iterable[str],
    ):
        """Adds labels to a Merge Request"""
        # merge_request maybe stale, refresh it to reduce the possibility of labels overwriting
        GitLabApi.refresh_labels(merge_request)

        new_labels = set(labels) - set(merge_request.labels)
        if not new_labels:
            return
        merge_request.labels.extend(new_labels)
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        merge_request.save()

    @staticmethod
    def set_labels_on_merge_request(
        merge_request: ProjectMergeRequest,
        labels: Iterable[str],
    ) -> None:
        """Set labels to a Merge Request"""
        desired_labels = set(labels)
        current_labels = set(merge_request.labels)
        labels_to_add = desired_labels - current_labels
        labels_to_remove = current_labels - desired_labels

        if not labels_to_add and not labels_to_remove:
            return

        # merge_request maybe stale, refresh it to reduce the possibility of labels overwriting
        GitLabApi.refresh_labels(merge_request)

        refreshed_current_labels = set(merge_request.labels)
        new_desired_labels = (
            refreshed_current_labels - labels_to_remove
        ) | labels_to_add

        if new_desired_labels == refreshed_current_labels:
            return

        merge_request.labels = list(new_desired_labels)
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        merge_request.save()

    @staticmethod
    def add_comment_to_merge_request(
        merge_request: ProjectMergeRequest,
        body: str,
    ) -> None:
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        merge_request.notes.create({"body": body})

    @staticmethod
    def get_items(method, **kwargs):
        all_items = []
        page = 1
        while True:
            gitlab_request.labels(integration=INTEGRATION_NAME).inc()
            items = method(page=page, per_page=100, **kwargs)
            all_items.extend(items)
            if len(items) < 100:
                break
            page += 1

        return all_items

    def create_label(self, label_text: str, label_color: str) -> None:
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        self.project.labels.create({"name": label_text, "color": label_color})

    @staticmethod
    def refresh_labels(item: ProjectMergeRequest | ProjectIssue):
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        refreshed_item = item.manager.get(item.get_id())
        item.labels = refreshed_item.labels

    @staticmethod
    def add_label_with_note(
        item: ProjectMergeRequest | ProjectIssue,
        label: str,
    ) -> None:
        # item maybe stale, refresh it to reduce the possibility of labels overwriting
        GitLabApi.refresh_labels(item)

        labels = item.labels
        if label in labels:
            return
        labels.append(label)
        note_body = (
            f"item has been marked as {label}. " f"to remove say `/{label} cancel`"
        )
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        item.notes.create({"body": note_body})
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        item.save()

    @staticmethod
    def remove_label(
        item: ProjectMergeRequest | ProjectIssue,
        label: str,
    ):
        # item maybe stale, refresh it to reduce the possibility of labels overwriting
        GitLabApi.refresh_labels(item)

        labels = item.labels
        if label not in labels:
            return
        labels.remove(label)
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        item.save()

    @staticmethod
    def remove_labels(
        item: ProjectMergeRequest | ProjectIssue,
        labels: Iterable[str],
    ):
        # item maybe stale, refresh it to reduce the possibility of labels overwriting
        GitLabApi.refresh_labels(item)

        current_labels = set(item.labels)
        to_be_removed = set(labels) & current_labels

        if not to_be_removed:
            return
        item.labels = list(current_labels - to_be_removed)

        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        item.save()

    @staticmethod
    def close(item):
        item.state_event = "close"
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        item.save()

    def get_user(self, username):
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        user = self.gl.users.list(search=username)
        if len(user) == 0:
            logging.error(username + " user not found")
            return
        return user[0]

    @retry()
    def get_project_hooks(self, repo_url):
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        p = self.get_project(repo_url)
        if p is None:
            return []
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        return p.hooks.list(per_page=100)

    def create_project_hook(self, repo_url, data):
        p = self.get_project(repo_url)
        if p is None:
            return
        url = data["job_url"]
        trigger = data["trigger"]
        hook = {
            "url": url,
            "enable_ssl_verification": 1,
            "note_events": int(trigger == "mr"),
            "push_events": int(trigger == "push"),
            "merge_requests_events": int(trigger == "mr"),
        }
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        p.hooks.create(hook)

    def get_repository_tree(self, ref="master"):
        """
        Wrapper around Gitlab.repository_tree() with pagination enabled.
        """
        return self.get_items(self.project.repository_tree, ref=ref, recursive=True)

    def get_file(self, path, ref="master"):
        """
        Wrapper around Gitlab.files.get() with exception handling.
        """
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        try:
            path = path.lstrip("/")
            return self.project.files.get(file_path=path, ref=ref)
        except gitlab.exceptions.GitlabGetError:
            return None

    def initiate_saas_bundle_repo(self, repo_url):
        project = self.get_project(repo_url)
        if project is None:
            return
        self.project = project
        self.create_file(
            "master",
            "README.md",
            "Initial commit",
            "Use the staging or the production branches.",
        )
        self.create_branch("staging", "master")
        self.create_branch("production", "master")

    def is_last_action_by_team(
        self, mr, team_usernames: list[str], hold_labels: list[str]
    ) -> bool:
        # what is the time of the last app-sre response?
        last_action_by_team = None
        # comments
        comments = self.get_merge_request_comments(mr)
        comments.sort(key=itemgetter("created_at"), reverse=True)
        for comment in comments:
            username = comment["username"]
            if username == self.user.username:
                continue
            if username in team_usernames:
                last_action_by_team = comment["created_at"]
                break
        # labels
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        label_events = mr.resourcelabelevents.list()
        for label in reversed(label_events):
            if label.action == "add" and label.label["name"] in hold_labels:
                username = label.user["username"]
                if username == self.user.username:
                    continue
                if username in team_usernames:
                    if not last_action_by_team:
                        last_action_by_team = label.created_at
                    else:
                        last_action_by_team = max(label.created_at, last_action_by_team)
                    break
        if not last_action_by_team:
            return False
        # possible responses from tenants (ignore the bot)
        last_action_not_by_team = None
        # commits
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        commits = list(mr.commits())
        commits.sort(key=attrgetter("created_at"), reverse=True)
        for commit in commits:
            last_action_not_by_team = commit.created_at
            break
        # comments
        for comment in comments:
            username = comment["username"]
            if username == self.user.username:
                continue
            if username not in team_usernames:
                last_action_not_by_team = comment["created_at"]
                break

        if not last_action_not_by_team:
            return True

        return last_action_not_by_team < last_action_by_team

    def is_assigned_by_team(
        self, mr: ProjectMergeRequest, team_usernames: list[str]
    ) -> bool:
        if not mr.assignee:
            return False
        last_assignment = self.last_assignment(mr)
        if not last_assignment:
            return False

        author, assignee = last_assignment[0], last_assignment[1]
        return author in team_usernames and mr.assignee["username"] == assignee

    def last_assignment(self, mr: ProjectMergeRequest) -> Optional[tuple[str, str]]:
        body_format = "assigned to @"
        notes = self.get_items(mr.notes.list)

        for note in notes:
            if not note.system:
                continue
            body = note.body
            if not body.startswith(body_format):
                continue
            assignee = body.replace(body_format, "")
            author = note.author["username"]

            return author, assignee

        return None

    def last_comment(
        self, mr: ProjectMergeRequest, exclude_bot=True
    ) -> Optional[dict[str, Any]]:
        comments = self.get_merge_request_comments(mr)
        comments.sort(key=itemgetter("created_at"), reverse=True)
        for comment in comments:
            username = comment["username"]
            if username == self.user.username and exclude_bot:
                continue
            return comment
        return None

    def get_commit_sha(self, ref: str, repo_url: str) -> str:
        gitlab_request.labels(integration=INTEGRATION_NAME).inc()
        project = self.get_project(repo_url)
        commits = project.commits.list(ref_name=ref, per_page=1)
        return commits[0].id

    def repository_compare(
        self, repo_url: str, ref_from: str, ref_to: str
    ) -> list[dict[str, Any]]:
        project = self.get_project(repo_url)
        response: Any = project.repository_compare(ref_from, ref_to)
        return response.get("commits", [])

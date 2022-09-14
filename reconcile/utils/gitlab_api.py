import logging
from typing import Any, Optional, Tuple

from operator import itemgetter, attrgetter
from urllib.parse import urlparse
from sretoolbox.utils import retry

import gitlab
from gitlab.v4.objects import ProjectMergeRequest, CurrentUser
import urllib3


from reconcile.utils.secret_reader import SecretReader


# The following line will suppress
# `InsecureRequestWarning: Unverified HTTPS request is being made`
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


MR_DESCRIPTION_COMMENT_ID = 0


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


class GitLabApi:  # pylint: disable=too-many-public-methods
    def __init__(
        self,
        instance,
        project_id=None,
        ssl_verify=True,
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
                self.project = self.gl.projects.get(name_with_namespace)
        else:
            self.project = self.gl.projects.get(project_id)
        self.saas_files = saas_files

    @retry()
    def _auth(self):
        self.gl.auth()

    def create_branch(self, new_branch, source_branch):
        data = {"branch": new_branch, "ref": source_branch}
        self.project.branches.create(data)

    def delete_branch(self, branch):
        self.project.branches.delete(branch)

    def create_commit(self, branch_name, commit_message, actions):
        """
        actions is a list of 'action' dictionaries. The 'action' dict is
        documented here: https://docs.gitlab.com/ee/api/commits.html
                         #create-a-commit-with-multiple-files-and-actions
        """

        self.project.commits.create(
            {
                "branch": branch_name,
                "commit_message": commit_message,
                "actions": actions,
            }
        )

    def create_file(self, branch_name, file_path, commit_message, content):
        data = {
            "branch": branch_name,
            "commit_message": commit_message,
            "actions": [
                {"action": "create", "file_path": file_path, "content": content}
            ],
        }
        self.project.commits.create(data)

    def delete_file(self, branch_name, file_path, commit_message):
        data = {
            "branch": branch_name,
            "commit_message": commit_message,
            "actions": [{"action": "delete", "file_path": file_path}],
        }
        self.project.commits.create(data)

    def update_file(self, branch_name, file_path, commit_message, content):
        data = {
            "branch": branch_name,
            "commit_message": commit_message,
            "actions": [
                {"action": "update", "file_path": file_path, "content": content}
            ],
        }
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
        return self.project.mergerequests.create(data)

    def mr_exists(self, title):
        mrs = self.get_merge_requests(state=MRState.OPENED)
        for mr in mrs:
            # since we are using a naming convention for these MRs
            # we can determine if a pending MR exists based on the title
            if mr.attributes.get("title") != title:
                continue

            return True

        return False

    @retry()
    def get_project_maintainers(self, repo_url=None):
        if repo_url is None:
            project = self.project
        else:
            project = self.get_project(repo_url)
        if project is None:
            return None
        members = project.members.all(all=True)
        return [m.username for m in members if m.access_level >= 40]

    def get_app_sre_group_users(self):
        app_sre_group = self.gl.groups.get("app-sre")
        return list(app_sre_group.members.list(all=True))

    def check_group_exists(self, group_name):
        groups = self.gl.groups.list(all=True)
        group_names = list(map(lambda x: x.name, groups))
        if group_name not in group_names:
            return False
        return True

    def get_group_members(self, group_name):
        if not self.check_group_exists(group_name):
            logging.error(group_name + " group not found")
            return []
        group = self.gl.groups.get(group_name)
        return [
            {
                "user": m.username,
                "access_level": self.get_access_level_string(m.access_level),
            }
            for m in group.members.list(all=True)
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

    def add_group_member(self, group_name, username, access):
        if not self.check_group_exists(group_name):
            logging.error(group_name + " group not found")
        else:
            group = self.gl.groups.get(group_name)
            user = self.get_user(username)
            access_level = self.get_access_level(access)
            if user is not None:
                try:
                    group.members.create(
                        {"user_id": user.id, "access_level": access_level}
                    )
                except gitlab.exceptions.GitlabCreateError:
                    member = group.members.get(user.id)
                    member.access_level = access_level

    def remove_group_member(self, group_name, username):
        group = self.gl.groups.get(group_name)
        user = self.get_user(username)
        if user is not None:
            group.members.delete(user.id)

    def change_access(self, group, username, access):
        group = self.gl.groups.get(group)
        user = self.get_user(username)
        member = group.members.get(user.id)
        member.access_level = self.get_access_level(access)
        member.save()

    @staticmethod
    def get_access_level_string(access_level):
        if access_level == gitlab.OWNER_ACCESS:
            return "owner"
        elif access_level == gitlab.MAINTAINER_ACCESS:
            return "maintainer"
        elif access_level == gitlab.DEVELOPER_ACCESS:
            return "developer"
        elif access_level == gitlab.REPORTER_ACCESS:
            return "reporter"
        elif access_level == gitlab.GUEST_ACCESS:
            return "guest"

    @staticmethod
    def get_access_level(access):
        access = access.lower()
        if access == "owner":
            return gitlab.OWNER_ACCESS
        elif access == "maintainer":
            return gitlab.MAINTAINER_ACCESS
        elif access == "developer":
            return gitlab.DEVELOPER_ACCESS
        elif access == "reporter":
            return gitlab.REPORTER_ACCESS
        elif access == "guest":
            return gitlab.GUEST_ACCESS

    def get_group_id_and_projects(self, group_name):
        group = self.gl.groups.get(group_name)
        return group.id, [p.name for p in self.get_items(group.projects.list)]

    def create_project(self, group_id, project):
        self.gl.projects.create({"name": project, "namespace_id": group_id})

    def get_project_url(self, group, project):
        return f"{self.server}/{group}/{project}"

    @retry()
    def get_project(self, repo_url):
        repo = repo_url.replace(self.server + "/", "")
        try:
            project = self.gl.projects.get(repo)
        except gitlab.exceptions.GitlabGetError:
            logging.warning(f"{repo_url} not found")
            project = None
        return project

    def get_issues(self, state):
        return self.get_items(self.project.issues.list, state=state)

    def get_merge_request(self, mr_id):
        return self.project.mergerequests.get(mr_id)

    def get_merge_requests(self, state):
        return self.get_items(self.project.mergerequests.list, state=state)

    def get_merge_request_label_events(self, mr: ProjectMergeRequest):
        return self.get_items(mr.resourcelabelevents.list)

    def get_merge_request_pipelines(self, mr: ProjectMergeRequest) -> list[dict]:
        return sorted(
            self.get_items(mr.pipelines), key=lambda x: x["created_at"], reverse=True
        )

    def get_merge_request_changed_paths(self, mr_id: int) -> list[str]:
        merge_request = self.project.mergerequests.get(mr_id)
        changes = merge_request.changes()["changes"]
        changed_paths = set()
        for change in changes:
            old_path = change["old_path"]
            new_path = change["new_path"]
            changed_paths.add(old_path)
            changed_paths.add(new_path)
        return list(changed_paths)

    def get_merge_request_comments(
        self, mr_id: int, include_description: bool = False
    ) -> list[dict[str, Any]]:
        comments = []
        merge_request = self.project.mergerequests.get(mr_id)
        if include_description:
            comments.append(
                {
                    "username": merge_request.author["username"],
                    "body": merge_request.description,
                    "created_at": merge_request.created_at,
                    "id": MR_DESCRIPTION_COMMENT_ID,
                }
            )
        for note in merge_request.notes.list(all=True):
            if note.system:
                continue
            comments.append(
                {
                    "username": note.author["username"],
                    "body": note.body,
                    "created_at": note.created_at,
                    "id": note.id,
                }
            )
        return comments

    def delete_gitlab_comment(self, mr_id, comment_id):
        merge_request = self.project.mergerequests.get(mr_id)
        note = merge_request.notes.get(comment_id)
        note.delete()

    def add_merge_request_comment(self, mr_id, comment):
        merge_request = self.project.mergerequests.get(mr_id)
        merge_request.notes.create({"body": comment})

    def get_project_labels(self):
        return [ln.name for ln in self.project.labels.list(all=True)]

    def get_merge_request_labels(self, mr_id):
        merge_request = self.project.mergerequests.get(mr_id)
        return merge_request.labels

    def add_label_to_merge_request(self, mr_id, label):
        merge_request = self.project.mergerequests.get(mr_id)
        labels = merge_request.attributes.get("labels")
        labels.append(label)
        self.update_labels(merge_request, "merge-request", labels)

    def add_labels_to_merge_request(self, mr_id, labels):
        """Adds labels to a Merge Request"""
        merge_request = self.project.mergerequests.get(mr_id)
        mr_labels = merge_request.attributes.get("labels")
        mr_labels += labels
        self.update_labels(merge_request, "merge-request", mr_labels)

    def remove_label_from_merge_request(self, mr_id, label):
        merge_request = self.project.mergerequests.get(mr_id)
        labels = merge_request.attributes.get("labels")
        if label in labels:
            labels.remove(label)
        self.update_labels(merge_request, "merge-request", labels)

    def add_comment_to_merge_request(self, mr_id, body):
        merge_request = self.project.mergerequests.get(mr_id)
        merge_request.notes.create({"body": body})

    @staticmethod
    def get_items(method, **kwargs):
        all_items = []
        page = 1
        while True:
            items = method(page=page, per_page=100, **kwargs)
            all_items.extend(items)
            if len(items) < 100:
                break
            page += 1

        return all_items

    def create_label(self, label_text: str, label_color: str) -> None:
        self.project.labels.create({"name": label_text, "color": label_color})

    def add_label(self, item, item_type, label):
        note_body = (
            "item has been marked as {0}. " "to remove say `/{0} cancel`"
        ).format(label)
        labels = item.attributes.get("labels")
        labels.append(label)
        item.notes.create({"body": note_body})
        self.update_labels(item, item_type, labels)

    def remove_label(self, item, item_type, label):
        labels = item.attributes.get("labels")
        labels.remove(label)
        self.update_labels(item, item_type, labels)

    def update_labels(self, item, item_type, labels):
        if item_type == "issue":
            editable_item = self.project.issues.get(
                item.attributes.get("iid"), lazy=True
            )
        elif item_type == "merge-request":
            editable_item = self.project.mergerequests.get(
                item.attributes.get("iid"), lazy=True
            )
        editable_item.labels = labels
        editable_item.save()

    @staticmethod
    def close(item):
        item.state_event = "close"
        item.save()

    def get_user(self, username):
        user = self.gl.users.list(search=username)
        if len(user) == 0:
            logging.error(username + " user not found")
            return
        return user[0]

    @retry()
    def get_project_hooks(self, repo_url):
        p = self.get_project(repo_url)
        if p is None:
            return []
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
        p.hooks.create(hook)

    def get_repository_tree(self, ref="master"):
        """
        Wrapper around Gitlab.repository_tree() with pagination disabled.
        """
        return self.project.repository_tree(ref=ref, recursive=True, all=True)

    def get_file(self, path, ref="master"):
        """
        Wrapper around Gitlab.files.get() with exception handling.
        """
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
        comments = self.get_merge_request_comments(mr.iid)
        comments.sort(key=itemgetter("created_at"), reverse=True)
        for comment in comments:
            username = comment["username"]
            if username == self.user.username:
                continue
            if username in team_usernames:
                last_action_by_team = comment["created_at"]
                break
        # labels
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

    def last_assignment(self, mr: ProjectMergeRequest) -> Optional[Tuple[str, str]]:
        body_format = "assigned to @"
        notes = mr.notes.list(all=True)

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
        comments = self.get_merge_request_comments(mr.iid)
        comments.sort(key=itemgetter("created_at"), reverse=True)
        for comment in comments:
            username = comment["username"]
            if username == self.user.username and exclude_bot:
                continue
            return comment
        return None

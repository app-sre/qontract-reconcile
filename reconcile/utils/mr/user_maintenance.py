import logging
from collections.abc import Iterable
from enum import Enum
from io import StringIO
from pathlib import Path

from pydantic import BaseModel, field_validator

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.ruamel import create_ruamel_instance

log = logging.getLogger(__name__)


class PathTypes(Enum):
    USER = 0
    REQUEST = 1
    QUERY = 2
    GABI = 3
    AWS_ACCOUNTS = 4
    SCHEDULE = 5


class PathSpec(BaseModel):
    type: PathTypes
    path: str

    @field_validator("path")
    @classmethod
    def prepend_data_to_path(cls, v: str) -> str:
        return "data" + v


class CreateDeleteUserAppInterface(MergeRequestBase):
    name = "create_delete_user_mr"

    def __init__(self, username: str, paths: Iterable[PathSpec]) -> None:
        self.username = username
        self.paths = paths

        super().__init__()

        self.labels = [AUTO_MERGE]

    @property
    def title(self) -> str:
        return f"[{self.name}] delete user {self.username}"

    @property
    def description(self) -> str:
        return f"delete user {self.username}"

    def process(self, gitlab_cli: GitLabApi) -> None:
        yaml = create_ruamel_instance(explicit_start=True)
        for path_spec in self.paths:
            path_type = path_spec.type
            path = path_spec.path
            if path_type in {PathTypes.USER, PathTypes.REQUEST, PathTypes.QUERY}:
                gitlab_cli.delete_file(
                    branch_name=self.branch, file_path=path, commit_message=self.title
                )
            elif path_type == PathTypes.GABI:
                raw_file = gitlab_cli.get_raw_file(
                    project=gitlab_cli.project,
                    path=path,
                    ref=self.branch,
                )
                content = yaml.load(raw_file)
                for gabi_user in content["users"][:]:
                    if self.username in gabi_user["$ref"]:
                        content["users"].remove(gabi_user)

                with StringIO() as stream:
                    yaml.dump(content, stream)
                    gitlab_cli.update_file(
                        branch_name=self.branch,
                        file_path=path,
                        commit_message=self.title,
                        content=stream.getvalue(),
                    )
            elif path_type == PathTypes.AWS_ACCOUNTS:
                raw_file = gitlab_cli.get_raw_file(
                    project=gitlab_cli.project,
                    path=path,
                    ref=self.branch,
                )
                content = yaml.load(raw_file)
                for reset_record in content["resetPasswords"]:
                    if self.username in reset_record["user"]["$ref"]:
                        content["resetPasswords"].remove(reset_record)

                        with StringIO() as stream:
                            yaml.dump(content, stream)
                            gitlab_cli.update_file(
                                branch_name=self.branch,
                                file_path=path,
                                commit_message=self.title,
                                content=stream.getvalue(),
                            )
            elif path_type == PathTypes.SCHEDULE:
                raw_file = gitlab_cli.get_raw_file(
                    project=gitlab_cli.project,
                    path=path,
                    ref=self.branch,
                )
                content = yaml.load(raw_file)
                delete_indexes: list[tuple[int, int]] = []
                for schedule_index, schedule_record in enumerate(content["schedule"]):
                    for user_index, user in enumerate(schedule_record["users"]):
                        if self.username == Path(user["$ref"]).stem:
                            delete_indexes.append((schedule_index, user_index))
                for schedule_index, user_index in reversed(delete_indexes):
                    del content["schedule"][schedule_index]["users"][user_index]

                with StringIO() as stream:
                    yaml.dump(content, stream)
                    gitlab_cli.update_file(
                        branch_name=self.branch,
                        file_path=path,
                        commit_message=self.title,
                        content=stream.getvalue(),
                    )


class CreateDeleteUserInfra(MergeRequestBase):
    PLAYBOOK = "ansible/hosts/host_vars/bastion.ci.int.devshift.net"

    name = "create_ssh_key_mr"

    def __init__(self, usernames: Iterable[str]):
        self.usernames = usernames

        super().__init__()

        self.labels = [AUTO_MERGE]

    @property
    def title(self) -> str:
        return f"[{self.name}] delete user(s)"

    @property
    def description(self) -> str:
        return "delete user(s)"

    def process(self, gitlab_cli: GitLabApi) -> None:
        raw_file = gitlab_cli.get_raw_file(
            project=gitlab_cli.project,
            path=self.PLAYBOOK,
            ref=self.branch,
        )
        yaml = create_ruamel_instance(explicit_start=True)
        content = yaml.load(raw_file)

        new_list = []
        for user in content["users"]:
            if user["name"] in self.usernames:
                log.info(["delete_user_from_infra", user["name"]])
                content["deleted_users"].append(user["name"])
                continue
            new_list.append(user)

        content["users"] = new_list

        with StringIO() as stream:
            yaml.dump(content, stream)
            gitlab_cli.update_file(
                branch_name=self.branch,
                file_path=self.PLAYBOOK,
                commit_message=self.title,
                content=stream.getvalue(),
            )

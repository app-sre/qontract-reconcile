from collections.abc import Iterable
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, validator
from ruamel import yaml

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE


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

    @validator("path")
    def prepend_data_to_path(cls, v):
        return "data" + v


class CreateDeleteUserAppInterface(MergeRequestBase):
    name = "create_delete_user_mr"

    def __init__(self, username, paths: Iterable[PathSpec]):
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
        for path_spec in self.paths:
            path_type = path_spec.type
            path = path_spec.path
            if path_type in {PathTypes.USER, PathTypes.REQUEST, PathTypes.QUERY}:
                gitlab_cli.delete_file(
                    branch_name=self.branch, file_path=path, commit_message=self.title
                )
            elif path_type == PathTypes.GABI:
                raw_file = gitlab_cli.project.files.get(file_path=path, ref=self.branch)
                content = yaml.load(raw_file.decode(), Loader=yaml.RoundTripLoader)
                for gabi_user in content["users"][:]:
                    if self.username in gabi_user["$ref"]:
                        content["users"].remove(gabi_user)
                new_content = "---\n"
                new_content += yaml.dump(content, Dumper=yaml.RoundTripDumper)
                gitlab_cli.update_file(
                    branch_name=self.branch,
                    file_path=path,
                    commit_message=self.title,
                    content=new_content,
                )
            elif path_type == PathTypes.AWS_ACCOUNTS:
                raw_file = gitlab_cli.project.files.get(file_path=path, ref=self.branch)
                content = yaml.load(raw_file.decode(), Loader=yaml.RoundTripLoader)
                for reset_record in content["resetPasswords"]:
                    if self.username in reset_record["user"]["$ref"]:
                        content["resetPasswords"].remove(reset_record)
                        new_content = "---\n"
                        new_content += yaml.dump(content, Dumper=yaml.RoundTripDumper)
                        gitlab_cli.update_file(
                            branch_name=self.branch,
                            file_path=path,
                            commit_message=self.title,
                            content=new_content,
                        )
            elif path_type == PathTypes.SCHEDULE:
                raw_file = gitlab_cli.project.files.get(file_path=path, ref=self.branch)
                content = yaml.load(raw_file.decode(), Loader=yaml.RoundTripLoader)
                delete_indexes: list[tuple[int, int]] = []
                for schedule_index, schedule_record in enumerate(content["schedule"]):
                    for user_index, user in enumerate(schedule_record["users"]):
                        if self.username == Path(user["$ref"]).stem:
                            delete_indexes.append((schedule_index, user_index))
                for schedule_index, user_index in reversed(delete_indexes):
                    del content["schedule"][schedule_index]["users"][user_index]
                new_content = "---\n"
                new_content += yaml.dump(content, Dumper=yaml.RoundTripDumper)
                gitlab_cli.update_file(
                    branch_name=self.branch,
                    file_path=path,
                    commit_message=self.title,
                    content=new_content,
                )


class CreateDeleteUserInfra(MergeRequestBase):
    PLAYBOOK = "ansible/playbooks/bastion-accounts.yml"

    name = "create_ssh_key_mr"

    def __init__(self, usernames):
        self.usernames = usernames

        super().__init__()

        self.labels = [AUTO_MERGE]

    @property
    def title(self) -> str:
        return f"[{self.name}] delete user(s)"

    @property
    def description(self) -> str:
        return "delete user(s)"

    def process(self, gitlab_cli):
        raw_file = gitlab_cli.project.files.get(
            file_path=self.PLAYBOOK, ref=self.branch
        )
        content = yaml.load(raw_file.decode(), Loader=yaml.RoundTripLoader)

        new_list = []
        for user in content[0]["vars"]["users"]:
            if user["name"] in self.usernames:
                content[0]["vars"]["deleted_users"].append(user["name"])
                continue
            new_list.append(user)

        content[0]["vars"]["users"] = new_list

        new_content = "---\n"
        new_content += yaml.dump(content, Dumper=yaml.RoundTripDumper)

        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=self.PLAYBOOK,
            commit_message=self.title,
            content=new_content,
        )

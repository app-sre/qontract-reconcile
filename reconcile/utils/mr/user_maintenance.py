from ruamel import yaml

from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE


class PathTypes:
    USER = 0
    REQUEST = 1
    QUERY = 2
    GABI = 3


class CreateDeleteUser(MergeRequestBase):

    name = "create_delete_user_mr"

    def __init__(self, username, paths):
        self.username = username
        self.paths = paths

        super().__init__()

        self.labels = [AUTO_MERGE]

    @property
    def title(self):
        return f"[{self.name}] delete user {self.username}"

    def process(self, gitlab_cli):
        for path_spec in self.paths:
            path_type = path_spec["type"]
            path = path_spec["path"]
            if path_type in [PathTypes.USER, PathTypes.REQUEST, PathTypes.QUERY]:
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

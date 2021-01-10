from utils.mr.base import MergeRequestBase
from utils.mr.labels import AUTO_MERGE


class CreateDeleteUser(MergeRequestBase):

    name = 'create_delete_user_mr'

    def __init__(self, username, paths):
        self.username = username
        self.paths = paths

        super().__init__()

        self.labels = [AUTO_MERGE]

    @property
    def title(self):
        return f'[{self.name}] delete user {self.username}'

    def process(self, gitlab_cli):
        for path in self.paths:
            gitlab_cli.delete_file(branch_name=self.branch,
                                   file_path=path,
                                   commit_message=self.title)

from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE


class PathTypes:
    USER = 0
    REQUEST = 1
    QUERY = 2


class CreateDeleteUser(MergeRequestBase):

    name = 'create_delete_user_mr'

    def __init__(self, username, paths):
        self.username = username
        self.paths = paths

        super().__init__()

        # self.labels = [AUTO_MERGE]
        self.labels = []

    @property
    def title(self):
        return f'[{self.name}] delete user {self.username}'

    def process(self, gitlab_cli):
        for path in self.paths:
            if path['type'] in [PathTypes.USER,
                                PathTypes.REQUEST,
                                PathTypes.QUERY]:
                gitlab_cli.delete_file(branch_name=self.branch,
                                       file_path=path['path'],
                                       commit_message=self.title)

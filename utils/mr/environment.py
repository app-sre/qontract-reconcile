import ruamel.yaml as yaml

from utils.mr.base import MergeRequestBase
from utils.mr.labels import AUTO_MERGE
from utils.mr.labels import SKIP_CI


class CreateEnvironment(MergeRequestBase):

    name = 'create_environment_mr'

    def __init__(self, environment_name, actions):
        self.environment_name = environment_name
        self.actions = actions

        super().__init__()

        self.labels = []

    @property
    def title(self):
        return (f'[{self.name}] '
                f'create environment {self.environment_name}')

    def process(self, gitlab_cli):
        for action in self.actions:
            continue
            # gitlab_cli...

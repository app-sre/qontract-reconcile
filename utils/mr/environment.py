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
            action_type = action['action']
            if action_type == 'copy_namespace':
                source_namespace_path = action['source_namespace_path']
                target_namespace_path = action['target_namespace_path']
                target_cluster_path = action['target_cluster_path']

                raw_file = gitlab_cli.project.files.get(
                    file_path=source_namespace_path,
                    ref=self.main_branch
                )
                content = yaml.load(raw_file.decode(), Loader=yaml.RoundTripLoader)
                content = content.replace()
                new_content = '---\n'
                new_content += yaml.dump(content, Dumper=yaml.RoundTripDumper)

                msg = 'Copy namespace'
                gitlab_cli.create_file(
                    branch_name=self.branch,
                    file_path=target_namespace_path,
                    commit_message=msg,
                    content=new_content)
            elif action_type == 'copy_target':
                continue
                saas_file_path = action['saas_file_path']
                rt_name = action['rt_name']
                source_namespace_path = action['source_namespace_path']
                target_namespace_path = action['target_namespace_path']

                raw_file = gitlab_cli.project.files.get(
                    file_path=saas_file_path,
                    ref=self.main_branch
                )
                content = yaml.load(raw_file.decode(), Loader=yaml.RoundTripLoader)
                new_content = '---\n'
                new_content += yaml.dump(content, Dumper=yaml.RoundTripDumper)
                


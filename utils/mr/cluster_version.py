import ruamel.yaml as yaml

from utils.mr.base import MergeRequestBase
from utils.mr.labels import DO_NOT_MERGE


class CreateUpdateClusterVersion(MergeRequestBase):

    name = 'create_update_cluster_version_mr'

    def __init__(self, cluster_name, path, version):
        self.cluster_name = cluster_name
        self.path = path.lstrip('/')
        self.version = version

        super().__init__()

        self.labels = [DO_NOT_MERGE]

    @property
    def title(self):
        return (f'[{self.name}] '
                f'update cluster {self.cluster_name} '
                f'version to {self.version}')

    def process(self, gitlab_cli):
        raw_file = gitlab_cli.project.files.get(file_path=self.path,
                                                ref=self.main_branch)
        content = yaml.load(raw_file.decode(), Loader=yaml.RoundTripLoader)

        if 'spec' not in content:
            self.cancel('Spec missing. Nothing to do.')

        old_version = content['spec']['version']
        if old_version == self.version:
            self.cancel('Cluster version is up to date. Nothing to do.')

        content['spec']['version'] = self.version

        new_content = '---\n'
        new_content += yaml.dump(content, Dumper=yaml.RoundTripDumper)

        msg = f'Update cluster version from {old_version} to {self.version}'
        gitlab_cli.update_file(branch_name=self.branch, file_path=self.path,
                               commit_message=msg, content=new_content)

import ruamel.yaml as yaml

from utils.mr.base import MergeRequestBase
from utils.mr.labels import DO_NOT_MERGE


class CreateUpdateClusterIds(MergeRequestBase):

    name = 'create_update_cluster_ids_mr'

    def __init__(self, cluster_name, path, cluster_id, cluster_external_id):
        self.cluster_name = cluster_name
        self.path = path.lstrip('/')
        self.cluster_id = cluster_id
        self.cluster_external_id = cluster_external_id

        super().__init__()

        self.labels = [DO_NOT_MERGE]

    @property
    def title(self):
        return (f'[{self.name}] '
                f'add cluster {self.cluster_name} id '
                f'and external_id fields')

    def process(self, gitlab_cli):
        raw_file = gitlab_cli.project.files.get(file_path=self.path,
                                                ref=self.main_branch)
        content = yaml.load(raw_file.decode(), Loader=yaml.RoundTripLoader)

        if 'spec' not in content:
            self.cancel('Spec missing. Nothing to do.')

        old_id = content['spec'].get('id')
        old_external_id = content['spec'].get('external_id')

        if all([old_id == self.cluster_id,
                old_external_id == self.cluster_external_id]):
            self.cancel('Cluster ids are up to date. Nothing to do.')

        content['spec']['id'] = self.cluster_id
        content['spec']['external_id'] = self.cluster_external_id

        new_content = '---\n'
        new_content += yaml.dump(content, Dumper=yaml.RoundTripDumper)

        msg = 'Add id and external_id fields'
        gitlab_cli.update_file(branch_name=self.branch, file_path=self.path,
                               commit_message=msg, content=new_content)

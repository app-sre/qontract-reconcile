from ruamel import yaml
from gitlab.exceptions import GitlabError

from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.mr.labels import SKIP_CI


class CSInstallConfig(MergeRequestBase):

    name = "cluster_service_install_config_mr"

    def __init__(self, mirrors_info):
        """
        :param mirrors_info: the list of mirrors dictionary in the
                             install-config format. Example:
            [
                {
                    'source': 'quay.io/app-sre/managed-upgrade-operator',
                    'mirrors': [
                        'quay.io/app-sre/managed-upgrade-operator',
                        '950916221866.dkr.ecr.us-east-1.amazonaws.com/muo',
                    ],
                },
            ]
        """
        self.mirrors_info = mirrors_info

        super().__init__()

        self.labels = [AUTO_MERGE, SKIP_CI]

    @property
    def title(self):
        return f"[{self.name}] Clusters Service install-config ConfigMap"

    def process(self, gitlab_cli):
        install_config = {}
        install_config["apiVersion"] = "v1"
        install_config["kind"] = "InstallConfig"
        install_config["imageContentSources"] = self.mirrors_info

        config_map = {}
        config_map["apiVersion"] = "v1"
        config_map["kind"] = "ConfigMap"
        config_map["metadata"] = {
            "name": "clusters-service",
            "labels": {
                "app": "clusters-service",
            },
        }

        config_map["data"] = {
            "install-config.yaml": yaml.dump(
                install_config, indent=2, Dumper=yaml.RoundTripDumper
            )
        }
        yaml.scalarstring.walk_tree(config_map)

        content = (
            "# App-interface autogenerates this file. \n" "# Do not manually edit it.\n"
        )
        content += yaml.dump(config_map, Dumper=yaml.RoundTripDumper)
        path = "resources/services/ocm/clusters-service.configmap.yaml"
        try:
            msg = "Update Clusters Service install-config ConfigMap"
            gitlab_cli.update_file(
                branch_name=self.branch,
                file_path=path,
                commit_message=msg,
                content=content,
            )
        except GitlabError:
            msg = "Create Clusters Service install-config ConfigMap"
            gitlab_cli.create_file(
                branch_name=self.branch,
                file_path=path,
                commit_message=msg,
                content=content,
            )

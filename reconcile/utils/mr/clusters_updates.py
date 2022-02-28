from ruamel import yaml

from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.mr.labels import SKIP_CI


class CreateClustersUpdates(MergeRequestBase):

    name = "create_clusters_updates_mr"

    def __init__(self, clusters_updates):
        self.clusters_updates = clusters_updates

        super().__init__()

        self.labels = [AUTO_MERGE, SKIP_CI]

    @property
    def title(self):
        return f"[{self.name}] clusters updates"

    def process(self, gitlab_cli):
        changes = False
        for cluster_name, cluster_updates in self.clusters_updates.items():
            if not cluster_updates:
                continue

            cluster_path = cluster_updates.pop("path")
            raw_file = gitlab_cli.project.files.get(
                file_path=cluster_path, ref=self.main_branch
            )
            content = yaml.load(raw_file.decode(), Loader=yaml.RoundTripLoader)
            if "spec" not in content:
                self.cancel("Spec missing. Nothing to do.")

            # check that there are updates to be made
            if (
                cluster_updates["spec"].items() <= content["spec"].items()
                and cluster_updates["root"].items() <= content.items()
            ):
                continue
            changes = True

            content["spec"].update(cluster_updates["spec"])
            # Since spec is a dictionary we can't simply do
            # content.update(cluster_updates) :(
            content.update(cluster_updates["root"])

            yaml.explicit_start = True
            new_content = yaml.dump(
                content, Dumper=yaml.RoundTripDumper, explicit_start=True
            )

            msg = f"update cluster {cluster_name} spec fields"
            gitlab_cli.update_file(
                branch_name=self.branch,
                file_path=cluster_path,
                commit_message=msg,
                content=new_content,
            )

        if not changes:
            self.cancel("Clusters are up to date. Nothing to do.")

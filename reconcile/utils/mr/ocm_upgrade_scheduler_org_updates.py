from ruamel import yaml

from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE


class CreateOCMUpgradeSchedulerOrgUpdates(MergeRequestBase):

    name = "create_ocm_upgrade_scheduler_org_updates_mr"

    def __init__(self, updates_info):
        self.updates_info = updates_info

        super().__init__()

        self.labels = [AUTO_MERGE]

    @property
    def title(self) -> str:
        return f"[{self.name}] ocm upgrade scheduler org updates"

    @property
    def description(self) -> str:
        return f'ocm upgrade scheduler org updates for {self.updates_info["name"]}'

    def process(self, gitlab_cli):
        changes = False
        ocm_path = self.updates_info["path"]
        ocm_name = self.updates_info["name"]

        raw_file = gitlab_cli.project.files.get(
            file_path=ocm_path, ref=self.main_branch
        )
        content = yaml.load(raw_file.decode(), Loader=yaml.RoundTripLoader)
        upgrade_policy_clusters = content["upgradePolicyClusters"]

        for update in self.updates_info["updates"]:
            action = update["action"]
            cluster_name = update["cluster"]
            upgrade_policy = update.get("policy")

            if action == "add":
                found = [
                    c for c in upgrade_policy_clusters if c["name"] == cluster_name
                ]
                if found:
                    continue
                item = {
                    "name": cluster_name,
                    "upgradePolicy": upgrade_policy,
                }
                upgrade_policy_clusters.append(item)
                changes = True
            elif action == "delete":
                found = [
                    c for c in upgrade_policy_clusters if c["name"] == cluster_name
                ]
                if not found:
                    continue
                content["upgradePolicyClusters"] = [
                    c for c in upgrade_policy_clusters if c["name"] != cluster_name
                ]
                upgrade_policy_clusters = content["upgradePolicyClusters"]
                changes = True
            else:
                raise NotImplementedError(action)

        if not changes:
            self.cancel("OCM Upgrade schedules are up to date. Nothing to do.")

        yaml.explicit_start = True  # type: ignore[attr-defined]
        new_content = yaml.dump(
            content, Dumper=yaml.RoundTripDumper, explicit_start=True
        )

        msg = f"update {ocm_name} upgrade policy clusters"
        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=ocm_path,
            commit_message=msg,
            content=new_content,
        )

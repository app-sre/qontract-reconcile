import ast

from reconcile.gql_definitions.fragments.upgrade_policy import ClusterUpgradePolicyV1
from reconcile.test.ocm.aus.fixtures import build_upgrade_policy
from reconcile.typed_queries.clusters import get_clusters
from reconcile.utils.helpers import unflatten
from reconcile.utils.oc_map import init_oc_map_from_clusters
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.runtime.integration import NoParams, QontractReconcileIntegration
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "acm-upgrade-scheduler"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class ACMUpgradeServiceIntegration(QontractReconcileIntegration[NoParams]):
    """
    A flavour of the OCM organization based upgrade scheduler, that uses
    ACM ManagedClusters to discover clusters and their upgrade policies.
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def fetch_desired_state(self) -> dict[str, ClusterUpgradePolicyV1]:
        desired_state: dict[str, ClusterUpgradePolicyV1] = {}
        oc_map = init_oc_map_from_clusters(
            clusters=get_clusters(),
            secret_reader=self.secret_reader,
            integration=QONTRACT_INTEGRATION,
            thread_pool_size=1,
            init_api_resources=True,
        )
        cluster_names = oc_map.clusters()
        if len(cluster_names) != 1:
            raise ValueError(
                "expecting a single cluster for a side-by-side execution with ACM"
            )
        cluster_name = cluster_names[0]
        oc = oc_map.get(cluster_name)
        managed_clusters = oc.get_all(kind="ManagedCluster")["items"]
        for mc in managed_clusters:
            r = OR(
                body=mc,
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
            )
            upgrade_policy_annotations = {
                k: v for k, v in r.annotations.items() if k.startswith("upgradePolicy")
            }
            if not upgrade_policy_annotations:
                continue
            upgrade_policy_mapping = unflatten(
                upgrade_policy_annotations, parent_key="upgradePolicy"
            )
            conditions = upgrade_policy_mapping["conditions"]
            upgrade_policy = build_upgrade_policy(
                soak_days=conditions["soakDays"],
                workloads=ast.literal_eval(upgrade_policy_mapping["workloads"]),
                schedule=upgrade_policy_mapping["schedule"],
            )
            desired_state[r.name] = upgrade_policy

        return desired_state

    def run(self, dry_run: bool = False) -> None:
        desired_state = self.fetch_desired_state()
        print("obtained desired state!")
        print(desired_state)

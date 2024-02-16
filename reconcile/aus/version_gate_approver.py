from typing import (
    Callable,
    Iterable,
    Optional,
)

import semver

from reconcile.aus.advanced_upgrade_service import aus_label_key
from reconcile.aus.base import gates_to_agree
from reconcile.aus.version_gates import ocp_gate_handler, sts_version_gate_handler
from reconcile.aus.version_gates.handler import GateHandler
from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.gql_definitions.fragments.minimal_ocm_organization import (
    MinimalOCMOrganization,
)
from reconcile.utils import gql
from reconcile.utils.grouping import group_by
from reconcile.utils.jobcontroller.controller import (
    build_job_controller,
)
from reconcile.utils.ocm.base import ClusterDetails, OCMCluster, OCMVersionGate
from reconcile.utils.ocm.clusters import discover_clusters_by_labels
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm.upgrades import (
    create_version_agreement,
    get_version_agreement,
    get_version_gates,
)
from reconcile.utils.ocm_base_client import (
    OCMBaseClient,
    init_ocm_base_client,
)
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)

QONTRACT_INTEGRATION = "version-gate-approver"
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


class VersionGateApproverParams(PydanticRunParams):
    job_controller_cluster: str
    job_controller_namespace: str
    job_controller_service_account: str
    rosa_job_image: Optional[str] = None


class VersionGateApprover(QontractReconcileIntegration[VersionGateApproverParams]):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def initialize_handlers(self, query_func: Callable) -> None:
        self.handlers: dict[str, GateHandler] = {
            sts_version_gate_handler.GATE_LABEL: sts_version_gate_handler.init_sts_gate_handler(
                query_func,
                self.secret_reader,
                service_account=self.params.job_controller_service_account,
                job_controller=build_job_controller(
                    integration=QONTRACT_INTEGRATION,
                    integration_version=QONTRACT_INTEGRATION_VERSION,
                    cluster=self.params.job_controller_cluster,
                    namespace=self.params.job_controller_namespace,
                    secret_reader=self.secret_reader,
                    dry_run=False,
                ),
                rosa_job_image=self.params.rosa_job_image,
            ),
            ocp_gate_handler.GATE_LABEL: ocp_gate_handler.OCPGateHandler(),
        }

    def run(self, dry_run: bool) -> None:
        gql_api = gql.get_api()
        self.initialize_handlers(gql_api.query)
        environments = ocm_environment_query(gql_api.query).environments
        ocm_apis = {
            env.name: init_ocm_base_client(env, self.secret_reader)
            for env in environments
        }
        for env in environments:
            self.process_environment(
                organizations=env.organizations or [],
                ocm_api=ocm_apis[env.name],
                dry_run=dry_run,
            )

    def process_environment(
        self,
        organizations: list[MinimalOCMOrganization],
        ocm_api: OCMBaseClient,
        dry_run: bool,
    ) -> None:
        """
        Find all clusters with AUS labels in the organization and process them
        org by org.
        """
        # lookup clusters
        clusters = discover_clusters_by_labels(
            ocm_api=ocm_api,
            label_filter=Filter().like("key", aus_label_key("%")),
        )
        clusters_by_org_id = group_by(clusters, lambda c: c.organization_id)

        # lookup version gates
        gates = get_version_gates(ocm_api)

        for org in organizations:
            self.process_organization(
                clusters=clusters_by_org_id.get(org.org_id, []),
                gates=gates,
                ocm_api=ocm_api,
                dry_run=dry_run,
            )

    def process_organization(
        self,
        clusters: Iterable[ClusterDetails],
        gates: list[OCMVersionGate],
        ocm_api: OCMBaseClient,
        dry_run: bool,
    ) -> None:
        """
        Process all clusters in an organization.
        """
        for cluster in clusters:
            unacked_gates = gates_to_agree(
                cluster=cluster.ocm_cluster,
                gates=gates,
                acked_gate_ids={
                    agreement["version_gate"]["id"]
                    for agreement in get_version_agreement(
                        ocm_api, cluster.ocm_cluster.id
                    )
                },
            )
            if not unacked_gates:
                continue
            self.process_cluster(
                cluster=cluster.ocm_cluster,
                gates=unacked_gates,
                ocm_api=ocm_api,
                dry_run=dry_run,
            )

    def process_cluster(
        self,
        cluster: OCMCluster,
        gates: list[OCMVersionGate],
        ocm_api: OCMBaseClient,
        dry_run: bool,
    ) -> None:
        """
        Process all unacknowledged gates for a cluster.
        """
        for gate in gates:
            success = self.handlers[gate.label].handle(ocm_api, cluster, gate, dry_run)
            if success and not dry_run:
                create_version_agreement(ocm_api, gate.id, cluster.id)
            elif not success:
                print(f"Failed to handle gate {gate.id} for cluster {cluster.name}")

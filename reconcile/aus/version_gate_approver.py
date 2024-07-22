import logging
from collections.abc import Callable, Iterable

from reconcile.aus.advanced_upgrade_service import aus_label_key
from reconcile.aus.base import gates_to_agree, get_orgs_for_environment
from reconcile.aus.version_gates import (
    ingress_gate_handler,
    ocp_gate_handler,
    sts_version_gate_handler,
)
from reconcile.aus.version_gates.handler import GateHandler
from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.utils import gql
from reconcile.utils.grouping import group_by
from reconcile.utils.jobcontroller.controller import (
    build_job_controller,
)
from reconcile.utils.ocm.base import (
    ClusterDetails,
    LabelContainer,
    OCMCluster,
    OCMVersionGate,
)
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
    init_ocm_base_client_for_org,
)
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "version-gate-approver"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class VersionGateApproverParams(PydanticRunParams):
    job_controller_cluster: str
    job_controller_namespace: str
    rosa_job_service_account: str
    rosa_role: str
    rosa_job_image: str | None = None


class VersionGateApprover(QontractReconcileIntegration[VersionGateApproverParams]):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def initialize_handlers(self, query_func: Callable) -> None:
        self.handlers: dict[str, GateHandler] = {
            sts_version_gate_handler.GATE_LABEL: sts_version_gate_handler.STSGateHandler(
                job_controller=build_job_controller(
                    integration=QONTRACT_INTEGRATION,
                    integration_version=QONTRACT_INTEGRATION_VERSION,
                    cluster=self.params.job_controller_cluster,
                    namespace=self.params.job_controller_namespace,
                    secret_reader=self.secret_reader,
                    dry_run=False,
                ),
                aws_iam_role=self.params.rosa_role,
                rosa_job_service_account=self.params.rosa_job_service_account,
                rosa_job_image=self.params.rosa_job_image,
            ),
            ocp_gate_handler.GATE_LABEL: ocp_gate_handler.OCPGateHandler(),
            ingress_gate_handler.GATE_LABEL: ingress_gate_handler.IngressGateHandler(),
        }

    def run(self, dry_run: bool) -> None:
        gql_api = gql.get_api()
        self.initialize_handlers(gql_api.query)
        environments = ocm_environment_query(gql_api.query).environments
        for env in environments:
            with init_ocm_base_client(env, self.secret_reader) as ocm_api:
                self.process_environment(
                    ocm_env_name=env.name,
                    ocm_api=ocm_api,
                    query_func=gql_api.query,
                    dry_run=dry_run,
                )

    def process_environment(
        self,
        ocm_env_name: str,
        ocm_api: OCMBaseClient,
        query_func: Callable,
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

        # lookup organization metadata
        organizations = get_orgs_for_environment(
            integration=QONTRACT_INTEGRATION,
            ocm_env_name=ocm_env_name,
            query_func=query_func,
            ocm_organization_ids=set(clusters_by_org_id.keys()),
        )

        for org in organizations:
            with init_ocm_base_client_for_org(org, self.secret_reader) as ocm_org_api:
                self.process_organization(
                    clusters=clusters_by_org_id.get(org.org_id, []),
                    gates=gates,
                    ocm_api=ocm_org_api,
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
                enabled_gate_handlers=get_enabled_gate_handlers(cluster.labels),
                gates=unacked_gates,
                ocm_api=ocm_api,
                ocm_org_id=cluster.organization_id,
                dry_run=dry_run,
            )

    def process_cluster(
        self,
        cluster: OCMCluster,
        enabled_gate_handlers: set[str],
        gates: list[OCMVersionGate],
        ocm_api: OCMBaseClient,
        ocm_org_id: str,
        dry_run: bool,
    ) -> None:
        """
        Process all unacknowledged gates for a cluster.
        """
        for gate in gates:
            if gate.label in self.handlers and gate.label not in enabled_gate_handlers:
                continue
            logging.info(
                f"handle gate {gate.label} for cluster {cluster.name} {{gate_id = {gate.id}), version = {gate.version_raw_id_prefix}, cluster_id = {cluster.id}, org_id = {ocm_org_id}}}"
            )
            success = self.handlers[gate.label].handle(
                ocm_api=ocm_api,
                ocm_org_id=ocm_org_id,
                cluster=cluster,
                gate=gate,
                dry_run=dry_run,
            )
            if success and not dry_run:
                create_version_agreement(ocm_api, gate.id, cluster.id)
            elif not success:
                logging.error(
                    f"failed to handle gate {gate.label} for cluster {cluster.name} {{gate_id = {gate.id}), version = {gate.version_raw_id_prefix}, cluster_id = {cluster.id}, org_id = {ocm_org_id}}}"
                )


def get_enabled_gate_handlers(labels: LabelContainer) -> set[str]:
    """
    Get the set of enabled gate handlers from the labels. Default to the OCP
    gate to keep backwards compatibility (for now).
    """
    handler_csv = labels.get_label_value(aus_label_key("version-gate-approvals"))
    if not handler_csv:
        return {ocp_gate_handler.GATE_LABEL}
    return set(handler_csv.split(","))

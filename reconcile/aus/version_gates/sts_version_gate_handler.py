import logging
from typing import Callable, Optional, Tuple

from sretoolbox.utils import threaded

from reconcile.aus.version_gates.handler import GateHandler
from reconcile.gql_definitions.common.rosa_clusters import (
    ClusterSpecROSAV1,
    ClusterV1,
)
from reconcile.typed_queries.rosa_cluster import get_rosa_clusters
from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.ocm.base import OCMCluster, OCMVersionGate
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.rosa.model import ROSACluster
from reconcile.utils.rosa.rosa_cli import RosaCliException
from reconcile.utils.rosa.session import (
    RosaSessionContextManager,
    rosa_session_ctx,
)
from reconcile.utils.secret_reader import SecretReaderBase

GATE_LABEL = "api.openshift.com/gate-sts"


def init_sts_gate_handler(
    gql_query_func: Callable,
    secret_reader: SecretReaderBase,
    job_controller: K8sJobController,
    service_account: str,
    rosa_job_image: Optional[str] = None,
    thread_pool_size: int = 10,
) -> "STSGateHandler":
    """
    Build an STS gate handler that can handle all ROSA clusters stored
    in app-interface. Other AUS users are not supported right now as
    we have no way to access their AWS accounts.
    """

    def _rosa_session_builder(
        cluster: ClusterV1,
    ) -> Optional[Tuple[ClusterV1, RosaSessionContextManager]]:
        return (
            cluster,
            rosa_session_ctx(
                cluster=ROSACluster(**cluster.dict(by_alias=True)),
                secret_reader=secret_reader,
                job_controller=job_controller,
                image=rosa_job_image,
                service_account=service_account,
            ),
        )

    clusters = get_rosa_clusters(gql_query_func)
    builders: list[Tuple[ClusterV1, RosaSessionContextManager]] = [
        result
        for result in threaded.run(
            _rosa_session_builder,
            clusters,
            thread_pool_size,
        )
        if result
    ]
    return STSGateHandler(
        rosa_session_builder={
            cluster.spec.q_id: session_builder
            for cluster, session_builder in builders
            if cluster.spec
            and isinstance(cluster.spec, ClusterSpecROSAV1)
            and cluster.spec.q_id
        }
    )


class STSGateHandler(GateHandler):
    def __init__(
        self, rosa_session_builder: dict[str, RosaSessionContextManager]
    ) -> None:
        self.rosa_session_builder = rosa_session_builder

    @staticmethod
    def responsible_for(cluster: OCMCluster) -> bool:
        return cluster.is_sts()

    def handle(
        self,
        _: OCMBaseClient,
        cluster: OCMCluster,
        gate: OCMVersionGate,
        dry_run: bool,
    ) -> bool:
        if not cluster.aws or not cluster.aws.sts or not cluster.is_sts():
            # checked already but mypy :/
            return False
        if cluster.is_rosa_hypershift():
            # thanks to hypershift managed policies, there is nothing to do for us here
            # returning True will ack the version gate
            return True
        if cluster.id not in self.rosa_session_builder:
            logging.warning(
                f"No AWS access for cluster {cluster.name}. Skipping STS gate handling."
            )
            return False

        with self.rosa_session_builder[cluster.id] as rosa:
            try:
                # account role handling
                account_role_prefix = cluster.aws.account_role_prefix
                if not account_role_prefix:
                    raise Exception(
                        f"Can't upgrade account roles. Cluster {cluster.name} does not define spec.aws.account_role_prefix"
                    )
                rosa.upgrade_account_roles(
                    account_role_prefix, gate.version_raw_id_prefix, dry_run
                )

                # operator role handling
                operator_role_prefix = cluster.aws.sts.operator_role_prefix
                if not operator_role_prefix:
                    raise Exception(
                        f"Can't upgrade operator roles. Cluster {cluster.name} does not define spec.aws.sts.operator_role_prefix"
                    )
                rosa.upgrade_operator_roles(
                    operator_role_prefix, gate.version_raw_id_prefix, dry_run
                )
            except RosaCliException as e:
                logging.error(
                    f"Failed to upgrade roles for cluster {cluster.name}: {e}"
                )
                e.write_logs_to_logger(logging.error)
                return False
        return True

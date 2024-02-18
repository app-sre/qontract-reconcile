import logging
from typing import Optional

from reconcile.aus.version_gates.handler import GateHandler
from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.ocm.base import OCMCluster, OCMVersionGate
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.rosa.rosa_cli import RosaCliException
from reconcile.utils.rosa.session import RosaSession

GATE_LABEL = "api.openshift.com/gate-sts"


class STSGateHandler(GateHandler):
    def __init__(
        self,
        job_controller: K8sJobController,
        rosa_job_service_account: Optional[str] = None,
        rosa_job_image: Optional[str] = None,
    ) -> None:
        self.job_controller = job_controller
        self.rosa_job_image = rosa_job_image
        self.rosa_job_service_account = rosa_job_service_account

    @staticmethod
    def responsible_for(cluster: OCMCluster) -> bool:
        return cluster.is_sts()

    def handle(
        self,
        ocm_api: OCMBaseClient,
        ocm_org_id: str,
        cluster: OCMCluster,
        gate: OCMVersionGate,
        dry_run: bool,
    ) -> bool:
        if (
            not cluster.id
            or not cluster.aws
            or not cluster.aws.sts
            or not cluster.is_sts()
        ):
            # checked already but mypy :/
            return False
        if cluster.is_rosa_hypershift():
            # thanks to hypershift managed policies, there is nothing to do for us here
            # returning True will ack the version gate
            return True

        rosa = RosaSession(
            aws_account_id=cluster.aws.aws_account_id,
            aws_region=cluster.region.id,
            ocm_org_id=ocm_org_id,
            ocm_api=ocm_api,
            job_controller=self.job_controller,
            image=self.rosa_job_image,
            service_account=self.rosa_job_service_account,
        )

        try:
            # account role handling
            account_role_prefix = cluster.aws.account_role_prefix
            if not account_role_prefix:
                raise Exception(
                    f"Can't upgrade account roles. Cluster {cluster.name} does not define spec.aws.account_role_prefix"
                )
            rosa.upgrade_account_roles(
                role_prefix=account_role_prefix,
                minor_version=gate.version_raw_id_prefix,
                channel_group=cluster.version.channel_group,
                dry_run=dry_run,
            )

            # operator role handling
            operator_role_prefix = cluster.aws.sts.operator_role_prefix
            if not operator_role_prefix:
                raise Exception(
                    f"Can't upgrade operator roles. Cluster {cluster.name} does not define spec.aws.sts.operator_role_prefix"
                )
            rosa.upgrade_operator_roles(
                cluster_id=cluster.id,
                role_prefix=operator_role_prefix,
                minor_version=gate.version_raw_id_prefix,
                channel_group=cluster.version.channel_group,
                dry_run=dry_run,
            )
        except RosaCliException as e:
            logging.error(f"Failed to upgrade roles for cluster {cluster.name}: {e}")
            e.write_logs_to_logger(logging.error)
            return False
        return True

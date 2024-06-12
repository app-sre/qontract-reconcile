import logging

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
        aws_iam_role: str,
        rosa_job_service_account: str | None = None,
        rosa_job_image: str | None = None,
    ) -> None:
        self.job_controller = job_controller
        self.aws_iam_role = aws_iam_role
        self.rosa_job_image = rosa_job_image
        self.rosa_job_service_account = rosa_job_service_account

    @staticmethod
    def gate_applicable_to_cluster(cluster: OCMCluster) -> bool:
        """
        The STS Gate is applicable to all clusters with STS enabled.
        This could potentially also be OSD STS clusters. While this handler
        does not handle OSD clusters as of now, it is still important that
        we report the STS gate to be applicable to OSD STS clusters.
        """
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
        if not cluster.is_rosa_classic():
            # we manage roels only for rosa classic clusters
            # returning here will prevent OSD STS clusters to be handled right now
            logging.error(
                f"Cluster {cluster.id} is not a ROSA cluster. "
                "STS version gates are only handled for ROSA classic clusters."
            )
            return False

        rosa = RosaSession(
            aws_account_id=cluster.aws.aws_account_id,
            aws_region=cluster.region.id,
            aws_iam_role=self.aws_iam_role,
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
            rosa.upgrade_operator_roles(
                cluster_id=cluster.id,
                dry_run=dry_run,
            )
        except RosaCliException as e:
            logging.error(f"Failed to upgrade roles for cluster {cluster.name}: {e}")
            e.write_logs_to_logger(logging.error)
            return False
        return True

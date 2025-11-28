import logging

from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.ocm.base import OCMCluster
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.rosa.rosa_cli import RosaCliError
from reconcile.utils.rosa.session import RosaSession
from reconcile.utils.semver_helper import get_version_prefix

STS_GATE_LABEL = "api.openshift.com/gate-sts"
AUS_VERSION_GATE_APPROVALS_LABEL = "sre-capabilities.aus.version-gate-approvals"


class AUSSTSGateHandler:
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

    def upgrade_rosa_roles(
        self,
        cluster: OCMCluster,
        upgrade_version: str,
        dry_run: bool,
        ocm_api: OCMBaseClient,
        ocm_org_id: str,
    ) -> bool:
        if not cluster.aws:
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
        policy_version = get_version_prefix(upgrade_version)
        try:
            rosa.upgrade_rosa_roles(
                cluster_name=cluster.name,
                upgrade_version=upgrade_version,
                policy_version=policy_version,
                dry_run=dry_run,
            )
        except RosaCliError as e:
            logging.error(f"Failed to upgrade roles for cluster {cluster.name}: {e}")
            e.write_logs_to_logger(logging.error)
            return False
        return True

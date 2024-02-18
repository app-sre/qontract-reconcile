import tempfile
from typing import Optional

from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.jobcontroller.models import JobConcurrencyPolicy, JobStatus
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.rosa.rosa_cli import (
    LogHandle,
    RosaCliException,
    RosaCliResult,
    RosaJob,
)


class RosaSession:
    """
    A ROSA session contains the required context to interact with OCM and AWS
    for a specific cluster.
    """

    def __init__(
        self,
        aws_account_id: str,
        aws_region: str,
        ocm_org_id: str,
        ocm_api: OCMBaseClient,
        job_controller: K8sJobController,
        image: Optional[str] = None,
        service_account: Optional[str] = None,
    ):
        self.aws_account_id = aws_account_id
        self.aws_region = aws_region
        self.ocm_org_id = ocm_org_id
        self.ocm_api = ocm_api
        self.job_controller = job_controller
        self.image = image or "registry.ci.openshift.org/ci/rosa-aws-cli:latest"
        self.service_account = service_account or "default"

    def assemble_job(
        self,
        cmd: str,
        annotations: Optional[dict[str, str]] = None,
        image: Optional[str] = None,
    ) -> RosaJob:
        return RosaJob(
            aws_account_id=self.aws_account_id,
            ocm_org_id=self.ocm_org_id,
            cmd=self.wrap_cli_command(cmd),
            aws_region=self.aws_region,
            ocm_token=self.ocm_api._access_token,
            image=image or self.image,
            extra_annotations=annotations or {},
            service_account=self.service_account,
        )

    def wrap_cli_command(self, cmd: str) -> str:
        return f"rosa login > /dev/null && {cmd}"

    def cli_execute(
        self,
        cmd: str,
        annotations: Optional[dict[str, str]] = None,
        image: Optional[str] = None,
    ) -> RosaCliResult:
        """
        Execute CLI commands in the context of a valid ROSA session (rosa login not required).
        The provided cmd needs to be a single command. If multiple commands are required, they
        need to be combined delimited with a ;
        """
        job = self.assemble_job(cmd, annotations, image)

        status = self.job_controller.enqueue_job_and_wait_for_completion(
            job,
            check_interval_seconds=2,
            timeout_seconds=60,
            concurrency_policy=JobConcurrencyPolicy.REPLACE_FAILED,
        )
        log_dir = tempfile.mkdtemp()
        self.job_controller.store_job_logs(job.name(), log_dir)
        log_file = f"{log_dir}/{job.name()}"
        if status != JobStatus.SUCCESS:
            raise RosaCliException(status, cmd, LogHandle(log_file))
        return RosaCliResult(status, cmd, LogHandle(log_file))

    def upgrade_account_roles(
        self, role_prefix: str, minor_version: str, channel_group: str, dry_run: bool
    ) -> None:
        if not dry_run:
            self.cli_execute(
                f"rosa upgrade account-roles --prefix {role_prefix} --version {minor_version} --channel-group {channel_group} -y -m=auto"
            )

    def upgrade_operator_roles(
        self,
        cluster_id: str,
        role_prefix: str,
        minor_version: str,
        channel_group: str,
        dry_run: bool,
    ) -> None:
        if not dry_run:
            self.cli_execute(
                cmd=f"rosa upgrade operator-roles --cluster {cluster_id} --prefix {role_prefix} --version {minor_version}.z --channel-group {channel_group} -y -m=auto",
                annotations={"qontract.rosa.cluster_id": cluster_id},
            )

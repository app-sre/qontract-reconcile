import logging
import tempfile
from typing import Optional

from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from reconcile.ocm.types import OCMSpec
from reconcile.utils.constants import PROJ_ROOT
from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.jobcontroller.models import JobConcurrencyPolicy, JobStatus
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.rosa.rosa_cli import (
    LogHandle,
    RosaCliException,
    RosaCliResult,
    RosaJob,
)


class RosaSessionBuilder(BaseModel, arbitrary_types_allowed=True):
    aws_iam_role: str
    job_controller: K8sJobController
    image: str
    service_account: str

    def build(
        self, ocm_api: OCMBaseClient, aws_account_id: str, region: str, ocm_org_id: str
    ) -> "RosaSession":
        return RosaSession(
            aws_account_id=aws_account_id,
            aws_region=region,
            aws_iam_role=self.aws_iam_role,
            ocm_org_id=ocm_org_id,
            ocm_api=ocm_api,
            job_controller=self.job_controller,
            image=self.image,
            service_account=self.service_account,
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
        aws_iam_role: str,
        ocm_org_id: str,
        ocm_api: OCMBaseClient,
        job_controller: K8sJobController,
        image: Optional[str] = None,
        service_account: Optional[str] = None,
    ):
        self.aws_account_id = aws_account_id
        self.aws_region = aws_region
        self.aws_iam_role = aws_iam_role
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
            aws_iam_role=self.aws_iam_role,
            aws_region=self.aws_region,
            ocm_org_id=self.ocm_org_id,
            ocm_token=self.ocm_api._access_token,
            cmd=cmd,
            image=image or self.image,
            extra_annotations=annotations or {},
            service_account=self.service_account,
        )

    def cli_execute(
        self,
        cmd: str,
        annotations: Optional[dict[str, str]] = None,
        image: Optional[str] = None,
        check_interval_seconds: int = 5,
        timeout_seconds: int = 60,
    ) -> RosaCliResult:
        """
        Execute CLI commands in the context of a valid ROSA session (rosa login not required).
        The provided cmd needs to be a single command. If multiple commands are required, they
        need to be combined delimited with a ;
        """
        job = self.assemble_job(cmd, annotations, image)

        status = self.job_controller.enqueue_job_and_wait_for_completion(
            job,
            check_interval_seconds=check_interval_seconds,
            timeout_seconds=timeout_seconds,
            concurrency_policy=JobConcurrencyPolicy.REPLACE_FAILED,
        )
        log_dir = tempfile.mkdtemp()
        log_file_name = self.job_controller.store_job_logs(job.name(), log_dir)
        if status != JobStatus.SUCCESS:
            raise RosaCliException(status, cmd, LogHandle(log_file_name))
        return RosaCliResult(status, cmd, LogHandle(log_file_name))

    def create_hcp_cluster(
        self,
        cluster_name: str,
        spec: OCMSpec,
        dry_run: bool,
        check_interval_seconds: int = 10,
        timeout_seconds: int = 300,
    ) -> RosaCliResult:
        """
        Create a ROSA HCP cluster in the OCM org and AWS account of this session.
        If dry-run is provided, cluster creation is simulated and invalid configuration
        data is highlighted as errors.
        """
        return self.cli_execute(
            cmd=rosa_hcp_creation_script(cluster_name, spec, dry_run),
            check_interval_seconds=check_interval_seconds,
            timeout_seconds=timeout_seconds,
        )

    def upgrade_account_roles(
        self, role_prefix: str, minor_version: str, channel_group: str, dry_run: bool
    ) -> None:
        logging.info(
            f"Upgrade account roles in AWS account {self.aws_account_id} to {minor_version} ({channel_group})"
        )
        if not dry_run:
            result = self.cli_execute(
                f"rosa upgrade account-roles --prefix {role_prefix} --version {minor_version} --channel-group {channel_group} -y -m=auto"
            )
            result.write_logs_to_logger(logging.info)

    def upgrade_operator_roles(
        self,
        cluster_id: str,
        dry_run: bool,
    ) -> None:
        """
        Upgrades the operator roles of a cluster to match the latest
        policy versions available for the cluster.
        """
        logging.info(
            f"Upgrade operator roles in AWS account {self.aws_account_id} for cluster {cluster_id}"
        )
        if not dry_run:
            result = self.cli_execute(
                cmd=f"rosa upgrade operator-roles --cluster {cluster_id} -y -m=auto",
                annotations={"qontract.rosa.cluster_id": cluster_id},
            )
            result.write_logs_to_logger(logging.info)


def rosa_hcp_creation_script(cluster_name: str, cluster: OCMSpec, dry_run: bool) -> str:
    """
    Builds a bash script to install a ROSA clusters.
    """
    # template_path = PROJ_ROOT / "templates" / "rosa-hcp-cluster-creation.sh.j2"
    # with open(template_path, encoding="utf-8") as f:
    env = Environment(loader=FileSystemLoader(PROJ_ROOT / "templates"))
    env.filters["split"] = lambda value, sep: value.split(sep)
    template = env.get_template("rosa-hcp-cluster-creation.sh.j2")
    # template = Template(f.read(), keep_trailing_newline=True, trim_blocks=True)
    return template.render(
        cluster_name=cluster_name,
        cluster=cluster,
        dry_run=dry_run,
    )

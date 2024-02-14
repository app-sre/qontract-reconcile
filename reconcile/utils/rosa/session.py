import tempfile
from types import TracebackType
from typing import Optional, Type

from reconcile.utils.aws_api import (
    AWSSessionBuilder,
    AWSStaticCredsSessionBuilder,
)
from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.jobcontroller.models import JobConcurrencyPolicy, JobStatus
from reconcile.utils.ocm_base_client import (
    OCMAPIClientConfiguration,
    OCMAPIClientConfigurationProtocol,
    OCMBaseClient,
    init_ocm_base_client,
)
from reconcile.utils.rosa.model import ROSACluster
from reconcile.utils.rosa.rosa_cli import (
    LogHandle,
    RosaCliException,
    RosaCliResult,
    RosaJob,
)
from reconcile.utils.secret_reader import SecretReaderBase


class RosaSession:
    """
    A ROSA session contains the required context to interact with OCM and AWS
    for a specific cluster.
    """

    def __init__(
        self,
        cluster: ROSACluster,
        aws_session_builder: AWSSessionBuilder,
        ocm_api: OCMBaseClient,
        job_controller: K8sJobController,
    ):
        self.cluster = cluster
        self.aws_session_builder = aws_session_builder
        self.ocm_api = ocm_api
        self.job_controller = job_controller
        self._closed = False

    def close(self) -> None:
        self._closed = True
        self.ocm_api.close()

    def is_closed(self) -> bool:
        return self._closed

    def cli_execute(self, cmd: str) -> RosaCliResult:
        """
        Execute CLI commands in the context of a valid ROSA session (rosa login not required).
        The provided cmd needs to be a single command. If multiple commands are required, they
        need to be combined into a single command with /bin/bash -c.
        """
        aws_tmp_creds = self.aws_session_builder.build_temporary_credentials()
        job = RosaJob(
            account_name=self.cluster.spec.account.name,
            cluster_name=self.cluster.name,
            org_id=self.cluster.ocm.org_id,
            cmd=f"rosa login > /dev/null && {cmd}",
            aws_credentials=aws_tmp_creds,
            ocm_token=self.ocm_api._access_token,
        )

        status = self.job_controller.enqueue_job_and_wait_for_completion(
            job,
            check_interval_seconds=2,
            timeout_seconds=60,
            concurrency_policy=JobConcurrencyPolicy.REPLACE_FAILED,
        )
        log_dir = tempfile.TemporaryDirectory()
        self.job_controller.store_job_logs(job.name(), log_dir.name)
        log_file = f"{log_dir.name}/{job.name()}"
        if status != JobStatus.SUCCESS:
            raise RosaCliException(status, cmd, LogHandle(log_file))
        return RosaCliResult(status, cmd, LogHandle(log_file))

    def upgrade_account_roles(
        self, role_prefix: str, minor_version: str, dry_run: bool
    ) -> None:
        if not dry_run:
            self.cli_execute(
                f"rosa upgrade account-roles --prefix {role_prefix} --version {minor_version} --channel-group {self.cluster.spec.channel} -y -m=auto"
            )

    def upgrade_operator_roles(
        self, role_prefix: str, minor_version: str, dry_run: bool
    ) -> None:
        cluster_id = self.cluster.spec.q_id
        if not cluster_id:
            raise Exception(
                f"Can't upgrade operator roles. Cluster {self.cluster.name} does not define spec.cluster_id"
            )
        if not dry_run:
            self.cli_execute(
                f"rosa upgrade operator-roles --cluster {cluster_id} --prefix {role_prefix} --version {minor_version}.z --channel-group {self.cluster.spec.channel} -y -m=auto"
            )


class RosaSessionContextManager:
    """
    A context manager providing a fresh ROSA session when entering.
    """

    def __init__(
        self,
        cluster: ROSACluster,
        aws_session_builder: AWSSessionBuilder,
        ocm_config: OCMAPIClientConfigurationProtocol,
        secret_reader: SecretReaderBase,
        job_controller: K8sJobController,
    ):
        self.cluster = cluster
        self.aws_session_builder = aws_session_builder
        self.ocm_config = ocm_config
        self.secret_reader = secret_reader
        self.job_controller = job_controller

        self._rosa_session: Optional[RosaSession] = None

    def __enter__(self) -> RosaSession:
        self._rosa_session = RosaSession(
            cluster=self.cluster,
            aws_session_builder=self.aws_session_builder,
            ocm_api=init_ocm_base_client(self.ocm_config, self.secret_reader),
            job_controller=self.job_controller,
        )
        return self._rosa_session

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        if self._rosa_session:
            self._rosa_session.close()
            self._rosa_session = None


def rosa_session_ctx(
    cluster: ROSACluster,
    secret_reader: SecretReaderBase,
    job_controller: K8sJobController,
) -> RosaSessionContextManager:
    """
    Creates a context manager for a ROSA session. The ROSA session
    itself is managed by the context manager and no AWS session nor
    OCM session is created at this point.
    """

    # build aws config
    aws_secret = secret_reader.read_all_secret(cluster.spec.account.automation_token)
    aws_session_builder = AWSStaticCredsSessionBuilder(
        access_key_id=aws_secret["aws_access_key_id"],
        secret_access_key=aws_secret["aws_secret_access_key"],
        region=cluster.spec.region,
    )

    # build OCM config
    ocm_config = OCMAPIClientConfiguration(
        url=cluster.ocm.environment.url,
        access_token_client_id=cluster.ocm.access_token_client_id
        or cluster.ocm.environment.access_token_client_id,
        access_token_client_secret=cluster.ocm.access_token_client_secret
        or cluster.ocm.environment.access_token_client_secret,
        access_token_url=cluster.ocm.access_token_url
        or cluster.ocm.environment.access_token_url,
    )

    rosa_session_builder = RosaSessionContextManager(
        cluster=cluster,
        aws_session_builder=aws_session_builder,
        ocm_config=ocm_config,
        secret_reader=secret_reader,
        job_controller=job_controller,
    )
    return rosa_session_builder

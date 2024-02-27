import collections
import itertools
import os
import textwrap
from collections.abc import Iterable
from typing import Any, Callable, Optional

from kubernetes.client import (
    V1Container,
    V1EmptyDirVolumeSource,
    V1EnvVar,
    V1JobSpec,
    V1ObjectMeta,
    V1PodSpec,
    V1PodTemplateSpec,
    V1ProjectedVolumeSource,
    V1SecretVolumeSource,
    V1ServiceAccountTokenProjection,
    V1Volume,
    V1VolumeMount,
    V1VolumeProjection,
)
from pydantic import BaseModel

from reconcile.utils.jobcontroller.models import JobStatus, K8sJob

SCRIPTS_MOUNT_PATH = "/scripts"
EXEC_SCRIPT = "execute.sh"


class LogHandle:
    """
    Represents a handle to a log file and offers convenience methods to consume
    the log content in an efficient manner.
    """

    def __init__(self, log_file: str) -> None:
        self.log_file = log_file

    def get_log_lines(
        self, max_lines: int = 5, from_file_end: bool = False
    ) -> Iterable[str]:
        if max_lines <= 0:
            return []
        with open(self.log_file, "r", encoding="utf-8") as f:
            if from_file_end:
                return collections.deque(f, maxlen=max_lines)
            return [line.rstrip() for line in itertools.islice(f, max_lines)]

    def write_logs_to_logger(self, logger: Callable[..., None]) -> None:
        with open(self.log_file, "r", encoding="utf-8") as f:
            logger(f.read())

    def exists(self) -> bool:
        return os.path.exists(self.log_file)

    def cleanup(self) -> None:
        os.remove(self.log_file)


class RosaCliResult:
    """
    Represents the result of a ROSA CLI execution.
    """

    def __init__(
        self,
        status: JobStatus,
        command: str,
        log_handle: Optional[LogHandle] = None,
    ) -> None:
        self.status = status
        self.command = command
        self.log_handle = log_handle

    def get_log_lines(
        self, max_lines: int = 5, from_file_end: bool = False
    ) -> Iterable[str]:
        if self.log_handle:
            return self.log_handle.get_log_lines(
                max_lines=max_lines, from_file_end=from_file_end
            )
        return []

    def write_logs_to_logger(self, logger: Callable[..., None]) -> None:
        if self.log_handle:
            self.log_handle.write_logs_to_logger(logger)

    def cleanup(self) -> None:
        if self.log_handle:
            self.log_handle.cleanup()


class RosaCliException(Exception, RosaCliResult):
    """
    Represents an exception that occurred during a ROSA CLI execution.
    """

    def __init__(
        self,
        status: JobStatus,
        command: str,
        log_handle: Optional[LogHandle] = None,
    ) -> None:
        Exception.__init__(
            self, f"ROSA CLI execution failed with status: {status}, cmd: {command}"
        )
        RosaCliResult.__init__(self, status, command, log_handle)


class RosaJob(K8sJob, BaseModel, frozen=True, arbitrary_types_allowed=True):
    """
    Represents a ROSA CLI job. It leverages the reconcile.utils.jobcontroller module
    functionality to execute ROSA CLI commands in a Kubernetes cluster.

    Since the ROSA CLI requires access to both AWS and OCM, the job is executed
    with the required credentials and tokens.
    """

    aws_account_id: str
    aws_region: str
    aws_iam_role: str
    ocm_org_id: str
    ocm_token: str
    cmd: str
    image: str
    service_account: str

    extra_annotations: dict[str, str]

    def name_prefix(self) -> str:
        return "rosa-cli"

    def unit_of_work_identity(self) -> Any:
        return {
            "cmd": self.cmd,
            "aws_account_id": self.aws_account_id,
            "aws_region": self.aws_region,
            "image": self.image,
            "service_account": self.service_account,
        }

    def annotations(self) -> dict[str, str]:
        _annotations = {
            "qontract.rosa.aws_account_id": self.aws_account_id,
            "qontract.rosa.aws_region": self.aws_region,
            "qontract.rosa.ocm_org_id": self.ocm_org_id,
        }
        _annotations.update(self.extra_annotations)
        return _annotations

    def secret_data(self) -> dict[str, str]:
        return {"OCM_TOKEN": self.ocm_token}

    def scripts(self) -> dict[str, str]:
        return {EXEC_SCRIPT: self.cmd}

    def assume_role_arn(self) -> str:
        return f"arn:aws:iam::{self.aws_account_id}:role/{self.aws_iam_role}"

    def assume_role_profile(self) -> str:
        return textwrap.dedent(
            f"""\
            [default]
            source_profile = jump-role
            role_arn = {self.assume_role_arn()}
            role_session_name = rosa-automation
            """
        )

    def job_spec(self) -> V1JobSpec:
        # this command formats the output of `aws sts assume-role` into an AWS credentials file
        prepare_aws_creds_cmd = f'cp $AWS_SHARED_CREDENTIALS_FILE /.config/aws-credentials ; echo -e "\n{self.assume_role_profile()}" >> /.config/aws-credentials'

        return V1JobSpec(
            backoff_limit=1,
            ttl_seconds_after_finished=3600,
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(
                    annotations=self.annotations(), labels=self.labels()
                ),
                spec=V1PodSpec(
                    init_containers=[
                        # prepare the AWS credentials file to assume role into the ROSA clusters AWS account
                        V1Container(
                            name="prepare-aws-creds",
                            image=self.image,
                            command=["/bin/bash"],
                            args=["-c", prepare_aws_creds_cmd],
                            env=[
                                V1EnvVar(
                                    name="AWS_SHARED_CREDENTIALS_FILE",
                                    value="/jump-role/credentials",
                                ),
                                V1EnvVar(
                                    name="HOME",
                                    value="/tmp",
                                ),
                            ],
                            volume_mounts=[
                                V1VolumeMount(
                                    name="aws-credentials",
                                    mount_path="/jump-role",
                                ),
                                V1VolumeMount(
                                    name="workdir",
                                    mount_path="/.config",
                                ),
                            ],
                        ),
                        # call `rosa login``
                        V1Container(
                            name="rosa-login",
                            image=self.image,
                            command=["/bin/bash", "-c"],
                            args=["rosa login"],
                            env=[
                                V1EnvVar(
                                    name="AWS_SHARED_CREDENTIALS_FILE",
                                    value="/.config/aws-credentials",
                                ),
                                V1EnvVar(
                                    name="AWS_REGION",
                                    value=self.aws_region,
                                ),
                            ]
                            + self.secret_data_to_env_vars_secret_refs(),
                            volume_mounts=[
                                V1VolumeMount(
                                    name="workdir",
                                    mount_path="/.config",
                                ),
                                V1VolumeMount(
                                    name="bound-sa-token",
                                    mount_path="/var/run/secrets/openshift/serviceaccount",
                                    read_only=True,
                                ),
                            ],
                        ),
                    ],
                    containers=[
                        # the actual job... do whatever `cmd` defines
                        V1Container(
                            name="rosa-cli",
                            image=self.image,
                            command=["/bin/bash"],
                            args=[f"{SCRIPTS_MOUNT_PATH}/{EXEC_SCRIPT}"],
                            env=[
                                V1EnvVar(
                                    name="AWS_SHARED_CREDENTIALS_FILE",
                                    value="/.config/aws-credentials",
                                ),
                                V1EnvVar(
                                    name="AWS_REGION",
                                    value=self.aws_region,
                                ),
                            ]
                            + self.secret_data_to_env_vars_secret_refs(),
                            volume_mounts=[
                                V1VolumeMount(
                                    name="workdir",
                                    mount_path="/.config",
                                ),
                                V1VolumeMount(
                                    name="workdir",
                                    mount_path="/.aws",
                                ),
                                V1VolumeMount(
                                    name="bound-sa-token",
                                    mount_path="/var/run/secrets/openshift/serviceaccount",
                                    read_only=True,
                                ),
                                self.scripts_volume_mount(SCRIPTS_MOUNT_PATH),
                            ],
                        )
                    ],
                    restart_policy="Never",
                    service_account_name=self.service_account,
                    volumes=[
                        V1Volume(
                            name="aws-credentials",
                            secret=V1SecretVolumeSource(
                                secret_name="rosa-automation-sts-iam",
                            ),
                        ),
                        V1Volume(
                            name="bound-sa-token",
                            projected=V1ProjectedVolumeSource(
                                sources=[
                                    V1VolumeProjection(
                                        service_account_token=V1ServiceAccountTokenProjection(
                                            audience="openshift",
                                            expiration_seconds=3600,
                                            path="token",
                                        )
                                    )
                                ]
                            ),
                        ),
                        V1Volume(
                            name="workdir",
                            empty_dir=V1EmptyDirVolumeSource(
                                size_limit="10Mi",
                            ),
                        ),
                        self.scripts_volume(),
                    ],
                ),
            ),
        )

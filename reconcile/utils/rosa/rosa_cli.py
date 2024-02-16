import itertools
import os
from typing import Any, Callable, Optional

from kubernetes.client import (
    V1Container,
    V1EmptyDirVolumeSource,
    V1JobSpec,
    V1ObjectMeta,
    V1PodSpec,
    V1PodTemplateSpec,
    V1Volume,
    V1VolumeMount,
)
from pydantic import BaseModel

from reconcile.utils.aws_api import (
    AWSCredentials,
)
from reconcile.utils.jobcontroller.models import JobStatus, K8sJob


class LogHandle:
    """
    Represents a handle to a log file and offers convenience methods to consume
    the log content in an efficient manner.
    """

    def __init__(self, log_file: str) -> None:
        self.log_file = log_file

    def get_log_lines(self, max_lines: int = 5) -> list[str]:
        if max_lines <= 0:
            return []
        with open(self.log_file, "r", encoding="utf-8") as f:
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

    def get_log_lines(self, max_lines: int = 5) -> list[str]:
        if self.log_handle:
            return self.log_handle.get_log_lines(max_lines)
        return []

    def write_logs_to_logger(self, logger: Callable[..., None]) -> None:
        if self.log_handle:
            self.log_handle.write_logs_to_logger(logger)


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

    account_name: str
    cluster_name: str
    org_id: str
    cmd: str
    image: str

    aws_credentials: AWSCredentials
    ocm_token: str

    dry_run: bool = False

    def name_prefix(self) -> str:
        prefix = "rosa-cli"
        if self.dry_run:
            prefix += "-dry-run"
        return prefix

    def unit_of_work_identity(self) -> Any:
        return {
            "cmd": self.cmd,
            "account_name": self.account_name,
            "cluster_name": self.cluster_name,
            "org_id": self.org_id,
            "dry_run": self.dry_run,
            "image": self.image,
        }

    def annotations(self) -> dict[str, str]:
        return {
            "qontract.rosa.account_name": self.account_name,
            "qontract.rosa.cluster_name": self.cluster_name,
            "qontract.rosa.org_id": self.org_id,
        }

    def secret_data(self) -> dict[str, str]:
        data = self.aws_credentials.as_env_vars()
        data["OCM_TOKEN"] = self.ocm_token
        return data

    def job_spec(self) -> V1JobSpec:
        return V1JobSpec(
            backoff_limit=1,
            ttl_seconds_after_finished=3600,
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(
                    annotations=self.annotations(), labels=self.labels()
                ),
                spec=V1PodSpec(
                    containers=[
                        V1Container(
                            name="rosa-cli",
                            image=self.image,
                            command=["/bin/bash", "-c"],
                            args=[self.cmd],
                            env=self.secret_data_to_env_vars_secret_refs(),
                            volume_mounts=[
                                V1VolumeMount(
                                    name="workdir",
                                    mount_path="/.config",
                                )
                            ],
                        )
                    ],
                    restart_policy="Never",
                    service_account_name="default",
                    volumes=[
                        V1Volume(
                            name="workdir",
                            empty_dir=V1EmptyDirVolumeSource(
                                size_limit="10Mi",
                            ),
                        )
                    ],
                ),
            ),
        )

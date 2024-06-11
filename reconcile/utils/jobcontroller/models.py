import hashlib
import inspect
from abc import ABC, abstractmethod
from enum import IntFlag, StrEnum
from typing import Any

from deepdiff import DeepHash
from kubernetes.client import (
    V1EnvVar,
    V1EnvVarSource,
    V1Job,
    V1JobSpec,
    V1KeyToPath,
    V1ObjectMeta,
    V1SecretKeySelector,
    V1SecretVolumeSource,
    V1Volume,
    V1VolumeMount,
)


class JobStatus(StrEnum):
    SUCCESS: str = "SUCCESS"
    ERROR: str = "ERROR"
    IN_PROGRESS: str = "IN_PROGRESS"
    NOT_EXISTS: str = "NOT_EXISTS"


class JobConcurrencyPolicy(IntFlag):
    NO_REPLACE: int = 1
    REPLACE_FAILED: int = 2
    REPLACE_IN_PROGRESS: int = 4
    REPLACE_FINISHED: int = 8


class JobValidationError(Exception):
    pass


JOB_GENERATION_ANNOTATION = "qontract-reconcile/job.generation"


class K8sJob(ABC):
    """
    This is the base class for all jobs that will be managed by the
    K8sJobController.

    A job needs to implement the following methods:
    - name_prefix: return the prefix of the job name. This is useful to group
        jobs of the same type together. The prefix is part of the final job name.

    - unit_of_work_identity: return the data that uniquely identifies the unit
        of work that the job will perform. This data will be used to calculate a
        hash that will be used as part of the job name. This way a unit of work
        can be uniquely identified by the job name.

    - job_spec: return the job spec that will be used as the spec part of
        the Kubernetes Job.

    The job can optionally also implement the following methods:
    - annotations: return a dictionary with the annotations that will be used
        in the job metadata.
    - labels: return a dictionary with the labels that will be used in the job
        metadata.
    - build_job: return the V1Job object that will be used to create the job in
        Kubernetes. Override this method if you need to customize the job that
        will represent your unit of work in Kubernetes.
    - name: return the name of the job. Override this method if you need to
        customize the name of the job that will represent your unit of work in
        Kubernetes. Keep in mind that the name of the job is used to identify job
        and the controllers concurrency policy functionality is based on the job name.
    """

    def name(self) -> str:
        return f"{self.name_prefix()}-{self.unit_of_work_digest()}"

    @abstractmethod
    def name_prefix(self) -> str:
        """
        Return the prefix of the job name. This is useful to group jobs of the
        same type together. The prefix is part of the final job name.
        """
        ...

    def unit_of_work_digest(self, length: int = 10) -> str:
        data = self.unit_of_work_identity()
        hash = DeepHash(data).get(data)
        return str(hash)[:length]

    @abstractmethod
    def unit_of_work_identity(self) -> Any:
        """
        Return the data that uniquely identifies the unit of work that the job
        will perform. This data will be used to calculate a hash that will be
        used as part of the job name.
        """
        ...

    def annotations(self) -> dict[str, Any]:
        return {}

    def labels(self) -> dict[str, str]:
        return {}

    def build_job(self) -> V1Job:
        job_annotations = self.annotations()
        job_annotations[JOB_GENERATION_ANNOTATION] = self.job_spec_generation_digest()
        return V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=V1ObjectMeta(
                name=self.name(),
                annotations=job_annotations,
                labels=self.labels(),
            ),
            spec=self.job_spec(),
        )

    @abstractmethod
    def job_spec(self) -> V1JobSpec: ...

    def job_spec_generation_digest(self, length: int = 10) -> str:
        """
        Calculate a hash of the job spec source code to be used as a generation
        identifier for the job spec. This is useful to determine if the job
        spec has changed and a job needs to be replaced.
        """
        job_spec_source_code = inspect.getsource(self.job_spec)
        hash_object = hashlib.sha256(job_spec_source_code.encode())
        hash = hash_object.hexdigest()
        return hash[:length]

    def secret_data(self) -> dict[str, str]:
        """
        If a job relies on some secret data, it should return it here. The
        job controller will manage the lifecycle of a kubernetes Secret.
        """
        return {}

    def scripts(self) -> dict[str, str]:
        """
        If a job relies on some scripts, it should return them here. The
        job controller will manage the lifecycle of a kubernetes Secret containing them.
        """
        return {}

    def secret_data_to_env_vars_secret_refs(self) -> list[V1EnvVar]:
        """
        Helper function to generate env var references from the `secret_data`,
        to be used in container specs
        """
        secret_name = self.name()
        return [
            V1EnvVar(
                name=secret_key_name,
                value_from=V1EnvVarSource(
                    secret_key_ref=V1SecretKeySelector(
                        name=secret_name,
                        key=secret_key_name,
                    )
                ),
            )
            for secret_key_name in self.secret_data().keys()
        ]

    def scripts_volume_mount(self, directory: str) -> V1VolumeMount:
        """
        Helper function to generate a volume mount for the `scripts` to be used
        in container specs
        """
        secret_name = self.name()
        return V1VolumeMount(
            name=secret_name,
            mount_path=directory,
        )

    def scripts_volume(self) -> V1Volume:
        """
        Helper function to generate a volume for the `scripts` to be used in
        pod specs
        """
        secret_name = self.name()
        return V1Volume(
            name=secret_name,
            secret=V1SecretVolumeSource(
                secret_name=secret_name,
                items=[
                    V1KeyToPath(
                        key=script_name,
                        path=script_name,
                    )
                    for script_name in self.scripts().keys()
                ],
            ),
        )

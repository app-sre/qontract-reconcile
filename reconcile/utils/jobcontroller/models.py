from abc import ABC, abstractmethod
from enum import Enum, IntFlag
from typing import Any

from deepdiff import DeepHash
from kubernetes.client import V1Job, V1JobSpec, V1ObjectMeta


class JobStatus(str, Enum):
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


class K8sJob(ABC):
    def name(self) -> str:
        return f"{self.name_prefix()}-{self.job_identity_digest()}"

    @abstractmethod
    def name_prefix(self) -> str: ...

    def job_identity_digest(self, length: int = 10) -> str:
        data = self.job_identity_data()
        hash = DeepHash(data).get(data)
        return str(hash)[:length]

    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    def job_identity_data(self) -> Any: ...

    def annotations(self) -> dict[str, Any]:
        return {}

    def labels(self) -> dict[str, str]:
        return {}

    def build_job(self) -> V1Job:
        return V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=V1ObjectMeta(
                name=self.name(),
                annotations=self.annotations(),
                labels=self.labels(),
            ),
            spec=self.job_spec(),
        )

    @abstractmethod
    def job_spec(self) -> V1JobSpec: ...

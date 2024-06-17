from typing import Any

from kubernetes.client import (  # type: ignore[attr-defined]
    ApiClient,
    V1JobSpec,
    V1PodTemplateSpec,
)
from pydantic import BaseModel

from reconcile.utils.jobcontroller.models import K8sJob


class SomeJob(K8sJob, BaseModel):
    identifying_attribute: str
    backoff_limit: int = 0
    credentials: dict[str, str] | None = None
    script: str | None = None

    def name_prefix(self) -> str:
        return "some-job"

    def unit_of_work_identity(self) -> Any:
        return self.identifying_attribute

    def job_spec(self) -> V1JobSpec:
        return V1JobSpec(
            backoff_limit=self.backoff_limit,
            ttl_seconds_after_finished=10,
            template=V1PodTemplateSpec(),
        )

    def secret_data(self) -> dict[str, str]:
        return self.credentials or {}

    def scripts(self) -> dict[str, str]:
        return (
            {
                "script.sh": self.script,
            }
            if self.script
            else {}
        )


class SomeJobV2(K8sJob, BaseModel):
    identifying_attribute: str
    credentials: dict[str, str] | None = None

    def name_prefix(self) -> str:
        return "some-job"

    def unit_of_work_identity(self) -> Any:
        return self.identifying_attribute

    def job_spec(self) -> V1JobSpec:
        return V1JobSpec(
            backoff_limit=2,  # this is the only difference from SomeJob
            ttl_seconds_after_finished=10,
            template=V1PodTemplateSpec(),
        )


def build_job_status(
    active: int = 0, succeeded: int = 0, failed: int = 0
) -> dict[str, Any]:
    return {
        "active": active,
        "succeeded": succeeded,
        "failed": failed,
    }


def build_job_resource(
    job: SomeJob, status: dict[str, Any] | None = None
) -> dict[str, Any]:
    job_resource = ApiClient().sanitize_for_serialization(job.build_job())
    if status:
        job_resource["status"] = status
    return job_resource

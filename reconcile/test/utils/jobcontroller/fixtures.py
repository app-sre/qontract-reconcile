from typing import Any, Optional
from unittest.mock import create_autospec

from kubernetes.client import (  # type: ignore[attr-defined]
    ApiClient,
    V1JobSpec,
    V1PodTemplateSpec,
)
from pydantic import BaseModel

from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.jobcontroller.models import K8sJob
from reconcile.utils.oc import OCCli


class SomeJob(K8sJob, BaseModel):
    identifying_attribute: str
    backoff_limit: int = 0

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


class SomeJobV2(K8sJob, BaseModel):
    identifying_attribute: str

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
    job: SomeJob, status: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    job_resource = ApiClient().sanitize_for_serialization(job.build_job())
    if status:
        job_resource["status"] = status
    return job_resource


def build_oc_fixture(job_specs: Optional[list[list[dict[str, Any]]]] = None) -> OCCli:
    mocked_oc_client = create_autospec(OCCli)
    mocked_oc_client.get_items.side_effect = job_specs or [[]]
    return mocked_oc_client


def build_job_controller_fixture(oc: OCCli, dry_run: bool) -> K8sJobController:
    return K8sJobController(
        oc=oc,
        cluster="some-cluster",
        namespace="some-ns",
        integration="some-integration",
        integration_version="0.1",
        dry_run=dry_run,
        time_module=TimeMock(),
    )


class TimeMock:
    def __init__(self) -> None:
        self.current_time = 0.0

    def time(self) -> float:
        return self.current_time

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("Negative value for sleep seconds not allowed")
        self.current_time += seconds

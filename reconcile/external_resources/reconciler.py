import sys
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from kubernetes.client import (
    V1Container,
    V1EmptyDirVolumeSource,
    V1EnvVar,
    V1EnvVarSource,
    V1JobSpec,
    V1LocalObjectReference,
    V1ObjectFieldSelector,
    V1ObjectMeta,
    V1PodSpec,
    V1PodTemplateSpec,
    V1SecretVolumeSource,
    V1Volume,
    V1VolumeMount,
)
from pydantic import BaseModel

from reconcile.external_resources.model import (
    Reconciliation,
)
from reconcile.external_resources.state import ReconcileStatus
from reconcile.utils.jobcontroller.controller import (
    JobConcurrencyPolicy,
    K8sJobController,
)
from reconcile.utils.jobcontroller.models import K8sJob


class ExternalResourcesReconciler(ABC):
    @abstractmethod
    def get_resource_reconcile_status(
        self,
        reconciliation: Reconciliation,
    ) -> ReconcileStatus: ...

    @abstractmethod
    def get_resource_reconcile_duration(
        self, reconciliation: Reconciliation
    ) -> int | None: ...

    @abstractmethod
    def reconcile_resource(self, reconciliation: Reconciliation) -> None: ...

    @abstractmethod
    def get_resource_reconcile_logs(self, reconciliation: Reconciliation) -> None: ...

    @abstractmethod
    def wait_for_reconcile_list_completion(
        self,
        reconcile_list: Iterable[Reconciliation],
        check_interval_seconds: int,
        timeout_seconds: int,
    ) -> dict[str, ReconcileStatus]: ...


class ReconciliationK8sJob(K8sJob, BaseModel, frozen=True):
    """
    Wraps a reconciliation request into a Kubernetes Job
    """

    reconciliation: Reconciliation
    is_dry_run: bool = False
    dry_run_suffix: str = ""

    def name_prefix(self) -> str:
        if self.is_dry_run:
            return f"er-dry-run-mr-{self.dry_run_suffix}"
        else:
            return "er"

    def unit_of_work_identity(self) -> Any:
        return self.reconciliation.key

    def description(self) -> str:
        return f"Action: {self.reconciliation.action}, Key: {self.reconciliation.key} "

    def annotations(self) -> dict[str, Any]:
        return {
            "provision_provider": self.reconciliation.key.provision_provider,
            "provisioner": self.reconciliation.key.provisioner_name,
            "provider": self.reconciliation.key.provision_provider,
            "identifier": self.reconciliation.key.identifier,
        }

    def job_spec(self) -> V1JobSpec:
        return V1JobSpec(
            backoff_limit=0,
            active_deadline_seconds=self.reconciliation.module_configuration.reconcile_timeout_minutes
            * 60,
            ttl_seconds_after_finished=3600,
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(
                    annotations=self.annotations(), labels=self.labels()
                ),
                spec=V1PodSpec(
                    init_containers=[
                        V1Container(
                            name="job",
                            image=self.reconciliation.module_configuration.image_version,
                            image_pull_policy="Always",
                            env=[
                                V1EnvVar(
                                    name="DRY_RUN",
                                    value=str(self.is_dry_run),
                                ),
                                V1EnvVar(
                                    name="ACTION",
                                    value=self.reconciliation.action.value,
                                ),
                            ],
                            volume_mounts=[
                                V1VolumeMount(
                                    name="credentials",
                                    mount_path="/credentials",
                                    sub_path="credentials",
                                ),
                                V1VolumeMount(
                                    name="workdir",
                                    mount_path="/work",
                                ),
                                self.scripts_volume_mount("/inputs"),
                            ],
                        )
                    ],
                    containers=[
                        V1Container(
                            name="outputs",
                            image=self.reconciliation.module_configuration.outputs_secret_image_version,
                            image_pull_policy="Always",
                            env=[
                                V1EnvVar(
                                    name="NAMESPACE",
                                    value_from=V1EnvVarSource(
                                        field_ref=V1ObjectFieldSelector(
                                            field_path="metadata.namespace"
                                        )
                                    ),
                                ),
                                V1EnvVar(
                                    name="ACTION",
                                    value=self.reconciliation.action,
                                ),
                                V1EnvVar(
                                    name="DRY_RUN",
                                    value=str(self.is_dry_run),
                                ),
                            ],
                            volume_mounts=[
                                V1VolumeMount(
                                    name="credentials",
                                    mount_path="/.aws/credentials",
                                    sub_path="credentials",
                                ),
                                V1VolumeMount(
                                    name="workdir",
                                    mount_path="/work",
                                ),
                                self.scripts_volume_mount("/inputs"),
                            ],
                        )
                    ],
                    image_pull_secrets=[V1LocalObjectReference(name="quay.io")],
                    volumes=[
                        V1Volume(
                            name="credentials",
                            secret=V1SecretVolumeSource(
                                secret_name=f"credentials-{self.reconciliation.key.provisioner_name}",
                            ),
                        ),
                        V1Volume(
                            name="workdir",
                            empty_dir=V1EmptyDirVolumeSource(size_limit="10Mi"),
                        ),
                        self.scripts_volume(),
                    ],
                    restart_policy="Never",
                    service_account_name="external-resources-sa",
                ),
            ),
        )

    def scripts(self) -> dict[str, str]:
        return {"input.json": self.reconciliation.input}


class K8sExternalResourcesReconciler(ExternalResourcesReconciler):
    def __init__(
        self, controller: K8sJobController, dry_run: bool, dry_run_job_suffix: str = ""
    ) -> None:
        self.controller = controller
        self.dry_run = dry_run
        self.dry_run_job_suffix = dry_run_job_suffix

    def get_resource_reconcile_status(
        self,
        reconciliation: Reconciliation,
    ) -> ReconcileStatus:
        job_name = ReconciliationK8sJob(reconciliation=reconciliation).name()
        return ReconcileStatus(self.controller.get_job_status(job_name))

    def get_resource_reconcile_duration(
        self, reconciliation: Reconciliation
    ) -> int | None:
        job_name = ReconciliationK8sJob(reconciliation=reconciliation).name()
        return self.controller.get_success_job_duration(job_name)

    def reconcile_resource(self, reconciliation: Reconciliation) -> None:
        concurrency_policy = (
            JobConcurrencyPolicy.REPLACE_FAILED | JobConcurrencyPolicy.REPLACE_FINISHED
        )
        if self.dry_run:
            concurrency_policy = (
                JobConcurrencyPolicy.REPLACE_FAILED
                | JobConcurrencyPolicy.REPLACE_FINISHED
                | JobConcurrencyPolicy.REPLACE_IN_PROGRESS
            )

        self.controller.enqueue_job(
            ReconciliationK8sJob(
                reconciliation=reconciliation,
                is_dry_run=self.dry_run,
                dry_run_suffix=self.dry_run_job_suffix,
            ),
            concurrency_policy=concurrency_policy,
        )

    def wait_for_reconcile_list_completion(
        self,
        reconcile_list: Iterable[Reconciliation],
        check_interval_seconds: int,
        timeout_seconds: int,
    ) -> dict[str, ReconcileStatus]:
        job_names = {
            ReconciliationK8sJob(
                reconciliation=r,
                is_dry_run=self.dry_run,
                dry_run_suffix=self.dry_run_job_suffix,
            ).name()
            for r in reconcile_list
        }
        job_status = self.controller.wait_for_job_list_completion(
            job_names=job_names,
            check_interval_seconds=check_interval_seconds,
            timeout_seconds=timeout_seconds,
        )
        return {job: ReconcileStatus(status) for job, status in job_status.items()}

    def get_resource_reconcile_logs(self, reconciliation: Reconciliation) -> None:
        job = ReconciliationK8sJob(
            reconciliation=reconciliation,
            is_dry_run=True,
            dry_run_suffix=self.dry_run_job_suffix,
        )
        self.controller.get_job_logs(job_name=job.name(), output=sys.stdout)

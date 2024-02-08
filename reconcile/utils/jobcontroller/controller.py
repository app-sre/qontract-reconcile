import logging
import time
from typing import Optional, TextIO, TypeVar

from kubernetes.client import ApiClient, V1Job  # type: ignore[attr-defined]

from reconcile.typed_queries.clusters_minimal import get_clusters_minimal
from reconcile.utils.jobcontroller.models import (
    JobConcurrencyPolicy,
    JobStatus,
    JobValidationError,
    K8sJob,
)
from reconcile.utils.oc import OCCli
from reconcile.utils.oc_map import init_oc_map_from_clusters
from reconcile.utils.openshift_resource import OpenshiftResource
from reconcile.utils.secret_reader import SecretReaderBase


def build_job_controller(
    integration: str,
    integration_version: str,
    cluster: str,
    namespace: str,
    secret_reader: SecretReaderBase,
    dry_run: bool,
) -> "K8sJobController":
    clusters = get_clusters_minimal(name=cluster)
    oc_map = init_oc_map_from_clusters(
        clusters=clusters,
        secret_reader=secret_reader,
        integration=integration,
        thread_pool_size=1,
        init_api_resources=False,
    )
    oc = oc_map.get_cluster(cluster=cluster)
    return K8sJobController(
        oc=oc,
        cluster=cluster,
        namespace=namespace,
        integration=integration,
        integration_version=integration_version,
        dry_run=dry_run,
    )


JobType = TypeVar("JobType", bound=K8sJob)


class K8sJobController:
    def __init__(
        self,
        oc: OCCli,
        cluster: str,
        namespace: str,
        integration: str,
        integration_version: str,
        dry_run: bool = False,
    ) -> None:
        self.cluster = cluster
        self.namespace = namespace
        self.integration = integration
        self.integration_version = integration_version
        self.oc = oc
        self.dry_run = dry_run
        self._cache: Optional[dict[str, OpenshiftResource]] = None

    @property
    def cache(self) -> dict[str, OpenshiftResource]:
        if not self._cache:
            return self.update_cache()
        return self._cache

    def update_cache(self) -> dict[str, OpenshiftResource]:
        new_cache = {}
        for item in self.oc.get_items(
            kind="Job",
            namespace=self.namespace,
        ):
            openshift_resource = OpenshiftResource(
                body=item,
                integration=self.integration,
                integration_version=self.integration_version,
            )
            new_cache[openshift_resource.name] = openshift_resource
        self._cache = new_cache
        return self._cache

    def get_job_status(self, job_name: str) -> JobStatus:
        job_resource = self.cache.get(job_name)

        if job_resource is None:
            return JobStatus.NOT_EXISTS

        status = job_resource.body["status"]
        backofflimit = job_resource.body["spec"].get("backoffLimit", 6)
        if status.get("succeeded", 0) > 0:
            return JobStatus.SUCCESS
        elif status.get("failed", 0) >= backofflimit:
            return JobStatus.ERROR
        return JobStatus.IN_PROGRESS

    def wait_for_job_list_completion(
        self, jobs: set[JobType], check_interval_seconds: int, timeout_seconds: int
    ) -> list[tuple[JobType, JobStatus]]:
        """
        Waits for all jobs in the list to complete, and returns a dictionary.
        * if a job from the list does not exist, it will have the status NOT_EXISTS set in the result.
        * if a job did not finish within the timeout boundaries, it will have the status
          IN_PROGRESS set in the result.
        """
        jobs_left = {j.name() for j in jobs}
        job_statuses: dict[str, tuple[JobType, JobStatus]] = {
            job.name(): (job, JobStatus.NOT_EXISTS) for job in jobs
        }

        start_time = time.time()
        while jobs_left:
            self.update_cache()
            for job_name in jobs_left:
                status = self.get_job_status(job_name)
                job_statuses[job_name] = (job_statuses[job_name][0], status)
                if status in {JobStatus.SUCCESS, JobStatus.ERROR}:
                    jobs_left.remove(job_name)
            if jobs_left:
                if timeout_seconds >= 0 and time.time() - start_time > timeout_seconds:
                    logging.warning(
                        f"Timeout waiting for jobs to complete: {jobs_left}"
                    )
                    break
                logging.info(
                    f"Waiting for {jobs_left} to complete. Rechecking in {check_interval_seconds} seconds"
                )
                time.sleep(check_interval_seconds)
        return list(job_statuses.values())

    def enqueue_job_and_wait_for_completion(
        self,
        job: K8sJob,
        check_interval_seconds: int,
        timeout_seconds: int,
        concurrency_policy: JobConcurrencyPolicy,
    ) -> JobStatus:
        self.enqueue_job(job, concurrency_policy)
        success = self.wait_for_job_completion(
            job.name(), check_interval_seconds, timeout_seconds
        )
        return JobStatus.SUCCESS if success else JobStatus.ERROR

    def enqueue_job(
        self,
        job: K8sJob,
        concurrency_policy: JobConcurrencyPolicy,
    ) -> bool:
        job_name = job.name()
        job_status = self.get_job_status(job_name)

        cancel_existing_job = False
        create_job = False
        match job_status:
            case JobStatus.IN_PROGRESS:
                if concurrency_policy & JobConcurrencyPolicy.REPLACE_IN_PROGRESS:
                    cancel_existing_job = True
                    create_job = True
            case JobStatus.ERROR:
                if concurrency_policy & JobConcurrencyPolicy.REPLACE_FAILED:
                    cancel_existing_job = True
                    create_job = True
            case JobStatus.SUCCESS:
                if concurrency_policy & JobConcurrencyPolicy.REPLACE_FINISHED:
                    cancel_existing_job = True
                    create_job = True
            case JobStatus.NOT_EXISTS:
                create_job = True

        if cancel_existing_job:
            self.delete_job(job.name())
        if create_job:
            self.create_job(job)
            return True
        return False

    def create_job(self, job: K8sJob) -> None:
        job_spec = job.build_job()
        self.validate_job(job_spec)
        api = ApiClient()
        res = OpenshiftResource(
            api.sanitize_for_serialization(job.build_job()),
            self.integration,
            self.integration_version,
        )
        self.oc.apply(self.namespace, res.annotate())

    def validate_job(self, job: V1Job) -> None:
        if not job.spec:
            raise JobValidationError("Job spec is missing")
        if not job.spec.ttl_seconds_after_finished:
            raise JobValidationError("Job spec is missing ttlSecondsAfterFinished")

    def delete_job(self, job_name: str) -> None:
        job_status = self.get_job_status(job_name)
        if job_status != JobStatus.NOT_EXISTS:
            self.oc.delete(self.namespace, "Job", job_name)

    def wait_for_job_completion(
        self, job_name: str, check_interval_seconds: int, timeout_seconds: int
    ) -> bool:
        start_time = time.time()
        while True:
            self.update_cache()
            status = self.get_job_status(job_name)
            match status:
                case JobStatus.SUCCESS:
                    return True
                case JobStatus.ERROR:
                    return False
            if time.time() - start_time > timeout_seconds:
                raise TimeoutError(f"Timeout waiting for job {job_name} to complete")
            time.sleep(check_interval_seconds)

    def get_job_logs(self, job: K8sJob, output: TextIO) -> None:
        self.oc.job_logs(
            namespace=self.namespace,
            follow=False,
            name=job.name(),
            output=output,
        )

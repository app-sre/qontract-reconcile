import logging
import time
from typing import Optional, Protocol

from kubernetes.client import (  # type: ignore[attr-defined]
    ApiClient,
    V1Job,
    V1ObjectMeta,
    V1OwnerReference,
    V1Secret,
)

from reconcile.typed_queries.clusters_minimal import get_clusters_minimal
from reconcile.utils.jobcontroller.models import (
    JOB_GENERATION_ANNOTATION,
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
    """
    Builds a job controller that will act on the given cluster and namespace.
    The integration name and integration_version are used to annotate the jobs
    created by the controller so there is a way to identify the source for them.

    The cluster parameter is the name of a cluster defined in app-interface. The namespace
    is expected to exist in the cluster.

    If dry_run is set to True, the controller will not perform any changes to the cluster.
    """
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


class TimeProtocol(Protocol):
    def time(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class K8sJobController:
    def __init__(
        self,
        oc: OCCli,
        cluster: str,
        namespace: str,
        integration: str,
        integration_version: str,
        dry_run: bool = False,
        time_module: TimeProtocol = time,
    ) -> None:
        self.cluster = cluster
        self.namespace = namespace
        self.integration = integration
        self.integration_version = integration_version
        self.oc = oc
        self.dry_run = dry_run
        self.time_module = time_module
        self._cache: Optional[dict[str, OpenshiftResource]] = None

    @property
    def cache(self) -> dict[str, OpenshiftResource]:
        if self._cache is None:
            return self.update_cache()
        return self._cache

    def update_cache(self) -> dict[str, OpenshiftResource]:
        """
        Updates the cache with the latest jobs in the namespace.
        """
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

    def get_job_generation(self, job_name: str) -> Optional[str]:
        """
        Returns the generation annotation for a job.
        """
        job_resource = self.cache.get(job_name)
        if job_resource is None:
            return None
        return (
            job_resource.body.get("metadata", {})
            .get("annotations", {})
            .get(JOB_GENERATION_ANNOTATION)
        )

    def get_job_status(self, job_name: str) -> JobStatus:
        """
        Looks up the status for a job. It expects the cache to be up to date, so
        the caller of this function should consider calling update_cache before
        calling this function.
        """
        job_resource = self.cache.get(job_name)

        if job_resource is None:
            return JobStatus.NOT_EXISTS

        status = job_resource.body.get("status") or {}
        backofflimit = job_resource.body["spec"].get("backoffLimit", 6)
        if status.get("succeeded", 0) > 0:
            return JobStatus.SUCCESS
        elif status.get("failed", 0) > backofflimit:
            return JobStatus.ERROR
        return JobStatus.IN_PROGRESS

    def wait_for_job_list_completion(
        self, job_names: set[str], check_interval_seconds: int, timeout_seconds: int
    ) -> dict[str, JobStatus]:
        """
        Waits for all jobs in the list to complete, and returns their statuses.
        * if a job from the list does not exist, it will have the status NOT_EXISTS set in the result.
        * if a job did not finish within the timeout boundaries, it will have the status
          IN_PROGRESS set in the result
        * failed and successful jobs report SUCCESS or ERROR respectively

        The check_interval_seconds parameter is the time to wait between checks for job completion.
        The timeout_seconds parameter is the maximum time to wait for all jobs to complete. If set to -1,
        the function will wait indefinitely.  If a timeout occures, a TimeoutError will be raised.
        """
        jobs_left = job_names.copy()
        job_statuses: dict[str, JobStatus] = {
            name: JobStatus.NOT_EXISTS for name in job_names
        }

        start_time = self.time_module.time()
        while jobs_left:
            self.update_cache()
            for job_name in list(jobs_left):
                status = self.get_job_status(job_name)
                job_statuses[job_name] = status
                if status in {JobStatus.SUCCESS, JobStatus.ERROR}:
                    jobs_left.remove(job_name)
            if jobs_left:
                elapsed_time = self.time_module.time() - start_time
                if timeout_seconds >= 0 and elapsed_time >= timeout_seconds:
                    logging.warning(
                        f"Timeout waiting for jobs to complete: {jobs_left}"
                    )
                    break
                logging.info(
                    f"Waiting for {jobs_left} to complete. Rechecking in {check_interval_seconds} seconds"
                )
                self._sleep_until_timeout(
                    elapsed_time, timeout_seconds, check_interval_seconds
                )
        return job_statuses

    def enqueue_job_and_wait_for_completion(
        self,
        job: K8sJob,
        check_interval_seconds: int,
        timeout_seconds: int,
        concurrency_policy: JobConcurrencyPolicy = JobConcurrencyPolicy.NO_REPLACE,
    ) -> JobStatus:
        """
        Schedules a job and waits for it to complete.
        * For the concurrency_policy, see documentation on the enqueue_job function
        * For check_interval_seconds and timeout_seconds, see documentation on the wait_for_job_completion function
        """
        self.enqueue_job(job, concurrency_policy)
        success = self.wait_for_job_completion(
            job.name(), check_interval_seconds, timeout_seconds
        )
        return JobStatus.SUCCESS if success else JobStatus.ERROR

    def enqueue_job(
        self,
        job: K8sJob,
        concurrency_policy: JobConcurrencyPolicy = JobConcurrencyPolicy.NO_REPLACE,
    ) -> bool:
        """
        Schedules a job on a cluster.

        In general a new job will not be scheduled if one with the same name already exists. This behaviour can
        be influenced by the concurrency_policy parameter. The following flags are available:

        * REPLACE_FAILED: if a job with the same name exists and it has failed, it will be replaced
        * REPLACE_IN_PROGRESS: if a job with the same name exists and it is in progress, it will be replaced
        * REPLACE_FINISHED: if a job with the same name exists and it has finished, it will be replaced

        True is returned when the job was scheduled or replaced an existing job, False otherwise.
        """
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

    def _lookup_job_uid(self, job_name: str) -> Optional[str]:
        job_resource = self.oc.get(
            self.namespace, "Job", job_name, allow_not_found=True
        )
        if not job_resource:
            return None
        return job_resource.get("metadata", {}).get("uid")

    def build_secret(self, job: K8sJob) -> Optional[V1Secret]:
        secret_data = job.secret_data()
        script_data = job.scripts()
        # fail if both dicts have overlapping keys
        if not set(secret_data).isdisjoint(script_data):
            raise JobValidationError(
                f"Secret data and script data have overlapping keys for {job.name()}"
            )
        data = {**secret_data, **script_data}
        if not data:
            return None

        job_name = job.name()
        job_uid = self._lookup_job_uid(job_name)
        if not job_uid:
            raise Exception(f"Failed to lookup job uid for {job_name}")
        return V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=V1ObjectMeta(
                name=job_name,
                annotations=job.annotations(),
                labels=job.labels(),
                owner_references=[
                    V1OwnerReference(
                        api_version="batch/v1",
                        kind="Job",
                        name=job_name,
                        uid=job_uid,
                    )
                ],
            ),
            string_data=data,
        )

    def create_job(self, job: K8sJob) -> None:
        """
        Creates the K8S job on the cluster and namespace.
        """
        job_spec = job.build_job()
        self.validate_job(job_spec)
        api = ApiClient()
        self.oc.apply(
            namespace=self.namespace,
            resource=OpenshiftResource(
                api.sanitize_for_serialization(job.build_job()),
                self.integration,
                self.integration_version,
            ).annotate(),
        )

        # if the job defines secret data, we need to create the secret
        # with proper owner reference
        job_secret = self.build_secret(job)
        if job_secret:
            self.oc.apply(
                namespace=self.namespace,
                resource=OpenshiftResource(
                    api.sanitize_for_serialization(job_secret),
                    self.integration,
                    self.integration_version,
                ).annotate(),
            )

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
        """
        Waits for a job to complete. Returns True if the job was successful, False otherwise.

        The check_interval_seconds parameter is the time to wait between checks for job completion.
        The timeout_seconds parameter is the maximum time to wait for all jobs to complete. If set to -1,
        the function will wait indefinitely. If a timeout occures, a TimeoutError will be raised.
        """
        start_time = self.time_module.time()
        while True:
            self.update_cache()
            status = self.get_job_status(job_name)
            match status:
                case JobStatus.SUCCESS:
                    return True
                case JobStatus.ERROR:
                    return False
            elapsed_time = self.time_module.time() - start_time
            if timeout_seconds >= 0 and elapsed_time >= timeout_seconds:
                raise TimeoutError(f"Timeout waiting for job {job_name} to complete")
            self._sleep_until_timeout(
                elapsed_time, timeout_seconds, check_interval_seconds
            )

    def _sleep_until_timeout(
        self,
        elapsed_time: float,
        timeout_seconds: float,
        default_sleep_interval_seconds: float,
    ) -> None:
        sleep_interval_seconds = default_sleep_interval_seconds
        if timeout_seconds >= 0:
            sleep_interval_seconds = min(
                default_sleep_interval_seconds, timeout_seconds - elapsed_time
            )
        if sleep_interval_seconds > 0:
            self.time_module.sleep(sleep_interval_seconds)

    def store_job_logs(self, job_name: str, output_dir_path: str) -> str:
        """
        Stores the logs of a job in the given output directory.
        The filename will be the name of the job.
        """
        return self.oc.job_logs_latest_pod(
            namespace=self.namespace,
            name=job_name,
            output=output_dir_path,
        )

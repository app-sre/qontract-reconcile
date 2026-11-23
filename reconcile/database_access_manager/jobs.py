from __future__ import annotations

import re
from typing import Any

from kubernetes.client import (
    V1Container,
    V1EnvVar,
    V1EnvVarSource,
    V1JobSpec,
    V1LocalObjectReference,
    V1ObjectMeta,
    V1PodSpec,
    V1PodTemplateSpec,
    V1ResourceRequirements,
    V1SecretKeySelector,
)
from pydantic import BaseModel, Field
from sretoolbox.container.image import Image

from reconcile.utils.jobcontroller.models import K8sJob
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "database-access-manager"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

JOB_DEADLINE_IN_SECONDS = 900
# the job-bound secret holds the database credential until DAM settles
# it into Vault. If reconciliation is paused for longer than this TTL
# after the SQL succeeds, the credential is lost and the password that
# was set can no longer be published. 24h gives ample time for a
# reconciliation pause without keeping finished jobs indefinitely.
JOB_TTL_SECONDS_AFTER_FINISHED = 86400


class DatabaseConnectionParameters(
    BaseModel, validate_by_name=True, validate_by_alias=True
):
    host: str = Field(..., alias="db.host")
    port: str = Field(..., alias="db.port")
    user: str = Field(..., alias="db.user")
    password: str = Field(..., alias="db.password")
    database: str = Field(..., alias="db.name")


def _sanitize_job_prefix(name: str) -> str:
    """Make the prefix of a job name DNS-1123 compliant."""
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")


class DatabaseAccessJob(K8sJob, BaseModel, frozen=True):
    """A psql job that applies a rendered database access script.

    The job connects with the admin credentials from the (pre-existing)
    RDS admin secret in the namespace. The rendered script and the user
    connection data live in a job-bound secret managed by the job
    controller. The user password is passed to psql as a variable and
    is never part of the job spec.
    """

    state_key: str
    job_image: str
    script: str
    admin_secret_name: str
    user_connection: DatabaseConnectionParameters
    pull_secret_name: str | None = None

    def name_prefix(self) -> str:
        return _sanitize_job_prefix(f"dbam-{self.state_key.replace('/', '-')}")

    def unit_of_work_identity(self) -> Any:
        # the identity is the state key only, so at most one job per
        # entry exists at any time: enqueuing a job for a changed
        # configuration replaces the previous job for the entry
        return self.state_key

    def labels(self) -> dict[str, str]:
        return {"app": "qontract-reconcile", "integration": QONTRACT_INTEGRATION}

    def secret_data(self) -> dict[str, str]:
        return self.user_connection.model_dump(by_alias=True)

    def scripts(self) -> dict[str, str]:
        return {"script.sql": self.script}

    def _secret_env(
        self, name: str, key: str, secret_name: str | None = None
    ) -> V1EnvVar:
        return V1EnvVar(
            name=name,
            value_from=V1EnvVarSource(
                secret_key_ref=V1SecretKeySelector(
                    name=secret_name or self.admin_secret_name, key=key
                )
            ),
        )

    def job_spec(self) -> V1JobSpec:
        image_tag = Image(self.job_image).tag
        image_pull_policy = "Always" if image_tag == "latest" else "IfNotPresent"

        env = [
            self._secret_env("db.host", "db.host"),
            self._secret_env("db.port", "db.port"),
            self._secret_env("db.user", "db.user"),
            self._secret_env("db.name", "db.name"),
            self._secret_env("PGPASSWORD", "db.password"),
            # the user password from the job-bound secret, passed to
            # psql as a variable -- the expansion happens in Kubernetes
            self._secret_env(
                "db_user_password", "db.password", secret_name=self.name()
            ),
        ]

        container = V1Container(
            name="dbam",
            image=self.job_image,
            image_pull_policy=image_pull_policy,
            command=["/usr/bin/psql"],
            args=[
                # no --echo-errors here: it would echo failed statements
                # including the interpolated password to the job logs
                "--host=$(db.host)",
                "--port=$(db.port)",
                "--username=$(db.user)",
                "--dbname=$(db.name)",
                "-v",
                "db_user_password=$(db_user_password)",
                "--file=/scripts/script.sql",
            ],
            env=env,
            resources=V1ResourceRequirements(
                requests={"cpu": "100m", "memory": "512Mi"},
                limits={"memory": "512Mi"},
            ),
            volume_mounts=[self.scripts_volume_mount("/scripts")],
        )

        return V1JobSpec(
            backoff_limit=1,
            active_deadline_seconds=JOB_DEADLINE_IN_SECONDS,
            ttl_seconds_after_finished=JOB_TTL_SECONDS_AFTER_FINISHED,
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(labels=self.labels()),
                spec=V1PodSpec(
                    automount_service_account_token=False,
                    restart_policy="Never",
                    image_pull_secrets=(
                        [V1LocalObjectReference(name=self.pull_secret_name)]
                        if self.pull_secret_name
                        else None
                    ),
                    containers=[container],
                    volumes=[self.scripts_volume()],
                ),
            ),
        )

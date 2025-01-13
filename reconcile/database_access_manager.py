import base64
import logging
from collections.abc import Callable
from random import choices
from string import (
    ascii_letters,
    digits,
)
from typing import (
    Any,
    TypedDict,
    cast,
)

from pydantic import BaseModel

from reconcile import openshift_base, queries
from reconcile import openshift_resources_base as orb
from reconcile.gql_definitions.terraform_resources.database_access_manager import (
    DatabaseAccessV1,
    NamespaceTerraformProviderResourceAWSV1,
    NamespaceTerraformResourceRDSV1,
    NamespaceV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.oc import (
    OC_Map,
    OCClient,
)
from reconcile.utils.openshift_resource import (
    OpenshiftResource,
    base64_encode_secret_field_value,
)
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.state import (
    State,
    init_state,
)
from reconcile.utils.vault import (
    VaultClient,
    _VaultClient,
)

QONTRACT_INTEGRATION = "database-access-manager"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

SUPPORTED_ENGINES = ["postgres"]

JOB_DEADLINE_IN_SECONDS = 60
JOB_PSQL_ENGINE_VERSION = "15.4-alpine"


def get_database_access_namespaces(
    query_func: Callable | None = None,
) -> list[NamespaceV1]:
    if not query_func:
        query_func = gql.get_api().query
    return query(query_func).namespaces_v1 or []


class DatabaseConnectionParameters(BaseModel):
    host: str
    port: str
    user: str
    password: str
    database: str


class PSQLScriptGenerator(BaseModel):
    db_access: DatabaseAccessV1
    current_db_access: DatabaseAccessV1 | None
    connection_parameter: DatabaseConnectionParameters
    admin_connection_parameter: DatabaseConnectionParameters
    engine: str

    def _get_db(self) -> str:
        return self.db_access.database

    def _get_user(self) -> str:
        return self.db_access.username

    def _get_admin_user(self) -> str:
        return self.admin_connection_parameter.user

    def _generate_create_user(self) -> str:
        return f"""
\\set ON_ERROR_STOP on

SELECT 'CREATE DATABASE "{self._get_db()}"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '{self._get_db()}');\\gexec
/* revoke only required for databases lower version 15
   this makes the behaviour compliant with postgres 15, writes are only allowed
   in the schema created for the role/user */
REVOKE ALL ON DATABASE "{self._get_db()}" FROM public;

\\c "{self._get_db()}"

select 'CREATE ROLE "{self._get_user()}"'
WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{self._get_user()}');\\gexec

ALTER ROLE "{self._get_user()}" WITH LOGIN  PASSWORD '{self.connection_parameter.password}' VALID UNTIL 'infinity';

GRANT CONNECT ON DATABASE "{self._get_db()}" to "{self._get_user()}";

-- rds specific, grant role to admin or create schema fails
GRANT "{self._get_user()}" to "{self._get_admin_user()}";
CREATE SCHEMA IF NOT EXISTS "{self._get_user()}" AUTHORIZATION "{self._get_user()}";"""

    def _generate_delete_user(self) -> str:
        return f"""
\\set ON_ERROR_STOP on
\\c "{self._get_db()}"
REASSIGN OWNED BY "{self._get_user()}" TO "{self._get_admin_user()}";
DROP ROLE IF EXISTS "{self._get_user()}";\\gexec"""

    def _generate_revoke_db_access(self) -> str:
        statements = [
            f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA "{access.target.dbschema}" FROM "{self._get_user()}";'
            for access in self.db_access.access or []
        ]
        return "\n".join(statements)

    def _generate_db_access(self) -> str:
        statements = [
            f'GRANT {",".join(access.grants)} ON ALL TABLES IN SCHEMA "{access.target.dbschema}" TO "{self._get_user()}";'
            for access in self.db_access.access or []
        ]
        return "\n".join(statements)

    def _generate_revoke_changed(self) -> str:
        if not self.current_db_access:
            return ""
        statements: list[str] = []
        current_grants = {
            x.target.dbschema: x.grants for x in self.current_db_access.access or []
        }
        desired_grants = {
            x.target.dbschema: x.grants for x in self.db_access.access or []
        }

        for schema, grants in current_grants.items():
            if schema not in desired_grants:
                statements.append(
                    f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA "{schema}" FROM "{self._get_user()}";'
                )
            else:
                statements.extend(
                    f'REVOKE {grant} ON ALL TABLES IN SCHEMA "{schema}" FROM "{self._get_user()}";'
                    for grant in set(grants) - set(desired_grants[schema])
                )
        return "".join(statements)

    def _provision_script(self) -> str:
        return (
            self._generate_create_user()
            + "\n"
            + self._generate_revoke_changed()
            + "\n"
            + self._generate_db_access()
        )

    def _deprovision_script(self) -> str:
        return self._generate_revoke_db_access() + "\n" + self._generate_delete_user()

    def generate_script(self) -> str:
        if self.db_access.delete:
            return self._deprovision_script()
        return self._provision_script()


def secret_head(name: str) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {
            "name": name,
        },
    }


def generate_user_secret_spec(
    name: str, db_connection: DatabaseConnectionParameters
) -> OpenshiftResource:
    secret = secret_head(name)
    secret["data"] = {
        "db.host": base64_encode_secret_field_value(db_connection.host),
        "db.name": base64_encode_secret_field_value(db_connection.database),
        "db.password": base64_encode_secret_field_value(db_connection.password),
        "db.port": base64_encode_secret_field_value(db_connection.port),
        "db.user": base64_encode_secret_field_value(db_connection.user),
    }
    return OpenshiftResource(
        body=secret,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
    )


def generate_script_secret_spec(name: str, script: str) -> OpenshiftResource:
    secret = secret_head(name)
    secret["data"] = {
        "script.sql": base64.b64encode(script.encode("utf-8")).decode("utf-8"),
    }
    return OpenshiftResource(
        body=secret,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
    )


def get_db_engine(resource: NamespaceTerraformResourceRDSV1) -> str:
    defaults = gql.get_resource(resource.defaults)
    engine = "postgres"
    for line in defaults["content"].split("\n"):
        if line and line.startswith("engine:"):
            engine = line.split(":")[1].strip()
    if engine not in SUPPORTED_ENGINES:
        raise Exception(f"Unsupported engine: {engine}")
    return engine


class JobData(BaseModel):
    engine: str
    engine_version: str
    name_suffix: str
    image_repository: str
    service_account_name: str
    rds_admin_secret_name: str
    script_secret_name: str
    pull_secret: str


def get_job_spec(job_data: JobData) -> OpenshiftResource:
    job_name = f"dbam-{job_data.name_suffix}"

    if job_data.engine == "postgres":
        command = "/usr/local/bin/psql"

    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "labels": {
                "app": "qontract-reconcile",
                "integration": QONTRACT_INTEGRATION,
            },
            "annotations": {
                "ignore-check.kube-linter.io/unset-cpu-requirements": "no cpu limits",
            },
        },
        "spec": {
            "backoffLimit": 1,
            "template": {
                "metadata": {
                    "name": job_name,
                },
                "spec": {
                    "activeDeadlineSeconds": JOB_DEADLINE_IN_SECONDS,
                    "imagePullSecrets": [{"name": job_data.pull_secret}],
                    "restartPolicy": "Never",
                    "serviceAccountName": job_data.service_account_name,
                    "containers": [
                        {
                            "name": job_name,
                            "image": f"{job_data.image_repository}/{job_data.engine}:{job_data.engine_version}",
                            "command": [
                                command,
                            ],
                            "args": [
                                "-b",
                                "--host=$(db.host)",
                                "--port=$(db.port)",
                                "--username=$(db.user)",
                                "--dbname=$(db.name)",
                                "--file=/tmp/scripts/script.sql",
                            ],
                            "env": [
                                {
                                    "name": "db.host",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": job_data.rds_admin_secret_name,
                                            "key": "db.host",
                                        },
                                    },
                                },
                                {
                                    "name": "db.name",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": job_data.rds_admin_secret_name,
                                            "key": "db.name",
                                        },
                                    },
                                },
                                {
                                    "name": "PGPASSWORD",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": job_data.rds_admin_secret_name,
                                            "key": "db.password",
                                        },
                                    },
                                },
                                {
                                    "name": "db.port",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": job_data.rds_admin_secret_name,
                                            "key": "db.port",
                                        },
                                    },
                                },
                                {
                                    "name": "db.user",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": job_data.rds_admin_secret_name,
                                            "key": "db.user",
                                        },
                                    },
                                },
                            ],
                            "resources": {
                                "requests": {
                                    "cpu": "100m",
                                    "memory": "128Mi",
                                },
                                "limits": {
                                    "memory": "256Mi",
                                },
                            },
                            "volumeMounts": [
                                {
                                    "name": "configs",
                                    "mountPath": "/tmp/scripts/",
                                    "readOnly": True,
                                },
                            ],
                        },
                    ],
                    "volumes": [
                        {
                            "name": "configs",
                            "projected": {
                                "sources": [
                                    {
                                        "secret": {
                                            "name": job_data.script_secret_name,
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            },
        },
    }
    return OpenshiftResource(
        body=job,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
    )


def get_service_account_spec(name: str) -> OpenshiftResource:
    return OpenshiftResource(
        body={
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {
                "name": name,
                "labels": {
                    "app": "qontract-reconcile",
                    "integration": QONTRACT_INTEGRATION,
                },
            },
            "automountServiceAccountToken": False,
        },
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
    )


class DBAMResource(BaseModel):
    resource: OpenshiftResource
    clean_up: bool

    class Config:
        arbitrary_types_allowed = True


class JobStatusCondition(BaseModel):
    type: str


class JobStatus(BaseModel):
    conditions: list[JobStatusCondition]

    def is_complete(self) -> bool:
        return bool(self.conditions)

    def has_errors(self) -> bool:
        return any(condition.type == "Failed" for condition in self.conditions)


def _populate_resources(
    db_access: DatabaseAccessV1,
    engine: str,
    image_repository: str,
    pull_secret: dict[Any, Any],
    admin_secret_name: str,
    resource_prefix: str,
    settings: dict[Any, Any],
    user_connection: DatabaseConnectionParameters,
    admin_connection: DatabaseConnectionParameters,
    current_db_access: DatabaseAccessV1 | None = None,
) -> list[DBAMResource]:
    if user_connection.database == admin_connection.database:
        raise ValueError(f"Can not use default database {admin_connection.database}")

    managed_resources: list[DBAMResource] = []
    # create service account
    managed_resources.append(
        DBAMResource(
            resource=get_service_account_spec(resource_prefix),
            clean_up=True,
        )
    )

    # create script secret
    generator = PSQLScriptGenerator(
        db_access=db_access,
        current_db_access=current_db_access,
        connection_parameter=user_connection,
        admin_connection_parameter=admin_connection,
        engine=engine,
    )
    script_secret_name = f"{resource_prefix}-script"
    managed_resources.extend([
        DBAMResource(
            resource=generate_script_secret_spec(
                script_secret_name,
                generator.generate_script(),
            ),
            clean_up=True,
        ),
        # create user secret
        DBAMResource(
            resource=generate_user_secret_spec(resource_prefix, user_connection),
            clean_up=False,
        ),
    ])
    # create pull secret
    labels = pull_secret["labels"] or {}
    pull_secret_resources = orb.fetch_provider_vault_secret(
        path=pull_secret["path"],
        version=pull_secret["version"],
        name=f"{resource_prefix}-pull-secret",
        labels=labels,
        annotations=pull_secret["annotations"] or {},
        type=pull_secret["type"],
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        settings=settings,
    )
    managed_resources.extend([
        DBAMResource(resource=pull_secret_resources, clean_up=True),
        # create job
        DBAMResource(
            resource=get_job_spec(
                JobData(
                    engine=engine,
                    engine_version=JOB_PSQL_ENGINE_VERSION,
                    name_suffix=db_access.name,
                    image_repository=image_repository,
                    service_account_name=resource_prefix,
                    rds_admin_secret_name=admin_secret_name,
                    script_secret_name=script_secret_name,
                    pull_secret=f"{resource_prefix}-pull-secret",
                )
            ),
            clean_up=True,
        ),
    ])

    return managed_resources


def _generate_password() -> str:
    return "".join(choices(ascii_letters + digits, k=32))


class _DBDonnections(TypedDict):
    user: DatabaseConnectionParameters
    admin: DatabaseConnectionParameters


def _create_database_connection_parameter(
    db_access: DatabaseAccessV1,
    namespace_name: str,
    oc: OCClient,
    admin_secret_name: str,
    user_secret_name: str,
) -> _DBDonnections:
    def _decode_secret_value(value: str) -> str:
        return base64.b64decode(value).decode("utf-8")

    user_secret = oc.get(
        namespace_name,
        "Secret",
        user_secret_name,
        allow_not_found=True,
    )
    admin_secret = oc.get(
        namespace_name,
        "Secret",
        admin_secret_name,
        allow_not_found=False,
    )

    if user_secret:
        password = _decode_secret_value(user_secret["data"]["db.password"])
        host = _decode_secret_value(user_secret["data"]["db.host"])
        user = _decode_secret_value(user_secret["data"]["db.user"])
        port = _decode_secret_value(user_secret["data"]["db.port"])
        database = _decode_secret_value(user_secret["data"]["db.name"])
    else:
        host = _decode_secret_value(admin_secret["data"]["db.host"])
        port = _decode_secret_value(admin_secret["data"]["db.port"])
        user = db_access.username
        password = _generate_password()
        database = db_access.database
    return _DBDonnections(
        user=DatabaseConnectionParameters(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
        ),
        admin=DatabaseConnectionParameters(
            host=_decode_secret_value(admin_secret["data"]["db.host"]),
            port=_decode_secret_value(admin_secret["data"]["db.port"]),
            user=_decode_secret_value(admin_secret["data"]["db.user"]),
            password=_decode_secret_value(admin_secret["data"]["db.password"]),
            database=_decode_secret_value(admin_secret["data"]["db.name"]),
        ),
    )


def _db_access_acccess_is_valid(db_acces: DatabaseAccessV1) -> bool:
    found_schema: set[str] = set()

    for schema in db_acces.access or []:
        if schema.target.dbschema in found_schema:
            return False
        found_schema.add(schema.target.dbschema)

    return True


class JobFailedError(Exception):
    pass


def _process_db_access(
    dry_run: bool,
    state: State,
    db_access: DatabaseAccessV1,
    namespace: NamespaceV1,
    admin_secret_name: str,
    engine: str,
    settings: dict[Any, Any],
    vault_output_path: str,
    vault_client: _VaultClient,
) -> None:
    if not _db_access_acccess_is_valid(db_access):
        raise ValueError("Duplicate schema in access list.")

    current_db_access: DatabaseAccessV1 | None = None
    if state.exists(db_access.name):
        current_state = state.get(db_access.name)
        if current_state == db_access.dict(by_alias=True):
            return
        current_db_access = DatabaseAccessV1(**current_state)
        if current_db_access.database != db_access.database:
            raise ValueError("Database name cannot be changed.")
        if current_db_access.username != db_access.username:
            raise ValueError("Username cannot be changed.")

    cluster_name = namespace.cluster.name
    namespace_name = namespace.name

    resource_prefix = f"dbam-{db_access.name}"
    with OC_Map(
        clusters=[namespace.cluster.dict(by_alias=True)],
        integration=QONTRACT_INTEGRATION,
        settings=settings,
    ) as oc_map:
        oc = oc_map.get_cluster(cluster_name, False)

        connections = _create_database_connection_parameter(
            db_access,
            namespace_name,
            oc,
            admin_secret_name,
            resource_prefix,
        )

        sql_query_settings = settings.get("sqlQuery")
        if not sql_query_settings:
            raise KeyError("sqlQuery settings are required")

        managed_resources = _populate_resources(
            db_access,
            engine,
            sql_query_settings["imageRepository"],
            sql_query_settings["pullSecret"],
            admin_secret_name,
            resource_prefix,
            settings,
            connections["user"],
            connections["admin"],
            current_db_access=current_db_access,
        )

        # create job, delete old, failed job first
        job = oc.get(
            namespace_name,
            "Job",
            f"dbam-{db_access.name}",
            allow_not_found=True,
        )
        if not job:
            for r in managed_resources:
                openshift_base.apply(
                    dry_run=dry_run,
                    oc_map=oc_map,
                    cluster=cluster_name,
                    namespace=namespace_name,
                    resource_type=r.resource.kind,
                    resource=r.resource,
                    wait_for_namespace=False,
                )
            return
        job_status = JobStatus(
            conditions=[
                JobStatusCondition(type=c["type"])
                for c in job["status"].get("conditions", [])
            ]
        )
        if job_status.is_complete():
            if job_status.has_errors():
                raise JobFailedError(
                    f"Job dbam-{db_access.name} failed, please check logs"
                )
            if not dry_run and not db_access.delete:
                secret = {
                    "path": f"{vault_output_path}/{QONTRACT_INTEGRATION}/{cluster_name}/{namespace_name}/{db_access.name}",
                    "data": connections["user"].dict(by_alias=True),
                }
                vault_client.write(secret, decode_base64=False)
            logging.debug("job completed, cleaning up")
            for r in managed_resources:
                if r.clean_up:
                    openshift_base.delete(
                        dry_run=dry_run,
                        oc_map=oc_map,
                        cluster=cluster_name,
                        namespace=namespace_name,
                        resource_type=r.resource.kind,
                        name=r.resource.name,
                        enable_deletion=True,
                    )
            state.add(
                db_access.name,
                value=db_access.dict(by_alias=True),
                force=True,
            )
        else:
            logging.info(f"Job dbam-{db_access.name} appears to be still running")


class DBAMIntegrationParams(PydanticRunParams):
    vault_output_path: str


class DatabaseAccessManagerIntegration(QontractReconcileIntegration):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        settings = queries.get_app_interface_settings()
        vault_client = cast(_VaultClient, VaultClient())

        state = init_state(
            integration=QONTRACT_INTEGRATION, secret_reader=self.secret_reader
        )

        encounteredErrors: list[Exception] = []

        namespaces = get_database_access_namespaces()
        for namespace in namespaces:
            for external_resource in [
                er
                for er in namespace.external_resources or []
                if isinstance(er, NamespaceTerraformProviderResourceAWSV1)
            ]:
                for resource in [
                    r
                    for r in external_resource.resources or []
                    if isinstance(r, NamespaceTerraformResourceRDSV1)
                    and r.database_access is not None
                ]:
                    if resource.output_resource_name is None:
                        admin_secret_name = f"{resource.identifier}-{resource.provider}"
                    else:
                        admin_secret_name = resource.output_resource_name

                    for db_access in resource.database_access or []:
                        try:
                            _process_db_access(
                                dry_run,
                                state,
                                db_access,
                                namespace,
                                admin_secret_name,
                                get_db_engine(resource),
                                settings,
                                self.params.vault_output_path,
                                vault_client,
                            )
                        except (JobFailedError, ValueError) as e:
                            encounteredErrors.append(e)

            if encounteredErrors:
                for err in encounteredErrors:
                    logging.error(err)
                raise JobFailedError("One or more jobs failed to complete")

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from pathlib import Path
from random import choices
from string import (
    ascii_letters,
    digits,
)
from typing import (
    TYPE_CHECKING,
)

from reconcile import openshift_base
from reconcile import openshift_resources_base as orb
from reconcile.database_access_manager.jobs import (
    QONTRACT_INTEGRATION,
    QONTRACT_INTEGRATION_VERSION,
    DatabaseAccessJob,
    DatabaseConnectionParameters,
)
from reconcile.gql_definitions.terraform_resources.database_access_manager import (
    DatabaseAccessV1,
    NamespaceTerraformProviderResourceAWSV1,
    NamespaceTerraformResourceRDSV1,
    NamespaceV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.jobcontroller.models import (
    JobConcurrencyPolicy,
    JobStatus,
)
from reconcile.utils.oc import OC_Map
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import SecretNotFoundError
from reconcile.utils.state import (
    State,
    init_state,
)
from reconcile.utils.vault import (
    VaultClient,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from reconcile.utils.oc import OCClient
    from reconcile.utils.secret_reader import SecretReaderBase

SUPPORTED_ENGINES = ["postgres"]

SQL_DIR = Path(__file__).parent / "sql"

MAX_USERNAME_LENGTH = 63

PULL_SECRET_NAME = "dbam-pull-secret"

# suffix for the state key that tracks the configuration of an
# enqueued job whose result has not been settled yet. If a job
# disappears (TTL expiry) before its result was observed, this marker
# is the only record of what it was going to apply.
PENDING_KEY_SUFFIX = "#pending"


def get_database_access_namespaces(
    query_func: Callable | None = None,
) -> list[NamespaceV1]:
    if not query_func:
        query_func = gql.get_api().query
    return query(query_func).namespaces_v1 or []


def get_db_engine(resource: NamespaceTerraformResourceRDSV1) -> str:
    defaults = gql.get_resource(resource.defaults)
    engine = "postgres"
    for line in defaults["content"].split("\n"):
        if line and line.startswith("engine:"):
            engine = line.split(":")[1].strip()
    if engine not in SUPPORTED_ENGINES:
        raise ValueError(f"Unsupported engine: {engine}")
    return engine


class JobFailedError(Exception):
    pass


def _sql_ident(value: str) -> str:
    """Escape a value for use as a quoted identifier."""
    return value.replace('"', '""')


def _sql_literal(value: str) -> str:
    """Escape a value for use as a single quoted string literal."""
    return value.replace("'", "''")


def _render_sql(template_name: str, **params: str) -> str:
    """Render a SQL template from reconcile/database_access_manager/sql.

    All values must be escaped by the caller (identifiers via
    _sql_ident, literals via _sql_literal). The user password is never
    rendered, it is passed to psql as a variable.
    """
    template = (SQL_DIR / template_name).read_text()
    return template.format(**params)


def _generate_password() -> str:
    return "".join(choices(ascii_letters + digits, k=32))


def _generated_username(role: str, state_key: str) -> str:
    """Deterministic username for role mode entries without an explicit
    username. Stable per entry, different for every new entry, which is
    the phase 1 rotation mechanism."""
    digest = hashlib.sha256(state_key.encode()).hexdigest()[:8]
    return f"{role[: MAX_USERNAME_LENGTH - len(digest) - 1]}_{digest}"


def _access_list(db_access: DatabaseAccessV1) -> str:
    return ";".join(
        f"{access.target.dbschema}|{','.join(access.grants)}"
        for access in db_access.access or []
    )


def _schemas_csv(db_access: DatabaseAccessV1) -> str:
    return ",".join(
        dict.fromkeys(access.target.dbschema for access in db_access.access or [])
    )


def _revoke_list(
    current: DatabaseAccessV1 | None,
    desired: DatabaseAccessV1,
    revoke_all: bool = False,
    stale_configs: list[DatabaseAccessV1] | None = None,
) -> str:
    """Compute the grants that must be revoked to converge from the
    current to the desired access list. Moving away from ALL requires
    a full revoke, otherwise privileges would linger. With revoke_all
    (a stale or expired job applied an unknown or superseded
    configuration), everything on all schemas that any of the known
    configurations managed is revoked before the desired grants."""
    if revoke_all:
        schemas = {access.target.dbschema for access in desired.access or []}
        for config in [
            *([current] if current else []),
            *(stale_configs or []),
        ]:
            schemas.update(access.target.dbschema for access in config.access or [])
        return ";".join(f"{schema}|ALL" for schema in sorted(schemas))
    if not current:
        return ""
    entries: list[str] = []
    current_grants = {x.target.dbschema: x.grants for x in current.access or []}
    desired_grants = {x.target.dbschema: x.grants for x in desired.access or []}

    for schema, grants in current_grants.items():
        desired_schema_grants = desired_grants.get(schema)
        if desired_schema_grants is None or (
            "ALL" in grants and "ALL" not in desired_schema_grants
        ):
            entries.append(f"{schema}|ALL")
        elif "ALL" not in grants and "ALL" not in desired_schema_grants:
            entries.extend(
                f"{schema}|{grant}"
                for grant in set(grants) - set(desired_schema_grants)
            )
    return ";".join(entries)


def _validate_db_access(db_access: DatabaseAccessV1) -> None:
    schemas = [access.target.dbschema for access in db_access.access or []]
    if len(set(schemas)) != len(schemas):
        raise ValueError("Duplicate schema in access list.")

    if db_access.role:
        if db_access.username == db_access.role:
            # the deprovision path would otherwise remove the shared
            # owner role and break every rotation login depending on it
            raise ValueError("Username must differ from the owner role.")
        # role mode: the access list may be empty, DAM manages the
        # username
        return

    if not db_access.username:
        raise ValueError("Username is required when no role is set.")


def _normalized_access(
    db_access: DatabaseAccessV1,
) -> list[tuple[str, tuple[str, ...]]]:
    return sorted(
        (access.target.dbschema, tuple(sorted(access.grants)))
        for access in db_access.access or []
    )


def _merge_pending_config(
    pending: DatabaseAccessV1 | None, desired: DatabaseAccessV1
) -> DatabaseAccessV1:
    """Union of the pending and the desired access lists. When a pending
    marker is overwritten for a replacement job, the record of schemas
    that only the previous job managed must survive a failed
    replacement, so a later retry still revokes them."""
    if not pending:
        return desired
    merged = desired.model_copy(deep=True)
    desired_schemas = {a.target.dbschema for a in merged.access or []}
    extra = [
        a for a in pending.access or [] if a.target.dbschema not in desired_schemas
    ]
    if extra:
        merged.access = [*(merged.access or []), *extra]
    return merged


def _resolve_username(db_access: DatabaseAccessV1, state_key: str) -> str:
    if db_access.username:
        return db_access.username
    if db_access.role:
        return _generated_username(db_access.role, state_key)
    raise ValueError("Username is required when no role is set.")


def _validate_role_sharing(
    entries: list[tuple[DatabaseAccessV1, str]],
) -> None:
    """PostgreSQL roles are shared across every database of one RDS
    instance while object grants stay database-local: entries sharing
    a role must agree on the database and the access list, otherwise
    one entry's revocations undo grants another entry still needs.
    Sharing is only allowed within one RDS resource (the rotation
    mechanism); name, username and delete flag may differ.

    Each entry is a (config, resolved username) tuple so that
    generated logins are covered by the collision check too."""
    database_access = [config for config, _ in entries]
    entries_by_role: dict[str, list[DatabaseAccessV1]] = {}
    for db_access in database_access:
        if db_access.role:
            entries_by_role.setdefault(db_access.role, []).append(db_access)

    for role, role_entries in entries_by_role.items():
        reference = role_entries[0]
        for other in role_entries[1:]:
            if other.database != reference.database:
                raise ValueError(
                    f"Role {role} is shared by entries with different databases."
                )
            if _normalized_access(other) != _normalized_access(reference):
                raise ValueError(
                    f"Role {role} is shared by entries with different access lists."
                )

    # a schema must be managed by at most one owner role per RDS
    # resource: two entries with different roles targeting the same
    # schema would transfer ownership away from each other on every
    # reconciliation, leaving the first role without access
    schemas_by_role: dict[str, set[str]] = {}
    for db_access in database_access:
        if db_access.role:
            schemas = {a.target.dbschema for a in db_access.access or []}
            schemas_by_role.setdefault(db_access.role, set()).update(schemas)

    all_schemas: dict[str, str] = {}  # schema -> role that manages it
    for role, schemas in schemas_by_role.items():
        for schema in schemas:
            if schema in all_schemas and all_schemas[schema] != role:
                raise ValueError(
                    f"Schema {schema} is managed by both role "
                    f"{all_schemas[schema]} and role {role}: a schema "
                    "can only be managed by one owner role."
                )
            all_schemas[schema] = role

    # a login username (explicit or generated) must never collide with
    # an owner role configured for another entry on the same instance:
    # provisioning that entry would grant LOGIN and a password to the
    # owner role, and deprovisioning it would reassign and drop the
    # shared owner role
    roles = {db_access.role for db_access in database_access if db_access.role}
    for _, username in entries:
        if username in roles:
            raise ValueError(
                f"Username {username} equals a role of another entry on this instance."
            )


def _configuration_digest(db_access: DatabaseAccessV1) -> str:
    """Stable digest of the desired configuration. Rendered into every
    script and used to identify which configuration a job applied --
    the rendered SQL itself is not stable (the revoke delta changes
    after the desired state has been applied)."""
    payload = json.dumps(db_access.model_dump(by_alias=True), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _script_configuration_digest(script: str) -> str | None:
    match = re.search(r"^-- dam-configuration: ([0-9a-f]+)$", script, re.MULTILINE)
    return match.group(1) if match else None


def _decode_secret_value(value: str) -> str:
    return base64.b64decode(value).decode("utf-8")


def _connection_from_data(data: dict[str, str]) -> DatabaseConnectionParameters:
    return DatabaseConnectionParameters(
        host=data["db.host"],
        port=data["db.port"],
        user=data["db.user"],
        password=data["db.password"],
        database=data["db.name"],
    )


def _admin_connection(
    oc: OCClient, namespace_name: str, admin_secret_name: str
) -> DatabaseConnectionParameters:
    admin_secret = oc.get(
        namespace_name,
        "Secret",
        admin_secret_name,
        allow_not_found=False,
    )
    return _connection_from_data({
        k: _decode_secret_value(v) for k, v in admin_secret["data"].items()
    })


def _read_job_secret(
    oc: OCClient, namespace_name: str, job_name: str
) -> dict[str, str] | None:
    """Read the job-bound secret of a job: the user connection data and
    the script it was created with."""
    secret = oc.get(namespace_name, "Secret", job_name, allow_not_found=True)
    if not secret:
        return None
    return {k: _decode_secret_value(v) for k, v in secret["data"].items()}


def _job_connection(
    job_secret: dict[str, str],
) -> DatabaseConnectionParameters:
    return _connection_from_data(job_secret)


def _write_vault_secret(
    vault_client: VaultClient,
    vault_output_path: str,
    state_key: str,
    user_connection: DatabaseConnectionParameters,
) -> None:
    vault_client.write(
        {
            "path": f"{vault_output_path}/{QONTRACT_INTEGRATION}/{state_key}",
            "data": user_connection.model_dump(by_alias=True),
        },
        decode_base64=False,
    )


def _vault_connection(
    secret_reader: SecretReaderBase, vault_output_path: str, state_key: str
) -> DatabaseConnectionParameters | None:
    """Read the user connection from vault. Existing role mode users
    keep their password this way, it is never regenerated."""
    path = f"{vault_output_path}/{QONTRACT_INTEGRATION}/{state_key}"
    try:
        data = secret_reader.read_all({"path": path})
    except SecretNotFoundError:
        return None
    if not data:
        return None
    return _connection_from_data(data)


def _build_script(
    db_access: DatabaseAccessV1,
    current_db_access: DatabaseAccessV1 | None,
    username: str,
    admin_user: str,
    revoke_all: bool = False,
    stale_configs: list[DatabaseAccessV1] | None = None,
) -> str:
    # the configuration digest in the header identifies which
    # configuration a job applied; the rendered SQL itself is not
    # stable (the revoke delta changes once the desired state is
    # applied)
    header = f"-- dam-configuration: {_configuration_digest(db_access)}\n"
    # values that end up inside single quoted SQL literals must be
    # literal-escaped, everything inside double quotes identifier-
    # escaped
    literals = {
        "username_literal": _sql_literal(username),
        "username_ident_literal": _sql_literal(_sql_ident(username)),
        "database_literal": _sql_literal(db_access.database),
        "role_literal": _sql_literal(db_access.role or ""),
    }
    if db_access.delete:
        if db_access.role:
            return header + _render_sql(
                "role_deprovision.sql",
                database=_sql_ident(db_access.database),
                username=_sql_ident(username),
                admin_user=_sql_ident(admin_user),
                **literals,
            )
        return header + _render_sql(
            "legacy_deprovision.sql",
            database=_sql_ident(db_access.database),
            username=_sql_ident(username),
            admin_user=_sql_ident(admin_user),
            access_list=_sql_literal(_access_list(db_access)),
            **literals,
        )

    if db_access.role:
        return header + _render_sql(
            "role_provision.sql",
            database=_sql_ident(db_access.database),
            username=_sql_ident(username),
            admin_user=_sql_ident(admin_user),
            role=_sql_ident(db_access.role),
            schemas_csv=_sql_literal(_schemas_csv(db_access)),
            access_list=_sql_literal(_access_list(db_access)),
            revoke_list=_sql_literal(
                _revoke_list(current_db_access, db_access, revoke_all, stale_configs)
            ),
            **literals,
        )

    return header + _render_sql(
        "legacy_provision.sql",
        database=_sql_ident(db_access.database),
        username=_sql_ident(username),
        admin_user=_sql_ident(admin_user),
        access_list=_sql_literal(_access_list(db_access)),
        revoke_list=_sql_literal(
            _revoke_list(current_db_access, db_access, revoke_all, stale_configs)
        ),
        **literals,
    )


def _job_name(
    state_key: str, job_image: str, admin_secret_name: str, pull_secret_name: str | None
) -> str:
    """The job name only depends on the unit of work (the state key),
    so a probe job with a dummy connection yields the real job name."""
    probe = DatabaseAccessJob(
        state_key=state_key,
        job_image=job_image,
        script="",
        admin_secret_name=admin_secret_name,
        user_connection=DatabaseConnectionParameters(
            host="probe", port="probe", user="probe", password="probe", database="probe"
        ),
        pull_secret_name=pull_secret_name,
    )
    return probe.name()


def _ensure_pull_secret(
    dry_run: bool,
    oc_map: OC_Map,
    cluster_name: str,
    namespace_name: str,
    secret_reader: SecretReaderBase,
    vault_output_path: str,
    pull_secret_path: str | None,
    pull_secret_version: str | None,
) -> str | None:
    if not pull_secret_path:
        return None
    resource = orb.fetch_provider_vault_secret(
        path=pull_secret_path,
        version=pull_secret_version or "",
        name=PULL_SECRET_NAME,
        labels={},
        annotations={},
        # the secret is used as an image pull secret: the kubelet only
        # considers secrets of this type with a .dockerconfigjson key
        type="kubernetes.io/dockerconfigjson",
        integration=QONTRACT_INTEGRATION,
        integration_version=str(QONTRACT_INTEGRATION_VERSION),
        secret_reader=secret_reader,
    )
    openshift_base.apply(
        dry_run=dry_run,
        oc_map=oc_map,
        cluster=cluster_name,
        namespace=namespace_name,
        resource_type="Secret",
        resource=resource,
        wait_for_namespace=False,
    )
    return PULL_SECRET_NAME


def _process_db_access(
    dry_run: bool,
    state: State,
    state_key: str,
    db_access: DatabaseAccessV1,
    namespace: NamespaceV1,
    admin_secret_name: str,
    engine: str,
    secret_reader: SecretReaderBase,
    vault_output_path: str,
    vault_client: VaultClient,
    job_image: str,
    pull_secret_path: str | None,
    pull_secret_version: str | None,
) -> None:
    _validate_db_access(db_access)

    username = _resolve_username(db_access, state_key)

    current_db_access: DatabaseAccessV1 | None = None
    state_matches = False
    if state.exists(state_key):
        current_state = state.get(state_key)
        # states written before the 'role' field existed do not contain the key
        current_state.setdefault("role", None)
        state_matches = current_state == db_access.model_dump(by_alias=True)
        if not state_matches:
            current_db_access = DatabaseAccessV1(**current_state)
            if current_db_access.database != db_access.database:
                raise ValueError("Database name cannot be changed.")
            if (current_db_access.username or None) != (db_access.username or None):
                raise ValueError("Username cannot be changed.")
            # adding a role to an existing entry is the opt-in migration to
            # the owner-role model; once set, the role cannot be changed or
            # removed
            if current_db_access.role and current_db_access.role != db_access.role:
                raise ValueError("Role cannot be changed.")

    cluster_name = namespace.cluster.name
    namespace_name = namespace.name

    with OC_Map(
        clusters=[namespace.cluster.model_dump(by_alias=True)],
        integration=QONTRACT_INTEGRATION,
        secret_reader=secret_reader,
    ) as oc_map:
        oc = oc_map.get_cluster(cluster_name, False)

        pull_secret_name = _ensure_pull_secret(
            dry_run,
            oc_map,
            cluster_name,
            namespace_name,
            secret_reader,
            vault_output_path,
            pull_secret_path,
            pull_secret_version,
        )
        admin_connection = _admin_connection(oc, namespace_name, admin_secret_name)

        if not db_access.role and db_access.database == admin_connection.database:
            raise ValueError(
                f"Can not use default database {admin_connection.database}"
            )

        controller = K8sJobController(
            oc=oc,
            cluster=cluster_name,
            namespace=namespace_name,
            integration=QONTRACT_INTEGRATION,
            integration_version=str(QONTRACT_INTEGRATION_VERSION),
            dry_run=dry_run,
        )

        job_name = _job_name(state_key, job_image, admin_secret_name, pull_secret_name)

        # a pending marker records the configuration of an enqueued job
        # whose result has not been settled yet. If the job disappears
        # (TTL expiry) before its result was observed, the marker is
        # the only record of what it was going to apply.
        pending_key = f"{state_key}{PENDING_KEY_SUFFIX}"
        pending_exists = state.exists(pending_key)
        pending_config: DatabaseAccessV1 | None = None
        if pending_exists:
            pending_config = DatabaseAccessV1(**state.get(pending_key))
            # the database, the resolved username and (once set) the
            # owner role are immutable against the pending marker too:
            # a change would enqueue the replacement job (and its
            # revocations) against different targets. Legacy-to-role
            # migrations (role None -> set) remain allowed.
            if pending_config.database != db_access.database:
                raise ValueError("Database name cannot be changed.")
            if _resolve_username(pending_config, state_key) != username:
                raise ValueError("Username cannot be changed.")
            if pending_config.role and pending_config.role != db_access.role:
                raise ValueError("Role cannot be changed.")

        # settle the job for this entry before treating the state as
        # converged: matching state with an unfinished or stale job
        # would skip work that has not been applied yet
        stale_job = False
        controller.update_cache()
        match controller.get_job_status(job_name):
            case JobStatus.IN_PROGRESS:
                if _read_job_secret(oc, namespace_name, job_name) is None:
                    # incomplete enqueue: the job was created without its
                    # job-bound secret (e.g. a failed secret write) and
                    # would wait forever -- remove it, the enqueue below
                    # re-creates it with its secret
                    if dry_run:
                        logging.warning(f"would delete incomplete job {job_name}")
                    else:
                        controller.delete_job(job_name)
                        logging.warning(f"deleted incomplete job {job_name}")
                else:
                    logging.info(f"Job {job_name} appears to be still running")
                return
            case JobStatus.ERROR:
                # remove the failed job so the enqueue below can retry,
                # and surface the error for this reconcile
                if dry_run:
                    raise JobFailedError(
                        f"Job {job_name} failed, it would be removed on a real "
                        "run, please check the job logs -- it will be retried "
                        "on the next reconciliation"
                    )
                controller.delete_job(job_name)
                raise JobFailedError(
                    f"Job {job_name} failed and was removed, please check the "
                    "job logs -- it will be retried on the next reconciliation"
                )
            case JobStatus.SUCCESS:
                job_secret = _read_job_secret(oc, namespace_name, job_name)
                if job_secret:
                    job_digest = _script_configuration_digest(
                        job_secret.get("script.sql", "")
                    )
                    if job_digest == _configuration_digest(db_access):
                        # the job ran the current configuration: settle.
                        # always publish the credentials the job used --
                        # a replacement job may have run with a password
                        # that vault does not have yet, even when the
                        # state already matches
                        if not dry_run:
                            if not db_access.delete:
                                _write_vault_secret(
                                    vault_client,
                                    vault_output_path,
                                    state_key,
                                    _job_connection(job_secret),
                                )
                            state.add(
                                state_key,
                                value=db_access.model_dump(by_alias=True),
                                force=True,
                            )
                            # idempotent: a repeated settlement of the
                            # same completed job must not fail
                            if state.exists(pending_key):
                                state.rm(pending_key)
                        if db_access.delete:
                            return
                        # do NOT return for provision entries: fall
                        # through to re-enqueue the (idempotent) job.
                        # This picks up objects created by the old app
                        # during the migration window. The convergence
                        # window lasts as long as the job exists (TTL):
                        # once the job expires, NOT_EXISTS +
                        # state_matches triggers the early return and
                        # the entry is fully converged.
                    # stale job from an older configuration (e.g. the
                    # configuration was reverted while the job was in
                    # flight): replace it below and revoke everything it
                    # may have applied
                    stale_job = True
                elif state_matches and not pending_exists:
                    # the job secret expired (TTL) and the state
                    # converged long ago. With a pending marker the
                    # applied configuration is still unknown: fall
                    # through to the repair below.
                    return
            case JobStatus.NOT_EXISTS:
                if state_matches and not pending_exists:
                    return
                if pending_exists:
                    # a job was enqueued but never observed: it either
                    # expired after succeeding (what it applied is
                    # unknown) or was removed after failing -- re-run
                    # with a full revoke to converge either way
                    stale_job = True

        # an unsettled pending marker means the applied configuration
        # is unknown: revoke everything any known configuration managed
        unknown_applied = stale_job or pending_exists
        script = _build_script(
            db_access,
            current_db_access,
            username,
            admin_connection.user,
            revoke_all=unknown_applied,
            stale_configs=[pending_config] if pending_config else [],
        )

        # role mode keeps the vault password, legacy mode generates a
        # new one on every configuration change
        user_connection = None
        if db_access.role:
            user_connection = _vault_connection(
                secret_reader, vault_output_path, state_key
            )
        if not user_connection:
            user_connection = DatabaseConnectionParameters(
                host=admin_connection.host,
                port=admin_connection.port,
                user=username,
                password=_generate_password(),
                database=db_access.database,
            )

        job = DatabaseAccessJob(
            state_key=state_key,
            job_image=job_image,
            script=script,
            admin_secret_name=admin_secret_name,
            user_connection=user_connection,
            pull_secret_name=pull_secret_name,
        )

        if dry_run:
            logging.info(f"would run job {job.name()} for {state_key}")
            return

        # a replacement job must not start with the previous run's
        # secret data: the controller applies the job before it applies
        # the secret, so a pod could read stale credentials before the
        # new secret is written. Removing the old secret first makes
        # the pod wait for the new one instead.
        if _read_job_secret(oc, namespace_name, job_name) is not None:
            oc.delete(namespace_name, "Secret", job_name)

        # record what this job is going to apply, so a job that
        # disappears before its result is observed can still be
        # reconciled (written before the enqueue: a crash in between
        # only leaves a harmless marker without a job). Schemas that
        # only the previous pending configuration managed are merged
        # in, so a failed replacement cannot lose the revoke baseline.
        state.add(
            pending_key,
            value=_merge_pending_config(pending_config, db_access).model_dump(
                by_alias=True
            ),
            force=True,
        )

        controller.enqueue_job(
            job,
            concurrency_policy=(
                JobConcurrencyPolicy.REPLACE_IN_PROGRESS
                | JobConcurrencyPolicy.REPLACE_FAILED
                | JobConcurrencyPolicy.REPLACE_FINISHED
            ),
        )
        controller.update_cache()
        match controller.get_job_status(job.name()):
            case JobStatus.IN_PROGRESS:
                logging.info(f"Job {job.name()} appears to be still running")
                return
            case JobStatus.ERROR:
                raise JobFailedError(f"Job {job.name()} failed, please check logs")
            case JobStatus.NOT_EXISTS:
                raise JobFailedError(
                    f"Job {job.name()} does not exist after being enqueued"
                )
            case JobStatus.SUCCESS:
                pass

        if not db_access.delete:
            _write_vault_secret(
                vault_client, vault_output_path, state_key, user_connection
            )

        state.add(
            state_key,
            value=db_access.model_dump(by_alias=True),
            force=True,
        )
        if state.exists(pending_key):
            state.rm(pending_key)


class DBAMIntegrationParams(PydanticRunParams):
    vault_output_path: str
    job_image: str
    pull_secret_path: str | None = None
    pull_secret_version: str | None = None


class DatabaseAccessManagerIntegration(QontractReconcileIntegration):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        vault_client = VaultClient.get_instance()

        state = init_state(
            integration=QONTRACT_INTEGRATION, secret_reader=self.secret_reader
        )

        encountered_errors: list[Exception] = []

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

                    # resolve usernames per entry: entries that fail
                    # resolution (no username, no role) are collected
                    # as errors without blocking the valid entries
                    resolved_entries: list[tuple[DatabaseAccessV1, str]] = []
                    for db_access in resource.database_access or []:
                        state_key = f"{external_resource.provisioner.name}/{resource.identifier}/{db_access.name}"
                        try:
                            resolved_entries.append((
                                db_access,
                                _resolve_username(db_access, state_key),
                            ))
                        except ValueError as e:
                            encountered_errors.append(e)

                    try:
                        _validate_role_sharing(resolved_entries)
                    except ValueError as e:
                        encountered_errors.append(e)
                        continue

                    for db_access in [config for config, _ in resolved_entries]:
                        try:
                            state_key = f"{external_resource.provisioner.name}/{resource.identifier}/{db_access.name}"
                            _process_db_access(
                                dry_run,
                                state,
                                state_key,
                                db_access,
                                namespace,
                                admin_secret_name,
                                get_db_engine(resource),
                                self.secret_reader,
                                self.params.vault_output_path,
                                vault_client,
                                self.params.job_image,
                                self.params.pull_secret_path,
                                self.params.pull_secret_version,
                            )
                        except (JobFailedError, ValueError) as e:
                            encountered_errors.append(e)

        if encountered_errors:
            for err in encountered_errors:
                logging.error(err)
            raise JobFailedError("One or more jobs failed to complete")

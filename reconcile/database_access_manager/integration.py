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
    SecretVersionNotFoundError,
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


def _access_schema_sequence(db_access: DatabaseAccessV1) -> list[str]:
    """The schema sequence of the access list in configured order.

    The SQL search path of the shared login is built from this order,
    so unqualified name resolution depends on it: entries sharing an
    owner role must list the schemas in the same sequence."""
    return [access.target.dbschema for access in db_access.access or []]


def _validate_role_sharing(
    entries: list[tuple[DatabaseAccessV1, str]],
) -> None:
    """PostgreSQL roles are shared across every database of one RDS
    instance while object grants stay database-local: entries sharing
    a role must agree on the database and the access list, otherwise
    one entry's revocations undo grants another entry still needs.
    They must also agree on the schema ORDER of the access list: the
    search path of the shared login follows the configured order, so
    divergent orders would resolve unqualified names differently per
    entry. Sharing is only allowed within one RDS resource (the
    rotation mechanism); name, username and delete flag may differ.

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
            if _access_schema_sequence(other) != _access_schema_sequence(reference):
                raise ValueError(
                    f"Role {role} is shared by entries with different access list "
                    "orders: the search path of the shared login depends on the "
                    "order of the schemas, so the entries must list the schemas "
                    "in the same sequence."
                )

    # a resolved login username must be unique within the RDS
    # resource: two entries resolving to the same login would
    # overwrite each other's password or retire a login the other
    # entry still uses. Checked before the schema exclusivity below:
    # two role-mode entries sharing a login also share the schema
    # named after it, and the duplicate login is the root cause of
    # that conflict
    resolved_usernames: dict[str, str] = {}  # username -> entry name
    for config, username in entries:
        if username in resolved_usernames:
            raise ValueError(
                f"Login {username} is used by both entry "
                f"{resolved_usernames[username]} and entry {config.name}: "
                "login usernames must be unique per instance."
            )
        resolved_usernames[username] = config.name

    # a schema must be managed by at most one owner role per RDS
    # resource AND per database: two entries with different roles
    # targeting the same schema would transfer ownership away from
    # each other on every reconciliation, leaving the first role
    # without access. Keying by (database, schema) allows the same
    # schema name in different databases. The managed set of an entry
    # also contains the schema named after its resolved login -- the
    # ownership transfer in role_provision.sql adopts that schema
    # even with an empty access list -- so it participates in the
    # check exactly like an access-list schema.
    schemas_by_role: dict[str, set[tuple[str, str]]] = {}
    for db_access, username in entries:
        if db_access.role:
            schemas = {(db_access.database, username)}
            schemas.update(
                (db_access.database, a.target.dbschema) for a in db_access.access or []
            )
            schemas_by_role.setdefault(db_access.role, set()).update(schemas)

    all_schemas: dict[tuple[str, str], str] = {}  # (db, schema) -> role
    for role, schemas in schemas_by_role.items():
        for db_schema in schemas:
            if db_schema in all_schemas and all_schemas[db_schema] != role:
                db_name, schema_name = db_schema
                raise ValueError(
                    f"Schema {schema_name} in database {db_name} is managed "
                    f"by both role {all_schemas[db_schema]} and role {role}: "
                    "a schema can only be managed by one owner role."
                )
            all_schemas[db_schema] = role

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


def _current_user_connection(
    password: str,
    admin_connection: DatabaseConnectionParameters,
    username: str,
    database: str,
) -> DatabaseConnectionParameters:
    """The user connection for the current configuration: the current
    admin endpoint, the resolved login and the desired database,
    carrying the given password. An existing credential (the vault
    secret of a role-mode entry or the bound secret of a settled job)
    only ever contributes its password -- republishing its recorded
    endpoint, login or database would republish stale values."""
    return DatabaseConnectionParameters(
        host=admin_connection.host,
        port=admin_connection.port,
        user=username,
        password=password,
        database=database,
    )


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
    except SecretNotFoundError, SecretVersionNotFoundError:
        # a missing KV v2 path raises SecretVersionNotFoundError, a
        # missing KV v1 path raises SecretNotFoundError: both mean the
        # credential has not been published yet
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


def _legacy_job_name(state_key: str) -> str:
    """The job name format used before the K8sJob migration: the raw
    state key with slashes replaced, no digest suffix and no DNS-1123
    sanitization (the old code relied on app-interface names being
    compliant). Jobs with this name may still be running during an
    upgrade."""
    return f"dbam-{state_key.replace('/', '-')}"


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
            # compare the RESOLVED usernames: an entry that first omitted
            # the username and later sets it to exactly the generated
            # login does not change the PostgreSQL identity (the pending
            # guard below resolves the same way)
            if _resolve_username(current_db_access, state_key) != username:
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

        # neither the resolved username nor the owner role may be the
        # admin user: the job would ALTER ROLE ... PASSWORD the admin
        # account, and deprovisioning would set it NOLOGIN and DROP
        # OWNED its objects. Generated usernames cannot collide (role
        # prefix plus digest, and the username must differ from the
        # role), but an explicit username or the role itself can equal
        # the admin name
        if username == admin_connection.user:
            raise ValueError(
                f"Username must not equal the admin user {admin_connection.user}."
            )
        if db_access.role == admin_connection.user:
            raise ValueError(
                f"Role must not equal the admin user {admin_connection.user}."
            )

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
        legacy_job_name = _legacy_job_name(state_key)

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
        convergence_password: str | None = None
        controller.update_cache()
        # check for a legacy-format job (pre-K8sJob naming) that may
        # still be running during an upgrade: it would race with a
        # new-format job for the same login
        legacy_status = controller.get_job_status(legacy_job_name)
        if legacy_status == JobStatus.IN_PROGRESS:
            logging.warning(
                f"legacy-format job {legacy_job_name} is still running, "
                "waiting for it to complete before scheduling a replacement"
            )
            return
        if legacy_status != JobStatus.NOT_EXISTS:
            # a settled legacy-format job (SUCCESS or ERROR): it is
            # finished and cannot race with a new-format job, but the
            # old code had no TTL cleanup -- remove it so it does not
            # linger forever
            if dry_run:
                logging.warning(f"would delete legacy-format job {legacy_job_name}")
            else:
                controller.delete_job(legacy_job_name)
                logging.warning(f"deleted legacy-format job {legacy_job_name}")
        if legacy_status == JobStatus.ERROR:
            raise JobFailedError(
                f"legacy-format job {legacy_job_name} failed, it was removed. "
                "It will be replaced with the new naming on the next reconciliation."
            )
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
                        # The confirmed application supersedes the
                        # pending marker -- what was applied is known,
                        # so the re-enqueued job below must not revoke
                        # everything. This also covers dry-run, where
                        # the marker is not physically removed.
                        pending_exists = False
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
                                    _current_user_connection(
                                        _job_connection(job_secret).password,
                                        admin_connection,
                                        username,
                                        db_access.database,
                                    ),
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
                        #
                        # Legacy entries do NOT re-enqueue: they have
                        # no ownership transfer to converge (the user
                        # owns their own schema), and the re-enqueue
                        # would either rotate the password (legacy
                        # generates a fresh one) or run forever (each
                        # replacement gets a fresh TTL).
                        if not db_access.role:
                            return
                        #
                        # Reuse the settled job's password for the
                        # re-enqueue: generating a fresh one here
                        # would change the database password on every
                        # reconcile, breaking the credential that vault
                        # just published.
                        convergence_password = _job_connection(job_secret).password
                    else:
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

        # only the password is taken from an existing credential (the
        # vault secret of a role-mode entry or the bound secret of a
        # settled job): the endpoint, the login and the database are
        # rebuilt from the current configuration, so a stale admin
        # endpoint, an old login or a superseded database recorded in
        # an old credential is never republished. Role mode keeps the
        # vault password, legacy mode generates a new one on every
        # configuration change.
        password = convergence_password
        if not password and db_access.role:
            if vault_connection := _vault_connection(
                secret_reader, vault_output_path, state_key
            ):
                password = vault_connection.password
        if not password:
            password = _generate_password()
        user_connection = _current_user_connection(
            password, admin_connection, username, db_access.database
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
                    and r.database_access
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
                                dry_run=dry_run,
                                state=state,
                                state_key=state_key,
                                db_access=db_access,
                                namespace=namespace,
                                admin_secret_name=admin_secret_name,
                                engine=get_db_engine(resource),
                                secret_reader=self.secret_reader,
                                vault_output_path=self.params.vault_output_path,
                                vault_client=vault_client,
                                job_image=self.params.job_image,
                                pull_secret_path=self.params.pull_secret_path,
                                pull_secret_version=self.params.pull_secret_version,
                            )
                        except (JobFailedError, ValueError) as e:
                            encountered_errors.append(e)

        if encountered_errors:
            for err in encountered_errors:
                logging.error(err)
            raise JobFailedError("One or more jobs failed to complete")

"""Shared fixtures and helpers for database-access-manager tests.

Provides:

- real PostgreSQL containers (docker or podman) with the full object
  zoo for testing the SQL templates end to end
- SQL rendering helpers shared by the E2E modules
- a job-flow harness that runs ``_process_db_access`` against a real
  container with the OpenShift/Vault/state infrastructure mocked
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
)
from unittest.mock import MagicMock

import pytest

from reconcile.database_access_manager.integration import (
    _build_script,
    _legacy_job_name,
    _process_db_access,
    _render_sql,
    _resolve_username,
)
from reconcile.database_access_manager.jobs import (
    DatabaseAccessJob,
    DatabaseConnectionParameters,
)
from reconcile.gql_definitions.terraform_resources.database_access_manager import (
    DatabaseAccessAccessGranteeV1,
    DatabaseAccessAccessV1,
    DatabaseAccessV1,
    NamespaceV1,
)
from reconcile.utils.jobcontroller.models import JobStatus
from reconcile.utils.state import State

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping

    from pytest_mock import MockerFixture


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "e2e: end-to-end tests requiring docker or podman"
    )


# ─── shared constants ─────────────────────────────────────────────────────

# all supported PostgreSQL versions
PG_VERSIONS = ["13", "14", "15", "16", "17", "18"]

# the executor role simulating the RDS master user
EXECUTOR = "test_admin"

DB_PASSWORD = "TestPw123"  # notsecret

# identifiers for the job-flow harness
E2E_STATE_KEY = "e2e-provisioner/e2e-rds/e2e-entry"
E2E_ADMIN_SECRET_NAME = "e2e-admin-secret"
E2E_JOB_IMAGE = "quay.io/app-sre/yet-another-debug-container:latest"


# ─── container engine detection ──────────────────────────────────────────


def _engine_daemon_ready(engine: str) -> bool:
    """Whether the engine's daemon responds to a bounded status probe."""
    try:
        result = subprocess.run(
            [engine, "info"],
            capture_output=True,
            check=False,
            timeout=15,
        )
    except subprocess.TimeoutExpired, OSError:
        return False
    return result.returncode == 0


def _detect_container_engine() -> str | None:
    """Return the first installed engine with a responsive daemon.

    A binary on PATH is not enough: with docker installed but its
    daemon unreachable, the fixture must fall through to podman
    instead of failing on the first engine found.
    """
    for engine in ("docker", "podman"):
        if shutil.which(engine) and _engine_daemon_ready(engine):
            return engine
    return None


def _container_ready(container: str, engine: str) -> bool:
    result = subprocess.run(
        [engine, "exec", container, "pg_isready", "-U", "postgres", "-h", "127.0.0.1"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _run(
    engine: str, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [engine, *args],
        capture_output=True,
        text=True,
        check=check,
    )


# ─── seed data: the full PostgreSQL object zoo ───────────────────────────

SEED_SQL = """
\\set ON_ERROR_STOP on

GRANT CREATE ON SCHEMA public TO {executor};
SET ROLE {executor};

-- tables (regular, partitioned with partitions, unlogged)
CREATE TABLE public.orders (
    id serial PRIMARY KEY,
    customer_id int NOT NULL,
    total numeric(10,2),
    status text DEFAULT 'pending',
    created_at timestamptz DEFAULT now()
);
CREATE TABLE public.order_items (
    id serial PRIMARY KEY,
    order_id int REFERENCES public.orders(id),
    product text NOT NULL,
    qty int DEFAULT 1
);
CREATE TABLE public.events (
    id bigint,
    payload text,
    created_at timestamptz DEFAULT now()
) PARTITION BY RANGE (created_at);
CREATE TABLE public.events_2026_01 PARTITION OF public.events
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE public.events_2026_02 PARTITION OF public.events
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE public.audit_log (
    id serial,
    action text
);

-- indexes (btree, partial, expression, GIN)
CREATE INDEX idx_orders_customer ON public.orders (customer_id);
CREATE INDEX idx_orders_pending ON public.orders (created_at) WHERE status = 'pending';
CREATE INDEX idx_orders_lower ON public.orders (lower(status));
CREATE INDEX idx_order_items_gin ON public.order_items USING gin (to_tsvector('english', product));

-- sequences (explicit + identity columns)
CREATE SEQUENCE public.custom_seq START 100 INCREMENT 5;
CREATE TABLE public.with_identity (
    id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    data text
);

-- views (regular, materialized)
CREATE VIEW public.v_open_orders AS
    SELECT id, customer_id, total FROM public.orders WHERE status = 'pending';
CREATE MATERIALIZED VIEW public.mv_order_totals AS
    SELECT customer_id, sum(total) AS total FROM public.orders GROUP BY customer_id;

-- functions (scalar, set-returning, aggregate)
CREATE FUNCTION public.get_order_total(oid int) RETURNS numeric
    AS 'SELECT total FROM public.orders WHERE id = $1' LANGUAGE sql STABLE;
CREATE FUNCTION public.top_customers(n int) RETURNS TABLE(customer_id int, total numeric)
    AS 'SELECT customer_id, sum(total) FROM public.orders GROUP BY customer_id ORDER BY 2 DESC LIMIT $1'
    LANGUAGE sql STABLE;
CREATE FUNCTION public.next_custom_seq() RETURNS bigint
    AS 'SELECT nextval(''public.custom_seq'')' LANGUAGE sql;
CREATE AGGREGATE public.max_qty(int) (
    SFUNC = int4larger,
    STYPE = int,
    INITCOND = '0'
);
CREATE PROCEDURE public.reset_pending()
    LANGUAGE plpgsql AS $$BEGIN UPDATE public.orders SET status = 'pending' WHERE status = 'shipped'; END$$;

-- triggers + trigger functions
CREATE FUNCTION public.audit_insert() RETURNS trigger
    LANGUAGE plpgsql AS $$BEGIN INSERT INTO public.audit_log(action) VALUES ('insert_' || TG_TABLE_NAME); RETURN NEW; END$$;
CREATE TRIGGER trg_orders_audit AFTER INSERT ON public.orders
    FOR EACH ROW EXECUTE FUNCTION public.audit_insert();

-- types (enum, composite, domain, range)
CREATE TYPE public.order_status AS ENUM ('pending', 'shipped', 'cancelled');
CREATE TYPE public.address AS (street text, city text, zip text);
CREATE DOMAIN public.positive_int AS int CHECK (VALUE > 0);
CREATE TYPE public.order_range AS RANGE (subtype = timestamptz);
ALTER TABLE public.orders ADD COLUMN status_enum public.order_status DEFAULT 'pending';

-- statistics (extended)
CREATE STATISTICS public.stat_orders_cust_status (dependencies)
    ON customer_id, status FROM public.orders;

-- constraints
ALTER TABLE public.order_items ADD CONSTRAINT chk_qty_positive CHECK (qty > 0);

-- insert test data
INSERT INTO public.orders (customer_id, total, status) VALUES (1, 100.00, 'pending'), (2, 200.00, 'shipped'), (3, 50.00, 'pending');
INSERT INTO public.order_items (order_id, product, qty) VALUES (1, 'widget', 3), (2, 'gadget', 1);

RESET ROLE;
"""


class PostgresContainer:
    """A real PostgreSQL instance in a container (docker or podman)."""

    def __init__(self, engine: str, container_name: str, version: str) -> None:
        self.engine = engine
        self.container_name = container_name
        self.version = version

    def exec_psql(
        self,
        user: str,
        database: str,
        sql: str | None = None,
        *,
        on_error_stop: bool = True,
        extra_args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Execute SQL via psql inside the container."""
        cmd = [self.engine, "exec", "-i"]
        if env:
            for name, value in env.items():
                cmd.extend(("-e", f"{name}={value}"))
        cmd.extend((
            self.container_name,
            "psql",
            "-U",
            user,
            "-h",
            "127.0.0.1",
            "-d",
            database,
        ))
        if on_error_stop:
            cmd.extend(("-v", "ON_ERROR_STOP=1"))
        if extra_args:
            cmd.extend(extra_args)
        if sql is not None:
            cmd.extend(["-f", "-"])
        return subprocess.run(
            cmd,
            input=sql,
            capture_output=True,
            text=True,
            check=False,
        )

    def query(self, user: str, database: str, sql: str) -> str:
        """Run a query and return the trimmed result."""
        result = self.exec_psql(user, database, extra_args=["-At", "-c", sql])
        if result.returncode != 0:
            pytest.fail(f"query failed: {result.stderr}\nSQL: {sql}")
        return result.stdout.strip()

    def seed(self, database: str, executor: str) -> None:
        """Create the full object zoo owned by the executor role."""
        # not .format(): the SQL contains $1 and $$ which format() would
        # interpret as placeholders
        sql = SEED_SQL.replace("{executor}", executor)
        result = self.exec_psql(executor, database, sql)
        if result.returncode != 0:
            pytest.fail(f"seed failed: {result.stderr}")

    def login(
        self, user: str, password: str, database: str, sql: str = "SELECT 1;"
    ) -> subprocess.CompletedProcess[str]:
        """Connect with real password authentication.

        The mounted pg_hba.conf enforces scram-sha-256 for every role
        except the fixture roles (postgres, test_admin).
        """
        return self.exec_psql(user, database, sql, env={"PGPASSWORD": password})

    def start_session(
        self,
        user: str,
        database: str,
        sql: str,
        *,
        password: str | None = None,
        extra_args: list[str] | None = None,
    ) -> subprocess.Popen[str]:
        """Run SQL in a background psql session, return the process.

        The session stays alive while the SQL runs (an open
        transaction holding a lock via BEGIN; LOCK TABLE; pg_sleep,
        or a long-running provision script). stdin stays open, so an
        unfinished transaction keeps its locks until the caller kills
        the process. The caller is responsible for cleanup.
        """
        cmd = [self.engine, "exec", "-i"]
        if password:
            cmd.extend(("-e", f"PGPASSWORD={password}"))
        cmd.extend((
            self.container_name,
            "psql",
            "-U",
            user,
            "-h",
            "127.0.0.1",
            "-d",
            database,
        ))
        if extra_args:
            cmd.extend(extra_args)
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert process.stdin is not None
        process.stdin.write(sql)
        process.stdin.flush()
        return process

    def terminate_sessions(self, user: str) -> None:
        """Terminate every session of user (test cleanup helper)."""
        self.exec_psql(
            "postgres",
            "postgres",
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE usename = '{user}' AND pid <> pg_backend_pid();",
        )


# ─── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def container_engine() -> str:
    engine = _detect_container_engine()
    if engine is None:
        pytest.skip("neither docker nor podman is available")
    return engine


def _container_test_suffix(node_name: str) -> str:
    """A docker-safe container-name fragment for a test node name."""
    # docker container names must be [a-zA-Z0-9][a-zA-Z0-9_.-]*
    # pytest parametrize IDs contain brackets and other special chars
    return "".join(
        c if c.isalnum() or c in "._-" else "-" for c in node_name[:30]
    ).strip("-")


@pytest.fixture(scope="session")
def _pg_hba_conf() -> Generator[Path]:
    """A session-scoped copy of pg_hba.conf for the container mount.

    Mounting the checkout's file directly can fail on
    SELinux-enforcing hosts: podman denies the container access to
    home-labeled files. The copy is mounted with a shared ``:z``
    label, so the engine relabels the temp copy as container-shared.
    The user's checkout is never relabeled (``:Z`` on the original
    would do exactly that).

    The copy is created next to the original (with a unique
    per-session name) instead of the system temp directory: the path
    must be bind-mountable by the container engine, and Docker
    Desktop only shares selected host paths (e.g. /Users) -- files in
    /var/folders or /tmp mount as empty directories there. A unique
    name keeps concurrent pytest runs isolated; the copy is removed
    at the end of the session.

    ``shutil.copyfile`` copies the content only: the copy is created
    with the process umask applied, so under a restrictive umask
    (e.g. 077) it comes out ``0600`` even from a ``0644`` original
    -- and the container's ``postgres`` user then cannot read it (the
    shared ``:z`` label relabels the SELinux context, it does not
    grant read permission), failing every E2E fixture at startup.
    The copy is therefore chmod-ed to ``0644`` before it is mounted;
    the original file's mode is never touched.
    """
    session_copy = Path(__file__).parent / f".pg_hba.conf.{uuid.uuid4().hex[:8]}.copy"
    shutil.copyfile(Path(__file__).parent / "pg_hba.conf", session_copy)
    os.chmod(session_copy, 0o644)
    try:
        yield session_copy
    finally:
        session_copy.unlink(missing_ok=True)


def _start_postgres(
    container_engine: str,
    version: str,
    test_suffix: str,
    hba_conf: Path,
    extra_server_args: list[str] | None = None,
) -> Generator[PostgresContainer]:
    """Start a fresh PostgreSQL container and remove it afterwards.

    Shared by the ``postgres`` fixture and the specialized fixtures
    that need extra server options: same resource identity, same
    authentication policy, same cleanup.
    """
    # a per-instance token gives every fixture instance its own
    # resource identity: two pytest processes (or worktrees) running
    # the same test id on the same container engine would otherwise
    # derive the same container name, and one run's setup would remove
    # the other run's ACTIVE container and its anonymous volume
    instance_token = uuid.uuid4().hex[:8]
    container_name = f"dam-e2e-{version}-{test_suffix}-{instance_token}"

    # deliberately NO pre-start removal of a same-named container: the
    # name is unique per fixture instance, so no stale container of an
    # earlier run can exist under this name, and removing a generically
    # named container here is exactly what deleted other runs' active
    # databases. Tradeoff: containers of hard-crashed runs (SIGKILL,
    # power loss) now linger until manual cleanup
    # (docker rm -f -v dam-e2e-*); cross-run isolation is worth it.
    try:
        # docker run can fail after the container (and its anonymous
        # volume) was already created -- the finally block below still
        # removes it in that case
        _run(
            container_engine,
            "run",
            "-d",
            "--name",
            container_name,
            "-e",
            "POSTGRES_PASSWORD=test",
            "-v",
            f"{hba_conf}:/dam-e2e/pg_hba.conf:ro,z",
            "postgres:" + version,
            # declarative test-container authentication policy (see
            # pg_hba.conf): fixture roles connect via trust, every app
            # login must authenticate. password_encryption covers
            # PostgreSQL 13, which would otherwise store md5 verifiers
            # that scram-sha-256 cannot check.
            "-c",
            "hba_file=/dam-e2e/pg_hba.conf",
            "-c",
            "password_encryption=scram-sha-256",
            *(extra_server_args or []),
        )

        for _ in range(30):
            if _container_ready(container_name, container_engine):
                break
            time.sleep(1)
        else:
            # pytest.fail raises, so the finally block below still
            # removes the container and its volume
            pytest.fail(f"PostgreSQL {version} container did not become ready")

        container = PostgresContainer(container_engine, container_name, version)

        # create the executor role (simulates the RDS master user)
        result = container.exec_psql(
            "postgres",
            "postgres",
            "CREATE ROLE test_admin NOSUPERUSER CREATEDB CREATEROLE LOGIN PASSWORD 'admin_pw';",
        )
        assert result.returncode == 0, f"failed to create executor: {result.stderr}"

        yield container
    finally:
        # remove the container together with its anonymous data volume
        # (rm needs -v for that) no matter whether the test passed,
        # failed, or the setup between docker run and yield raised
        _run(container_engine, "rm", "-f", "-v", container_name, check=False)


@pytest.fixture
def postgres(
    request: pytest.FixtureRequest,
    container_engine: str,
    _pg_hba_conf: Path,
) -> Generator[PostgresContainer]:
    """A fresh PostgreSQL container for each test.

    Parametrize with @pytest.mark.parametrize("postgres", [...]) to
    test specific versions, or use the default 16.
    """
    version = getattr(request, "param", "16")
    yield from _start_postgres(
        container_engine,
        version,
        _container_test_suffix(request.node.name),
        _pg_hba_conf,
    )


@pytest.fixture
def postgres_server_search_path(
    request: pytest.FixtureRequest,
    container_engine: str,
    _pg_hba_conf: Path,
) -> Generator[PostgresContainer]:
    """A fresh PostgreSQL container with an instance-wide search_path.

    The server is started with ``-c search_path=public`` (like an RDS
    parameter group setting the instance default): every session
    without a more specific role or database setting observes
    ``search_path=public`` with source ``command line``. Same
    authentication policy and lifecycle as the ``postgres`` fixture;
    parametrize indirectly for versions.
    """
    version = getattr(request, "param", "16")
    yield from _start_postgres(
        container_engine,
        version,
        _container_test_suffix(request.node.name),
        _pg_hba_conf,
        ["-c", "search_path=public"],
    )


# ─── SQL rendering helpers (shared by the E2E modules) ───────────────────


def _render_provision(
    database: str,
    username: str,
    *,
    role: str | None = None,
    access_list: str = "public|SELECT,INSERT",
    revoke_list: str = "",
    schemas_csv: str = "public",
    admin_user: str = EXECUTOR,
) -> str:
    """Render the appropriate provision template."""
    common = {
        "database": database,
        "database_literal": database,
        "username": username,
        "username_literal": username,
        "username_ident_literal": username,
        "admin_user": admin_user,
    }
    if role:
        return _render_sql(
            "role_provision.sql",
            role=role,
            role_literal=role,
            schemas_csv=schemas_csv,
            access_list=access_list,
            revoke_list=revoke_list,
            **common,
        )
    return _render_sql(
        "legacy_provision.sql",
        access_list=access_list,
        revoke_list=revoke_list,
        **common,
    )


def _render_deprovision(
    database: str,
    username: str,
    *,
    role: bool = False,
    admin_user: str = EXECUTOR,
    access_list: str = "",
) -> str:
    """Render a deprovision template. The access list defaults to
    empty like a settled-state removal; pass a nonempty list to
    exercise the guard position with a revoke block behind it."""
    template = "role_deprovision.sql" if role else "legacy_deprovision.sql"
    return _render_sql(
        template,
        database=database,
        database_literal=database,
        username=username,
        username_literal=username,
        admin_user=admin_user,
        access_list=access_list,
    )


def _create_database(
    pg: PostgresContainer, name: str, *, owner: str = EXECUTOR
) -> None:
    """Create a database owned by the given role."""
    result = pg.exec_psql(
        "postgres", "postgres", f"CREATE DATABASE {name} OWNER {owner};"
    )
    assert result.returncode == 0, f"CREATE DATABASE failed: {result.stderr}"


def _assert_owner(
    pg: PostgresContainer, db: str, obj_type: str, query: str, expected: str
) -> None:
    actual = pg.query(EXECUTOR, db, query)
    assert actual == expected, f"{obj_type}: expected owner {expected}, got {actual}"


def _database_owner(pg: PostgresContainer, db: str) -> str:
    """The owner of a database, queried from the cluster catalog."""
    return pg.query(
        EXECUTOR,
        "postgres",
        f"SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = '{db}'",
    )


def make_db_access(
    *,
    database: str,
    username: str | None = None,
    role: str | None = None,
    access: list[tuple[str, tuple[str, ...]]] | None = None,
    name: str = "e2e",
    delete: bool = False,
) -> DatabaseAccessV1:
    """Build a DatabaseAccessV1 like app-interface delivers it."""
    return DatabaseAccessV1(
        username=username,
        name=name,
        database=database,
        delete=delete,
        role=role,
        access=[
            DatabaseAccessAccessV1(
                grants=list(grants),
                target=DatabaseAccessAccessGranteeV1(dbschema=schema),
            )
            for schema, grants in access or []
        ]
        or None,
    )


def build_script(
    db_access: DatabaseAccessV1,
    current_db_access: DatabaseAccessV1 | None = None,
    *,
    admin_user: str = EXECUTOR,
    state_key: str = E2E_STATE_KEY,
) -> str:
    """Render a script through the production renderer (revoke delta
    included), exactly like _process_db_access does for a real job."""
    return _build_script(
        db_access,
        current_db_access,
        _resolve_username(db_access, state_key),
        admin_user,
    )


# ─── DAM job-flow harness against a real container ───────────────────────


def _b64(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


class FakeDamState(State):
    """In-memory State double: multi-run flows behave like the real
    integration state (settled state and pending markers persist
    across harness.run calls). The real State is S3-backed; only the
    primitives _process_db_access uses are implemented."""

    def __init__(self) -> None:
        # no super().__init__(): the S3 bucket and client of the real
        # State are never touched
        self._data: dict[str, Any] = {}

    def exists(self, key: str) -> bool:
        return key in self._data

    def add(
        self,
        key: str,
        value: Any = None,
        metadata: Mapping[str, str] | None = None,
        force: bool = False,
    ) -> None:
        self._data[key] = value

    def rm(self, key: str) -> None:
        self._data.pop(key, None)

    def get(self, key: str, *args: Any) -> Any:
        return self._data[key]


class DamJobHarness:
    """Runs _process_db_access against a real PostgreSQL container with
    the OpenShift, Vault and state infrastructure mocked.

    Simulated transition: a job runs as soon as DAM polls its status
    after enqueueing (a fast Kubernetes job) -- the enqueued script is
    executed via psql on the container at that point, and the
    job-bound secret the real controller writes is recorded so that
    settlement and configuration-digest checks work like production.
    No production service is involved.
    """

    def __init__(
        self,
        pg: PostgresContainer,
        mocker: MockerFixture,
        namespace: NamespaceV1,
        *,
        admin_user: str = EXECUTOR,
        admin_database: str = "postgres",
    ) -> None:
        self.pg = pg
        self.admin_user = admin_user
        self.admin_database = admin_database
        self.namespace = namespace
        self.state = FakeDamState()
        self.enqueued_jobs: list[DatabaseAccessJob] = []
        self.vault_writes: list[dict[str, Any]] = []
        self.last_job_result: subprocess.CompletedProcess[str] | None = None
        self._job_status: dict[str, JobStatus] = {}
        self._job_secrets: dict[str, dict[str, str]] = {}
        # job names whose execution is held back by hold_job(): polls
        # report IN_PROGRESS for them without running the script
        self._held_jobs: set[str] = set()

        self.vault_client = MagicMock()
        self.vault_client.write.side_effect = self._record_vault_write

        self.secret_reader = MagicMock()
        self.secret_reader.read_all.return_value = {}

        self.controller = MagicMock()
        self.controller.get_job_status.side_effect = self._poll_job_status
        self.controller.enqueue_job.side_effect = self._enqueue
        mocker.patch(
            "reconcile.database_access_manager.integration.K8sJobController",
            return_value=self.controller,
        )

        self.oc = MagicMock()
        self.oc.get.side_effect = self._oc_get
        self.oc.delete.side_effect = self._oc_delete

        oc_map = MagicMock()
        oc_map.get_cluster.return_value = self.oc
        oc_map.__enter__.return_value = oc_map
        mocker.patch(
            "reconcile.database_access_manager.integration.OC_Map", return_value=oc_map
        )

    # ── the mocked infrastructure ────────────────────────────────────

    def _record_vault_write(self, write: dict[str, Any], **_kwargs: Any) -> None:
        self.vault_writes.append(write)

    def _admin_secret(self) -> dict[str, dict[str, str]]:
        return {
            "data": {
                key: _b64(value)
                for key, value in {
                    "db.host": "localhost",
                    "db.port": "5432",
                    "db.user": self.admin_user,
                    "db.password": "adminpw",  # notsecret
                    "db.name": self.admin_database,
                }.items()
            }
        }

    def _oc_get(
        self,
        _namespace: str,
        _kind: str,
        name: str,
        allow_not_found: bool = True,
    ) -> dict[str, Any] | None:
        if name == E2E_ADMIN_SECRET_NAME:
            return self._admin_secret()
        if secret := self._job_secrets.get(name):
            return {"data": {k: _b64(v) for k, v in secret.items()}}
        return None

    def _oc_delete(self, _namespace: str, _kind: str, name: str) -> None:
        self._job_secrets.pop(name, None)

    def _enqueue(self, job: DatabaseAccessJob, **_kwargs: Any) -> None:
        self.enqueued_jobs.append(job)
        # a replacement job has not run yet
        self._job_status.pop(job.name(), None)

    def _poll_job_status(self, job_name: str) -> JobStatus:
        if job_name in self._held_jobs:
            # a held job behaves like a Kubernetes job whose pod has
            # not finished yet: IN_PROGRESS, script not executed. Only
            # hold_job() ever puts a name in here, so without holds the
            # harness behavior is completely unchanged
            return JobStatus.IN_PROGRESS
        if job_name == _legacy_job_name(E2E_STATE_KEY):
            return JobStatus.NOT_EXISTS
        if job_name in self._job_status:
            return self._job_status[job_name]
        if job := next(
            (j for j in reversed(self.enqueued_jobs) if j.name() == job_name), None
        ):
            self.last_job_result = self.pg.exec_psql(
                self.admin_user,
                self.admin_database,
                job.script,
                extra_args=["-v", f"db_user_password={job.user_connection.password}"],
            )
            result = self.last_job_result
            status = (
                JobStatus.SUCCESS
                if result.returncode == 0 and "ERROR" not in result.stderr
                else JobStatus.ERROR
            )
            if status == JobStatus.SUCCESS:
                self._job_secrets[job_name] = {**job.secret_data(), **job.scripts()}
            self._job_status[job_name] = status
            return status
        return JobStatus.NOT_EXISTS

    # ── holding a job's execution (proven-overlap scenarios) ────────

    def hold_job(self, job_name: str) -> None:
        """Hold the execution of a job: status polls report IN_PROGRESS
        without executing the enqueued script, exactly like a
        Kubernetes job whose pod has not finished yet.

        Additive test hook for proven-overlap scenarios: one entry's
        job is held while another entry is reconciled, so the second
        job provably runs while the first is still in progress. The
        job keeps its enqueued script; release_job() lets the next
        status poll execute it.
        """
        self._held_jobs.add(job_name)

    def release_job(self, job_name: str) -> None:
        """Release a held job: the next status poll executes its
        enqueued script again (the normal harness behavior)."""
        self._held_jobs.discard(job_name)

    def job_in_progress(self, job_name: str) -> bool:
        """Whether DAM would currently observe the job as IN_PROGRESS:
        a held job, or one whose recorded status is IN_PROGRESS.
        Side-effect free -- unlike the controller's get_job_status
        double, this never executes anything."""
        return job_name in self._held_jobs or (
            self._job_status.get(job_name) is JobStatus.IN_PROGRESS
        )

    # ── driving the integration ──────────────────────────────────────

    def run(self, db_access: DatabaseAccessV1) -> None:
        """One reconciliation of the entry, including the job run."""
        _process_db_access(
            dry_run=False,
            state=self.state,
            state_key=E2E_STATE_KEY,
            db_access=db_access,
            namespace=self.namespace,
            admin_secret_name=E2E_ADMIN_SECRET_NAME,
            engine="postgres",
            secret_reader=self.secret_reader,
            vault_output_path="vault-out",
            vault_client=self.vault_client,
            job_image=E2E_JOB_IMAGE,
            pull_secret_path=None,
            pull_secret_version=None,
        )

    def published_credentials(self) -> list[DatabaseConnectionParameters]:
        """Every credential DAM published to Vault, in order."""
        return [
            DatabaseConnectionParameters(**write["data"]) for write in self.vault_writes
        ]

    def last_published_credential(self) -> DatabaseConnectionParameters:
        assert self.vault_writes, "DAM published no credential"
        return DatabaseConnectionParameters(**self.vault_writes[-1]["data"])


@pytest.fixture
def dam_harness_factory(
    mocker: MockerFixture,
    gql_class_factory: Callable[..., NamespaceV1],
) -> Callable[..., DamJobHarness]:
    """Factory for the DAM job-flow harness against a real container."""

    def _factory(
        pg: PostgresContainer,
        *,
        admin_user: str = EXECUTOR,
        admin_database: str = "postgres",
    ) -> DamJobHarness:
        namespace = gql_class_factory(
            NamespaceV1,
            {"name": "e2e-ns", "cluster": {"name": "e2e-cluster"}},
        )
        return DamJobHarness(
            pg,
            mocker,
            namespace,
            admin_user=admin_user,
            admin_database=admin_database,
        )

    return _factory

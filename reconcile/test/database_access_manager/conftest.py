"""Shared fixtures for database-access-manager E2E tests.

Provides real PostgreSQL containers (docker or podman) with the full
object zoo for testing the SQL templates end to end.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "e2e: end-to-end tests requiring docker or podman"
    )


# ─── container engine detection ──────────────────────────────────────────


def _detect_container_engine() -> str | None:
    """Return 'docker' or 'podman' if available, None otherwise."""
    for engine in ("docker", "podman"):
        if shutil.which(engine):
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
    ) -> subprocess.CompletedProcess[str]:
        """Execute SQL via psql inside the container."""
        cmd = [
            self.engine,
            "exec",
            "-i",
            self.container_name,
            "psql",
            "-U",
            user,
            "-h",
            "127.0.0.1",
            "-d",
            database,
        ]
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


# ─── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def container_engine() -> str:
    engine = _detect_container_engine()
    if engine is None:
        pytest.skip("neither docker nor podman is available")
    return engine


@pytest.fixture
def postgres(
    request: pytest.FixtureRequest,
    container_engine: str,
) -> Generator[PostgresContainer]:
    """A fresh PostgreSQL container for each test.

    Parametrize with @pytest.mark.parametrize("pg_version", [...]) to
    test specific versions, or use the default 16.
    """
    version = getattr(request, "param", "16")
    # docker container names must be [a-zA-Z0-9][a-zA-Z0-9_.-]*
    # pytest parametrize IDs contain brackets and other special chars
    test_suffix = "".join(
        c if c.isalnum() or c in "._-" else "-" for c in request.node.name[:30]
    ).strip("-")
    container_name = f"dam-e2e-{version}-{test_suffix}"

    _run(container_engine, "rm", "-f", container_name, check=False)
    _run(
        container_engine,
        "run",
        "-d",
        "--name",
        container_name,
        "-e",
        "POSTGRES_PASSWORD=test",
        "postgres:" + version,
    )

    for _ in range(30):
        if _container_ready(container_name, container_engine):
            break
        time.sleep(1)
    else:
        _run(container_engine, "rm", "-f", container_name, check=False)
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

    _run(container_engine, "rm", "-f", container_name, check=False)

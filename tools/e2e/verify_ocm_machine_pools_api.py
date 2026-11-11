#!/usr/bin/env python3
"""E2E + plan-parity verification for the ocm-machine-pools-api integration.

Runs the client-side integration's own compilation code against a real
App-Interface GraphQL server, reconciles the compiled desired state
through the server-side service against real OCM, and - the core check -
compares the resulting dry-run plan against the LEGACY integration's
dry-run plan for the same clusters. Identical plans are the strongest
available proof that a migration preserves reconciliation decisions.

Read-only by default. Mutations (--mutate) only touch throwaway pools
(prefixed "e2e-"), built from live OCM snapshots - real App-Interface
desired state is never applied.

All environment-specific values (GraphQL server, vault path, cluster
names) are CLI arguments - nothing internal is baked in.

Usage:
    export VAULT_ADDR=<vault server>   # vault login done already
    uv run python -m tools.e2e.verify_ocm_machine_pools_api \
        --gql-url <app-interface graphql url> \
        --machine-pool-cluster <osd-or-rosa-classic-cluster> \
        --node-pool-cluster <rosa-hcp-cluster> \
        [--mutate]
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from qontract_api.cache.base import CacheBackend
from qontract_api.config import OcmSettings, Settings
from qontract_api.integrations.ocm_machine_pools.domain import (
    ClusterType,
    DesiredClusterMachinePools,
    DesiredMachinePool,
    DesiredMachinePoolAutoscaling,
    DesiredNodePool,
    DesiredNodePoolAutoscaling,
)
from qontract_api.integrations.ocm_machine_pools.service import OcmMachinePoolsService
from qontract_api.models import TaskStatus
from qontract_api.ocm.ocm_workspace_client import OcmWorkspaceClient
from qontract_utils.ocm_api import OcmApi, OcmNodePoolAws

# imported as a module alias: the verification tool deliberately exercises
# the integration's own compilation path, private helpers included
from reconcile import ocm_machine_pools_api as client_integration
from reconcile.ocm_machine_pools import (
    calculate_diff,
    create_desired_state_from_gql,
    fetch_current_state,
)

# the verification tool deliberately exercises the integration's own
# compilation path, private helpers included
from reconcile.typed_queries.clusters import get_clusters
from reconcile.utils import config, gql
from reconcile.utils.ocm import OCMMap
from reconcile.utils.secret_reader import SecretReaderBase

if TYPE_CHECKING:
    from collections.abc import Generator

THROWAWAY_PREFIX = "e2e-ocm-mp-api-"
OCM_ENVIRONMENT = "e2e"

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    """Print PASS/FAIL for one assertion and track failures."""
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" ({detail})" if detail else ""))
    if not condition:
        _failures.append(label)


def dump(label: str, obj: object) -> None:
    print(f"  {label}: {obj!r}")


def get_client_secret(vault_secret_path: str) -> str:
    """Read the OCM client secret from Vault (vault CLI login required)."""
    return subprocess.check_output(
        ["vault", "kv", "get", "-field=client_secret", vault_secret_path],
        text=True,
    ).strip()


#
# harness: the server-side service against real OCM, in-process
#


class InMemoryCacheBackend(CacheBackend):
    """Minimal in-process CacheBackend (no Redis dependency)."""

    def __init__(self) -> None:
        super().__init__(memory_max_size=1000, memory_ttl=600)
        self._store: dict[str, str] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self._store[key] = value

    def _delete_from_backend(self, key: str) -> None:
        self._store.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self._store

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        self._store.clear()

    def clear(self) -> None:
        """Drop everything (after out-of-band mutations)."""
        self._store.clear()
        self.clear_memory_cache()

    @contextmanager
    def lock(self, key: str, timeout: float = 300) -> Generator[None]:
        with self._locks_guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            yield


class ServiceHarness:
    """Runs the server-side service against real OCM, in-process."""

    def __init__(self, secret: str, ocm_url: str, sso_url: str, client_id: str) -> None:
        self.secret = secret
        self.cache = InMemoryCacheBackend()
        self.settings = Settings(ocm=OcmSettings())
        self.ocm_api_builds = 0

        def factory() -> OcmApi:
            self.ocm_api_builds += 1
            return OcmApi(
                url=ocm_url,
                access_token_url=sso_url,
                access_token_client_id=client_id,
                access_token_client_secret=secret,
            )

        self._factory = factory
        self.service = OcmMachinePoolsService(
            cache=self.cache,
            secret_manager=None,  # type: ignore[arg-type]
            settings=self.settings,
        )

    def reconcile(
        self,
        clusters: list[DesiredClusterMachinePools],
        *,
        dry_run: bool = True,
    ) -> Any:
        """Run one reconcile with the factory patched to real OCM."""

        def fake_factory(
            _params: object,
            cache: CacheBackend,
            _secret_manager: object,
            settings: Settings,
        ) -> OcmWorkspaceClient:
            return OcmWorkspaceClient(
                ocm_api_factory=self._factory,
                cache=cache,
                settings=settings,
                environment_key="e2e-verify",
            )

        with patch(
            "qontract_api.integrations.ocm_machine_pools.service."
            "create_ocm_workspace_client",
            side_effect=fake_factory,
        ):
            return self.service.reconcile(
                ocm_environment=OCM_ENVIRONMENT,
                ocm_connection=None,  # type: ignore[arg-type]
                clusters=clusters,
                dry_run=dry_run,
            )

    def bootstrap_api(self) -> OcmApi:
        """A raw Layer 1 client for snapshots and cluster-id resolution."""
        return self._factory()


#
# helpers
#


def resolve_cluster_id(api: OcmApi, name: str) -> str:
    """Look up a cluster's OCM id by name (search endpoint)."""
    resp = api._client.get(
        "/api/clusters_mgmt/v1/clusters",
        params={"search": f"name='{name}'"},
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if len(items) != 1:
        raise RuntimeError(f"cluster {name!r}: expected 1 result, got {len(items)}")
    return str(items[0]["id"])


def init_gql(gql_url: str) -> None:
    """Point the GQL layer at the App-Interface server."""
    config.init({"graphql": {"server": gql_url}})
    gql.init(gql_url, None, integration=None, validate_schemas=False)


def to_server_models(clusters: list[Any]) -> list[DesiredClusterMachinePools]:
    """Convert client-schema cluster models to the server's domain models.

    Pydantic v2 does not re-validate instances of a foreign BaseModel
    class, so the client's request models must round-trip through dicts
    before the in-process service consumes them - exactly what the
    HTTP/JSON boundary does in production.
    """
    return [DesiredClusterMachinePools.model_validate(c.model_dump()) for c in clusters]


def compiled_clusters(
    machine_pool_cluster: str, node_pool_cluster: str
) -> tuple[list[Any], dict[tuple[str, str], list[Any]]]:
    """Compile the desired state via the client integration's own code,
    with enablement patched (the -api integration may not be enabled
    anywhere yet - that is the rollout step this verification precedes)."""
    with patch(
        "reconcile.ocm_machine_pools_api.integration_is_enabled",
        return_value=True,
    ):
        all_clusters = client_integration._get_clusters()
        by_name = {c.name: c for c in all_clusters}
        for name in (machine_pool_cluster, node_pool_cluster):
            if name not in by_name:
                raise RuntimeError(f"cluster {name} not found in App-Interface")
        selected = [by_name[machine_pool_cluster], by_name[node_pool_cluster]]
        api_clusters = client_integration._build_api_clusters(selected)
        groups = client_integration._group_clusters_by_ocm(selected)
    return api_clusters, groups


#
# read-only scenarios
#


def scenario_compile_desired_state(
    api_clusters: list[Any],
    machine_pool_cluster: str,
    node_pool_cluster: str,
) -> None:
    print("== read-only: desired-state compilation (App-Interface GQL)")
    by_name = {c.name: c for c in api_clusters}
    check("two clusters compiled", len(api_clusters) == 2, str(list(by_name)))

    mp_cluster = by_name.get(machine_pool_cluster)
    np_cluster = by_name.get(node_pool_cluster)
    check(
        "machine pool cluster classified",
        mp_cluster is not None and mp_cluster.cluster_type in {"osd", "rosa"},
        str(mp_cluster.cluster_type if mp_cluster else None),
    )
    check(
        "HCP cluster classified",
        np_cluster is not None and np_cluster.cluster_type == "hypershift",
        str(np_cluster.cluster_type if np_cluster else None),
    )
    check(
        "cluster ids from spec.id",
        bool(mp_cluster and mp_cluster.cluster_id)
        and bool(np_cluster and np_cluster.cluster_id),
    )
    if mp_cluster:
        dump(
            f"{mp_cluster.name} pools",
            [(p.id, type(p).__name__) for p in mp_cluster.pools],
        )
        check(
            "machine pool cluster has machine pools",
            all(type(p).__name__ == "DesiredMachinePool" for p in mp_cluster.pools),
        )
    if np_cluster:
        dump(
            f"{np_cluster.name} pools",
            [(p.id, type(p).__name__) for p in np_cluster.pools],
        )
        check(
            "HCP cluster has node pools",
            all(type(p).__name__ == "DesiredNodePool" for p in np_cluster.pools),
        )


def scenario_grouping_and_connection(groups: dict[tuple[str, str], list[Any]]) -> None:
    print("== read-only: request grouping + connection (client path)")
    check(
        "clusters grouped",
        sum(len(v) for v in groups.values()) == 2,
        str({k: [c.name for c in v] for k, v in groups.items()}),
    )
    for (env_name, _ocm_name), cluster_list in groups.items():
        connection = client_integration._build_ocm_connection(
            cluster_list[0], "https://vault.example.com"
        )
        check(
            f"connection for {env_name} has an OCM url",
            bool(connection.ocm_url),
            str(connection.ocm_url),
        )
        check(
            f"connection for {env_name} has a client id",
            bool(connection.access_token_client_id),
        )


def new_dry_run_plan(
    harness: ServiceHarness, groups: dict[tuple[str, str], list[Any]]
) -> tuple[set[tuple[str, str, str]], list[str]]:
    """Dry-run the real desired state through the new server-side service."""
    print("== read-only: NEW integration dry-run plan (real OCM)")
    plan: set[tuple[str, str, str]] = set()
    errors: list[str] = []
    for (env_name, _ocm_name), cluster_list in groups.items():
        api_clusters = to_server_models(
            client_integration._build_api_clusters(cluster_list)
        )
        result = harness.reconcile(api_clusters, dry_run=True)
        check(
            f"dry-run {env_name} completed",
            result.status in {TaskStatus.SUCCESS, TaskStatus.FAILED},
            str(result.status),
        )
        for action in result.actions:
            plan.add((action.cluster, action.pool_id, action.action_type))
            dump("action", f"{action.cluster} {action.pool_id} {action.action_type}")
        errors.extend(result.errors)
    return plan, errors


def legacy_dry_run_plan(
    secret: str,
    machine_pool_cluster: str,
    node_pool_cluster: str,
) -> tuple[set[tuple[str, str, str]], list[str]]:
    """Dry-run the same clusters through the LEGACY integration code path."""
    print("== read-only: LEGACY integration dry-run plan (real OCM)")

    class StaticSecretReader(SecretReaderBase):
        """Serves the vault-CLI-read secret; the VaultClient's approle/kube
        auth isn't practical in a standalone script."""

        def _read(
            self, path: str, field: str, format: str | None, version: int | None
        ) -> str:
            return secret

        def _read_all(
            self, path: str, field: str, format: str | None, version: int | None
        ) -> dict[str, str]:
            return {"client_secret": secret}

    with patch(
        "reconcile.ocm_machine_pools.integration_is_enabled",
        return_value=True,
    ):
        clusters = get_clusters()
    selected = [
        c for c in clusters if c.name in {machine_pool_cluster, node_pool_cluster}
    ]
    if len(selected) != 2:
        raise RuntimeError(
            f"expected 2 clusters from legacy query, got {len(selected)}"
        )

    secret_reader = StaticSecretReader()
    ocm_map = OCMMap(
        clusters=[c.model_dump(by_alias=True) for c in selected],
        integration="e2e-parity",
        secret_reader=secret_reader,
    )

    current_state = fetch_current_state(ocm_map, selected)
    desired_state = create_desired_state_from_gql(selected)
    diffs, errors = calculate_diff(current_state, desired_state)
    error_messages = [str(e) for e in errors]

    plan: set[tuple[str, str, str]] = set()
    for diff in diffs:
        kind = "node_pool" if type(diff.pool).__name__ == "NodePool" else "machine_pool"
        plan.add((diff.pool.cluster, diff.pool.id, f"{diff.action}_{kind}"))
        dump(
            "legacy action", f"{diff.pool.cluster} {diff.pool.id} {diff.action}_{kind}"
        )
    return plan, error_messages


def scenario_parity(
    new_plan: set[tuple[str, str, str]],
    legacy_plan: set[tuple[str, str, str]],
    new_errors: list[str],
    legacy_errors: list[str],
) -> None:
    print("== read-only: PARITY (new plan == legacy plan)")
    check(
        "plans identical",
        new_plan == legacy_plan,
        f"only-new={sorted(new_plan - legacy_plan)} "
        f"only-legacy={sorted(legacy_plan - new_plan)}",
    )
    dump("new plan", sorted(new_plan) or "no actions")
    dump("legacy plan", sorted(legacy_plan) or "no actions")
    check(
        "error counts match",
        len(new_errors) == len(legacy_errors),
        f"new={len(new_errors)} legacy={len(legacy_errors)}",
    )


#
# mutation scenario (--mutate): throwaway pools only
#


def _snapshot_clusters(
    api: OcmApi,
    machine_pool_cluster: str,
    node_pool_cluster: str,
    mp_id: str,
    np_id: str,
) -> list[DesiredClusterMachinePools]:
    """Live-snapshot desired clusters using the server's domain models,
    with cluster ids from the live OCM lookup (the same values the client
    compiles from spec.id)."""

    def mp(p: Any) -> DesiredMachinePool:
        return DesiredMachinePool(
            id=p.id,
            instance_type=p.instance_type,
            replicas=p.replicas,
            autoscaling=(
                DesiredMachinePoolAutoscaling(
                    min_replicas=p.autoscaling.min_replicas,
                    max_replicas=p.autoscaling.max_replicas,
                )
                if p.autoscaling
                else None
            ),
            labels=p.labels,
            taints=p.taints,
        )

    def np(p: Any) -> DesiredNodePool:
        return DesiredNodePool(
            id=p.id,
            aws_node_pool=OcmNodePoolAws(instance_type=p.aws_node_pool.instance_type),
            replicas=p.replicas,
            autoscaling=(
                DesiredNodePoolAutoscaling(
                    min_replica=p.autoscaling.min_replica,
                    max_replica=p.autoscaling.max_replica,
                )
                if p.autoscaling
                else None
            ),
            labels=p.labels,
            taints=p.taints,
            subnet=p.subnet,
        )

    return [
        DesiredClusterMachinePools(
            name=machine_pool_cluster,
            cluster_id=mp_id,
            cluster_type=ClusterType.OSD,
            pools=[mp(p) for p in api.get_machine_pools(mp_id)],
        ),
        DesiredClusterMachinePools(
            name=node_pool_cluster,
            cluster_id=np_id,
            cluster_type=ClusterType.ROSA_HCP,
            pools=[np(p) for p in api.get_node_pools(np_id)],
        ),
    ]


def mutation_checks(
    harness: ServiceHarness,
    machine_pool_cluster: str,
    node_pool_cluster: str,
) -> None:
    """Throwaway-pool lifecycle through the client request-building path,
    against the in-process service with live-snapshot desired state (real
    App-Interface desired state is never applied)."""
    print("== mutate: cleanup leftovers from aborted runs")
    api = harness.bootstrap_api()
    try:
        mp_id = resolve_cluster_id(api, machine_pool_cluster)
        np_id = resolve_cluster_id(api, node_pool_cluster)
        for delete, cluster_id, pool_id in (
            (api.delete_machine_pool, mp_id, THROWAWAY_PREFIX + "mp"),
            (api.delete_node_pool, np_id, THROWAWAY_PREFIX + "np"),
        ):
            try:
                delete(cluster_id, pool_id)
                print(f"  deleted leftover {pool_id}")
            except Exception:
                logging.debug("no leftover %s", pool_id, exc_info=True)
        # the cleanup bypassed the workspace client, so its cache
        # invalidation never ran - drop the stale entries
        harness.cache.clear()

        print("== mutate: dry-run shows the creates")
        clusters = _snapshot_with_throwaway(
            api, machine_pool_cluster, node_pool_cluster, mp_id, np_id
        )
        result = harness.reconcile(clusters, dry_run=True)
        action_types = sorted(a.action_type for a in result.actions)
        check(
            "dry-run reports both creates",
            action_types == ["create_machine_pool", "create_node_pool"],
            str(action_types),
        )

        print("== mutate: create")
        result = harness.reconcile(clusters, dry_run=False)
        check(
            "create run SUCCESS",
            result.status == TaskStatus.SUCCESS,
            str(result.errors),
        )
        check(
            "creates applied",
            result.applied_count == 2,
            f"applied={result.applied_count}",
        )
        live_mp = [
            p for p in api.get_machine_pools(mp_id) if p.id.startswith(THROWAWAY_PREFIX)
        ]
        live_np = [
            p for p in api.get_node_pools(np_id) if p.id.startswith(THROWAWAY_PREFIX)
        ]
        check("machine pool live", len(live_mp) == 1)
        check("node pool live", len(live_np) == 1)

        print("== mutate: mode transition")
        # re-snapshot from live so OCM-assigned defaults don't read as drift
        by_name = {
            c.name: c
            for c in _snapshot_clusters(
                api, machine_pool_cluster, node_pool_cluster, mp_id, np_id
            )
        }

        def with_mp(pool_update: dict[str, Any]) -> list[DesiredClusterMachinePools]:
            out = []
            for c in (by_name[machine_pool_cluster], by_name[node_pool_cluster]):
                pools = [
                    p.model_copy(update=pool_update)
                    if p.id == THROWAWAY_PREFIX + "mp"
                    else p
                    for p in c.pools
                ]
                out.append(c.model_copy(update={"pools": pools}))
            return out

        result = harness.reconcile(
            with_mp({
                "replicas": None,
                "autoscaling": DesiredMachinePoolAutoscaling(
                    min_replicas=0, max_replicas=2
                ),
            }),
            dry_run=False,
        )
        check(
            "fixed->autoscaling SUCCESS",
            result.status == TaskStatus.SUCCESS,
            str(result.errors),
        )
        live_mp = [
            p for p in api.get_machine_pools(mp_id) if p.id == THROWAWAY_PREFIX + "mp"
        ]
        check(
            "autoscaling active",
            bool(live_mp) and live_mp[0].autoscaling is not None,
        )

        result = harness.reconcile(
            with_mp({"replicas": 1, "autoscaling": None}), dry_run=False
        )
        check(
            "autoscaling->fixed SUCCESS",
            result.status == TaskStatus.SUCCESS,
            str(result.errors),
        )
        live_mp = [
            p for p in api.get_machine_pools(mp_id) if p.id == THROWAWAY_PREFIX + "mp"
        ]
        check(
            "fixed active",
            bool(live_mp)
            and live_mp[0].autoscaling is None
            and live_mp[0].replicas == 1,
        )

        print("== mutate: delete throwaway pools")
        clean = [
            c.model_copy(
                update={
                    "pools": [
                        p for p in c.pools if not p.id.startswith(THROWAWAY_PREFIX)
                    ]
                }
            )
            for c in _snapshot_clusters(
                api, machine_pool_cluster, node_pool_cluster, mp_id, np_id
            )
        ]
        result = harness.reconcile(clean, dry_run=False)
        check(
            "delete run SUCCESS",
            result.status == TaskStatus.SUCCESS,
            str(result.errors),
        )
        leftovers_mp = [
            p.id
            for p in api.get_machine_pools(mp_id)
            if p.id.startswith(THROWAWAY_PREFIX)
        ]
        leftovers_np = [
            p.id for p in api.get_node_pools(np_id) if p.id.startswith(THROWAWAY_PREFIX)
        ]
        check("no throwaway machine pools left", leftovers_mp == [], str(leftovers_mp))
        check("no throwaway node pools left", leftovers_np == [], str(leftovers_np))
    finally:
        api.close()


def _snapshot_with_throwaway(
    api: OcmApi,
    machine_pool_cluster: str,
    node_pool_cluster: str,
    mp_id: str,
    np_id: str,
) -> list[DesiredClusterMachinePools]:
    """Live snapshot with throwaway pools added."""
    clusters = _snapshot_clusters(
        api, machine_pool_cluster, node_pool_cluster, mp_id, np_id
    )
    out = []
    for c in clusters:
        if c.name == machine_pool_cluster:
            pools: list[Any] = [
                DesiredMachinePool(
                    id=THROWAWAY_PREFIX + "mp",
                    instance_type="m5.xlarge",
                    replicas=0,
                ),
                *c.pools,
            ]
        else:
            pools = [
                DesiredNodePool(
                    id=THROWAWAY_PREFIX + "np",
                    aws_node_pool=OcmNodePoolAws(instance_type="m5.xlarge"),
                    replicas=0,
                ),
                *c.pools,
            ]
        out.append(c.model_copy(update={"pools": pools}))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gql-url", required=True, help="App-Interface GraphQL URL")
    parser.add_argument(
        "--machine-pool-cluster",
        required=True,
        help="OSD or ROSA classic cluster name (machine pools)",
    )
    parser.add_argument(
        "--node-pool-cluster",
        required=True,
        help="ROSA HCP cluster name (node pools)",
    )
    parser.add_argument(
        "--vault-secret-path",
        required=True,
        help="Vault KV path holding the OCM client secret (field: client_secret)",
    )
    parser.add_argument("--ocm-url", default="https://api.openshift.com")
    parser.add_argument(
        "--sso-url",
        default="https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token",
    )
    parser.add_argument("--ocm-client-id", required=True)
    parser.add_argument("--mutate", action="store_true")
    args = parser.parse_args()

    print(f"ocm-machine-pools-api E2E verification (mutate={args.mutate})")

    secret = get_client_secret(args.vault_secret_path)
    init_gql(args.gql_url)
    print(f"using App-Interface GraphQL: {args.gql_url}")

    harness = ServiceHarness(secret, args.ocm_url, args.sso_url, args.ocm_client_id)

    api_clusters, groups = compiled_clusters(
        args.machine_pool_cluster, args.node_pool_cluster
    )
    scenario_compile_desired_state(
        api_clusters, args.machine_pool_cluster, args.node_pool_cluster
    )
    scenario_grouping_and_connection(groups)

    new_plan, new_errors = new_dry_run_plan(harness, groups)
    legacy_plan, legacy_errors = legacy_dry_run_plan(
        secret, args.machine_pool_cluster, args.node_pool_cluster
    )
    scenario_parity(new_plan, legacy_plan, new_errors, legacy_errors)

    if args.mutate:
        mutation_checks(harness, args.machine_pool_cluster, args.node_pool_cluster)
    else:
        print("(read-only; re-run with --mutate for throwaway-pool mutations)")

    if _failures:
        print(f"\nFAILED checks: {len(_failures)}")
        for failure in _failures:
            print(f"  - {failure}")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

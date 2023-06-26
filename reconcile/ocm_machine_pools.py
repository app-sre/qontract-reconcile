import logging
import sys
from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Mapping
from typing import (
    Iterable,
    Optional,
)

from pydantic import BaseModel

from reconcile import queries
from reconcile.gql_definitions.common.clusters import (
    ClusterMachinePoolV1,
    ClusterV1,
)
from reconcile.gql_definitions.common.clusters import query as clusters_query
from reconcile.utils import gql
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.ocm import (
    OCM,
    OCMMap,
)

QONTRACT_INTEGRATION = "ocm-machine-pools"


class InvalidUpdateError(Exception):
    pass


class AbstractPool(ABC, BaseModel):
    # Abstract class for machine pools, to be implemented by OSD/HyperShift classes

    id: str
    replicas: int
    taints: Optional[list[Mapping[str, str]]]
    labels: Optional[Mapping[str, str]]
    cluster: str

    @abstractmethod
    def create(self, ocm: OCM) -> None:
        pass

    @abstractmethod
    def delete(self, ocm: OCM) -> None:
        pass

    @abstractmethod
    def update(self, ocm: OCM) -> None:
        pass

    @abstractmethod
    def has_diff(self, pool: ClusterMachinePoolV1) -> bool:
        pass

    @abstractmethod
    def invalid_diff(self, pool: ClusterMachinePoolV1) -> Optional[str]:
        pass


class MachinePool(AbstractPool):
    # Machine pool, used for OSD clusters

    instance_type: str

    def delete(self, ocm: OCM) -> None:
        ocm.delete_machine_pool(self.cluster, self.dict(by_alias=True))

    def create(self, ocm: OCM) -> None:
        ocm.create_machine_pool(self.cluster, self.dict(by_alias=True))

    def update(self, ocm: OCM) -> None:
        update_dict = self.dict(by_alias=True)
        # can not update instance_type
        del update_dict["instance_type"]
        if not update_dict["labels"]:
            del update_dict["labels"]
        if not update_dict["taints"]:
            del update_dict["taints"]
        ocm.update_machine_pool(self.cluster, update_dict)

    def has_diff(self, pool: ClusterMachinePoolV1) -> bool:
        if self.taints != pool.taints or self.labels != pool.labels:
            logging.warning(
                f"updating labels or taints for machine pool {pool.q_id} "
                f"will only be applied to new Nodes"
            )
        return (
            self.replicas != pool.replicas
            or self.taints != pool.taints
            or self.labels != pool.labels
            or self.instance_type != pool.instance_type
        )

    def invalid_diff(self, pool: ClusterMachinePoolV1) -> Optional[str]:
        if self.instance_type != pool.instance_type:
            return "instance_type"
        return None

    @classmethod
    def create_from_gql(cls, pool: ClusterMachinePoolV1, cluster: str):
        return cls(
            id=pool.q_id,
            replicas=pool.replicas,
            instance_type=pool.instance_type,
            taints=[p.dict(by_alias=True) for p in pool.taints or []],
            labels=pool.labels,
            cluster=cluster,
        )


class AWSNodePool(BaseModel):
    instance_type: str


class NodePool(AbstractPool):
    # Node pool, used for HyperShift clusters

    aws_node_pool: AWSNodePool
    subnet: Optional[str]

    def delete(self, ocm: OCM) -> None:
        ocm.delete_node_pool(self.cluster, self.dict(by_alias=True))

    def create(self, ocm: OCM) -> None:
        ocm.create_node_pool(self.cluster, self.dict(by_alias=True))

    def update(self, ocm: OCM) -> None:
        update_dict = self.dict(by_alias=True)
        # can not update instance_type
        del update_dict["aws_node_pool"]
        # can not update subnet
        del update_dict["subnet"]
        if not update_dict["labels"]:
            del update_dict["labels"]
        if not update_dict["taints"]:
            del update_dict["taints"]
        ocm.update_node_pool(self.cluster, update_dict)

    def has_diff(self, pool: ClusterMachinePoolV1) -> bool:
        if self.taints != pool.taints or self.labels != pool.labels:
            logging.warning(
                f"updating labels or taints for node pool {pool.q_id} "
                f"will only be applied to new Nodes"
            )
        return (
            self.replicas != pool.replicas
            or self.taints != pool.taints
            or self.labels != pool.labels
            or self.aws_node_pool.instance_type != pool.instance_type
            or self.subnet != pool.subnet
        )

    def invalid_diff(self, pool: ClusterMachinePoolV1) -> Optional[str]:
        if self.aws_node_pool.instance_type != pool.instance_type:
            return "instance_type"
        if self.subnet != pool.subnet:
            return "subnet"
        return None

    @classmethod
    def create_from_gql(cls, pool: ClusterMachinePoolV1, cluster: str):
        return cls(
            id=pool.q_id,
            replicas=pool.replicas,
            aws_node_pool=AWSNodePool(
                instance_type=pool.instance_type,
            ),
            taints=[p.dict(by_alias=True) for p in pool.taints or []],
            labels=pool.labels,
            subnet=pool.subnet,
            cluster=cluster,
        )


class PoolHandler(BaseModel):
    # Class, that acts on a pool, based on the action

    action: str
    pool: AbstractPool

    def act(self, dry_run: bool, ocm: OCM) -> None:
        logging.info(f"{self.action} {self.pool.dict(by_alias=True)}")
        if dry_run:
            return

        if not self.action:
            pass
        elif self.action == "delete":
            self.pool.delete(ocm)
        elif self.action == "create":
            self.pool.create(ocm)
        elif self.action == "update":
            self.pool.update(ocm)


class DesiredMachinePool(BaseModel):
    cluster_name: str
    hypershift: bool
    pools: list[ClusterMachinePoolV1]


class DesiredStateList(BaseModel):
    cluster_pools: list[DesiredMachinePool]


def fetch_current_state(
    ocm_map: OCMMap,
    clusters: Iterable[ClusterV1],
) -> Mapping[str, list[AbstractPool]]:
    return {
        c.name: fetch_current_state_for_cluster(c, ocm_map.get(c.name))
        for c in clusters
    }


def fetch_current_state_for_cluster(cluster, ocm):
    if cluster.spec and cluster.spec.hypershift:
        return [
            NodePool(
                id=machine_pool["id"],
                replicas=machine_pool["replicas"],
                aws_node_pool=AWSNodePool(
                    instance_type=machine_pool["aws_node_pool"]["instance_type"]
                ),
                taints=machine_pool.get("taints"),
                labels=machine_pool.get("labels"),
                subnet=machine_pool.get("subnet"),
                cluster=cluster.name,
            )
            for machine_pool in ocm.get_node_pools(cluster.name)
        ]
    return [
        MachinePool(
            id=machine_pool["id"],
            replicas=machine_pool["replicas"],
            instance_type=machine_pool["instance_type"],
            taints=machine_pool.get("taints"),
            labels=machine_pool.get("labels"),
            cluster=cluster.name,
        )
        for machine_pool in ocm.get_machine_pools(cluster.name)
    ]


def create_desired_state_from_gql(
    clusters: Iterable[ClusterV1],
) -> DesiredStateList:
    desired_state: DesiredStateList = DesiredStateList(cluster_pools=[])
    for cluster in clusters:
        if cluster.machine_pools:
            is_hypershift = False
            if cluster.spec:
                is_hypershift = True if cluster.spec.hypershift else False
            desired_state.cluster_pools.append(
                DesiredMachinePool(
                    cluster_name=cluster.name,
                    hypershift=is_hypershift,
                    pools=cluster.machine_pools,
                )
            )

    return desired_state


def calculate_diff(
    current_state: Mapping[str, list[AbstractPool]],
    desired_state: DesiredStateList,
) -> tuple[list[PoolHandler], list[InvalidUpdateError]]:
    diffs: list[PoolHandler] = []
    errors: list[InvalidUpdateError] = []

    all_desired_pools: set[tuple[str, str]] = set()
    for desired in desired_state.cluster_pools:
        for desired_machine_pool in desired.pools:
            current_machine_pool = [
                p
                for p in current_state.get(desired.cluster_name, [])
                if p.id == desired_machine_pool.q_id
            ]
            all_desired_pools.add((desired_machine_pool.q_id, desired.cluster_name))
            if not current_machine_pool:
                if desired.hypershift:
                    diffs.append(
                        PoolHandler(
                            action="create",
                            pool=NodePool.create_from_gql(
                                pool=desired_machine_pool,
                                cluster=desired.cluster_name,
                            ),
                        )
                    )
                else:
                    diffs.append(
                        PoolHandler(
                            action="create",
                            pool=MachinePool.create_from_gql(
                                pool=desired_machine_pool,
                                cluster=desired.cluster_name,
                            ),
                        )
                    )
                    continue
            elif current_machine_pool[0].has_diff(desired_machine_pool):
                invalid_diff = current_machine_pool[0].invalid_diff(
                    desired_machine_pool
                )
                if invalid_diff:
                    errors.append(
                        InvalidUpdateError(
                            f"can not update {invalid_diff} for existing machine pool"
                        )
                    )
                else:
                    if desired.hypershift:
                        diffs.append(
                            PoolHandler(
                                action="update",
                                pool=NodePool.create_from_gql(
                                    pool=desired_machine_pool,
                                    cluster=desired.cluster_name,
                                ),
                            )
                        )
                    else:
                        diffs.append(
                            PoolHandler(
                                action="update",
                                pool=MachinePool.create_from_gql(
                                    pool=desired_machine_pool,
                                    cluster=desired.cluster_name,
                                ),
                            )
                        )

    for cluster_name, machine_pools in current_state.items():
        for pool in machine_pools:
            if (pool.id, cluster_name) not in all_desired_pools:
                if pool.id.startswith("workers"):
                    # As of now, you can not delete the first worker pool(s)
                    continue
                diffs.append(
                    PoolHandler(
                        action="delete",
                        pool=pool,
                    )
                )
    return diffs, errors


def act(dry_run: bool, diffs: Iterable[PoolHandler], ocm_map: OCMMap) -> None:
    for diff in diffs:
        logging.info([diff.action, diff.pool.cluster, diff.pool.id])
        if not dry_run:
            ocm = ocm_map.get(diff.pool.cluster)
            diff.act(dry_run, ocm)


def _cluster_is_compatible(cluster: ClusterV1) -> bool:
    return cluster.ocm is not None and cluster.machine_pools is not None


def run(dry_run: bool):
    clusters = clusters_query(query_func=gql.get_api().query).clusters or []

    filtered_clusters = [
        c
        for c in clusters
        if integration_is_enabled(QONTRACT_INTEGRATION, c) and _cluster_is_compatible(c)
    ]
    if not filtered_clusters:
        logging.debug("No machinePools definitions found in app-interface")
        sys.exit(0)

    settings = queries.get_app_interface_settings()
    cluster_like_objects = [
        cluster.dict(by_alias=True) for cluster in filtered_clusters
    ]
    ocm_map = OCMMap(
        clusters=cluster_like_objects,
        integration=QONTRACT_INTEGRATION,
        settings=settings,
    )

    current_state = fetch_current_state(ocm_map, filtered_clusters)
    desired_state = create_desired_state_from_gql(filtered_clusters)
    diffs, errors = calculate_diff(current_state, desired_state)

    act(dry_run, diffs, ocm_map)

    if errors:
        for err in errors:
            logging.error(err)
        sys.exit(1)

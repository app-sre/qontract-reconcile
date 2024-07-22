from __future__ import annotations

import logging
import random
import string
from abc import abstractmethod
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from reconcile.ocm.types import (
    ClusterMachinePool,
    OCMClusterNetwork,
    OCMClusterSpec,
    OCMSpec,
    OSDClusterSpec,
    ROSAClusterAWSAccount,
    ROSAClusterSpec,
    ROSAOcmAwsAttrs,
    ROSAOcmAwsStsAttrs,
)
from reconcile.utils.exceptions import ParameterError
from reconcile.utils.ocm.clusters import get_provisioning_shard_id
from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.rosa.rosa_cli import RosaCliException
from reconcile.utils.rosa.session import RosaSessionBuilder

CS_API_BASE = "/api/clusters_mgmt"

SPEC_ATTR_ACCOUNT = "account"
SPEC_ATTR_DISABLE_UWM = "disable_user_workload_monitoring"
SPEC_ATTR_PRIVATE = "private"
SPEC_ATTR_CHANNEL = "channel"
SPEC_ATTR_LOAD_BALANCERS = "load_balancers"
SPEC_ATTR_STORAGE = "storage"
SPEC_ATTR_ID = "id"
SPEC_ATTR_EXTERNAL_ID = "external_id"
SPEC_ATTR_OIDC_ENDPONT_URL = "oidc_endpoint_url"
SPEC_ATTR_PROVISION_SHARD_ID = "provision_shard_id"
SPEC_ATTR_VERSION = "version"
SPEC_ATTR_INITIAL_VERSION = "initial_version"
SPEC_ATTR_MULTI_AZ = "multi_az"
SPEC_ATTR_HYPERSHIFT = "hypershift"
SPEC_ATTR_SUBNET_IDS = "subnet_ids"
SPEC_ATTR_AVAILABILITY_ZONES = "availability_zones"

SPEC_ATTR_NETWORK = "network"

SPEC_ATTR_CONSOLE_URL = "consoleUrl"
SPEC_ATTR_SERVER_URL = "serverUrl"
SPEC_ATTR_ELBFQDN = "elbFQDN"
SPEC_ATTR_PATH = "path"

BYTES_IN_GIGABYTE = 1024**3
DEFAULT_OCM_MACHINE_POOL_ID = "worker"

OCM_PRODUCT_OSD = "osd"
OCM_PRODUCT_ROSA = "rosa"
OCM_PRODUCT_HYPERSHIFT = "hypershift"


class OCMValidationException(Exception):
    pass


class OCMProduct:
    ALLOWED_SPEC_UPDATE_FIELDS: set[str]
    EXCLUDED_SPEC_FIELDS: set[str]

    @abstractmethod
    def create_cluster(
        self,
        ocm: OCMBaseClient,
        org_id: str,
        name: str,
        cluster: OCMSpec,
        dry_run: bool,
    ) -> None:
        pass

    @abstractmethod
    def update_cluster(
        self,
        ocm: OCMBaseClient,
        cluster_id: str,
        update_spec: Mapping[str, Any],
        dry_run: bool,
    ) -> None:
        pass

    @abstractmethod
    def get_ocm_spec(
        self,
        ocm: OCMBaseClient,
        cluster: Mapping[str, Any],
        init_provision_shards: bool,
    ) -> OCMSpec:
        pass


class OCMProductOsd(OCMProduct):
    ALLOWED_SPEC_UPDATE_FIELDS = {
        SPEC_ATTR_STORAGE,
        SPEC_ATTR_LOAD_BALANCERS,
        SPEC_ATTR_PRIVATE,
        SPEC_ATTR_CHANNEL,
        SPEC_ATTR_DISABLE_UWM,
    }

    EXCLUDED_SPEC_FIELDS = {
        SPEC_ATTR_ID,
        SPEC_ATTR_EXTERNAL_ID,
        SPEC_ATTR_PROVISION_SHARD_ID,
        SPEC_ATTR_VERSION,
        SPEC_ATTR_INITIAL_VERSION,
        SPEC_ATTR_HYPERSHIFT,
    }

    def create_cluster(
        self,
        ocm: OCMBaseClient,
        org_id: str,
        name: str,
        cluster: OCMSpec,
        dry_run: bool,
    ) -> None:
        ocm_spec = self._get_create_cluster_spec(name, cluster)
        api = f"{CS_API_BASE}/v1/clusters"
        params = {}
        if dry_run:
            params["dryRun"] = "true"

        ocm.post(api, ocm_spec, params)

    def update_cluster(
        self,
        ocm: OCMBaseClient,
        cluster_id: str,
        update_spec: Mapping[str, Any],
        dry_run: bool,
    ) -> None:
        ocm_spec = self._get_update_cluster_spec(update_spec)
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}"
        params: dict[str, Any] = {}
        if dry_run:
            params["dryRun"] = "true"
        ocm.patch(api, ocm_spec, params)

    def get_ocm_spec(
        self,
        ocm: OCMBaseClient,
        cluster: Mapping[str, Any],
        init_provision_shards: bool,
    ) -> OCMSpec:
        if init_provision_shards:
            provision_shard_id = get_provisioning_shard_id(ocm, cluster["id"])
        else:
            provision_shard_id = None

        spec = OCMClusterSpec(
            product=cluster["product"]["id"],
            id=cluster["id"],
            external_id=cluster["external_id"],
            provider=cluster["cloud_provider"]["id"],
            region=cluster["region"]["id"],
            channel=cluster["version"]["channel_group"],
            version=cluster["version"]["raw_id"],
            multi_az=cluster["multi_az"],
            private=cluster["api"]["listening"] == "internal",
            disable_user_workload_monitoring=cluster[
                "disable_user_workload_monitoring"
            ],
            provision_shard_id=provision_shard_id,
            hypershift=cluster["hypershift"]["enabled"],
        )

        if not cluster["ccs"]["enabled"]:
            cluster_spec_data = spec.dict()
            cluster_spec_data["storage"] = (
                cluster["storage_quota"]["value"] // BYTES_IN_GIGABYTE
            )
            cluster_spec_data["load_balancers"] = cluster["load_balancer_quota"]
            spec = OSDClusterSpec(**cluster_spec_data)

        machine_pools = [
            ClusterMachinePool(**p) for p in cluster.get("machinePools") or []
        ]

        network = OCMClusterNetwork(
            type=cluster["network"].get("type") or "OVNKubernetes",
            vpc=cluster["network"]["machine_cidr"],
            service=cluster["network"]["service_cidr"],
            pod=cluster["network"]["pod_cidr"],
        )

        ocm_spec = OCMSpec(
            console_url=cluster["console"]["url"],
            server_url=cluster["api"]["url"],
            domain=cluster["dns"]["base_domain"],
            spec=spec,
            machine_pools=machine_pools,
            network=network,
        )

        return ocm_spec

    def _get_nodes_spec(self, cluster: OCMSpec) -> dict[str, Any]:
        default_machine_pool = next(
            (
                mp
                for mp in cluster.machine_pools
                if mp.id == DEFAULT_OCM_MACHINE_POOL_ID
            ),
            None,
        )
        if default_machine_pool is None:
            raise OCMValidationException(
                f"No default machine pool found, id: {DEFAULT_OCM_MACHINE_POOL_ID}"
            )

        spec: dict[str, Any] = {
            "compute_machine_type": {"id": default_machine_pool.instance_type},
        }
        if default_machine_pool.autoscale is not None:
            spec["autoscale_compute"] = default_machine_pool.autoscale.dict()
        else:
            spec["compute"] = default_machine_pool.replicas
        return spec

    def _get_create_cluster_spec(
        self, cluster_name: str, cluster: OCMSpec
    ) -> dict[str, Any]:
        ocm_spec: dict[str, Any] = {
            "name": cluster_name,
            "cloud_provider": {"id": cluster.spec.provider},
            "region": {"id": cluster.spec.region},
            "version": {
                "id": f"openshift-v{cluster.spec.initial_version}",
                "channel_group": cluster.spec.channel,
            },
            "multi_az": cluster.spec.multi_az,
            "nodes": self._get_nodes_spec(cluster),
            "network": {
                "type": cluster.network.type or "OVNKubernetes",
                "machine_cidr": cluster.network.vpc,
                "service_cidr": cluster.network.service,
                "pod_cidr": cluster.network.pod,
            },
            "api": {"listening": "internal" if cluster.spec.private else "external"},
            "disable_user_workload_monitoring": (
                duwm
                if (duwm := cluster.spec.disable_user_workload_monitoring) is not None
                else True
            ),
        }

        # Workaround to enable type checks.
        # cluster.spec is a Union of pydantic models Union[OSDClusterSpec, RosaClusterSpec].
        # In this case, cluster.spec will always be an OSDClusterSpec because the type
        # assignment is managed by pydantic, however, mypy complains if OSD attributes are set
        # outside the isinstance check because it checks all the types set in the Union.
        if isinstance(cluster.spec, OSDClusterSpec):
            ocm_spec["storage_quota"] = {
                "value": float(cluster.spec.storage * BYTES_IN_GIGABYTE),
            }
            ocm_spec["load_balancer_quota"] = cluster.spec.load_balancers

        provision_shard_id = cluster.spec.provision_shard_id
        if provision_shard_id:
            ocm_spec.setdefault("properties", {})
            ocm_spec["properties"]["provision_shard_id"] = provision_shard_id
        return ocm_spec

    def _get_update_cluster_spec(
        self, update_spec: Mapping[str, Any]
    ) -> dict[str, Any]:
        ocm_spec: dict[str, Any] = {}

        storage = update_spec.get("storage")
        if storage is not None:
            ocm_spec["storage_quota"] = {"value": float(storage * 1073741824)}  # 1024^3

        load_balancers = update_spec.get("load_balancers")
        if load_balancers is not None:
            ocm_spec["load_balancer_quota"] = load_balancers

        private = update_spec.get("private")
        if private is not None:
            ocm_spec["api"] = {"listening": "internal" if private else "external"}

        channel = update_spec.get("channel")
        if channel is not None:
            ocm_spec["version"] = {"channel_group": channel}

        disable_uwm = update_spec.get("disable_user_workload_monitoring")
        if disable_uwm is not None:
            ocm_spec["disable_user_workload_monitoring"] = disable_uwm

        return ocm_spec


class OCMProductRosa(OCMProduct):
    def __init__(self, rosa_session_builder: RosaSessionBuilder | None) -> None:
        super().__init__()
        self.rosa_session_builder = rosa_session_builder

    ALLOWED_SPEC_UPDATE_FIELDS = {
        SPEC_ATTR_CHANNEL,
        SPEC_ATTR_DISABLE_UWM,
    }

    EXCLUDED_SPEC_FIELDS = {
        SPEC_ATTR_ID,
        SPEC_ATTR_EXTERNAL_ID,
        SPEC_ATTR_PROVISION_SHARD_ID,
        SPEC_ATTR_VERSION,
        SPEC_ATTR_INITIAL_VERSION,
        SPEC_ATTR_ACCOUNT,
        SPEC_ATTR_HYPERSHIFT,
        SPEC_ATTR_SUBNET_IDS,
        SPEC_ATTR_AVAILABILITY_ZONES,
        SPEC_ATTR_OIDC_ENDPONT_URL,
    }

    def create_cluster(
        self,
        ocm: OCMBaseClient,
        org_id: str,
        name: str,
        cluster: OCMSpec,
        dry_run: bool,
    ) -> None:
        if not isinstance(cluster.spec, ROSAClusterSpec):
            # make mypy happy
            return

        if self.rosa_session_builder is None:
            raise Exception(
                "OCMProductROSA is not configured with a rosa session builder"
            )

        rosa_session = self.rosa_session_builder.build(
            ocm, cluster.spec.account.uid, cluster.spec.region, org_id
        )
        try:
            result = rosa_session.create_rosa_cluster(
                cluster_name=name, spec=cluster, dry_run=dry_run
            )
            logging.info("cluster creation kicked off...")
            result.write_logs_to_logger(logging.info)
        except RosaCliException as e:
            logs = "".join(e.get_log_lines(max_lines=10, from_file_end=True))
            e.cleanup()
            raise OCMValidationException(
                f"last 10 lines from failed cluster creation job...\n\n{logs}"
            ) from None

    def update_cluster(
        self,
        ocm: OCMBaseClient,
        cluster_id: str,
        update_spec: Mapping[str, Any],
        dry_run: bool,
    ) -> None:
        ocm_spec = self._get_update_cluster_spec(update_spec)
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}"
        params: dict[str, Any] = {}
        if dry_run:
            params["dryRun"] = "true"
        ocm.patch(api, ocm_spec, params)

    def get_ocm_spec(
        self,
        ocm: OCMBaseClient,
        cluster: Mapping[str, Any],
        init_provision_shards: bool,
    ) -> OCMSpec:
        if init_provision_shards:
            provision_shard_id = get_provisioning_shard_id(ocm, cluster["id"])
        else:
            provision_shard_id = None

        sts = None
        oidc_endpoint_url = None
        if cluster["aws"].get("sts", None):
            sts = ROSAOcmAwsStsAttrs(
                installer_role_arn=cluster["aws"]["sts"]["role_arn"],
                support_role_arn=cluster["aws"]["sts"]["support_role_arn"],
                controlplane_role_arn=cluster["aws"]["sts"]["instance_iam_roles"].get(
                    "master_role_arn"
                ),
                worker_role_arn=cluster["aws"]["sts"]["instance_iam_roles"][
                    "worker_role_arn"
                ],
            )
            oidc_endpoint_url = cluster["aws"]["sts"]["oidc_endpoint_url"]
        account = ROSAClusterAWSAccount(
            uid=cluster["properties"]["rosa_creator_arn"].split(":")[4],
            rosa=ROSAOcmAwsAttrs(
                creator_role_arn=cluster["properties"]["rosa_creator_arn"],
                sts=sts,
            ),
        )

        spec = ROSAClusterSpec(
            product=cluster["product"]["id"],
            account=account,
            id=cluster["id"],
            external_id=cluster.get("external_id"),
            provider=cluster["cloud_provider"]["id"],
            region=cluster["region"]["id"],
            channel=cluster["version"]["channel_group"],
            version=cluster["version"]["raw_id"],
            multi_az=cluster["multi_az"],
            private=cluster["api"]["listening"] == "internal",
            disable_user_workload_monitoring=cluster[
                "disable_user_workload_monitoring"
            ],
            provision_shard_id=provision_shard_id,
            hypershift=cluster["hypershift"]["enabled"],
            subnet_ids=cluster["aws"].get("subnet_ids"),
            availability_zones=cluster["nodes"].get("availability_zones"),
            oidc_endpoint_url=oidc_endpoint_url,
        )

        machine_pools = [
            ClusterMachinePool(**p) for p in cluster.get("machinePools") or []
        ]

        network = OCMClusterNetwork(
            type=cluster["network"].get("type") or "OVNKubernetes",
            vpc=cluster["network"]["machine_cidr"],
            service=cluster["network"]["service_cidr"],
            pod=cluster["network"]["pod_cidr"],
        )

        ocm_spec = OCMSpec(
            # Hosted control plane clusters can reach a Ready State without having the console
            # Endpoint
            console_url=cluster.get("console", {}).get("url", ""),
            server_url=cluster["api"]["url"],
            domain=cluster["dns"]["base_domain"],
            spec=spec,
            machine_pools=machine_pools,
            network=network,
        )

        return ocm_spec

    def _get_nodes_spec(self, cluster: OCMSpec) -> dict[str, Any]:
        default_machine_pool = next(
            (
                mp
                for mp in cluster.machine_pools
                if mp.id == DEFAULT_OCM_MACHINE_POOL_ID
            ),
            None,
        )
        if default_machine_pool is None:
            raise OCMValidationException(
                f"No default machine pool found, id: {DEFAULT_OCM_MACHINE_POOL_ID}"
            )

        spec: dict[str, Any] = {
            "compute_machine_type": {"id": default_machine_pool.instance_type},
        }
        if default_machine_pool.autoscale is not None:
            spec["autoscale_compute"] = default_machine_pool.autoscale.dict()
        else:
            spec["compute"] = default_machine_pool.replicas
        return spec

    def _get_create_cluster_spec(
        self, cluster_name: str, cluster: OCMSpec
    ) -> dict[str, Any]:
        if not isinstance(cluster.spec, ROSAClusterSpec):
            # make mypy happy
            raise ParameterError("spec is not for a ROSA cluster")
        if not cluster.spec.account.rosa:
            raise ParameterError(
                "cluster.spec.account.rosa not specified... required for ROSA classic clusters"
            )

        operator_roles_prefix = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=4)
        )

        ocm_spec: dict[str, Any] = {
            "api": {"listening": "internal" if cluster.spec.private else "external"},
            "name": cluster_name,
            "cloud_provider": {"id": cluster.spec.provider},
            "region": {"id": cluster.spec.region},
            "version": {
                "id": f"openshift-v{cluster.spec.initial_version}",
                "channel_group": cluster.spec.channel,
            },
            "hypershift": {"enabled": cluster.spec.hypershift},
            "multi_az": cluster.spec.multi_az,
            "nodes": self._get_nodes_spec(cluster),
            "network": {
                "type": cluster.network.type or "OVNKubernetes",
                "machine_cidr": cluster.network.vpc,
                "service_cidr": cluster.network.service,
                "pod_cidr": cluster.network.pod,
            },
            "disable_user_workload_monitoring": (
                duwm
                if (duwm := cluster.spec.disable_user_workload_monitoring) is not None
                else True
            ),
        }

        provision_shard_id = cluster.spec.provision_shard_id
        if provision_shard_id:
            ocm_spec.setdefault("properties", {})
            ocm_spec["properties"]["provision_shard_id"] = provision_shard_id

        if isinstance(cluster.spec, ROSAClusterSpec):
            ocm_spec.setdefault("properties", {})
            ocm_spec["properties"]["rosa_creator_arn"] = (
                cluster.spec.account.rosa.creator_role_arn
            )

            if not cluster.spec.account.rosa.sts:
                raise ParameterError("STS is required for ROSA clusters")

            rosa_spec: dict[str, Any] = {
                "product": {"id": "rosa"},
                "ccs": {"enabled": True},
                "aws": {
                    "account_id": cluster.spec.account.uid,
                    "sts": {
                        "enabled": True,
                        "auto_mode": True,
                        "role_arn": cluster.spec.account.rosa.sts.installer_role_arn,
                        "support_role_arn": cluster.spec.account.rosa.sts.support_role_arn,
                        "instance_iam_roles": {
                            "worker_role_arn": cluster.spec.account.rosa.sts.worker_role_arn,
                        },
                        "operator_role_prefix": f"{cluster_name}-{operator_roles_prefix}",
                    },
                },
            }

            if cluster.spec.account.rosa.sts.controlplane_role_arn:
                rosa_spec["aws"]["sts"]["instance_iam_roles"]["master_role_arn"] = (
                    cluster.spec.account.rosa.sts.controlplane_role_arn
                )

            if cluster.spec.hypershift:
                ocm_spec["nodes"]["availability_zones"] = (
                    cluster.spec.availability_zones
                )
                rosa_spec["aws"]["subnet_ids"] = cluster.spec.subnet_ids

        ocm_spec.update(rosa_spec)
        return ocm_spec

    def _get_update_cluster_spec(
        self, update_spec: Mapping[str, Any]
    ) -> dict[str, Any]:
        ocm_spec: dict[str, Any] = {}

        channel = update_spec.get(SPEC_ATTR_CHANNEL)
        if channel is not None:
            ocm_spec["version"] = {"channel_group": channel}

        disable_uwm = update_spec.get(SPEC_ATTR_DISABLE_UWM)
        if disable_uwm is not None:
            ocm_spec["disable_user_workload_monitoring"] = disable_uwm

        return ocm_spec


class OCMProductHypershift(OCMProduct):
    def __init__(self, rosa_session_builder: RosaSessionBuilder | None) -> None:
        super().__init__()
        self.rosa_session_builder = rosa_session_builder

    # Not a real product, but a way to represent the Hypershift specialties
    ALLOWED_SPEC_UPDATE_FIELDS = {
        SPEC_ATTR_CHANNEL,
        SPEC_ATTR_PRIVATE,
        SPEC_ATTR_DISABLE_UWM,
    }

    EXCLUDED_SPEC_FIELDS = {
        SPEC_ATTR_ID,
        SPEC_ATTR_EXTERNAL_ID,
        SPEC_ATTR_PROVISION_SHARD_ID,
        SPEC_ATTR_VERSION,
        SPEC_ATTR_INITIAL_VERSION,
        SPEC_ATTR_ACCOUNT,
        SPEC_ATTR_HYPERSHIFT,
        SPEC_ATTR_SUBNET_IDS,
        SPEC_ATTR_AVAILABILITY_ZONES,
        SPEC_ATTR_OIDC_ENDPONT_URL,
    }

    def create_cluster(
        self,
        ocm: OCMBaseClient,
        org_id: str,
        name: str,
        cluster: OCMSpec,
        dry_run: bool,
    ) -> None:
        if not isinstance(cluster.spec, ROSAClusterSpec):
            # make mypy happy
            return

        if self.rosa_session_builder is None:
            raise Exception(
                "OCMProductHypershift is not configured with a rosa session builder"
            )

        rosa_session = self.rosa_session_builder.build(
            ocm, cluster.spec.account.uid, cluster.spec.region, org_id
        )
        try:
            result = rosa_session.create_hcp_cluster(
                cluster_name=name, spec=cluster, dry_run=dry_run
            )
            logging.info("cluster creation kicked off...")
            result.write_logs_to_logger(logging.info)
        except RosaCliException as e:
            logs = "".join(e.get_log_lines(max_lines=10, from_file_end=True))
            e.cleanup()
            raise OCMValidationException(
                f"last 10 lines from failed cluster creation job...\n\n{logs}"
            ) from None

    def update_cluster(
        self,
        ocm: OCMBaseClient,
        cluster_id: str,
        update_spec: Mapping[str, Any],
        dry_run: bool,
    ) -> None:
        ocm_spec = self._get_update_cluster_spec(update_spec)
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}"
        params: dict[str, Any] = {}
        if dry_run:
            params["dryRun"] = "true"
        ocm.patch(api, ocm_spec, params)

    def get_ocm_spec(
        self,
        ocm: OCMBaseClient,
        cluster: Mapping[str, Any],
        init_provision_shards: bool,
    ) -> OCMSpec:
        if init_provision_shards:
            provision_shard_id = get_provisioning_shard_id(ocm, cluster["id"])
        else:
            provision_shard_id = None

        sts = None
        oidc_endpoint_url = None
        if cluster["aws"].get("sts", None):
            sts = ROSAOcmAwsStsAttrs(
                installer_role_arn=cluster["aws"]["sts"]["role_arn"],
                support_role_arn=cluster["aws"]["sts"]["support_role_arn"],
                controlplane_role_arn=cluster["aws"]["sts"]["instance_iam_roles"].get(
                    "master_role_arn"
                ),
                worker_role_arn=cluster["aws"]["sts"]["instance_iam_roles"][
                    "worker_role_arn"
                ],
            )
            oidc_endpoint_url = cluster["aws"]["sts"]["oidc_endpoint_url"]
        account = ROSAClusterAWSAccount(
            uid=cluster["properties"]["rosa_creator_arn"].split(":")[4],
            rosa=ROSAOcmAwsAttrs(
                creator_role_arn=cluster["properties"]["rosa_creator_arn"],
                sts=sts,
            ),
        )

        spec = ROSAClusterSpec(
            product=cluster["product"]["id"],
            account=account,
            id=cluster["id"],
            external_id=cluster.get("external_id"),
            provider=cluster["cloud_provider"]["id"],
            region=cluster["region"]["id"],
            channel=cluster["version"]["channel_group"],
            version=cluster["version"]["raw_id"],
            multi_az=cluster["multi_az"],
            private=cluster["api"]["listening"] == "internal",
            disable_user_workload_monitoring=cluster[
                "disable_user_workload_monitoring"
            ],
            provision_shard_id=provision_shard_id,
            subnet_ids=cluster["aws"].get("subnet_ids"),
            availability_zones=cluster["nodes"].get("availability_zones"),
            hypershift=cluster["hypershift"]["enabled"],
            oidc_endpoint_url=oidc_endpoint_url,
        )

        network = OCMClusterNetwork(
            type=cluster["network"].get("type") or "OVNKubernetes",
            vpc=cluster["network"]["machine_cidr"],
            service=cluster["network"]["service_cidr"],
            pod=cluster["network"]["pod_cidr"],
        )

        ocm_spec = OCMSpec(
            # Hosted control plane clusters can reach a Ready State without having the console
            # Endpoint
            console_url=cluster.get("console", {}).get("url", ""),
            server_url=cluster["api"]["url"],
            domain=cluster["dns"]["base_domain"],
            spec=spec,
            network=network,
        )

        return ocm_spec

    def _get_update_cluster_spec(
        self, update_spec: Mapping[str, Any]
    ) -> dict[str, Any]:
        ocm_spec: dict[str, Any] = {}

        disable_uwm = update_spec.get(SPEC_ATTR_DISABLE_UWM)
        if disable_uwm is not None:
            ocm_spec["disable_user_workload_monitoring"] = disable_uwm

        return ocm_spec


def build_product_portfolio(
    rosa_session_builder: RosaSessionBuilder | None = None,
) -> OCMProductPortfolio:
    return OCMProductPortfolio(
        products={
            OCM_PRODUCT_OSD: OCMProductOsd(),
            OCM_PRODUCT_ROSA: OCMProductRosa(rosa_session_builder),
            OCM_PRODUCT_HYPERSHIFT: OCMProductHypershift(rosa_session_builder),
        }
    )


class OCMProductPortfolio(BaseModel, arbitrary_types_allowed=True):
    products: dict[str, OCMProduct]

    @property
    def product_names(self) -> list[str]:
        return list(self.products.keys())

    def get_product_impl(
        self, product: str, hypershift: bool | None = False
    ) -> OCMProduct:
        if hypershift:
            return self.products[OCM_PRODUCT_HYPERSHIFT]
        return self.products[product]

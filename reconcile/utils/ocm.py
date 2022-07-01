from __future__ import annotations
from abc import abstractmethod
import functools
import logging
import re
from typing import Any, Optional, Tuple, Union, Mapping


import reconcile.utils.aws_helper as awsh
import requests
from reconcile.utils.secret_reader import SecretReader
from sretoolbox.utils import retry

from reconcile.ocm.types import (
    OCMSpec,
    OSDClusterSpec,
    OCMClusterAutoscale,
    OCMClusterNetwork,
    ROSAClusterSpec,
)


STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_DELETING = "deleting"

AMS_API_BASE = "/api/accounts_mgmt"
CS_API_BASE = "/api/clusters_mgmt"
KAS_API_BASE = "/api/kafkas_mgmt"

MACHINE_POOL_DESIRED_KEYS = {"id", "instance_type", "replicas", "labels", "taints"}
UPGRADE_CHANNELS = {"stable", "fast", "candidate"}
UPGRADE_POLICY_DESIRED_KEYS = {"id", "schedule_type", "schedule", "next_run", "version"}
ROUTER_DESIRED_KEYS = {"id", "listening", "dns_name", "route_selectors"}
AUTOSCALE_DESIRED_KEYS = {"min_replicas", "max_replicas"}
CLUSTER_ADDON_DESIRED_KEYS = {"id", "parameters"}

DISABLE_UWM_ATTR = "disable_user_workload_monitoring"
BYTES_IN_GIGABYTE = 1024**3
REQUEST_TIMEOUT_SEC = 60


SPEC_ATTR_DISABLE_UWM = "disable_user_workload_monitoring"
SPEC_ATTR_AUTOSCALE = "autoscale"
SPEC_ATTR_INSTANCE_TYPE = "instance_type"
SPEC_ATTR_PRIVATE = "private"
SPEC_ATTR_CHANNEL = "channel"
SPEC_ATTR_NODES = "nodes"
SPEC_ATTR_LOAD_BALANCERS = "load_balancers"
SPEC_ATTR_STORAGE = "storage"
SPEC_ATTR_ID = "id"
SPEC_ATTR_EXTERNAL_ID = "external_id"
SPEC_ATTR_PROVISION_SHARD_ID = "provision_shard_id"
SPEC_ATTR_VERSION = "version"
SPEC_ATTR_INITIAL_VERSION = "initial_version"
SPEC_ATTR_MULTI_AZ = "multi_az"

SPEC_ATTR_NETWORK = "network"

SPEC_ATTR_CONSOLE_URL = "consoleUrl"
SPEC_ATTR_SERVER_URL = "serverUrl"
SPEC_ATTR_ELBFQDN = "elbFQDN"
SPEC_ATTR_PATH = "path"

OCM_PRODUCT_OSD = "osd"
OCM_PRODCUT_ROSA = "rosa"


class OCMProduct:

    ALLOWED_SPEC_UPDATE_FIELDS: set[str]
    EXCLUDED_SPEC_FIELDS: set[str]

    @staticmethod
    @abstractmethod
    def create_cluster(ocm: OCM, name: str, cluster: OCMSpec, dry_run: bool):
        pass

    @staticmethod
    @abstractmethod
    def update_cluster(ocm: OCM, cluster_name: str, update_spec: Mapping[str, Any]):
        pass

    @staticmethod
    @abstractmethod
    def get_ocm_spec(
        ocm: OCM, cluster: Mapping[str, Any], init_provision_shards: bool
    ) -> OCMSpec:
        pass


class OCMProductOsd(OCMProduct):
    ALLOWED_SPEC_UPDATE_FIELDS = {
        SPEC_ATTR_INSTANCE_TYPE,
        SPEC_ATTR_STORAGE,
        SPEC_ATTR_LOAD_BALANCERS,
        SPEC_ATTR_PRIVATE,
        SPEC_ATTR_CHANNEL,
        SPEC_ATTR_AUTOSCALE,
        SPEC_ATTR_NODES,
        SPEC_ATTR_DISABLE_UWM,
    }

    EXCLUDED_SPEC_FIELDS = {
        SPEC_ATTR_ID,
        SPEC_ATTR_EXTERNAL_ID,
        SPEC_ATTR_PROVISION_SHARD_ID,
        SPEC_ATTR_VERSION,
        SPEC_ATTR_INITIAL_VERSION,
    }

    @staticmethod
    def create_cluster(ocm: OCM, name: str, cluster: OCMSpec, dry_run: bool):
        ocm_spec = OCMProductOsd._get_create_cluster_spec(name, cluster)
        api = f"{CS_API_BASE}/v1/clusters"
        params = {}
        if dry_run:
            params["dryRun"] = "true"

        ocm._post(api, ocm_spec, params)

    @staticmethod
    def update_cluster(ocm: OCM, cluster_name: str, update_spec: Mapping[str, Any]):
        ocm_spec = OCMProductOsd._get_update_cluster_spec(update_spec)
        cluster_id = ocm.cluster_ids.get(cluster_name)
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}"
        params: dict[str, Any] = {}
        ocm._patch(api, ocm_spec, params)

    @staticmethod
    def get_ocm_spec(
        ocm: OCM, cluster: Mapping[str, Any], init_provision_shards: bool
    ) -> OCMSpec:
        if init_provision_shards:
            provision_shard_id = ocm.get_provision_shard(cluster["id"])["id"]
        else:
            provision_shard_id = None

        autoscale = cluster["nodes"].get("autoscale_compute")
        autoscale_spec = (
            OCMClusterAutoscale(
                max_replicas=autoscale.get("max_replicas"),
                min_replicas=autoscale.get("min_replicas"),
            )
            if autoscale
            else None
        )

        spec = OSDClusterSpec(
            product=cluster["product"]["id"],
            id=cluster["id"],
            external_id=cluster["external_id"],
            provider=cluster["cloud_provider"]["id"],
            region=cluster["region"]["id"],
            channel=cluster["version"]["channel_group"],
            version=cluster["version"]["raw_id"],
            multi_az=cluster["multi_az"],
            instance_type=cluster["nodes"]["compute_machine_type"]["id"],
            storage=cluster["storage_quota"]["value"] // BYTES_IN_GIGABYTE,
            load_balancers=cluster["load_balancer_quota"],
            private=cluster["api"]["listening"] == "internal",
            disable_user_workload_monitoring=cluster[
                "disable_user_workload_monitoring"
            ],
            provision_shard_id=provision_shard_id,
            nodes=cluster["nodes"].get("compute"),
            autoscale=autoscale_spec,
        )

        network = OCMClusterNetwork(
            type=cluster["network"].get("type") or "OpenShiftSDN",
            vpc=cluster["network"]["machine_cidr"],
            service=cluster["network"]["service_cidr"],
            pod=cluster["network"]["pod_cidr"],
        )

        ocm_spec = OCMSpec(
            console_url=cluster["console"]["url"],
            server_url=cluster["api"]["url"],
            domain=cluster["dns"]["base_domain"],
            spec=spec,
            network=network,
        )

        return ocm_spec

    @staticmethod
    def _get_create_cluster_spec(cluster_name: str, cluster: OCMSpec) -> dict[str, Any]:
        ocm_spec: dict[str, Any] = {
            "name": cluster_name,
            "cloud_provider": {"id": cluster.spec.provider},
            "region": {"id": cluster.spec.region},
            "version": {
                "id": f"openshift-v{cluster.spec.initial_version}",
                "channel_group": cluster.spec.channel,
            },
            "multi_az": cluster.spec.multi_az,
            "nodes": {"compute_machine_type": {"id": cluster.spec.instance_type}},
            "network": {
                "type": cluster.network.type or "OpenShiftSDN",
                "machine_cidr": cluster.network.vpc,
                "service_cidr": cluster.network.service,
                "pod_cidr": cluster.network.pod,
            },
            "api": {"listening": "internal" if cluster.spec.private else "external"},
            "disable_user_workload_monitoring": cluster.spec.disable_user_workload_monitoring
            or True,
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

        autoscale = cluster.spec.autoscale
        if autoscale is not None:
            ocm_spec["nodes"]["autoscale_compute"] = autoscale.dict()
        else:
            ocm_spec["nodes"]["compute"] = cluster.spec.nodes
        return ocm_spec

    @staticmethod
    def _get_update_cluster_spec(update_spec: Mapping[str, Any]) -> dict[str, Any]:
        ocm_spec: dict[str, Any] = {}

        instance_type = update_spec.get("instance_type")
        if instance_type is not None:
            ocm_spec["nodes"] = {"compute_machine_type": {"id": instance_type}}

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

        autoscale = update_spec.get("autoscale")
        if autoscale is not None:
            ocm_spec["nodes"] = {"autoscale_compute": autoscale}

        nodes = update_spec.get("nodes")
        if nodes:
            ocm_spec["nodes"] = {"compute": update_spec["nodes"]}

        disable_uwm = update_spec.get("disable_user_workload_monitoring")
        if disable_uwm is not None:
            ocm_spec["disable_user_workload_monitoring"] = disable_uwm

        return ocm_spec


class OCMProductRosa(OCMProduct):
    ALLOWED_SPEC_UPDATE_FIELDS = {
        SPEC_ATTR_INSTANCE_TYPE,
        SPEC_ATTR_CHANNEL,
        SPEC_ATTR_AUTOSCALE,
        SPEC_ATTR_NODES,
        SPEC_ATTR_DISABLE_UWM,
    }

    EXCLUDED_SPEC_FIELDS = {
        SPEC_ATTR_ID,
        SPEC_ATTR_EXTERNAL_ID,
        SPEC_ATTR_PROVISION_SHARD_ID,
        SPEC_ATTR_VERSION,
        SPEC_ATTR_INITIAL_VERSION,
    }

    @staticmethod
    def create_cluster(ocm: OCM, name: str, cluster: OCMSpec, dry_run: bool):
        raise NotImplementedError("create_cluster not implemeneted for ROSA")

    @staticmethod
    def update_cluster(ocm: OCM, cluster_name: str, update_spec: Mapping[str, Any]):
        raise NotImplementedError("update_cluster not implemeneted for ROSA")

    @staticmethod
    def get_ocm_spec(
        ocm: OCM, cluster: Mapping[str, Any], init_provision_shards: bool
    ) -> OCMSpec:
        if init_provision_shards:
            provision_shard_id = ocm.get_provision_shard(cluster["id"])["id"]
        else:
            provision_shard_id = None

        autoscale = cluster["nodes"].get("autoscale_compute")
        autoscale_spec = (
            OCMClusterAutoscale(
                max_replicas=autoscale.get("max_replicas"),
                min_replicas=autoscale.get("min_replicas"),
            )
            if autoscale
            else None
        )

        spec = ROSAClusterSpec(
            product=cluster["product"]["id"],
            id=cluster["id"],
            external_id=cluster["external_id"],
            provider=cluster["cloud_provider"]["id"],
            region=cluster["region"]["id"],
            channel=cluster["version"]["channel_group"],
            version=cluster["version"]["raw_id"],
            multi_az=cluster["multi_az"],
            instance_type=cluster["nodes"]["compute_machine_type"]["id"],
            private=cluster["api"]["listening"] == "internal",
            disable_user_workload_monitoring=cluster[
                "disable_user_workload_monitoring"
            ],
            provision_shard_id=provision_shard_id,
            nodes=cluster["nodes"].get("compute"),
            autoscale=autoscale_spec,
        )

        network = OCMClusterNetwork(
            type=cluster["network"].get("type") or "OpenShiftSDN",
            vpc=cluster["network"]["machine_cidr"],
            service=cluster["network"]["service_cidr"],
            pod=cluster["network"]["pod_cidr"],
        )

        ocm_spec = OCMSpec(
            console_url=cluster["console"]["url"],
            server_url=cluster["api"]["url"],
            domain=cluster["dns"]["base_domain"],
            spec=spec,
            network=network,
        )

        return ocm_spec

    @staticmethod
    def _get_create_cluster_spec(cluster_name: str, cluster: OCMSpec) -> dict[str, Any]:
        ocm_spec: dict[str, Any] = {
            "name": cluster_name,
            "cloud_provider": {"id": cluster.spec.provider},
            "region": {"id": cluster.spec.region},
            "version": {
                "id": f"openshift-v{cluster.spec.initial_version}",
                "channel_group": cluster.spec.channel,
            },
            "multi_az": cluster.spec.multi_az,
            "nodes": {"compute_machine_type": {"id": cluster.spec.instance_type}},
            "network": {
                "type": cluster.network.type or "OpenShiftSDN",
                "machine_cidr": cluster.network.vpc,
                "service_cidr": cluster.network.service,
                "pod_cidr": cluster.network.pod,
            },
            "api": {"listening": "internal" if cluster.spec.private else "external"},
            "disable_user_workload_monitoring": cluster.spec.disable_user_workload_monitoring
            or True,
        }

        provision_shard_id = cluster.spec.provision_shard_id
        if provision_shard_id:
            ocm_spec.setdefault("properties", {})
            ocm_spec["properties"]["provision_shard_id"] = provision_shard_id

        autoscale = cluster.spec.autoscale
        if autoscale is not None:
            ocm_spec["nodes"]["autoscale_compute"] = autoscale.dict()
        else:
            ocm_spec["nodes"]["compute"] = cluster.spec.nodes
        return ocm_spec

    @staticmethod
    def _get_update_cluster_spec(update_spec: Mapping[str, Any]) -> dict[str, Any]:
        ocm_spec: dict[str, Any] = {}

        instance_type = update_spec.get("instance_type")
        if instance_type is not None:
            ocm_spec["nodes"] = {"compute_machine_type": {"id": instance_type}}

        private = update_spec.get("private")
        if private is not None:
            ocm_spec["api"] = {"listening": "internal" if private else "external"}

        channel = update_spec.get("channel")
        if channel is not None:
            ocm_spec["version"] = {"channel_group": channel}

        autoscale = update_spec.get("autoscale")
        if autoscale is not None:
            ocm_spec["nodes"] = {"autoscale_compute": autoscale}

        nodes = update_spec.get("nodes")
        if nodes:
            ocm_spec["nodes"] = {"compute": update_spec["nodes"]}

        disable_uwm = update_spec.get("disable_user_workload_monitoring")
        if disable_uwm is not None:
            ocm_spec["disable_user_workload_monitoring"] = disable_uwm

        return ocm_spec


OCM_PRODUCTS_IMPL = {
    OCM_PRODUCT_OSD: OCMProductOsd,
    OCM_PRODCUT_ROSA: OCMProductRosa,
}


class OCM:  # pylint: disable=too-many-public-methods
    """
    OCM is an instance of OpenShift Cluster Manager.

    :param name: OCM instance name
    :param url: OCM instance URL
    :param access_token_client_id: client-id to get access token
    :param access_token_url: URL to get access token from
    :param offline_token: Long lived offline token used to get access token
    :param init_provision_shards: should initiate provision shards
    :param init_addons: should initiate addons
    :param blocked_versions: versions to block upgrades for
    :type url: string
    :type access_token_client_id: string
    :type access_token_url: string
    :type offline_token: string
    :type init_provision_shards: bool
    :type init_addons: bool
    :type init_version_gates: bool
    :type blocked_version: list
    """

    def __init__(
        self,
        name,
        url,
        access_token_client_id,
        access_token_url,
        offline_token,
        init_provision_shards=False,
        init_addons=False,
        init_version_gates=False,
        blocked_versions=None,
    ):
        """Initiates access token and gets clusters information."""
        self.name = name
        self.url = url
        self.access_token = ""
        self.access_token_client_id = access_token_client_id
        self.access_token_url = access_token_url
        self.offline_token = offline_token
        self._session = requests.Session()
        self._init_access_token()
        self._init_request_headers()
        self._init_clusters(init_provision_shards=init_provision_shards)

        if init_addons:
            self._init_addons()

        self._init_blocked_versions(blocked_versions)

        self.init_version_gates = init_version_gates
        self.version_gates = []
        if init_version_gates:
            self._init_version_gates()

        # Setup caches on the instance itself to avoid leak
        # https://stackoverflow.com/questions/33672412/python-functools-lru-cache-with-class-methods-release-object
        # using @lru_cache decorators on methods would lek AWSApi instances
        # since the cache keeps a reference to self.
        self.get_aws_infrastructure_access_role_grants = functools.lru_cache()(
            self.get_aws_infrastructure_access_role_grants
        )

    @retry()
    def _init_access_token(self):
        data = {
            "grant_type": "refresh_token",
            "client_id": self.access_token_client_id,
            "refresh_token": self.offline_token,
        }
        r = self._session.post(
            self.access_token_url, data=data, timeout=REQUEST_TIMEOUT_SEC
        )
        r.raise_for_status()
        self.access_token = r.json().get("access_token")

    def _init_request_headers(self):
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.access_token}",
                "accept": "application/json",
            }
        )

    @staticmethod
    def _ready_for_app_interface(cluster: dict[str, Any]) -> bool:
        return (
            cluster["managed"]
            and cluster["state"] == STATUS_READY
            and cluster["product"]["id"] in OCM_PRODUCTS_IMPL
        )

    def _init_clusters(self, init_provision_shards):
        api = f"{CS_API_BASE}/v1/clusters"
        clusters = self._get_json(api)["items"]
        self.cluster_ids = {c["name"]: c["id"] for c in clusters}

        self.clusters: dict[str, OCMSpec] = {}
        self.not_ready_clusters: set[str] = set()

        for c in clusters:
            cluster_name = c["name"]
            if self._ready_for_app_interface(c):
                ocm_spec = self._get_cluster_ocm_spec(c, init_provision_shards)
                self.clusters[cluster_name] = ocm_spec
            else:
                self.not_ready_clusters.add(cluster_name)

    def _get_cluster_ocm_spec(
        self, cluster: Mapping[str, Any], init_provision_shards: bool
    ) -> OCMSpec:

        product = cluster["product"]["id"]
        impl = OCM_PRODUCTS_IMPL[product]
        spec = impl.get_ocm_spec(self, cluster, init_provision_shards)
        return spec

    def create_cluster(self, name: str, cluster: OCMSpec, dry_run: bool):
        impl = OCM_PRODUCTS_IMPL[cluster.spec.product]
        impl.create_cluster(self, name, cluster, dry_run)

    def update_cluster(
        self, cluster_name: str, update_spec: Mapping[str, Any], dry_run=False
    ):
        cluster = self.clusters[cluster_name]
        impl = OCM_PRODUCTS_IMPL[cluster.spec.product]
        impl.update_cluster(self, cluster_name, update_spec)

    def get_group_if_exists(self, cluster, group_id):
        """Returns a list of users in a group in a cluster.
        If the group does not exist, None will be returned.

        :param cluster: cluster name
        :param group_id: group name

        :type cluster: string
        :type group_id: string
        """
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return None
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/groups"
        groups = self._get_json(api)["items"]
        if group_id not in [g["id"] for g in groups]:
            return None

        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/" + f"groups/{group_id}/users"
        users = self._get_json(api).get("items", [])
        return {"users": [u["id"] for u in users]}

    def add_user_to_group(self, cluster, group_id, user):
        """
        Adds a user to a group in a cluster.

        :param cluster: cluster name
        :param group_id: group name
        :param user: user name

        :type cluster: string
        :type group_id: string
        :type user: string
        """
        cluster_id = self.cluster_ids[cluster]
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/" + f"groups/{group_id}/users"
        self._post(api, {"id": user})

    def del_user_from_group(self, cluster, group_id, user_id):
        """Deletes a user from a group in a cluster.

        :param cluster: cluster name
        :param group_id: group name
        :param user: user name

        :type cluster: string
        :type group_id: string
        :type user: string
        """
        cluster_id = self.cluster_ids[cluster]
        api = (
            f"{CS_API_BASE}/v1/clusters/{cluster_id}/"
            + f"groups/{group_id}/users/{user_id}"
        )
        self._delete(api)

    def get_cluster_aws_account_id(self, cluster: str) -> Optional[str]:
        """Returns the AWS account id of the cluster.
        Since there is no direct API to get this information,
        we hack our way by relying on existing role grants
        and parsing out the console_url from one of them.
        """
        role_grants = self.get_aws_infrastructure_access_role_grants(cluster)
        # filter for role grants with a console url
        role_grants = [r for r in role_grants if r[-1]]
        if not role_grants:
            return None
        switch_role_link = role_grants[0][-1]
        return awsh.get_account_uid_from_role_link(switch_role_link)

    # pylint: disable=method-hidden
    def get_aws_infrastructure_access_role_grants(self, cluster):
        """Returns a list of AWS users (ARN, access level)
        who have AWS infrastructure access in a cluster.

        :param cluster: cluster name

        :type cluster: string
        """
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return []
        api = (
            f"{CS_API_BASE}/v1/clusters/{cluster_id}/"
            + "aws_infrastructure_access_role_grants"
        )
        role_grants = self._get_json(api).get("items", [])
        return [
            (r["user_arn"], r["role"]["id"], r["state"], r["console_url"])
            for r in role_grants
        ]

    def get_aws_infrastructure_access_terraform_assume_role(
        self, cluster, tf_account_id, tf_user
    ):
        role_grants = self.get_aws_infrastructure_access_role_grants(cluster)
        user_arn = f"arn:aws:iam::{tf_account_id}:user/{tf_user}"
        for arn, role_id, _, console_url in role_grants:
            if arn != user_arn:
                continue
            if role_id != "network-mgmt":
                continue
            # split out only the url arguments
            account_and_role = console_url.split("?")[1]
            account, role = account_and_role.split("&")
            role_account_id = account.replace("account=", "")
            role_name = role.replace("roleName=", "")
            return f"arn:aws:iam::{role_account_id}:role/{role_name}"

    def add_user_to_aws_infrastructure_access_role_grants(
        self, cluster, user_arn, access_level
    ):
        """
        Adds a user to AWS infrastructure access in a cluster.

        :param cluster: cluster name
        :param user_arn: user ARN
        :param access_level: access level (read-only or network-mgmt)

        :type cluster: string
        :type user_arn: string
        :type access_level: string
        """
        cluster_id = self.cluster_ids[cluster]
        api = (
            f"{CS_API_BASE}/v1/clusters/{cluster_id}/"
            + "aws_infrastructure_access_role_grants"
        )
        self._post(api, {"user_arn": user_arn, "role": {"id": access_level}})

    def del_user_from_aws_infrastructure_access_role_grants(
        self, cluster, user_arn, access_level
    ):
        """
        Deletes a user from AWS infrastructure access in a cluster.

        :param cluster: cluster name
        :param user_arn: user ARN
        :param access_level: access level (read-only or network-mgmt)

        :type cluster: string
        :type user_arn: string
        :type access_level: string
        """
        cluster_id = self.cluster_ids[cluster]
        api = (
            f"{CS_API_BASE}/v1/clusters/{cluster_id}/"
            + "aws_infrastructure_access_role_grants"
        )
        role_grants = self._get_json(api).get("items", [])
        for rg in role_grants:
            if rg["user_arn"] != user_arn:
                continue
            if rg["role"]["id"] != access_level:
                continue
            aws_infrastructure_access_role_grant_id = rg["id"]
            self._delete(f"{api}/{aws_infrastructure_access_role_grant_id}")

    def get_github_idp_teams(self, cluster):
        """Returns a list of details of GitHub IDP providers

        :param cluster: cluster name

        :type cluster: string
        """
        result_idps = []
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return result_idps
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/identity_providers"
        idps = self._get_json(api).get("items")
        if not idps:
            return result_idps

        for idp in idps:
            if idp["type"] != "GithubIdentityProvider":
                continue
            if idp["mapping_method"] != "claim":
                continue
            idp_name = idp["name"]
            idp_github = idp["github"]

            item = {
                "cluster": cluster,
                "name": idp_name,
                "client_id": idp_github["client_id"],
                "teams": idp_github.get("teams"),
            }
            result_idps.append(item)
        return result_idps

    def create_github_idp_teams(self, spec):
        """Creates a new GitHub IDP

        :param cluster: cluster name
        :param spec: required information for idp creation

        :type cluster: string
        :type spec: dictionary
        """
        cluster = spec["cluster"]
        cluster_id = self.cluster_ids[cluster]
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/identity_providers"
        payload = {
            "type": "GithubIdentityProvider",
            "mapping_method": "claim",
            "name": spec["name"],
            "github": {
                "client_id": spec["client_id"],
                "client_secret": spec["client_secret"],
                "teams": spec["teams"],
            },
        }
        self._post(api, payload)

    def get_external_configuration_labels(self, cluster):
        """Returns details of External Configurations

        :param cluster: cluster name

        :type cluster: string
        """
        results = {}
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return results
        api = (
            f"{CS_API_BASE}/v1/clusters/{cluster_id}" + "/external_configuration/labels"
        )
        items = self._get_json(api).get("items")
        if not items:
            return results

        for item in items:
            key = item["key"]
            value = item["value"]
            results[key] = value

        return results

    def create_external_configuration_label(self, cluster, label):
        """Creates a new External Configuration label

        :param cluster: cluster name
        :param label: key and value for new label

        :type cluster: string
        :type label: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        api = (
            f"{CS_API_BASE}/v1/clusters/{cluster_id}" + "/external_configuration/labels"
        )
        self._post(api, label)

    def delete_external_configuration_label(self, cluster, label):
        """Deletes an existing External Configuration label

        :param cluster: cluster name
        :param label:  key and value of label to delete

        :type cluster: string
        :type label: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        api = (
            f"{CS_API_BASE}/v1/clusters/{cluster_id}" + "/external_configuration/labels"
        )
        items = self._get_json(api).get("items")
        item = [item for item in items if label.items() <= item.items()]
        if not item:
            return
        label_id = item[0]["id"]
        api = (
            f"{CS_API_BASE}/v1/clusters/{cluster_id}"
            + f"/external_configuration/labels/{label_id}"
        )
        self._delete(api)

    def get_machine_pools(self, cluster):
        """Returns a list of details of Machine Pools

        :param cluster: cluster name

        :type cluster: string
        """
        results = []
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return results
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/machine_pools"
        items = self._get_json(api).get("items")
        if not items:
            return results

        for item in items:
            result = {k: v for k, v in item.items() if k in MACHINE_POOL_DESIRED_KEYS}
            results.append(result)

        return results

    def create_machine_pool(self, cluster, spec):
        """Creates a new Machine Pool

        :param cluster: cluster name
        :param spec: required information for machine pool creation

        :type cluster: string
        :type spec: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/machine_pools"
        self._post(api, spec)

    def update_machine_pool(self, cluster, spec):
        """Updates an existing Machine Pool

        :param cluster: cluster name
        :param spec: required information for machine pool update

        :type cluster: string
        :type spec: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        machine_pool_id = spec["id"]
        labels = spec.get("labels", {})
        spec["labels"] = labels
        api = (
            f"{CS_API_BASE}/v1/clusters/{cluster_id}/machine_pools/"
            + f"{machine_pool_id}"
        )
        self._patch(api, spec)

    def delete_machine_pool(self, cluster, spec):
        """Deletes an existing Machine Pool

        :param cluster: cluster name
        :param spec: required information for machine pool update

        :type cluster: string
        :type spec: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        machine_pool_id = spec["id"]
        api = (
            f"{CS_API_BASE}/v1/clusters/{cluster_id}/machine_pools/"
            + f"{machine_pool_id}"
        )
        self._delete(api)

    def version_blocked(self, version):
        """Check if a version is blocked

        Args:
            version (string): version to check

        Returns:
            bool: is version blocked
        """
        return any(re.search(b, version) for b in self.blocked_versions)

    def get_available_upgrades(self, version, channel):
        """Get available versions to upgrade from specified version
        in the specified channel

        Args:
            version (string): OpenShift version ID
            channel (string): Upgrade channel

        Raises:
            KeyError: if specified channel is not valid

        Returns:
            list: available versions to upgrade to
        """
        if channel not in UPGRADE_CHANNELS:
            raise KeyError(f"channel should be one of {UPGRADE_CHANNELS}")
        version_id = f"openshift-v{version}"
        if channel != "stable":
            version_id = f"{version_id}-{channel}"
        api = f"{CS_API_BASE}/v1/versions/{version_id}"
        return self._get_json(api).get("available_upgrades", [])

    def get_upgrade_policies(self, cluster, schedule_type=None):
        """Returns a list of details of Upgrade Policies

        :param cluster: cluster name

        :type cluster: string
        """
        results = []
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return results
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/upgrade_policies"
        items = self._get_json(api).get("items")
        if not items:
            return results

        for item in items:
            if schedule_type and item["schedule_type"] != schedule_type:
                continue
            result = {k: v for k, v in item.items() if k in UPGRADE_POLICY_DESIRED_KEYS}
            results.append(result)

        return results

    def create_upgrade_policy(self, cluster, spec):
        """Creates a new Upgrade Policy

        :param cluster: cluster name
        :param spec: required information for creation

        :type cluster: string
        :type spec: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/upgrade_policies"
        self._post(api, spec)

    def delete_upgrade_policy(self, cluster, spec):
        """Deletes an existing Upgrade Policy

        :param cluster: cluster name
        :param spec: required information for update

        :type cluster: string
        :type spec: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        upgrade_policy_id = spec["id"]
        api = (
            f"{CS_API_BASE}/v1/clusters/{cluster_id}/"
            + f"upgrade_policies/{upgrade_policy_id}"
        )
        self._delete(api)

    def get_additional_routers(self, cluster):
        """Returns a list of Additional Application Routers

        :param cluster: cluster name

        :type cluster: string
        """
        results = []
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return results
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/ingresses"
        items = self._get_json(api).get("items")
        if not items:
            return results

        for item in items:
            # filter out default router
            if item["default"]:
                continue
            result = {k: v for k, v in item.items() if k in ROUTER_DESIRED_KEYS}
            results.append(result)

        return results

    def create_additional_router(self, cluster, spec):
        """Creates a new Additional Application Router

        :param cluster: cluster name
        :param spec: required information for creation

        :type cluster: string
        :type spec: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/ingresses"
        self._post(api, spec)

    def delete_additional_router(self, cluster, spec):
        """Deletes an existing Additional Application Router

        :param cluster: cluster name
        :param spec: required information for update

        :type cluster: string
        :type spec: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        router_id = spec["id"]
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/" + f"ingresses/{router_id}"
        self._delete(api)

    def get_provision_shard(self, cluster_id):
        """Returns details of the provision shard

        :param cluster: cluster id

        :type cluster: string
        """
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/provision_shard"
        return self._get_json(api)

    @staticmethod
    def _get_autoscale(cluster):
        autoscale = cluster["nodes"].get("autoscale_compute", None)
        if autoscale is None:
            return None
        return {k: v for k, v in autoscale.items() if k in AUTOSCALE_DESIRED_KEYS}

    def get_pull_secrets(
        self,
    ):
        api = f"{AMS_API_BASE}/v1/access_token"
        return self._post(api)

    def get_kafka_clusters(self, fields=None):
        """Returns details of the Kafka clusters"""
        api = f"{KAS_API_BASE}/v1/kafkas"
        clusters = self._get_json(api)["items"]
        if fields:
            clusters = [
                {k: v for k, v in cluster.items() if k in fields}
                for cluster in clusters
            ]
        return clusters

    def get_kafka_service_accounts(self, fields=None):
        """Returns details of the Kafka service accounts"""
        results = []
        api = f"{KAS_API_BASE}/v1/service_accounts"
        service_accounts = self._get_json(api)["items"]
        for sa in service_accounts:
            sa_id = sa["id"]
            id_api = f"{api}/{sa_id}"
            sa_details = self._get_json(id_api)
            if fields:
                sa_details = {k: v for k, v in sa_details.items() if k in fields}
            results.append(sa_details)
        return results

    def create_kafka_cluster(self, data):
        """Creates (async) a Kafka cluster"""
        api = f"{KAS_API_BASE}/v1/kafkas"
        params = {"async": "true"}
        self._post(api, data, params)

    def create_kafka_service_account(self, name, fields=None):
        """Creates a Kafka service account"""
        api = f"{KAS_API_BASE}/v1/service_accounts"
        result = self._post(api, {"name": name})
        if fields:
            result = {k: v for k, v in result.items() if k in fields}
        return result

    def _init_addons(self):
        """Returns a list of Addons"""
        api = f"{CS_API_BASE}/v1/addons"
        self.addons = self._get_json(api).get("items")

    def _init_version_gates(self):
        """Returns a list of version gates"""
        if self.version_gates:
            return
        api = f"{CS_API_BASE}/v1/version_gates"
        self.version_gates = self._get_json(api).get("items")

    def get_addon(self, id):
        for addon in self.addons:
            addon_id = addon["id"]
            if id == addon_id:
                return addon
        return None

    def get_version_gates(
        self, version_prefix: str, sts_only: bool = False
    ) -> list[dict[str, Any]]:
        if not self.init_version_gates:
            self._init_version_gates()
        return [
            g
            for g in self.version_gates
            if g["version_raw_id_prefix"] == version_prefix
            and g["sts_only"] == sts_only
        ]

    def get_version_agreement(self, cluster: str) -> list[dict[str, Any]]:
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return []
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/gate_agreements"
        agreements = self._get_json(api).get("items")
        if agreements:
            return agreements
        return []

    def create_version_agreement(
        self, gate_id: str, cluster: str
    ) -> list[dict[str, Union[str, bool]]]:
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return []
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/gate_agreements"
        return self._post(api, {"version_gate": {"id": gate_id}})

    def get_cluster_addons(self, cluster):
        """Returns a list of Addons installed on a cluster

        :param cluster: cluster name

        :type cluster: string
        """
        results = []
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return results
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/addons"
        items = self._get_json(api).get("items")
        if not items:
            return results

        for item in items:
            result = {k: v for k, v in item.items() if k in CLUSTER_ADDON_DESIRED_KEYS}
            parameters = result.pop("parameters", None)
            if parameters is not None:
                result["parameters"] = parameters["items"]
            results.append(result)

        return results

    def install_addon(self, cluster, spec):
        """Installs an addon on a cluster

        :param cluster: cluster name
        :param spec: required information for installation

        :type cluster: string
        :type spec: dictionary ({'id': <addon_id>})
        """
        cluster_id = self.cluster_ids[cluster]
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/addons"
        parameters = spec.pop("parameters", None)
        data = {"addon": spec}
        if parameters is not None:
            data["parameters"] = {}
            data["parameters"]["items"] = parameters
        self._post(api, data)

    def _init_blocked_versions(self, blocked_versions):
        try:
            self.blocked_versions = set(blocked_versions)
        except TypeError:
            self.blocked_versions = set()

        for b in self.blocked_versions:
            try:
                re.compile(b)
            except re.error:
                raise TypeError(f"blocked version is not a valid regex expression: {b}")

    @retry(max_attempts=10)
    def _do_get_request(self, api: str, params: Mapping[str, str]) -> dict[str, Any]:
        r = self._session.get(
            f"{self.url}{api}",
            params=params,
            timeout=REQUEST_TIMEOUT_SEC,
        )
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _response_is_list(rs: Mapping[str, Any]) -> bool:
        return rs["kind"].endswith("List")

    def _get_json(self, api: str) -> dict[str, Any]:
        responses = []
        params = {"size": 100}
        while True:
            rs = self._do_get_request(api, params=params)
            responses.append(rs)
            if (
                self._response_is_list(rs)
                and rs.get("size", len(rs.get("items", []))) == params["size"]
            ):
                params["page"] = rs.get("page", 1) + 1
            else:
                break

        if self._response_is_list(responses[0]):
            items = []
            for resp in responses:
                items_to_add = resp.get("items")
                if items_to_add:
                    items.extend(items_to_add)
            ret_items = {
                "kind": responses[0]["kind"],
                "total": len(items),
            }
            if items:
                ret_items["items"] = items
            return ret_items
        return responses[0]

    def _post(self, api, data=None, params=None):
        r = self._session.post(
            f"{self.url}{api}", json=data, params=params, timeout=REQUEST_TIMEOUT_SEC
        )
        try:
            r.raise_for_status()
        except Exception as e:
            logging.error(r.text)
            raise e
        if r.status_code == requests.codes.no_content:
            return None
        return r.json()

    def _patch(self, api, data, params=None):
        r = self._session.patch(
            f"{self.url}{api}", json=data, params=params, timeout=REQUEST_TIMEOUT_SEC
        )
        try:
            r.raise_for_status()
        except Exception as e:
            logging.error(r.text)
            raise e

    def _delete(self, api):
        r = self._session.delete(f"{self.url}{api}", timeout=REQUEST_TIMEOUT_SEC)
        r.raise_for_status()


class OCMMap:  # pylint: disable=too-many-public-methods
    """
    OCMMap gets a GraphQL query results list as input
    and initiates a dictionary of OCM clients per OCM.

    The input must contain either 'clusters' or 'namespaces', but not both.

    In case a cluster does not have an ocm instance
    the OCM client will be initiated to False.

    :param clusters: Graphql clusters query results list
    :param namespaces: Graphql namespaces query results list
    :param integration: Name of calling integration.
                        Used to disable integrations.
    :param settings: App Interface settings
    :param init_provision_shards: should initiate provision shards
    :param init_addons: should initiate addons
    :type clusters: list
    :type namespaces: list
    :type integration: string
    :type settings: dict
    :type init_provision_shards: bool
    :type init_addons: bool
    :type init_version_gates bool
    """

    def __init__(
        self,
        clusters=None,
        namespaces=None,
        integration="",
        settings=None,
        init_provision_shards=False,
        init_addons=False,
        init_version_gates=False,
    ):
        """Initiates OCM instances for each OCM referenced in a cluster."""
        self.clusters_map = {}
        self.ocm_map = {}
        self.calling_integration = integration
        self.settings = settings

        if clusters and namespaces:
            raise KeyError("expected only one of clusters or namespaces.")
        elif clusters:
            for cluster_info in clusters:
                self.init_ocm_client(
                    cluster_info,
                    init_provision_shards,
                    init_addons,
                    init_version_gates=init_version_gates,
                )
        elif namespaces:
            for namespace_info in namespaces:
                cluster_info = namespace_info["cluster"]
                self.init_ocm_client(
                    cluster_info,
                    init_provision_shards,
                    init_addons,
                    init_version_gates=init_version_gates,
                )
        else:
            raise KeyError("expected one of clusters or namespaces.")

    def init_ocm_client(
        self, cluster_info, init_provision_shards, init_addons, init_version_gates
    ):
        """
        Initiate OCM client.
        Gets the OCM information and initiates an OCM client.
        Skip initiating OCM if it has already been initialized or if
        the current integration is disabled on it.

        :param cluster_info: Graphql cluster query result
        :param init_provision_shards: should initiate provision shards
        :param init_addons: should initiate addons

        :type cluster_info: dict
        """
        if self.cluster_disabled(cluster_info):
            return
        cluster_name = cluster_info["name"]
        ocm_info = cluster_info["ocm"]
        ocm_name = ocm_info["name"]
        # pointer from each cluster to its referenced OCM instance
        self.clusters_map[cluster_name] = ocm_name
        if self.ocm_map.get(ocm_name):
            return

        access_token_client_id = ocm_info.get("accessTokenClientId")
        access_token_url = ocm_info.get("accessTokenUrl")
        ocm_offline_token = ocm_info.get("offlineToken")
        if ocm_offline_token is None:
            self.ocm_map[ocm_name] = False
        else:
            url = ocm_info["url"]
            name = ocm_info["name"]
            secret_reader = SecretReader(settings=self.settings)
            token = secret_reader.read(ocm_offline_token)
            self.ocm_map[ocm_name] = OCM(
                name,
                url,
                access_token_client_id,
                access_token_url,
                token,
                init_provision_shards=init_provision_shards,
                init_addons=init_addons,
                blocked_versions=ocm_info.get("blockedVersions"),
                init_version_gates=init_version_gates,
            )

    def instances(self) -> list[str]:
        """Get list of OCM instance names initiated in the OCM map."""
        return self.ocm_map.keys()

    def cluster_disabled(self, cluster_info):
        """
        Checks if the calling integration is disabled in this cluster.

        :param cluster_info: Graphql cluster query result

        :type cluster_info: dict
        """
        try:
            integrations = cluster_info["disable"]["integrations"]
            if self.calling_integration.replace("_", "-") in integrations:
                return True
        except (KeyError, TypeError):
            pass

        return False

    def get(self, cluster) -> OCM:
        """
        Gets an OCM instance by cluster.

        :param cluster: cluster name

        :type cluster: string
        """
        ocm = self.clusters_map[cluster]
        return self.ocm_map.get(ocm, None)

    def clusters(self) -> list[str]:
        """Get list of cluster names initiated in the OCM map."""
        return [k for k, v in self.clusters_map.items() if v]

    def cluster_specs(self) -> Tuple[dict[str, OCMSpec], list]:
        """Get dictionary of cluster names and specs in the OCM map."""
        cluster_specs = {}
        for v in self.ocm_map.values():
            cluster_specs.update(v.clusters)

        not_ready_cluster_names = []
        for v in self.ocm_map.values():
            not_ready_cluster_names.extend(v.not_ready_clusters)
        return cluster_specs, not_ready_cluster_names

    def kafka_cluster_specs(self):
        """Get dictionary of Kafka cluster names and specs in the OCM map."""
        fields = [
            "id",
            "status",
            "cloud_provider",
            "region",
            "multi_az",
            "name",
            "bootstrap_server_host",
            "failed_reason",
        ]
        cluster_specs = []
        for ocm in self.ocm_map.values():
            clusters = ocm.get_kafka_clusters(fields=fields)
            cluster_specs.extend(clusters)
        return cluster_specs

    def kafka_service_account_specs(self):
        """Get dictionary of Kafka service account specs in the OCM map."""
        fields = ["name", "client_id"]
        service_account_specs = []
        for ocm in self.ocm_map.values():
            service_accounts = ocm.get_kafka_service_accounts(fields=fields)
            service_account_specs.extend(service_accounts)
        return service_account_specs

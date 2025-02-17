from __future__ import annotations

import functools
from collections.abc import Mapping
from typing import Any

from sretoolbox.utils import retry

import reconcile.utils.aws_helper as awsh
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.ocm.types import (
    OCMSpec,
)
from reconcile.utils.ocm.clusters import get_node_pools
from reconcile.utils.ocm.products import (
    OCMProduct,
    OCMProductPortfolio,
    build_product_portfolio,
)
from reconcile.utils.ocm_base_client import (
    OCMAPIClientConfiguration,
    OCMBaseClient,
    init_ocm_base_client,
)
from reconcile.utils.secret_reader import SecretReader

STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_DELETING = "deleting"

AMS_API_BASE = "/api/accounts_mgmt"
CS_API_BASE = "/api/clusters_mgmt"

MACHINE_POOL_DESIRED_KEYS = {
    "id",
    "instance_type",
    "replicas",
    "autoscaling",
    "labels",
    "taints",
}
UPGRADE_CHANNELS = {"stable", "fast", "candidate"}
UPGRADE_POLICY_DESIRED_KEYS = {
    "id",
    "schedule_type",
    "schedule",
    "next_run",
    "version",
    "state",
}
ADDON_UPGRADE_POLICY_DESIRED_KEYS = {
    "id",
    "addon_id",
    "schedule_type",
    "schedule",
    "next_run",
    "version",
}
ROUTER_DESIRED_KEYS = {"id", "listening", "dns_name", "route_selectors"}
CLUSTER_ADDON_DESIRED_KEYS = {"id", "parameters"}

DISABLE_UWM_ATTR = "disable_user_workload_monitoring"
CLUSTER_ADMIN_LABEL_KEY = "capability.cluster.manage_cluster_admin"
REQUEST_TIMEOUT_SEC = 60


class OCM:  # pylint: disable=too-many-public-methods
    """
    OCM is an instance of OpenShift Cluster Manager.

    :param name: OCM instance name
    :param org_id: OCM org ID
    :param ocm_env: OCM env
    :param ocm_client: the OCM API client to talk to OCM
    :param init_provision_shards: should initiate provision shards
    :param init_addons: should initiate addons
    :param init_version_gates: should initiate version gates
    :type init_provision_shards: bool
    :type init_addons: bool
    :type init_version_gates: bool
    """

    def __init__(
        self,
        name,
        org_id,
        ocm_env: str,
        ocm_client: OCMBaseClient,
        init_provision_shards=False,
        init_addons=False,
        init_version_gates=False,
        product_portfolio: OCMProductPortfolio | None = None,
    ):
        """Initiates access token and gets clusters information."""
        self.name = name
        self._ocm_client = ocm_client
        self.org_id = org_id
        self.ocm_env = ocm_env
        if product_portfolio is None:
            self.product_portfolio = build_product_portfolio()
        else:
            self.product_portfolio = product_portfolio
        self._init_clusters(init_provision_shards=init_provision_shards)

        if init_addons:
            self._init_addons()

        self.init_version_gates = init_version_gates
        self.version_gates: list[Any] = []
        if init_version_gates:
            self._init_version_gates()

        # Setup caches on the instance itself to avoid leak
        # https://stackoverflow.com/questions/33672412/python-functools-lru-cache-with-class-methods-release-object
        # using @lru_cache decorators on methods would lek AWSApi instances
        # since the cache keeps a reference to self.
        self.get_aws_infrastructure_access_role_grants = functools.lru_cache()(  # type: ignore
            self.get_aws_infrastructure_access_role_grants
        )

    @property
    def ocm_api(self) -> OCMBaseClient:
        return self._ocm_client

    def _ready_for_app_interface(self, cluster: dict[str, Any]) -> bool:
        return (
            cluster["managed"]
            and cluster["state"] == STATUS_READY
            and cluster["product"]["id"] in self.product_portfolio.product_names
        )

    def _init_clusters(self, init_provision_shards: bool):
        api = f"{CS_API_BASE}/v1/clusters"
        product_csv = ",".join([f"'{p}'" for p in self.product_portfolio.product_names])
        params = {
            "search": f"organization.id='{self.org_id}' and managed='true' and product.id in ({product_csv})"
        }
        clusters = self._get_json(api, params=params).get("items", [])
        self.cluster_ids: dict[str, str] = {c["name"]: c["id"] for c in clusters}

        self.clusters: dict[str, OCMSpec] = {}
        self.available_cluster_upgrades: dict[str, list[str]] = {}
        self.not_ready_clusters: set[str] = set()

        for c in clusters:
            cluster_name = c["name"]
            if self._ready_for_app_interface(c):
                ocm_spec = self._get_cluster_ocm_spec(c, init_provision_shards)
                self.clusters[cluster_name] = ocm_spec
                self.available_cluster_upgrades[cluster_name] = c.get(
                    "version", {}
                ).get("available_upgrades")
            else:
                self.not_ready_clusters.add(cluster_name)

    def get_product_impl(
        self, product: str, hypershift: bool | None = False
    ) -> OCMProduct:
        return self.product_portfolio.get_product_impl(product, hypershift)

    def _get_cluster_ocm_spec(
        self, cluster: Mapping[str, Any], init_provision_shards: bool
    ) -> OCMSpec:
        impl = self.get_product_impl(
            cluster["product"]["id"], cluster["hypershift"]["enabled"]
        )
        spec = impl.get_ocm_spec(self.ocm_api, cluster, init_provision_shards)
        return spec

    def create_cluster(self, name: str, cluster: OCMSpec, dry_run: bool):
        impl = self.get_product_impl(cluster.spec.product, cluster.spec.hypershift)
        impl.create_cluster(self.ocm_api, self.org_id, name, cluster, dry_run)

    def update_cluster(
        self, cluster_name: str, update_spec: Mapping[str, Any], dry_run=False
    ):
        cluster = self.clusters[cluster_name]
        cluster_id = self.cluster_ids[cluster_name]
        impl = self.get_product_impl(cluster.spec.product, cluster.spec.hypershift)
        impl.update_cluster(self.ocm_api, cluster_id, update_spec, dry_run)

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

    def get_cluster_aws_account_id(self, cluster: str) -> str | None:
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
            idp_name = idp["name"]
            idp_github = idp["github"]

            item = {
                "id": idp["id"],
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
            "mapping_method": "add",
            "name": spec["name"],
            "github": {
                "client_id": spec["client_id"],
                "client_secret": spec["client_secret"],
                "teams": spec["teams"],
            },
        }
        self._post(api, payload)

    def get_kubeconfig(self, cluster: str) -> str | None:
        """Returns the cluster credentials (kubeconfig)

        :param cluster: cluster name

        :type cluster: string
        """
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return None
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/credentials"
        return self._get_json(api).get("kubeconfig")

    def get_external_configuration_labels(self, cluster: str) -> dict[str, str]:
        """Returns details of External Configurations

        :param cluster: cluster name

        :type cluster: string
        """
        results: dict[str, str] = {}
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

    def get_node_pools(self, cluster):
        """Returns a list of details of Node Pools

        :param cluster: cluster name

        :type cluster: string
        """
        results = []
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return results

        return get_node_pools(self._ocm_client, cluster_id)

    def delete_node_pool(self, cluster, spec):
        """Deletes an existing Node Pool

        :param cluster: cluster name
        :param spec: required information for node pool update

        :type cluster: string
        :type spec: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        node_pool_id = spec["id"]
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/node_pools/" + f"{node_pool_id}"
        self._delete(api)

    def create_node_pool(self, cluster, spec):
        """Creates a new Node Pool

        :param cluster: cluster name
        :param spec: required information for node pool creation

        :type cluster: string
        :type spec: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/node_pools"
        self._post(api, spec)

    def update_node_pool(self, cluster, spec):
        """Updates an existing Node Pool

        :param cluster: cluster name
        :param spec: required information for node pool update

        :type cluster: string
        :type spec: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        node_pool_id = spec["id"]
        labels = spec.get("labels", {})
        spec["labels"] = labels
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/node_pools/" + f"{node_pool_id}"
        self._patch(api, spec)

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

    def get_cluster_addons(
        self,
        cluster: str,
        with_version: bool = False,
        required_state: str | None = None,
    ) -> list[dict[str, str]]:
        """Returns a list of Addons installed on a cluster

        :param cluster: cluster name
        :param with_version: include addon version
        :param required_state: add search parameter to filter by specified state

        :type cluster: string
        """
        results: list[dict[str, str]] = []
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return results
        api = f"{CS_API_BASE}/v1/clusters/{cluster_id}/addons"

        p: dict[str, Any] | None = None
        if required_state:
            p = {"search": f"state='{required_state}'"}

        items = self._get_json(api, params=p).get("items")
        if not items:
            return results

        for item in items:
            result = {k: v for k, v in item.items() if k in CLUSTER_ADDON_DESIRED_KEYS}
            parameters = result.pop("parameters", None)
            if parameters is not None:
                result["parameters"] = parameters["items"]
            if with_version:
                result["version"] = item["addon_version"]["id"]
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

    @retry(max_attempts=10)
    def _do_get_request(self, api: str, params: Mapping[str, str]) -> dict[str, Any]:
        return self._ocm_client.get(
            api_path=api,
            params=params,
        )

    @staticmethod
    def _response_is_list(rs: Mapping[str, Any]) -> bool:
        return rs["kind"].endswith("List")

    def _get_json(
        self, api: str, params: dict[str, Any] | None = None, page_size: int = 100
    ) -> dict[str, Any]:
        responses = []
        if not params:
            params = {}
        params["size"] = page_size
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
        return self._ocm_client.post(
            api_path=api,
            data=data,
            params=params,
        )

    def _patch(self, api, data, params=None):
        return self._ocm_client.patch(
            api_path=api,
            data=data,
            params=params,
        )

    def _delete(self, api):
        return self._ocm_client.delete(
            api_path=api,
        )


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
        ocms=None,
        integration="",
        settings=None,
        init_provision_shards=False,
        init_addons=False,
        init_version_gates=False,
        product_portfolio: OCMProductPortfolio | None = None,
    ) -> None:
        """Initiates OCM instances for each OCM referenced in a cluster."""
        self.clusters_map: dict[str, str] = {}
        self.ocm_map: dict[str, OCM] = {}
        self.calling_integration = integration
        self.settings = settings

        inputs = [i for i in [clusters, namespaces, ocms] if i]
        if len(inputs) > 1:
            raise KeyError("expected only one of clusters, namespaces or ocm.")
        if clusters:
            for cluster_info in clusters:
                self.init_ocm_client_from_cluster(
                    cluster_info,
                    init_provision_shards,
                    init_addons,
                    init_version_gates=init_version_gates,
                    product_portfolio=product_portfolio,
                )
        elif namespaces:
            for namespace_info in namespaces:
                cluster_info = namespace_info["cluster"]
                self.init_ocm_client_from_cluster(
                    cluster_info,
                    init_provision_shards,
                    init_addons,
                    init_version_gates=init_version_gates,
                    product_portfolio=product_portfolio,
                )
        elif ocms:
            for ocm in ocms:
                self.init_ocm_client(
                    ocm,
                    init_provision_shards,
                    init_addons,
                    init_version_gates=init_version_gates,
                    product_portfolio=product_portfolio,
                )
        else:
            raise KeyError("expected one of clusters, namespaces or ocm.")

    def __getitem__(self, ocm_name: str) -> OCM:
        return self.ocm_map[ocm_name]

    def init_ocm_client_from_cluster(
        self,
        cluster_info,
        init_provision_shards,
        init_addons,
        init_version_gates,
        product_portfolio: OCMProductPortfolio | None = None,
    ):
        if self.cluster_disabled(cluster_info):
            return
        cluster_name = cluster_info["name"]
        ocm_info = cluster_info["ocm"]
        ocm_name = ocm_info["name"]
        # pointer from each cluster to its referenced OCM instance
        self.clusters_map[cluster_name] = ocm_name

        if ocm_name not in self.ocm_map:
            self.init_ocm_client(
                ocm_info,
                init_provision_shards,
                init_addons,
                init_version_gates,
                product_portfolio,
            )

    def init_ocm_client(
        self,
        ocm_info,
        init_provision_shards,
        init_addons,
        init_version_gates,
        product_portfolio: OCMProductPortfolio | None = None,
    ):
        """
        Initiate OCM client.
        Gets the OCM information and initiates an OCM client.
        Skip initiating OCM if it has already been initialized or if
        the current integration is disabled on it.

        :param ocm_info: Graphql ocm query result
        :param init_provision_shards: should initiate provision shards
        :param init_addons: should initiate addons

        :type cluster_info: dict
        """
        ocm_name = ocm_info["name"]
        ocm_environment = ocm_info["environment"]
        access_token_client_id = (
            ocm_info.get("accessTokenClientId")
            or ocm_environment["accessTokenClientId"]
        )
        access_token_url = (
            ocm_info.get("accessTokenUrl") or ocm_environment["accessTokenUrl"]
        )
        access_token_client_secret = (
            ocm_info.get("accessTokenClientSecret")
            or ocm_environment["accessTokenClientSecret"]
        )
        url = ocm_environment["url"]
        org_id = ocm_info["orgId"]
        name = ocm_info["name"]
        ocm_client = init_ocm_base_client(
            cfg=OCMAPIClientConfiguration(
                url=url,
                access_token_url=access_token_url,
                access_token_client_id=access_token_client_id,
                access_token_client_secret=VaultSecret(**access_token_client_secret),
            ),
            secret_reader=SecretReader(settings=self.settings),
        )

        self.ocm_map[ocm_name] = OCM(
            name,
            org_id,
            ocm_environment["name"],
            ocm_client,
            init_provision_shards=init_provision_shards,
            init_addons=init_addons,
            init_version_gates=init_version_gates,
            product_portfolio=product_portfolio,
        )

    def instances(self) -> list[str]:
        """Get list of OCM instance names initiated in the OCM map."""
        return list(self.ocm_map.keys())

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
        return self.ocm_map[ocm]

    def clusters(self) -> list[str]:
        """Get list of cluster names initiated in the OCM map."""
        return [k for k, v in self.clusters_map.items() if v]

    def cluster_specs(self) -> tuple[dict[str, OCMSpec], list[str]]:
        """Get dictionary of cluster names and specs in the OCM map."""
        cluster_specs = {}
        for v in self.ocm_map.values():
            cluster_specs.update(v.clusters)

        not_ready_cluster_names: list[str] = []
        for v in self.ocm_map.values():
            not_ready_cluster_names.extend(v.not_ready_clusters)
        return cluster_specs, not_ready_cluster_names

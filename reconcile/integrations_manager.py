import json
import logging
import os
import sys
from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import (
    Iterable,
    Mapping,
    MutableMapping,
)
from dataclasses import dataclass
from typing import (
    Any,
    Optional,
)

from github import Github

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.github_org import (
    GH_BASE_URL,
    get_default_config,
)
from reconcile.status import ExitCodes
from reconcile.utils import helm
from reconcile.utils.defer import defer
from reconcile.utils.oc import oc_process
from reconcile.utils.openshift_resource import (
    OpenshiftResource,
    ResourceInventory,
)
from reconcile.utils.runtime.meta import IntegrationMeta
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "integrations-manager"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class ShardingStrategy(ABC):
    @abstractmethod
    def build_integration_shards(
        self, integration_meta: IntegrationMeta, spec: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        pass


@dataclass
class IntegrationShardManager:

    strategies: dict[str, ShardingStrategy]
    integration_runtime_meta: dict[str, IntegrationMeta]

    def build_integration_shards(
        self, integration: str, spec: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        sharding_strategy = spec.get("shardingStrategy") or "static"
        if sharding_strategy in self.strategies:
            integration_meta = self.integration_runtime_meta.get(integration)
            if not integration_meta:
                # workaround until we can get metadata for non cli.py based integrations
                integration_meta = IntegrationMeta(
                    name=integration, args=[], short_help=None
                )
            shards = self.strategies[sharding_strategy].build_integration_shards(
                integration_meta, spec
            )

            # add the extra args of the integrations pr check spec to each shard
            extra_args = spec["extraArgs"]
            if extra_args:
                for s in shards:
                    s["extra_args"] = f"{extra_args} {s['extra_args']}".strip()
            return shards
        else:
            raise ValueError(f"unsupported sharding strategy '{sharding_strategy}'")


class StaticShardingStrategy(ShardingStrategy):
    def build_integration_shards(
        self, _: IntegrationMeta, spec: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        shards = spec.get("shards") or 1
        return [
            {
                "shard_id": str(s),
                "shards": str(shards),
                "shard_name_suffix": f"-{s}" if shards > 1 else "",
                "extra_args": "",
            }
            for s in range(0, shards)
        ]


class AWSAccountShardManager(ShardingStrategy):
    def __init__(self, aws_accounts: list[dict[str, Any]]):
        self.aws_accounts = aws_accounts

    def build_integration_shards(
        self, integration_meta: IntegrationMeta, _: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        if "--account-name" in integration_meta.args:
            filtered_accounts = self._aws_accounts_for_integration(
                integration_meta.name
            )
            return [
                {
                    "shard_key": account["name"],
                    "shard_name_suffix": f"-{account['name']}"
                    if len(filtered_accounts) > 1
                    else "",
                    "extra_args": f"--account-name {account['name']}",
                }
                for account in filtered_accounts
            ]
        else:
            raise ValueError(
                f"integration {integration_meta.name} does not support arg --account-name required by the per-aws-account sharding strategy"
            )

    def _aws_accounts_for_integration(self, integration: str) -> list[dict[str, Any]]:
        return [
            a
            for a in self.aws_accounts
            if a["disable"] is None
            or "integrations" not in a["disable"]
            or integration not in (a["disable"]["integrations"] or [])
        ]


@dataclass
class IntegrationShardSpecOverride:

    imageRef: str
    awsAccount: Mapping[str, str]

    def update_shard_if_matched(self, shard: MutableMapping[str, Any]):
        if shard["shard_key"] == self.awsAccount["name"]:
            shard["imageRef"] = self.imageRef


def construct_values_file(
    integration_specs: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "integrations": [],
        "cronjobs": [],
    }
    for spec in integration_specs:
        key = "cronjobs" if spec.get("cron") else "integrations"
        values[key].append(spec)
    return values


def values_set_shard_specifics(
    values: Mapping[str, Any], integration_overrides: Mapping[str, Any]
):
    for integration in values["integrations"]:
        for shard in integration.get("shard_specs", []):
            for override in integration_overrides.get(integration["name"], []):
                if "shard_key" in shard:
                    override.update_shard_if_matched(shard)


def get_image_tag_from_ref(ref: str) -> str:
    settings = queries.get_app_interface_settings()
    gh_token = get_default_config()["token"]
    github = Github(gh_token, base_url=GH_BASE_URL)
    commit_sha = github.get_repo("app-sre/qontract-reconcile").get_commit(sha=ref).sha
    return commit_sha[: settings["hashLength"]]


def collect_parameters(
    template: Mapping[str, Any],
    environment: Mapping[str, Any],
    image_tag_from_ref: Optional[Mapping[str, str]],
) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    environment_parameters = environment.get("parameters")
    if environment_parameters:
        parameters.update(json.loads(environment_parameters))
    template_parameters = template.get("parameters")
    if template_parameters:
        tp_env_vars = {
            p["name"]: os.environ[p["name"]]
            for p in template_parameters
            if p["name"] in os.environ
        }
        parameters.update(tp_env_vars)
    if image_tag_from_ref:
        for e, r in image_tag_from_ref.items():
            if environment["name"] == e:
                parameters["IMAGE_TAG"] = get_image_tag_from_ref(r)

    return parameters


def construct_oc_resources(
    namespace_info: Mapping[str, Any],
    image_tag_from_ref: Optional[Mapping[str, str]],
    integration_overrides: Mapping[str, list[IntegrationShardSpecOverride]],
) -> list[OpenshiftResource]:
    values = construct_values_file(namespace_info["integration_specs"])
    values_set_shard_specifics(values, integration_overrides)
    template = helm.template(values)

    parameters = collect_parameters(
        template, namespace_info["environment"], image_tag_from_ref
    )
    resources = oc_process(template, parameters)
    return [
        OpenshiftResource(
            r,
            QONTRACT_INTEGRATION,
            QONTRACT_INTEGRATION_VERSION,
            error_details=r.get("metadata", {}).get("name"),
        )
        for r in resources
    ]


def initialize_shard_specs(
    namespaces: Iterable[Mapping[str, Any]], shard_manager: IntegrationShardManager
) -> None:
    for namespace_info in namespaces:
        for spec in namespace_info["integration_specs"]:
            spec["shard_specs"] = shard_manager.build_integration_shards(
                spec["name"], spec
            )


def fetch_desired_state(
    namespaces: Iterable[Mapping[str, Any]],
    ri: ResourceInventory,
    image_tag_from_ref: Optional[Mapping[str, str]],
    environment_override_mapping: Mapping[
        str, Mapping[str, list[IntegrationShardSpecOverride]]
    ],
) -> None:
    for namespace_info in namespaces:
        namespace = namespace_info["name"]
        environment_name = namespace_info["environment"]["name"]
        cluster = namespace_info["cluster"]["name"]
        oc_resources = construct_oc_resources(
            namespace_info,
            image_tag_from_ref,
            environment_override_mapping[environment_name],
        )
        for r in oc_resources:
            ri.add_desired(cluster, namespace, r.kind, r.name, r)


def collect_namespaces(
    integrations: Iterable[Mapping[str, Any]], environment_name: str
) -> list[dict[str, Any]]:
    unique_namespaces: dict[str, dict[str, Any]] = {}
    for i in integrations:
        managed = i.get("managed") or []
        for m in managed:
            ns = m["namespace"]
            if environment_name and ns["environment"]["name"] != environment_name:
                continue
            ns = unique_namespaces.setdefault(ns["path"], ns)
            spec = m["spec"]
            spec["name"] = i["name"]
            # create a backref from namespace to integration spec
            ns.setdefault("integration_specs", []).append(spec)

    return list(unique_namespaces.values())


def collect_managed_integrations(
    integrations: Iterable[Mapping[str, Any]], namespaces: Iterable[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    # Filter integrations, return a list of integrations with key managed,
    # that are deployed to the passed in namespaces
    environments = {ns["environment"]["name"] for ns in namespaces}

    filtered_integrations = []
    for managed_integration in [i for i in integrations if i.get("managed")]:
        for instance in managed_integration["managed"]:
            environment_name = instance["namespace"]["environment"]["name"]
            if environment_name in environments:
                filtered_integrations.append(instance)
    return filtered_integrations


def initialize_environment_override_mapping(
    namespaces: list[dict[str, Any]], integrations: list[Mapping[str, Any]]
) -> Mapping[str, Mapping[str, list[IntegrationShardSpecOverride]]]:
    environment_override_mapping: Mapping[str, Any] = {
        namespace["environment"]["name"]: {
            integration["name"]: [] for integration in namespace["integration_specs"]
        }
        for namespace in namespaces
    }
    for instance in integrations:
        environment_name = instance["namespace"]["environment"]["name"]
        name = instance["spec"]["name"]
        overrides = instance.get("shardSpecOverride", [])
        if overrides:
            for override in overrides:
                environment_override_mapping[environment_name][name].append(
                    (IntegrationShardSpecOverride(**override))
                )

    return environment_override_mapping


@defer
def run(
    dry_run,
    environment_name,
    integration_runtime_meta: dict[str, IntegrationMeta],
    thread_pool_size=10,
    internal=None,
    use_jump_host=True,
    image_tag_from_ref=None,
    defer=None,
):
    # Beware, environment_name can be empty! It's optional to set it!
    # If not set, all environments should be considered.
    all_integrations = queries.get_integrations(managed=True)
    namespaces = collect_namespaces(all_integrations, environment_name)
    managed_integrations = collect_managed_integrations(all_integrations, namespaces)
    environment_override_mapping = initialize_environment_override_mapping(
        namespaces, managed_integrations
    )

    if not namespaces:
        logging.debug("Nothing to do, exiting.")
        sys.exit(ExitCodes.SUCCESS)

    ri, oc_map = ob.fetch_current_state(
        namespaces=namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=["Deployment", "StatefulSet", "CronJob", "Service"],
        internal=internal,
        use_jump_host=use_jump_host,
    )
    defer(oc_map.cleanup)
    shard_manager = IntegrationShardManager(
        strategies={
            "static": StaticShardingStrategy(),
            "per-aws-account": AWSAccountShardManager(queries.get_aws_accounts()),
        },
        integration_runtime_meta=integration_runtime_meta,
    )
    initialize_shard_specs(namespaces, shard_manager)
    fetch_desired_state(
        namespaces, ri, image_tag_from_ref, environment_override_mapping
    )
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    if ri.has_error_registered():
        sys.exit(ExitCodes.ERROR)

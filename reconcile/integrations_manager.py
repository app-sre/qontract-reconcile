import logging
import os
import sys
from collections.abc import (
    Iterable,
    Mapping,
    Sequence,
)
from typing import (
    Any,
    Optional,
)

from github import Github
from pydantic import BaseModel

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.github_org import (
    GH_BASE_URL,
    get_default_config,
)
from reconcile.gql_definitions.integrations import integrations
from reconcile.gql_definitions.integrations.integrations import (
    EnvironmentV1,
    IntegrationManagedV1,
    IntegrationSpecV1,
    IntegrationV1,
    NamespaceV1,
)
from reconcile.status import ExitCodes
from reconcile.utils import (
    gql,
    helm,
)
from reconcile.utils.defer import defer
from reconcile.utils.oc import oc_process
from reconcile.utils.openshift_resource import (
    OpenshiftResource,
    ResourceInventory,
)
from reconcile.utils.runtime.meta import IntegrationMeta
from reconcile.utils.runtime.sharding import (
    AWSAccountShardingStrategy,
    CloudflareDnsZoneShardingStrategy,
    IntegrationShardManager,
    OCMOrganizationShardingStrategy,
    OpenshiftClusterShardingStrategy,
    ShardSpec,
    StaticShardingStrategy,
)
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "integrations-manager"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

IMAGE_DEFAULT = "quay.io/app-sre/qontract-reconcile"
UPSTREAM_DEFAULT = "https://github.com/app-sre/qontract-reconcile"

INTEGRATION_UPSTREAM_REPOS_PARAM = "INTEGRATION_UPSTREAM_REPOS"


def get_image_tag_from_ref(ref: str, upstream: str) -> str:
    gh_prefix = "https://github.com/"
    if upstream.startswith(gh_prefix):
        upstream = upstream[len(gh_prefix) :]
    settings = queries.get_app_interface_settings()
    gh_token = get_default_config()["token"]
    github = Github(gh_token, base_url=GH_BASE_URL)
    commit_sha = github.get_repo(upstream).get_commit(sha=ref).sha
    return commit_sha[: settings["hashLength"]]


def collect_parameters(
    template: Mapping[str, Any],
    environment: EnvironmentV1,
    upstream: str,
    image: str,
    image_tag_from_ref: Optional[Mapping[str, str]],
) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    if environment.parameters:
        parameters.update(environment.parameters)

    template_parameters = template.get("parameters")
    if template_parameters:
        tp_env_vars = {
            p["name"]: os.environ[p["name"]]
            for p in template_parameters
            if p["name"] in os.environ
        }
        parameters.update(tp_env_vars)

    # overwrite image and imtage tag from environment parameter
    for upstream_config in (environment.parameters or {}).get(
        INTEGRATION_UPSTREAM_REPOS_PARAM, []
    ):
        if upstream_config.get("repo") == upstream:
            parameters["IMAGE_TAG"] = get_image_tag_from_ref(
                upstream_config.get("ref"), upstream
            )

    # overwrite image tag from cli parameters
    if image_tag_from_ref:
        for e, r in image_tag_from_ref.items():
            if environment.name == e:
                parameters["IMAGE_TAG"] = get_image_tag_from_ref(r, upstream)
    if image:
        parameters["IMAGE"] = image
    return parameters


class HelmIntegrationSpec(IntegrationSpecV1):
    """Integration specs used by the Helm chart does not exactly
    match the gql IntegrationSpec. This class extends the Ingtegration spec with the
    missing attributes"""

    name: str
    shard_specs: Sequence[ShardSpec] = []


def _build_helm_integration_spec(
    integration_name: str,
    managed: IntegrationManagedV1,
    shard_manager: IntegrationShardManager,
):
    integration_spec = managed.spec.dict(by_alias=True)
    shard_specs = shard_manager.build_integration_shards(integration_name, managed)
    his = HelmIntegrationSpec(
        **integration_spec, name=integration_name, shard_specs=shard_specs
    )
    return his


class HelmValues(BaseModel):
    integrations: list[HelmIntegrationSpec] = []
    cronjobs: list[HelmIntegrationSpec] = []


def build_helm_values(specs: Iterable[HelmIntegrationSpec]) -> dict:
    values = HelmValues()
    for s in specs:
        if s.cron:
            values.cronjobs.append(s)
        else:
            values.integrations.append(s)

    return values.dict(exclude_none=True, by_alias=True)


class IntegrationsEnvironment(BaseModel):
    namespace: NamespaceV1
    integration_specs: list[HelmIntegrationSpec] = []


def collect_integrations_environment(
    integrations: Iterable[IntegrationV1],
    environment_name: str,
    shard_manager: IntegrationShardManager,
) -> list[IntegrationsEnvironment]:
    int_envs: dict[str, IntegrationsEnvironment] = {}

    for i in integrations:
        for m in i.managed or []:
            ns = m.namespace
            if environment_name and ns.environment.name != environment_name:
                continue

            env = int_envs.setdefault(
                ns.path,
                IntegrationsEnvironment(namespace=ns),
            )
            his = _build_helm_integration_spec(i.name, m, shard_manager)
            env.integration_specs.append(his)

    return list(int_envs.values())


def construct_oc_resources(
    integrations_environment: IntegrationsEnvironment,
    upstream: str,
    image: str,
    image_tag_from_ref: Optional[Mapping[str, str]],
) -> list[OpenshiftResource]:
    # Generate the openshift template with the helm chart. The resulting template
    # contains all the integrations in the environment
    values = build_helm_values(integrations_environment.integration_specs)
    template = helm.template(values)

    parameters = collect_parameters(
        template,
        integrations_environment.namespace.environment,
        upstream,
        image,
        image_tag_from_ref,
    )

    resources = oc_process(template, parameters)
    return [
        OpenshiftResource(
            r,
            QONTRACT_INTEGRATION,
            QONTRACT_INTEGRATION_VERSION,
            error_details=r.get("metadata", {}).get("name"),
            caller_name=upstream,
        )
        for r in resources
    ]


def fetch_desired_state(
    integrations_environments: Iterable[IntegrationsEnvironment],
    ri: ResourceInventory,
    upstream: str,
    image: str,
    image_tag_from_ref: Optional[Mapping[str, str]],
):
    for ie in integrations_environments:
        oc_resources = construct_oc_resources(ie, upstream, image, image_tag_from_ref)
        for r in oc_resources:
            ri.add_desired(
                ie.namespace.cluster.name, ie.namespace.name, r.kind, r.name, r
            )


def filter_integrations(
    integrations: Iterable[IntegrationV1], upstream: Optional[str] = None
) -> list[IntegrationV1]:
    if upstream is None:
        return list(integrations)

    return [i for i in integrations if i.upstream == upstream]


@defer
def run(
    dry_run,
    environment_name,
    integration_runtime_meta: dict[str, IntegrationMeta],
    thread_pool_size=10,
    internal=None,
    use_jump_host=True,
    image_tag_from_ref=None,
    upstream=None,
    image=None,
    defer=None,
):
    # Beware, environment_name can be empty! It's optional to set it!
    # If not set, all environments should be considered.

    all_integrations = (
        integrations.query(query_func=gql.get_api().query).integrations or []
    )

    filtered_integrations = filter_integrations(all_integrations, upstream)

    shard_manager = IntegrationShardManager(
        strategies={
            StaticShardingStrategy.IDENTIFIER: StaticShardingStrategy(),
            AWSAccountShardingStrategy.IDENTIFIER: AWSAccountShardingStrategy(),
            OpenshiftClusterShardingStrategy.IDENTIFIER: OpenshiftClusterShardingStrategy(),
            CloudflareDnsZoneShardingStrategy.IDENTIFIER: CloudflareDnsZoneShardingStrategy(),
            OCMOrganizationShardingStrategy.IDENTIFIER: OCMOrganizationShardingStrategy(),
        },
        integration_runtime_meta=integration_runtime_meta,
    )

    integration_environments = collect_integrations_environment(
        filtered_integrations, environment_name, shard_manager
    )

    if not integration_environments:
        logging.debug("Nothing to do, exiting.")
        sys.exit(ExitCodes.SUCCESS)

    fetch_args = {
        "namespaces": [
            ie.namespace.dict(by_alias=True) for ie in integration_environments
        ],
        "thread_pool_size": thread_pool_size,
        "integration": QONTRACT_INTEGRATION,
        "integration_version": QONTRACT_INTEGRATION_VERSION,
        "override_managed_types": ["Deployment", "StatefulSet", "CronJob", "Service"],
        "internal": internal,
        "use_jump_host": use_jump_host,
    }

    if not image:
        image = IMAGE_DEFAULT

    if upstream:
        use_upstream = True
        fetch_args["caller"] = upstream
    else:
        # Not set to fetch_args on purpose, fallback for cases where caller is not yet set
        use_upstream = False
        upstream = UPSTREAM_DEFAULT

    ri, oc_map = ob.fetch_current_state(**fetch_args)
    defer(oc_map.cleanup)

    fetch_desired_state(
        integration_environments, ri, upstream, image, image_tag_from_ref
    )

    ob.publish_metrics(ri, QONTRACT_INTEGRATION)
    if use_upstream:
        ob.realize_data(dry_run, oc_map, ri, thread_pool_size, caller=upstream)
    else:
        ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    if ri.has_error_registered():
        sys.exit(ExitCodes.ERROR)

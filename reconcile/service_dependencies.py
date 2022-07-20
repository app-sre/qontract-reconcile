import sys
import logging
from typing import Any, Mapping
from reconcile.gql_queries.service_dependencies import service_dependencies
from reconcile.gql_queries.service_dependencies.service_dependencies import (
    AppV1,
    ServiceDependenciesQueryData,
)

from reconcile.utils import gql
from reconcile import queries


QONTRACT_INTEGRATION = "service-dependencies"


def get_dependency_names(dependency_map: Mapping[Any, Any], dep_type: str) -> list[str]:
    dep_names = []
    for dm in dependency_map:
        if dm["type"] != dep_type:
            continue
        for service in dm["services"]:
            dep_names.append(service["name"])
    return dep_names


def get_desired_dependency_names(
    app: AppV1, dependency_map: Mapping[Any, Any]
) -> set[str]:
    required_dep_names = set()

    code_components = app.code_components
    if code_components:
        gitlab_urls = [cc for cc in code_components if "gitlab" in cc.url]
        if gitlab_urls:
            required_dep_names.update(get_dependency_names(dependency_map, "gitlab"))
        github_urls = [cc for cc in code_components if "github.com" in cc.url]
        if github_urls:
            required_dep_names.update(get_dependency_names(dependency_map, "github"))

    jenkins_configs = app.jenkins_configs
    if jenkins_configs:
        instances = {jc.instance.name for jc in jenkins_configs}
        for instance in instances:
            required_dep_names.update(get_dependency_names(dependency_map, instance))

    saas_files = app.saas_files or []
    tekton_pipelines = [
        s for s in saas_files if s.pipelines_provider.provider == "tekton"
    ]
    if tekton_pipelines:
        # All our tekton SaaS deployment pipelines are in appsrep05ue1,
        # hence openshift is a required dependency.
        required_dep_names.update(get_dependency_names(dependency_map, "openshift"))

    quay_repos = app.quay_repos
    if quay_repos:
        required_dep_names.update(get_dependency_names(dependency_map, "quay"))

    namespaces = app.namespaces
    if namespaces:
        required_dep_names.update(get_dependency_names(dependency_map, "openshift"))
        er_namespaces = [n for n in namespaces if n.managed_external_resources]
        for ern in er_namespaces:
            providers: set[str] = set()
            if ern.managed_external_resources and ern.external_resources:
                providers = {res.provider for res in ern.external_resources}
            for p in providers:
                required_dep_names.update(get_dependency_names(dependency_map, p))
        kafka_namespaces = [n for n in namespaces if n.kafka_cluster]
        if kafka_namespaces:
            required_dep_names.update(get_dependency_names(dependency_map, "kafka"))

    return required_dep_names


def run(dry_run):
    settings = queries.get_app_interface_settings()
    dependency_map = settings.get("dependencies")
    if not dependency_map:
        sys.exit()

    gqlapi = gql.get_api()
    apps: dict[Any, Any] = gqlapi.query(service_dependencies.QUERY)
    query_data: ServiceDependenciesQueryData = ServiceDependenciesQueryData(**apps)

    error = False
    for app in query_data.apps or []:
        app_name = app.name
        app_deps = app.dependencies
        current_deps = [a.name for a in app_deps] if app_deps else []
        desired_deps = get_desired_dependency_names(app, dependency_map)

        missing_deps = list(desired_deps.difference(current_deps))
        if missing_deps:
            error = True
            msg = f"App '{app_name}' has missing dependencies: {missing_deps}"
            logging.error(msg)

        redundant_deps = list(set(current_deps).difference(desired_deps))
        if redundant_deps:
            msg = f"App '{app_name}' has redundant dependencies: " + f"{redundant_deps}"
            logging.debug(msg)

    if error:
        sys.exit(1)

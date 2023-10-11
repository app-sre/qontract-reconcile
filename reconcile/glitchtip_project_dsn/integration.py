import logging
from collections.abc import (
    Callable,
    Iterable,
)
from typing import (
    Any,
    Optional,
)

from sretoolbox.utils import threaded

import reconcile.openshift_base as ob
from reconcile.gql_definitions.glitchtip.glitchtip_instance import (
    DEFINITION as GLITCHTIP_INSTANCE_DEFINITION,
)
from reconcile.gql_definitions.glitchtip.glitchtip_instance import (
    query as glitchtip_instance_query,
)
from reconcile.gql_definitions.glitchtip.glitchtip_project import (
    DEFINITION as GLITCHTIP_PROJECT_DEFINITION,
)
from reconcile.gql_definitions.glitchtip.glitchtip_project import GlitchtipProjectsV1
from reconcile.gql_definitions.glitchtip.glitchtip_project import (
    query as glitchtip_project_query,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.glitchtip_settings import get_glitchtip_settings
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.glitchtip import GlitchtipClient
from reconcile.utils.glitchtip.models import (
    Organization,
    Project,
    ProjectKey,
)
from reconcile.utils.oc_map import (
    OCMap,
    init_oc_map_from_namespaces,
)
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "glitchtip-project-dsn"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

LABELS = {
    "app.kubernetes.io/name": "glitchtip-project-dsn",
    "app.kubernetes.io/part-of": "glitchtip",
    "app.kubernetes.io/managed-by": "qontract-reconcile",
}


def glitchtip_project_dsn_secret(project: Project, key: ProjectKey) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": f"{project.slug}-dsn",
            "labels": LABELS,
        },
        "type": "Opaque",
        "stringData": {
            "dsn": key.dsn,
            "security_endpoint": key.security_endpoint,
        },
    }


def fetch_current_state(
    project: GlitchtipProjectsV1,
    oc_map: OCMap,
    ri: ResourceInventory,
) -> None:
    for namespace in project.namespaces:
        oc = oc_map.get_cluster(namespace.cluster.name)
        if not oc.project_exists(namespace.name):
            logging.info(
                f"{namespace.cluster.name}/{namespace.name}: Namespace does not exist (yet). Skipping for now!"
            )
            continue

        for item in oc.get_items(
            kind="Secret",
            namespace=namespace.name,
            labels=LABELS,
        ):
            openshift_resource = OR(
                body=item,
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
            )
            ri.initialize_resource_type(
                cluster=namespace.cluster.name,
                namespace=namespace.name,
                resource_type=openshift_resource.kind,
            )
            ri.add_current(
                cluster=namespace.cluster.name,
                namespace=namespace.name,
                resource_type="Secret",
                name=openshift_resource.name,
                value=openshift_resource,
            )


def fetch_desired_state(
    glitchtip_projects: Iterable[GlitchtipProjectsV1],
    ri: ResourceInventory,
    glitchtip_client: GlitchtipClient,
) -> None:
    for glitchtip_project in glitchtip_projects:
        org = Organization(name=glitchtip_project.organization.name)
        project = Project(name=glitchtip_project.name)
        if project not in glitchtip_client.projects(organization_slug=org.slug):
            logging.info(f"Project {project.name} does not exist (yet). Skipping.")
            continue
        key = glitchtip_client.project_key(
            organization_slug=org.slug, project_slug=project.slug
        )
        secret = glitchtip_project_dsn_secret(project, key)
        openshift_resource = OR(
            body=secret,
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
        )
        for namespace in glitchtip_project.namespaces:
            ri.initialize_resource_type(
                cluster=namespace.cluster.name,
                namespace=namespace.name,
                resource_type=openshift_resource.kind,
            )
            ri.add_desired(
                cluster=namespace.cluster.name,
                namespace=namespace.name,
                resource_type="Secret",
                name=openshift_resource.name,
                value=openshift_resource,
            )


def projects_query(query_func: Callable) -> list[GlitchtipProjectsV1]:
    glitchtip_projects = []
    for project in (
        glitchtip_project_query(query_func=query_func).glitchtip_projects or []
    ):
        # remove namespaces marked for deletion or where the integration is disabled
        project.namespaces = [
            ns
            for ns in project.namespaces
            if not ns.delete
            and integration_is_enabled(QONTRACT_INTEGRATION, ns.cluster)
        ]
        if not project.namespaces:
            # skip projects with no namespaces
            continue
        glitchtip_projects.append(project)

    return glitchtip_projects


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    internal: Optional[bool] = None,
    use_jump_host: bool = True,
    instance: Optional[str] = None,
    defer: Optional[Callable] = None,
) -> None:
    # settings
    vault_settings = get_app_interface_vault_settings()
    read_timeout, max_retries, _ = get_glitchtip_settings()

    # data
    gqlapi = gql.get_api()
    glitchtip_instances = glitchtip_instance_query(query_func=gqlapi.query).instances
    glitchtip_projects = projects_query(query_func=gqlapi.query)

    # APIs
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    oc_map = init_oc_map_from_namespaces(
        namespaces=[
            namespace
            for project in glitchtip_projects
            for namespace in project.namespaces
        ],
        secret_reader=secret_reader,
        integration=QONTRACT_INTEGRATION,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
        internal=internal,
    )
    if defer:
        defer(oc_map.cleanup)

    ri = ResourceInventory()

    for glitchtip_instance in glitchtip_instances:
        if instance and glitchtip_instance.name != instance:
            continue

        glitchtip_client = GlitchtipClient(
            host=glitchtip_instance.console_url,
            token=secret_reader.read_secret(glitchtip_instance.automation_token),
            read_timeout=read_timeout,
            max_retries=max_retries,
        )
        threaded.run(
            fetch_current_state,
            [
                p
                for p in glitchtip_projects
                if p.organization.instance.name == glitchtip_instance.name
            ],
            thread_pool_size,
            oc_map=oc_map,
            ri=ri,
        )
        fetch_desired_state(
            glitchtip_projects=[
                p
                for p in glitchtip_projects
                if p.organization.instance.name == glitchtip_instance.name
            ],
            ri=ri,
            glitchtip_client=glitchtip_client,
        )

    ob.publish_metrics(ri, QONTRACT_INTEGRATION)
    # create/update/delete all secrets
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    gqlapi = gql.get_api()
    return {
        "projects": gqlapi.query(GLITCHTIP_PROJECT_DEFINITION)["glitchtip_projects"],
        "instances": gqlapi.query(GLITCHTIP_INSTANCE_DEFINITION)["instances"],
    }

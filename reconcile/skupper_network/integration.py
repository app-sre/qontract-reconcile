import logging
import sys
from collections.abc import (
    Callable,
    Iterable,
)
from typing import Any

import jinja2
import yaml
from sretoolbox.utils import threaded

from reconcile.gql_definitions.skupper_network.skupper_networks import SkupperNetworkV1
from reconcile.gql_definitions.skupper_network.skupper_networks import (
    query as skupper_networks_query,
)
from reconcile.skupper_network import reconciler
from reconcile.skupper_network.models import SkupperSite
from reconcile.skupper_network.site_controller import get_site_controller
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.oc_map import (
    OCMap,
    init_oc_map_from_namespaces,
)
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "skupper-network"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)
SITE_CONTROLLER_LABELS = {
    "app": "skupper-site-controller",
    "managed-by": "qontract-reconcile",
}
CONFIG_NAME = "skupper-site"


class SkupperNetworkExcpetion(Exception):
    """Base exception for Skupper Network integration."""


def load_site_controller_template(
    path: str, variables: dict[str, str]
) -> dict[str, Any]:
    """Fetches a yaml resource from qontract-server and parses it"""
    resource = gql.get_api().get_resource(path)
    try:
        body = jinja2.Template(
            resource["content"], undefined=jinja2.StrictUndefined
        ).render(variables)
    except jinja2.exceptions.UndefinedError as e:
        raise SkupperNetworkExcpetion(
            f"Failed to render template {path}: {e.message}"
        ) from None
    return yaml.safe_load(body)


def compile_skupper_sites(
    skupper_networks: Iterable[SkupperNetworkV1],
) -> list[SkupperSite]:
    """Compile the list of skupper sites to be created, updated or deleted."""
    sites: list[SkupperSite] = []
    for skupper_network in skupper_networks:
        network_sites: list[SkupperSite] = []

        for ns in skupper_network.namespaces:
            if not ns.skupper_site:
                # make mypy happy
                continue

            if not integration_is_enabled(QONTRACT_INTEGRATION, ns.cluster):
                # integration is disabled for this cluster
                continue

            site_controller_objects = []
            for tmpl in (
                ns.skupper_site.site_controller_templates
                or skupper_network.site_controller_templates
            ):
                tmpl_vars = tmpl.variables or {}
                tmpl_vars["resource"] = {"namespace": ns.dict(by_alias=True)}

                site_controller_objects.append(
                    load_site_controller_template(tmpl.path, tmpl_vars)
                )

            # inject integration labels
            for obj in site_controller_objects:
                obj["metadata"].setdefault("labels", {}).update(SITE_CONTROLLER_LABELS)

            # create a skupper site with the skupper network defaults overridden by the namespace site config and our own defaults
            network_sites.append(
                SkupperSite(
                    name=f"{skupper_network.identifier}-{ns.cluster.name}-{ns.name}",
                    site_controller_objects=site_controller_objects,
                    namespace=ns,
                    # delete skupper site if the skupper site is marked for deletion or the namespace is marked for deletion
                    delete=bool(ns.skupper_site.delete or ns.delete),
                )
            )

        # create skupper site connections; iterate over sorted list of sites to ensure deterministic site connections
        for site in sorted(network_sites, reverse=True):
            site.compute_connected_sites(network_sites)

        # check that all sites are connected
        # we don't support skupper installations with just one site
        for site in network_sites:
            if site.is_island(network_sites):
                raise SkupperNetworkExcpetion(
                    f"{site}: Site is not connected to any other skupper site in the network."
                )

        sites += network_sites
    return sites


def fetch_current_state(
    site: SkupperSite,
    oc_map: OCMap,
    ri: ResourceInventory,
    integration_managed_kinds: Iterable[str],
) -> None:
    """Populate current openshift site state in resource inventory"""
    oc = oc_map.get_cluster(site.cluster.name)

    for kind in integration_managed_kinds:
        for item in oc.get_items(
            kind=kind,
            namespace=site.namespace.name,
            labels=SITE_CONTROLLER_LABELS,
        ):
            openshift_resource = OR(
                body=item,
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
            )
            ri.initialize_resource_type(
                cluster=site.cluster.name,
                namespace=site.namespace.name,
                resource_type=openshift_resource.kind_and_group,
            )
            ri.add_current(
                cluster=site.cluster.name,
                namespace=site.namespace.name,
                resource_type=kind,
                name=openshift_resource.name,
                value=openshift_resource,
            )


def fetch_desired_state(
    ri: ResourceInventory, skupper_sites: Iterable[SkupperSite]
) -> set[str]:
    """Fetch desired state of skupper resources in ResourceInventory"""
    integration_managed_kinds = set()
    for site in skupper_sites:
        sc = get_site_controller(site)
        for resource in sc.resources:
            openshift_resource = OR(
                body=resource,
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
            )
            integration_managed_kinds.add(openshift_resource.kind_and_group)
            # only add desired state if not deleting
            if not site.delete:
                ri.initialize_resource_type(
                    cluster=site.cluster.name,
                    namespace=site.namespace.name,
                    resource_type=openshift_resource.kind_and_group,
                )
                ri.add_desired(
                    cluster=site.cluster.name,
                    namespace=site.namespace.name,
                    resource_type=openshift_resource.kind_and_group,
                    name=openshift_resource.name,
                    value=openshift_resource,
                )
    return integration_managed_kinds


def skupper_site_config_changes(ri: ResourceInventory) -> bool:
    """Check if skupper site config has changes"""
    changes = False
    for cluster, ns, resource_type, resource in ri:
        if resource_type != "ConfigMap":
            continue

        if (
            resource["current"]
            and CONFIG_NAME in resource["current"]
            and CONFIG_NAME in resource["desired"]
        ):
            current = resource["current"][CONFIG_NAME].body["data"]
            desired = resource["desired"][CONFIG_NAME].body["data"]
            if current != desired:
                changes = True
                logging.error(f"{cluster}/{ns}: Skupper site config has changed")
    return changes


def act(
    oc_map: OCMap,
    ri: ResourceInventory,
    dry_run: bool,
    thread_pool_size: int,
    skupper_sites: Iterable[SkupperSite],
    integration_managed_kinds: Iterable[str],
) -> None:
    """Realize all skupper resources and create skupper site connections."""
    # skupper-site config map updates are not supported yet
    # https://github.com/skupperproject/skupper/issues/58
    # to change the skupper site configuration, the skupper site must be deleted and recreated
    if skupper_site_config_changes(ri):
        logging.error(
            "skupper-site config changes detected. Please delete and recreate the affected skupper site(s)!"
        )
        sys.exit(1)

    # create/update/delete skupper resources
    reconciler.reconcile(
        oc_map=oc_map,
        ri=ri,
        dry_run=dry_run,
        thread_pool_size=thread_pool_size,
        skupper_sites=skupper_sites,
        integration_managed_kinds=integration_managed_kinds,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        labels=SITE_CONTROLLER_LABELS,
    )


def get_skupper_networks(query_func: Callable) -> list[SkupperNetworkV1]:
    data = skupper_networks_query(query_func)
    return data.skupper_networks or []


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    internal: bool | None = None,
    use_jump_host: bool = True,
    defer: Callable | None = None,
) -> None:
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    gqlapi = gql.get_api()

    # data query
    skupper_networks = get_skupper_networks(gqlapi.query)
    if not skupper_networks:
        logging.debug("No skupper networks found. Exiting...")
        return
    skupper_sites = compile_skupper_sites(skupper_networks)
    if not skupper_sites:
        logging.debug("No skupper sites found. Exiting...")
        return

    # APIs
    oc_map = init_oc_map_from_namespaces(
        namespaces=[site.namespace for site in skupper_sites],
        secret_reader=secret_reader,
        integration=QONTRACT_INTEGRATION,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
        internal=internal,
    )
    if defer:
        defer(oc_map.cleanup)
    ri = ResourceInventory()

    # run
    integration_managed_kinds = fetch_desired_state(ri=ri, skupper_sites=skupper_sites)
    threaded.run(
        fetch_current_state,
        skupper_sites,
        thread_pool_size,
        oc_map=oc_map,
        ri=ri,
        integration_managed_kinds=integration_managed_kinds,
    )
    act(
        oc_map=oc_map,
        ri=ri,
        dry_run=dry_run,
        thread_pool_size=thread_pool_size,
        skupper_sites=skupper_sites,
        integration_managed_kinds=integration_managed_kinds,
    )


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    gqlapi = gql.get_api()
    skupper_networks = get_skupper_networks(gqlapi.query)
    return {
        "skupper_sites": [
            site.dict() for site in compile_skupper_sites(skupper_networks)
        ],
    }

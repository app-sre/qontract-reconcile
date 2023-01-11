import logging
import sys
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
from reconcile import queries
from reconcile.gql_definitions.skupper_network.skupper_networks import SkupperNetworkV1
from reconcile.gql_definitions.skupper_network.skupper_networks import (
    query as skupper_networks_query,
)
from reconcile.skupper_network.models import (
    SkupperConfig,
    SkupperSite,
)
from reconcile.skupper_network.site_controller import CONFIG_NAME
from reconcile.skupper_network.site_controller import LABELS as SITE_CONTROLLER_LABELS
from reconcile.skupper_network.site_controller import (
    is_usable_connection_token,
    site_config,
    site_controller_deployment,
    site_controller_role,
    site_controller_role_binding,
    site_controller_service_account,
    site_token,
)
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.oc import OC_Map
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "skupper-network"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class SkupperNetworkExcpetion(Exception):
    """Base exception for Skupper Network integration."""

    pass


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

            edge = ns.cluster.internal if ns.cluster.internal else False
            if skupper_network.site_config_defaults.edge is not None:
                edge = skupper_network.site_config_defaults.edge
            if ns.skupper_site.config and ns.skupper_site.config.edge is not None:
                edge = ns.skupper_site.config.edge

            # create a skupper site with the skupper network defaults overridden by the namespace site config and our own defaults
            network_sites.append(
                SkupperSite(
                    namespace=ns,
                    skupper_site_controller=skupper_network.site_config_defaults.skupper_site_controller,
                    # delete skupper site if the skupper site is marked for deletion or the namespace is marked for deletion
                    delete=bool(ns.skupper_site.delete or ns.delete),
                    config=SkupperConfig.init(
                        name=f"{skupper_network.identifier}-{ns.cluster.name}-{ns.name}",
                        edge=edge,
                        defaults=skupper_network.site_config_defaults,
                        config=ns.skupper_site.config,
                    ),
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
    skupper_site: SkupperSite,
    oc_map: OC_Map,
    ri: ResourceInventory,
    integration_managed_kinds: Iterable[str],
) -> None:
    """Populate current openshift site state in resource inventory"""
    oc = oc_map.get_cluster(skupper_site.cluster.name)

    for kind in integration_managed_kinds:
        for item in oc.get_items(
            kind=kind,
            namespace=skupper_site.namespace.name,
            labels=SITE_CONTROLLER_LABELS,
        ):
            openshift_resource = OR(
                body=item,
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
            )
            ri.add_current(
                cluster=skupper_site.cluster.name,
                namespace=skupper_site.namespace.name,
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
        for resource in [
            site_controller_deployment(site),
            site_controller_service_account(site),
            site_controller_role(site),
            site_controller_role_binding(site),
            site_config(site),
        ]:
            openshift_resource = OR(
                body=resource,
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
            )
            integration_managed_kinds.add(openshift_resource.kind)
            ri.initialize_resource_type(
                cluster=site.cluster.name,
                namespace=site.namespace.name,
                resource_type=openshift_resource.kind,
            )
            # only add desired state if not deleting
            # but we need to handle it to initialize the resource inventory
            if not site.delete:
                ri.add_desired(
                    cluster=site.cluster.name,
                    namespace=site.namespace.name,
                    resource_type=openshift_resource.kind,
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
            current = SkupperConfig(**resource["current"][CONFIG_NAME].body["data"])
            desired = SkupperConfig(**resource["desired"][CONFIG_NAME].body["data"])
            if current != desired:
                changes = True
                logging.error(f"{cluster}/{ns}: Skupper site config has changed")
    return changes


def delete_skupper_resources(
    skupper_site: SkupperSite,
    oc_map: OC_Map,
    dry_run: bool,
    integration_managed_kinds: Iterable[str],
) -> None:
    """Delete all skupper resources starting with 'skupper-' in a namespace."""
    logging.info(f"{skupper_site}: Deleting all other Skupper openshift resources")
    oc = oc_map.get_cluster(skupper_site.cluster.name)
    to_delete: dict[str, dict[str, Any]] = {}

    for kind in integration_managed_kinds:
        # delete everything labeled by us
        to_delete.update(
            {
                f'{item["kind"]}-{item["metadata"]["name"]}': item
                for item in oc.get_items(
                    kind=kind,
                    namespace=skupper_site.namespace.name,
                    labels=SITE_CONTROLLER_LABELS,
                )
            }
        )
        # delete everything else that starts with 'skupper-'
        to_delete.update(
            {
                f'{item["kind"]}-{item["metadata"]["name"]}': item
                for item in oc.get_items(
                    kind=kind, namespace=skupper_site.namespace.name
                )
                if item["metadata"]["name"].startswith("skupper-")
            }
        )

    for item in to_delete.values():
        logging.info(
            [
                "delete",
                skupper_site.cluster.name,
                skupper_site.namespace.name,
                item["kind"],
                item["metadata"]["name"],
            ]
        )
        if not dry_run:
            oc.delete(
                skupper_site.namespace.name, item["kind"], item["metadata"]["name"]
            )


def connect_sites(site: SkupperSite, oc_map: OC_Map, dry_run: bool) -> None:
    """Connect skupper sites together."""
    oc = oc_map.get_cluster(site.cluster.name)
    if not oc.project_exists(site.namespace.name):
        logging.info(
            f"{site}: Namespace does not exist yet. Skipping this skupper site for now!"
        )
        return

    token_labels = {"token-receiver": site.name}

    for connected_site in site.connected_sites:
        # An existing connection token means we are already connected to this site
        if not oc.get(
            site.namespace.name,
            "Secret",
            site.token_name(connected_site),
            allow_not_found=True,
        ):
            # no connection token found. get the token from the connected site and import it
            connected_site_oc = oc_map.get_cluster(connected_site.cluster.name)
            if not connected_site_oc.project_exists(connected_site.namespace.name):
                logging.info(
                    f"{connected_site}: Namespace does not exist yet."
                    " Skipping this skupper site for now!"
                )
                continue

            if token := connected_site_oc.get(
                connected_site.namespace.name,
                "Secret",
                connected_site.unique_token_name(site),
                allow_not_found=True,
            ):
                if not is_usable_connection_token(token):
                    # token connection request secret not yet processed by site controller. skip it for now and try again later
                    logging.info(
                        f"{connected_site}: Site controller has not processed connection token request yet. Skipping"
                    )
                    continue

                logging.info(f"{site}: Connect to {connected_site}")
                # remove the token, it is not needed anymore on the receiver site
                connected_site_oc.delete(
                    connected_site.namespace.name,
                    "Secret",
                    connected_site.unique_token_name(site),
                )
                # change the token name to match the remote site name for easier identification, e.g. for `skupper link status`
                token["metadata"]["name"] = site.token_name(connected_site)
                token = OR(
                    # remove the namespace and other unneeded Openshift fields from the token secret
                    body=OR.canonicalize(token),
                    integration=QONTRACT_INTEGRATION,
                    integration_version=QONTRACT_INTEGRATION_VERSION,
                ).annotate()
                if not dry_run:
                    logging.info(
                        [
                            "apply",
                            site.cluster.name,
                            site.namespace.name,
                            "Secret",
                            token.name,
                        ]
                    )
                    oc.apply(site.namespace.name, token)
            else:
                # no token found - create a new connection token to be used by this site
                logging.info(
                    f"{connected_site}: Creating new connection token for {site}"
                )
                if not dry_run:
                    oc.apply(
                        connected_site.namespace.name,
                        resource=OR(
                            body=site_token(
                                connected_site.unique_token_name(site), token_labels
                            ),
                            integration=QONTRACT_INTEGRATION,
                            integration_version=QONTRACT_INTEGRATION_VERSION,
                        ),
                    )

    # finally delete any connection tokens that are no longer needed
    for item in oc.get_items(
        kind="Secret",
        namespace=site.namespace.name,
        labels=token_labels,
    ):
        if item["metadata"]["name"] not in [
            site.token_name(connected_site) for connected_site in site.connected_sites
        ]:
            logging.info(
                f"{site}: Delete unused/obsolete skupper site connection {item['metadata']['name']}"
            )
            oc.delete(site.namespace.name, item["kind"], item["metadata"]["name"])


def act(
    oc_map: OC_Map,
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

    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    # delete all other skupper related resources create by the skupper site controller
    threaded.run(
        delete_skupper_resources,
        [site for site in skupper_sites if site.delete],
        thread_pool_size,
        oc_map=oc_map,
        dry_run=dry_run,
        integration_managed_kinds=list(integration_managed_kinds) + ["Secret"],
    )
    threaded.run(
        connect_sites,
        [site for site in skupper_sites if not site.delete],
        thread_pool_size,
        oc_map=oc_map,
        dry_run=dry_run,
    )


def get_skupper_networks(query_func: Callable) -> list[SkupperNetworkV1]:
    data = skupper_networks_query(query_func)
    return data.skupper_networks or []


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    internal: Optional[bool] = None,
    use_jump_host: bool = True,
    defer: Optional[Callable] = None,
) -> None:
    settings = queries.get_app_interface_settings()
    gqlapi = gql.get_api()

    # data query
    skupper_networks = get_skupper_networks(gqlapi.query)
    skupper_sites = compile_skupper_sites(skupper_networks)

    # APIs
    oc_map = OC_Map(
        namespaces=[site.namespace.dict(by_alias=True) for site in skupper_sites],
        integration=QONTRACT_INTEGRATION,
        settings=settings,
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
    return {
        "skupper_networks": [site.dict() for site in get_skupper_networks(gqlapi.query)]
    }

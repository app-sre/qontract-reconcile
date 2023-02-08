import logging
from collections.abc import Iterable
from typing import Any

from sretoolbox.utils import threaded

import reconcile.openshift_base as ob
from reconcile.skupper_network.models import SkupperSite
from reconcile.skupper_network.site_controller import LABELS as SITE_CONTROLLER_LABELS
from reconcile.skupper_network.site_controller import get_site_controller
from reconcile.utils.oc import OC_Map
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory


def delete_skupper_site(
    site: SkupperSite,
    oc_map: OC_Map,
    dry_run: bool,
    integration_managed_kinds: Iterable[str],
) -> None:
    """Delete all skupper resources (leftovers not covered by ResourceInventory) starting with 'skupper-' in a namespace."""
    oc = oc_map.get_cluster(site.cluster.name)
    to_delete: dict[str, dict[str, Any]] = {}

    for kind in integration_managed_kinds:
        # delete everything labeled by us
        to_delete.update(
            {
                f'{item["kind"]}-{item["metadata"]["name"]}': item
                for item in oc.get_items(
                    kind=kind,
                    namespace=site.namespace.name,
                    labels=SITE_CONTROLLER_LABELS,
                )
            }
        )
        # delete everything else that starts with 'skupper-'
        to_delete.update(
            {
                f'{item["kind"]}-{item["metadata"]["name"]}': item
                for item in oc.get_items(kind=kind, namespace=site.namespace.name)
                if item["metadata"]["name"].startswith("skupper-")
            }
        )

    for item in to_delete.values():
        if "qontract.integration" in item["metadata"].get("annotations", {}):
            # don't delete resources managed by other integrations
            continue

        logging.info(
            [
                "delete",
                site.cluster.name,
                site.namespace.name,
                item["kind"],
                item["metadata"]["name"],
            ]
        )
        if not dry_run:
            oc.delete(site.namespace.name, item["kind"], item["metadata"]["name"])


def _get_token(oc_map: OC_Map, site: SkupperSite, name: str) -> dict[str, Any]:
    """Get a connection token secret from the site's namespace."""
    oc = oc_map.get_cluster(site.cluster.name)
    return oc.get(site.namespace.name, "Secret", name, allow_not_found=True)


def _create_token(
    oc_map: OC_Map,
    site: SkupperSite,
    connected_site: SkupperSite,
    dry_run: bool,
    integration: str,
    integration_version: str,
) -> None:
    """Create a connection token secret in the site's namespace."""
    oc = oc_map.get_cluster(connected_site.cluster.name)
    logging.info(f"{connected_site}: Creating new connection token for {site}")
    sc = get_site_controller(connected_site)
    if not dry_run:
        oc.apply(
            connected_site.namespace.name,
            resource=OR(
                body=sc.site_token(
                    connected_site.unique_token_name(site), site.token_labels
                ),
                integration=integration,
                integration_version=integration_version,
            ),
        )


def _transfer_token(
    oc_map: OC_Map,
    site: SkupperSite,
    connected_site: SkupperSite,
    dry_run: bool,
    integration: str,
    integration_version: str,
    token: dict[str, Any],
) -> None:
    """Move a connection token secret from one site to another."""
    sc = get_site_controller(site)
    if not sc.is_usable_connection_token(token):
        # token connection request secret not yet processed by site controller. skip it for now and try it again later
        logging.info(
            f"{connected_site}: Site controller has not processed connection token request yet. Skipping"
        )
        return

    oc = oc_map.get_cluster(site.cluster.name)
    connected_site_oc = oc_map.get_cluster(connected_site.cluster.name)

    logging.info(f"{site}: Connect to {connected_site}")
    if not dry_run:
        # remove the token, it is not needed anymore on the receiver site
        connected_site_oc.delete(
            connected_site.namespace.name,
            "Secret",
            connected_site.unique_token_name(site),
        )
    # change the token name to match the remote site name for easier identification, e.g. for `skupper link status`
    token["metadata"]["name"] = site.token_name(connected_site)
    connection_token = OR(
        # remove the namespace and other unneeded Openshift fields from the token secret
        body=OR.canonicalize(token),
        integration=integration,
        integration_version=integration_version,
    ).annotate()
    if not dry_run:
        logging.info(
            [
                "apply",
                site.cluster.name,
                site.namespace.name,
                "Secret",
                connection_token.name,
            ]
        )
        oc.apply(site.namespace.name, connection_token)


def connect_sites(
    site: SkupperSite,
    oc_map: OC_Map,
    dry_run: bool,
    integration: str,
    integration_version: str,
) -> None:
    """Connect skupper sites together.

    Connection sites together algorithm:
    1. Check if all related sites (namespaces) are available
    2. Iterate over all "to be connected sites" (connected_sites) and
    2.1. if we are already connected (connection-token exists) -> done
    2.2. if not connected (connection-token doesn't exist) -> token exchange alghorithm

    Token exchange alghorithm:
    1. Create a connection-token-request (secret with a unique token name) in the connected site's namespace
    2. Wait for the site controller to process the connection-token-request
    3. Move the connection-token (the processed connection-token-request secret) from the connected site's namespace into the site's namespace
    """
    oc = oc_map.get_cluster(site.cluster.name)
    if not oc.project_exists(site.namespace.name):
        logging.info(
            f"{site}: Namespace does not exist (yet). Skipping this skupper site for now!"
        )
        return

    for connected_site in site.connected_sites:
        # an existing connection token means we are already connected to this site
        if not _get_token(oc_map, site, site.token_name(connected_site)):
            # no connection token found. get the token from the connected site and import it
            connected_site_oc = oc_map.get_cluster(connected_site.cluster.name)
            if not connected_site_oc.project_exists(connected_site.namespace.name):
                logging.info(
                    f"{connected_site}: Namespace does not exist (yet)."
                    " Skipping this skupper site for now!"
                )
                continue

            if token := _get_token(
                oc_map,
                connected_site,
                connected_site.unique_token_name(site),
            ):
                # token found - move it to this site
                _transfer_token(
                    oc_map,
                    site,
                    connected_site,
                    dry_run,
                    integration,
                    integration_version,
                    token,
                )
            else:
                # no token found - create a new connection token to be used by this site
                _create_token(
                    oc_map,
                    site,
                    connected_site,
                    dry_run,
                    integration,
                    integration_version,
                )


def delete_unused_tokens(site: SkupperSite, oc_map: OC_Map, dry_run: bool) -> None:
    """Delete any other connection tokens that are no longer needed."""
    oc = oc_map.get_cluster(site.cluster.name)
    for item in oc.get_items(
        kind="Secret",
        namespace=site.namespace.name,
        labels=site.token_labels,
    ):
        if item["metadata"]["name"] not in [
            site.token_name(connected_site) for connected_site in site.connected_sites
        ]:
            logging.info(
                f"{site}: Delete unused/obsolete skupper site connection {item['metadata']['name']}"
            )
            if not dry_run:
                oc.delete(site.namespace.name, item["kind"], item["metadata"]["name"])


def reconcile(
    oc_map: OC_Map,
    ri: ResourceInventory,
    dry_run: bool,
    thread_pool_size: int,
    skupper_sites: Iterable[SkupperSite],
    integration_managed_kinds: Iterable[str],
    integration: str,
    integration_version: str,
) -> None:
    """Realize all skupper resources and create skupper site connections."""

    # create/update/delete all skupper site resources
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    # create skupper site connections by connection token exchange
    threaded.run(
        connect_sites,
        [site for site in skupper_sites if not site.delete],
        thread_pool_size,
        oc_map=oc_map,
        dry_run=dry_run,
        integration=integration,
        integration_version=integration_version,
    )

    # delete unused skupper site connection tokens
    threaded.run(
        delete_unused_tokens,
        [site for site in skupper_sites if not site.delete],
        thread_pool_size,
        oc_map=oc_map,
        dry_run=dry_run,
    )

    # delete all other skupper related resources create by the skupper site controller
    threaded.run(
        delete_skupper_site,
        [site for site in skupper_sites if site.delete],
        thread_pool_size,
        oc_map=oc_map,
        dry_run=dry_run,
        integration_managed_kinds=list(integration_managed_kinds) + ["Secret"],
    )

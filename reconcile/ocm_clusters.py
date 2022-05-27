import sys
import logging
from typing import Any, Iterable, Tuple, Mapping
from reconcile.utils.semver_helper import parse_semver

from reconcile import queries

from reconcile import mr_client_gateway

import reconcile.utils.mr.clusters_updates as cu

import reconcile.utils.ocm as ocmmod

from reconcile.ocm.types import OCMSpec

QONTRACT_INTEGRATION = "ocm-clusters"

OCM_GENERATED_FIELDS = ["network", "consoleUrl", "serverUrl", "elbFQDN"]
MANAGED_FIELDS = ["spec"] + OCM_GENERATED_FIELDS


def fetch_desired_state(clusters: Iterable[Mapping[str, Any]]) -> dict[str, OCMSpec]:
    """Builds a dictionary with all clusters retrieved from app-interface. Cluster specs
    are based on OCMSpec implementations depending the ocm product

    Parameters:
        clusters (list): list of clusters retrieved from app-interface

    Returns:
        dict: Collection with all cluster specs with the defined OCM model
    """
    desired_state = {}
    for c in clusters:
        name = c["name"]
        desired_state[name] = OCMSpec(**c)
    return desired_state


class ClusterVersionError(Exception):
    pass


def _cluster_version_needs_update(
    cluster: str, current_version: str, desired_version: str
) -> bool:
    """Compares version strings (semver) to determine if a current manifest is required.

    Parameters:
        cluster (str): cluster name
        current_version(str): current version string (semver)
        desired_version(str): desired verseion string (semver)

    Returns:
        bool: True if current version is grater than desired_version

    Raises:
        ClusterVersionError: if current_version < desired_version. It means the version
            has been updated in the app-interface manifest before the cluster update.
            Cluster updates are managed by the ocm-upgrade-scheduler integration.

    """

    desired_version = parse_semver(desired_version)
    current_version = parse_semver(current_version)

    if current_version > desired_version:
        # current version is geater due to an upgrade.
        # submit MR to update cluster version
        logging.info(
            f"[{cluster}] desired version {desired_version} is different from "
            + f"current version {current_version}. Version will be updated "
            + "in app-interface"
        )
        return True

    elif current_version < desired_version:
        raise ClusterVersionError(
            f"""[{cluster}] desired version [{desired_version}] is greater than
            current version [{current_version}]. Please correct version to be
            {current_version}, as this field is only meant for tracking purposes.
            Cluster upgrades are managed by ocm-upgrade-scheduler."""
        )
    # Versions are equal
    return False


def get_app_interface_spec_updates(
    cluster: str, current_spec: OCMSpec, desired_spec: OCMSpec
) -> Tuple[dict[str, Any], bool]:
    """Get required changes to apply to app-interface clusters manifest

    Parameters:
        cluster (str): cluster name
        current_spec (OCMSpec): Cluster spec retreived from OCM api
        desired_spec (OCMSpec): Cluster spec retreived from App-Interface

    Returns:
        updates (dict): Required updates to do in app-interface manifest
        err(bool): If there are errors with the specs (version related)

    """

    error = False
    ocm_spec_updates: dict[str, Any] = {}
    root_updates: dict[str, Any] = {}

    try:
        if _cluster_version_needs_update(
            cluster, current_spec.spec.version, desired_spec.spec.version
        ):
            ocm_spec_updates[ocmmod.SPEC_ATTR_VERSION] = current_spec.spec.version
    except ClusterVersionError as cve:
        logging.error(cve)
        error = True

    if not desired_spec.spec.id:
        ocm_spec_updates[ocmmod.SPEC_ATTR_ID] = current_spec.spec.id

    if not desired_spec.spec.external_id:
        ocm_spec_updates[ocmmod.SPEC_ATTR_EXTERNAL_ID] = current_spec.spec.external_id

    if (
        desired_spec.spec.disable_user_workload_monitoring is None
        and current_spec.spec.disable_user_workload_monitoring
    ):
        ocm_spec_updates[
            ocmmod.SPEC_ATTR_DISABLE_UWM
        ] = current_spec.spec.disable_user_workload_monitoring

    if desired_spec.spec.provision_shard_id != current_spec.spec.provision_shard_id:
        ocm_spec_updates[
            ocmmod.SPEC_ATTR_PROVISION_SHARD_ID
        ] = current_spec.spec.provision_shard_id

    if not desired_spec.console_url:
        root_updates[ocmmod.SPEC_ATTR_CONSOLE_URL] = current_spec.console_url

    if not desired_spec.server_url:
        root_updates[ocmmod.SPEC_ATTR_SERVER_URL] = current_spec.server_url

    if not desired_spec.elb_fqdn:
        root_updates[
            ocmmod.SPEC_ATTR_ELBFQDN
        ] = f"elb.apps.{cluster}.{current_spec.domain}"

    updates: dict[str, Any] = {}
    updates[ocmmod.SPEC_ATTR_PATH] = desired_spec.path
    updates["root"] = root_updates
    updates["spec"] = ocm_spec_updates

    return updates, error


def get_cluster_ocm_update_spec(
    ocm: ocmmod.OCM, cluster: str, current_spec: OCMSpec, desired_spec: OCMSpec
) -> Tuple[dict[str, Any], bool]:
    """Get cluster updates to request to OCM api

    Parameters:
        ocm (OCM): ocm implementation for an ocm product (osd, rosa)
        cluster (str): cluster name
        current_spec (OCMSpec): Cluster spec retreived from OCM api
        desired_spec (OCMSpec): Cluster spec retreived from App-Interface

    Returns:
        updates (dict): Updates to request to OCM api
        error (bool): If errors detected due to spec not allowed updates.
    """

    impl = ocmmod.OCM_PRODUCTS_IMPL[current_spec.spec.product]

    error = False
    if not desired_spec.network.type:
        desired_spec.network.type = "OpenShiftSDN"

    if current_spec.network != desired_spec.network:
        error = True
        logging.error(f"[{cluster}] invalid update: network")

    # Convert ocm specs to dicts, removing null values and excluded attributes
    current_ocm_spec = {
        k: v
        for k, v in current_spec.spec.dict().items()
        if v is not None and k not in impl.EXCLUDED_SPEC_FIELDS
    }

    desired_ocm_spec = {
        k: v
        for k, v in desired_spec.spec.dict().items()
        if v is not None and k not in impl.EXCLUDED_SPEC_FIELDS
    }

    # Updated attributes in app-interface
    updated_attrs = {
        k: v for k, v in desired_ocm_spec.items() if current_ocm_spec.get(k) != v
    }

    # Removed attributes in app-interface
    deleted_attrs = {
        k: v
        for k, v in current_ocm_spec.items()
        if k not in desired_ocm_spec and v is not None
    }

    diffs = deleted_attrs
    diffs.update(updated_attrs)

    not_allowed_updates = set(diffs) - impl.ALLOWED_SPEC_UPDATE_FIELDS
    if not_allowed_updates:
        error = True
        logging.error(f"[{cluster}] invalid updates: {not_allowed_updates}")

    return diffs, error


def _app_interface_updates_mr(
    clusters_updates: Mapping[str, Any], gitlab_project_id: str, dry_run: bool
):
    """Creates an MR to app-interface with the necessary cluster manifest updates

    Parameters:
        clusters_updates (Mapping): Updates to perform. Format required by the MR utils code
        gitlab_project_id (str): Gitlab project where to raise the MR
        dry_run (bool): dry_run
    """
    create_update_mr = False
    for cluster_name, cluster_updates in clusters_updates.items():
        for k, v in cluster_updates["spec"].items():
            logging.info(
                f"[{cluster_name}] desired key in spec "
                + f"{k} will be updated automatically "
                + f"with value {v}."
            )
            create_update_mr = True
        for k, v in cluster_updates["root"].items():
            logging.info(
                f"[{cluster_name}] desired root key {k} will "
                f"be updated automatically with value {v}"
            )
            create_update_mr = True

    if create_update_mr and not dry_run:
        mr_cli = mr_client_gateway.init(gitlab_project_id=gitlab_project_id)
        mr = cu.CreateClustersUpdates(clusters_updates)
        mr.submit(cli=mr_cli)


def run(dry_run, gitlab_project_id=None, thread_pool_size=10):
    settings = queries.get_app_interface_settings()
    clusters = queries.get_clusters()
    clusters = [c for c in clusters if c.get("ocm") is not None]
    ocm_map = ocmmod.OCMMap(
        clusters=clusters,
        integration=QONTRACT_INTEGRATION,
        settings=settings,
        init_provision_shards=True,
    )

    # current_state = ocm_state
    current_state, pending_state = ocm_map.cluster_specs()
    desired_state = fetch_desired_state(clusters)

    error = False
    clusters_updates = {}

    for cluster_name, desired_spec in desired_state.items():
        current_spec = current_state.get(cluster_name)
        if current_spec:
            # APP-Interface manifests updates.
            # OCM populated attributes that are not set in app-interface.
            # These updates are performed with a single MR out of this main loop
            clusters_updates[cluster_name], err = get_app_interface_spec_updates(
                cluster_name, current_spec, desired_spec
            )
            if err:
                error = True

            # OCM API Updates
            # Changes made to pp-interface manifests that need to be requested
            # to the OCM Api
            ocm = ocm_map.get(cluster_name)
            update_spec, err = get_cluster_ocm_update_spec(
                ocm, cluster_name, current_spec, desired_spec
            )
            if err:
                error = True
                continue

            # update cluster
            # TODO(mafriedm): check dry_run in OCM API patch
            if update_spec:
                logging.info(["update_cluster", cluster_name])
                logging.debug(
                    f"current_spec: {current_spec}, desired_spec: {desired_spec}"
                )
                if not dry_run:
                    ocm = ocm_map.get(cluster_name)
                    try:
                        ocm.update_cluster(cluster_name, update_spec, dry_run)
                    except NotImplementedError:
                        logging.error(
                            f"[{cluster_name}] Update clusters is currently not "
                            "implemented for [{desired_spec.spec.product}] product. "
                            "Updates to the cluster spec are not supported."
                        )
                        # Not marking error as a changer made in ocm could trigger
                        # this.
                        # error = True
        else:
            # create cluster
            if cluster_name in pending_state:
                continue
            logging.info(["create_cluster", cluster_name])
            ocm = ocm_map.get(cluster_name)
            try:
                ocm.create_cluster(cluster_name, desired_spec, dry_run)
            except NotImplementedError:
                logging.error(
                    f"[{cluster_name}] Create clusters is not currently implemented "
                    "for [{desired_spec.spec.product}] product type. Make sure the "
                    "cluster exists and it is returned by the OCM api before adding "
                    "its manifest to app-interface"
                )
                error = True

    _app_interface_updates_mr(clusters_updates, gitlab_project_id, dry_run)
    sys.exit(int(error))

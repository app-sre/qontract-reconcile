import logging
import sys
from collections.abc import (
    Iterable,
    Mapping,
)
from typing import Any

import reconcile.utils.mr.clusters_updates as cu
import reconcile.utils.ocm as ocmmod
from reconcile import (
    mr_client_gateway,
    queries,
)
from reconcile.ocm.types import (
    OCMSpec,
    ROSAClusterAWSAccount,
    ROSAOcmAwsAttrs,
    ROSAOcmAwsStsAttrs,
)
from reconcile.status import ExitCodes
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.semver_helper import parse_semver

QONTRACT_INTEGRATION = "ocm-clusters"


def _set_rosa_ocm_attrs(cluster: Mapping[str, Any]):
    """Cluster account (aws) attribute from app-interface differs from the OCMSpec.
    app-interface's account includes the details for all the OCM environments
    but the cluster only needs the target OCM environment where it belongs.
    This method changes the cluster dictionary to include just those.
    """
    ocm_env = [
        env
        for env in cluster["spec"]["account"]["rosa"]["ocm_environments"]
        if env["ocm"]["name"] == cluster["ocm"]["name"]
    ]

    if len(ocm_env) != 1:
        logging.error(
            "The cluster's OCM reference does not exist or it is duplicated in the AWS account manifest. "
            "Check the cluster's AWS account rosa configuration. "
            f"OCM:{cluster['ocm']['name']}, AWSAcc:{cluster['spec']['account']['uid']}"
        )
        sys.exit(ExitCodes.ERROR)

    uid = cluster["spec"]["account"]["uid"]
    env = ocm_env[0]
    # doing this allows to exclude account fields which can be queried in graphql
    cluster["spec"]["account"] = ROSAClusterAWSAccount(
        uid=uid,
        rosa=ROSAOcmAwsAttrs(
            creator_role_arn=env["creator_role_arn"],
            sts=ROSAOcmAwsStsAttrs(
                installer_role_arn=env["installer_role_arn"],
                support_role_arn=env["support_role_arn"],
                controlplane_role_arn=env["controlplane_role_arn"],
                worker_role_arn=env["worker_role_arn"],
            ),
        ),
    )


def fetch_desired_state(clusters: Iterable[Mapping[str, Any]]) -> dict[str, OCMSpec]:
    """Builds a dictionary with all clusters retrieved from app-interface. Cluster specs
    are based on OCMSpec implementations depending on the ocm product

    :param clusters: list of clusters retrieved from app-interface
    :return: Collection with all cluster specs with the defined OCM model
    """
    desired_state = {}
    for c in clusters:
        if c["spec"]["product"] == ocmmod.OCM_PRODUCT_ROSA:
            _set_rosa_ocm_attrs(c)
        name = c["name"]
        desired_state[name] = OCMSpec(**c)

    return desired_state


class ClusterVersionError(Exception):
    pass


def _cluster_version_needs_update(
    cluster: str, current_version: str, desired_version: str
) -> bool:
    """Compares version strings (semver) to determine if a current manifest is required.

    :param cluster: cluster name
    :param current_version: current version string (semver)
    :param desired_version: desired version string (semver)
    :raises ClusterVersionError: if current_version < desired_version. It means the
            version has been updated in the app-interface manifest before the cluster
            update. Cluster updates are managed by the ocm-upgrade-scheduler integration.
    :return: True if current version is greater than desired_version
    """

    # .spec.version not set in app-interface (or empty string)
    if not desired_version:
        return True

    desired_version = parse_semver(desired_version)
    current_version = parse_semver(current_version)

    if current_version > desired_version:
        # current version is geater due to an upgrade.
        # submit MR to update cluster version
        logging.info(
            f"[{cluster}] desired version {desired_version} is different from "
            f"current version {current_version}. Version will be updated "
            "in app-interface"
        )
        return True

    if current_version < desired_version:
        raise ClusterVersionError(
            f"[{cluster}] desired version [{desired_version}] is greater than "
            f"current version [{current_version}]. Please correct version to be "
            f"{current_version}, as this field is only meant for tracking purposes. "
            "Cluster upgrades are managed by ocm-upgrade-scheduler."
        )
    # Versions are equal
    return False


def get_app_interface_spec_updates(
    cluster: str, current_spec: OCMSpec, desired_spec: OCMSpec
) -> tuple[dict[str, Any], bool]:
    """Get required changes to apply to app-interface clusters manifest

    :param cluster: cluster name
    :param current_spec: Cluster spec retreived from OCM api
    :param desired_spec: Cluster spec retreived from App-Interface
    :return: Required updates to do in app-interface manifest and a bool to notify errors
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

    if current_spec.spec.id and desired_spec.spec.id != current_spec.spec.id:
        ocm_spec_updates[ocmmod.SPEC_ATTR_ID] = current_spec.spec.id

    if (
        current_spec.spec.external_id
        and desired_spec.spec.external_id != current_spec.spec.external_id
    ):
        ocm_spec_updates[ocmmod.SPEC_ATTR_EXTERNAL_ID] = current_spec.spec.external_id

    if (
        desired_spec.spec.disable_user_workload_monitoring is None
        and current_spec.spec.disable_user_workload_monitoring
    ):
        ocm_spec_updates[
            ocmmod.SPEC_ATTR_DISABLE_UWM
        ] = current_spec.spec.disable_user_workload_monitoring

    if (
        current_spec.spec.provision_shard_id is not None
        and desired_spec.spec.provision_shard_id != current_spec.spec.provision_shard_id
    ):
        ocm_spec_updates[
            ocmmod.SPEC_ATTR_PROVISION_SHARD_ID
        ] = current_spec.spec.provision_shard_id

    if current_spec.server_url and desired_spec.server_url != current_spec.server_url:
        root_updates[ocmmod.SPEC_ATTR_SERVER_URL] = current_spec.server_url

    if current_spec.console_url:
        if desired_spec.console_url != current_spec.console_url:
            root_updates[ocmmod.SPEC_ATTR_CONSOLE_URL] = current_spec.console_url

        # https://issues.redhat.com/browse/SDA-7204
        elb_fqdn = current_spec.console_url.replace(
            "https://console-openshift-console", "elb"
        )
        if desired_spec.elb_fqdn != elb_fqdn:
            root_updates[ocmmod.SPEC_ATTR_ELBFQDN] = elb_fqdn

    updates: dict[str, Any] = {}
    updates[ocmmod.SPEC_ATTR_PATH] = "data" + str(desired_spec.path)
    updates["root"] = root_updates
    updates["spec"] = ocm_spec_updates

    return updates, error


def get_cluster_ocm_update_spec(
    ocm: ocmmod.OCM, cluster: str, current_spec: OCMSpec, desired_spec: OCMSpec
) -> tuple[dict[str, Any], bool]:
    """Get cluster updates to request to OCM api

    :param ocm: ocm implementation for an ocm product (osd, rosa)
    :param cluster: cluster name
    :param current_spec: Cluster spec retrieved from OCM api
    :param desired_spec: Cluster spec retrieved from App-Interface
    :return: a tuple with the updates to request to OCM and a bool to notify errors
    """

    impl = ocmmod.OCM_PRODUCTS_IMPL[current_spec.spec.product]

    error = False
    if not desired_spec.network.type:
        desired_spec.network.type = "OVNKubernetes"

    cspec = current_spec.spec.dict()
    cspec[ocmmod.SPEC_ATTR_NETWORK] = current_spec.network.dict()

    dspec = desired_spec.spec.dict()
    dspec[ocmmod.SPEC_ATTR_NETWORK] = desired_spec.network.dict()

    # Convert ocm specs to dicts, removing null values and excluded attributes
    current_ocm_spec = {
        k: v
        for k, v in cspec.items()
        if v is not None and k not in impl.EXCLUDED_SPEC_FIELDS
    }

    desired_ocm_spec = {
        k: v
        for k, v in dspec.items()
        if v is not None and k not in impl.EXCLUDED_SPEC_FIELDS
    }

    # Updated attributes in app-interface
    updated_attrs = {
        k: v for k, v in desired_ocm_spec.items() if current_ocm_spec.get(k) != v
    }

    # Removed attributes in app-interface
    deleted_attrs = {
        k: v for k, v in current_ocm_spec.items() if k not in desired_ocm_spec
    }

    diffs = deleted_attrs | updated_attrs

    not_allowed_updates = set(diffs) - impl.ALLOWED_SPEC_UPDATE_FIELDS
    if not_allowed_updates:
        error = True
        logging.error(f"[{cluster}] invalid updates: {not_allowed_updates}")

    return updated_attrs, error


def _app_interface_updates_mr(
    clusters_updates: Mapping[str, Any], gitlab_project_id: str, dry_run: bool
):
    """Creates an MR to app-interface with the necessary cluster manifest updates

    :param clusters_updates: Updates to perform. Format required by the MR utils code
    :param gitlab_project_id: Gitlab project where to raise the MR
    :param dry_run: dry_run
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
        mr = cu.CreateClustersUpdates(clusters_updates)
        with mr_client_gateway.init(gitlab_project_id=gitlab_project_id) as mr_cli:
            mr.submit(cli=mr_cli)


def _cluster_is_compatible(cluster: Mapping[str, Any]) -> bool:
    return cluster.get("ocm") is not None


def run(dry_run: bool, gitlab_project_id=None, thread_pool_size=10):
    settings = queries.get_app_interface_settings()
    clusters = queries.get_clusters()
    clusters = [
        c
        for c in clusters
        if integration_is_enabled(QONTRACT_INTEGRATION, c) and _cluster_is_compatible(c)
    ]
    if not clusters:
        logging.debug("No OCM cluster definitions found in app-interface")
        sys.exit(ExitCodes.SUCCESS)

    ocm_map = ocmmod.OCMMap(
        clusters=clusters,
        integration=QONTRACT_INTEGRATION,
        settings=settings,
        init_provision_shards=True,
    )

    # current_state is the state got from the ocm api
    current_state, pending_state = ocm_map.cluster_specs()
    desired_state = fetch_desired_state(clusters)

    error = False
    clusters_updates = {}

    for cluster_name, desired_spec in desired_state.items():
        current_spec = current_state.get(cluster_name)
        if current_spec:
            # App-Interface manifests updates.
            # OCM populated attributes that are not set in app-interface.
            # These updates are performed with a single MR out of this main loop
            clusters_updates[cluster_name], err = get_app_interface_spec_updates(
                cluster_name, current_spec, desired_spec
            )
            if err:
                error = True

            # OCM API Updates
            # Changes made to app-interface manifests that need to be requested
            # to the OCM Api
            ocm = ocm_map.get(cluster_name)
            update_spec, err = get_cluster_ocm_update_spec(
                ocm, cluster_name, current_spec, desired_spec
            )
            if err:
                error = True
                continue

            # update cluster
            if update_spec:
                logging.info(["update_cluster", cluster_name])
                logging.debug(
                    f"current_spec: {current_spec}, desired_spec: {desired_spec}"
                )
                ocm = ocm_map.get(cluster_name)
                ocm.update_cluster(cluster_name, update_spec, dry_run)

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
                    f"for [{desired_spec.spec.product}] product type. Make sure the "
                    "cluster exists and it is returned by the OCM api before adding "
                    "its manifest to app-interface"
                )
                error = True
            except ocmmod.OCMValidationException as e:
                logging.error("[%s] Error creating cluster: %s", cluster_name, e)
                error = True

    _app_interface_updates_mr(clusters_updates, gitlab_project_id, dry_run)
    sys.exit(int(error))

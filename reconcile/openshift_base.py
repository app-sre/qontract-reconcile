from dataclasses import dataclass, field
import logging
import itertools

from typing import Any, Dict, Optional, Iterable, Mapping, Union

import yaml

from sretoolbox.utils import retry
from sretoolbox.utils import threaded

from reconcile import queries
from reconcile.utils.oc import (
    DeploymentFieldIsImmutableError,
    FieldIsImmutableError,
    OCClient,
    OCLogMsg,
)
from reconcile.utils.oc import MayNotChangeOnceSetError
from reconcile.utils.oc import PrimaryClusterIPCanNotBeUnsetError
from reconcile.utils.oc import InvalidValueApplyError
from reconcile.utils.oc import MetaDataAnnotationsTooLongApplyError
from reconcile.utils.oc import StatefulSetUpdateForbidden
from reconcile.utils.oc import OCDeprecated, OC_Map
from reconcile.utils.oc import StatusCodeError
from reconcile.utils.oc import UnsupportedMediaTypeError
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory


ACTION_APPLIED = "applied"
ACTION_DELETED = "deleted"


class ValidationError(Exception):
    pass


class ValidationErrorJobFailed(Exception):
    pass


@dataclass
class BaseStateSpec:

    oc: OCClient = field(compare=False, repr=False)
    cluster: str
    namespace: str


@dataclass
class CurrentStateSpec(BaseStateSpec):

    kind: str
    resource_names: Optional[Iterable[str]]


@dataclass
class DesiredStateSpec(BaseStateSpec):

    resource: Mapping[str, Any]
    parent: Mapping[Any, Any] = field(repr=False)
    privileged: bool = False


StateSpec = Union[CurrentStateSpec, DesiredStateSpec]


def init_specs_to_fetch(
    ri: ResourceInventory,
    oc_map: OC_Map,
    namespaces: Optional[Iterable[Mapping]] = None,
    clusters: Optional[Iterable[Mapping]] = None,
    override_managed_types: Optional[Iterable[str]] = None,
    managed_types_key: str = "managedResourceTypes",
) -> list[StateSpec]:
    state_specs: list[StateSpec] = []

    if clusters and namespaces:
        raise KeyError("expected only one of clusters or namespaces.")
    elif namespaces:
        for namespace_info in namespaces:
            if override_managed_types is None:
                managed_types = set(namespace_info.get(managed_types_key) or [])
            else:
                managed_types = set(override_managed_types)

            if not managed_types:
                continue

            cluster = namespace_info["cluster"]["name"]
            privileged = namespace_info.get("clusterAdmin", False) is True
            try:
                oc = oc_map.get_cluster(cluster, privileged)
            except OCLogMsg as ex:
                if ex.log_level >= logging.ERROR:
                    ri.register_error()
                logging.log(level=ex.log_level, msg=ex.message)
                continue

            namespace = namespace_info["name"]
            # These may exit but have a value of None
            managed_resource_names = namespace_info.get("managedResourceNames") or []
            managed_resource_type_overrides = (
                namespace_info.get("managedResourceTypeOverrides") or []
            )

            # Prepare resource names
            resource_names = {}
            resource_type_overrides = {}
            for mrn in managed_resource_names:
                # Current implementation guarantees only one
                # managed_resource_name of each managed type
                if mrn["resource"] in managed_types:
                    resource_names[mrn["resource"]] = mrn["resourceNames"]
                elif override_managed_types:
                    logging.debug(
                        f"Skipping resource {mrn['resource']} in {cluster}/"
                        f"{namespace} because the integration explicitly "
                        "dismisses it"
                    )
                else:
                    raise KeyError(
                        f"Non-managed resource name {mrn} listed on "
                        f"{cluster}/{namespace} (valid kinds: {managed_types})"
                    )

            # Prepare type overrides
            for o in managed_resource_type_overrides:
                # Current implementation guarantees only one
                # override of each managed type
                if o["resource"] in managed_types:
                    resource_type_overrides[o["resource"]] = o["override"]
                elif override_managed_types:
                    logging.debug(
                        f"Skipping resource type override {o} listed on"
                        f"{cluster}/{namespace} because the integration "
                        "dismisses it explicitly"
                    )
                else:
                    raise KeyError(
                        f"Non-managed override {o} listed on "
                        f"{cluster}/{namespace} (valid kinds: {managed_types})"
                    )

            # Initialized current state specs
            for kind in managed_types:
                managed_names = resource_names.get(kind)
                kind_to_use = resource_type_overrides.get(kind, kind)
                ri.initialize_resource_type(cluster, namespace, kind_to_use)
                state_specs.append(
                    CurrentStateSpec(
                        oc=oc,
                        cluster=cluster,
                        namespace=namespace,
                        kind=kind_to_use,
                        resource_names=managed_names,
                    )
                )

            # Initialize desired state specs
            openshift_resources = namespace_info.get("openshiftResources")
            for openshift_resource in openshift_resources or []:
                state_specs.append(
                    DesiredStateSpec(
                        oc=oc,
                        cluster=cluster,
                        namespace=namespace,
                        resource=openshift_resource,
                        parent=namespace_info,
                        privileged=privileged,
                    )
                )

    elif clusters:
        # set namespace to something indicative
        namespace = "cluster"
        for cluster_info in clusters:
            cluster = cluster_info["name"]
            try:
                oc = oc_map.get_cluster(cluster)
            except OCLogMsg as ex:
                if ex.log_level >= logging.ERROR:
                    ri.register_error()
                logging.log(level=ex.log_level, msg=ex.message)
                continue

            # we currently only use override_managed_types,
            # and not allow a `managedResourcesTypes` field in a cluster file
            for kind in override_managed_types or []:
                ri.initialize_resource_type(cluster, namespace, kind)

                # Initialize current state specs
                state_specs.append(
                    CurrentStateSpec(
                        oc=oc,
                        cluster=cluster,
                        namespace=namespace,
                        kind=kind,
                        resource_names=[],
                    )
                )
                # Initialize desired state specs
                # it seems this StateSpec has no effect and can be disabled. the only code path
                # leading to this place is from openshift_clusterrolebindings > ob.fetch_current_state >
                # init_specs_to_fetch. ob_fetch_current_state then uses the specs return from here
                # to populate the current state in an ResourceInventory (populate_current), which does not
                # differentiate between StateSpecs of type current and desired and just populates the
                # ResourceInventory spec with it. that is also the reason that it is not a problem that
                # the resource field in the desired StateSpec can be a resource_type instead of being
                # a resource dict like usual.
                #
                # running the openshift-clusterrolebinding integration showed a clean log after disabling
                # this line, which indicates no change in behaviour. even a dry-run mode with some deleted
                # roles showed expected behaviour.
                #
                # following this reasoning - i'm going to disable this line for now and will remove it
                # before merging this PR if i get no objection.
                #
                # d_spec = StateSpec("desired", oc, cluster, namespace, resource_type)

    else:
        raise KeyError("expected one of clusters or namespaces.")

    return state_specs


def populate_current_state(
    spec: CurrentStateSpec,
    ri: ResourceInventory,
    integration: str,
    integration_version: str,
):
    # if spec.oc is None: - oc can't be none because init_namespace_specs_to_fetch does not create specs if oc is none
    #    return
    if spec.oc.init_api_resources and not spec.oc.is_kind_supported(spec.kind):
        msg = f"[{spec.cluster}] cluster has no API resource {spec.kind}."
        logging.warning(msg)
        return
    try:
        for item in spec.oc.get_items(
            spec.kind, namespace=spec.namespace, resource_names=spec.resource_names
        ):
            openshift_resource = OR(item, integration, integration_version)
            ri.add_current(
                spec.cluster,
                spec.namespace,
                spec.kind,
                openshift_resource.name,
                openshift_resource,
            )
    except StatusCodeError:
        ri.register_error(cluster=spec.cluster)


def fetch_current_state(
    namespaces=None,
    clusters=None,
    thread_pool_size=None,
    integration=None,
    integration_version=None,
    override_managed_types=None,
    internal=None,
    use_jump_host=True,
    init_api_resources=False,
    cluster_admin=False,
):
    ri = ResourceInventory()
    settings = queries.get_app_interface_settings()
    oc_map = OC_Map(
        namespaces=namespaces,
        clusters=clusters,
        integration=integration,
        settings=settings,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
        init_api_resources=init_api_resources,
        cluster_admin=cluster_admin,
    )
    state_specs = init_specs_to_fetch(
        ri,
        oc_map,
        namespaces=namespaces,
        clusters=clusters,
        override_managed_types=override_managed_types,
    )
    threaded.run(
        populate_current_state,
        state_specs,
        thread_pool_size,
        ri=ri,
        integration=integration,
        integration_version=integration_version,
    )

    return ri, oc_map


@retry(max_attempts=20)
def wait_for_namespace_exists(oc, namespace):
    if not oc.project_exists(namespace):
        raise Exception(f"namespace {namespace} does not exist")


def apply(
    dry_run: bool,
    oc_map: OC_Map,
    cluster: str,
    namespace: str,
    resource_type: str,
    resource: OR,
    wait_for_namespace: bool,
    recycle_pods: bool = True,
    privileged: bool = False,
) -> None:
    logging.info(["apply", cluster, namespace, resource_type, resource.name])

    try:
        oc = oc_map.get_cluster(cluster, privileged)
    except OCLogMsg as ex:
        logging.log(level=ex.log_level, msg=ex.message)
        return None
    if not dry_run:
        annotated = resource.annotate()
        # skip if namespace does not exist (as it will soon)
        # do not skip if this is a cluster scoped integration
        if namespace != "cluster" and not oc.project_exists(namespace):
            msg = f"[{cluster}/{namespace}] namespace does not exist (yet)."
            if wait_for_namespace:
                logging.info(msg + " waiting...")
                wait_for_namespace_exists(oc, namespace)
            else:
                logging.warning(msg)
                return

        try:
            oc.apply(namespace, annotated)
        except InvalidValueApplyError:
            oc.remove_last_applied_configuration(
                namespace, resource_type, resource.name
            )
            oc.apply(namespace, annotated)
        except (MetaDataAnnotationsTooLongApplyError, UnsupportedMediaTypeError):
            if not oc.get(
                namespace, resource_type, resource.name, allow_not_found=True
            ):
                oc.create(namespace, annotated)
            oc.replace(namespace, annotated)
        except FieldIsImmutableError:
            # Add more resources types to the list when you're
            # sure they're safe.
            if resource_type not in ["Route", "Service", "Secret"]:
                raise
            oc.delete(namespace=namespace, kind=resource_type, name=resource.name)
            oc.apply(namespace=namespace, resource=annotated)
        except DeploymentFieldIsImmutableError:
            logging.info(["replace", cluster, namespace, resource_type, resource.name])
            # spec.selector changes
            current_resource = oc.get(namespace, resource_type, resource.name)

            # check update strategy
            if current_resource["spec"]["strategy"]["type"] != "RollingUpdate":
                logging.error(
                    f"Can't replace Deployment '{resource.name}' inplace w/o"
                    "interruption because spec.strategy.type != 'RollingUpdate'"
                )
                raise

            # Get active ReplicSet for old Deployment. We've to take care of it
            # after the new Deployment is in place.
            obsolete_rs = oc.get_replicaset(
                namespace, current_resource, allow_empty=True
            )

            # delete old Deployment
            oc.delete(
                namespace=namespace,
                kind=resource_type,
                name=resource.name,
                cascade=False,
            )
            # create new one
            oc.apply(namespace=namespace, resource=annotated)
            if obsolete_rs:
                # refresh resources
                deployment = oc.get(namespace, resource_type, resource.name)
                new_rs = oc.get_replicaset(namespace, deployment)
                obsolete_rs = oc.get(
                    namespace, obsolete_rs["kind"], obsolete_rs["metadata"]["name"]
                )

                # adopting old ReplicaSet to new Deployment
                # labels must match spec.selector.matchLabels of the new Deployment
                labels = deployment["spec"]["selector"]["matchLabels"]
                labels["pod-template-hash"] = obsolete_rs["metadata"]["labels"][
                    "pod-template-hash"
                ]
                obsolete_rs["metadata"]["labels"] = labels
                # restore and set ownerReferences of old ReplicaSet
                owner_references = new_rs["metadata"]["ownerReferences"]
                # not allowed to set 'blockOwnerDeletion'
                del owner_references[0]["blockOwnerDeletion"]
                obsolete_rs["metadata"]["ownerReferences"] = owner_references
                oc.apply(namespace=namespace, resource=OR(obsolete_rs, "", ""))
        except (MayNotChangeOnceSetError, PrimaryClusterIPCanNotBeUnsetError):
            if resource_type not in ["Service"]:
                raise

            oc.delete(namespace=namespace, kind=resource_type, name=resource.name)
            oc.apply(namespace=namespace, resource=annotated)
        except StatefulSetUpdateForbidden:
            if resource_type != "StatefulSet":
                raise

            logging.info(
                [
                    "delete_sts_and_apply",
                    cluster,
                    namespace,
                    resource_type,
                    resource.name,
                ]
            )
            current_resource = oc.get(namespace, resource_type, resource.name)
            current_storage = oc.get_storage(current_resource)
            desired_storage = oc.get_storage(resource.body)
            resize_required = current_storage != desired_storage
            if resize_required:
                owned_pods = oc.get_owned_pods(namespace, resource)
                owned_pvc_names = oc.get_pod_owned_pvc_names(owned_pods)
            oc.delete(
                namespace=namespace,
                kind=resource_type,
                name=resource.name,
                cascade=False,
            )
            oc.apply(namespace=namespace, resource=annotated)
            # the resource was applied without cascading.
            # if the change was in the storage, we need to
            # take care of the resize ourselves.
            # ref: https://github.com/kubernetes/enhancements/pull/2842
            if resize_required:
                logging.info(["resizing_pvcs", cluster, namespace, owned_pvc_names])
                oc.resize_pvcs(namespace, owned_pvc_names, desired_storage)

    if recycle_pods:
        oc.recycle_pods(dry_run, namespace, resource_type, resource)


def create(dry_run, oc_map, cluster, namespace, resource_type, resource):
    logging.info(["create", cluster, namespace, resource_type, resource.name])

    oc = oc_map.get(cluster)
    if not oc:
        logging.log(level=oc.log_level, msg=oc.message)
        return None
    if not dry_run:
        annotated = resource.annotate()
        oc.create(namespace, annotated)


def delete(
    dry_run: bool,
    oc_map: OC_Map,
    cluster: str,
    namespace: str,
    resource_type: str,
    name: str,
    enable_deletion: bool,
    privileged: bool = False,
) -> None:
    logging.info(["delete", cluster, namespace, resource_type, name])

    if not enable_deletion:
        logging.error("'delete' action is disabled due to previous errors.")
        return

    try:
        oc = oc_map.get_cluster(cluster, privileged)
        if not dry_run:
            oc.delete(namespace, resource_type, name)
    except OCLogMsg as ex:
        logging.log(level=ex.log_level, msg=ex.message)
        return None


def check_unused_resource_types(ri):
    for cluster, namespace, resource_type, data in ri:
        if not data["desired"].items():
            msg = (
                f"[{cluster}/{namespace}] unused "
                + f"resource type: {resource_type}. please remove it "
                + "in a following PR."
            )
            logging.warning(msg)


def _realize_resource_data(
    unpacked_ri_item,
    dry_run,
    oc_map: OC_Map,
    ri: ResourceInventory,
    take_over,
    caller,
    all_callers,
    wait_for_namespace,
    no_dry_run_skip_compare,
    override_enable_deletion,
    recycle_pods,
):
    cluster, namespace, resource_type, data = unpacked_ri_item
    actions: list[dict] = []
    if ri.has_error_registered(cluster=cluster):
        msg = ("[{}] skipping realize_data for " "cluster with errors").format(cluster)
        logging.error(msg)
        return actions

    enable_deletion = False if ri.has_error_registered() else True
    # only allow to override enable_deletion if no errors were found
    if enable_deletion is True and override_enable_deletion is False:
        enable_deletion = False

    # desired items
    for name, d_item in data["desired"].items():
        c_item: OR = data["current"].get(name)

        if c_item is not None:
            if not dry_run and no_dry_run_skip_compare:
                msg = ("[{}/{}] skipping compare of resource '{}/{}'.").format(
                    cluster, namespace, resource_type, name
                )
                logging.debug(msg)
            else:
                # If resource doesn't have annotations, annotate and apply
                if not c_item.has_qontract_annotations():
                    msg = (
                        "[{}/{}] resource '{}/{}' present "
                        "w/o annotations, annotating and applying"
                    ).format(cluster, namespace, resource_type, name)
                    logging.info(msg)

                # don't apply if there is a caller (saas file)
                # and this is not a take over
                # and current item caller is different from the current caller
                elif caller and not take_over and c_item.caller != caller:
                    # if the current item is owned by a caller that no longer exists,
                    # do nothing. the condition is nested so we fall into this condition
                    # so we end up either applying to take ownership, or we error if the
                    # current caller is still present
                    if c_item.caller in all_callers:
                        ri.register_error()
                        logging.error(
                            f"[{cluster}/{namespace}] resource '{resource_type}/{name}' present and managed by another caller: {c_item.caller}"
                        )
                        continue

                # don't apply if resources match
                # if there is a caller (saas file) and this is a take over
                # we skip the equal compare as it's not covering
                # cases of a removed label (for example)
                # d_item == c_item is uncommutative
                elif not (caller and take_over) and d_item == c_item:
                    msg = (
                        "[{}/{}] resource '{}/{}' present "
                        "and matches desired, skipping."
                    ).format(cluster, namespace, resource_type, name)
                    logging.debug(msg)
                    continue

                # don't apply if sha256sum hashes match
                elif c_item.sha256sum() == d_item.sha256sum():
                    if c_item.has_valid_sha256sum():
                        msg = (
                            "[{}/{}] resource '{}/{}' present "
                            "and hashes match, skipping."
                        ).format(cluster, namespace, resource_type, name)
                        logging.debug(msg)
                        continue
                    else:
                        msg = (
                            "[{}/{}] resource '{}/{}' present and "
                            "has stale sha256sum due to manual changes."
                        ).format(cluster, namespace, resource_type, name)
                        logging.info(msg)

                logging.debug("CURRENT: " + OR.serialize(OR.canonicalize(c_item.body)))
        else:
            logging.debug("CURRENT: None")

        logging.debug("DESIRED: " + OR.serialize(OR.canonicalize(d_item.body)))

        try:
            privileged = data["use_admin_token"].get(name, False)
            apply(
                dry_run,
                oc_map,
                cluster,
                namespace,
                resource_type,
                d_item,
                wait_for_namespace,
                recycle_pods,
                privileged,
            )
            action = {
                "action": ACTION_APPLIED,
                "cluster": cluster,
                "namespace": namespace,
                "kind": resource_type,
                "name": d_item.name,
                "privileged": privileged,
            }
            actions.append(action)
        except StatusCodeError as e:
            ri.register_error()
            err = (
                str(e)
                if resource_type != "Secret"
                else f"error applying Secret {d_item.name}: REDACTED"
            )
            msg = (
                f"[{cluster}/{namespace}] {err} "
                + f"(error details: {d_item.error_details})"
            )
            logging.error(msg)

    # current items
    for name, c_item in data["current"].items():
        d_item = data["desired"].get(name)
        if d_item is not None:
            continue

        if c_item.has_qontract_annotations():
            if caller and c_item.caller != caller:
                continue
        elif not take_over:
            # this is reached when the current resources:
            # - does not have qontract annotations (not managed)
            # - not taking over all resources of the current kind
            msg = (
                f"[{cluster}/{namespace}] skipping " + f"{resource_type}/{c_item.name}"
            )
            logging.debug(msg)
            continue

        if c_item.has_owner_reference():
            continue

        try:
            privileged = data["use_admin_token"].get(name, False)
            delete(
                dry_run,
                oc_map,
                cluster,
                namespace,
                resource_type,
                name,
                enable_deletion,
                privileged,
            )
            action = {
                "action": ACTION_DELETED,
                "cluster": cluster,
                "namespace": namespace,
                "kind": resource_type,
                "name": name,
                "privileged": privileged,
            }
            actions.append(action)
        except StatusCodeError as e:
            ri.register_error()
            msg = "[{}/{}] {}".format(cluster, namespace, str(e))
            logging.error(msg)

    return actions


def realize_data(
    dry_run,
    oc_map: OC_Map,
    ri: ResourceInventory,
    thread_pool_size,
    take_over=False,
    caller=None,
    all_callers=None,
    wait_for_namespace=False,
    no_dry_run_skip_compare=False,
    override_enable_deletion=None,
    recycle_pods=True,
):
    """
    Realize the current state to the desired state.

    :param dry_run: run in dry-run mode
    :param oc_map: a dictionary containing oc client per cluster
    :param ri: a ResourceInventory containing current and desired states
    :param thread_pool_size: Thread pool size to use for parallelism
    :param take_over: manage resource types in a namespace exclusively
    :param caller: name of the calling entity.
                   enables multiple running instances of the same integration
                   to deploy to the same namespace
    :param all_callers: names of all possible callers. used in conjunction with
                    caller to allow renaming of saas files.
    :param wait_for_namespace: wait for namespace to exist before applying
    :param no_dry_run_skip_compare: when running without dry-run, skip compare
    :param override_enable_deletion: override calculated enable_deletion value
    :param recycle_pods: should pods be recycled if a dependency changed
    """
    args = locals()
    del args["thread_pool_size"]
    results = threaded.run(_realize_resource_data, ri, thread_pool_size, **args)
    return list(itertools.chain.from_iterable(results))


def _validate_resources_used_exist(
    ri: ResourceInventory,
    oc: OCDeprecated,
    spec: Dict[str, Any],
    cluster: str,
    namespace: str,
    kind: str,
    name: str,
    used_kind: str,
) -> None:
    used_resources = oc.get_resources_used_in_pod_spec(
        spec, used_kind, include_optional=False
    )
    for used_name, used_keys in used_resources.items():
        # perhaps used resource is deployed together with the using resource?
        resource = ri.get_desired(cluster, namespace, used_kind, used_name)
        # if not, perhaps it's a secret that will be created from a Service's
        # serving-cert that is deployed along with the using resource?
        # lets iterate through all resources and find Services that have the annotation
        if not resource and used_kind == "Secret":
            # consider only Service resources that are in the same cluster & namespace
            service_resources = []
            for (cname, nname, restype, res) in ri:
                if cname == cluster and nname == namespace and restype == "Service":
                    service_resources.extend(res["desired"].values())
            # Check serving-cert-secret-name annotation on every considered resource
            for service in service_resources:
                metadata = service.body.get("metadata", {})
                annotations = metadata.get("annotations", {})
                serving_cert_alpha_secret_name = annotations.get(
                    "service.alpha.openshift.io/serving-cert-secret-name", False
                )
                serving_cert_beta_secret_name = annotations.get(
                    "service.beta.openshift.io/serving-cert-secret-name", False
                )
                # we found one! does it's value (secret name) match the
                # using resource's?
                if used_name in (
                    serving_cert_alpha_secret_name,
                    serving_cert_beta_secret_name,
                ):
                    # found a match. we assume the serving cert secret will
                    # be present at some point soon after the Service is deployed
                    resource = service
                    break

        if resource:
            # get the body to match with the possible result from oc.get
            resource = resource.body
        else:
            # no. perhaps used resource exists in the namespace?
            resource = oc.get(
                namespace, used_kind, name=used_name, allow_not_found=True
            )
        err_base = f"[{kind}/{name}] {used_kind} {used_name}"
        if not resource:
            # no. where is used resource hiding? we can't find it anywhere
            logging.error(f"{err_base} does not exist")
            ri.register_error()
            continue
        # here it is! let's make sure it has all the required keys
        missing_keys = (
            used_keys
            - resource.get("data", {}).keys()
            - resource.get("stringData", {}).keys()
        )
        if missing_keys:
            logging.error(f"{err_base} does not contain keys: {missing_keys}")
            ri.register_error()
            continue


def validate_planned_data(ri: ResourceInventory, oc_map: OC_Map) -> None:
    for cluster, namespace, kind, data in ri:
        oc = oc_map.get(cluster)

        for name, d_item in data["desired"].items():
            if kind in ("Deployment", "DeploymentConfig"):
                spec = d_item.body["spec"]["template"]["spec"]
                _validate_resources_used_exist(
                    ri, oc, spec, cluster, namespace, kind, name, "Secret"
                )
                _validate_resources_used_exist(
                    ri, oc, spec, cluster, namespace, kind, name, "ConfigMap"
                )


@retry(exceptions=(ValidationError), max_attempts=100)
def validate_realized_data(actions: Iterable[Dict[str, str]], oc_map: OC_Map):
    """
    Validate the realized desired state.

    :param oc_map: a dictionary containing oc client per cluster
    :param actions: a dictionary of performed actions
    """

    supported_kinds = [
        "Deployment",
        "DeploymentConfig",
        "StatefulSet",
        "Subscription",
        "Job",
        "ClowdApp",
        "ClowdJobInvocation",
    ]
    for action in actions:
        if action["action"] == ACTION_APPLIED:
            kind = action["kind"]
            if kind not in supported_kinds:
                continue
            cluster = action["cluster"]
            namespace = action["namespace"]
            name = action["name"]
            logging.info(["validating", cluster, namespace, kind, name])

            oc = oc_map.get(cluster)
            if not oc:
                logging.log(level=oc.log_level, msg=oc.message)
                continue
            resource = oc.get(namespace, kind, name=name)
            status = resource.get("status")
            if not status:
                raise ValidationError("status")
            # add elif to validate additional resource kinds
            if kind in ["Deployment", "DeploymentConfig", "StatefulSet"]:
                desired_replicas = resource["spec"]["replicas"]
                if desired_replicas == 0:
                    continue
                replicas = status.get("replicas")
                if replicas == 0:
                    continue
                updated_replicas = status.get("updatedReplicas")
                ready_replicas = status.get("readyReplicas")
                if (
                    not desired_replicas
                    == replicas
                    == ready_replicas
                    == updated_replicas
                ):
                    logging.info(
                        f"{kind} {name} has replicas that are not ready "
                        f"({ready_replicas} ready / {desired_replicas} total)"
                    )
                    raise ValidationError(name)
            elif kind == "Subscription":
                state = status.get("state")
                if state != "AtLatestKnown":
                    logging.info(
                        f"Subscription {name} state is invalid. "
                        f"Current state: {state}"
                    )
                    raise ValidationError(name)
            elif kind == "Job":
                succeeded = status.get("succeeded")
                if not succeeded:
                    logging.info(f"Job {name} has not succeeded")
                    conditions = status.get("conditions")
                    if conditions:
                        logging.info(f"Job conditions are: {conditions}")
                        logging.info(yaml.safe_dump(conditions))
                        for c in conditions:
                            if c.get("type") == "Failed":
                                msg = f"{name}: {c.get('reason')}"
                                raise ValidationErrorJobFailed(msg)
                    raise ValidationError(name)
            elif kind == "ClowdApp":
                deployments = status.get("deployments")
                if not deployments:
                    logging.info("ClowdApp has no deployments, status is invalid")
                    raise ValidationError(name)
                managed_deployments = deployments.get("managedDeployments")
                ready_deployments = deployments.get("readyDeployments")
                if managed_deployments != ready_deployments:
                    logging.info(
                        f"ClowdApp has deployments that are not ready "
                        f"({ready_deployments} ready / "
                        f"{managed_deployments} total)"
                    )
                    raise ValidationError(name)
            elif kind == "ClowdJobInvocation":
                completed = status.get("completed")
                jobs = status.get("jobMap", {})
                if jobs:
                    logging.info(f"CJI {name} jobs are: {jobs}")
                    logging.info(yaml.safe_dump(jobs))
                if completed:
                    failed_jobs = []
                    for job_name, job_state in jobs.items():
                        if job_state == "Failed":
                            failed_jobs.append(job_name)
                    if failed_jobs:
                        raise ValidationErrorJobFailed(
                            f"CJI {name} failed jobs: {failed_jobs}"
                        )
                else:
                    logging.info(f"CJI {name} has not completed")
                    conditions = status.get("conditions")
                    if conditions:
                        logging.info(f"CJI conditions are: {conditions}")
                        logging.info(yaml.safe_dump(conditions))
                    raise ValidationError(name)


def follow_logs(oc_map, actions, io_dir):
    """
    Collect the logs from the owned pods into files in io_dir.

    :param oc_map: a dictionary containing oc client per cluster
    :param actions: a dictionary of performed actions
    :param io_dir: a directory to store the logs as files
    """

    supported_kinds = ["Job", "ClowdJobInvocation"]
    for action in actions:
        if action["action"] == ACTION_APPLIED:
            kind = action["kind"]
            if kind not in supported_kinds:
                continue
            cluster = action["cluster"]
            namespace = action["namespace"]
            name = action["name"]
            logging.info(["collecting", cluster, namespace, kind, name])

            oc = oc_map.get(cluster)
            if not oc:
                logging.log(level=oc.log_level, msg=oc.message)
                continue

            if kind == "Job":
                oc.job_logs(namespace, name, follow=True, output=io_dir)
            if kind == "ClowdJobInvocation":
                resource = oc.get(namespace, kind, name=name)
                jobs = resource.get("status", {}).get("jobMap", {})
                for jn in jobs:
                    logging.info(["collecting", cluster, namespace, kind, jn])
                    oc.job_logs(namespace, jn, follow=True, output=io_dir)


def aggregate_shared_resources(namespace_info, shared_resources_type):
    """This function aggregates shared resources of the desired type
    from a shared resources file to the appropriate namespace section."""
    supported_shared_resources_types = [
        "openshiftResources",
        "openshiftServiceAccountTokens",
    ]
    if shared_resources_type not in supported_shared_resources_types:
        raise KeyError(
            f"shared_resource_type must be one of "
            f"{supported_shared_resources_types}."
        )
    shared_resources = namespace_info.get("sharedResources")
    namespace_type_resources = namespace_info.get(shared_resources_type)
    if shared_resources:
        shared_type_resources_items = []
        for shared_resources_item in shared_resources:
            shared_type_resources = shared_resources_item.get(shared_resources_type)
            if shared_type_resources:
                shared_type_resources_items.extend(shared_type_resources)
        if namespace_type_resources:
            namespace_type_resources.extend(shared_type_resources_items)
        else:
            namespace_type_resources = shared_type_resources_items
            namespace_info[shared_resources_type] = namespace_type_resources


def determine_user_key_for_access(cluster_info: dict) -> str:
    DEFAULT = "github_username"
    AUTH_METHOD_USER_KEY = {
        "github-org": "github_username",
        "github-org-team": "github_username",
        "oidc": "org_username",
    }
    cluster_auth = cluster_info["auth"]
    if not cluster_auth:
        # for backwards compatibility
        logging.debug(
            f"[{cluster_info['name']}] auth section missing, defaulting to: {DEFAULT}"
        )
        return DEFAULT

    service = cluster_auth["service"]
    try:
        return AUTH_METHOD_USER_KEY[service]
    except KeyError:
        raise NotImplementedError(
            f"[{cluster_info['name']}] auth service not implemented: {service}"
        )

import itertools
import logging
from collections import Counter
from collections.abc import (
    Iterable,
    Mapping,
    MutableMapping,
    Sequence,
)
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
    Protocol,
    runtime_checkable,
)

import yaml
from sretoolbox.utils import (
    retry,
    threaded,
)

from reconcile import queries
from reconcile.utils import (
    differ,
    metrics,
)
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.oc import (
    DeploymentFieldIsImmutableError,
    FieldIsImmutableError,
    InvalidValueApplyError,
    MayNotChangeOnceSetError,
    MetaDataAnnotationsTooLongApplyError,
    OC_Map,
    OCCli,
    OCClient,
    OCLogMsg,
    PrimaryClusterIPCanNotBeUnsetError,
    RequestEntityTooLargeError,
    StatefulSetUpdateForbiddenError,
    StatusCodeError,
    UnsupportedMediaTypeError,
)
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import (
    OpenshiftResourceInventoryGauge,
    ResourceInventory,
)
from reconcile.utils.three_way_diff_strategy import three_way_diff_using_hash

ACTION_APPLIED = "applied"
ACTION_DELETED = "deleted"
AUTH_METHOD_USER_KEY = {
    "github-org": "github_username",
    "github-org-team": "github_username",
    "oidc": "org_username",
    "rhidp": "org_username",
}


class ValidationError(Exception):
    pass


class ValidationErrorJobFailedError(Exception):
    pass


@dataclass
class BaseStateSpec:
    oc: OCClient = field(compare=False, repr=False)
    cluster: str
    namespace: str


@dataclass
class CurrentStateSpec(BaseStateSpec):
    kind: str
    resource_names: Iterable[str] | None


@dataclass
class DesiredStateSpec(BaseStateSpec):
    resource: Mapping[str, Any]
    parent: Mapping[Any, Any] = field(repr=False)
    privileged: bool = False


StateSpec = CurrentStateSpec | DesiredStateSpec


@runtime_checkable
class HasService(Protocol):
    """A service protocol."""

    service: str


class HasNameAndAuthService(Protocol):
    """A cluster name & auth protocol."""

    name: str

    @property
    def auth(self) -> Sequence[HasService]: ...


class HasOrgAndGithubUsername(Protocol):
    """An org and github username protocol."""

    org_username: str
    github_username: str


class ClusterMap(Protocol):
    """An OCMap protocol."""

    def get(self, cluster: str, privileged: bool = False) -> OCCli | OCLogMsg: ...

    def get_cluster(self, cluster: str, privileged: bool = False) -> OCCli: ...

    def clusters(
        self, include_errors: bool = False, privileged: bool = False
    ) -> list[str]: ...


def init_specs_to_fetch(
    ri: ResourceInventory,
    oc_map: ClusterMap,
    namespaces: Iterable[Mapping] | None = None,
    clusters: Iterable[Mapping] | None = None,
    override_managed_types: Iterable[str] | None = None,
    managed_types_key: str = "managedResourceTypes",
    cluster_admin: bool = False,
) -> list[StateSpec]:
    state_specs: list[StateSpec] = []

    if clusters and namespaces:
        raise KeyError("expected only one of clusters or namespaces.")
    if namespaces:
        for namespace_info in namespaces:
            if override_managed_types is None:
                managed_types = set(namespace_info.get(managed_types_key) or [])
            else:
                managed_types = set(override_managed_types)

            if not managed_types:
                continue

            cluster = namespace_info["cluster"]["name"]
            privileged = (
                namespace_info.get("clusterAdmin", False) is True or cluster_admin
            )
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
                ri.initialize_resource_type(
                    cluster, namespace, kind_to_use, managed_names
                )
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
            state_specs.extend(
                DesiredStateSpec(
                    oc=oc,
                    cluster=cluster,
                    namespace=namespace,
                    resource=openshift_resource,
                    parent=namespace_info,
                    privileged=privileged,
                )
                for openshift_resource in openshift_resources or []
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
    caller: str | None = None,
) -> None:
    # if spec.oc is None: - oc can't be none because init_namespace_specs_to_fetch does not create specs if oc is none
    #    return
    if not spec.oc.is_kind_supported(spec.kind):
        msg = f"[{spec.cluster}] cluster has no API resource {spec.kind}."
        logging.warning(msg)
        return
    try:
        for item in spec.oc.get_items(
            spec.kind,
            namespace=spec.namespace,
            resource_names=spec.resource_names,
        ):
            openshift_resource = OR(item, integration, integration_version)

            if caller and openshift_resource.caller != caller:
                continue

            ri.add_current(
                spec.cluster,
                spec.namespace,
                spec.kind,
                openshift_resource.name,
                openshift_resource,
            )
    except StatusCodeError as e:
        ri.register_error(cluster=spec.cluster)
        logging.error(f"[{spec.cluster}/{spec.namespace}] {e!s}")


def fetch_current_state(
    namespaces: Iterable[Mapping] | None = None,
    clusters: Iterable[Mapping] | None = None,
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE,
    integration: str | None = None,
    integration_version: str | None = None,
    override_managed_types: Iterable[str] | None = None,
    internal: bool | None = None,
    use_jump_host: bool = True,
    init_api_resources: bool = False,
    cluster_admin: bool = False,
    caller: str | None = None,
    init_projects: bool = False,
) -> tuple[ResourceInventory, OC_Map]:
    ri = ResourceInventory()
    settings = queries.get_app_interface_settings()
    oc_map = OC_Map(
        namespaces=namespaces,
        clusters=clusters,
        integration=integration or "",
        settings=settings,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
        init_api_resources=init_api_resources,
        cluster_admin=cluster_admin,
        init_projects=init_projects,
    )
    state_specs = init_specs_to_fetch(
        ri,
        oc_map,
        namespaces=namespaces,
        clusters=clusters,
        override_managed_types=override_managed_types,
        cluster_admin=cluster_admin,
    )
    threaded.run(
        populate_current_state,
        state_specs,
        thread_pool_size,
        ri=ri,
        integration=integration,
        integration_version=integration_version,
        caller=caller,
    )

    return ri, oc_map


@retry(max_attempts=30)
def wait_for_namespace_exists(oc: OCCli, namespace: str) -> None:
    if not oc.project_exists(namespace):
        raise StatusCodeError(f"namespace {namespace} does not exist")


def apply(
    dry_run: bool,
    oc_map: ClusterMap,
    cluster: str,
    namespace: str,
    resource_type: str,
    resource: OR,
    wait_for_namespace: bool,
    recycle_pods: bool = True,
    privileged: bool = False,
) -> None:
    logging.info([
        "apply",
        f"privileged={privileged}",
        cluster,
        namespace,
        resource_type,
        resource.name,
    ])

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
        except (
            MetaDataAnnotationsTooLongApplyError,
            UnsupportedMediaTypeError,
            RequestEntityTooLargeError,
        ):
            if not oc.get(
                namespace, resource_type, resource.name, allow_not_found=True
            ):
                oc.create(namespace, annotated)
            oc.replace(namespace, annotated)
        except FieldIsImmutableError:
            # Add more resources types to the list when you're
            # sure they're safe.
            if resource_type not in {"Route", "Service", "Secret", "Job"}:
                raise
            oc.delete(namespace=namespace, kind=resource_type, name=resource.name)
            oc.apply(namespace=namespace, resource=annotated)
        except DeploymentFieldIsImmutableError:
            logging.info(["replace", cluster, namespace, resource_type, resource.name])
            # spec.selector changes
            current_resource = oc.get(namespace, resource_type, resource.name)

            if current_resource["spec"]["strategy"]["type"] == "Recreate":
                oc.delete(namespace, resource_type, resource.name)
                oc.create(namespace, resource=annotated)
                return

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
            if resource_type != "Service":
                raise

            oc.delete(namespace=namespace, kind=resource_type, name=resource.name)
            oc.apply(namespace=namespace, resource=annotated)
        except StatefulSetUpdateForbiddenError:
            if resource_type != "StatefulSet":
                raise

            logging.info([
                "delete_sts_and_apply",
                cluster,
                namespace,
                resource_type,
                resource.name,
            ])
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


def create(
    dry_run: bool,
    oc_map: ClusterMap,
    cluster: str,
    namespace: str,
    resource_type: str,
    resource: OR,
) -> None:
    logging.info(["create", cluster, namespace, resource_type, resource.name])

    oc = oc_map.get(cluster)
    if isinstance(oc, OCLogMsg):
        logging.log(level=oc.log_level, msg=oc.message)
        return
    if not dry_run:
        annotated = resource.annotate()
        oc.create(namespace, annotated)


def delete(
    dry_run: bool,
    oc_map: ClusterMap,
    cluster: str,
    namespace: str,
    resource_type: str,
    name: str,
    enable_deletion: bool,
    privileged: bool = False,
) -> None:
    logging.info([
        "delete",
        f"privileged={privileged}",
        cluster,
        namespace,
        resource_type,
        name,
    ])

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


def check_unused_resource_types(ri: ResourceInventory) -> None:
    for cluster, namespace, resource_type, data in ri:
        if not data["desired"].items():
            msg = (
                f"[{cluster}/{namespace}] unused "
                + f"resource type: {resource_type}. please remove it "
                + "in a following PR."
            )
            logging.warning(msg)


@dataclass
class ApplyOptions:
    dry_run: bool
    no_dry_run_skip_compare: bool
    wait_for_namespace: bool
    recycle_pods: bool
    take_over: bool
    override_enable_deletion: bool | None
    caller: str | None
    all_callers: Sequence[str] | None
    privileged: bool | None
    enable_deletion: bool | None


def should_apply(
    current: OR,
    desired: OR,
    ri: ResourceInventory,
    options: ApplyOptions,
    cluster: str,
    name: str,
    namespace: str,
    resource_type: str,
) -> bool:
    if not options.dry_run and options.no_dry_run_skip_compare:
        msg = (
            f"[{cluster}/{namespace}] skipping compare of resource"
            f"'{resource_type}/{name}'"
        )
        logging.debug(msg)
        return True
    if (
        not options.take_over
        and options.caller
        and current.caller != options.caller
        and options.all_callers
        and current.caller in options.all_callers
    ):
        ri.register_error()
        logging.error(
            f"[{cluster}/{namespace}] resource '{resource_type}/{name}' present and "
            f"managed by another caller: {current.caller}"
        )
        return False

    if logging.getLogger().isEnabledFor(logging.DEBUG):
        logging.debug("CURRENT: " + OR.serialize(OR.canonicalize(current.body)))
        logging.debug("DESIRED: " + OR.serialize(OR.canonicalize(desired.body)))

    return True


def should_delete(
    current: OR,
    cluster: str,
    name: str,
    namespace: str,
    resource_type: str,
    options: ApplyOptions,
) -> bool:
    if current.has_qontract_annotations():
        if options.caller and current.caller != options.caller:
            return False
    elif not options.take_over:
        # this is reached when the current resources:
        # - does not have qontract annotations (not managed)
        # - not taking over all resources of the current kind
        msg = f"[{cluster}/{namespace}] skipping " + f"{resource_type}/{name}"
        logging.debug(msg)
        return False
    elif current.has_owner_reference():
        return False
    return True


def handle_new_resources(
    oc_map: ClusterMap,
    ri: ResourceInventory,
    new_resources: Mapping[Any, Any],
    cluster: str,
    namespace: str,
    resource_type: str,
    data: Mapping[Any, Any],
    options: ApplyOptions,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    for name, desired in new_resources.items():
        options.privileged = data["use_admin_token"].get(name, False)
        action = {
            "action": ACTION_APPLIED,
            "cluster": cluster,
            "namespace": namespace,
            "kind": resource_type,
            "name": name,
            "privileged": options.privileged,
        }
        actions.append(action)
        apply_action(
            oc_map=oc_map,
            ri=ri,
            cluster=cluster,
            namespace=namespace,
            resource_type=resource_type,
            resource=desired,
            options=options,
        )

    return actions


def should_take_over(
    current: OR,
    ri: ResourceInventory,
    options: ApplyOptions,
    cluster: str,
    name: str,
    namespace: str,
    resource_type: str,
) -> bool:
    if options.caller and options.caller != current.caller:
        # The resources are identical but the caller is different
        if options.take_over or (
            options.all_callers and current.caller not in options.all_callers
        ):
            return True
        else:
            ri.register_error()
            logging.error(
                f"[{cluster}/{namespace}] resource '{resource_type}/{name}' present "
                f"and managed by another caller: {current.caller}"
            )
    return False


def handle_identical_resources(
    oc_map: ClusterMap,
    ri: ResourceInventory,
    identical_resources: Mapping[Any, Any],
    cluster: str,
    namespace: str,
    resource_type: str,
    data: Mapping[Any, Any],
    options: ApplyOptions,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    for name, dp in identical_resources.items():
        if should_take_over(
            current=dp.current,
            ri=ri,
            cluster=cluster,
            name=name,
            namespace=namespace,
            resource_type=resource_type,
            options=options,
        ):
            options.privileged = data["use_admin_token"].get(name, False)
            action = {
                "action": ACTION_APPLIED,
                "cluster": cluster,
                "namespace": namespace,
                "kind": resource_type,
                "name": name,
                "privileged": options.privileged,
            }
            actions.append(action)
            apply_action(
                oc_map=oc_map,
                ri=ri,
                cluster=cluster,
                namespace=namespace,
                resource_type=resource_type,
                resource=dp.desired,
                options=options,
            )
    return actions


def handle_modified_resources(
    oc_map: ClusterMap,
    ri: ResourceInventory,
    modified_resources: Mapping[Any, Any],
    cluster: str,
    namespace: str,
    resource_type: str,
    data: Mapping[Any, Any],
    options: ApplyOptions,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    for name, dp in modified_resources.items():
        if should_apply(
            current=dp.current,
            desired=dp.desired,
            ri=ri,
            cluster=cluster,
            name=name,
            namespace=namespace,
            resource_type=resource_type,
            options=options,
        ):
            options.privileged = data["use_admin_token"].get(name, False)
            action = {
                "action": ACTION_APPLIED,
                "cluster": cluster,
                "namespace": namespace,
                "kind": resource_type,
                "name": name,
                "privileged": options.privileged,
            }
            actions.append(action)
            apply_action(
                oc_map=oc_map,
                ri=ri,
                cluster=cluster,
                namespace=namespace,
                resource_type=resource_type,
                resource=dp.desired,
                options=options,
            )
    return actions


def handle_deleted_resources(
    oc_map: ClusterMap,
    ri: ResourceInventory,
    deleted_resources: Mapping[Any, Any],
    cluster: str,
    namespace: str,
    resource_type: str,
    data: Mapping[Any, Any],
    options: ApplyOptions,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    for name, current in deleted_resources.items():
        if should_delete(
            current=current,
            cluster=cluster,
            name=name,
            namespace=namespace,
            resource_type=resource_type,
            options=options,
        ):
            options.privileged = data["use_admin_token"].get(name, False)
            action = {
                "action": ACTION_DELETED,
                "cluster": cluster,
                "namespace": namespace,
                "kind": resource_type,
                "name": name,
                "privileged": options.privileged,
            }
            actions.append(action)
            delete_action(
                oc_map=oc_map,
                ri=ri,
                cluster=cluster,
                namespace=namespace,
                resource_type=resource_type,
                resource_name=name,
                options=options,
            )

    return actions


def apply_action(
    oc_map: ClusterMap,
    ri: ResourceInventory,
    cluster: str,
    namespace: str,
    resource_type: str,
    resource: OR,
    options: ApplyOptions,
) -> None:
    try:
        apply(
            dry_run=options.dry_run,
            oc_map=oc_map,
            cluster=cluster,
            namespace=namespace,
            resource_type=resource_type,
            resource=resource,
            wait_for_namespace=options.wait_for_namespace,
            recycle_pods=options.recycle_pods,
            privileged=bool(options.privileged),
        )

    except StatusCodeError as e:
        ri.register_error()
        err = (
            str(e)
            if resource_type != "Secret"
            else f"error applying Secret {resource.name}: REDACTED"
        )
        msg = f"[{cluster}/{namespace}] {err} (error details: {resource.error_details})"
        logging.error(msg)


def delete_action(
    oc_map: ClusterMap,
    ri: ResourceInventory,
    cluster: str,
    namespace: str,
    resource_type: str,
    resource_name: str,
    options: ApplyOptions,
) -> None:
    try:
        delete(
            dry_run=options.dry_run,
            oc_map=oc_map,
            cluster=cluster,
            namespace=namespace,
            resource_type=resource_type,
            name=resource_name,
            enable_deletion=bool(options.enable_deletion),
            privileged=bool(options.privileged),
        )
    except StatusCodeError as e:
        ri.register_error()
        msg = f"[{cluster}/{namespace}] {e!s}"
        logging.error(msg)


def _realize_resource_data(
    ri_item: tuple[str, str, str, Mapping[str, Any]],
    dry_run: bool,
    oc_map: ClusterMap,
    ri: ResourceInventory,
    take_over: bool,
    caller: str,
    all_callers: Sequence[str],
    wait_for_namespace: bool,
    no_dry_run_skip_compare: bool,
    override_enable_deletion: bool,
    recycle_pods: bool,
) -> list[dict[str, Any]]:
    options = ApplyOptions(
        dry_run=dry_run,
        no_dry_run_skip_compare=no_dry_run_skip_compare,
        wait_for_namespace=wait_for_namespace,
        override_enable_deletion=override_enable_deletion,
        take_over=take_over,
        caller=caller,
        all_callers=all_callers,
        recycle_pods=recycle_pods,
        privileged=False,
        enable_deletion=False,
    )
    return _realize_resource_data_3way_diff(
        ri_item=ri_item, oc_map=oc_map, ri=ri, options=options
    )


def _realize_resource_data_3way_diff(
    ri_item: tuple[str, str, str, Mapping[str, Any]],
    oc_map: ClusterMap,
    ri: ResourceInventory,
    options: ApplyOptions,
) -> list[dict[str, Any]]:
    cluster, namespace, resource_type, data = ri_item

    actions: list[dict] = []

    if ri.has_error_registered(cluster=cluster):
        msg = f"[{cluster}] skipping realize_data for cluster with errors"
        logging.error(msg)
        return actions

    # don't delete resources if there are errors
    options.enable_deletion = not ri.has_error_registered()
    # only allow to override enable_deletion if no errors were found
    if options.enable_deletion and options.override_enable_deletion is False:
        options.enable_deletion = False

    diff_result = differ.diff_mappings(
        data["current"], data["desired"], equal=three_way_diff_using_hash
    )

    # identical resources need to be checked
    # for take_overs and saas file deprecations
    actions.extend(
        handle_identical_resources(
            oc_map=oc_map,
            ri=ri,
            identical_resources=diff_result.identical,
            cluster=cluster,
            namespace=namespace,
            resource_type=resource_type,
            data=data,
            options=options,
        )
    )

    actions.extend(
        handle_new_resources(
            oc_map=oc_map,
            ri=ri,
            new_resources=diff_result.add,
            cluster=cluster,
            namespace=namespace,
            resource_type=resource_type,
            data=data,
            options=options,
        )
    )

    actions.extend(
        handle_modified_resources(
            oc_map=oc_map,
            ri=ri,
            modified_resources=diff_result.change,
            cluster=cluster,
            namespace=namespace,
            resource_type=resource_type,
            data=data,
            options=options,
        )
    )

    actions.extend(
        handle_deleted_resources(
            oc_map=oc_map,
            ri=ri,
            deleted_resources=diff_result.delete,
            cluster=cluster,
            namespace=namespace,
            resource_type=resource_type,
            data=data,
            options=options,
        )
    )

    return actions


def realize_data(
    dry_run: bool,
    oc_map: ClusterMap,
    ri: ResourceInventory,
    thread_pool_size: int,
    take_over: bool = False,
    caller: str | None = None,
    all_callers: Sequence[str] | None = None,
    wait_for_namespace: bool = False,
    no_dry_run_skip_compare: bool = False,
    override_enable_deletion: bool | None = None,
    recycle_pods: bool = True,
) -> list[dict[str, Any]]:
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
    oc: OCCli,
    spec: dict[str, Any],
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
            for cname, nname, restype, res in ri:
                if cname == cluster and nname == namespace and restype == "Service":
                    service_resources.extend(res["desired"].values())
            # Check serving-cert-secret-name annotation on every considered resource
            for service in service_resources:
                metadata = service.body.get("metadata", {})
                annotations = metadata.get("annotations") or {}
                serving_cert_alpha_secret_name = annotations.get(
                    "service.alpha.openshift.io/serving-cert-secret-name", False
                )
                serving_cert_beta_secret_name = annotations.get(
                    "service.beta.openshift.io/serving-cert-secret-name", False
                )
                # we found one! does it's value (secret name) match the
                # using resource's?
                if used_name in {
                    serving_cert_alpha_secret_name,
                    serving_cert_beta_secret_name,
                }:
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
        err_base = f"[{cluster}/{namespace}] [{kind}/{name}] {used_kind} {used_name}"
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


def validate_planned_data(ri: ResourceInventory, oc_map: ClusterMap) -> None:
    for cluster, namespace, kind, data in ri:
        oc = oc_map.get_cluster(cluster)

        for name, d_item in data["desired"].items():
            if kind in {"Deployment", "DeploymentConfig"}:
                spec = d_item.body["spec"]["template"]["spec"]
                _validate_resources_used_exist(
                    ri, oc, spec, cluster, namespace, kind, name, "Secret"
                )
                _validate_resources_used_exist(
                    ri, oc, spec, cluster, namespace, kind, name, "ConfigMap"
                )


@retry(exceptions=(ValidationError), max_attempts=200)
def validate_realized_data(
    actions: Iterable[dict[str, str]], oc_map: ClusterMap
) -> None:
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
            if isinstance(oc, OCLogMsg):
                logging.log(level=oc.log_level, msg=oc.message)
                continue
            resource = oc.get(namespace, kind, name=name)
            status = resource.get("status")
            if not status:
                raise ValidationError("status")
            # add elif to validate additional resource kinds
            if kind in {"Deployment", "DeploymentConfig", "StatefulSet"}:
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
                        f"Subscription {name} state is invalid. Current state: {state}"
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
                                raise ValidationErrorJobFailedError(msg)
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
                        raise ValidationErrorJobFailedError(
                            f"CJI {name} failed jobs: {failed_jobs}"
                        )
                else:
                    logging.info(f"CJI {name} has not completed")
                    conditions = status.get("conditions")
                    if conditions:
                        logging.info(f"CJI conditions are: {conditions}")
                        logging.info(yaml.safe_dump(conditions))
                    raise ValidationError(name)


def follow_logs(
    oc_map: ClusterMap, actions: Iterable[Mapping[str, Any]], io_dir: str
) -> None:
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
            if isinstance(oc, OCLogMsg):
                logging.log(level=oc.log_level, msg=oc.message)
                continue

            if kind == "Job":
                oc.job_logs(namespace, name, follow=True, output=io_dir)
            if kind == "ClowdJobInvocation":
                if isinstance(oc, OCLogMsg):
                    logging.log(level=oc.log_level, msg=oc.message)
                    continue
                resource = oc.get(namespace, kind, name=name)
                jobs = resource.get("status", {}).get("jobMap", {})
                for jn in jobs:
                    logging.info(["collecting", cluster, namespace, kind, jn])
                    if isinstance(oc, OCLogMsg):
                        logging.log(level=oc.log_level, msg=oc.message)
                        continue
                    oc.job_logs(namespace, jn, follow=True, output=io_dir)


def aggregate_shared_resources(
    namespace_info: MutableMapping[str, Any], shared_resources_type: str
) -> None:
    """This function aggregates shared resources of the desired type
    from a shared resources file to the appropriate namespace section."""
    supported_shared_resources_types = [
        "openshiftResources",
        "openshiftServiceAccountTokens",
    ]
    if shared_resources_type not in supported_shared_resources_types:
        raise KeyError(
            f"shared_resource_type must be one of {supported_shared_resources_types}."
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


@runtime_checkable
class HasOpenShiftResources(Protocol):
    openshift_resources: list | None


@runtime_checkable
class HasOpenshiftServiceAccountTokens(Protocol):
    openshift_service_account_tokens: list | None


@runtime_checkable
class HasSharedResourcesOpenShiftResources(Protocol):
    @property
    def shared_resources(self) -> Sequence[HasOpenShiftResources] | None: ...


@runtime_checkable
class HasSharedResourcesOpenshiftServiceAccountTokens(Protocol):
    @property
    def shared_resources(self) -> Sequence[HasOpenshiftServiceAccountTokens] | None: ...


@runtime_checkable
class HasOpenshiftServiceAccountTokensAndSharedResources(
    HasOpenshiftServiceAccountTokens,
    HasSharedResourcesOpenshiftServiceAccountTokens,
    Protocol,
): ...


@runtime_checkable
class HasOpenShiftResourcesAndSharedResources(
    HasOpenShiftResources, HasSharedResourcesOpenShiftResources, Protocol
): ...


def aggregate_shared_resources_typed(
    namespace: HasOpenshiftServiceAccountTokensAndSharedResources
    | HasOpenShiftResourcesAndSharedResources,
) -> None:
    """This function aggregates the shared resources to the appropriate namespace section.

    Attention: It updates the namespace object in place and isn't indempotent!
    """
    if not namespace.shared_resources:
        return

    match namespace:
        case HasOpenshiftServiceAccountTokensAndSharedResources():
            shared_type_resources_items = []
            for ost_shared_resources_item in namespace.shared_resources:
                if (
                    shared_type_resources
                    := ost_shared_resources_item.openshift_service_account_tokens
                ):
                    shared_type_resources_items.extend(shared_type_resources)
            if namespace.openshift_service_account_tokens:
                namespace.openshift_service_account_tokens.extend(
                    shared_type_resources_items
                )
            else:
                namespace.openshift_service_account_tokens = shared_type_resources_items
        case HasOpenShiftResourcesAndSharedResources():
            shared_type_resources_items = []
            for or_shared_resources_item in namespace.shared_resources:
                if (
                    shared_type_resources
                    := or_shared_resources_item.openshift_resources
                ):
                    shared_type_resources_items.extend(shared_type_resources)
            if namespace.openshift_resources:
                namespace.openshift_resources.extend(shared_type_resources_items)
            else:
                namespace.openshift_resources = shared_type_resources_items


def determine_user_keys_for_access(
    cluster_name: str,
    auth_list: Sequence[dict[str, str] | HasService],
    enforced_user_keys: list[str] | None = None,
) -> list[str]:
    """Return user keys based on enabled cluster authentication methods."""

    user_keys: list[str] = []

    if enforced_user_keys:
        # return enforced user keys if provided
        return enforced_user_keys

    # for backward compatibility. some clusters don't have auth objects
    if not auth_list:
        return ["github_username"]

    for auth in auth_list:
        service = auth.service if isinstance(auth, HasService) else auth["service"]
        try:
            if AUTH_METHOD_USER_KEY[service] in user_keys:
                continue
            user_keys.append(AUTH_METHOD_USER_KEY[service])
        except KeyError:
            raise NotImplementedError(
                f"[{cluster_name}] auth service not implemented: {service}"
            ) from None
    return user_keys


def is_namespace_deleted(namespace_info: Mapping) -> bool:
    return bool(namespace_info.get("delete"))


def user_has_cluster_access(
    user: HasOrgAndGithubUsername,
    cluster: HasNameAndAuthService,
    cluster_users: Sequence[str],
) -> bool:
    """Check user has access to cluster."""
    userkeys = determine_user_keys_for_access(cluster.name, cluster.auth)
    return any(getattr(user, userkey) in cluster_users for userkey in userkeys)


def get_namespace_type_overrides(namespace: Mapping) -> dict[str, str]:
    """Returns a dict with the type overrides defined in a namespace

    :param namespace: the namespace
    :return: dict with the the type overrides
    """
    return {
        o["resource"]: o["override"]
        for o in namespace.get("managedResourceTypeOverrides") or []
    }


def get_namespace_resource_types(
    namespace: Mapping, type_overrides: dict[str, str] | None = None
) -> list[str]:
    """Returns a list with the namespace ResourceTypes, with the overrides in place

    :param namespace: the namespace
    :param type_overrides: dict with the namespace type overrides
    :return: Definitive managed resource TYPES for a namespace
    """
    if not type_overrides:
        type_overrides = get_namespace_type_overrides(namespace)

    return [
        type_overrides.get(t, t) for t in namespace.get("managedResourceTypes") or []
    ]


def get_namespace_resource_names(
    namespace: Mapping, type_overrides: dict[str, str] | None = None
) -> dict[str, list[str]]:
    """Returns a list with the namespace ResourceTypeNames, with the overrides in place

    :param namespace: the namespace
    :param type_overrides: dict with the namespace type overrides
    :return: Definitive managed resource NAMES for a namespace
    """
    if not type_overrides:
        type_overrides = get_namespace_type_overrides(namespace)
    rnames: dict[str, list[str]] = {}

    for item in namespace.get("managedResourceNames") or []:
        kind = type_overrides.get(item["resource"], item["resource"])
        ref = rnames.setdefault(kind, [])
        ref += item["resourceNames"]

    return rnames


def publish_metrics(ri: ResourceInventory, integration: str) -> None:
    for cluster, namespace, kind, data in ri:
        for state in ("current", "desired"):
            metrics.set_gauge(
                OpenshiftResourceInventoryGauge(
                    integration=integration.replace("_", "-"),
                    cluster=cluster,
                    namespace=namespace,
                    kind=kind,
                    state=state,
                ),
                len(data[state]),
            )


def get_state_count_combinations(state: Iterable[Mapping[str, str]]) -> Counter[str]:
    return Counter(s["cluster"] for s in state)


def publish_cluster_desired_metrics_from_state(
    state: Iterable[Mapping[str, str]], integration: str, kind: str
) -> None:
    for cluster, count in get_state_count_combinations(state).items():
        metrics.set_gauge(
            OpenshiftResourceInventoryGauge(
                integration=integration,
                cluster=cluster,
                namespace="cluster",
                kind=kind,
                state="desired",
            ),
            count,
        )

import logging

import utils.threaded as threaded
import reconcile.queries as queries

from utils.oc import OC_Map
from utils.oc import (StatusCodeError,
                      InvalidValueApplyError,
                      MetaDataAnnotationsTooLongApplyError,
                      UnsupportedMediaTypeError)
from utils.openshift_resource import (OpenshiftResource as OR,
                                      ResourceInventory)

from sretoolbox.utils import retry

ACTION_APPLIED = 'applied'
ACTION_DELETED = 'deleted'


class ValidationError(Exception):
    pass


class StateSpec(object):
    def __init__(self, type, oc, cluster, namespace, resource, parent=None,
                 resource_type_override=None, resource_names=None):
        self.type = type
        self.oc = oc
        self.cluster = cluster
        self.namespace = namespace
        self.resource = resource
        self.parent = parent
        self.resource_type_override = resource_type_override
        self.resource_names = resource_names


def init_specs_to_fetch(ri, oc_map,
                        namespaces=None,
                        clusters=None,
                        override_managed_types=None,
                        managed_types_key='managedResourceTypes'):
    state_specs = []

    if clusters and namespaces:
        raise KeyError('expected only one of clusters or namespaces.')
    elif namespaces:
        for namespace_info in namespaces:
            if override_managed_types is None:
                managed_types = namespace_info.get(managed_types_key)
            else:
                managed_types = override_managed_types

            if not managed_types:
                continue

            cluster = namespace_info['cluster']['name']
            oc = oc_map.get(cluster)
            if oc is None:
                msg = f"[{cluster}] cluster skipped."
                logging.debug(msg)
                continue
            if oc is False:
                ri.register_error()
                msg = f"[{cluster}] cluster has no automationToken."
                logging.error(msg)
                continue

            namespace = namespace_info['name']
            managed_resource_names = \
                namespace_info.get('managedResourceNames')
            managed_resource_type_overrides = \
                namespace_info.get('managedResourceTypeOverrides')

            # Initialize current state specs
            for resource_type in managed_types:
                ri.initialize_resource_type(cluster, namespace, resource_type)
                # Handle case of specific managed resources
                resource_names = \
                    [mrn['resourceNames'] for mrn in managed_resource_names
                     if mrn['resource'] == resource_type] \
                    if managed_resource_names else None
                # Handle case of resource type override
                resource_type_override = \
                    [mnto['override'] for mnto
                     in managed_resource_type_overrides
                     if mnto['resource'] == resource_type] \
                    if managed_resource_type_overrides else None
                # If not None, there is a single element in the list
                if resource_names:
                    [resource_names] = resource_names
                if resource_type_override:
                    [resource_type_override] = resource_type_override
                c_spec = StateSpec(
                    "current", oc, cluster, namespace,
                    resource_type,
                    resource_type_override=resource_type_override,
                    resource_names=resource_names)
                state_specs.append(c_spec)

            # Initialize desired state specs
            openshift_resources = namespace_info.get('openshiftResources')
            for openshift_resource in openshift_resources or []:
                d_spec = StateSpec("desired", oc, cluster, namespace,
                                   openshift_resource, namespace_info)
                state_specs.append(d_spec)
    elif clusters:
        # set namespace to something indicative
        namespace = 'cluster'
        for cluster_info in clusters or []:
            cluster = cluster_info['name']
            oc = oc_map.get(cluster)
            if oc is None:
                msg = f"[{cluster}] cluster skipped."
                logging.debug(msg)
                continue
            if oc is False:
                ri.register_error()
                msg = f"[{cluster}] cluster has no automationToken."
                logging.error(msg)
                continue

            # we currently only use override_managed_types,
            # and not allow a `managedResourcesTypes` field in a cluster file
            for resource_type in override_managed_types or []:
                ri.initialize_resource_type(cluster, namespace, resource_type)
                # Initialize current state specs
                c_spec = StateSpec("current", oc, cluster, namespace,
                                   resource_type)
                state_specs.append(c_spec)
                # Initialize desired state specs
                d_spec = StateSpec("desired", oc, cluster, namespace,
                                   resource_type)
                state_specs.append(d_spec)
    else:
        raise KeyError('expected one of clusters or namespaces.')

    return state_specs


def populate_current_state(spec, ri, integration, integration_version):
    oc = spec.oc
    if oc is None:
        return
    api_resources = oc.api_resources
    if api_resources and spec.resource not in api_resources:
        msg = f"[{spec.cluster}] cluster has no API resource {spec.resource}."
        logging.warning(msg)
        return
    for item in oc.get_items(spec.resource,
                             namespace=spec.namespace,
                             resource_names=spec.resource_names):
        openshift_resource = OR(item,
                                integration,
                                integration_version)
        ri.add_current(
            spec.cluster,
            spec.namespace,
            spec.resource,
            openshift_resource.name,
            openshift_resource
        )


def fetch_current_state(namespaces=None,
                        clusters=None,
                        thread_pool_size=None,
                        integration=None,
                        integration_version=None,
                        override_managed_types=None,
                        internal=None,
                        use_jump_host=True,
                        init_api_resources=False):
    ri = ResourceInventory()
    settings = queries.get_app_interface_settings()
    oc_map = OC_Map(namespaces=namespaces,
                    clusters=clusters,
                    integration=integration,
                    settings=settings,
                    internal=internal,
                    use_jump_host=use_jump_host,
                    thread_pool_size=thread_pool_size,
                    init_api_resources=init_api_resources)
    state_specs = \
        init_specs_to_fetch(
            ri,
            oc_map,
            namespaces=namespaces,
            clusters=clusters,
            override_managed_types=override_managed_types
        )
    threaded.run(populate_current_state, state_specs, thread_pool_size,
                 ri=ri,
                 integration=integration,
                 integration_version=integration_version)

    return ri, oc_map


@retry(max_attempts=20)
def wait_for_namespace_exists(oc, namespace):
    if not oc.project_exists(namespace):
        raise Exception(f'namespace {namespace} does not exist')


def apply(dry_run, oc_map, cluster, namespace, resource_type, resource,
          wait_for_namespace):
    logging.info(['apply', cluster, namespace, resource_type, resource.name])

    oc = oc_map.get(cluster)
    if not dry_run:
        annotated = resource.annotate()
        # skip if namespace does not exist (as it will soon)
        # do not skip if this is a cluster scoped integration
        if namespace != 'cluster' and not oc.project_exists(namespace):
            msg = f"[{cluster}/{namespace}] namespace does not exist (yet)."
            if wait_for_namespace:
                logging.info(msg + ' waiting...')
                wait_for_namespace_exists(oc, namespace)
            else:
                logging.warning(msg)
                return

        try:
            oc.apply(namespace, annotated.toJSON())
        except InvalidValueApplyError:
            oc.remove_last_applied_configuration(
                namespace, resource_type, resource.name)
            oc.apply(namespace, annotated.toJSON())
        except (MetaDataAnnotationsTooLongApplyError,
                UnsupportedMediaTypeError):
            oc.replace(namespace, annotated.toJSON())

    oc.recycle_pods(dry_run, namespace, resource_type, resource)


def delete(dry_run, oc_map, cluster, namespace, resource_type, name,
           enable_deletion):
    logging.info(['delete', cluster, namespace, resource_type, name])

    if not enable_deletion:
        logging.error('\'delete\' action is disabled due to previous errors.')
        return

    if not dry_run:
        oc_map.get(cluster).delete(namespace, resource_type, name)


def check_unused_resource_types(ri):
    for cluster, namespace, resource_type, data in ri:
        if not data['desired'].items():
            msg = f'[{cluster}/{namespace}] unused ' + \
                f'resource type: {resource_type}. please remove it ' + \
                f'in a following PR.'
            logging.warning(msg)


def realize_data(dry_run, oc_map, ri,
                 take_over=False,
                 caller=None,
                 wait_for_namespace=False,
                 no_dry_run_skip_compare=False):
    """
    Realize the current state to the desired state.

    :param dry_run: run in dry-run mode
    :param oc_map: a dictionary containing oc client per cluster
    :param ri: a ResourceInventory containing current and desired states
    :param take_over: manage resource types in a namespace exclusively
    :param caller: name of the calling entity.
                   enables multiple running instances of the same integration
                   to deploy to the same namespace
    :param wait_for_namespace: wait for namespace to exist before applying
    :param no_dry_run_skip_compare: when running without dry-run, skip compare
    """
    actions = []
    enable_deletion = False if ri.has_error_registered() else True

    for cluster, namespace, resource_type, data in ri:
        # desired items
        for name, d_item in data['desired'].items():
            c_item = data['current'].get(name)

            if c_item is not None:
                if not dry_run and no_dry_run_skip_compare:
                    msg = (
                        "[{}/{}] skipping compare of resource '{}/{}'."
                    ).format(cluster, namespace, resource_type, name)
                    logging.debug(msg)
                else:
                    # If resource doesn't have annotations, annotate and apply
                    if not c_item.has_qontract_annotations():
                        msg = (
                            "[{}/{}] resource '{}/{}' present "
                            "w/o annotations, annotating and applying"
                        ).format(cluster, namespace, resource_type, name)
                        logging.info(msg)

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

                    logging.debug("CURRENT: " +
                                  OR.serialize(OR.canonicalize(c_item.body)))
            else:
                logging.debug("CURRENT: None")

            logging.debug("DESIRED: " +
                          OR.serialize(OR.canonicalize(d_item.body)))

            try:
                apply(dry_run, oc_map, cluster, namespace,
                      resource_type, d_item, wait_for_namespace)
                action = {
                    'action': ACTION_APPLIED,
                    'cluster': cluster,
                    'namespace': namespace,
                    'kind': resource_type,
                    'name': d_item.name
                }
                actions.append(action)
            except StatusCodeError as e:
                ri.register_error()
                msg = "[{}/{}] {} (error details: {})".format(
                    cluster, namespace, str(e), d_item.error_details)
                logging.error(msg)

        # current items
        for name, c_item in data['current'].items():
            d_item = data['desired'].get(name)
            if d_item is not None:
                continue

            if c_item.has_qontract_annotations():
                if caller and c_item.caller != caller:
                    continue
            elif not take_over:
                continue

            try:
                delete(dry_run, oc_map, cluster, namespace,
                       resource_type, name, enable_deletion)
                action = {
                    'action': ACTION_DELETED,
                    'cluster': cluster,
                    'namespace': namespace,
                    'kind': resource_type,
                    'name': name
                }
                actions.append(action)
            except StatusCodeError as e:
                ri.register_error()
                msg = "[{}/{}] {}".format(cluster, namespace, str(e))
                logging.error(msg)

    return actions


@retry(exceptions=(ValidationError), max_attempts=100)
def validate_data(oc_map, actions):
    """
    Validate the realized desired state.

    :param oc_map: a dictionary containing oc client per cluster
    :param actions: a dictionary of performed actions
    """

    supported_kinds = [
        'Deployment',
        'DeploymentConfig',
        'Subscription',
        'Job'
    ]
    for action in actions:
        if action['action'] == ACTION_APPLIED:
            kind = action['kind']
            if kind not in supported_kinds:
                continue
            cluster = action['cluster']
            namespace = action['namespace']
            name = action['name']
            logging.info(['validating', cluster, namespace, kind, name])

            oc = oc_map.get(cluster)
            resource = oc.get(namespace, kind, name=name)
            status = resource.get('status')
            if not status:
                raise ValidationError('status')
            # add elif to validate additional resource kinds
            if kind in ['Deployment', 'DeploymentConfig']:
                desired_replicas = resource['spec']['replicas']
                if desired_replicas == 0:
                    continue
                replicas = status.get('replicas')
                if replicas == 0:
                    continue
                updated_replicas = status.get('updatedReplicas')
                ready_replicas = status.get('readyReplicas')
                if not desired_replicas == replicas == \
                        ready_replicas == updated_replicas:
                    logging.info('new replicas not ready, status is invalid')
                    raise ValidationError(name)
            elif kind == 'Subscription':
                state = status.get('state')
                if state != 'AtLatestKnown':
                    logging.info('Subscription status.state is invalid')
                    raise ValidationError(name)
            elif kind == 'Job':
                succeeded = status.get('succeeded')
                if not succeeded:
                    logging.info('Job has not succeeded, status is invalid')
                    raise ValidationError(name)


def follow_logs(oc_map, actions, io_dir):
    """
    Collect the logs from the owned pods into files in io_dir.

    :param oc_map: a dictionary containing oc client per cluster
    :param actions: a dictionary of performed actions
    :param io_dir: a directory to store the logs as files
    """

    supported_kinds = [
        'Job'
    ]
    for action in actions:
        if action['action'] == ACTION_APPLIED:
            kind = action['kind']
            if kind not in supported_kinds:
                continue
            cluster = action['cluster']
            namespace = action['namespace']
            name = action['name']
            logging.info(['collecting', cluster, namespace, kind, name])

            oc = oc_map.get(cluster)
            oc.job_logs(namespace, name, follow=True, output=io_dir)


def aggregate_shared_resources(namespace_info, shared_resources_type):
    """ This function aggregates shared resources of the desired type
    from a shared resources file to the appropriate namespace section. """
    supported_shared_resources_types = [
        'openshiftResources',
        'openshiftServiceAccountTokens'
    ]
    if shared_resources_type not in supported_shared_resources_types:
        raise KeyError(
            f'shared_resource_type must be one of '
            f'{supported_shared_resources_types}.'
        )
    shared_resources = namespace_info.get('sharedResources')
    namespace_type_resources = namespace_info.get(shared_resources_type)
    if shared_resources:
        shared_type_resources_items = []
        for shared_resources_item in shared_resources:
            shared_type_resources = \
                shared_resources_item.get(shared_resources_type)
            if shared_type_resources:
                shared_type_resources_items.extend(shared_type_resources)
        if namespace_type_resources:
            namespace_type_resources.extend(shared_type_resources_items)
        else:
            namespace_type_resources = shared_type_resources_items
            namespace_info[shared_resources_type] = namespace_type_resources

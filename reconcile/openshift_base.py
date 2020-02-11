import logging

import utils.threaded as threaded
import reconcile.queries as queries

from utils.oc import OC_Map
from utils.oc import StatusCodeError
from utils.openshift_resource import (OpenshiftResource as OR,
                                      ResourceInventory)


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
    if spec.oc is None:
        return
    for item in spec.oc.get_items(spec.resource,
                                  namespace=spec.namespace):
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
                        internal=None):
    ri = ResourceInventory()
    settings = queries.get_app_interface_settings()
    oc_map = OC_Map(namespaces=namespaces,
                    clusters=clusters,
                    integration=integration,
                    settings=settings,
                    internal=internal)
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


def apply(dry_run, oc_map, cluster, namespace, resource_type, resource):
    logging.info(['apply', cluster, namespace, resource_type, resource.name])

    oc = oc_map.get(cluster)
    if not dry_run:
        annotated = resource.annotate()
        # skip if namespace does not exist (as it will soon)
        # do not skip if this is a cluster scoped integration
        if namespace != 'cluster' and not oc.project_exists(namespace):
            msg = f"[{cluster}/{namespace}] namespace does not exist (yet)"
            logging.warning(msg)
            return

        oc.apply(namespace, annotated.toJSON())

    oc.recycle_pods(dry_run, namespace, resource_type, resource)


def delete(dry_run, oc_map, cluster, namespace, resource_type, name,
           enable_deletion):
    # this section is only relevant for the terraform integrations
    if not enable_deletion:
        logging.error(['delete', cluster, namespace, resource_type, name])
        logging.error('\'delete\' action is not enabled. ' +
                      'Please run the integration manually ' +
                      'with the \'--enable-deletion\' flag.')
        return

    logging.info(['delete', cluster, namespace, resource_type, name])

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
                 enable_deletion=True,
                 take_over=False):
    for cluster, namespace, resource_type, data in ri:
        # desired items
        for name, d_item in data['desired'].items():
            c_item = data['current'].get(name)

            if c_item is not None:
                #  If resource doesn't have annotations, annotate and apply
                if not c_item.has_qontract_annotations():
                    msg = (
                        "[{}/{}] resource '{}/{}' present "
                        "w/o annotations, annotating and applying"
                    ).format(cluster, namespace, resource_type, name)
                    logging.info(msg)

                # don't apply if resources match
                elif d_item == c_item:
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
                            "[{}/{}] resource '{}/{}' present "
                            "and has stale sha256sum due to manual changes."
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
                      resource_type, d_item)
            except StatusCodeError as e:
                ri.register_error()
                msg = "[{}/{}] {}".format(cluster, namespace, str(e))
                logging.error(msg)

        # current items
        for name, c_item in data['current'].items():
            d_item = data['desired'].get(name)
            if d_item is not None:
                continue

            if not c_item.has_qontract_annotations():
                if not take_over:
                    continue
            try:
                delete(dry_run, oc_map, cluster, namespace,
                       resource_type, name, enable_deletion)
            except StatusCodeError as e:
                ri.register_error()
                msg = "[{}/{}] {}".format(cluster, namespace, str(e))
                logging.error(msg)

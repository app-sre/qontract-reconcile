import logging

import utils.threaded as threaded

from utils.oc import OC_Map
from utils.oc import StatusCodeError
from utils.openshift_resource import (OpenshiftResource as OR,
                                      ResourceInventory)


class StateSpec(object):
    def __init__(self, type, oc, cluster, namespace, resource, parent=None):
        self.type = type
        self.oc = oc
        self.cluster = cluster
        self.namespace = namespace
        self.resource = resource
        self.parent = parent


def init_cluster_specs_to_fetch(clusters, ri, oc_map,
                                override_managed_types,
                                managed_types_key='managedResourceTypes'):
    state_specs = []

    for cluster in clusters:
        if override_managed_types is None:
            managed_types = cluster.get(managed_types_key)
        else:
            managed_types = override_managed_types

        if not managed_types:
            continue

        cluster_name = cluster['name']
        oc = oc_map.get(cluster_name)
        if oc is None:
            msg = (
                "[{}] cluster skipped."
            ).format(cluster)
            logging.debug(msg)
            continue
        if oc is False:
            ri.register_error()
            msg = (
                "[{}] cluster has no automationToken."
            ).format(cluster)
            logging.error(msg)
            continue

        for resource_type in managed_types:
            ri.initialize_resource_type(cluster_name, None, resource_type)
            c_spec = StateSpec("current",
                               oc,
                               cluster_name,
                               None,
                               resource_type)
            state_specs.append(c_spec)

    return state_specs


def init_namespaced_specs_to_fetch(namespaces, ri, oc_map,
                                   override_managed_types,
                                   managed_types_key='managedResourceTypes'):
    state_specs = []

    for namespace_info in namespaces:
        if override_managed_types is None:
            managed_types = namespace_info.get(managed_types_key)
        else:
            managed_types = override_managed_types

        if not managed_types:
            continue

        cluster = namespace_info['cluster']['name']
        namespace = namespace_info['name']

        oc = oc_map.get(cluster)
        if oc is None:
            msg = (
                "[{}] cluster skipped."
            ).format(cluster)
            logging.debug(msg)
            continue
        if oc is False:
            ri.register_error()
            msg = (
                "[{}/{}] cluster has no automationToken."
            ).format(cluster, namespace)
            logging.error(msg)
            continue

        # Initialize current state specs
        for resource_type in managed_types:
            ri.initialize_resource_type(cluster, namespace, resource_type)
            c_spec = StateSpec("current", oc, cluster, namespace,
                               resource_type)
            state_specs.append(c_spec)

        # Initialize desired state specs
        openshift_resources = namespace_info.get('openshiftResources') or []
        for openshift_resource in openshift_resources:
            d_spec = StateSpec("desired", oc, cluster, namespace,
                               openshift_resource, namespace_info)
            state_specs.append(d_spec)

    return state_specs


def init_specs_to_fetch(clusters=None, namespaces=None,
                        ri=None, oc_map=None,
                        override_managed_types=None,
                        managed_types_key='managedResourceTypes'):
    if clusters and namespaces:
        raise KeyError('expected only one of clusters or namespaces.')
    elif clusters:
        state_specs = init_cluster_specs_to_fetch(clusters, ri, oc_map,
                                                  override_managed_types,
                                                  managed_types_key)
    elif namespaces:
        state_specs = init_namespaced_specs_to_fetch(namespaces, ri, oc_map,
                                                     override_managed_types,
                                                     managed_types_key)
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


def fetch_current_state(clusters=None, namespaces=None,
                        thread_pool_size=None,
                        integration=None,
                        integration_version=None,
                        override_managed_types=None):
    ri = ResourceInventory()

    if clusters and namespaces:
        raise KeyError('expected only one of clusters or namespaces.')
    elif clusters:
        oc_map = OC_Map(clusters=clusters, integration=integration)
        state_specs = \
            init_specs_to_fetch(
                ri=ri,
                oc_map=oc_map,
                clusters=clusters,
                override_managed_types=override_managed_types
            )
    elif namespaces:
        oc_map = OC_Map(namespaces=namespaces, integration=integration)
        state_specs = \
            init_specs_to_fetch(
                ri=ri,
                oc_map=oc_map,
                namespaces=namespaces,
                override_managed_types=override_managed_types
            )
    else:
        raise KeyError('expected one of clusters or namespaces.')

    threaded.run(populate_current_state, state_specs, thread_pool_size,
                 ri=ri,
                 integration=integration,
                 integration_version=integration_version)

    return ri, oc_map


def apply(dry_run, oc_map, cluster, namespace, resource_type, resource):
    logging.info(['apply', cluster, namespace, resource_type, resource.name])

    if not dry_run:
        annotated = resource.annotate()
        oc_map.get(cluster).apply(namespace, annotated.toJSON())


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


def realize_data(dry_run, oc_map, ri, enable_deletion=True):
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
                logging.debug("DESIRED: " +
                              OR.serialize(OR.canonicalize(d_item.body)))
            else:
                logging.debug("CURRENT: None")

            try:
                apply(dry_run, oc_map, cluster, namespace,
                      resource_type, d_item)
            except StatusCodeError as e:
                ri.register_error()
                msg = "[{}/{}] {}".format(cluster, namespace, e.message)
                logging.error(msg)

        # current items
        for name, c_item in data['current'].items():
            d_item = data['desired'].get(name)
            if d_item is not None:
                continue

            if not c_item.has_qontract_annotations():
                continue

            try:
                delete(dry_run, oc_map, cluster, namespace,
                       resource_type, name, enable_deletion)
            except StatusCodeError as e:
                ri.register_error()
                msg = "[{}/{}] {}".format(cluster, namespace, e.message)
                logging.error(msg)

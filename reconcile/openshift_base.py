import logging


class StateSpec(object):
    def __init__(self, type, oc, cluster, namespace, resource, parent=None):
        self.type = type
        self.oc = oc
        self.cluster = cluster
        self.namespace = namespace
        self.resource = resource
        self.parent = parent


def init_specs_to_fetch(ri, oc_map, namespaces,
                        override_managed_types=None,
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

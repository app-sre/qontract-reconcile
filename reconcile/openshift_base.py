import logging

from utils.oc import StatusCodeError
from utils.openshift_resource import OR


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

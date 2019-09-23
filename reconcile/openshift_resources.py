import logging
import sys
import base64
import json
import operator
import anymarkup
import jinja2
import semver

import utils.gql as gql
import utils.threaded as threaded
import utils.vault_client as vault_client
import utils.openssl as openssl

from utils.oc import OC_Map, StatusCodeError
from utils.defer import defer
from utils.openshift_resource import (OpenshiftResource,
                                      ResourceInventory,
                                      ResourceKeyExistsError)
from utils.jinja2_ext import B64EncodeExtension
from threading import Lock

"""
+-----------------------+-------------------------+-------------+
|   Current \ Desired   |         Present         | Not Present |
+=======================+=========================+=============+
| Present               | Apply if sha256sum      | Delete      |
| (with annotations)    | is different or if      |             |
|                       | sha256sum is stale      |             |
|                       | (due to manual changes) |             |
+-----------------------+-------------------------+-------------+
| Present               | Annotate and apply      | Skip        |
| (without annotations) |                         |             |
+-----------------------+-------------------------+-------------+
| Not Present           | Apply                   | Skip        |
+-----------------------+-------------------------+-------------+
"""

NAMESPACES_QUERY = """
{
  namespaces: namespaces_v1 {
    name
    managedResourceTypes
    openshiftResources {
      provider
      ... on NamespaceOpenshiftResourceResource_v1 {
        path
      }
      ... on NamespaceOpenshiftResourceResourceTemplate_v1 {
        path
        type
        variables
      }
      ... on NamespaceOpenshiftResourceVaultSecret_v1 {
        path
        version
        name
        labels
        annotations
        type
      }
      ... on NamespaceOpenshiftResourceRoute_v1 {
        path
        vault_tls_secret_path
        vault_tls_secret_version
      }
    }
    cluster {
      name
      serverUrl
      jumpHost {
          hostname
          knownHosts
          user
          port
          identity {
              path
              field
              format
          }
      }
      automationToken {
        path
        field
        format
      }
      disable {
        integrations
      }
    }
  }
}
"""

QONTRACT_INTEGRATION = 'openshift_resources'
QONTRACT_INTEGRATION_VERSION = semver.format_version(1, 9, 2)
QONTRACT_BASE64_SUFFIX = '_qb64'

_log_lock = Lock()


class FetchResourceError(Exception):
    def __init__(self, msg):
        super(FetchResourceError, self).__init__(
            "error fetching resource: " + str(msg)
        )


class FetchVaultSecretError(Exception):
    def __init__(self, msg):
        super(FetchVaultSecretError, self).__init__(
            "error fetching vault secret: " + str(msg)
        )


class FetchRouteError(Exception):
    def __init__(self, msg):
        super(FetchRouteError, self).__init__(
            "error fetching route: " + str(msg)
        )


class Jinja2TemplateError(Exception):
    def __init__(self, msg):
        super(Jinja2TemplateError, self).__init__(
            "error processing jinja2 template: " + str(msg)
        )


class ResourceTemplateRenderError(Exception):
    def __init__(self, msg):
        super(ResourceTemplateRenderError, self).__init__(msg)


class UnknownProviderError(Exception):
    def __init__(self, msg):
        super(UnknownProviderError, self).__init__(
            "unknown provider error: " + str(msg)
        )


class UnknownTemplateTypeError(Exception):
    def __init__(self, msg):
        super(UnknownTemplateTypeError, self).__init__(
            "unknown template type error: " + str(msg)
        )


class OR(OpenshiftResource):
    def __init__(self, body):
        super(OR, self).__init__(
            body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
        )


class StateSpec(object):
    def __init__(self, type, oc, cluster, namespace, resource, parent=None):
        self.type = type
        self.oc = oc
        self.cluster = cluster
        self.namespace = namespace
        self.resource = resource
        self.parent = parent


def lookup_vault_secret(path, key, version=None):
    secret = {
        'path': path,
        'field': key,
        'version': version
    }
    try:
        return vault_client.read(secret)
    except Exception as e:
        raise FetchVaultSecretError(e)


def process_jinja2_template(body, vars={}, env={}):
    vars.update({'vault': lookup_vault_secret})
    try:
        env = jinja2.Environment(
            extensions=[B64EncodeExtension],
            undefined=jinja2.StrictUndefined,
            **env
        )
        template = env.from_string(body)
        r = template.render(vars)
    except Exception as e:
        raise Jinja2TemplateError(e)
    return r


def process_extracurlyjinja2_template(body, vars={}):
    env = {
        'block_start_string': '{{%',
        'block_end_string': '%}}',
        'variable_start_string': '{{{',
        'variable_end_string': '}}}',
        'comment_start_string': '{{#',
        'comment_end_string': '#}}'
    }
    return process_jinja2_template(body, vars=vars, env=env)


def fetch_provider_resource(path, tfunc=None, tvars=None):
    gqlapi = gql.get_api()

    # get resource data
    try:
        resource = gqlapi.get_resource(path)
    except gql.GqlApiError as e:
        raise FetchResourceError(e.message)

    content = resource['content']
    if tfunc:
        content = tfunc(content, tvars)

    try:
        resource['body'] = anymarkup.parse(
            content,
            force_types=None
        )
    except anymarkup.AnyMarkupError:
        e_msg = "Could not parse data. Skipping resource: {}"
        raise FetchResourceError(e_msg.format(path))

    openshift_resource = OR(resource['body'])

    try:
        openshift_resource.verify_valid_k8s_object()
    except (KeyError, TypeError) as e:
        k = e.__class__.__name__
        e_msg = "Invalid data ({}). Skipping resource: {}"
        raise FetchResourceError(e_msg.format(k, path))

    return openshift_resource


def fetch_provider_vault_secret(path, version, name,
                                labels, annotations, type):
    body = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": type,
        "metadata": {
            "name": name,
            "annotations": annotations
        },
        "data": {}
    }
    if labels:
        body['metadata']['labels'] = labels

    # get the fields from vault
    raw_data = vault_client.read_all({'path': path, 'version': version})
    for k, v in raw_data.items():
        if v == "":
            v = None
        if k.lower().endswith(QONTRACT_BASE64_SUFFIX):
            k = k[:-len(QONTRACT_BASE64_SUFFIX)]
        elif v is not None:
            v = base64.b64encode(v)
        body['data'][k] = v

    openshift_resource = OR(body)

    try:
        openshift_resource.verify_valid_k8s_object()
    except (KeyError, TypeError) as e:
        k = e.__class__.__name__
        e_msg = "Invalid data ({}). Skipping resource: {}"
        raise FetchVaultSecretError(e_msg.format(k, path))

    return openshift_resource


def fetch_provider_route(path, tls_path, tls_version):
    global _log_lock

    openshift_resource = fetch_provider_resource(path)

    if tls_path is None or tls_version is None:
        return openshift_resource

    # override existing tls fields from vault secret
    openshift_resource.body['spec'].setdefault('tls', {})
    tls = openshift_resource.body['spec']['tls']
    # get tls fields from vault
    raw_data = \
        vault_client.read_all({'path': tls_path, 'version': tls_version})
    valid_keys = ['termination', 'insecureEdgeTerminationPolicy',
                  'certificate', 'key',
                  'caCertificate', 'destinationCACertificate']
    for k, v in raw_data.items():
        if k in valid_keys:
            tls[k] = v
            continue

        msg = "Route secret '{}' key '{}' not in valid keys {}".format(
            tls_path, k, valid_keys
        )
        _log_lock.acquire()
        logging.info(msg)
        _log_lock.release()

    host = openshift_resource.body['spec'].get('host')
    certificate = openshift_resource.body['spec']['tls'].get('certificate')
    if host and certificate:
        match = openssl.certificate_matches_host(certificate, host)
        if not match:
            e_msg = "Route host does not match CN (common name): {}"
            raise FetchRouteError(e_msg.format(path))

    return openshift_resource


def fetch_openshift_resource(resource, parent):
    global _log_lock

    provider = resource['provider']
    path = resource['path']
    msg = "Fetching {}: {}".format(provider, path)
    _log_lock.acquire()
    logging.debug(msg)
    _log_lock.release()

    if provider == 'resource':
        openshift_resource = fetch_provider_resource(path)
    elif provider == 'resource-template':
        tv = {}
        if resource['variables']:
            tv = anymarkup.parse(resource['variables'], force_types=None)
        tv['resource'] = resource
        tv['resource']['namespace'] = parent
        tt = resource['type']
        tt = 'jinja2' if tt is None else tt
        if tt == 'jinja2':
            tfunc = process_jinja2_template
        elif tt == 'extracurlyjinja2':
            tfunc = process_extracurlyjinja2_template
        else:
            UnknownTemplateTypeError(tt)
        try:
            openshift_resource = fetch_provider_resource(path,
                                                         tfunc=tfunc,
                                                         tvars=tv)
        except Exception as e:
            msg = "could not render template at path {}\n{}".format(path, e)
            raise ResourceTemplateRenderError(msg)
    elif provider == 'vault-secret':
        version = resource['version']
        rn = resource['name']
        name = path.split('/')[-1] if rn is None else rn
        rl = resource['labels']
        labels = {} if rl is None else json.loads(rl)
        ra = resource['annotations']
        annotations = {} if ra is None else json.loads(ra)
        rt = resource['type']
        type = 'Opaque' if rt is None else rt
        try:
            openshift_resource = \
                fetch_provider_vault_secret(path, version, name,
                                            labels, annotations, type)
        except vault_client.SecretVersionNotFound as e:
            raise FetchVaultSecretError(e)
    elif provider == 'route':
        tls_path = resource['vault_tls_secret_path']
        tls_version = resource['vault_tls_secret_version']
        openshift_resource = fetch_provider_route(path, tls_path, tls_version)
    else:
        raise UnknownProviderError(provider)

    return openshift_resource


def fetch_current_state(oc, ri, cluster, namespace, resource_type):
    global _log_lock

    msg = "Fetching {}s from {}/{}".format(resource_type, cluster, namespace)
    _log_lock.acquire()
    logging.debug(msg)
    _log_lock.release()
    if oc is None:
        return
    for item in oc.get_items(resource_type, namespace=namespace):
        openshift_resource = OR(item)
        ri.add_current(
            cluster,
            namespace,
            resource_type,
            openshift_resource.name,
            openshift_resource
        )


def fetch_desired_state(oc, ri, cluster, namespace, resource, parent):
    global _log_lock

    if oc is None:
        return

    try:
        openshift_resource = fetch_openshift_resource(resource, parent)
    except (FetchResourceError,
            FetchVaultSecretError,
            FetchRouteError,
            UnknownProviderError) as e:
        ri.register_error()
        msg = "[{}/{}] {}".format(cluster, namespace, e.message)
        _log_lock.acquire()
        logging.error(msg)
        _log_lock.release()
        return

    # add to inventory
    try:
        ri.add_desired(
            cluster,
            namespace,
            openshift_resource.kind,
            openshift_resource.name,
            openshift_resource
        )
    except KeyError:
        # This is failing because in the managed_type loop (where the
        # `initialize_resource_type` method was called), this specific
        # combination was not initialized, meaning that it shouldn't be
        # managed. But someone is trying to add it via app-interface
        ri.register_error()
        msg = "[{}/{}] unknown kind: {}.".format(
            cluster, namespace, openshift_resource.kind)
        _log_lock.acquire()
        logging.error(msg)
        _log_lock.release()
        return
    except ResourceKeyExistsError:
        # This is failing because an attempt to add
        # a desired resource with the same name and
        # the same type was already added previously
        ri.register_error()
        msg = (
            "[{}/{}] desired item already exists: {}/{}."
        ).format(cluster, namespace, openshift_resource.kind,
                 openshift_resource.name)
        _log_lock.acquire()
        logging.error(msg)
        _log_lock.release()
        return


def fetch_states(spec, ri):
    if spec.type == "current":
        fetch_current_state(spec.oc, ri, spec.cluster,
                            spec.namespace, spec.resource)
    if spec.type == "desired":
        fetch_desired_state(spec.oc, ri, spec.cluster,
                            spec.namespace, spec.resource,
                            spec.parent)


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

    return sorted(state_specs, key=operator.attrgetter('type'))


def fetch_data(namespaces, thread_pool_size):
    ri = ResourceInventory()
    oc_map = OC_Map(namespaces=namespaces, integration=QONTRACT_INTEGRATION)
    state_specs = init_specs_to_fetch(ri, oc_map, namespaces)
    threaded.run(fetch_states, state_specs, thread_pool_size, ri=ri)

    return oc_map, ri


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


@defer
def run(dry_run=False, thread_pool_size=10, defer=None):
    gqlapi = gql.get_api()
    namespaces = gqlapi.query(NAMESPACES_QUERY)['namespaces']
    oc_map, ri = fetch_data(namespaces, thread_pool_size)
    defer(lambda: oc_map.cleanup())

    realize_data(dry_run, oc_map, ri)

    if ri.has_error_registered():
        sys.exit(1)

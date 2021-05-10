import base64
import json
import logging
import sys

from threading import Lock
from textwrap import indent
from sretoolbox.utils import retry

import anymarkup
import jinja2

import reconcile.openshift_base as ob
import reconcile.queries as queries
import reconcile.utils.amtool as amtool
import reconcile.utils.gql as gql
import reconcile.utils.openssl as openssl
import reconcile.utils.threaded as threaded

from reconcile.exceptions import FetchResourceError
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.defer import defer
from reconcile.utils.jinja2_ext import B64EncodeExtension
from reconcile.utils.jinja2_ext import RaiseErrorExtension
from reconcile.utils.oc import OC_Map
from reconcile.utils.oc import StatusCodeError
from reconcile.utils.sharding import is_in_shard
from reconcile.utils.openshift_resource import (OpenshiftResource as OR,
                                                ConstructResourceError,
                                                ResourceInventory,
                                                ResourceKeyExistsError)
from reconcile.utils.vault import SecretVersionNotFound
from reconcile.utils.vault import VaultClient


"""
+-----------------------+-------------------------+-------------+
|   Current / Desired   |         Present         | Not Present |
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

OPENSHIFT_RESOURCE = """
provider
... on NamespaceOpenshiftResourceResource_v1 {
  path
  validate_json
  validate_alertmanager_config
  alertmanager_config_key
}
... on NamespaceOpenshiftResourceResourceTemplate_v1 {
  path
  type
  variables
  validate_alertmanager_config
  alertmanager_config_key
}
... on NamespaceOpenshiftResourceVaultSecret_v1 {
  path
  version
  name
  labels
  annotations
  type
  validate_alertmanager_config
  alertmanager_config_key
}
... on NamespaceOpenshiftResourceRoute_v1 {
  path
  vault_tls_secret_path
  vault_tls_secret_version
}
"""

NAMESPACES_QUERY = """
{
  namespaces: namespaces_v1 {
    name
    managedResourceTypes
    managedResourceTypeOverrides {
      resource
      override
    }
    managedResourceNames {
      resource
      resourceNames
    }
    sharedResources {
      openshiftResources {
        %s
      }
    }
    openshiftResources {
      %s
    }
    cluster {
      name
      serverUrl
      auth {
        org
        team
      }
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
      spec {
        version
      }
      automationToken {
        path
        field
        format
      }
      internal
      disable {
        integrations
      }
    }
  }
}
""" % (indent(OPENSHIFT_RESOURCE, 8*' '), indent(OPENSHIFT_RESOURCE, 6*' '))

QONTRACT_INTEGRATION = 'openshift_resources_base'
QONTRACT_INTEGRATION_VERSION = make_semver(1, 9, 2)
QONTRACT_BASE64_SUFFIX = '_qb64'
APP_INT_BASE_URL = 'https://gitlab.cee.redhat.com/service/app-interface'

_log_lock = Lock()


class FetchVaultSecretError(Exception):
    def __init__(self, msg):
        super().__init__("error fetching vault secret: " + str(msg))


class FetchRouteError(Exception):
    def __init__(self, msg):
        super().__init__("error fetching route: " + str(msg))


class Jinja2TemplateError(Exception):
    def __init__(self, msg):
        super().__init__("error processing jinja2 template: " + str(msg))


class ResourceTemplateRenderError(Exception):
    pass


class UnknownProviderError(Exception):
    def __init__(self, msg):
        super().__init__("unknown provider error: " + str(msg))


class UnknownTemplateTypeError(Exception):
    def __init__(self, msg):
        super().__init__("unknown template type error: " + str(msg))


@retry()
def lookup_vault_secret(path, key, version=None, tvars=None):
    if tvars is not None:
        path = process_jinja2_template(path, vars=tvars)
        key = process_jinja2_template(key, vars=tvars)
        if version and not isinstance(version, int):
            version = process_jinja2_template(version, vars=tvars)
    secret = {
        'path': path,
        'field': key,
        'version': version
    }
    try:
        vault_client = VaultClient()
        return vault_client.read(secret)
    except Exception as e:
        raise FetchVaultSecretError(e)


def process_jinja2_template(body, vars=None, env=None):
    if vars is None:
        vars = {}
    if env is None:
        env = {}
    vars.update({'vault': lambda p, k, v=None:
                 lookup_vault_secret(p, k, v, vars)})
    try:
        env = jinja2.Environment(
            extensions=[B64EncodeExtension, RaiseErrorExtension],
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


def check_alertmanager_config(data, path, alertmanager_config_key,
                              decode_base64=False):
    try:
        config = data[alertmanager_config_key]
    except KeyError:
        e_msg = f"error validating alertmanager config in {path}: " \
                f"missing key {alertmanager_config_key}"
        raise FetchResourceError(e_msg)

    if decode_base64:
        config = base64.b64decode(config).decode('utf-8')

    result = amtool.check_config(config)
    if not result:
        e_msg = f"error validating alertmanager config in {path}: {result}"
        raise FetchResourceError(e_msg)


def fetch_provider_resource(path, tfunc=None, tvars=None,
                            validate_json=False,
                            validate_alertmanager_config=False,
                            alertmanager_config_key='alertmanager.yaml',
                            add_path_to_prom_rules=True):
    gqlapi = gql.get_api()

    # get resource data
    try:
        resource = gqlapi.get_resource(path)
    except gql.GqlGetResourceError as e:
        raise FetchResourceError(str(e))

    content = resource['content']
    if tfunc:
        content = tfunc(content, tvars)

    try:
        resource['body'] = anymarkup.parse(
            content,
            force_types=None
        )
        resource['body'].pop('$schema', None)
    except TypeError:
        body_type = type(resource['body']).__name__
        e_msg = f"invalid resource type {body_type} found in path: {path}"
        raise FetchResourceError(e_msg)
    except anymarkup.AnyMarkupError:
        e_msg = f"Could not parse data. Skipping resource: {path}"
        raise FetchResourceError(e_msg)

    if validate_json:
        files = resource['body']['data']
        for file_name, file_content in files.items():
            try:
                json.loads(file_content)
            except ValueError:
                e_msg = f"invalid json in {path} under {file_name}"
                raise FetchResourceError(e_msg)

    if validate_alertmanager_config:
        decode_base64 = True if resource['body']['kind'] == 'Secret' else False
        check_alertmanager_config(resource['body']['data'], path,
                                  alertmanager_config_key,
                                  decode_base64)

    if add_path_to_prom_rules:
        body = resource['body']
        if body['kind'] == 'PrometheusRule':
            try:
                groups = body['spec']['groups']
                for group in groups:
                    rules = group['rules']
                    for rule in rules:
                        annotations = rule.get('annotations')
                        if not annotations:
                            continue
                        # TODO(mafriedm): make this better
                        rule['annotations']['html_url'] = \
                            f"{APP_INT_BASE_URL}/blob/master/resources{path}"
            except Exception:
                logging.warning(
                    'could not add html_url annotation to' +
                    body['name'])

    try:
        return OR(resource['body'],
                  QONTRACT_INTEGRATION,
                  QONTRACT_INTEGRATION_VERSION,
                  error_details=path)
    except ConstructResourceError as e:
        raise FetchResourceError(str(e))


def fetch_provider_vault_secret(
        path, version, name,
        labels, annotations, type,
        integration,
        integration_version,
        validate_alertmanager_config=False,
        alertmanager_config_key='alertmanager.yaml'):
    # get the fields from vault
    vault_client = VaultClient()
    raw_data = vault_client.read_all({'path': path, 'version': version})

    if validate_alertmanager_config:
        check_alertmanager_config(raw_data, path, alertmanager_config_key)

    # construct oc resource
    body = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": type,
        "metadata": {
            "name": name,
            "annotations": annotations
        }
    }
    if labels:
        body['metadata']['labels'] = labels
    if raw_data.items():
        body['data'] = {}

    # populate data
    for k, v in raw_data.items():
        if v == "":
            continue
        if k.lower().endswith(QONTRACT_BASE64_SUFFIX):
            k = k[:-len(QONTRACT_BASE64_SUFFIX)]
            v = v.replace('\n', '')
        elif v is not None:
            v = base64.b64encode(v.encode()).decode('utf-8')
        body['data'][k] = v

    try:
        return OR(body,
                  integration,
                  integration_version,
                  error_details=path)
    except ConstructResourceError as e:
        raise FetchResourceError(str(e))


def fetch_provider_route(path, tls_path, tls_version):
    global _log_lock

    openshift_resource = fetch_provider_resource(path)

    if tls_path is None or tls_version is None:
        return openshift_resource

    # override existing tls fields from vault secret
    openshift_resource.body['spec'].setdefault('tls', {})
    tls = openshift_resource.body['spec']['tls']
    # get tls fields from vault
    vault_client = VaultClient()
    raw_data = vault_client.read_all({'path': tls_path,
                                      'version': tls_version})
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
        validate_json = resource.get('validate_json') or False
        add_path_to_prom_rules = \
            resource.get('add_path_to_prom_rules', True)
        validate_alertmanager_config = \
            resource.get('validate_alertmanager_config') or False
        alertmanager_config_key = \
            resource.get('alertmanager_config_key') or 'alertmanager.yaml'
        openshift_resource = fetch_provider_resource(
            path,
            validate_json=validate_json,
            validate_alertmanager_config=validate_alertmanager_config,
            alertmanager_config_key=alertmanager_config_key,
            add_path_to_prom_rules=add_path_to_prom_rules)
    elif provider == 'resource-template':
        add_path_to_prom_rules = \
            resource.get('add_path_to_prom_rules', True)
        validate_alertmanager_config = \
            resource.get('validate_alertmanager_config') or False
        alertmanager_config_key = \
            resource.get('alertmanager_config_key') or 'alertmanager.yaml'
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
            openshift_resource = fetch_provider_resource(
                path,
                tfunc=tfunc,
                tvars=tv,
                validate_alertmanager_config=validate_alertmanager_config,
                alertmanager_config_key=alertmanager_config_key,
                add_path_to_prom_rules=add_path_to_prom_rules)
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
        validate_alertmanager_config = \
            resource.get('validate_alertmanager_config') or False
        alertmanager_config_key = \
            resource.get('alertmanager_config_key') or 'alertmanager.yaml'
        try:
            openshift_resource = fetch_provider_vault_secret(
                path, version, name,
                labels, annotations, type,
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
                validate_alertmanager_config=validate_alertmanager_config,
                alertmanager_config_key=alertmanager_config_key)
        except SecretVersionNotFound as e:
            raise FetchVaultSecretError(e)
    elif provider == 'route':
        tls_path = resource['vault_tls_secret_path']
        tls_version = resource['vault_tls_secret_version']
        openshift_resource = fetch_provider_route(path, tls_path, tls_version)
    else:
        raise UnknownProviderError(provider)

    return openshift_resource


def fetch_current_state(oc, ri, cluster, namespace, resource_type,
                        resource_type_override=None, resource_names=None):
    global _log_lock

    resource_type_to_use = resource_type_override or resource_type

    msg = "Fetching {}s from {}/{}".format(
        resource_type_to_use, cluster, namespace)
    _log_lock.acquire()
    logging.debug(msg)
    _log_lock.release()
    if oc is None:
        return
    # some resource types may be used explicitly (<kind>.<api_group>).
    # we only take the first token as oc.api_resources contains only the kind.
    # this is the case created by using `managedResourceTypeOverrides`.
    if oc.api_resources and \
            resource_type_to_use.split('.')[0].lower() \
            not in [a.lower() for a in oc.api_resources]:
        msg = \
            f"[{cluster}] cluster has no API resource {resource_type_to_use}."
        logging.warning(msg)
        return
    for item in oc.get_items(resource_type_to_use, namespace=namespace,
                             resource_names=resource_names):
        openshift_resource = OR(item,
                                QONTRACT_INTEGRATION,
                                QONTRACT_INTEGRATION_VERSION)
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
        msg = "[{}/{}] {}".format(cluster, namespace, str(e))
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
    try:
        if spec.type == "current":
            fetch_current_state(spec.oc, ri, spec.cluster,
                                spec.namespace, spec.resource,
                                spec.resource_type_override,
                                spec.resource_names)
        if spec.type == "desired":
            fetch_desired_state(spec.oc, ri, spec.cluster,
                                spec.namespace, spec.resource,
                                spec.parent)

    except StatusCodeError as e:
        ri.register_error(cluster=spec.cluster)
        msg = 'cluster: {},'
        msg += 'namespace: {},'
        msg += 'resource_names: {},'
        msg += 'exception: {}'
        msg = msg.format(spec.cluster,
                         spec.namespace,
                         spec.resource_names,
                         str(e))
        logging.error(msg)


def fetch_data(namespaces, thread_pool_size, internal, use_jump_host,
               init_api_resources=False):
    ri = ResourceInventory()
    settings = queries.get_app_interface_settings()
    oc_map = OC_Map(namespaces=namespaces, integration=QONTRACT_INTEGRATION,
                    settings=settings, internal=internal,
                    use_jump_host=use_jump_host,
                    thread_pool_size=thread_pool_size,
                    init_api_resources=init_api_resources)
    state_specs = ob.init_specs_to_fetch(ri, oc_map, namespaces=namespaces)
    threaded.run(fetch_states, state_specs, thread_pool_size, ri=ri)

    return oc_map, ri


def filter_namespaces_by_cluster_and_namespace(namespaces,
                                               cluster_name,
                                               namespace_name):
    if cluster_name:
        namespaces = [n for n in namespaces
                      if n['cluster']['name'] == cluster_name]
    if namespace_name:
        namespaces = [n for n in namespaces
                      if n['name'] == namespace_name]
    return namespaces


def canonicalize_namespaces(namespaces, providers):
    canonicalized_namespaces = []
    for namespace_info in namespaces:
        ob.aggregate_shared_resources(namespace_info, 'openshiftResources')
        openshift_resources = namespace_info.get('openshiftResources')
        if openshift_resources:
            for resource in openshift_resources[:]:
                if resource['provider'] not in providers:
                    openshift_resources.remove(resource)
        if openshift_resources:
            if len(providers) == 1:
                if providers[0] == 'vault-secret':
                    namespace_info['managedResourceTypes'] = ['Secret']
                elif providers[0] == 'route':
                    namespace_info['managedResourceTypes'] = ['Route']
            canonicalized_namespaces.append(namespace_info)

    return canonicalized_namespaces


@defer
def run(dry_run, thread_pool_size=10, internal=None,
        use_jump_host=True, providers=[],
        cluster_name=None, namespace_name=None,
        init_api_resources=False,
        defer=None):
    gqlapi = gql.get_api()
    namespaces = [namespace_info for namespace_info
                  in gqlapi.query(NAMESPACES_QUERY)['namespaces']
                  if is_in_shard(
                      f"{namespace_info['cluster']['name']}/" +
                      f"{namespace_info['name']}")]
    namespaces = \
        filter_namespaces_by_cluster_and_namespace(
            namespaces,
            cluster_name,
            namespace_name
        )
    namespaces = canonicalize_namespaces(namespaces, providers)
    oc_map, ri = \
        fetch_data(namespaces, thread_pool_size, internal, use_jump_host,
                   init_api_resources=init_api_resources)
    defer(lambda: oc_map.cleanup())

    ob.realize_data(dry_run, oc_map, ri)

    if ri.has_error_registered():
        sys.exit(1)

    return ri

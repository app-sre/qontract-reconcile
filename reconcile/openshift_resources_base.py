import base64
import hashlib
import itertools
import json
import logging
import sys
from collections.abc import (
    Iterable,
    Mapping,
)
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cache
from textwrap import indent
from threading import Lock
from typing import (
    Any,
    Optional,
    Protocol,
    Tuple,
)
from urllib import parse

import anymarkup
import jinja2
from sretoolbox.utils import (
    retry,
    threaded,
)

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.change_owners.diff import IDENTIFIER_FIELD_NAME
from reconcile.checkpoint import url_makes_sense
from reconcile.github_users import init_github
from reconcile.utils import (
    amtool,
    gql,
    openssl,
)
from reconcile.utils.defer import defer
from reconcile.utils.exceptions import FetchResourceError
from reconcile.utils.jinja2_ext import (
    B64EncodeExtension,
    RaiseErrorExtension,
)
from reconcile.utils.oc import (
    OC_Map,
    OCClient,
    OCLogMsg,
    StatusCodeError,
)
from reconcile.utils.openshift_resource import ConstructResourceError
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import (
    ResourceInventory,
    ResourceKeyExistsError,
)
from reconcile.utils.runtime.integration import DesiredStateShardConfig
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.sharding import is_in_shard
from reconcile.utils.vault import (
    SecretVersionIsNone,
    SecretVersionNotFound,
)

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
  resource: path {
    content
    path
    schema
  }
  validate_json
  validate_alertmanager_config
  alertmanager_config_key
  enable_query_support
}
... on NamespaceOpenshiftResourceResourceTemplate_v1 {
  resource: path {
    content
    path
    schema
  }
  type
  variables
  validate_alertmanager_config
  alertmanager_config_key
  enable_query_support
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
  resource: path {
    content
    path
    schema
  }
  vault_tls_secret_path
  vault_tls_secret_version
}
"""

NAMESPACES_QUERY = """
{
  namespaces: namespaces_v1 {
    name
    delete
    clusterAdmin
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
          service
          ... on ClusterAuthGithubOrg_v1 {
              org
          }
          ... on ClusterAuthGithubOrgTeam_v1 {
              org
              team
          }
          # ... on ClusterAuthOIDC_v1 {
          # }
        }
      insecureSkipTLSVerify
      jumpHost {
        %s
      }
      spec {
        version
        region
      }
      network {
        pod
      }
      automationToken {
        path
        field
        version
        format
      }
      clusterAdminAutomationToken {
        path
        field
        version
        format
      }
      internal
      disable {
        integrations
      }
    }
  }
}
""" % (
    indent(OPENSHIFT_RESOURCE, 8 * " "),
    indent(OPENSHIFT_RESOURCE, 6 * " "),
    indent(queries.JUMPHOST_FIELDS, 8 * " "),
)

QONTRACT_INTEGRATION = "openshift_resources_base"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 9, 2)
QONTRACT_BASE64_SUFFIX = "_qb64"
APP_INT_BASE_URL = "https://gitlab.cee.redhat.com/service/app-interface"

_log_lock = Lock()


class FetchSecretError(Exception):
    def __init__(self, msg):
        super().__init__("error fetching secret: " + str(msg))


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
def lookup_secret(path, key, version=None, tvars=None, settings=None):
    if tvars is not None:
        path = process_jinja2_template(body=path, vars=tvars, settings=settings)
        key = process_jinja2_template(body=key, vars=tvars, settings=settings)
        if version and not isinstance(version, int):
            version = process_jinja2_template(
                body=version, vars=tvars, settings=settings
            )
    secret = {"path": path, "field": key, "version": version}
    try:
        secret_reader = SecretReader(settings)
        return secret_reader.read(secret)
    except Exception as e:
        raise FetchSecretError(e)


def lookup_github_file_content(repo, path, ref, tvars=None, settings=None):
    if tvars is not None:
        repo = process_jinja2_template(body=repo, vars=tvars, settings=settings)
        path = process_jinja2_template(body=path, vars=tvars, settings=settings)
        ref = process_jinja2_template(body=ref, vars=tvars, settings=settings)

    gh = init_github()
    c = gh.get_repo(repo).get_contents(path, ref).decoded_content
    return c.decode("utf-8")


def lookup_graphql_query_results(query: str, **kwargs) -> list[Any]:
    gqlapi = gql.get_api()
    resource = gqlapi.get_resource(query)["content"]
    rendered_resource = jinja2.Template(resource).render(**kwargs)
    results = list(gqlapi.query(rendered_resource).values())[0]
    return results


def json_to_dict(input):
    """Jinja2 filter to parse JSON strings into dictionaries.
       This becomes useful to access Graphql queries data (labels)
    :param input: json string
    :return: dict with the parsed inputs contents
    """
    data = json.loads(input)
    return data


def urlescape(
    string: str,
    safe: str = "/",
    encoding: Optional[str] = None,
) -> str:
    """Jinja2 filter that is a simple wrapper around urllib's URL quoting
    functions that takes a string value and makes it safe for use as URL
    components escaping any reserved characters using URL encoding. See:
    urllib.parse.quote() and urllib.parse.quote_plus() for reference.

    :param str string: String value to escape.
    :param str safe: Optional characters that should not be escaped.
    :param encoding: Encoding to apply to the string to be escaped. Defaults
        to UTF-8. Unsupported characters raise a UnicodeEncodeError error.
    :type encoding: typing.Optional[str]
    :returns: A string with reserved characters escaped.
    :rtype: str
    """
    return parse.quote(string, safe=safe, encoding=encoding)


def urlunescape(string: str, encoding: Optional[str] = None) -> str:
    """Jinja2 filter that is a simple wrapper around urllib's URL unquoting
    functions that takes an URL-encoded string value and unescapes it
    replacing any URL-encoded values with their character equivalent. See:
    urllib.parse.unquote() and urllib.parse.unquote_plus() for reference.

    :param str string: String value to unescape.
    :param encoding: Encoding to apply to the string to be unescaped. Defaults
        to UTF-8. Unsupported characters are replaced by placeholder values.
    :type encoding: typing.Optional[str]
    :returns: A string with URL-encoded sequences unescaped.
    :rtype: str
    """
    if encoding is None:
        encoding = "utf-8"
    return parse.unquote(string, encoding=encoding)


@cache
def compile_jinja2_template(body, extra_curly: bool = False):
    env: dict = {}
    if extra_curly:
        env = {
            "block_start_string": "{{%",
            "block_end_string": "%}}",
            "variable_start_string": "{{{",
            "variable_end_string": "}}}",
            "comment_start_string": "{{#",
            "comment_end_string": "#}}",
        }

    jinja_env = jinja2.Environment(
        extensions=[B64EncodeExtension, RaiseErrorExtension],
        undefined=jinja2.StrictUndefined,
        **env,
    )
    jinja_env.filters.update(
        {
            "json_to_dict": json_to_dict,
            "urlescape": urlescape,
            "urlunescape": urlunescape,
        }
    )

    return jinja_env.from_string(body)


def process_jinja2_template(body, vars=None, extra_curly: bool = False, settings=None):
    if vars is None:
        vars = {}
    vars.update(
        {
            "vault": lambda p, k, v=None: lookup_secret(
                path=p, key=k, version=v, tvars=vars, settings=settings
            ),
            "github": lambda u, p, r, v=None: lookup_github_file_content(
                repo=u, path=p, ref=r, tvars=vars, settings=settings
            ),
            "urlescape": lambda u, s="/", e=None: urlescape(
                string=u, safe=s, encoding=e
            ),
            "urlunescape": lambda u, e=None: urlunescape(string=u, encoding=e),
            "query": lookup_graphql_query_results,
            "url": url_makes_sense,
        }
    )
    try:
        template = compile_jinja2_template(body, extra_curly)
        r = template.render(vars)
    except Exception as e:
        raise Jinja2TemplateError(e)
    return r


def process_extracurlyjinja2_template(body, vars=None, env=None, settings=None):
    if vars is None:
        vars = {}
    return process_jinja2_template(body, vars=vars, extra_curly=True, settings=settings)


def check_alertmanager_config(data, path, alertmanager_config_key, decode_base64=False):
    try:
        config = data[alertmanager_config_key]
    except KeyError:
        e_msg = (
            f"error validating alertmanager config in {path}: "
            f"missing key {alertmanager_config_key}"
        )
        raise FetchResourceError(e_msg)

    if decode_base64:
        config = base64.b64decode(config).decode("utf-8")

    result = amtool.check_config(config)
    if not result:
        e_msg = f"error validating alertmanager config in {path}: {result}"
        raise FetchResourceError(e_msg)


def fetch_provider_resource(
    resource: dict,
    tfunc=None,
    tvars=None,
    validate_json=False,
    validate_alertmanager_config=False,
    alertmanager_config_key="alertmanager.yaml",
    add_path_to_prom_rules=True,
    skip_validation=False,
    settings=None,
) -> OR:
    path = resource["path"]
    content = resource["content"]
    if tfunc:
        content = tfunc(body=content, vars=tvars, settings=settings)

    if skip_validation:
        return OR(
            content,
            QONTRACT_INTEGRATION,
            QONTRACT_INTEGRATION_VERSION,
            error_details=path,
            validate_k8s_object=False,
        )

    try:
        body = anymarkup.parse(content, force_types=None)
        body.pop("$schema", None)
    except TypeError:
        body_type = type(body).__name__
        e_msg = f"invalid resource type {body_type} found in path: {path}"
        raise FetchResourceError(e_msg)
    except anymarkup.AnyMarkupError:
        e_msg = f"Could not parse data. Skipping resource: {path}"
        raise FetchResourceError(e_msg)

    if validate_json:
        files = body["data"]
        for file_name, file_content in files.items():
            try:
                json.loads(file_content)
            except ValueError:
                e_msg = f"invalid json in {path} under {file_name}"
                raise FetchResourceError(e_msg)

    if validate_alertmanager_config:
        if body["kind"] == "Secret":
            if "data" in body:
                am_data = body["data"]
                decode_base64 = True
            elif "stringData" in body:
                am_data = body["stringData"]
                decode_base64 = False
        else:
            am_data = body["data"]
            decode_base64 = False

        check_alertmanager_config(am_data, path, alertmanager_config_key, decode_base64)

    if add_path_to_prom_rules:
        if body["kind"] == "PrometheusRule":
            try:
                groups = body["spec"]["groups"]
                for group in groups:
                    rules = group["rules"]
                    for rule in rules:
                        annotations = rule.get("annotations")
                        if not annotations:
                            continue
                        # TODO(mafriedm): make this better
                        rule["annotations"][
                            "html_url"
                        ] = f"{APP_INT_BASE_URL}/blob/master/resources{path}"
            except Exception:
                logging.warning(
                    "could not add html_url annotation to" + body["metadata"]["name"]
                )

    try:
        return OR(
            body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION, error_details=path
        )
    except ConstructResourceError as e:
        raise FetchResourceError(str(e))


def fetch_provider_vault_secret(
    path,
    version,
    name,
    labels,
    annotations,
    type,
    integration,
    integration_version,
    validate_alertmanager_config=False,
    alertmanager_config_key="alertmanager.yaml",
    settings=None,
) -> OR:
    # get the fields from vault
    secret_reader = SecretReader(settings)
    raw_data = secret_reader.read_all({"path": path, "version": version})

    if validate_alertmanager_config:
        check_alertmanager_config(raw_data, path, alertmanager_config_key)

    # construct oc resource
    body = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": type,
        "metadata": {"name": name, "annotations": annotations},
    }
    if labels:
        body["metadata"]["labels"] = labels

    # populate data
    for k, v in raw_data.items():
        if v == "":
            continue
        if k.lower().endswith(QONTRACT_BASE64_SUFFIX):
            k = k[: -len(QONTRACT_BASE64_SUFFIX)]
            v = v.replace("\n", "")
        elif v is not None:
            v = base64.b64encode(v.encode()).decode("utf-8")
        body.setdefault("data", {})[k] = v

    try:
        return OR(body, integration, integration_version, error_details=path)
    except ConstructResourceError as e:
        raise FetchResourceError(str(e))


def fetch_provider_route(resource: dict, tls_path, tls_version, settings=None) -> OR:
    global _log_lock

    path = resource["path"]
    openshift_resource = fetch_provider_resource(resource)

    if tls_path is None or tls_version is None:
        return openshift_resource

    # override existing tls fields from vault secret
    openshift_resource.body["spec"].setdefault("tls", {})
    tls = openshift_resource.body["spec"]["tls"]
    # get tls fields from vault
    secret_reader = SecretReader(settings)
    raw_data = secret_reader.read_all({"path": tls_path, "version": tls_version})
    valid_keys = [
        "termination",
        "insecureEdgeTerminationPolicy",
        "certificate",
        "key",
        "caCertificate",
        "destinationCACertificate",
    ]
    for k, v in raw_data.items():
        if k in valid_keys:
            tls[k] = v
            continue

        msg = "Route secret '{}' key '{}' not in valid keys {}".format(
            tls_path, k, valid_keys
        )
        _log_lock.acquire()  # pylint: disable=consider-using-with
        logging.info(msg)
        _log_lock.release()

    host = openshift_resource.body["spec"].get("host")
    certificate = openshift_resource.body["spec"]["tls"].get("certificate")
    if host and certificate:
        match = openssl.certificate_matches_host(certificate, host)
        if not match:
            e_msg = "Route host does not match CN (common name): {}"
            raise FetchRouteError(e_msg.format(path))

    return openshift_resource


def _locked_log(lock, msg):
    lock.acquire()  # pylint: disable=consider-using-with
    logging.debug(msg)
    lock.release()


def fetch_openshift_resource(
    resource, parent, settings=None, skip_validation=False
) -> OR:
    global _log_lock

    provider = resource["provider"]
    if provider == "resource":
        path = resource["resource"]["path"]
        _locked_log(_log_lock, "Processing {}: {}".format(provider, path))
        validate_json = resource.get("validate_json") or False
        add_path_to_prom_rules = resource.get("add_path_to_prom_rules", True)
        validate_alertmanager_config = (
            resource.get("validate_alertmanager_config") or False
        )
        alertmanager_config_key = (
            resource.get("alertmanager_config_key") or "alertmanager.yaml"
        )
        openshift_resource = fetch_provider_resource(
            resource["resource"],
            validate_json=validate_json,
            validate_alertmanager_config=validate_alertmanager_config,
            alertmanager_config_key=alertmanager_config_key,
            add_path_to_prom_rules=add_path_to_prom_rules,
            skip_validation=skip_validation,
            settings=settings,
        )
    elif provider == "resource-template":
        path = resource["resource"]["path"]
        _locked_log(_log_lock, "Processing {}: {}".format(provider, path))
        add_path_to_prom_rules = resource.get("add_path_to_prom_rules", True)
        validate_alertmanager_config = (
            resource.get("validate_alertmanager_config") or False
        )
        alertmanager_config_key = (
            resource.get("alertmanager_config_key") or "alertmanager.yaml"
        )
        tv = {}
        if resource["variables"]:
            tv = anymarkup.parse(resource["variables"], force_types=None)
        tv["resource"] = resource
        tv["resource"]["namespace"] = parent
        tt = resource["type"]
        tt = "jinja2" if tt is None else tt
        if tt == "jinja2":
            tfunc = process_jinja2_template
        elif tt == "extracurlyjinja2":
            tfunc = process_extracurlyjinja2_template
        else:
            UnknownTemplateTypeError(tt)
        try:
            openshift_resource = fetch_provider_resource(
                resource["resource"],
                tfunc=tfunc,
                tvars=tv,
                validate_alertmanager_config=validate_alertmanager_config,
                alertmanager_config_key=alertmanager_config_key,
                add_path_to_prom_rules=add_path_to_prom_rules,
                skip_validation=skip_validation,
                settings=settings,
            )
        except Exception as e:
            msg = "could not render template at path {}\n{}".format(path, e)
            raise ResourceTemplateRenderError(msg)
    elif provider == "vault-secret":
        path = resource["path"]
        version = resource["version"]
        _locked_log(_log_lock, "Processing {}: {} - {}".format(provider, path, version))
        rn = resource["name"]
        name = path.split("/")[-1] if rn is None else rn
        rl = resource["labels"]
        labels = {} if rl is None else json.loads(rl)
        ra = resource["annotations"]
        annotations = {} if ra is None else json.loads(ra)
        rt = resource["type"]
        type = "Opaque" if rt is None else rt
        validate_alertmanager_config = (
            resource.get("validate_alertmanager_config") or False
        )
        alertmanager_config_key = (
            resource.get("alertmanager_config_key") or "alertmanager.yaml"
        )
        try:
            openshift_resource = fetch_provider_vault_secret(
                path,
                version,
                name,
                labels,
                annotations,
                type,
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
                validate_alertmanager_config=validate_alertmanager_config,
                alertmanager_config_key=alertmanager_config_key,
                settings=settings,
            )
        except (SecretVersionNotFound, SecretVersionIsNone) as e:
            raise FetchSecretError(e)
    elif provider == "route":
        path = resource["resource"]["path"]
        _locked_log(_log_lock, "Processing {}: {}".format(provider, path))
        tls_path = resource["vault_tls_secret_path"]
        tls_version = resource["vault_tls_secret_version"]
        openshift_resource = fetch_provider_route(
            resource["resource"], tls_path, tls_version, settings
        )
    else:
        raise UnknownProviderError(provider)

    return openshift_resource


def fetch_current_state(
    oc: OCClient,
    ri: ResourceInventory,
    cluster: str,
    namespace: str,
    kind: str,
    resource_names=Iterable[str],
):
    global _log_lock

    msg = f"Fetching {kind} from {cluster}/{namespace}"
    _log_lock.acquire()  # pylint: disable=consider-using-with
    logging.debug(msg)
    _log_lock.release()
    if not oc.is_kind_supported(kind):
        logging.warning(f"[{cluster}] cluster has no API resource {kind}.")
        return
    for item in oc.get_items(kind, namespace=namespace, resource_names=resource_names):
        openshift_resource = OR(
            item, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
        )
        ri.add_current(
            cluster,
            namespace,
            kind,
            openshift_resource.name,
            openshift_resource,
        )


def fetch_desired_state(
    oc: OCClient,
    ri: ResourceInventory,
    cluster: str,
    namespace: str,
    resource: Mapping[str, Any],
    parent: Mapping[str, Any],
    privileged: bool,
    settings: Optional[Mapping[str, Any]] = None,
):
    global _log_lock

    try:
        openshift_resource = fetch_openshift_resource(resource, parent, settings)
    except (
        FetchResourceError,
        FetchSecretError,
        FetchRouteError,
        UnknownProviderError,
    ) as e:
        ri.register_error()
        msg = "[{}/{}] {}".format(cluster, namespace, str(e))
        _log_lock.acquire()  # pylint: disable=consider-using-with
        logging.error(msg)
        _log_lock.release()
        return

    # add to inventory
    try:
        ri.add_desired_resource(
            cluster,
            namespace,
            openshift_resource,
            privileged,
        )
    except KeyError:
        # This is failing because in the managed_type loop (where the
        # `initialize_resource_type` method was called), this specific
        # combination was not initialized, meaning that it shouldn't be
        # managed. But someone is trying to add it via app-interface
        ri.register_error()
        msg = "[{}/{}] unknown kind: {}. hint: is it missing from managedResourceTypes?".format(
            cluster, namespace, openshift_resource.kind
        )
        _log_lock.acquire()  # pylint: disable=consider-using-with
        logging.error(msg)
        _log_lock.release()
        return
    except ResourceKeyExistsError:
        # This is failing because an attempt to add
        # a desired resource with the same name and
        # the same type was already added previously
        ri.register_error()
        msg = ("[{}/{}] desired item already exists: {}/{}.").format(
            cluster, namespace, openshift_resource.kind, openshift_resource.name
        )
        _log_lock.acquire()  # pylint: disable=consider-using-with
        logging.error(msg)
        _log_lock.release()
        return


def fetch_states(
    spec: ob.StateSpec,
    ri: ResourceInventory,
    settings: Optional[Mapping[str, Any]] = None,
) -> None:
    try:
        if isinstance(spec, ob.CurrentStateSpec):
            fetch_current_state(
                spec.oc,
                ri,
                spec.cluster,
                spec.namespace,
                spec.kind,
                spec.resource_names,
            )
        if isinstance(spec, ob.DesiredStateSpec):
            fetch_desired_state(
                spec.oc,
                ri,
                spec.cluster,
                spec.namespace,
                spec.resource,
                spec.parent,
                spec.privileged,
                settings,
            )

    except StatusCodeError as e:
        ri.register_error(cluster=spec.cluster)
        logging.error(f"{spec} - exception: {str(e)}")


def fetch_data(
    namespaces,
    thread_pool_size,
    internal,
    use_jump_host,
    init_api_resources=False,
    overrides=None,
):
    ri = ResourceInventory()
    settings = queries.get_app_interface_settings()
    logging.debug(f"Overriding keys {overrides}")
    oc_map = OC_Map(
        namespaces=namespaces,
        integration=QONTRACT_INTEGRATION,
        settings=settings,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
        init_api_resources=init_api_resources,
    )
    state_specs = ob.init_specs_to_fetch(
        ri, oc_map, namespaces=namespaces, override_managed_types=overrides
    )
    threaded.run(fetch_states, state_specs, thread_pool_size, ri=ri, settings=settings)

    return oc_map, ri


def filter_namespaces_by_cluster_and_namespace(
    namespaces, cluster_name, namespace_name
):
    if cluster_name:
        namespaces = [n for n in namespaces if n["cluster"]["name"] == cluster_name]
    if namespace_name:
        namespaces = [n for n in namespaces if n["name"] == namespace_name]
    return namespaces


def canonicalize_namespaces(
    namespaces: Iterable[dict[str, Any]],
    providers: list[str],
    resource_schema_filter: Optional[str] = None,
) -> tuple[list[dict[str, Any]], Optional[list[str]]]:
    canonicalized_namespaces = []
    override = None
    logging.debug(f"Received providers {providers}")
    for namespace_info in namespaces:
        ob.aggregate_shared_resources(namespace_info, "openshiftResources")
        openshift_resources: list = namespace_info.get("openshiftResources") or []
        ors = [
            r
            for r in openshift_resources
            if r["provider"] in providers
            and (
                resource_schema_filter is None
                or r["resource"]["schema"] == resource_schema_filter
            )
        ]
        if ors and providers:
            # For the time being we only care about the first item in
            # providers
            # TODO: confvert it to a scalar?
            if providers[0] == "vault-secret":
                override = ["Secret"]
            elif providers[0] == "route":
                override = ["Route"]
            namespace_info["openshiftResources"] = ors
            canonicalized_namespaces.append(namespace_info)
    logging.debug(f"Overriding {override}")
    return canonicalized_namespaces, override


def get_namespaces(
    providers: Optional[list[str]] = None,
    cluster_name: Optional[str] = None,
    namespace_name: Optional[str] = None,
    resource_schema_filter: Optional[str] = None,
    filter_by_shard: Optional[bool] = True,
) -> tuple[list[dict[str, Any]], Optional[list[str]]]:
    if providers is None:
        providers = []
    gqlapi = gql.get_api()
    namespaces = [
        namespace_info
        for namespace_info in gqlapi.query(NAMESPACES_QUERY)["namespaces"]
        if not ob.is_namespace_deleted(namespace_info)
        and (
            not filter_by_shard
            or is_in_shard(
                f"{namespace_info['cluster']['name']}/" + f"{namespace_info['name']}"
            )
        )
    ]
    namespaces = filter_namespaces_by_cluster_and_namespace(
        namespaces, cluster_name, namespace_name
    )
    return canonicalize_namespaces(namespaces, providers, resource_schema_filter)


@defer
def run(
    dry_run,
    thread_pool_size=10,
    internal=None,
    use_jump_host=True,
    providers=None,
    cluster_name=None,
    namespace_name=None,
    init_api_resources=False,
    defer=None,
):
    namespaces, overrides = get_namespaces(
        providers=providers, cluster_name=cluster_name, namespace_name=namespace_name
    )
    if not namespaces:
        logging.info(
            "No namespaces found when filtering for "
            f"cluster={cluster_name}, namespace={namespace_name}. "
            "Exiting."
        )
        return None
    oc_map, ri = fetch_data(
        namespaces,
        thread_pool_size,
        internal,
        use_jump_host,
        init_api_resources=init_api_resources,
        overrides=overrides,
    )
    defer(oc_map.cleanup)
    if dry_run and QONTRACT_INTEGRATION == "openshift-resources":
        error = check_cluster_scoped_resources(oc_map, ri, namespaces, None)
        if error:
            sys.exit(1)

    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    if ri.has_error_registered():
        sys.exit(1)

    return ri


class CheckError(Exception):
    pass


class CheckNamespaceResources(Protocol):
    def check(self) -> list[Exception]:
        pass


@dataclass
class CheckClusterScopedResourceNames:
    oc_map: OC_Map
    ri: ResourceInventory
    namespaces: list[Mapping[str, Any]]

    def check(self) -> list[Exception]:
        errors: list[Exception] = []
        for ns in self.namespaces:
            cluster_name = ns["cluster"]["name"]
            try:
                oc = self.oc_map.get_cluster(cluster_name)
            except OCLogMsg as ex:
                if ex.log_level >= logging.ERROR:
                    self.ri.register_error()
                    errors.append(ex)
                continue

            ns_type_overrides = ob.get_namespace_type_overrides(ns)
            managed_resource_types = ob.get_namespace_resource_types(
                ns, ns_type_overrides
            )
            cluster_scoped_types = [
                k for k in managed_resource_types if not oc.is_kind_namespaced(k)
            ]

            if len(cluster_scoped_types) > 0:
                # Check that all non namespaced resources are explicitly set in the
                # ManagedResourceNames attribute.
                mrn = ob.get_namespace_resource_names(ns, ns_type_overrides)
                for kind in cluster_scoped_types:
                    declared_items = mrn.get(kind, [])
                    desired_items = set(
                        self.ri.get_desired_by_type(
                            cluster_name, ns["name"], kind
                        ).keys()
                    )
                    diff = desired_items.difference(declared_items)
                    if len(diff) > 0:
                        errors.append(
                            CheckError(
                                "Cluster scoped resources not defined in ManagedResourceNames. "
                                f"cluster: {cluster_name}, namespace: {ns['name']}, "
                                f"kind:{kind}, names:{diff}",
                            )
                        )

        return errors


@dataclass
class CheckClusterScopedResourceDuplicates:
    oc_map: OC_Map
    all_namespaces: Optional[list[Mapping]] = None

    def check(self) -> list[Exception]:
        errors: list[Exception] = []
        clusters = set(self.oc_map.clusters() + self.oc_map.clusters(privileged=True))
        cluster_cs_resources = get_cluster_scoped_resources(
            self.oc_map, clusters, self.all_namespaces
        )

        duplicates = self._find_resource_duplicates(cluster_cs_resources)
        for cluster, kind, name, namespaces in duplicates:
            errors.append(
                CheckError(
                    f"Cluster resource defined in multiple namespaces. "
                    f"cluster: {cluster}, namespaces: {namespaces}, "
                    f"kind:{kind}, name:{name}"
                )
            )
        return errors

    def _find_resource_duplicates(
        self, cluster_cs_resources: dict[str, dict[str, dict[str, list[str]]]]
    ) -> list[Tuple[str, str, str, list[str]]]:
        # ) -> dict[Tuple[str, str, str], list[str]]:
        """Finds cluster resource duplicates by kind/name.
        :param cluster_cs_resources
        :return: duplicates as [(cluster, kind, name, [namespaces])]
        """
        duplicates: list[Tuple[str, str, str, list[str]]] = []

        for cluster, cluster_resources in cluster_cs_resources.items():
            _kind_name: dict[str, dict[str, list[str]]] = {}
            for ns, resources in cluster_resources.items():
                for kind, names in resources.items():
                    k_ref = _kind_name.setdefault(kind, {})
                    for name in names:
                        n_ref = k_ref.setdefault(name, [])
                        n_ref.append(ns)
                        if len(n_ref) > 1:
                            duplicates.append((cluster, kind, name, n_ref))

        return duplicates


def check_cluster_scoped_resources(
    oc_map: OC_Map,
    ri: ResourceInventory,
    namespaces: list[Mapping[str, Any]],
    all_namespaces: Optional[list[Mapping[str, Any]]] = None,
) -> bool:

    checks = [
        CheckClusterScopedResourceNames(oc_map, ri, namespaces),
        CheckClusterScopedResourceDuplicates(oc_map, all_namespaces),
    ]

    results = threaded.run(
        lambda x: x.check(), checks, len(checks), return_exceptions=True
    )
    errors = list(itertools.chain.from_iterable(results))

    for e in errors:
        logging.error(e)

    return len(errors) > 0


def get_cluster_scoped_resources(
    oc_map: OC_Map,
    clusters: Iterable[str],
    namespaces: Optional[Iterable[Mapping[str, Any]]] = None,
    thread_pool_size: int = 10,
) -> dict[str, dict[str, dict[str, list[str]]]]:
    """Returns cluster scoped resources for a list of clusters

    :param oc_map: OC_Map
    :param clusters: Iterable whith the clusters list
    :param namespaces: Namespaces where to find the clusters
    :param thread_pool_size: defaults to 10
    :return: {cluster: {ns: {kind:[names], ns2:...}, cluster2:...}
    """

    if not namespaces:
        namespaces, _ = get_namespaces(
            providers=["resource", "resource-template"], filter_by_shard=False
        )

    cluster_namespaces = [ns for ns in namespaces if ns["cluster"]["name"] in clusters]

    results = threaded.run(
        _get_namespace_cluster_scoped_resources,
        cluster_namespaces,
        thread_pool_size,
        False,
        oc_map=oc_map,
    )
    cluster_resources: dict[str, dict[str, dict[str, list[str]]]] = {}
    for cluster, namespace, resources in results:
        c_ref = cluster_resources.setdefault(cluster, {})
        c_ref[namespace] = resources

    return cluster_resources


def _get_namespace_cluster_scoped_resources(
    namespace: Mapping,
    oc_map: OC_Map,
) -> Tuple[str, str, dict[str, dict[str, Any]]]:
    """Returns all non-namespaced resources defined in a namespace manifest.

    :param namespace: the namespace dict
    :param oc: OC_Map
    :return: {ns: {kind:[names]} if resources else None
    """
    managed_resource_names = ob.get_namespace_resource_names(namespace)
    resources: dict[str, Any] = {}
    cluster_name = namespace["cluster"]["name"]
    oc = oc_map.get_cluster(cluster_name)
    for kind, names in managed_resource_names.items():
        if not oc.is_kind_namespaced(kind):
            resources_kind_list = resources.setdefault(kind, [])
            resources_kind_list += names
    return (cluster_name, namespace["name"], resources)


def early_exit_desired_state(
    providers: list[str], resource_schema_filter: Optional[str] = None
) -> dict[str, Any]:
    settings = queries.get_secret_reader_settings()
    namespaces, _ = get_namespaces(
        providers, resource_schema_filter=resource_schema_filter
    )
    fetch_specs = [
        (r, ns_info) for ns_info in namespaces for r in ns_info["openshiftResources"]
    ]

    # this context manager patches functions used during jinja templating
    # to ignore data that is not part of the desired state in app-interface.
    # the context manager also ensures this function patching is
    # reverted afterwards
    with _early_exit_monkey_patch():
        resources = threaded.run(
            _early_exit_fetch_resource,
            fetch_specs,
            thread_pool_size=10,
            settings=settings,
        )

    def post_process_ns(ns):
        ns[IDENTIFIER_FIELD_NAME] = f"{ns['cluster']['name']}/{ns['name']}"
        # the sharedResources have been aggreated into the openshiftResources
        # and are no longer needed - speeds up diffing process
        del ns["sharedResources"]
        return ns

    return {
        "namespaces": [post_process_ns(ns) for ns in namespaces],
        "resources": resources,
    }


def _early_exit_fetch_resource(spec, settings):
    resource = spec[0]
    ns_info = spec[1]
    cluster_name = ns_info["cluster"]["name"]
    id = f"{cluster_name}/{ns_info['name']}/{resource['provider']}/{resource['resource']['path']}"
    if resource.get("enable_query_support"):
        # use the regular resource processing functionality that evaluates templates
        # and inline queries, if the resource is allowed to use this inline query
        # functionality. this is crucial in such situations because the result of
        # the template processing depends heavily on other data in app-interface
        c = fetch_openshift_resource(
            resource, ns_info, skip_validation=True, settings=settings
        ).body
    else:
        # for regular resources, the plain content is sufficient enough to
        # detect changes in desired state
        c = resource["resource"].get("content")
    del resource["resource"]
    resource[IDENTIFIER_FIELD_NAME] = id
    content_sha = hashlib.md5(c.encode("utf-8")).hexdigest()
    return {
        IDENTIFIER_FIELD_NAME: id,
        "cluster": cluster_name,
        "content_sha": content_sha,
    }


@contextmanager
def _early_exit_monkey_patch():
    """Avoid looking outside of app-interface on early-exit pr-check."""
    orig_lookup_secret = lookup_secret
    orig_lookup_github_file_content = lookup_github_file_content
    orig_url_makes_sense = url_makes_sense
    orig_check_alertmanager_config = check_alertmanager_config

    try:
        yield _early_exit_monkey_patch_assign(
            lambda path, key, version=None, tvars=None, settings=None: f"vault({path}, {key}, {version})",
            lambda repo, path, ref, tvars=None, settings=None: f"github({repo}, {path}, {ref})",
            lambda url: False,
            lambda data, path, alertmanager_config_key, decode_base64=False: True,
        )
    finally:
        _early_exit_monkey_patch_assign(
            orig_lookup_secret,
            orig_lookup_github_file_content,
            orig_url_makes_sense,
            orig_check_alertmanager_config,
        )


def _early_exit_monkey_patch_assign(
    lookup_secret,
    lookup_github_file_content,
    url_makes_sense,
    check_alertmanager_config,
):
    sys.modules[__name__].lookup_secret = lookup_secret
    sys.modules[__name__].lookup_github_file_content = lookup_github_file_content
    sys.modules[__name__].url_makes_sense = url_makes_sense
    sys.modules[__name__].check_alertmanager_config = check_alertmanager_config


def desired_state_shard_config() -> DesiredStateShardConfig:
    return DesiredStateShardConfig(
        shard_arg_name="cluster_name",
        shard_path_selectors={
            "namespaces[*].cluster.name",
            "resources[*].cluster",
        },
        sharded_run_review=lambda proposal: len(proposal.proposed_shards) <= 2,
    )

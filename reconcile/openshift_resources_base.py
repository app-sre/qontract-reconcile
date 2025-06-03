import base64
import hashlib
import itertools
import json
import logging
import re
import sys
from collections import defaultdict
from collections.abc import (
    Callable,
    Generator,
    Iterable,
    Mapping,
    MutableMapping,
    Sequence,
)
from contextlib import contextmanager
from dataclasses import dataclass
from textwrap import indent
from threading import Lock
from typing import (
    Any,
    Protocol,
)
from unittest.mock import DEFAULT, patch

import anymarkup
from deepdiff import DeepHash
from sretoolbox.utils import (
    threaded,
)

import reconcile.openshift_base as ob
import reconcile.utils.jinja2.utils as jinja2_utils
from reconcile import queries
from reconcile.change_owners.diff import IDENTIFIER_FIELD_NAME
from reconcile.external_resources.meta import SECRET_UPDATED_AT
from reconcile.utils import (
    amtool,
    gql,
    openssl,
)
from reconcile.utils.defer import defer
from reconcile.utils.exceptions import FetchResourceError
from reconcile.utils.jinja2.utils import (
    FetchSecretError,
    process_extracurlyjinja2_template,
    process_jinja2_template,
)
from reconcile.utils.oc import (
    OC_Map,
    OCClient,
    OCLogMsg,
    StatusCodeError,
)
from reconcile.utils.openshift_resource import (
    ConstructResourceError,
    ResourceInventory,
    ResourceKeyExistsError,
    ResourceNotManagedError,
    base64_encode_secret_field_value,
)
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.runtime.integration import DesiredStateShardConfig
from reconcile.utils.secret_reader import SecretReader, SecretReaderBase
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.sharding import is_in_shard
from reconcile.utils.vault import (
    SecretVersionIsNone,
    SecretVersionNotFound,
)

# +-----------------------+-------------------------+-------------+
# |   Current / Desired   |         Present         | Not Present |
# +=======================+=========================+=============+
# | Present               | Apply if sha256sum      | Delete      |
# | (with annotations)    | is different or if      |             |
# |                       | sha256sum is stale      |             |
# |                       | (due to manual changes) |             |
# +-----------------------+-------------------------+-------------+
# | Present               | Annotate and apply      | Skip        |
# | (without annotations) |                         |             |
# +-----------------------+-------------------------+-------------+
# | Not Present           | Apply                   | Skip        |
# +-----------------------+-------------------------+-------------+


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
... on NamespaceOpenshiftResourcePrometheusRule_v1 {
  resource: path {
    content
    path
    schema
  }
  type
  variables
  enable_query_support
  tests
}
"""

NAMESPACES_QUERY = """
{
  namespaces: namespaces_v1 {
    name
    path
    labels
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
    environment {
      name
      parameters
    }
    cluster {
      name
      labels
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
        ... on ClusterSpecROSA_v1 {
          account {
            uid
          }
        }
        version
        region
        hypershift
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
KUBERNETES_SECRET_DATA_KEY_RE = "^[-._a-zA-Z0-9]+$"

# Keys in vault secrets that do not need to land
# into K8S secrets.
VAULT_SECRETS_EXCLUDED_KEYS = {SECRET_UPDATED_AT}
_log_lock = Lock()


def _locked_info_log(msg: str) -> None:
    with _log_lock:
        logging.info(msg)


def _locked_debug_log(msg: str) -> None:
    with _log_lock:
        logging.debug(msg)


def _locked_error_log(msg: str) -> None:
    with _log_lock:
        logging.error(msg)


class FetchRouteError(Exception):
    def __init__(self, msg: Any):
        super().__init__("error fetching route: " + str(msg))


class ResourceTemplateRenderError(Exception):
    pass


class SecretKeyFormatError(Exception):
    pass


class UnknownProviderError(Exception):
    def __init__(self, msg: Any):
        super().__init__("unknown provider error: " + str(msg))


class UnknownTemplateTypeError(Exception):
    def __init__(self, msg: Any):
        super().__init__("unknown template type error: " + str(msg))


def check_alertmanager_config(
    data: Mapping[str, Any],
    path: str,
    alertmanager_config_key: str,
    decode_base64: bool = False,
) -> None:
    try:
        config = data[alertmanager_config_key]
    except KeyError:
        e_msg = (
            f"error validating alertmanager config in {path}: "
            f"missing key {alertmanager_config_key}"
        )
        raise FetchResourceError(e_msg) from None

    if decode_base64:
        config = base64.b64decode(config).decode("utf-8")

    result = amtool.check_config(config)
    if not result:
        e_msg = f"error validating alertmanager config in {path}: {result}"
        raise FetchResourceError(e_msg)


def fetch_provider_resource(
    resource: Mapping,
    tfunc: Callable | None = None,
    tvars: Mapping[str, Any] | None = None,
    validate_json: bool = False,
    validate_alertmanager_config: bool = False,
    alertmanager_config_key: str = "alertmanager.yaml",
    add_path_to_prom_rules: bool = True,
    skip_validation: bool = False,
    settings: Mapping[str, Any] | None = None,
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
        raise FetchResourceError(e_msg) from None
    except anymarkup.AnyMarkupError:
        e_msg = f"Could not parse data. Skipping resource: {path}"
        raise FetchResourceError(e_msg) from None

    if validate_json:
        files = body["data"]
        for file_name, file_content in files.items():
            try:
                json.loads(file_content)
            except ValueError:
                e_msg = f"invalid json in {path} under {file_name}"
                raise FetchResourceError(e_msg) from None

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
            app_int_base_url = "https://gitlab.cee.redhat.com/service/app-interface"
            if settings and "repoUrl" in settings:
                app_int_base_url = settings["repoUrl"]
            try:
                groups = body["spec"]["groups"]
                for group in groups:
                    rules = group["rules"]
                    for rule in rules:
                        annotations = rule.get("annotations")
                        if not annotations:
                            continue
                        rule["annotations"]["html_url"] = (
                            f"{app_int_base_url}/blob/master/resources{path}"
                        )
            except Exception:
                logging.warning(
                    "could not add html_url annotation to" + body["metadata"]["name"]
                )

    try:
        return OR(
            body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION, error_details=path
        )
    except ConstructResourceError as e:
        raise FetchResourceError(str(e)) from None


def fetch_provider_vault_secret(
    path: str,
    version: str,
    name: str,
    labels: Mapping[str, str] | None,
    annotations: Mapping[str, str],
    type: str,
    integration: str,
    integration_version: str,
    validate_alertmanager_config: bool = False,
    alertmanager_config_key: str = "alertmanager.yaml",
    settings: Mapping[str, Any] | None = None,
    secret_reader: SecretReaderBase | None = None,
) -> OR:
    if not secret_reader and not settings:
        raise Exception(
            "Parameter settings or secret_reader must be provided to run fetch_provider_vault_secret."
        )

    if not secret_reader:
        # get the fields from vault
        secret_reader = SecretReader(settings)
    raw_data = {
        k: v
        for k, v in secret_reader.read_all({"path": path, "version": version}).items()
        if k not in VAULT_SECRETS_EXCLUDED_KEYS
    }

    if validate_alertmanager_config:
        check_alertmanager_config(raw_data, path, alertmanager_config_key)

    # construct oc resource
    body: dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": type,
        "metadata": {"name": name, "annotations": annotations},
    }
    if labels:
        body["metadata"]["labels"] = labels

    assert_valid_secret_keys(raw_data)

    # populate data
    for k, v in raw_data.items():
        if k.lower().endswith(QONTRACT_BASE64_SUFFIX):
            k = k[: -len(QONTRACT_BASE64_SUFFIX)]
            v = v.replace("\n", "")
        else:
            v = base64_encode_secret_field_value(v)
        body.setdefault("data", {})[k] = v

    try:
        return OR(body, integration, integration_version, error_details=path)
    except ConstructResourceError as e:
        raise FetchResourceError(str(e)) from None


# check to ensure that all of the keys are valid by looking to see if there are
# any white space issues. If any issues are uncovered, an exception will be
# raised.
# we're receiving the full key: value information, not simply a list of keys.
def assert_valid_secret_keys(secrets_data: dict[str, str]) -> None:
    for k in secrets_data:
        matches = re.search(KUBERNETES_SECRET_DATA_KEY_RE, k)
        if not matches:
            raise SecretKeyFormatError(
                f"'{k}' is not valid key name for a Secret. a valid Secret key must consist of alphanumeric characters, '-', '_' or '.' (e.g. 'key.name',  or 'KEY_NAME',  or 'key-name', regex used for validation is '^[-._a-zA-Z0-9]+$')"
            )


def fetch_provider_route(
    resource: Mapping,
    tls_path: str | None,
    tls_version: str | None,
    settings: Mapping | None = None,
) -> OR:
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

        msg = f"Route secret '{tls_path}' key '{k}' not in valid keys {valid_keys}"
        _locked_info_log(msg)

    host = openshift_resource.body["spec"].get("host")
    certificate = openshift_resource.body["spec"]["tls"].get("certificate")
    if host and certificate:
        match = openssl.certificate_matches_host(certificate, host)
        if not match:
            e_msg = "Route host does not match CN (common name): {}"
            raise FetchRouteError(e_msg.format(path))

    return openshift_resource


def fetch_openshift_resource(
    resource: Mapping,
    parent: Mapping[str, Any],
    settings: Mapping | None = None,
    skip_validation: bool = False,
) -> OR:
    provider = resource["provider"]
    if provider == "resource":
        path = resource["resource"]["path"]
        _locked_debug_log(f"Processing {provider}: {path}")
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
        _locked_debug_log(f"Processing {provider}: {path}")
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
            raise UnknownTemplateTypeError(tt)
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
            msg = f"could not render template at path {path}\n{e}"
            raise ResourceTemplateRenderError(msg) from None
    elif provider == "vault-secret":
        path = resource["path"]
        version = resource["version"]
        _locked_debug_log(f"Processing {provider}: {path} - {version}")
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
            raise FetchSecretError(e) from None
    elif provider == "route":
        path = resource["resource"]["path"]
        _locked_debug_log(f"Processing {provider}: {path}")
        tls_path = resource["vault_tls_secret_path"]
        tls_version = resource["vault_tls_secret_version"]
        openshift_resource = fetch_provider_route(
            resource["resource"], tls_path, tls_version, settings
        )
    elif provider == "prometheus-rule":
        path = resource["resource"]["path"]
        _locked_debug_log(f"Processing {provider}: {path}")
        add_path_to_prom_rules = resource.get("add_path_to_prom_rules", True)
        tv = {}
        if resource["variables"]:
            tv = anymarkup.parse(resource["variables"], force_types=None)
        tv["resource"] = resource
        tv["resource"]["namespace"] = parent

        tt = resource["type"]
        if tt == "resource":
            tfunc = None
            tv = None
        elif tt == "resource-template-jinja2":
            tfunc = process_jinja2_template
        elif tt == "resource-template-extracurlyjinja2":
            tfunc = process_extracurlyjinja2_template
        else:
            raise UnknownTemplateTypeError(tt)
        try:
            openshift_resource = fetch_provider_resource(
                resource["resource"],
                tfunc=tfunc,
                tvars=tv,
                add_path_to_prom_rules=add_path_to_prom_rules,
                skip_validation=skip_validation,
                settings=settings,
            )
        except Exception as e:
            msg = f"could not render template at path {path}\n{e}"
            raise ResourceTemplateRenderError(msg) from None

    else:
        raise UnknownProviderError(provider)

    return openshift_resource


def fetch_current_state(
    oc: OCClient,
    ri: ResourceInventory,
    cluster: str,
    namespace: str,
    kind: str,
    resource_names: Iterable[str] | None,
) -> None:
    _locked_debug_log(f"Fetching {kind} from {cluster}/{namespace}")
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
    settings: Mapping[str, Any] | None = None,
) -> None:
    try:
        openshift_resource = fetch_openshift_resource(resource, parent, settings)
    except (
        FetchResourceError,
        FetchSecretError,
        FetchRouteError,
        UnknownProviderError,
    ) as e:
        ri.register_error()
        msg = f"[{cluster}/{namespace}] {e!s}"
        _locked_error_log(msg)
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
        msg = f"[{cluster}/{namespace}] unknown kind: {openshift_resource.kind}. hint: is it missing from managedResourceTypes?"
        _locked_error_log(msg)
        return
    except ResourceKeyExistsError:
        # This is failing because an attempt to add
        # a desired resource with the same name and
        # the same type was already added previously
        ri.register_error()
        msg = f"[{cluster}/{namespace}] desired item already exists: {openshift_resource.kind}/{openshift_resource.name}."
        _locked_error_log(msg)
        return
    except ResourceNotManagedError:
        # This is failing because the resource name is
        # not in the list of resource names that are managed
        ri.register_error()
        msg = f"[{cluster}/{namespace}] desired item is not managed: {openshift_resource.kind}/{openshift_resource.name}."
        _locked_error_log(msg)
        return


def fetch_states(
    spec: ob.StateSpec,
    ri: ResourceInventory,
    settings: Mapping[str, Any] | None = None,
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
        logging.error(f"{spec} - exception: {e!s}")


def fetch_data(
    namespaces: Iterable[Mapping[str, Any]],
    thread_pool_size: int,
    internal: bool | None,
    use_jump_host: bool,
    init_api_resources: bool = False,
    overrides: Iterable[str] | None = None,
) -> tuple[OC_Map, ResourceInventory]:
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
    namespaces: Sequence[dict[str, Any]],
    cluster_names: Iterable[str] | None,
    exclude_clusters: Iterable[str] | None,
    namespace_name: str | None,
) -> Sequence[dict[str, Any]]:
    if cluster_names:
        namespaces = [n for n in namespaces if n["cluster"]["name"] in cluster_names]
    elif exclude_clusters:
        namespaces = [
            n for n in namespaces if n["cluster"]["name"] not in exclude_clusters
        ]

    if namespace_name:
        namespaces = [n for n in namespaces if n["name"] == namespace_name]

    return namespaces


def canonicalize_namespaces(
    namespaces: Iterable[dict[str, Any]],
    providers: Sequence[str],
    resource_schema_filter: str | None = None,
) -> tuple[list[dict[str, Any]], list[str] | None]:
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
            elif providers[0] == "prometheus-rule":
                override = ["PrometheusRule"]

            namespace_info["openshiftResources"] = ors
            canonicalized_namespaces.append(namespace_info)
    logging.debug(f"Overriding {override}")
    return canonicalized_namespaces, override


def get_namespaces(
    providers: Sequence[str] | None = None,
    cluster_names: Iterable[str] | None = None,
    exclude_clusters: Iterable[str] | None = None,
    namespace_name: str | None = None,
    resource_schema_filter: str | None = None,
    filter_by_shard: bool | None = True,
) -> tuple[list[dict[str, Any]], list[str] | None]:
    if providers is None:
        providers = []
    gqlapi = gql.get_api()
    namespaces: list[dict[str, Any]] = [
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
    namespaces_ = filter_namespaces_by_cluster_and_namespace(
        namespaces, cluster_names, exclude_clusters, namespace_name
    )
    return canonicalize_namespaces(namespaces_, providers, resource_schema_filter)


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    internal: bool | None = None,
    use_jump_host: bool = True,
    providers: Sequence[str] | None = None,
    cluster_name: Sequence[str] | None = None,
    exclude_cluster: Sequence[str] | None = None,
    namespace_name: str | None = None,
    init_api_resources: bool = False,
    defer: Callable | None = None,
) -> ResourceInventory | None:
    # https://click.palletsprojects.com/en/8.1.x/options/#multiple-options
    cluster_names = cluster_name
    exclude_clusters = exclude_cluster

    if exclude_clusters and not dry_run:
        raise RuntimeError("--exclude-cluster is only supported in dry-run mode")

    if exclude_clusters and cluster_names:
        raise RuntimeError(
            "--cluster-name and --exclude-cluster can not be used together"
        )
    if cluster_names and len(cluster_names) > 1 and not dry_run:
        raise RuntimeError(
            "Running with multiple clusters is only supported in dry-run mode"
        )

    namespaces, overrides = get_namespaces(
        providers=providers,
        cluster_names=cluster_names,
        exclude_clusters=exclude_clusters,
        namespace_name=namespace_name,
    )
    if not namespaces:
        logging.debug(
            "No namespaces found when filtering for "
            f"cluster={cluster_names}, namespace={namespace_name}. "
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
    if defer:
        defer(oc_map.cleanup)
    if dry_run and QONTRACT_INTEGRATION == "openshift-resources":
        error = check_cluster_scoped_resources(oc_map, ri, namespaces, None)
        if error:
            sys.exit(1)

    ob.publish_metrics(ri, QONTRACT_INTEGRATION)
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
    namespaces: Iterable[Mapping[str, Any]]

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
    all_namespaces: Iterable[Mapping] | None = None

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
    ) -> list[tuple[str, str, str, list[str]]]:
        # ) -> dict[Tuple[str, str, str], list[str]]:
        """Finds cluster resource duplicates by kind/name.
        :param cluster_cs_resources
        :return: duplicates as [(cluster, kind, name, [namespaces])]
        """
        duplicates: list[tuple[str, str, str, list[str]]] = []

        for cluster, cluster_resources in cluster_cs_resources.items():
            kind_name: dict[str, dict[str, list[str]]] = {}
            for ns, resources in cluster_resources.items():
                for kind, names in resources.items():
                    k_ref = kind_name.setdefault(kind, {})
                    for name in names:
                        n_ref = k_ref.setdefault(name, [])
                        n_ref.append(ns)
                        if len(n_ref) > 1:
                            duplicates.append((cluster, kind, name, n_ref))

        return duplicates


def check_cluster_scoped_resources(
    oc_map: OC_Map,
    ri: ResourceInventory,
    namespaces: Iterable[Mapping[str, Any]],
    all_namespaces: Iterable[Mapping[str, Any]] | None = None,
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
    namespaces: Iterable[Mapping[str, Any]] | None = None,
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
) -> tuple[str, str, dict[str, dict[str, Any]]]:
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
    providers: list[str], resource_schema_filter: str | None = None
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
    with early_exit_monkey_patch():
        resources = threaded.run(
            _early_exit_fetch_resource,
            fetch_specs,
            thread_pool_size=10,
            settings=settings,
        )

    def post_process_ns(ns: MutableMapping) -> MutableMapping:
        # the sharedResources have been aggreated into the openshiftResources
        # and are no longer needed - speeds up diffing process
        del ns["sharedResources"]
        return ns

    # assemble all namespaces and resources file under a cluster
    state_for_clusters = defaultdict(list)
    for ns in namespaces:
        state_for_clusters[ns["cluster"]["name"]].append(post_process_ns(ns))
    for res in resources:
        state_for_clusters[res["cluster"]].append(res)

    return {
        "state": {
            cluster: {"shard": cluster, "hash": DeepHash(state).get(state)}
            for cluster, state in state_for_clusters.items()
        }
    }


def _early_exit_fetch_resource(spec: Sequence, settings: Mapping) -> dict[str, str]:
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
def early_exit_monkey_patch() -> Generator:
    """Avoid looking outside of app-interface on early-exit pr-check."""
    with patch.multiple(
        jinja2_utils,
        lookup_secret=DEFAULT,
        lookup_github_file_content=DEFAULT,
        url_makes_sense=DEFAULT,
        lookup_s3_object=DEFAULT,
        list_s3_objects=DEFAULT,
    ) as mocks:
        # mock lookup_secret
        mocks["lookup_secret"].side_effect = (
            lambda path,
            key,
            version=None,
            tvars=None,
            allow_not_found=False,
            settings=None,
            secret_reader=None: f"vault({path}, {key}, {version}"
        )
        # needed for jinja2 `is_safe_callable`
        mocks["lookup_secret"].unsafe_callable = False
        mocks["lookup_secret"].alters_data = False

        # mock lookup_github_file_content
        mocks["lookup_github_file_content"].side_effect = (
            lambda repo,
            path,
            ref,
            tvars=None,
            settings=None,
            secret_reader=None: f"github({repo}, {path}, {ref})"
        )
        # needed for jinja2 `is_safe_callable`
        mocks["lookup_github_file_content"].unsafe_callable = False
        mocks["lookup_github_file_content"].alters_data = False

        # mock url_makes_sense
        mocks["url_makes_sense"].side_effect = lambda url: False
        # needed for jinja2 `is_safe_callable`
        mocks["url_makes_sense"].unsafe_callable = False
        mocks["url_makes_sense"].alters_data = False

        # mock lookup_s3_object
        mocks["lookup_s3_object"].side_effect = (
            lambda account_name,
            bucket_name,
            path,
            region_name=None: f"lookup_s3_object({account_name}, {bucket_name}, {path}, {region_name})"
        )
        # needed for jinja2 `is_safe_callable`
        mocks["lookup_s3_object"].unsafe_callable = False
        mocks["lookup_s3_object"].alters_data = False

        # mock list_s3_objects
        mocks["list_s3_objects"].side_effect = (
            lambda account_name,
            bucket_name,
            path,
            region_name=None: f"list_s3_objects({account_name}, {bucket_name}, {path}, {region_name})"
        )
        # needed for jinja2 `is_safe_callable`
        mocks["list_s3_objects"].unsafe_callable = False
        mocks["list_s3_objects"].alters_data = False

        with patch(
            "reconcile.openshift_resources_base.check_alertmanager_config",
            return_value=True,
        ):
            yield


def desired_state_shard_config() -> DesiredStateShardConfig:
    return DesiredStateShardConfig(
        shard_arg_name="cluster_name",
        shard_arg_is_collection=True,
        shard_path_selectors={"state.*.shard"},
        sharded_run_review=lambda proposal: len(proposal.proposed_shards) <= 2,
    )

from contextlib import contextmanager
from typing import Any
from sretoolbox.utils import threaded

import reconcile.openshift_base as ob
import reconcile.openshift_resources_base as orb

from reconcile import queries
from reconcile.utils import gql
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "openshift_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 9, 3)
PROVIDERS = ["resource", "resource-template"]


def run(
    dry_run,
    thread_pool_size=10,
    internal=None,
    use_jump_host=True,
    cluster_name=None,
    namespace_name=None,
    defer=None,
):
    orb.QONTRACT_INTEGRATION = QONTRACT_INTEGRATION
    orb.QONTRACT_INTEGRATION_VERSION = QONTRACT_INTEGRATION_VERSION

    ri = orb.run(
        dry_run=dry_run,
        thread_pool_size=thread_pool_size,
        internal=internal,
        use_jump_host=use_jump_host,
        providers=PROVIDERS,
        cluster_name=cluster_name,
        namespace_name=namespace_name,
        init_api_resources=True,
    )

    # check for unused resources types
    # listed under `managedResourceTypes`
    ob.check_unused_resource_types(ri)


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    gqlapi = gql.get_api()
    settings = queries.get_secret_reader_settings()
    namespaces, _ = orb.get_namespaces(PROVIDERS)
    fetch_specs = [
        (r, ns_info) for ns_info in namespaces for r in ns_info["openshiftResources"]
    ]
    with early_exit_monkey_patch():
        resources = threaded.run(
            get_resource,
            fetch_specs,
            thread_pool_size=10,
            gqlapi=gqlapi,
            settings=settings,
        )
    return {
        "namespaces": namespaces,
        "resources": resources,
    }


def get_resource(spec, gqlapi, settings):
    resource = spec[0]
    ns_info = spec[1]
    if resource.get("enable_query_support"):
        return orb.fetch_openshift_resource(resource, ns_info, settings=settings).body
    else:
        return gqlapi.get_resource(resource["path"])


@contextmanager
def early_exit_monkey_patch():
    """Avoid looking outside of app-interface on early-exit pr-check."""
    lookup_secret = orb.lookup_secret
    lookup_github_file_content = orb.lookup_github_file_content
    url_makes_sense = orb.url_makes_sense
    check_alertmanager_config = orb.check_alertmanager_config

    try:
        yield early_exit_monkey_patch_assign(
            lambda path, key, version=None, tvars=None, settings=None: f"vault({path}, {key}, {version})",
            lambda repo, path, ref, tvars=None, settings=None: f"github({repo}, {path}, {ref})",
            lambda url: False,
            lambda data, path, alertmanager_config_key, decode_base64=False: True,
        )
    finally:
        early_exit_monkey_patch_assign(
            lookup_secret,
            lookup_github_file_content,
            url_makes_sense,
            check_alertmanager_config,
        )


def early_exit_monkey_patch_assign(
    lookup_secret,
    lookup_github_file_content,
    url_makes_sense,
    check_alertmanager_config,
):
    orb.lookup_secret = lookup_secret
    orb.lookup_github_file_content = lookup_github_file_content
    orb.url_makes_sense = url_makes_sense
    orb.check_alertmanager_config = check_alertmanager_config

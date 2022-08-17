from typing import Any

import reconcile.openshift_base as ob
import reconcile.openshift_resources_base as orb

from reconcile import queries
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
    early_exit_monkey_patch()
    settings = queries.get_secret_reader_settings()
    namespaces, _ = orb.get_namespaces(PROVIDERS)
    resources = [
        orb.fetch_openshift_resource(r, ns_info, settings=settings).body
        for ns_info in namespaces
        for r in ns_info["openshiftResources"]
    ]

    return {
        "namespaces": namespaces,
        "resources": resources,
    }


def early_exit_monkey_patch():
    """Avoid looking outside of app-interface on early-exit pr-check."""
    orb.lookup_secret = (
        lambda path, key, version=None, tvars=None, settings=None: f"vault({path}, {key}, {version})"
    )
    orb.lookup_github_file_content = (
        lambda repo, path, ref, tvars=None, settings=None: f"github({repo}, {path}, {ref})"
    )
    orb.url_makes_sense = lambda url: False  # type: ignore[assignment]
    orb.check_alertmanager_config = (
        lambda data, path, alertmanager_config_key, decode_base64=False: True
    )

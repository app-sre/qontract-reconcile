import logging
from collections.abc import Callable
from threading import Lock
from typing import Any

from sretoolbox.utils import threaded

import reconcile.openshift_base as osb
from reconcile import (
    jenkins_base,
    queries,
)
from reconcile.openshift_tekton_resources import (
    build_one_per_saas_file_tkn_pipeline_name,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.saas_files import (
    get_saas_files,
    get_saasherder_settings,
)
from reconcile.typed_queries.tekton_pipeline_providers import (
    get_tekton_pipeline_providers,
)
from reconcile.utils.defer import defer
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.oc_map import (
    OCLogMsg,
    OCMap,
    init_oc_map_from_namespaces,
)
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.parse_dhms_duration import dhms_to_seconds
from reconcile.utils.saasherder import (
    Providers,
    SaasHerder,
    TriggerSpecUnion,
)
from reconcile.utils.saasherder.interfaces import SaasPipelinesProviderTekton
from reconcile.utils.saasherder.models import TriggerTypes
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.sharding import is_in_shard
from reconcile.utils.state import init_state

_trigger_lock = Lock()


class TektonTimeoutBadValueError(Exception):
    pass


@defer
def run(
    dry_run: bool,
    trigger_type: TriggerTypes,
    integration: str,
    integration_version: str,
    thread_pool_size: int,
    internal: bool,
    use_jump_host: bool,
    include_trigger_trace: bool,
    defer: Callable | None = None,
) -> bool:
    """Run trigger integration

    Args:
        dry_run (bool): Is this a dry run
        trigger_type (str): Indicates which method to call to get diff
                            and update state
        integration (string): Name of calling integration
        integration_version (string): Version of calling integration
        thread_pool_size (int): Thread pool size to use
        internal (bool): Should run for internal/extrenal/all clusters
        use_jump_host (bool): Should use jump host to reach clusters
        include_trigger_trace (bool): Should include traces of the triggering integration and reason

    Returns:
        bool: True if there was an error, False otherwise
    """
    saasherder, oc_map = setup(
        thread_pool_size=thread_pool_size,
        internal=internal,
        use_jump_host=use_jump_host,
        integration=integration,
        integration_version=integration_version,
        include_trigger_trace=include_trigger_trace,
    )
    if defer:  # defer is set by method decorator. this makes just mypy happy
        defer(saasherder.cleanup)
        defer(oc_map.cleanup)

    trigger_specs, diff_err = saasherder.get_diff(trigger_type, dry_run)
    # This will be populated by 'trigger' in the below loop and
    # we need it to be consistent across all iterations
    already_triggered: set[str] = set()

    errors = threaded.run(
        trigger,
        trigger_specs,
        thread_pool_size,
        dry_run=dry_run,
        saasherder=saasherder,
        oc_map=oc_map,
        already_triggered=already_triggered,
        integration=integration,
        integration_version=integration_version,
    )
    errors.append(diff_err)

    return saasherder.has_error_registered or any(errors)


def setup(
    thread_pool_size: int,
    internal: bool,
    use_jump_host: bool,
    integration: str,
    integration_version: str,
    include_trigger_trace: bool,
) -> tuple[SaasHerder, OCMap]:
    """Setup required resources for triggering integrations

    Args:
        thread_pool_size (int): Thread pool size to use
        internal (bool): Should run for internal/extrenal/all clusters
        use_jump_host (bool): Should use jump host to reach clusters
        integration (string): Name of calling integration
        integration_version (string): Version of calling integration
        include_trigger_trace (bool): Should include traces of the triggering integration and reason

    Returns:
        saasherder (SaasHerder): a SaasHerder instance
        oc_map (OC_Map): a dictionary of OC clients per cluster
    """
    vault_settings = get_app_interface_vault_settings()
    saasherder_settings = get_saasherder_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    saas_files = get_saas_files()
    if not saas_files:
        raise RuntimeError("no saas files found")
    saas_files = [sf for sf in saas_files if is_in_shard(sf.name)]

    # Remove saas-file targets that are disabled
    for saas_file in saas_files[:]:
        for rt in saas_file.resource_templates[:]:
            for target in rt.targets[:]:
                if target.disable:
                    rt.targets.remove(target)

    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    gl = GitLabApi(instance, settings=settings)
    jenkins_map = jenkins_base.get_jenkins_map()
    tkn_provider_namespaces = [pp.namespace for pp in get_tekton_pipeline_providers()]

    oc_map = init_oc_map_from_namespaces(
        namespaces=tkn_provider_namespaces,
        integration=integration,
        secret_reader=secret_reader,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
    )

    saasherder = SaasHerder(
        saas_files,
        thread_pool_size=thread_pool_size,
        integration=integration,
        integration_version=integration_version,
        secret_reader=secret_reader,
        hash_length=saasherder_settings.hash_length,
        repo_url=saasherder_settings.repo_url,
        gitlab=gl,
        jenkins_map=jenkins_map,
        state=init_state(integration=integration, secret_reader=secret_reader),
        include_trigger_trace=include_trigger_trace,
    )

    return saasherder, oc_map


def trigger(
    spec: TriggerSpecUnion,
    dry_run: bool,
    saasherder: SaasHerder,
    oc_map: OCMap,
    already_triggered: set[str],
    integration: str,
    integration_version: str,
) -> bool:
    """Trigger a deployment according to the specified pipelines provider

    Args:
        spec (dict): A trigger spec as created by saasherder
        dry_run (bool): Is this a dry run
        saasherder (SaasHerder): a SaasHerder instance
        oc_map (OC_Map): a dictionary of OC clients per cluster
        already_triggered (set): A set of already triggered deployments.
                                    It will get populated by this function.
        integration (string): Name of calling integration
        integration_version (string): Version of calling integration

    Returns:
        bool: True if there was an error, False otherwise
    """
    saas_file_name = spec.saas_file_name
    error = False
    if spec.pipelines_provider.provider == Providers.TEKTON.value:
        error = _trigger_tekton(
            spec,
            dry_run,
            saasherder,
            oc_map,
            already_triggered,
            integration,
            integration_version,
        )
    else:
        error = True
        logging.error(
            f"[{saas_file_name}] unsupported provider: "
            + f"{spec.pipelines_provider.provider}"
        )

    return error


def _trigger_tekton(
    spec: TriggerSpecUnion,
    dry_run: bool,
    saasherder: SaasHerder,
    oc_map: OCMap,
    already_triggered: set[str],
    integration: str,
    integration_version: str,
) -> bool:
    if not isinstance(spec.pipelines_provider, SaasPipelinesProviderTekton):
        # This should never happen. It's here to make mypy happy
        raise TypeError(
            f"spec.pipelines_provider should be of type "
            f"SaasPipelinesProviderTekton, got {type(spec.pipelines_provider)}"
        )
    pipeline_template_name = (
        spec.pipelines_provider.pipeline_templates.openshift_saas_deploy.name
        if spec.pipelines_provider.pipeline_templates
        else spec.pipelines_provider.defaults.pipeline_templates.openshift_saas_deploy.name
    )
    tkn_pipeline_name = build_one_per_saas_file_tkn_pipeline_name(
        pipeline_template_name, spec.saas_file_name
    )
    tkn_namespace_name = spec.pipelines_provider.namespace.name
    tkn_cluster_name = spec.pipelines_provider.namespace.cluster.name
    tkn_cluster_console_url = spec.pipelines_provider.namespace.cluster.console_url

    # if pipeline does not exist it means that either it hasn't been
    # statically created from app-interface or it hasn't been dynamically
    # created from openshift-tekton-resources. In either case, we return here
    # to avoid triggering anything or updating the state. We don't return an
    # error as this is an expected condition when adding a new saas file
    if not _pipeline_exists(
        tkn_pipeline_name, tkn_cluster_name, tkn_namespace_name, oc_map
    ):
        logging.warning(
            f"Pipeline {tkn_pipeline_name} does not exist in "
            f"{tkn_cluster_name}/{tkn_namespace_name}."
        )
        return False

    tkn_trigger_resource, tkn_name = _construct_tekton_trigger_resource(
        spec.saas_file_name,
        spec.env_name,
        tkn_pipeline_name,
        spec.timeout,
        tkn_cluster_console_url,
        tkn_namespace_name,
        integration,
        integration_version,
        saasherder.include_trigger_trace,
        spec.reason,
    )

    error = False
    to_trigger = _register_trigger(tkn_name, already_triggered)
    if to_trigger:
        try:
            osb.create(
                dry_run=dry_run,
                oc_map=oc_map,
                cluster=tkn_cluster_name,
                namespace=tkn_namespace_name,
                resource_type=tkn_trigger_resource.kind,
                resource=tkn_trigger_resource,
            )
        except Exception as e:
            error = True
            logging.error(
                f"could not trigger pipeline {tkn_name} "
                + f"in {tkn_cluster_name}/{tkn_namespace_name}. "
                + f"details: {e!s}"
            )

    if not error and not dry_run:
        saasherder.update_state(spec)

    return error


def _pipeline_exists(
    name: str, tkn_cluster_name: str, tkn_namespace_name: str, oc_map: OCMap
) -> bool:
    oc = oc_map.get(tkn_cluster_name)
    if isinstance(oc, OCLogMsg):
        logging.error(oc.message)
        raise RuntimeError(f"No OC client for {tkn_cluster_name}: {oc.message}")
    return bool(
        oc.get(
            namespace=tkn_namespace_name,
            kind="Pipeline",
            name=name,
            allow_not_found=True,
        )
    )


def _construct_tekton_trigger_resource(
    saas_file_name: str,
    env_name: str,
    tkn_pipeline_name: str,
    timeout: str | None,
    tkn_cluster_console_url: str,
    tkn_namespace_name: str,
    integration: str,
    integration_version: str,
    include_trigger_trace: bool,
    reason: str | None,
) -> tuple[OR, str]:
    """Construct a resource (PipelineRun) to trigger a deployment via Tekton.

    Args:
        saas_file_name (string): SaaS file name
        env_name (string): Environment name
        tkn_cluster_console_url (string): Cluster console URL of the cluster
                                          where the pipeline runs
        tkn_namespace_name (string): namespace where the pipeline runs
        timeout (str): Timeout in minutes before the PipelineRun fails (must be > 60)
        integration (string): Name of calling integration
        integration_version (string): Version of calling integration
        include_trigger_trace (bool): Should include traces of the triggering integration and reason
        reason (string): The reason this trigger was created

    Returns:
        OpenshiftResource: OpenShift resource to be applied
    """
    tkn_name, tkn_long_name = SaasHerder.build_saas_file_env_combo(
        saas_file_name, env_name
    )
    name = tkn_name.lower()

    parameters = [
        {"name": "saas_file_name", "value": saas_file_name},
        {"name": "env_name", "value": env_name},
        {"name": "tkn_cluster_console_url", "value": tkn_cluster_console_url},
        {"name": "tkn_namespace_name", "value": tkn_namespace_name},
    ]
    if include_trigger_trace:
        if not reason:
            raise RuntimeError(
                "reason must be provided if include_trigger_trace is True"
            )

        parameters.extend([
            {"name": "trigger_integration", "value": integration},
            {"name": "trigger_reason", "value": reason},
        ])
    body: dict[str, Any] = {
        "apiVersion": "tekton.dev/v1",
        "kind": "PipelineRun",
        "metadata": {"generateName": f"{name}-"},
        "spec": {
            "pipelineRef": {"name": tkn_pipeline_name},
            "params": parameters,
        },
    }

    if timeout:
        seconds = dhms_to_seconds(timeout)
        if seconds < 3600:  # 1 hour
            raise TektonTimeoutBadValueError(
                f"timeout {timeout} is smaller than 60 minutes"
            )

        body["spec"]["timeouts"] = {
            "pipeline": "0",
            "tasks": timeout,
        }

    return (
        OR(body, integration, integration_version, error_details=name),
        tkn_long_name.lower(),
    )


def _register_trigger(name: str, already_triggered: set[str]) -> bool:
    """checks if a trigger should occur and registers as if it did

    Args:
        name (str): unique trigger name to check and
        already_triggered (set): A set of already triggered deployments.
                                 It will get populated by this function.

    Returns:
        bool: to trigger or not to trigger
    """
    to_trigger = False
    with _trigger_lock:
        if name not in already_triggered:
            to_trigger = True
            already_triggered.add(name)

    return to_trigger

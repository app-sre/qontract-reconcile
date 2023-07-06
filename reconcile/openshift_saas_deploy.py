import logging
import sys
from collections.abc import Callable
from typing import Optional

import reconcile.openshift_base as ob
from reconcile import (
    jenkins_base,
    queries,
)
from reconcile.gql_definitions.common.saas_files import PipelinesProviderTektonV1
from reconcile.openshift_tekton_resources import (
    build_one_per_saas_file_tkn_pipeline_name,
)
from reconcile.slack_base import slackapi_from_slack_workspace
from reconcile.status import ExitCodes
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.saas_files import (
    SaasFile,
    get_saas_files,
    get_saasherder_settings,
)
from reconcile.utils.defer import defer
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.saasherder import SaasHerder
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.slack_api import SlackApi
from reconcile.utils.state import init_state

QONTRACT_INTEGRATION = "openshift-saas-deploy"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def compose_console_url(saas_file: SaasFile, env_name: str) -> str:
    if not isinstance(saas_file.pipelines_provider, PipelinesProviderTektonV1):
        raise ValueError(
            f"Unsupported pipelines_provider: {saas_file.pipelines_provider}"
        )
    pipeline_template_name = (
        saas_file.pipelines_provider.defaults.pipeline_templates.openshift_saas_deploy.name
        if not saas_file.pipelines_provider.pipeline_templates
        else saas_file.pipelines_provider.pipeline_templates.openshift_saas_deploy.name
    )
    pipeline_name = build_one_per_saas_file_tkn_pipeline_name(
        pipeline_template_name, saas_file.name
    )
    tkn_name, _ = SaasHerder.build_saas_file_env_combo(saas_file.name, env_name)

    return (
        f"{saas_file.pipelines_provider.namespace.cluster.console_url}/k8s/ns/"
        f"{saas_file.pipelines_provider.namespace.name}/tekton.dev~v1beta1~Pipeline/"
        f"{pipeline_name}/Runs?name={tkn_name}"
    )


def slack_notify(
    saas_file_name: str,
    env_name: str,
    slack: SlackApi,
    ri: ResourceInventory,
    console_url: str,
    in_progress: bool,
    trigger_reason: Optional[str] = None,
) -> None:
    success = not ri.has_error_registered()
    if in_progress:
        icon = ":yellow_jenkins_circle:"
        description = "In Progress"
    elif success:
        icon = ":green_jenkins_circle:"
        description = "Success"
    else:
        icon = ":red_jenkins_circle:"
        description = "Failure"
    message = (
        f"{icon} SaaS file *{saas_file_name}* "
        + f"deployment to environment *{env_name}*: "
        + f"{description} (<{console_url}|Open>)"
    )
    if trigger_reason:
        message += f". Reason: {trigger_reason}"
    slack.chat_post_message(message)


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    io_dir: str = "throughput/",
    use_jump_host: bool = True,
    saas_file_name: Optional[str] = None,
    env_name: Optional[str] = None,
    gitlab_project_id: Optional[str] = None,
    trigger_reason: Optional[str] = None,
    defer: Optional[Callable] = None,
) -> None:
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)

    all_saas_files = get_saas_files()
    saas_files = get_saas_files(saas_file_name, env_name)
    if not saas_files:
        logging.error("no saas files found")
        raise RuntimeError("no saas files found")

    # notify different outputs (publish results, slack notifications)
    # we only do this if:
    # - this is not a dry run
    # - there is a single saas file deployed
    notify = not dry_run and len(saas_files) == 1
    slack = None
    if notify:
        saas_file = saas_files[0]
        if saas_file.slack:
            if not saas_file_name or not env_name:
                raise RuntimeError(
                    "saas_file_name and env_name must be provided "
                    + "when using slack notifications"
                )
            slack = slackapi_from_slack_workspace(
                saas_file.slack.dict(by_alias=True),
                secret_reader,
                QONTRACT_INTEGRATION,
                init_usergroups=False,
            )
            ri = ResourceInventory()
            console_url = compose_console_url(saas_file, env_name)
            if (
                defer
            ):  # defer is provided by the method decorator. this makes just mypy happy
                # deployment result notification
                defer(
                    lambda: slack_notify(
                        saas_file_name,
                        env_name,
                        slack,
                        ri,
                        console_url,
                        in_progress=False,
                        trigger_reason=trigger_reason,
                    )
                )
            # deployment start notification
            if saas_file.slack.notifications and saas_file.slack.notifications.start:
                slack_notify(
                    saas_file_name,
                    env_name,
                    slack,
                    ri,
                    console_url,
                    in_progress=True,
                    trigger_reason=trigger_reason,
                )

    jenkins_map = jenkins_base.get_jenkins_map()
    saasherder_settings = get_saasherder_settings()
    settings = queries.get_app_interface_settings()
    try:
        instance = queries.get_gitlab_instance()
        gl = GitLabApi(instance, settings=settings)
    except Exception:
        # allow execution without access to gitlab
        # as long as there are no access attempts.
        gl = None

    saasherder = SaasHerder(
        saas_files=saas_files,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        secret_reader=secret_reader,
        hash_length=saasherder_settings.hash_length,
        repo_url=saasherder_settings.repo_url,
        gitlab=gl,
        jenkins_map=jenkins_map,
        state=init_state(integration=QONTRACT_INTEGRATION, secret_reader=secret_reader),
    )
    if defer:
        defer(saasherder.cleanup)
    if len(saasherder.namespaces) == 0:
        logging.warning("no targets found")
        sys.exit(ExitCodes.SUCCESS)

    ri, oc_map = ob.fetch_current_state(
        namespaces=[ns.dict(by_alias=True) for ns in saasherder.namespaces],
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        init_api_resources=True,
        cluster_admin=bool(saasherder.cluster_admin),
        use_jump_host=use_jump_host,
    )
    if defer:  # defer is provided by the method decorator. this makes just mypy happy
        defer(oc_map.cleanup)
    saasherder.populate_desired_state(ri)

    # validate that this deployment is valid
    # based on promotion information in targets
    if not saasherder.validate_promotions():
        logging.error("invalid promotions")
        ri.register_error()
        sys.exit(ExitCodes.ERROR)

    # validate that the deployment will succeed
    # to the best of our ability to predict
    ob.validate_planned_data(ri, oc_map)

    # if saas_file_name is defined, the integration
    # is being called from multiple running instances
    actions = ob.realize_data(
        dry_run,
        oc_map,
        ri,
        thread_pool_size,
        caller=saas_file_name,
        all_callers=[sf.name for sf in all_saas_files if not sf.deprecated],
        wait_for_namespace=True,
        no_dry_run_skip_compare=(not saasherder.compare),
        take_over=saasherder.take_over,
    )

    if not dry_run:
        if saasherder.publish_job_logs:
            try:
                ob.follow_logs(oc_map, actions, io_dir)
            except Exception as e:
                logging.error(str(e))
                ri.register_error()
        try:
            ob.validate_realized_data(actions, oc_map)
        except Exception as e:
            logging.error(str(e))
            ri.register_error()

    # publish results of this deployment
    # based on promotion information in targets
    success = not ri.has_error_registered()
    # only publish promotions for deployment jobs (a single saas file)
    if notify:
        # Auto-promotions are now created by saas-auto-promotions-manager integration
        # However, we still need saas-herder to publish the state to S3, because
        # saas-auto-promotions-manager needs that information
        saasherder.publish_promotions(success, all_saas_files)

    if not success:
        sys.exit(ExitCodes.ERROR)

    # send human readable notifications to slack
    # we only do this if:
    # - this is not a dry run
    # - there is a single saas file deployed
    # - output is 'events'
    # - no errors were registered
    if (
        notify
        and slack
        and actions
        and saas_file.slack
        and saas_file.slack.output == "events"
    ):
        for action in actions:
            message = (
                f"[{action['cluster']}] "
                + f"{action['kind']} {action['name']} {action['action']}"
            )
            slack.chat_post_message(message)

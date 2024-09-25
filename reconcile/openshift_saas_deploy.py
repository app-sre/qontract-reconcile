import json
import logging
import os
import sys
from collections.abc import Callable

import reconcile.openshift_base as ob
from reconcile import (
    jenkins_base,
    openshift_saas_deploy_trigger_images,
    openshift_saas_deploy_trigger_upstream_jobs,
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
    SaasFileList,
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
from reconcile.utils.unleash import get_feature_toggle_state

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
        f"{saas_file.pipelines_provider.namespace.name}/tekton.dev~v1~Pipeline/"
        f"{pipeline_name}/Runs?name={tkn_name}"
    )


def slack_notify(
    saas_file_name: str,
    env_name: str,
    slack: SlackApi,
    ri: ResourceInventory,
    console_url: str,
    in_progress: bool,
    trigger_integration: str | None = None,
    trigger_reason: str | None = None,
    skip_successful_notifications: bool | None = False,
) -> None:
    success = not ri.has_error_registered()
    # if the deployment doesn't want any notifications for successful
    # deployments, then we should grant the wish. However, there's a user
    # expereince concern where the deployment owners will receive a "in
    # progress" notice but no subsequent notice. We handle this case by
    # including an "fyi" message for in progress deployments down below.
    if success and skip_successful_notifications and not in_progress:
        logging.info(
            f"Skipping Slack notification for {saas_file_name} to {env_name} because deploy was successful."
        )
        return
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
    if trigger_integration:
        message += f" triggered by _{trigger_integration}_"
    if in_progress and skip_successful_notifications:
        message += ". There will not be a notice for success."
    slack.chat_post_message(message)


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    io_dir: str = "throughput/",
    use_jump_host: bool = True,
    saas_file_name: str | None = None,
    env_name: str | None = None,
    trigger_integration: str | None = None,
    trigger_reason: str | None = None,
    saas_file_list: SaasFileList | None = None,
    defer: Callable | None = None,
) -> None:
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)

    if not saas_file_list:
        saas_file_list = SaasFileList()
    all_saas_files = saas_file_list.saas_files
    saas_files = saas_file_list.where(name=saas_file_name, env_name=env_name)

    if not saas_files:
        logging.error("no saas files found")
        raise RuntimeError("no saas files found")

    # notify different outputs (publish results, slack notifications)
    # we only do this if:
    # - this is not a dry run
    # - there is a single saas file deployed
    notify = not dry_run and len(saas_files) == 1
    skip_successful_deploy_notifications = (
        saas_files[0].skip_successful_deploy_notifications if saas_files else False
    )
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
                        trigger_integration=trigger_integration,
                        trigger_reason=trigger_reason,
                        skip_successful_notifications=skip_successful_deploy_notifications,
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
                    trigger_integration=trigger_integration,
                    trigger_reason=trigger_reason,
                    skip_successful_notifications=skip_successful_deploy_notifications,
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
        all_saas_files=saas_file_list.saas_files,
    )
    if defer:
        defer(saasherder.cleanup)
    if len(saasherder.namespaces) == 0:
        logging.warning("no targets found")
        sys.exit(ExitCodes.SUCCESS)

    # check enable_init_projects flag status
    enable_init_projects = get_feature_toggle_state(
        "enable_init_projects",
        default=False,
    )
    ri, oc_map = ob.fetch_current_state(
        namespaces=[ns.dict(by_alias=True) for ns in saasherder.namespaces],
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        init_api_resources=True,
        cluster_admin=bool(saasherder.cluster_admin),
        use_jump_host=use_jump_host,
        init_projects=enable_init_projects,
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
    if saasherder.validate_planned_data:
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

    # get upstream repo info for sast scan
    # get image info for clamav scan
    # we only do this if:
    # - this is not a dry run
    # - there is a single saas file deployed
    # - saas-deploy triggered by upstream job or image build
    allowed_integration = [
        openshift_saas_deploy_trigger_upstream_jobs.QONTRACT_INTEGRATION,
        openshift_saas_deploy_trigger_images.QONTRACT_INTEGRATION,
    ]
    scan = (
        not dry_run
        and len(saas_files) == 1
        and trigger_integration
        and trigger_integration in allowed_integration
        and trigger_reason
    )
    if scan:
        saas_file = saas_files[0]
        owners = saas_file.app.service_owners or []
        emails = " ".join([o.email for o in owners])
        file, url = saasherder.get_archive_info(saas_file, trigger_reason)
        sast_file = os.path.join(io_dir, "sast")
        with open(sast_file, "w", encoding="locale") as f:
            f.write(file + "\n")
            f.write(url + "\n")
            f.write(emails + "\n")
        images = " ".join(saasherder.images)
        app_name = saas_file.app.name
        clamav_file = os.path.join(io_dir, "clamav")
        with open(clamav_file, "w", encoding="locale") as f:
            f.write(images + "\n")
            f.write(app_name + "\n")
        image_auth = saasherder._initiate_image_auth(saas_file)
        if image_auth.auth_server:
            json_file = os.path.join(io_dir, "dockerconfigjson")
            with open(json_file, "w", encoding="locale") as f:
                f.write(json.dumps(image_auth.getDockerConfigJson(), indent=2))

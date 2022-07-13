import logging
import sys


import reconcile.jenkins_plugins as jenkins_base
import reconcile.openshift_base as ob
from reconcile import queries

from reconcile import mr_client_gateway
from reconcile.slack_base import slackapi_from_slack_workspace
from reconcile.status import ExitCodes
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.defer import defer
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.saasherder import SaasHerder
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.openshift_tekton_resources import build_one_per_saas_file_tkn_object_name


QONTRACT_INTEGRATION = "openshift-saas-deploy"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def compose_console_url(saas_file, saas_file_name, env_name):
    pp = saas_file["pipelinesProvider"]
    pp_ns = pp["namespace"]
    pp_ns_name = pp_ns["name"]
    pp_cluster = pp_ns["cluster"]
    pp_cluster_console_url = pp_cluster["consoleUrl"]

    pipeline_template_name = pp["defaults"]["pipelineTemplates"]["openshiftSaasDeploy"][
        "name"
    ]

    if pp["pipelineTemplates"]:
        pipeline_template_name = pp["pipelineTemplates"]["openshiftSaasDeploy"]["name"]

    pipeline_name = build_one_per_saas_file_tkn_object_name(
        pipeline_template_name, saas_file_name
    )

    return (
        f"{pp_cluster_console_url}/k8s/ns/{pp_ns_name}/"
        + "tekton.dev~v1beta1~Pipeline/"
        + f"{pipeline_name}/Runs?name={saas_file_name}-{env_name}"
    )


def slack_notify(saas_file_name, env_name, slack, ri, console_url, in_progress):
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
    slack.chat_post_message(message)


@defer
def run(
    dry_run,
    thread_pool_size=10,
    io_dir="throughput/",
    use_jump_host=True,
    saas_file_name=None,
    env_name=None,
    gitlab_project_id=None,
    defer=None,
):
    all_saas_files = queries.get_saas_files()
    saas_files = queries.get_saas_files(saas_file_name, env_name)
    if not saas_files:
        logging.error("no saas files found")
        sys.exit(ExitCodes.ERROR)

    # notify different outputs (publish results, slack notifications)
    # we only do this if:
    # - this is not a dry run
    # - there is a single saas file deployed
    notify = not dry_run and len(saas_files) == 1
    if notify:
        saas_file = saas_files[0]
        slack_info = saas_file.get("slack")
        if slack_info:
            slack = slackapi_from_slack_workspace(
                slack_info,
                SecretReader(queries.get_secret_reader_settings()),
                QONTRACT_INTEGRATION,
                init_usergroups=False,
            )
            ri = ResourceInventory()
            console_url = compose_console_url(saas_file, saas_file_name, env_name)
            # deployment result notification
            defer(
                lambda: slack_notify(
                    saas_file_name,
                    env_name,
                    slack,
                    ri,
                    console_url,
                    in_progress=False,
                )
            )
            # deployment start notification
            slack_notifications = slack_info.get("notifications")
            if slack_notifications and slack_notifications.get("start"):
                slack_notify(
                    saas_file_name,
                    env_name,
                    slack,
                    ri,
                    console_url,
                    in_progress=True,
                )
        else:
            slack = None

    instance = queries.get_gitlab_instance()
    # instance exists in v1 saas files only
    desired_jenkins_instances = [
        s["instance"]["name"] for s in saas_files if s.get("instance")
    ]
    jenkins_map = jenkins_base.get_jenkins_map(
        desired_instances=desired_jenkins_instances
    )
    settings = queries.get_app_interface_settings()
    accounts = queries.get_aws_accounts()
    try:
        gl = GitLabApi(instance, settings=settings)
    except Exception:
        # allow execution without access to gitlab
        # as long as there are no access attempts.
        gl = None

    saasherder = SaasHerder(
        saas_files,
        thread_pool_size=thread_pool_size,
        gitlab=gl,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        settings=settings,
        jenkins_map=jenkins_map,
        accounts=accounts,
    )
    if len(saasherder.namespaces) == 0:
        logging.warning("no targets found")
        sys.exit(ExitCodes.SUCCESS)

    ri, oc_map = ob.fetch_current_state(
        namespaces=saasherder.namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        init_api_resources=True,
        cluster_admin=saasherder.cluster_admin,
        use_jump_host=use_jump_host,
    )
    defer(oc_map.cleanup)
    saasherder.populate_desired_state(ri)

    # validate that this deployment is valid
    # based on promotion information in targets
    if not saasherder.validate_promotions():
        logging.error("invalid promotions")
        ri.register_error()
        sys.exit(ExitCodes.ERROR)

    # if saas_file_name is defined, the integration
    # is being called from multiple running instances
    actions = ob.realize_data(
        dry_run,
        oc_map,
        ri,
        thread_pool_size,
        caller=saas_file_name,
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
            ob.validate_data(oc_map, actions)
        except Exception as e:
            logging.error(str(e))
            ri.register_error()

    # publish results of this deployment
    # based on promotion information in targets
    success = not ri.has_error_registered()
    # only publish promotions for deployment jobs (a single saas file)
    if notify:
        # Auto-promote next stages only if there are changes in the
        # promoting stage. This prevents trigger promotions on job re-runs
        auto_promote = len(actions) > 0
        mr_cli = mr_client_gateway.init(gitlab_project_id=gitlab_project_id)
        saasherder.publish_promotions(success, all_saas_files, mr_cli, auto_promote)

    if not success:
        sys.exit(ExitCodes.ERROR)

    # send human readable notifications to slack
    # we only do this if:
    # - this is not a dry run
    # - there is a single saas file deployed
    # - output is 'events'
    # - no errors were registered
    if notify and slack and actions and slack_info.get("output") == "events":
        for action in actions:
            message = (
                f"[{action['cluster']}] "
                + f"{action['kind']} {action['name']} {action['action']}"
            )
            slack.chat_post_message(message)

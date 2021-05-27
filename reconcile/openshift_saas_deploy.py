import logging
import sys


import reconcile.jenkins_plugins as jenkins_base
import reconcile.openshift_base as ob
import reconcile.queries as queries

from reconcile import mr_client_gateway
from reconcile.slack_base import init_slack
from reconcile.status import ExitCodes
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.defer import defer
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.saasherder import SaasHerder


QONTRACT_INTEGRATION = 'openshift-saas-deploy'
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


@defer
def run(dry_run, thread_pool_size=10, io_dir='throughput/',
        saas_file_name=None, env_name=None,
        gitlab_project_id=None, defer=None):
    all_saas_files = queries.get_saas_files(v1=True, v2=True)
    saas_files = queries.get_saas_files(saas_file_name, env_name,
                                        v1=True, v2=True)
    if not saas_files:
        logging.error('no saas files found')
        sys.exit(ExitCodes.ERROR)

    # notify different outputs (publish results, slack notifications)
    # we only do this if:
    # - this is not a dry run
    # - there is a single saas file deployed
    notify = not dry_run and len(saas_files) == 1
    if notify:
        slack_info = saas_files[0].get('slack')
        if slack_info:
            slack = init_slack(slack_info, QONTRACT_INTEGRATION,
                               init_usergroups=False)
        else:
            slack = None

    instance = queries.get_gitlab_instance()
    # instance exists in v1 saas files only
    desired_jenkins_instances = [s['instance']['name'] for s in saas_files
                                 if s.get('instance')]
    jenkins_map = jenkins_base.get_jenkins_map(
        desired_instances=desired_jenkins_instances)
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
        accounts=accounts)
    if len(saasherder.namespaces) == 0:
        logging.warning('no targets found')
        sys.exit(ExitCodes.SUCCESS)

    ri, oc_map = ob.fetch_current_state(
        namespaces=saasherder.namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        init_api_resources=True)
    defer(lambda: oc_map.cleanup())
    saasherder.populate_desired_state(ri)

    # validate that this deployment is valid
    # based on promotion information in targets
    if not saasherder.validate_promotions():
        logging.error('invalid promotions')
        sys.exit(ExitCodes.ERROR)

    # if saas_file_name is defined, the integration
    # is being called from multiple running instances
    actions = ob.realize_data(
        dry_run, oc_map, ri,
        caller=saas_file_name,
        wait_for_namespace=True,
        no_dry_run_skip_compare=(not saasherder.compare),
        take_over=saasherder.take_over
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
        mr_cli = mr_client_gateway.init(gitlab_project_id=gitlab_project_id)
        saasherder.publish_promotions(success, all_saas_files, mr_cli)

    if not success:
        sys.exit(ExitCodes.ERROR)

    # send human readable notifications to slack
    # we only do this if:
    # - this is not a dry run
    # - there is a single saas file deployed
    # - output is 'events'
    # - no errors were registered
    if notify and slack and actions and slack_info.get('output') == 'events':
        for action in actions:
            message = \
                f"[{action['cluster']}] " + \
                f"{action['kind']} {action['name']} {action['action']}"
            slack.chat_post_message(message)

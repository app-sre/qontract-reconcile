import json
import logging
import os
import sys
import re

import click
import sentry_sdk

import reconcile.utils.config as config
import reconcile.utils.gql as gql
import reconcile.github_org
import reconcile.github_owners
import reconcile.github_users
import reconcile.github_scanner
import reconcile.github_validator
import reconcile.openshift_clusterrolebindings
import reconcile.openshift_rolebindings
import reconcile.openshift_groups
import reconcile.openshift_limitranges
import reconcile.openshift_resourcequotas
import reconcile.openshift_users
import reconcile.openshift_resources
import reconcile.openshift_vault_secrets
import reconcile.openshift_routes
import reconcile.openshift_namespaces
import reconcile.openshift_network_policies
import reconcile.openshift_serviceaccount_tokens
import reconcile.openshift_saas_deploy
import reconcile.openshift_saas_deploy_wrapper
import reconcile.openshift_saas_deploy_trigger_moving_commits
import reconcile.openshift_saas_deploy_trigger_upstream_jobs
import reconcile.openshift_saas_deploy_trigger_configs
import reconcile.openshift_saas_deploy_trigger_cleaner
import reconcile.saas_file_owners
import reconcile.gitlab_ci_skipper
import reconcile.gitlab_labeler
import reconcile.saas_file_validator
import reconcile.quay_membership
import reconcile.gcr_mirror
import reconcile.quay_mirror
import reconcile.quay_mirror_org
import reconcile.quay_repos
import reconcile.quay_permissions
import reconcile.ldap_users
import reconcile.terraform_resources
import reconcile.terraform_resources_wrapper
import reconcile.terraform_users
import reconcile.terraform_vpc_peerings
import reconcile.terraform_tgw_attachments
import reconcile.github_repo_invites
import reconcile.github_repo_permissions_validator
import reconcile.jenkins_roles
import reconcile.jenkins_plugins
import reconcile.jenkins_job_builder
import reconcile.jenkins_job_cleaner
import reconcile.jenkins_webhooks
import reconcile.jenkins_webhooks_cleaner
import reconcile.jira_watcher
import reconcile.unleash_watcher
import reconcile.openshift_upgrade_watcher
import reconcile.slack_usergroups
import reconcile.slack_cluster_usergroups
import reconcile.gitlab_integrations
import reconcile.gitlab_permissions
import reconcile.gitlab_housekeeping
import reconcile.gitlab_fork_compliance
import reconcile.gitlab_members
import reconcile.gitlab_owners
import reconcile.gitlab_mr_sqs_consumer
import reconcile.gitlab_projects
import reconcile.aws_garbage_collector
import reconcile.aws_iam_keys
import reconcile.aws_ecr_image_pull_secrets
import reconcile.aws_support_cases_sos
import reconcile.ocm_groups
import reconcile.ocm_clusters
import reconcile.ocm_external_configuration_labels
import reconcile.ocm_machine_pools
import reconcile.ocm_upgrade_scheduler
import reconcile.ocm_addons
import reconcile.ocm_aws_infrastructure_access
import reconcile.ocm_github_idp
import reconcile.ocm_additional_routers
import reconcile.email_sender
import reconcile.sentry_helper
import reconcile.requests_sender
import reconcile.service_dependencies
import reconcile.sentry_config
import reconcile.sql_query
import reconcile.user_validator
import reconcile.integrations_validator
import reconcile.dashdotdb_cso
import reconcile.ocp_release_mirror
import reconcile.ecr_mirror
import reconcile.kafka_clusters
import reconcile.terraform_aws_route53
import reconcile.prometheus_rules_tester
import reconcile.dashdotdb_dvo
import reconcile.sendgrid_teammates
import reconcile.osd_mirrors_data_updater
import reconcile.dashdotdb_slo
import reconcile.jenkins_job_builds_cleaner
import reconcile.cluster_deployment_mapper

from reconcile.status import ExitCodes
from reconcile.status import RunningState

from reconcile.utils.gql import (GqlApiErrorForbiddenSchema,
                                 GqlApiIntegrationNotFound)
from reconcile.utils.aggregated_list import RunnerException
from reconcile.utils.binary import binary, binary_version
from reconcile.utils.environ import environ
from reconcile.utils.unleash import get_feature_toggle_state


TERRAFORM_VERSION = '0.13.7'
TERRAFORM_VERSION_REGEX = r'^Terraform\sv([\d]+\.[\d]+\.[\d]+)$'

OC_VERSION = '4.6.1'
OC_VERSION_REGEX = r'^Client\sVersion:\s([\d]+\.[\d]+\.[\d]+)$'

LOG_FMT = '[%(asctime)s] [%(levelname)s] ' \
    '[%(filename)s:%(funcName)s:%(lineno)d] - %(message)s'
LOG_DATEFMT = '%Y-%m-%d %H:%M:%S'


def before_breadcrumb(crumb, hint):
    # https://docs.sentry.io/platforms/python/configuration/filtering/
    # Configure breadcrumb to filter error mesage
    if 'category' in crumb and crumb['category'] == 'subprocess':
        # remove cluster token
        crumb['message'] = re.sub(
            r'--token \S*\b', '--token ***', crumb['message']
        )
    return crumb


# Enable Sentry
if os.getenv('SENTRY_DSN'):
    sentry_sdk.init(
        os.environ['SENTRY_DSN'],
        before_breadcrumb=before_breadcrumb
    )


def config_file(function):
    help_msg = 'Path to configuration file in toml format.'
    function = click.option('--config', 'configfile',
                            required=True,
                            help=help_msg)(function)
    return function


def log_level(function):
    function = click.option('--log-level',
                            help='log-level of the command. Defaults to INFO.',
                            type=click.Choice([
                                'DEBUG',
                                'INFO',
                                'WARNING',
                                'ERROR',
                                'CRITICAL']))(function)
    return function


def dry_run(function):
    help_msg = ('If `true`, it will only print the planned actions '
                'that would be performed, without executing them.')

    function = click.option('--dry-run/--no-dry-run',
                            default=False,
                            help=help_msg)(function)
    return function


def validate_schemas(function):
    help_msg = 'Fail integration if it queries forbidden schemas'

    function = click.option('--validate-schemas/--no-validate-schemas',
                            default=True,
                            help=help_msg)(function)
    return function


def dump_schemas(function):
    help_msg = 'Dump schemas to a file'

    function = click.option('--dump-schemas', 'dump_schemas_file',
                            help=help_msg)(function)
    return function


def gql_sha_url(function):
    help_msg = ('If `false`, it will not use the sha_url endpoint '
                'of graphql (prevent stopping execution on data reload).')

    function = click.option('--gql-sha-url/--no-gql-sha-url',
                            default=True,
                            help=help_msg)(function)
    return function


def gql_url_print(function):
    help_msg = ('If `false`, it will not print the url endpoint of graphql.')

    function = click.option('--gql-url-print/--no-gql-url-print',
                            default=True,
                            help=help_msg)(function)
    return function


def threaded(**kwargs):
    def f(function):
        opt = '--thread-pool-size'
        msg = 'number of threads to run in parallel.'
        function = click.option(opt,
                                default=kwargs.get('default', 10),
                                help=msg)(function)
        return function
    return f


def take_over(**kwargs):
    def f(function):
        help_msg = 'manage resources exclusively (take over existing ones).'
        function = click.option('--take-over/--no-take-over',
                                help=help_msg,
                                default=True)(function)
        return function
    return f


def internal(**kwargs):
    def f(function):
        help_msg = 'manage resources in internal or external clusters only.'
        function = click.option('--internal/--external',
                                help=help_msg,
                                default=None)(function)
        return function
    return f


def use_jump_host(**kwargs):
    def f(function):
        help_msg = 'use jump host if defined.'
        function = click.option('--use-jump-host/--no-use-jump-host',
                                help=help_msg,
                                default=True)(function)
        return function
    return f


def print_only(function):
    function = click.option('--print-only/--no-print-only',
                            help='only print the config file.',
                            default=False)(function)

    return function


def config_name(function):
    function = click.option('--config-name',
                            help='jenkins config name to print out.'
                                 'must works with --print-only mode',
                            default=None)(function)

    return function


def job_name(function):
    function = click.option('--job-name',
                            help='jenkins job name to print out.',
                            default=None)(function)

    return function


def instance_name(function):
    function = click.option('--instance-name',
                            help='jenkins instance name to act on.',
                            default=None)(function)

    return function


def throughput(function):
    function = click.option('--io-dir',
                            help='directory of input/output files.',
                            default='throughput/')(function)

    return function


def vault_input_path(function):
    function = click.option('--vault-input-path',
                            help='path in Vault to find input resources.',
                            default='')(function)

    return function


def vault_output_path(function):
    function = click.option('--vault-output-path',
                            help='path in Vault to store output resources.',
                            default='')(function)

    return function


def vault_throughput_path(function):
    function = click.option('--vault-throughput-path',
                            help='path in Vault to find input resources '
                                 'and store output resources.',
                            default='')(function)

    return function


def cluster_name(function):
    function = click.option('--cluster-name',
                            help='cluster name to act on.',
                            default=None)(function)

    return function


def namespace_name(function):
    function = click.option('--namespace-name',
                            help='namespace name to act on.',
                            default=None)(function)

    return function


def account_name(function):
    function = click.option('--account-name',
                            help='aws account name to act on.',
                            default=None)(function)

    return function


def gitlab_project_id(function):
    function = click.option('--gitlab-project-id',
                            help='gitlab project id to submit PRs to. '
                                 'not required if mergeRequestGateway '
                                 'is not set to gitlab',
                            default=None)(function)

    return function


def enable_deletion(**kwargs):
    def f(function):
        opt = '--enable-deletion/--no-enable-deletion'
        msg = 'enable destroy/replace action.'
        function = click.option(opt,
                                default=kwargs.get('default', True),
                                help=msg)(function)
        return function
    return f


def send_mails(**kwargs):
    def f(function):
        opt = '--send-mails/--no-send-mails'
        msg = 'send email notification to users.'
        function = click.option(opt,
                                default=kwargs.get('default', False),
                                help=msg)(function)
        return function
    return f


def enable_rebase(**kwargs):
    def f(function):
        opt = '--enable-rebase/--no-enable-rebase'
        msg = 'enable the merge request rebase action.'
        function = click.option(opt,
                                default=kwargs.get('default', True),
                                help=msg)(function)
        return function
    return f


def run_integration(func_container, ctx, *args, **kwargs):
    try:
        int_name = func_container.QONTRACT_INTEGRATION.replace('_', '-')
        running_state = RunningState()
        running_state.integration = int_name
    except AttributeError:
        sys.stderr.write("Integration missing QONTRACT_INTEGRATION.\n")
        sys.exit(ExitCodes.ERROR)

    try:
        gql.init_from_config(sha_url=ctx['gql_sha_url'],
                             integration=int_name,
                             validate_schemas=ctx['validate_schemas'],
                             print_url=ctx['gql_url_print'])
    except GqlApiIntegrationNotFound as e:
        sys.stderr.write(str(e) + "\n")
        sys.exit(ExitCodes.INTEGRATION_NOT_FOUND)

    unleash_feature_state = get_feature_toggle_state(int_name)
    if not unleash_feature_state:
        logging.info('Integration toggle is disabled, skipping integration.')
        sys.exit(ExitCodes.SUCCESS)

    dry_run = ctx.get('dry_run', False)

    try:
        func_container.run(dry_run, *args, **kwargs)
    except RunnerException as e:
        sys.stderr.write(str(e) + "\n")
        sys.exit(ExitCodes.ERROR)
    except GqlApiErrorForbiddenSchema as e:
        sys.stderr.write(str(e) + "\n")
        sys.exit(ExitCodes.FORBIDDEN_SCHEMA)
    finally:
        if ctx.get('dump_schemas_file'):
            gqlapi = gql.get_api()
            with open(ctx.get('dump_schemas_file'), 'w') as f:
                f.write(json.dumps(gqlapi.get_queried_schemas()))


def init_log_level(log_level):
    level = getattr(logging, log_level) if log_level else logging.INFO
    logging.basicConfig(format=LOG_FMT, datefmt=LOG_DATEFMT, level=level)


@click.group()
@config_file
@dry_run
@validate_schemas
@dump_schemas
@gql_sha_url
@gql_url_print
@log_level
@click.pass_context
def integration(ctx, configfile, dry_run, validate_schemas, dump_schemas_file,
                log_level, gql_sha_url, gql_url_print):
    ctx.ensure_object(dict)

    init_log_level(log_level)
    config.init_from_toml(configfile)
    ctx.obj['dry_run'] = dry_run
    ctx.obj['validate_schemas'] = validate_schemas
    ctx.obj['gql_sha_url'] = gql_sha_url
    ctx.obj['gql_url_print'] = gql_url_print
    ctx.obj['dump_schemas_file'] = dump_schemas_file


@integration.command()
@print_only
@threaded()
@binary(['terraform'])
@binary_version('terraform', ['version'],
                TERRAFORM_VERSION_REGEX, TERRAFORM_VERSION)
@enable_deletion(default=False)
@click.pass_context
def terraform_aws_route53(ctx, print_only, enable_deletion,
                          thread_pool_size):
    run_integration(reconcile.terraform_aws_route53, ctx.obj,
                    print_only, enable_deletion, thread_pool_size)


@integration.command()
@click.pass_context
def github(ctx):
    run_integration(reconcile.github_org, ctx.obj)


@integration.command()
@click.pass_context
def github_owners(ctx):
    run_integration(reconcile.github_owners, ctx.obj)


@integration.command()
@environ(['gitlab_pr_submitter_queue_url'])
@gitlab_project_id
@threaded()
@enable_deletion(default=False)
@send_mails(default=False)
@click.pass_context
def github_users(ctx, gitlab_project_id, thread_pool_size,
                 enable_deletion, send_mails):
    run_integration(reconcile.github_users, ctx.obj,
                    gitlab_project_id, thread_pool_size,
                    enable_deletion, send_mails)


@integration.command()
@environ(['gitlab_pr_submitter_queue_url'])
@gitlab_project_id
@threaded()
@binary(['git', 'git-secrets'])
@click.pass_context
def github_scanner(ctx, gitlab_project_id, thread_pool_size):
    run_integration(reconcile.github_scanner, ctx.obj,
                    gitlab_project_id, thread_pool_size)


@integration.command()
@click.pass_context
def github_validator(ctx):
    run_integration(reconcile.github_validator, ctx.obj)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_clusterrolebindings(ctx, thread_pool_size, internal,
                                  use_jump_host):
    run_integration(reconcile.openshift_clusterrolebindings,
                    ctx.obj, thread_pool_size, internal,
                    use_jump_host)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_rolebindings(ctx, thread_pool_size, internal, use_jump_host):
    run_integration(reconcile.openshift_rolebindings, ctx.obj,
                    thread_pool_size, internal, use_jump_host)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_groups(ctx, thread_pool_size, internal, use_jump_host):
    run_integration(reconcile.openshift_groups, ctx.obj,
                    thread_pool_size, internal, use_jump_host)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_users(ctx, thread_pool_size, internal, use_jump_host):
    run_integration(reconcile.openshift_users, ctx.obj,
                    thread_pool_size, internal, use_jump_host)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@vault_output_path
@click.pass_context
def openshift_serviceaccount_tokens(ctx, thread_pool_size, internal,
                                    use_jump_host, vault_output_path):
    run_integration(reconcile.openshift_serviceaccount_tokens,
                    ctx.obj, thread_pool_size, internal,
                    use_jump_host, vault_output_path)


@integration.command()
@click.pass_context
def jenkins_roles(ctx):
    run_integration(reconcile.jenkins_roles, ctx.obj)


@integration.command()
@click.pass_context
def jenkins_plugins(ctx):
    run_integration(reconcile.jenkins_plugins, ctx.obj)


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@print_only
@config_name
@job_name
@instance_name
@throughput
@click.pass_context
def jenkins_job_builder(ctx, io_dir, print_only,
                        config_name, job_name, instance_name):
    run_integration(reconcile.jenkins_job_builder, ctx.obj, io_dir,
                    print_only, config_name, job_name, instance_name)


@integration.command()
@click.pass_context
def jenkins_job_builds_cleaner(ctx):
    run_integration(reconcile.jenkins_job_builds_cleaner, ctx.obj)


@integration.command()
@click.pass_context
def jenkins_job_cleaner(ctx):
    run_integration(reconcile.jenkins_job_cleaner, ctx.obj)


@integration.command()
@click.pass_context
def jenkins_webhooks(ctx):
    run_integration(reconcile.jenkins_webhooks, ctx.obj)


@integration.command()
@click.pass_context
def jenkins_webhooks_cleaner(ctx):
    run_integration(reconcile.jenkins_webhooks_cleaner, ctx.obj)


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@click.pass_context
def jira_watcher(ctx):
    run_integration(reconcile.jira_watcher, ctx.obj)


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@click.pass_context
def unleash_watcher(ctx):
    run_integration(reconcile.unleash_watcher, ctx.obj)


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@threaded()
@internal()
@use_jump_host()
@click.pass_context
def openshift_upgrade_watcher(ctx, thread_pool_size, internal, use_jump_host):
    run_integration(reconcile.openshift_upgrade_watcher, ctx.obj,
                    thread_pool_size, internal, use_jump_host)


@integration.command()
@click.pass_context
def slack_usergroups(ctx):
    run_integration(reconcile.slack_usergroups, ctx.obj)


@integration.command()
@click.pass_context
def slack_cluster_usergroups(ctx):
    run_integration(reconcile.slack_cluster_usergroups, ctx.obj)


@integration.command()
@click.pass_context
def gitlab_integrations(ctx):
    run_integration(reconcile.gitlab_integrations, ctx.obj)


@integration.command()
@threaded()
@click.pass_context
def gitlab_permissions(ctx, thread_pool_size):
    run_integration(reconcile.gitlab_permissions, ctx.obj,
                    thread_pool_size)


@integration.command()
@click.option('--wait-for-pipeline/--no-wait-for-pipeline',
              default=False,
              help='wait for pending/running pipelines before acting.')
@click.pass_context
def gitlab_housekeeping(ctx, wait_for_pipeline):
    run_integration(reconcile.gitlab_housekeeping, ctx.obj,
                    wait_for_pipeline)


@integration.command()
@environ(['gitlab_pr_submitter_queue_url'])
@click.argument('gitlab-project-id')
@click.pass_context
def gitlab_mr_sqs_consumer(ctx, gitlab_project_id):
    run_integration(reconcile.gitlab_mr_sqs_consumer, ctx.obj,
                    gitlab_project_id)


@integration.command()
@throughput
@threaded()
@click.pass_context
def aws_garbage_collector(ctx, thread_pool_size, io_dir):
    run_integration(reconcile.aws_garbage_collector, ctx.obj,
                    thread_pool_size, io_dir)


@integration.command()
@threaded()
@account_name
@click.pass_context
def aws_iam_keys(ctx, thread_pool_size, account_name):
    run_integration(reconcile.aws_iam_keys, ctx.obj,
                    thread_pool_size, account_name=account_name)


@integration.command()
@vault_output_path
@click.pass_context
def aws_ecr_image_pull_secrets(ctx, vault_output_path):
    run_integration(reconcile.aws_ecr_image_pull_secrets, ctx.obj,
                    vault_output_path)


@integration.command()
@environ(['gitlab_pr_submitter_queue_url'])
@gitlab_project_id
@threaded()
@click.pass_context
def aws_support_cases_sos(ctx, gitlab_project_id, thread_pool_size):
    run_integration(reconcile.aws_support_cases_sos, ctx.obj,
                    gitlab_project_id, thread_pool_size)


@integration.command()
@threaded(default=20)
@binary(['oc', 'ssh', 'amtool'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@cluster_name
@namespace_name
@click.pass_context
def openshift_resources(ctx, thread_pool_size, internal, use_jump_host,
                        cluster_name, namespace_name):
    run_integration(reconcile.openshift_resources,
                    ctx.obj, thread_pool_size, internal,
                    use_jump_host,
                    cluster_name=cluster_name,
                    namespace_name=namespace_name)


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@environ(['gitlab_pr_submitter_queue_url'])
@gitlab_project_id
@threaded(default=20)
@throughput
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@click.option('--saas-file-name',
              default=None,
              help='saas-file to act on.')
@click.option('--env-name',
              default=None,
              help='environment to deploy to.')
@click.pass_context
def openshift_saas_deploy(ctx, thread_pool_size, io_dir,
                          saas_file_name, env_name, gitlab_project_id):
    run_integration(reconcile.openshift_saas_deploy,
                    ctx.obj, thread_pool_size, io_dir,
                    saas_file_name, env_name, gitlab_project_id)


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@environ(['gitlab_pr_submitter_queue_url'])
@gitlab_project_id
@threaded()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@throughput
@click.pass_context
def openshift_saas_deploy_wrapper(ctx, thread_pool_size, io_dir,
                                  gitlab_project_id):
    run_integration(reconcile.openshift_saas_deploy_wrapper,
                    ctx.obj, thread_pool_size, io_dir, gitlab_project_id)


@integration.command()
@click.pass_context
def saas_file_validator(ctx):
    run_integration(reconcile.saas_file_validator, ctx.obj)


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@threaded()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_saas_deploy_trigger_moving_commits(ctx, thread_pool_size,
                                                 internal, use_jump_host):
    run_integration(
        reconcile.openshift_saas_deploy_trigger_moving_commits,
        ctx.obj, thread_pool_size, internal, use_jump_host)


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@threaded()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_saas_deploy_trigger_upstream_jobs(ctx, thread_pool_size,
                                                internal, use_jump_host):
    run_integration(
        reconcile.openshift_saas_deploy_trigger_upstream_jobs,
        ctx.obj, thread_pool_size, internal, use_jump_host)


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@threaded()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_saas_deploy_trigger_configs(ctx, thread_pool_size,
                                          internal, use_jump_host):
    run_integration(
        reconcile.openshift_saas_deploy_trigger_configs,
        ctx.obj, thread_pool_size, internal, use_jump_host)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_saas_deploy_trigger_cleaner(ctx, thread_pool_size,
                                          internal, use_jump_host):
    run_integration(
        reconcile.openshift_saas_deploy_trigger_cleaner,
        ctx.obj, thread_pool_size, internal, use_jump_host)


@integration.command()
@throughput
@click.argument('gitlab-project-id')
@click.argument('gitlab-merge-request-id')
@click.option('--compare/--no-compare',
              default=True,
              help='compare between current and desired state.')
@click.pass_context
def saas_file_owners(ctx, gitlab_project_id, gitlab_merge_request_id,
                     io_dir, compare):
    run_integration(reconcile.saas_file_owners, ctx.obj,
                    gitlab_project_id, gitlab_merge_request_id,
                    io_dir, compare)


@integration.command()
@click.argument('gitlab-project-id')
@click.argument('gitlab-merge-request-id')
@click.pass_context
def gitlab_ci_skipper(ctx, gitlab_project_id, gitlab_merge_request_id):
    run_integration(reconcile.gitlab_ci_skipper, ctx.obj,
                    gitlab_project_id, gitlab_merge_request_id)


@integration.command()
@click.argument('gitlab-project-id')
@click.argument('gitlab-merge-request-id')
@click.pass_context
def gitlab_labeler(ctx, gitlab_project_id, gitlab_merge_request_id):
    run_integration(reconcile.gitlab_labeler, ctx.obj,
                    gitlab_project_id, gitlab_merge_request_id)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_namespaces(ctx, thread_pool_size, internal, use_jump_host):
    run_integration(reconcile.openshift_namespaces,
                    ctx.obj, thread_pool_size, internal,
                    use_jump_host)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_network_policies(ctx, thread_pool_size, internal, use_jump_host):
    run_integration(reconcile.openshift_network_policies,
                    ctx.obj, thread_pool_size, internal,
                    use_jump_host)


@integration.command()
@threaded()
@take_over()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_limitranges(ctx, thread_pool_size, internal,
                          use_jump_host, take_over):
    run_integration(reconcile.openshift_limitranges,
                    ctx.obj, thread_pool_size, internal,
                    use_jump_host, take_over)


@integration.command()
@threaded()
@take_over()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@click.pass_context
def openshift_resourcequotas(ctx, thread_pool_size, internal,
                             use_jump_host, take_over):
    run_integration(reconcile.openshift_resourcequotas,
                    ctx.obj, thread_pool_size, internal,
                    use_jump_host, take_over)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@cluster_name
@namespace_name
@click.pass_context
def openshift_vault_secrets(ctx, thread_pool_size, internal, use_jump_host,
                            cluster_name, namespace_name):
    run_integration(reconcile.openshift_vault_secrets,
                    ctx.obj, thread_pool_size, internal, use_jump_host,
                    cluster_name=cluster_name,
                    namespace_name=namespace_name)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@cluster_name
@namespace_name
@click.pass_context
def openshift_routes(ctx, thread_pool_size, internal, use_jump_host,
                     cluster_name, namespace_name):
    run_integration(reconcile.openshift_routes,
                    ctx.obj, thread_pool_size, internal, use_jump_host,
                    cluster_name=cluster_name,
                    namespace_name=namespace_name)


@integration.command()
@click.pass_context
def quay_membership(ctx):
    run_integration(reconcile.quay_membership, ctx.obj)


@integration.command()
@click.pass_context
@binary(['skopeo'])
def gcr_mirror(ctx):
    run_integration(reconcile.gcr_mirror, ctx.obj)


@integration.command()
@click.pass_context
@binary(['skopeo'])
def quay_mirror(ctx):
    run_integration(reconcile.quay_mirror, ctx.obj)


@integration.command()
@click.pass_context
@binary(['skopeo'])
def quay_mirror_org(ctx):
    run_integration(reconcile.quay_mirror_org, ctx.obj)


@integration.command()
@click.pass_context
def quay_repos(ctx):
    run_integration(reconcile.quay_repos, ctx.obj)


@integration.command()
@click.pass_context
def quay_permissions(ctx):
    run_integration(reconcile.quay_permissions, ctx.obj)


@integration.command()
@click.argument('gitlab-project-id')
@click.pass_context
def ldap_users(ctx, gitlab_project_id):
    run_integration(reconcile.ldap_users, ctx.obj, gitlab_project_id)


@integration.command()
@click.pass_context
def user_validator(ctx):
    run_integration(reconcile.user_validator, ctx.obj)


@integration.command()
@print_only
@throughput
@vault_output_path
@threaded(default=20)
@binary(['terraform', 'oc'])
@binary_version('terraform', ['version'],
                TERRAFORM_VERSION_REGEX, TERRAFORM_VERSION)
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@enable_deletion(default=False)
@account_name
@click.option('--light/--full',
              default=False,
              help='run without executing terraform plan and apply.')
@click.pass_context
def terraform_resources(ctx, print_only, enable_deletion,
                        io_dir, thread_pool_size, internal, use_jump_host,
                        light, vault_output_path, account_name):
    run_integration(reconcile.terraform_resources,
                    ctx.obj, print_only,
                    enable_deletion, io_dir, thread_pool_size,
                    internal, use_jump_host, light, vault_output_path,
                    account_name=account_name,
                    extra_labels=ctx.obj.get('extra_labels', {}))


@integration.command()
@print_only
@throughput
@vault_output_path
@threaded(default=20)
@binary(['terraform', 'oc'])
@binary_version('terraform', ['version'],
                TERRAFORM_VERSION_REGEX, TERRAFORM_VERSION)
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@enable_deletion(default=False)
@click.option('--light/--full',
              default=False,
              help='run without executing terraform plan and apply.')
@click.pass_context
def terraform_resources_wrapper(ctx, print_only, enable_deletion,
                                io_dir, thread_pool_size, internal,
                                use_jump_host, light, vault_output_path):
    run_integration(reconcile.terraform_resources_wrapper,
                    ctx.obj, print_only,
                    enable_deletion, io_dir, thread_pool_size,
                    internal, use_jump_host, light, vault_output_path,
                    extra_labels=ctx.obj.get('extra_labels', {}))


@integration.command()
@print_only
@throughput
@threaded(default=20)
@binary(['terraform', 'gpg'])
@binary_version('terraform', ['version'],
                TERRAFORM_VERSION_REGEX, TERRAFORM_VERSION)
@enable_deletion(default=True)
@send_mails(default=True)
@click.pass_context
def terraform_users(ctx, print_only, enable_deletion, io_dir,
                    thread_pool_size, send_mails):
    run_integration(reconcile.terraform_users,
                    ctx.obj, print_only,
                    enable_deletion, io_dir,
                    thread_pool_size, send_mails)


@integration.command()
@print_only
@threaded()
@binary(['terraform'])
@binary_version('terraform', ['version'],
                TERRAFORM_VERSION_REGEX, TERRAFORM_VERSION)
@enable_deletion(default=False)
@click.pass_context
def terraform_vpc_peerings(ctx, print_only, enable_deletion,
                           thread_pool_size):
    run_integration(reconcile.terraform_vpc_peerings,
                    ctx.obj, print_only,
                    enable_deletion, thread_pool_size)


@integration.command()
@print_only
@threaded()
@binary(['terraform'])
@binary_version('terraform', ['version'],
                TERRAFORM_VERSION_REGEX, TERRAFORM_VERSION)
@enable_deletion(default=False)
@click.pass_context
def terraform_tgw_attachments(ctx, print_only, enable_deletion,
                              thread_pool_size):
    run_integration(reconcile.terraform_tgw_attachments,
                    ctx.obj, print_only,
                    enable_deletion, thread_pool_size)


@integration.command()
@click.pass_context
def github_repo_invites(ctx):
    run_integration(reconcile.github_repo_invites, ctx.obj)


@integration.command()
@click.argument('instance-name')
@click.argument('bot-token-org-name')
@click.pass_context
def github_repo_permissions_validator(ctx, instance_name, bot_token_org_name):
    run_integration(reconcile.github_repo_permissions_validator,
                    ctx.obj, instance_name, bot_token_org_name)


@integration.command()
@click.pass_context
def gitlab_members(ctx):
    run_integration(reconcile.gitlab_members, ctx.obj)


@integration.command()
@click.pass_context
def gitlab_projects(ctx):
    run_integration(reconcile.gitlab_projects, ctx.obj)


@integration.command()
@threaded()
@click.pass_context
def ocm_groups(ctx, thread_pool_size):
    run_integration(reconcile.ocm_groups, ctx.obj, thread_pool_size)


@integration.command()
@environ(['gitlab_pr_submitter_queue_url'])
@gitlab_project_id
@threaded()
@click.pass_context
def ocm_clusters(ctx, gitlab_project_id, thread_pool_size):
    run_integration(reconcile.ocm_clusters, ctx.obj,
                    gitlab_project_id, thread_pool_size)


@integration.command()
@threaded()
@click.pass_context
def ocm_external_configuration_labels(ctx, thread_pool_size):
    run_integration(reconcile.ocm_external_configuration_labels, ctx.obj,
                    thread_pool_size)


@integration.command()
@threaded()
@click.pass_context
def ocm_machine_pools(ctx, thread_pool_size):
    run_integration(reconcile.ocm_machine_pools, ctx.obj, thread_pool_size)


@integration.command()
@threaded()
@click.pass_context
def ocm_upgrade_scheduler(ctx, thread_pool_size):
    run_integration(reconcile.ocm_upgrade_scheduler, ctx.obj,
                    thread_pool_size)


@integration.command()
@threaded()
@click.pass_context
def ocm_addons(ctx, thread_pool_size):
    run_integration(reconcile.ocm_addons, ctx.obj,
                    thread_pool_size)


@integration.command()
@click.pass_context
def ocm_aws_infrastructure_access(ctx):
    run_integration(reconcile.ocm_aws_infrastructure_access, ctx.obj)


@integration.command()
@vault_input_path
@click.pass_context
def ocm_github_idp(ctx, vault_input_path):
    run_integration(reconcile.ocm_github_idp, ctx.obj, vault_input_path)


@integration.command()
@click.pass_context
def ocm_additional_routers(ctx):
    run_integration(reconcile.ocm_additional_routers, ctx.obj)


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@click.pass_context
def email_sender(ctx):
    run_integration(reconcile.email_sender, ctx.obj)


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@click.pass_context
def sentry_helper(ctx):
    run_integration(reconcile.sentry_helper, ctx.obj)


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@click.pass_context
def requests_sender(ctx):
    run_integration(reconcile.requests_sender, ctx.obj)


@integration.command()
@click.pass_context
def service_dependencies(ctx):
    run_integration(reconcile.service_dependencies, ctx.obj)


@integration.command()
@click.pass_context
def sentry_config(ctx):
    run_integration(reconcile.sentry_config, ctx.obj)


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@enable_deletion(default=False)
@click.pass_context
def sql_query(ctx, enable_deletion):
    run_integration(reconcile.sql_query, ctx.obj, enable_deletion)


@integration.command()
@threaded()
@click.pass_context
def gitlab_owners(ctx, thread_pool_size):
    run_integration(reconcile.gitlab_owners, ctx.obj, thread_pool_size)


@integration.command()
@click.argument('gitlab-project-id')
@click.argument('gitlab-merge-request-id')
@click.argument('gitlab-maintainers-group')
@click.pass_context
def gitlab_fork_compliance(ctx, gitlab_project_id, gitlab_merge_request_id,
                           gitlab_maintainers_group):
    run_integration(reconcile.gitlab_fork_compliance, ctx.obj,
                    gitlab_project_id, gitlab_merge_request_id,
                    gitlab_maintainers_group)


@integration.command()
@threaded(default=2)
@click.pass_context
def dashdotdb_cso(ctx, thread_pool_size):
    run_integration(reconcile.dashdotdb_cso, ctx.obj, thread_pool_size)


@integration.command()
@threaded(default=2)
@click.pass_context
@cluster_name
def dashdotdb_dvo(ctx, thread_pool_size, cluster_name):
    run_integration(reconcile.dashdotdb_dvo, ctx.obj,
                    thread_pool_size, cluster_name)


@integration.command()
@threaded(default=2)
@click.pass_context
def dashdotdb_slo(ctx, thread_pool_size):
    run_integration(reconcile.dashdotdb_slo, ctx.obj, thread_pool_size)


@integration.command()
@click.pass_context
def ocp_release_mirror(ctx):
    run_integration(reconcile.ocp_release_mirror, ctx.obj)


@integration.command()
@gitlab_project_id
@click.pass_context
def osd_mirrors_data_updater(ctx, gitlab_project_id):
    run_integration(reconcile.osd_mirrors_data_updater, ctx.obj,
                    gitlab_project_id)


@integration.command()
@threaded()
@click.pass_context
def ecr_mirror(ctx, thread_pool_size):
    run_integration(reconcile.ecr_mirror, ctx.obj, thread_pool_size)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@binary_version('oc', ['version', '--client'], OC_VERSION_REGEX, OC_VERSION)
@internal()
@use_jump_host()
@vault_throughput_path
@click.pass_context
def kafka_clusters(ctx, thread_pool_size, internal, use_jump_host,
                   vault_throughput_path):
    run_integration(reconcile.kafka_clusters, ctx.obj, thread_pool_size,
                    internal, use_jump_host, vault_throughput_path)


@integration.command()
@click.pass_context
def integrations_validator(ctx):
    run_integration(reconcile.integrations_validator, ctx.obj,
                    reconcile.cli.integration.commands.keys())


@integration.command()
@threaded()
@binary(['promtool'])
@cluster_name
@click.pass_context
def prometheus_rules_tester(ctx, thread_pool_size, cluster_name):
    run_integration(reconcile.prometheus_rules_tester, ctx.obj,
                    thread_pool_size, cluster_name)


@integration.command()
@click.pass_context
def sendgrid_teammates(ctx):
    run_integration(reconcile.sendgrid_teammates, ctx.obj)


@integration.command()
@vault_output_path
@click.pass_context
def cluster_deployment_mapper(ctx, vault_output_path):
    run_integration(reconcile.cluster_deployment_mapper, ctx.obj,
                    vault_output_path)

import os
import sys
import logging
import click

from UnleashClient import UnleashClient

import utils.config as config
import utils.gql as gql
import reconcile.github_org
import reconcile.github_users
import reconcile.github_scanner
import reconcile.github_validator
import reconcile.openshift_acme
import reconcile.openshift_clusterrolebindings
import reconcile.openshift_rolebindings
import reconcile.openshift_groups
import reconcile.openshift_limitranges
import reconcile.openshift_resourcequotas
import reconcile.openshift_users
import reconcile.openshift_resources
import reconcile.openshift_namespaces
import reconcile.openshift_network_policies
import reconcile.openshift_performance_parameters
import reconcile.openshift_serviceaccount_tokens
import reconcile.openshift_saas_deploy
import reconcile.openshift_saas_deploy_trigger_moving_commits
import reconcile.openshift_saas_deploy_trigger_configs
import reconcile.saas_file_owners
import reconcile.quay_membership
import reconcile.quay_mirror
import reconcile.quay_repos
import reconcile.ldap_users
import reconcile.terraform_resources
import reconcile.terraform_users
import reconcile.terraform_vpc_peerings
import reconcile.github_repo_invites
import reconcile.jenkins_roles
import reconcile.jenkins_plugins
import reconcile.jenkins_job_builder
import reconcile.jenkins_webhooks
import reconcile.jira_watcher
import reconcile.slack_usergroups
import reconcile.gitlab_integrations
import reconcile.gitlab_permissions
import reconcile.gitlab_housekeeping
import reconcile.gitlab_fork_compliance
import reconcile.gitlab_members
import reconcile.gitlab_owners
import reconcile.gitlab_pr_submitter
import reconcile.gitlab_projects
import reconcile.aws_garbage_collector
import reconcile.aws_iam_keys
import reconcile.aws_support_cases_sos
import reconcile.ocm_groups
import reconcile.ocm_clusters
import reconcile.ocm_aws_infrastructure_access
import reconcile.email_sender
import reconcile.requests_sender
import reconcile.service_dependencies
import reconcile.sentry_config
import reconcile.sql_query
import reconcile.user_validator

from utils.gql import GqlApiError
from utils.aggregated_list import RunnerException
from utils.binary import binary
from utils.environ import environ
from utils.defer import defer


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


def terraform(function):
    function = click.option('--print-only/--no-print-only',
                            help='only print the terraform config file.',
                            default=False)(function)

    return function


def throughput(function):
    function = click.option('--io-dir',
                            help='directory of input/output files.',
                            default='throughput/')(function)

    return function


def vault_output_path(function):
    function = click.option('--vault-output-path',
                            help='path in Vault to store output resources.',
                            default='')(function)

    return function


def gitlab_project_id(function):
    function = click.option('--gitlab-project-id',
                            help='gitlab project id to submit PRs to. '
                                 'not required if pullRequestGateway '
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


def get_feature_toggle_default(feature_name: str, context: dict) -> bool:
    return True


@defer
def get_feature_toggle_state(integration_name, defer=None):
    api_url = os.environ.get('UNLEASH_API_URL')
    client_access_token = os.environ.get('UNLEASH_CLIENT_ACCESS_TOKEN')
    if not (api_url and client_access_token):
        return True

    # hide INFO logging from UnleashClient
    logger = logging.getLogger()
    default_logging = logger.level
    logger.setLevel(logging.ERROR)
    defer(lambda: logger.setLevel(default_logging))

    headers = {'Authorization': f'Bearer {client_access_token}'}
    client = UnleashClient(url=api_url,
                           app_name='qontract-reconcile',
                           custom_headers=headers)
    client.initialize_client()
    defer(lambda: client.destroy())

    state = client.is_enabled(integration_name,
                              fallback_function=get_feature_toggle_true)
    return state


def run_integration(func_container, *args):
    integration_name = func_container.QONTRACT_INTEGRATION.replace('_', '-')
    unleash_feature_state = get_feature_toggle_default(integration_name)
    if not unleash_feature_state:
        logging.info('Integration toggle is disabled, skipping integration.')
        sys.exit(0)

    try:
        func_container.run(*args)
    except RunnerException as e:
        sys.stderr.write(str(e) + "\n")
        sys.exit(1)
    except GqlApiError as e:
        if '409' in str(e):
            logging.error(f'Data changed during execution. This is fine.')
            # exit code to relect conflict
            # TODO: document this better
            sys.exit(3)
        else:
            raise e


def init_log_level(log_level):
    level = getattr(logging, log_level) if log_level else logging.INFO
    format = '[%(asctime)s] [%(levelname)s] '
    format += '[%(filename)s:%(funcName)s:%(lineno)d] '
    format += '- %(message)s'
    logging.basicConfig(format=format,
                        datefmt='%Y-%m-%d %H:%M:%S',
                        level=level)


@click.group()
@config_file
@dry_run
@log_level
@click.pass_context
def integration(ctx, configfile, dry_run, log_level):
    ctx.ensure_object(dict)

    init_log_level(log_level)
    config.init_from_toml(configfile)
    gql.init_from_config()
    ctx.obj['dry_run'] = dry_run


@integration.command()
@click.pass_context
def github(ctx):
    run_integration(reconcile.github_org, ctx.obj['dry_run'])


@integration.command()
@environ(['gitlab_pr_submitter_queue_url'])
@gitlab_project_id
@threaded()
@enable_deletion(default=False)
@send_mails(default=False)
@click.pass_context
def github_users(ctx, gitlab_project_id, thread_pool_size,
                 enable_deletion, send_mails):
    run_integration(reconcile.github_users, ctx.obj['dry_run'],
                    gitlab_project_id, thread_pool_size,
                    enable_deletion, send_mails)


@integration.command()
@environ(['gitlab_pr_submitter_queue_url'])
@gitlab_project_id
@threaded()
@binary(['git', 'git-secrets'])
@click.pass_context
def github_scanner(ctx, gitlab_project_id, thread_pool_size):
    run_integration(reconcile.github_scanner, ctx.obj['dry_run'],
                    gitlab_project_id, thread_pool_size)


@integration.command()
@click.pass_context
def github_validator(ctx):
    run_integration(reconcile.github_validator, ctx.obj['dry_run'])


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@internal()
@use_jump_host()
@click.pass_context
def openshift_clusterrolebindings(ctx, thread_pool_size, internal,
                                  use_jump_host):
    run_integration(reconcile.openshift_clusterrolebindings,
                    ctx.obj['dry_run'], thread_pool_size, internal,
                    use_jump_host)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@internal()
@use_jump_host()
@click.pass_context
def openshift_rolebindings(ctx, thread_pool_size, internal, use_jump_host):
    run_integration(reconcile.openshift_rolebindings, ctx.obj['dry_run'],
                    thread_pool_size, internal, use_jump_host)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@internal()
@use_jump_host()
@click.pass_context
def openshift_groups(ctx, thread_pool_size, internal, use_jump_host):
    run_integration(reconcile.openshift_groups, ctx.obj['dry_run'],
                    thread_pool_size, internal, use_jump_host)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@internal()
@use_jump_host()
@click.pass_context
def openshift_users(ctx, thread_pool_size, internal, use_jump_host):
    run_integration(reconcile.openshift_users, ctx.obj['dry_run'],
                    thread_pool_size, internal, use_jump_host)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@internal()
@use_jump_host()
@vault_output_path
@click.pass_context
def openshift_serviceaccount_tokens(ctx, thread_pool_size, internal,
                                    use_jump_host, vault_output_path):
    run_integration(reconcile.openshift_serviceaccount_tokens,
                    ctx.obj['dry_run'], thread_pool_size, internal,
                    use_jump_host, vault_output_path)


@integration.command()
@click.pass_context
def jenkins_roles(ctx):
    run_integration(reconcile.jenkins_roles, ctx.obj['dry_run'])


@integration.command()
@click.pass_context
def jenkins_plugins(ctx):
    run_integration(reconcile.jenkins_plugins, ctx.obj['dry_run'])


@integration.command()
@throughput
@click.option('--compare/--no-compare',
              default=True,
              help='compare between current and desired state.')
@click.pass_context
def jenkins_job_builder(ctx, io_dir, compare):
    run_integration(reconcile.jenkins_job_builder, ctx.obj['dry_run'],
                    io_dir, compare)


@integration.command()
@click.pass_context
def jenkins_webhooks(ctx):
    run_integration(reconcile.jenkins_webhooks, ctx.obj['dry_run'])


@integration.command()
@throughput
@click.pass_context
def jira_watcher(ctx, io_dir):
    run_integration(reconcile.jira_watcher, ctx.obj['dry_run'], io_dir)


@integration.command()
@click.pass_context
def slack_usergroups(ctx):
    run_integration(reconcile.slack_usergroups, ctx.obj['dry_run'])


@integration.command()
@click.pass_context
def gitlab_integrations(ctx):
    run_integration(reconcile.gitlab_integrations, ctx.obj['dry_run'])


@integration.command()
@threaded()
@click.pass_context
def gitlab_permissions(ctx, thread_pool_size):
    run_integration(reconcile.gitlab_permissions, ctx.obj['dry_run'],
                    thread_pool_size)


@integration.command()
@click.option('--days-interval',
              default=15,
              help='interval of days between actions.')
@click.option('--limit',
              default=1,
              help='max number of rebases/merges to perform.')
@enable_deletion(default=False)
@click.pass_context
def gitlab_housekeeping(ctx, days_interval,
                        enable_deletion, limit):
    run_integration(reconcile.gitlab_housekeeping,
                    ctx.obj['dry_run'], days_interval, enable_deletion,
                    limit)


@integration.command()
@environ(['gitlab_pr_submitter_queue_url'])
@click.argument('gitlab-project-id')
@click.pass_context
def gitlab_pr_submitter(ctx, gitlab_project_id):
    run_integration(reconcile.gitlab_pr_submitter, gitlab_project_id,
                    ctx.obj['dry_run'])


@integration.command()
@throughput
@threaded()
@click.pass_context
def aws_garbage_collector(ctx, thread_pool_size, io_dir):
    run_integration(reconcile.aws_garbage_collector, ctx.obj['dry_run'],
                    thread_pool_size, io_dir)


@integration.command()
@threaded()
@click.pass_context
def aws_iam_keys(ctx, thread_pool_size):
    run_integration(reconcile.aws_iam_keys, ctx.obj['dry_run'],
                    thread_pool_size)


@integration.command()
@environ(['gitlab_pr_submitter_queue_url'])
@gitlab_project_id
@threaded()
@click.pass_context
def aws_support_cases_sos(ctx, gitlab_project_id, thread_pool_size):
    run_integration(reconcile.aws_support_cases_sos, ctx.obj['dry_run'],
                    gitlab_project_id, thread_pool_size)


@integration.command()
@threaded(default=20)
@binary(['oc', 'ssh'])
@internal()
@use_jump_host()
@click.pass_context
def openshift_resources(ctx, thread_pool_size, internal, use_jump_host):
    run_integration(reconcile.openshift_resources,
                    ctx.obj['dry_run'], thread_pool_size, internal,
                    use_jump_host)


@integration.command()
@threaded(default=20)
@binary(['oc', 'ssh'])
@click.option('--saas-file-name',
              default=None,
              help='saas-file to act on.')
@click.option('--env-name',
              default=None,
              help='environment to deploy to.')
@click.pass_context
def openshift_saas_deploy(ctx, thread_pool_size, saas_file_name, env_name):
    run_integration(reconcile.openshift_saas_deploy,
                    ctx.obj['dry_run'], thread_pool_size,
                    saas_file_name, env_name)


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@threaded()
@click.pass_context
def openshift_saas_deploy_trigger_moving_commits(ctx, thread_pool_size):
    run_integration(
        reconcile.openshift_saas_deploy_trigger_moving_commits,
        ctx.obj['dry_run'], thread_pool_size)


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@threaded()
@click.pass_context
def openshift_saas_deploy_trigger_configs(ctx, thread_pool_size):
    run_integration(
        reconcile.openshift_saas_deploy_trigger_configs,
        ctx.obj['dry_run'], thread_pool_size)


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
    run_integration(reconcile.saas_file_owners,
                    gitlab_project_id, gitlab_merge_request_id,
                    ctx.obj['dry_run'], io_dir, compare)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@internal()
@use_jump_host()
@click.pass_context
def openshift_namespaces(ctx, thread_pool_size, internal, use_jump_host):
    run_integration(reconcile.openshift_namespaces,
                    ctx.obj['dry_run'], thread_pool_size, internal,
                    use_jump_host)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@internal()
@use_jump_host()
@click.pass_context
def openshift_network_policies(ctx, thread_pool_size, internal, use_jump_host):
    run_integration(reconcile.openshift_network_policies,
                    ctx.obj['dry_run'], thread_pool_size, internal,
                    use_jump_host)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@internal()
@use_jump_host()
@click.pass_context
def openshift_acme(ctx, thread_pool_size, internal, use_jump_host):
    run_integration(reconcile.openshift_acme,
                    ctx.obj['dry_run'], thread_pool_size, internal,
                    use_jump_host)


@integration.command()
@threaded()
@take_over()
@binary(['oc', 'ssh'])
@internal()
@use_jump_host()
@click.pass_context
def openshift_limitranges(ctx, thread_pool_size, internal,
                          use_jump_host, take_over):
    run_integration(reconcile.openshift_limitranges,
                    ctx.obj['dry_run'], thread_pool_size, internal,
                    use_jump_host, take_over)


@integration.command()
@threaded()
@take_over()
@binary(['oc', 'ssh'])
@internal()
@use_jump_host()
@click.pass_context
def openshift_resourcequotas(ctx, thread_pool_size, internal,
                             use_jump_host, take_over):
    run_integration(reconcile.openshift_resourcequotas,
                    ctx.obj['dry_run'], thread_pool_size, internal,
                    use_jump_host, take_over)


@integration.command()
@threaded()
@binary(['oc', 'ssh', 'jsonnet'])
@internal()
@use_jump_host()
@click.pass_context
def openshift_performance_parameters(ctx, thread_pool_size, internal,
                                     use_jump_host):
    run_integration(reconcile.openshift_performance_parameters,
                    ctx.obj['dry_run'], thread_pool_size, internal,
                    use_jump_host)


@integration.command()
@click.pass_context
def quay_membership(ctx):
    run_integration(reconcile.quay_membership, ctx.obj['dry_run'])


@integration.command()
@click.pass_context
@binary(['skopeo'])
def quay_mirror(ctx):
    run_integration(reconcile.quay_mirror, ctx.obj['dry_run'])


@integration.command()
@click.pass_context
def quay_repos(ctx):
    run_integration(reconcile.quay_repos, ctx.obj['dry_run'])


@integration.command()
@click.argument('gitlab-project-id')
@threaded()
@click.pass_context
def ldap_users(ctx, gitlab_project_id, thread_pool_size):
    run_integration(reconcile.ldap_users, gitlab_project_id,
                    ctx.obj['dry_run'], thread_pool_size)


@integration.command()
@click.pass_context
def user_validator(ctx):
    run_integration(reconcile.user_validator, ctx.obj['dry_run'])


@integration.command()
@terraform
@throughput
@vault_output_path
@threaded(default=20)
@binary(['terraform', 'oc'])
@internal()
@use_jump_host()
@enable_deletion(default=False)
@click.option('--light/--full',
              default=False,
              help='run without executing terraform plan and apply.')
@click.pass_context
def terraform_resources(ctx, print_only, enable_deletion,
                        io_dir, thread_pool_size, internal, use_jump_host,
                        light, vault_output_path):
    run_integration(reconcile.terraform_resources,
                    ctx.obj['dry_run'], print_only,
                    enable_deletion, io_dir, thread_pool_size,
                    internal, use_jump_host, light, vault_output_path)


@integration.command()
@terraform
@throughput
@threaded(default=20)
@binary(['terraform', 'gpg'])
@enable_deletion(default=True)
@send_mails(default=True)
@click.pass_context
def terraform_users(ctx, print_only, enable_deletion, io_dir,
                    thread_pool_size, send_mails):
    run_integration(reconcile.terraform_users,
                    ctx.obj['dry_run'], print_only,
                    enable_deletion, io_dir,
                    thread_pool_size, send_mails)


@integration.command()
@terraform
@threaded()
@binary(['terraform'])
@enable_deletion(default=False)
@click.pass_context
def terraform_vpc_peerings(ctx, print_only, enable_deletion,
                           thread_pool_size):
    run_integration(reconcile.terraform_vpc_peerings,
                    ctx.obj['dry_run'], print_only,
                    enable_deletion, thread_pool_size)


@integration.command()
@click.pass_context
def github_repo_invites(ctx):
    run_integration(reconcile.github_repo_invites, ctx.obj['dry_run'])


@integration.command()
@click.pass_context
def gitlab_members(ctx):
    run_integration(reconcile.gitlab_members, ctx.obj['dry_run'])


@integration.command()
@click.pass_context
def gitlab_projects(ctx):
    run_integration(reconcile.gitlab_projects, ctx.obj['dry_run'])


@integration.command()
@threaded()
@click.pass_context
def ocm_groups(ctx, thread_pool_size):
    run_integration(reconcile.ocm_groups, ctx.obj['dry_run'],
                    thread_pool_size)


@integration.command()
@threaded()
@click.pass_context
def ocm_clusters(ctx, thread_pool_size):
    run_integration(reconcile.ocm_clusters, ctx.obj['dry_run'],
                    thread_pool_size)


@integration.command()
@click.pass_context
def ocm_aws_infrastructure_access(ctx):
    run_integration(reconcile.ocm_aws_infrastructure_access,
                    ctx.obj['dry_run'])


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@click.pass_context
def email_sender(ctx):
    run_integration(reconcile.email_sender, ctx.obj['dry_run'])


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@click.pass_context
def requests_sender(ctx):
    run_integration(reconcile.requests_sender, ctx.obj['dry_run'])


@integration.command()
@click.pass_context
def service_dependencies(ctx):
    run_integration(reconcile.service_dependencies, ctx.obj['dry_run'])


@integration.command()
@click.pass_context
def sentry_config(ctx):
    run_integration(reconcile.sentry_config, ctx.obj['dry_run'])


@integration.command()
@environ(['APP_INTERFACE_STATE_BUCKET', 'APP_INTERFACE_STATE_BUCKET_ACCOUNT'])
@enable_deletion(default=False)
@click.pass_context
def sql_query(ctx, enable_deletion):
    run_integration(reconcile.sql_query, ctx.obj['dry_run'],
                    enable_deletion)


@integration.command()
@click.pass_context
def gitlab_owners(ctx):
    run_integration(reconcile.gitlab_owners,
                    ctx.obj['dry_run'])


@integration.command()
@click.argument('gitlab-project-id')
@click.argument('gitlab-merge-request-id')
@click.argument('gitlab-maintainers-group')
def gitlab_fork_compliance(gitlab_project_id, gitlab_merge_request_id,
                           gitlab_maintainers_group):
    run_integration(reconcile.gitlab_fork_compliance,
                    gitlab_project_id, gitlab_merge_request_id,
                    gitlab_maintainers_group)

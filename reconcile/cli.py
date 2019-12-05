import sys
import logging
import click

import utils.config as config
import utils.gql as gql
import reconcile.github_org
import reconcile.github_users
import reconcile.github_scanner
import reconcile.openshift_acme
import reconcile.openshift_rolebindings
import reconcile.openshift_groups
import reconcile.openshift_limitranges
import reconcile.openshift_users
import reconcile.openshift_resources
import reconcile.openshift_namespaces
import reconcile.openshift_network_policies
import reconcile.openshift_prometheusrules
import reconcile.quay_membership
import reconcile.quay_repos
import reconcile.ldap_users
import reconcile.terraform_resources
import reconcile.terraform_users
import reconcile.github_repo_invites
import reconcile.jenkins_roles
import reconcile.jenkins_plugins
import reconcile.jenkins_job_builder
import reconcile.jenkins_webhooks
import reconcile.jira_watcher
import reconcile.slack_usergroups
import reconcile.gitlab_permissions
import reconcile.gitlab_housekeeping
import reconcile.gitlab_members
import reconcile.gitlab_pr_submitter
import reconcile.aws_garbage_collector
import reconcile.aws_iam_keys
import reconcile.aws_support_cases_sos

from utils.aggregated_list import RunnerException
from utils.binary import binary
from utils.environ import environ


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


def run_integration(func, *args):
    try:
        func(*args)
    except RunnerException as e:
        sys.stderr.write(str(e) + "\n")
        sys.exit(1)


def init_log_level(log_level):
    level = getattr(logging, log_level) if log_level else logging.INFO
    logging.basicConfig(format='%(levelname)s: %(message)s', level=level)


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
    run_integration(reconcile.github_org.run, ctx.obj['dry_run'])


@integration.command()
@environ(['gitlab_pr_submitter_queue_url'])
@gitlab_project_id
@threaded()
@enable_deletion(default=False)
@send_mails(default=False)
@click.pass_context
def github_users(ctx, gitlab_project_id, thread_pool_size,
                 enable_deletion, send_mails):
    run_integration(reconcile.github_users.run, ctx.obj['dry_run'],
                    gitlab_project_id, thread_pool_size,
                    enable_deletion, send_mails)


@integration.command()
@environ(['gitlab_pr_submitter_queue_url'])
@gitlab_project_id
@threaded()
@binary(['git', 'git-secrets'])
@click.pass_context
def github_scanner(ctx, gitlab_project_id, thread_pool_size):
    run_integration(reconcile.github_scanner.run, ctx.obj['dry_run'],
                    gitlab_project_id, thread_pool_size)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@internal()
@click.pass_context
def openshift_rolebindings(ctx, thread_pool_size, internal):
    run_integration(reconcile.openshift_rolebindings.run, ctx.obj['dry_run'],
                    thread_pool_size, internal)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@internal()
@click.pass_context
def openshift_groups(ctx, thread_pool_size, internal):
    run_integration(reconcile.openshift_groups.run, ctx.obj['dry_run'],
                    thread_pool_size, internal)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@internal()
@click.pass_context
def openshift_users(ctx, thread_pool_size, internal):
    run_integration(reconcile.openshift_users.run, ctx.obj['dry_run'],
                    thread_pool_size, internal)


@integration.command()
@click.pass_context
def jenkins_roles(ctx):
    run_integration(reconcile.jenkins_roles.run, ctx.obj['dry_run'])


@integration.command()
@click.pass_context
def jenkins_plugins(ctx):
    run_integration(reconcile.jenkins_plugins.run, ctx.obj['dry_run'])


@integration.command()
@throughput
@click.option('--compare/--no-compare',
              default=True,
              help='compare between current and desired state.')
@click.pass_context
def jenkins_job_builder(ctx, io_dir, compare):
    run_integration(reconcile.jenkins_job_builder.run, ctx.obj['dry_run'],
                    io_dir, compare)


@integration.command()
@click.pass_context
def jenkins_webhooks(ctx):
    run_integration(reconcile.jenkins_webhooks.run, ctx.obj['dry_run'])


@integration.command()
@throughput
@click.pass_context
def jira_watcher(ctx, io_dir):
    run_integration(reconcile.jira_watcher.run, ctx.obj['dry_run'], io_dir)


@integration.command()
@click.pass_context
def slack_usergroups(ctx):
    run_integration(reconcile.slack_usergroups.run, ctx.obj['dry_run'])


@integration.command()
@threaded()
@click.pass_context
def gitlab_permissions(ctx, thread_pool_size):
    run_integration(reconcile.gitlab_permissions.run, ctx.obj['dry_run'],
                    thread_pool_size)


@integration.command()
@click.argument('gitlab-project-id')
@click.option('--days-interval',
              default=15,
              help='interval of days between actions.')
@click.option('--limit',
              default=1,
              help='max number of rebases/merges to perform.')
@enable_deletion(default=False)
@click.pass_context
def gitlab_housekeeping(ctx, gitlab_project_id, days_interval,
                        enable_deletion, limit):
    run_integration(reconcile.gitlab_housekeeping.run, gitlab_project_id,
                    ctx.obj['dry_run'], days_interval, enable_deletion,
                    limit)


@integration.command()
@environ(['gitlab_pr_submitter_queue_url'])
@click.argument('gitlab-project-id')
@click.pass_context
def gitlab_pr_submitter(ctx, gitlab_project_id):
    run_integration(reconcile.gitlab_pr_submitter.run, gitlab_project_id,
                    ctx.obj['dry_run'])


@integration.command()
@throughput
@threaded()
@enable_deletion(default=False)
@click.pass_context
def aws_garbage_collector(ctx, thread_pool_size, enable_deletion, io_dir):
    run_integration(reconcile.aws_garbage_collector.run, ctx.obj['dry_run'],
                    thread_pool_size, enable_deletion, io_dir)


@integration.command()
@threaded()
@click.pass_context
def aws_iam_keys(ctx, thread_pool_size):
    run_integration(reconcile.aws_iam_keys.run, ctx.obj['dry_run'],
                    thread_pool_size)


@integration.command()
@environ(['gitlab_pr_submitter_queue_url'])
@gitlab_project_id
@threaded()
@click.pass_context
def aws_support_cases_sos(ctx, gitlab_project_id, thread_pool_size):
    run_integration(reconcile.aws_support_cases_sos.run, ctx.obj['dry_run'],
                    gitlab_project_id, thread_pool_size)


@integration.command()
@threaded(default=20)
@binary(['oc', 'ssh'])
@internal()
@click.pass_context
def openshift_resources(ctx, thread_pool_size, internal):
    run_integration(reconcile.openshift_resources.run,
                    ctx.obj['dry_run'], thread_pool_size, internal)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@internal()
@click.pass_context
def openshift_namespaces(ctx, thread_pool_size, internal):
    run_integration(reconcile.openshift_namespaces.run,
                    ctx.obj['dry_run'], thread_pool_size, internal)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@internal()
@click.pass_context
def openshift_network_policies(ctx, thread_pool_size, internal):
    run_integration(reconcile.openshift_network_policies.run,
                    ctx.obj['dry_run'], thread_pool_size, internal)



@integration.command()
@threaded()
@binary(['oc', 'jb', 'jsonnet'])
@click.pass_context
def openshift_prometheusrules(ctx, thread_pool_size):
    run_integration(reconcile.openshift_prometheusrules.run,
                    ctx.obj['dry_run'], thread_pool_size)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@internal()
@click.pass_context
def openshift_acme(ctx, thread_pool_size, internal):
    run_integration(reconcile.openshift_acme.run,
                    ctx.obj['dry_run'], thread_pool_size, internal)


@integration.command()
@threaded()
@take_over()
@binary(['oc', 'ssh'])
@internal()
@click.pass_context
def openshift_limitranges(ctx, thread_pool_size, internal, take_over):
    run_integration(reconcile.openshift_limitranges.run,
                    ctx.obj['dry_run'], thread_pool_size, internal, take_over)


@integration.command()
@click.pass_context
def quay_membership(ctx):
    run_integration(reconcile.quay_membership.run, ctx.obj['dry_run'])


@integration.command()
@click.pass_context
def quay_repos(ctx):
    run_integration(reconcile.quay_repos.run, ctx.obj['dry_run'])


@integration.command()
@click.argument('gitlab-project-id')
@threaded()
@click.pass_context
def ldap_users(ctx, gitlab_project_id, thread_pool_size):
    run_integration(reconcile.ldap_users.run, gitlab_project_id,
                    ctx.obj['dry_run'], thread_pool_size)


@integration.command()
@terraform
@throughput
@vault_output_path
@threaded(default=20)
@binary(['terraform', 'oc'])
@internal()
@enable_deletion(default=False)
@click.option('--light/--full',
              default=False,
              help='run without executing terraform plan and apply.')
@click.pass_context
def terraform_resources(ctx, print_only, enable_deletion,
                        io_dir, thread_pool_size, internal, light,
                        vault_output_path):
    run_integration(reconcile.terraform_resources.run,
                    ctx.obj['dry_run'], print_only,
                    enable_deletion, io_dir, thread_pool_size,
                    internal, light, vault_output_path)


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
    run_integration(reconcile.terraform_users.run,
                    ctx.obj['dry_run'], print_only,
                    enable_deletion, io_dir,
                    thread_pool_size, send_mails)


@integration.command()
@click.pass_context
def github_repo_invites(ctx):
    run_integration(reconcile.github_repo_invites.run, ctx.obj['dry_run'])


@integration.command()
@click.pass_context
def gitlab_members(ctx):
    run_integration(reconcile.gitlab_members.run, ctx.obj['dry_run'])

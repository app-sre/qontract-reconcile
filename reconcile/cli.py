import sys
import logging
import click

import utils.config as config
import utils.gql as gql
import reconcile.github_org
import reconcile.github_users
import reconcile.openshift_rolebinding
import reconcile.openshift_groups
import reconcile.openshift_users
import reconcile.openshift_resources
import reconcile.openshift_namespaces
import reconcile.openshift_resources_annotate
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
import reconcile.slack_usergroups
import reconcile.gitlab_permissions
import reconcile.gitlab_housekeeping
import reconcile.gitlab_members
import reconcile.aws_garbage_collector
import reconcile.aws_iam_keys

from utils.aggregated_list import RunnerException
from utils.binary import binary


def threaded(**kwargs):
    def f(function):
        opt = '--thread-pool-size'
        msg = 'number of threads to run in parallel.'
        function = click.option(opt,
                                default=kwargs.get('default', 10),
                                help=msg)(function)
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
        sys.stderr.write(e.message + "\n")
        sys.exit(1)


@click.group()
@click.option('--config', 'configfile',
              required=True,
              help='Path to configuration file in toml format.')
@click.option('--dry-run/--no-dry-run',
              default=False,
              help='If `true`, it will only print the planned actions '
                   'that would be performed, without executing them.')
@click.option('--log-level',
              help='log-level of the command. Defaults to INFO.',
              type=click.Choice([
                  'DEBUG',
                  'INFO',
                  'WARNING',
                  'ERROR',
                  'CRITICAL']))
@click.pass_context
def integration(ctx, configfile, dry_run, log_level):
    ctx.ensure_object(dict)

    level = getattr(logging, log_level) if log_level else logging.INFO
    logging.basicConfig(format='%(levelname)s: %(message)s', level=level)

    config.init_from_toml(configfile)

    gql.init_from_config()
    ctx.obj['dry_run'] = dry_run


@integration.command()
@click.pass_context
def github(ctx):
    run_integration(reconcile.github_org.run, ctx.obj['dry_run'])


@integration.command()
@click.argument('project-id')
@threaded()
@enable_deletion(default=False)
@send_mails(default=False)
@click.pass_context
def github_users(ctx, project_id, thread_pool_size,
                 enable_deletion, send_mails):
    run_integration(reconcile.github_users.run, project_id,
                    ctx.obj['dry_run'], thread_pool_size,
                    enable_deletion, send_mails)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@click.pass_context
def openshift_rolebinding(ctx, thread_pool_size):
    run_integration(reconcile.openshift_rolebinding.run, ctx.obj['dry_run'],
                    thread_pool_size)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@click.pass_context
def openshift_groups(ctx, thread_pool_size):
    run_integration(reconcile.openshift_groups.run, ctx.obj['dry_run'],
                    thread_pool_size)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@click.pass_context
def openshift_users(ctx, thread_pool_size):
    run_integration(reconcile.openshift_users.run, ctx.obj['dry_run'],
                    thread_pool_size)


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
@click.pass_context
def slack_usergroups(ctx):
    run_integration(reconcile.slack_usergroups.run, ctx.obj['dry_run'])


@integration.command()
@threaded()
@click.pass_context
def gitlab_permissions(ctx, thread_pool_size):
    run_integration(reconcile.gitlab_permissions.run, ctx.obj['dry_run'])


@integration.command()
@click.option('--days-interval',
              default=15,
              help='interval of days between actions.')
@enable_deletion(default=False)
@click.pass_context
def gitlab_housekeeping(ctx, days_interval, enable_deletion):
    run_integration(reconcile.gitlab_housekeeping.run, ctx.obj['dry_run'],
                    days_interval, enable_deletion)


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
@threaded(default=20)
@binary(['oc', 'ssh', 'openssl'])
@click.pass_context
def openshift_resources(ctx, thread_pool_size):
    run_integration(reconcile.openshift_resources.run,
                    ctx.obj['dry_run'], thread_pool_size)


@integration.command()
@threaded()
@binary(['oc', 'ssh'])
@click.pass_context
def openshift_namespaces(ctx, thread_pool_size):
    run_integration(reconcile.openshift_namespaces.run,
                    ctx.obj['dry_run'], thread_pool_size)


@integration.command()
@click.pass_context
def quay_membership(ctx):
    run_integration(reconcile.quay_membership.run, ctx.obj['dry_run'])


@integration.command()
@click.pass_context
def quay_repos(ctx):
    run_integration(reconcile.quay_repos.run, ctx.obj['dry_run'])


@integration.command()
@click.argument('project-id')
@threaded()
@click.pass_context
def ldap_users(ctx, project_id, thread_pool_size):
    run_integration(reconcile.ldap_users.run, project_id,
                    ctx.obj['dry_run'], thread_pool_size)


@integration.command()
@click.argument('cluster')
@click.argument('namespace')
@click.argument('kind')
@click.argument('name')
@click.pass_context
def openshift_resources_annotate(ctx, cluster, namespace, kind, name):
    run_integration(reconcile.openshift_resources_annotate.run,
                    ctx.obj['dry_run'], cluster, namespace, kind, name)


@integration.command()
@terraform
@throughput
@threaded(default=20)
@binary(['terraform', 'oc'])
@enable_deletion(default=False)
@click.pass_context
def terraform_resources(ctx, print_only, enable_deletion,
                        io_dir, thread_pool_size):
    run_integration(reconcile.terraform_resources.run,
                    ctx.obj['dry_run'], print_only,
                    enable_deletion, io_dir, thread_pool_size)


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

import sys
import logging
import click

import utils.config as config
import utils.gql as gql
import reconcile.github_org
import reconcile.openshift_rolebinding
import reconcile.openshift_resources
import reconcile.openshift_namespaces
import reconcile.openshift_resources_annotate
import reconcile.quay_membership
import reconcile.quay_repos
import reconcile.ldap_users
import reconcile.terraform_resources
import reconcile.terraform_users
import reconcile.github_repo_invites

from utils.aggregated_list import RunnerException


def threaded(function):
    function = click.option('--thread-pool-size',
                            help='number of threads to run in parallel',
                            default=10)(function)

    return function


def terraform(function):
    function = click.option('--print-only/--no-print-only',
                            help='only print the terraform config file.',
                            default=False)(function)

    return function


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
@click.pass_context
def openshift_rolebinding(ctx):
    run_integration(reconcile.openshift_rolebinding.run, ctx.obj['dry_run'])


@integration.command()
@threaded
@click.pass_context
def openshift_resources(ctx, thread_pool_size):
    run_integration(reconcile.openshift_resources.run,
                    ctx.obj['dry_run'], thread_pool_size)


@integration.command()
@threaded
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
@threaded
@click.pass_context
def ldap_users(ctx, thread_pool_size):
    run_integration(reconcile.ldap_users.run,
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
@threaded
@click.option('--enable-deletion/--no-enable-deletion',
              default=False,
              help='enable destroy/replace action.')
@click.pass_context
def terraform_resources(ctx, print_only, enable_deletion, thread_pool_size):
    run_integration(reconcile.terraform_resources.run,
                    ctx.obj['dry_run'], print_only,
                    enable_deletion, thread_pool_size)


@integration.command()
@terraform
@threaded
@click.option('--enable-deletion/--no-enable-deletion',
              default=True,
              help='enable destroy/replace action.')
@click.option('--send-mails/--no-send-mails',
              default=True,
              help='send email invitation to new users.')
@click.pass_context
def terraform_users(ctx, print_only, enable_deletion,
                    thread_pool_size, send_mails):
    run_integration(reconcile.terraform_users.run,
                    ctx.obj['dry_run'], print_only,
                    enable_deletion, thread_pool_size,
                    send_mails)


@integration.command()
@click.pass_context
def github_repo_invites(ctx):
    run_integration(reconcile.github_repo_invites.run, ctx.obj['dry_run'])

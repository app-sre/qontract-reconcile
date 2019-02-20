import sys
import logging

import click

import reconcile.config as config
import reconcile.gql as gql
import reconcile.github_org
import reconcile.openshift_rolebinding
import reconcile.openshift_resources
import reconcile.openshift_resources_annotate
import reconcile.quay_membership
import reconcile.quay_repos
import reconcile.ldap_users

from reconcile.aggregated_list import RunnerException


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
              help='If true, only print the planned actions that would be'
                   'performed, without executing them it.')
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
    logging.basicConfig(format='%(levelname)s:%(message)s', level=level)

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
@click.pass_context
def openshift_resources(ctx):
    run_integration(reconcile.openshift_resources.run, ctx.obj['dry_run'])


@integration.command()
@click.pass_context
def quay_membership(ctx):
    run_integration(reconcile.quay_membership.run, ctx.obj['dry_run'])


@integration.command()
@click.pass_context
def quay_repos(ctx):
    run_integration(reconcile.quay_repos.run, ctx.obj['dry_run'])


@integration.command()
@click.pass_context
def ldap_users(ctx):
    run_integration(reconcile.ldap_users.run, ctx.obj['dry_run'])


@integration.command()
@click.argument('cluster')
@click.argument('namespace')
@click.argument('kind')
@click.argument('name')
@click.pass_context
def openshift_resources_annotate(ctx, cluster, namespace, kind, name):
    run_integration(reconcile.openshift_resources_annotate.run,
                    ctx.obj['dry_run'], cluster, namespace, kind, name)

import sys
import logging
import click

import utils.config as config
import utils.gql as gql
import e2e_tests.create_namespace
import e2e_tests.dedicated_admin_rolebindings
import e2e_tests.default_network_policies
import e2e_tests.default_project_labels

from utils.aggregated_list import RunnerException


def run_test(func, *args):
    try:
        func(*args)
    except RunnerException as e:
        sys.stderr.write(e.message + "\n")
        sys.exit(1)


@click.group()
@click.option('--config', 'configfile',
              required=True,
              help='Path to configuration file in toml format.')
@click.option('--log-level',
              help='log-level of the command. Defaults to INFO.',
              type=click.Choice([
                  'DEBUG',
                  'INFO',
                  'WARNING',
                  'ERROR',
                  'CRITICAL']))
@click.pass_context
def test(ctx, configfile, log_level):
    ctx.ensure_object(dict)

    level = getattr(logging, log_level) if log_level else logging.INFO
    logging.basicConfig(format='%(levelname)s: %(message)s', level=level)

    config.init_from_toml(configfile)

    gql.init_from_config()


@test.command()
@click.pass_context
def create_namespace(ctx):
    run_test(e2e_tests.create_namespace.run)

@test.command()
@click.pass_context
def dedicated_admin_rolebindings(ctx):
    run_test(e2e_tests.dedicated_admin_rolebindings.run)

@test.command()
@click.pass_context
def default_network_policies(ctx):
    run_test(e2e_tests.default_network_policies.run)

@test.command()
@click.pass_context
def default_project_labels(ctx):
    run_test(e2e_tests.default_project_labels.run)

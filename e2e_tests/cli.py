import logging
import sys

import click

import e2e_tests.create_namespace
import e2e_tests.dedicated_admin_rolebindings
import e2e_tests.default_network_policies
import e2e_tests.default_project_labels
from reconcile.cli import threaded
from reconcile.utils import (
    config,
    gql,
)
from reconcile.utils.aggregated_list import RunnerException


def run_test(func, *args):
    try:
        func(*args)
    except RunnerException as e:
        sys.stderr.write(str(e) + "\n")
        sys.exit(1)


@click.group()
@click.option(
    "--config",
    "configfile",
    required=True,
    help="Path to configuration file in toml format.",
)
@click.option(
    "--log-level",
    help="log-level of the command. Defaults to INFO.",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]),
)
@click.option(
    "--dry-run/--no-dry-run",
    "dry_run",
    default=False,
    help="Only print the planned actions if `true`",
)
@click.pass_context
def test(ctx, configfile, log_level, dry_run):
    ctx.ensure_object(dict)

    level = getattr(logging, log_level) if log_level else logging.INFO
    logging.basicConfig(format="%(levelname)s: %(message)s", level=level)

    ctx.obj["dry_run"] = dry_run

    config.init_from_toml(configfile)

    gql.init_from_config()


@test.command()
@threaded()
@click.pass_context
def create_namespace(ctx, thread_pool_size):
    run_test(e2e_tests.create_namespace.run, thread_pool_size, ctx.obj["dry_run"])


@test.command()
@threaded()
@click.pass_context
def dedicated_admin_rolebindings(ctx, thread_pool_size):
    run_test(e2e_tests.dedicated_admin_rolebindings.run, thread_pool_size)


@test.command()
@threaded()
@click.pass_context
def default_network_policies(ctx, thread_pool_size):
    run_test(e2e_tests.default_network_policies.run, thread_pool_size)


@test.command()
@threaded()
@click.pass_context
def default_project_labels(ctx, thread_pool_size):
    run_test(e2e_tests.default_project_labels.run, thread_pool_size)

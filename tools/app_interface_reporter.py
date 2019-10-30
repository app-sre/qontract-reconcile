import click

from reconcile.cli import (config_file,
                           log_level,
                           dry_run,
                           init_log_level)

import utils.config as config
import utils.gql as gql


@click.command()
@config_file
@dry_run
@log_level
def main(configfile, dry_run, log_level):
    config.init_from_toml(configfile)
    init_log_level(log_level)
    config.init_from_toml(configfile)
    gql.init_from_config()

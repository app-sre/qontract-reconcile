import click

from reconcile.cli import config_file, log_level, dry_run


@click.command()
@config_file
@dry_run
@log_level
def main(configfile, dry_run, log_level):
    print('app-interface-exporter')

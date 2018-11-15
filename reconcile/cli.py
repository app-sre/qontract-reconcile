import click

import reconcile.config as config
import reconcile.gql as gql
import reconcile.github_org

services = {
    'github': reconcile.github_org
}


@click.command()
@click.option('--config', 'configfile',
              required=True,
              help='Path to configuration file in toml format.')
@click.option('--dry-run/--no-dry-run',
              default=False,
              help='If true, only print the planned actions that would be'
                   'performed, without executing them it.')
@click.argument('service', type=click.Choice(services.keys()))
def main(configfile, dry_run, service):
    config.init_from_toml(configfile)
    gql.init_from_config()

    services[service].run(dry_run)


if __name__ == "__main__":
    main()

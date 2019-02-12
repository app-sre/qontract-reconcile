import sys
import logging

import click

import reconcile.config as config
import reconcile.gql as gql
import reconcile.github_org
import reconcile.openshift_rolebinding
import reconcile.quay_membership
import reconcile.quay_repos
import reconcile.ldap_users

from reconcile.aggregated_list import RunnerException

services = {
    'github': reconcile.github_org,
    'openshift-rolebinding': reconcile.openshift_rolebinding,
    'quay-membership': reconcile.quay_membership,
    'quay-repos': reconcile.quay_repos,
    'ldap-users': reconcile.ldap_users,
}


@click.command()
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
@click.argument('service', type=click.Choice(services.keys()))
def main(configfile, dry_run, log_level, service):
    level = getattr(logging, log_level) if log_level else logging.INFO
    logging.basicConfig(format='%(levelname)s:%(message)s', level=level)

    config.init_from_toml(configfile)

    gql.init_from_config()

    try:
        services[service].run(dry_run)
    except RunnerException as e:
        sys.stderr.write(e.message + "\n")
        sys.exit(1)


if __name__ == "__main__":
    main()

import sys
import logging
import reconcile.queries as queries

QONTRACT_INTEGRATION = 'integrations-validator'


def run(dry_run, integration_commands):
    desired_integrations = [i['name'] for i in queries.get_integrations()]

    missing = set(integration_commands) - set(desired_integrations)

    for integration in missing:
        logging.info(['missing_integration', integration])

    if missing:
        sys.exit(1)

import base64
import logging
import semver
import sys

import utils.gql as gql
import reconcile.openshift_resources as openshift_resources
import utils.vault_client as vault_client
import utils.smtp_client as smtp_client

from utils.config import get_config
from utils.openshift_resource import OpenshiftResource, ResourceInventory
from utils.prometheus_alertmanager import Alertmanager
from utils.prometheus_alertmanager import Route, RouteMatcher, Receiver

from multiprocessing.dummy import Pool as ThreadPool
from functools import partial


QUERY = """
{
    alertmanagers: alertmanager_v1 {
        name
        config {
            path
        }
        app {
            namespaces {
                name
                cluster {
                    name
                    serverUrl
                    automationToken {
                        path
                        field
                        format
                    }
                }
            }
        }
        managedApps {
            name
            escalations {
                name
                aliases
                recipients {
                    email
                    slack
                    pagerduty {
                        path
                        field
                        format
                    }
                    webhook
                }
            }
        }
    }
}
"""

QONTRACT_INTEGRATION = 'prometheus_alertmanager'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 0, 1)

DEFAULT_SLACK_ACTIONS = [
    {
        'type': 'button',
        'text': 'Runbook :green_book:',
        'url': '{{ (index .Alerts 0).Annotations.runbook }}'
    },
    {
        'type': 'button',
        'text': 'Query :mag:',
        'url': '{{ (index .Alerts 0).GeneratorURL }}'
    },
    {
        'type': 'button',
        'text': 'Dashboard :grafana:',
        'url': '{{ (index .Alerts 0).Annotations.dashboard }}'
    },
    {
        'type': 'button',
        'text': 'Silence :no_bell:',
        'url': '{{ template "__alert_silence_link" . }}'
    },
    {
        'type': 'button',
        'text': '{{ template "slack.default.link_button_text" . }}',
        'url': '{{ .CommonAnnotations.link_url }}'
    },
]


class NoDataFound(Exception):
    def __init__(self):
        super(NoDataFound, self).__init__(
            "No data found in graphql"
        )


def populate_oc_resources(spec, ri):
    for item in spec.oc.get_items(spec.resource,
                                  namespace=spec.namespace):
        openshift_resource = OpenshiftResource(item,
                                               QONTRACT_INTEGRATION,
                                               QONTRACT_INTEGRATION_VERSION)
        ri.add_current(
            spec.cluster,
            spec.namespace,
            spec.resource,
            openshift_resource.name,
            openshift_resource
        )


def fetch_current_state(namespaces, thread_pool_size):
    ri = ResourceInventory()
    oc_map = {}
    state_specs = \
        openshift_resources.init_specs_to_fetch(
            ri,
            oc_map,
            namespaces,
            override_managed_types=['Secret']
        )

    pool = ThreadPool(thread_pool_size)
    populate_oc_resources_partial = \
        partial(populate_oc_resources, ri=ri)
    pool.map(populate_oc_resources_partial, state_specs)

    return ri, oc_map


def get_graphql_data(query):
    """
    Get data from GraphQL
    """
    gqlapi = gql.get_api()
    res = gqlapi.query(query)

    return res


def get_vault_data(path, version=None):
    """
    Get data from vault
    """
    try:
        data = vault_client.read_all_v2(path, version)
        return data
    except vault_client.SecretVersionNotFound:
        return None


def gen_recipient_name(*args):
    """
    Generates a recipient name from a list of strings

    Blacklists some characters from the resulting string
    """
    blacklist = ""
    recname = args[0]

    for arg in args[1:]:
        recname += "__" + arg

    recname = ''.join('-' if c in blacklist else c for c in recname)

    return recname


def populate_recipient(config, rec, recipient_type, recipient):
    if recipient_type == 'email':
        rec.add_email_config({
            'to': recipient,
            'headers': {
                'From': config['smtp_from'],
                'To': recipient,
                'Subject':
                    '{{ template "email.default.subject" . }}',
            },
            'html': '{{ template "email.default.html" . }}',
            'send_resolved': True,
        })
    elif recipient_type == 'pagerduty':
        pd_data = get_vault_data(recipient['path'])
        rec.add_pagerduty_config({
            'service_key': pd_data[recipient['field']],
            'send_resolved': True,
        })
    elif recipient_type == 'slack':
        rec.add_slack_config({
            'channel': recipient,
            'send_resolved': True,
        })
    elif recipient_type == 'webhook':
        rec.add_webhook_config({
            'url': recipient,
            'send_resolved': True,
        })


def massage_data(data):
    alertmanagers = []
    namespaces = []
    secrets = []
    has_errors = False

    if not isinstance(alertmanagers, list):
        return [], [], []

    # Get SMTP configs from vault
    qconfig = get_config()
    smtp_config = smtp_client.config_from_vault(qconfig['smtp']['secret_path'])

    for alertmanager in data['alertmanagers']:
        # Get integration config from vault
        config = get_vault_data(alertmanager['config']['path'])

        # Alertmanager config
        am = Alertmanager(alertmanager['name'])

        # Global configs
        am.set_global('resolve_timeout', '5m')
        am.set_global('slack_api_url', config['slack_api_url'])

        # Global smtp configs
        am.set_global('smtp_auth_username', smtp_config['username'])
        am.set_global('smtp_auth_identity', smtp_config['username'])
        am.set_global('smtp_auth_password', smtp_config['password'])
        am.set_global('smtp_from', smtp_config['username'])
        am.set_global('smtp_smarthost', "{}:{}".format(
            smtp_config['server'],
            smtp_config['port']))
        if smtp_config['require_tls'].lower() == 'true':
            am.set_global('smtp_require_tls', True)
        else:
            am.set_global('smtp_require_tls', False)

        default_receiver_name = config['default_receiver_name']
        default_slack_channel = config['default_slack_channel']

        # Default receiver for unmatched routes
        rec = Receiver(default_receiver_name).add_slack_config({
            'channel': default_slack_channel,
            'actions': DEFAULT_SLACK_ACTIONS,
        })
        am.add_receiver(rec)

        # Default route
        am.set_default_route(default_receiver_name,
                             group_by=['job', 'cluster', 'service'],
                             group_wait='30s',
                             group_interval='5m',
                             repeat_interval='24h')

        am.add_inhibit_rule({
            'source_match': {
                'severity': 'critical',
            },
            'target_match': {
                'severity': 'medium',
            },
            'equal': [
                "alertname",
                "cluster",
                "service",
            ]
        })

        am.add_template('/etc/alertmanager/config/*.tmpl')
        am.add_template('/etc/alertmanager/configmaps/templates/*.tmpl')

        for app in alertmanager['managedApps']:
            if not app['escalations']:
                logging.warn("Application {} has no escalations!".format(
                    app['name']))
                app['escalations'] = dict()

            routes = []

            for escalation in app['escalations']:
                # If we have a list of aliases, use them
                if 'aliases' in escalation and escalation['aliases']:
                    sevs = [escalation['name']] + escalation['aliases']
                else:
                    sevs = escalation['name']

                matcher = RouteMatcher('severity', sevs)

                recipient_name = "{}-{}".format(app['name'],
                                                escalation['name'])

                new_receiver = Receiver(recipient_name)
                for rec_type, recipients in escalation['recipients'].items():
                    for rec in recipients or []:
                        populate_recipient(config,
                                           new_receiver,
                                           rec_type,
                                           rec)

                am.add_receiver(new_receiver)

                route = Route(recipient_name, matcher=matcher, __continue=True)
                routes.append(route.config)

            am.add_route(default_receiver_name,
                         match={'service': app['name']},
                         routes=routes)

        # Get namespace on which we will apply the configs
        for alertmanager in data['alertmanagers']:
            for namespace in alertmanager['app']['namespaces']:
                if namespace['name'] == config['target_namespace'] and \
                   namespace['cluster']['name'] == config['target_cluster']:
                    namespaces.append(namespace)

        # Generate secret
        body = {
            "apiVersion": "v1",
            "kind": "Secret",
            "type": "Opaque",
            "metadata": {
                    "name": config['target_secret'],
            },
            "data": {
                'alertmanager.yml': base64.b64encode(am.config())
            }
        }
        secrets.append({
            'secret': OpenshiftResource(body,
                                        QONTRACT_INTEGRATION,
                                        QONTRACT_INTEGRATION_VERSION),
            'target_cluster': config['target_cluster'],
            'target_namespace': config['target_namespace'],
            'target_secret': config['target_secret'],
        })

        alertmanagers.append(am)

    return alertmanagers, namespaces, secrets, has_errors


def run(dry_run=False, thread_pool_size=10,
        show_routing_tree=False, show_config=False):

    has_errors = False

    # Fetch data from GraphQL
    gqldata = get_graphql_data(QUERY)

    if 'alertmanagers' not in gqldata or len(gqldata['alertmanagers']) == 0:
        raise(Exception("no alertmanagers instances were found"))

    alertmanagers, namespaces, secrets, has_errors = massage_data(gqldata)

    if show_routing_tree:
        for am in alertmanagers:
            print
            print("##### {} #####".format(am.name))
            print(am.routing_tree())
        sys.exit(0)

    if show_config:
        for am in alertmanagers:
            print
            print("##### {} #####".format(am.name))
            print(am.config())
        sys.exit(0)

    if has_errors:
        sys.exit(1)

    # Build state map
    ri, oc_map = fetch_current_state(namespaces, thread_pool_size)

    # Add desired secrets state
    for secret in secrets:
        ri.add_desired(secret['target_cluster'],
                       secret['target_namespace'],
                       'Secret',
                       secret['target_secret'],
                       secret['secret'])

    openshift_resources.realize_data(dry_run, oc_map, ri, False)

    if ri.has_error_registered():
        sys.exit(1)

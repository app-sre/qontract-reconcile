import base64
import logging
import semver
import re
import sys

import utils.gql as gql
import reconcile.openshift_resources as openshift_resources
import utils.vault_client as vault_client
from utils.config import get_config

from utils.openshift_resource import OpenshiftResource, ResourceInventory
from utils.prometheus_alertmanager import Alertmanager, Route, RouteMatcher

from multiprocessing.dummy import Pool as ThreadPool
from functools import partial


QUERY = """
{
    apps: apps_v1 {
        name
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
        escalations {
            warning {
                aliases
                emailRecipients
                pagerdutyRecipients
                slackRecipients
                webhookRecipients
            }
            critical {
                aliases
                emailRecipients
                pagerdutyRecipients
                slackRecipients
                webhookRecipients
            }
            deadmanssnitch {
                aliases
                emailRecipients
                pagerdutyRecipients
                slackRecipients
                webhookRecipients
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


def get_data(name, query):
    gqlapi = gql.get_api()
    res = gqlapi.query(query)

    if name not in res:
        raise gql.GqlInvalidResponse(
            "{}} key not found in results".format(name))

    data = res[name]
    if not len(data) >= 1:
        raise NoDataFound()

    return data


def get_vault_config(path, version=None):
    data = vault_client.read_all_v2(path, version)
    return data


def gen_recipient_name(*args):
    blacklist = ":/"
    recname = args[0]

    for arg in args[1:]:
        recname += "__" + arg

    recname = ''.join('-' if c in blacklist else c for c in recname)

    return recname


def run(dry_run=False, thread_pool_size=10,
        show_routing_tree=False, show_config=False):
    # Get qontract-reconcile config
    qconfig = get_config()

    # Get integration config from vault
    config = get_vault_config(qconfig['alertmanager']['secret_path'])

    # Fetch apps data from GraphQL
    apps = get_data('apps', QUERY)

    # Alertmanager config
    am = Alertmanager()

    am.set_global('resolve_timeout', '5m')

    am.set_global('smtp_auth_username', config['smtp_auth_username'])
    am.set_global('smtp_auth_identity', config['smtp_auth_username'])
    am.set_global('smtp_auth_password', config['smtp_auth_password'])
    am.set_global('smtp_from', config['smtp_from'])
    am.set_global('smtp_smarthost', config['smtp_smarthost'])
    if config['smtp_require_tls'].lower() == 'true':
        am.set_global('smtp_require_tls', True)
    else:
        am.set_global('smtp_require_tls', False)

    am.set_global('slack_api_url', config['slack_api_url'])

    default_receiver_name = config['default_receiver_name']
    default_slack_channel = config['default_slack_channel']

    # Default receiver for unmatched routes
    am.add_slack_receiver(default_receiver_name, params={
        'channel': default_slack_channel,
        'actions': DEFAULT_SLACK_ACTIONS,
    })

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

    for app in apps:
        if not app['escalations']:
            logging.warn("Application {} has no escalations defined!".format(
                app['name']))
            app['escalations'] = dict()

        routes = []
        for sevname, severity in app['escalations'].items():
            # If we have a list of aliases, use them
            if severity['aliases']:
                sevs = [sevname] + severity['aliases']
            else:
                sevs = sevname

            # Create route matcher
            matcher = RouteMatcher('severity', sevs)

            for rectype, recipients in severity.items():
                # Get recipients keys and extract first part of the
                #   recipient key to get a short name for it
                m = re.search('(.+?)Recipients', rectype)
                if not m:
                    continue
                short_rec_type = m.group(1)

                for recipient in recipients or []:
                    if rectype == 'emailRecipients':
                        recname = gen_recipient_name(
                            short_rec_type, app['name'], sevname, recipient
                        )
                        am.add_email_receiver(recname, params={
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
                    elif rectype == 'pagerdutyRecipients':
                        recname = gen_recipient_name(
                            short_rec_type, app['name'], sevname, recipient
                        )
                        am.add_pagerduty_receiver(recname, params={
                            'service_key': config['pagerduty_service_key'],
                            'send_resolved': True,
                        })
                    elif rectype == 'slackRecipients':
                        recname = gen_recipient_name(
                            short_rec_type, app['name'], sevname, recipient
                        )
                        am.add_slack_receiver(recname, params={
                            'channel': recipient,
                            'send_resolved': True,
                        })
                    elif rectype == 'webhookRecipients':
                        recname = gen_recipient_name(
                            short_rec_type, app['name'], sevname
                        )
                        am.add_webhook_receiver(recname, params={
                            'url': recipient,
                            'send_resolved': True,
                        })

                    r = Route(recname, matcher=matcher, __continue=True)
                    routes.append(r.config)

        am.add_route(None, match={'service': app['name']}, routes=routes)

    if show_routing_tree:
        print(am.routing_tree())
        sys.exit(0)

    if show_config:
        print(am.config())
        sys.exit(0)

    # Get namespace on which we will apply the configs
    namespaces = [
        namespace
        for app in apps
        for namespace in app['namespaces']
        if namespace['name'] == config['target_namespace'] and
        namespace['cluster']['name'] == config['target_cluster']
    ]

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
    secret = OpenshiftResource(body,
                               QONTRACT_INTEGRATION,
                               QONTRACT_INTEGRATION_VERSION)

    # Build state map
    ri, oc_map = fetch_current_state(namespaces, thread_pool_size)

    # Apply add desired secret state
    ri.add_desired(config['target_cluster'],
                   config['target_namespace'],
                   'Secret',
                   config['target_secret'],
                   secret)

    openshift_resources.realize_data(dry_run, oc_map, ri, False)

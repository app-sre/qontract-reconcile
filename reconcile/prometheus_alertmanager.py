import copy
import logging
import yaml

import utils.gql as gql
import utils.prometheus_alertmanager as alertmanager


QUERY = """
{
  applications: apps_v1 {
    name
    escalations {
        warning {
            aliases
            emailRecipients
            pagerdutyRecipients
            slackRecipients
        }
        critical {
            aliases
            emailRecipients
            pagerdutyRecipients
            slackRecipients
        }
    }
  }
}
"""

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


class NoApplicationsFound(Exception):
    def __init__(self):
        super(NoApplicationsFound, self).__init__(
            "No applications found"
        )


class InvalidRecipient(Exception):
    pass


def run(generate_default_routes=False, dry_run=False):

    # Default receiver for unmatched services
    blackhole_receiver = alertmanager.SlackReceiver('slack-default-unknown-service').add_slack_config(
        alertmanager.SlackConfig('#sd-app-sre-alerts',
                                actions=DEFAULT_SLACK_ACTIONS))

    # Default route
    default_route = alertmanager.Route(blackhole_receiver.name).group_by(['job','cluster', 'service'])

    # Create config
    config = alertmanager.Config(default_route)
    config.add_receiver(blackhole_receiver)

    config.set_global('smtp_from', 'example@example.com')
    config.set_global('smtp_smarthost', 'smtp.gmail.com:587')
    config.set_global('smtp_require_tls', True)
    config.set_global('slack_api_url', 'https://a.b.c/')

    config.add_inhibit_rule({
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

    config.add_template('/etc/alertmanager/config/*.tmpl')
    config.add_template('/etc/alertmanager/configmaps/templates/*.tmpl')

    # Add default receiver
    receiver_slack_default = alertmanager.SlackReceiver('slack-default')
    receiver_slack_default.add_slack_config(
        alertmanager.SlackConfig('#sd-app-sre-alerts', actions=DEFAULT_SLACK_ACTIONS)
    )
    
    config.add_receiver(receiver_slack_default)

    gqlapi = gql.get_api()
    res = gqlapi.query(QUERY)

    if not 'applications' in res:
        raise gql.GqlInvalidResponse("applications key not found in results")

    if not len(res['applications']) >= 1:
        raise NoApplicationsFound()

    for app in res['applications']:

        if not app['escalations']:
            logging.warn("Application {} has no escalations defined!".format(app['name']))
                
            # TODO: Update schema so these are set on resources by default?
            app['escalations'] = {
                'warning': {
                    'emailRecipients': [],
                    'pagerdutyRecipients': [],
                    'slackRecipients': [],
                },
                'critical': {
                    'emailRecipients': [],
                    'pagerdutyRecipients': [],
                    'slackRecipients': [],
                },
            }

        serviceRoute = alertmanager.Route(receiver_slack_default.name,
                                            group_by=['alertname', 'cluster', 'job', 'service'])
        serviceRoute.set_match('service', app['name'])

        for severity in ('warning', 'critical'):

            severityRoute = alertmanager.Route(receiver_slack_default.name, group_by=['alertname', 'cluster', 'job', 'service'])
            severityRoute.set_match('severity', [severity] + app['escalations'][severity].get('aliases', []))

            # TODO: Don't hardcode, make this dynamic?
            for rectype in ('emailRecipients', 'pagerdutyRecipients', 'slackRecipients'):
                if not app['escalations'][severity][rectype]:
                    continue
                for rec in app['escalations'][severity][rectype]:

                    # TODO: Don't hardcode, make this dynamic?
                    if rectype == 'emailRecipients':
                        emailConfig = alertmanager.EmailConfig(rec)
                        recipient = alertmanager.EmailReceiver("email-{}-{}-{}".format(app['name'], severity, rec)).add_email_config(emailConfig)
                    elif rectype == 'pagerdutyRecipients':
                        pagerdutyConfig = alertmanager.PagerdutyConfig('SERVICEKEY_CHANGEME')
                        recipient = alertmanager.PagerdutyReceiver("pd-{}-{}-{}".format(app['name'], severity, rec)).add_pagerduty_config(pagerdutyConfig)
                    elif rectype == 'slackRecipients':
                        slackConfig = alertmanager.SlackConfig(rec)
                        recipient = alertmanager.SlackReceiver("slack-{}-{}-{}".format(app['name'], severity, rec)).add_slack_config(slackConfig)

                    receiverRoute = alertmanager.Route(recipient.name, __continue=True)
                    severityRoute.add_route(receiverRoute)
                    config.add_receiver(recipient)
                    
            serviceRoute.add_route(severityRoute)

        config.add_route(serviceRoute)

    # TODO: Populate openshift resources instead of print to stdout
    print(config.render())

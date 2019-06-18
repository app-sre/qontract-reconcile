import logging

import utils.gql as gql
import utils.prometheus_alertmanager as am


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
    bh_config = am.SlackConfig('#sd-app-sre-alerts',
                               actions=DEFAULT_SLACK_ACTIONS)
    bh_receiver = am.SlackReceiver('slack-default-unknown-service',
                                   slack_config=bh_config)

    # Default route
    default_route = am.Route(bh_receiver.name,
                             group_by=['job', 'cluster', 'service'])

    # Create config
    config = am.Config(default_route)
    config.add_receiver(bh_receiver)

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
    receiver_slack_default = am.SlackReceiver('slack-default')
    receiver_slack_default.add_slack_config(
        am.SlackConfig('#sd-app-sre-alerts', actions=DEFAULT_SLACK_ACTIONS)
    )

    config.add_receiver(receiver_slack_default)

    gqlapi = gql.get_api()
    res = gqlapi.query(QUERY)

    if 'applications' not in res:
        raise gql.GqlInvalidResponse("applications key not found in results")

    if not len(res['applications']) >= 1:
        raise NoApplicationsFound()

    for app in res['applications']:

        if not app['escalations']:
            logging.warn("Application {} has no escalations defined!".format(
                app['name'])
            )

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

        serviceRoute = am.Route(receiver_slack_default.name,
                                group_by=['alertname',
                                          'cluster',
                                          'job',
                                          'service'])
        serviceRoute.set_match('service', app['name'])

        for severity in ('warning', 'critical'):

            severityRoute = am.Route(receiver_slack_default.name,
                                     group_by=['alertname',
                                               'cluster',
                                               'job',
                                               'service'])
            aliases = app['escalations'][severity].get('aliases', [])
            all_sevs = [severity] + aliases
            severityRoute.set_match('severity', all_sevs)

            # TODO: Don't hardcode, make this dynamic?
            for rectype in ('emailRecipients',
                            'pagerdutyRecipients',
                            'slackRecipients'):
                if not app['escalations'][severity][rectype]:
                    continue
                for rec in app['escalations'][severity][rectype]:

                    # TODO: Don't hardcode, make this dynamic?
                    if rectype == 'emailRecipients':
                        emailConfig = am.EmailConfig(rec)
                        recipient = am.EmailReceiver(
                            "email-{}-{}-{}".format(
                                app['name'], severity, rec
                            ), emailConfig)
                    elif rectype == 'pagerdutyRecipients':
                        pdConfig = am.PagerdutyConfig('SERVICEKEY_CHANGEME')
                        recipient = am.PagerdutyReceiver(
                            "pd-{}-{}-{}".format(
                                app['name'], severity, rec
                            ), pdConfig)
                    elif rectype == 'slackRecipients':
                        slackConfig = am.SlackConfig(rec)
                        recipient = am.SlackReceiver(
                            "slack-{}-{}-{}".format(
                                app['name'], severity, rec
                            ), slackConfig)

                    receiverRoute = am.Route(recipient.name, set_continue=True)
                    severityRoute.add_route(receiverRoute)
                    config.add_receiver(recipient)

            serviceRoute.add_route(severityRoute)

        config.add_route(serviceRoute)

    # TODO: Populate openshift resources instead of print to stdout
    print(config.render())

import json
import semver
import logging
import traceback

import utils.gql as gql
import reconcile.openshift_base as ob
import utils.jsonnet as jsonnet
import utils.template as template

from utils.defer import defer
from utils.openshift_resource import (OpenshiftResource as OR)

SLO_RULES = 'slo-rules.jsonnet.j2'

PERFORMANCE_PARAMETERS_QUERY = """
{
  performance_parameters_v1 {
    labels
    name
    component
    prometheusLabels
    namespace {
      name
      cluster {
        observabilityNamespace {
          name
          cluster {
            name
            serverUrl
            jumpHost {
              hostname
              knownHosts
              user
              port
              identity {
                path
                field
                format
              }
            }
            automationToken {
              path
              field
              format
            }
            disable {
              integrations
            }
          }
        }
        name
        serverUrl
        jumpHost {
          hostname
          knownHosts
          user
          port
          identity {
            path
            field
            format
          }
        }
        automationToken {
          path
          field
          format
        }
        internal
        disable {
          integrations
        }
      }
    }
    sloRules {
      name
      kind
      metric
      percentile
      selectors
      httpStatusLabel
    }
    volume {
      name
      threshold
      rule
      additionalLabels
    }
    availability {
      name
      additionalLabels
      rules {
        latency
        errors
      }
    }
    latency {
      name
      threshold
      rule
      additionalLabels
    }
    errors {
      name
      target
      rule
      additionalLabels
    }
    rawRecording {
      record
      expr
      labels
    }
  }
}
"""

QONTRACT_INTEGRATION = 'openshift-prometheusrules'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def labels_to_selectors(labels):
    return ", ".join(['\'%s="%s"\'' % (k, v) for k, v in labels.items()])


def build_rules_aoa(rules, category):
    return " + ".join(['[%s__%s.rules]' % (r, category) for r in rules])


def generate_resource(template_file, values):
    template_env = template.get_package_environment()
    tpl = template_env.get_template(template_file)
    tpl.globals['labels_to_selectors'] = labels_to_selectors
    tpl.globals['build_rules_aoa'] = build_rules_aoa
    tpl.globals['load_json'] = json.loads
    return OR(jsonnet.generate_object(tpl.render(values)),
              QONTRACT_INTEGRATION,
              QONTRACT_INTEGRATION_VERSION)


def check_data_consistency(pp):
    errors = []

    # check that rule names are unique
    # we'll also use slo_rules in slos validation
    slo_rules = set([r['name'] for r in pp['sloRules']])
    if len(slo_rules) != len(pp['sloRules']):
        errors.append('sloRules names are not unique')

    # percentile is mandatory for latency rates
    for rule in [r for r in pp['sloRules'] if r['kind'] == 'latency_rate']:
        if 'percentile' not in rule:
            errors.append('percentile missing in %s slo rule' % rule['name'])

    # volume, latency, errors => check that rules exist in slo_recordings
    # we'll also use it for the availability validation
    slos = {}
    for category in ['volume', 'latency', 'errors']:
        slos[category] = set([s['name'] for s in pp[category]])

        if len(slos[category]) != len(pp[category]):
            errors.append('slo names are not unique for %s' % category)

        for slx in pp[category]:
            if slx['rule'] not in slo_rules:
                errors.append('Unknown slo rule %s' % slx['rule'])

    # check availability names are unique and slo rules exist
    availability_rule_names = set()
    for slx in pp['availability']:
        availability_rule_names.add(slx['name'])
        for c in ['latency', 'errors']:
            for rule_name in slx['rules'][category]:
                if rule_name not in slos[category]:
                    errors.append('Unknown %s rule %s' % (category,
                                                          rule_name))

    if len(availability_rule_names) != len(pp[category]):
        errors.append('slo names are not unique for %s' % category)

    return errors


# Build params to pass to the template
def build_template_params(pp):
    params = {}
    params['http_rates'] = []     # sloRules of http_rate type
    params['latency_rates'] = []  # sloRules of latency_rate type
    params['all_rules'] = []      # contains the name of each rule.

    # We have checked that rule names are unique by category, but not as whole
    # we will add a suffix to each rule to make sure they're unique
    for r in pp['sloRules']:
        if r['kind'] == 'http_rate':
            params['http_rates'].append(r)
            params['all_rules'].extend(
                ['%s__http_rates.rateRules' % r['name'],
                 '%s__http_rates.errorRateRules' % r['name']])
        else:
            params['latency_rates'].append(r)
            params['all_rules'].append('%s__latency_rates.rules' % r['name'])

    for c in ['volume', 'latency', 'errors', 'availability']:
        params['all_rules'].extend(['%s__%s.rules' % (r['name'], c)
                                    for r in pp[c]])
        params[c] = pp[c]

    params['labels'] = pp['labels']
    params['component'] = pp['component']
    params['namespace'] = pp['namespace']['name']
    params['prometheus_labels'] = pp['prometheusLabels']

    return params


def fetch_desired_state(performance_parameters, ri):
    for pp in performance_parameters['performance_parameters_v1']:
        if pp['namespace']['cluster']['observabilityNamespace'] is None:
            logging.error('No observability namespace for %s' % pp['name'])
            continue

        try:
            errors = check_data_consistency(pp)
            if len(errors) > 0:
                logging.error(
                    'Data inconsistent for %s. Errors detected: %s' % (
                        pp['name'], errors))
                continue

            params = build_template_params(pp)
            rules_resource = generate_resource(SLO_RULES, params)
        except Exception as e:
            logging.error('Error building resource for %s: %s' % (
                pp['name'], e))
            logging.debug(traceback.format_exc())
            continue

        cluster_observability_namespace = \
            pp['namespace']['cluster']['observabilityNamespace']
        ri.add_desired(
            cluster_observability_namespace['cluster']['name'],
            cluster_observability_namespace['name'],
            'PrometheusRule',
            rules_resource.body['metadata']['name'],
            rules_resource)


@defer
def run(dry_run=False, thread_pool_size=10, internal=None,
        use_jump_host=True, defer=None):
    gqlapi = gql.get_api()
    performance_parameters = gqlapi.query(PERFORMANCE_PARAMETERS_QUERY)
    observability_namespaces = [
        pp['namespace']['cluster']['observabilityNamespace']
        for pp in performance_parameters['performance_parameters_v1']
        if pp['namespace']['cluster']['observabilityNamespace'] is not None]

    if len(observability_namespaces) == 0:
        logging.error('No observability namespace matching')
        return

    ri, oc_map = ob.fetch_current_state(
        namespaces=observability_namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=['PrometheusRule'],
        internal=internal,
        use_jump_host=use_jump_host)
    defer(lambda: oc_map.cleanup())
    fetch_desired_state(performance_parameters, ri)
    ob.realize_data(dry_run, oc_map, ri)

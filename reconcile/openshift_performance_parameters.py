import sys
import json
import semver
import logging
import traceback

import utils.jsonnet as jsonnet
import utils.template as template
import reconcile.openshift_base as ob
import reconcile.queries as queries

from utils.defer import defer
from utils.openshift_resource import (OpenshiftResource as OR)

SLO_RULES = 'slo-rules.jsonnet.j2'
QONTRACT_INTEGRATION = 'openshift-performance-parameters'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def labels_to_selectors(labels):
    if isinstance(labels, str):
        labels = json.loads(labels)
    if not labels:
        return ""
    elif isinstance(labels, list):
        return ", ".join([f"'{sel}'" for sel in labels])
    else:
        return ", ".join([f'\'{k}="{v}"\'' for k, v in labels.items()])


def build_rules_aoa(rules, category):
    return " + ".join([f'[{r}__{category}.rules]' for r in rules])


def render_template(template_file, values):
    template_env = template.get_package_environment()
    tpl = template_env.get_template(template_file)
    tpl.globals['labels_to_selectors'] = labels_to_selectors
    tpl.globals['build_rules_aoa'] = build_rules_aoa
    tpl.globals['load_json'] = json.loads
    tpl.globals['dump_json'] = json.dumps

    return tpl.render(values)


def generate_resource(template_file, values):
    rendered = render_template(template_file, values)
    jsonnet_resource = jsonnet.generate_object(rendered)

    return OR(jsonnet_resource,
              QONTRACT_INTEGRATION,
              QONTRACT_INTEGRATION_VERSION)


def check_data_consistency(pp):
    errors = []

    # check that rule names are unique
    # we'll also use sli_rules in slis validation
    sli_rules = set([r['name'] for r in pp['SLIRecordingRules']])
    if len(sli_rules) != len(pp['SLIRecordingRules']):
        errors.append('SLIRecordingRules names are not unique')

    # percentile is mandatory for latency rates
    latency_sli_rules = [r for r in pp['SLIRecordingRules']
                         if r['kind'] == 'latency_rate']
    for rule in latency_sli_rules:
        if 'percentile' not in rule:
            errors.append(f"percentile missing in {rule['name']} sli rule")

    # volume, latency, errors => check that rules exist in sli_recordings
    # we'll also use it for the availability validation
    slis = {}
    for category in ['volume', 'latency', 'errors']:
        slis[category] = set([s['name'] for s in pp[category]])

        if len(slis[category]) != len(pp[category]):
            errors.append(f'sli names are not unique for {category}')

        for slx in pp[category]:
            if slx['rules'] not in sli_rules:
                errors.append(f"Unknown sli rule {slx['rules']}")

    # check availability names are unique and sli rules exist
    availability_rule_names = set()
    for slx in pp['availability']:
        availability_rule_names.add(slx['name'])
        for c in ['latency', 'errors']:
            for rule_name in slx['rules'][category]:
                if rule_name not in slis[category]:
                    errors.append(f'Unknown {category} rule {rule_name}')

    if len(availability_rule_names) != len(pp[category]):
        errors.append(f'sli names are not unique for {category}')

    return errors


def decode_json_labels(raw):
    return [{**r, 'labels': json.loads(r['labels'])} for r in raw]


# Build params to pass to the template
def build_template_params(pp):
    params = {}
    params['http_rates'] = []     # SLIRecordingRules of http_rate type
    params['latency_rates'] = []  # SLIRecordingRules of latency_rate type
    params['all_rules'] = []      # contains the name of each rule.

    # We have checked that rule names are unique by category, but not as whole
    # we will add a suffix to each rule to make sure they're unique
    for r in pp['SLIRecordingRules']:
        if r['kind'] == 'http_rate':
            params['http_rates'].append(r)
            params['all_rules'].extend([
                f"{r['name']}__http_rates.rateRules",
                f"{r['name']}__http_rates.errorRateRules"])
        else:
            params['latency_rates'].append(r)
            params['all_rules'].append(f"{r['name']}__latency_rates.rules")

    for c in ['volume', 'latency', 'errors', 'availability']:
        params['all_rules'].extend([f"{r['name']}__{c}.rules" for r in pp[c]])
        params[c] = pp[c]

    params['labels'] = {**json.loads(pp['labels']),
                        'component': pp['component']}
    params['namespace'] = pp['namespace']['name']
    params['prometheus_labels'] = pp['prometheusLabels']
    params['raw'] = []

    if pp['rawRecordingRules']:
        params['raw'].extend(decode_json_labels(pp['rawRecordingRules']))

    if pp['rawAlerting']:
        params['raw'].extend(decode_json_labels(pp['rawAlerting']))

    return params


def fetch_desired_state(performance_parameters, ri):
    for pp in performance_parameters:
        if pp['namespace']['cluster']['observabilityNamespace'] is None:
            ri.register_error()
            logging.error(f"No observability namespace for {pp['name']}")
            continue

        errors = check_data_consistency(pp)
        if errors:
            ri.register_error()
            logging.error(
                f"Data inconsistent for {pp['name']}. "
                f"Errors detected: {errors}")
            continue

        params = build_template_params(pp)

        try:
            rules_resource = generate_resource(SLO_RULES, params)
        except jsonnet.JsonnetError as e:
            ri.register_error()
            logging.error(f"Error building resource for {pp['name']}: {e}")
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
def run(dry_run, thread_pool_size=10, internal=None,
        use_jump_host=True, defer=None):
    performance_parameters = queries.get_performance_parameters()
    observability_namespaces = [
        pp['namespace']['cluster']['observabilityNamespace']
        for pp in performance_parameters
        if pp['namespace']['cluster']['observabilityNamespace'] is not None]

    if not observability_namespaces:
        logging.error('No observability namespaces found')
        sys.exit(1)

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

    if ri.has_error_registered():
        sys.exit(1)

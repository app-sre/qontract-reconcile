import logging
import semver
import sys
import time
import jinja2
import ruamel.yaml as yaml

from textwrap import indent

from reconcile import openshift_base
from reconcile import queries
from reconcile.status import ExitCodes

from utils import gql
from utils.oc import OC_Map
from utils.oc import StatusCodeError
from utils.state import State
from utils.openshift_resource import OpenshiftResource


QONTRACT_INTEGRATION = 'sql-query'
QONTRACT_INTEGRATION_VERSION = semver.format_version(1, 1, 0)

LOG = logging.getLogger(__name__)

JOB_TTL = 604800  # 7 days
POD_TTL = 3600  # 1 hour (used only when output is "filesystem")

JOB_SPEC = """
spec:
  template:
    metadata:
      name: {{ JOB_NAME }}
    spec:
      containers:
      - name: {{ JOB_NAME }}
        image: quay.io/app-sre/{{ ENGINE }}:{{ENGINE_VERSION}}
        command:
          - /bin/bash
        args:
          - '-c'
          - '{{ COMMAND }}'
        env:
          {% for key, value in DB_CONN.items() %}
          {% if value is none %}
          # When value is not provided, we get it from the secret
          - name: {{ key }}
            valueFrom:
              secretKeyRef:
                name: {{ SECRET_NAME }}
                key: {{ key }}
          {% else %}
          # When value is provided, we get just use it
          - name: {{ key }}
            value: {{ value }}
          {% endif %}
          {% endfor %}
      restartPolicy: Never
"""


JOB_TEMPLATE = """
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ JOB_NAME }}
%s
""" % (JOB_SPEC)


CRONJOB_TEMPLATE = """
apiVersion: batch/v1beta1
kind: CronJob
metadata:
  name: {{ JOB_NAME }}
spec:
  schedule: "{{ SCHEDULE }}"
  concurrencyPolicy: "Forbid"
  jobTemplate:
    %s
""" % (indent(JOB_SPEC, 4*' '))


def get_tf_resource_info(namespace, identifier):
    """
    Extracting the terraformResources information from the namespace
    for a given identifier

    :param namespace: the namespace dictionary
    :param identifier: the identifier we are looking for
    :return: the terraform resource information dictionary
    """
    tf_resources = namespace['terraformResources']
    for tf_resource in tf_resources:
        if 'identifier' not in tf_resource:
            continue

        if tf_resource['identifier'] != identifier:
            continue

        if tf_resource['provider'] != 'rds':
            continue

        defaults_ref = gql.get_api().get_resource(tf_resource['defaults'])
        defaults = yaml.safe_load(defaults_ref['content'])

        output_resource_name = tf_resource['output_resource_name']
        if output_resource_name is None:
            output_resource_name = (f'{tf_resource["identifier"]}-'
                                    f'{tf_resource["provider"]}')

        return {
            'cluster': namespace['cluster']['name'],
            'output_resource_name': output_resource_name,
            'engine': defaults.get('engine', 'postgres'),
            'engine_version': defaults.get('engine_version', 'latest'),
        }


def collect_queries(query_name=None):
    """
    Consults the app-interface and constructs the list of queries
    to be executed.

    :param query_name: (optional) query to look for

    :return: List of queries dictionaries
    """
    queries_list = []

    # Items to be either overridden ot taken from the k8s secret
    db_conn_items = {'db.host': None,
                     'db.name': None,
                     'db.password': None,
                     'db.port': None,
                     'db.user': None}

    sql_queries = queries.get_app_interface_sql_queries()

    for sql_query in sql_queries:
        name = sql_query['name']

        for existing in queries_list:
            if existing['name'] == name:
                logging.error(['SQL-Query %s defined more than once'],
                              name)
                sys.exit(ExitCodes.ERROR)

        # Looking for a specific query
        if query_name is not None:
            if name != query_name:
                continue

        namespace = sql_query['namespace']
        identifier = sql_query['identifier']

        # Due to an API limitation, the keys are coming with underscore
        # instead of period, so we are using this unpacking routine
        # to also replace "_" by "." in the keys
        if sql_query['overrides'] is not None:
            overrides = {key.replace('_', '.'): value
                         for key, value in sql_query['overrides'].items()
                         if value is not None}
        else:
            overrides = {}

        # Merging the overrides. Values that are still None after this
        # will be taken from the k8s secret on template rendering
        db_conn = {**db_conn_items, **overrides}

        # Output can be:
        # - stdout
        # - filesystem
        output = sql_query['output']
        if output is None:
            output = 'stdout'

        # Extracting the terraformResources information from the namespace
        # fo the given identifier
        tf_resource_info = get_tf_resource_info(namespace,
                                                identifier)
        if tf_resource_info is None:
            logging.error(
                ['Could not find rds identifier %s in namespace %s'],
                identifier, namespace['name']
            )
            sys.exit(ExitCodes.ERROR)

        # building up the final query dictionary
        item = {
            'name': name,
            'namespace': namespace,
            'identifier': sql_query['identifier'],
            'db_conn': db_conn,
            'output': output,
            'query': sql_query['query'].replace("'", "''"),
            **tf_resource_info,
        }

        # If schedule is defined
        # this should be a CronJob
        schedule = sql_query.get('schedule')
        if schedule:
            item['schedule'] = schedule

        queries_list.append(item)

    return queries_list


def make_postgres_command(output, query):
    command = [
        'time psql',
        'postgres://$(db.user):$(db.password)@'
        '$(db.host):$(db.port)/$(db.name)',
        f'--command "{query}"',
    ]

    if output == 'filesystem':
        command.extend(filesystem_extra_command())

    return ' '.join(command)


def make_mysql_command(output, query):
    command = [
        'time mysql',
        '--host=$(db.host)',
        '--port=$(db.port)',
        '--database=$(db.name)',
        '--user=$(db.user)',
        '--password=$(db.password)',
        f'--execute="{query}"',
    ]

    if output == 'filesystem':
        command.extend(filesystem_extra_command())

    return ' '.join(command)


def filesystem_extra_command():
    return [
        '> /tmp/query-result.txt;',
        'echo;',
        'echo Get the sql-query results with:;',
        'echo;',
        'echo  oc rsh --shell=/bin/bash ${HOSTNAME} ',
        'cat /tmp/query-result.txt;',
        'echo;',
        f'echo Sleeping {POD_TTL}s...;',
        f'sleep {POD_TTL};',
    ]


def process_template(query):
    """
    Renders the Jinja2 Job Template.

    :param query: the query dictionary containing the parameters
                  to be used in the Template
    :return: rendered Job YAML
    """
    engine_cmd_map = {'postgres': make_postgres_command,
                      'mysql': make_mysql_command}

    engine = query['engine']
    if engine not in engine_cmd_map:
        raise RuntimeError(f'Engine {engine} not supported')

    supported_outputs = ['stdout', 'filesystem']
    output = query['output']
    if output not in supported_outputs:
        raise RuntimeError(f'Output {output} not supported')

    make_command = engine_cmd_map[engine]

    command = make_command(output=output,
                           query=query['query'])

    template_to_render = JOB_TEMPLATE
    render_kwargs = {
        'JOB_NAME': query['name'],
        'QUERY': query['query'],
        'SECRET_NAME': query['output_resource_name'],
        'ENGINE': engine,
        'ENGINE_VERSION': query['engine_version'],
        'DB_CONN': query['db_conn'],
        'COMMAND': command
    }
    schedule = query.get('schedule')
    if schedule:
        template_to_render = CRONJOB_TEMPLATE
        render_kwargs['SCHEDULE'] = schedule

    template = jinja2.Template(template_to_render)
    job_yaml = template.render(**render_kwargs)
    return job_yaml


def run(dry_run, enable_deletion=False):
    settings = queries.get_app_interface_settings()
    accounts = queries.get_aws_accounts()
    state = State(integration=QONTRACT_INTEGRATION,
                  accounts=accounts,
                  settings=settings)

    queries_list = collect_queries()
    remove_candidates = []
    for query in queries_list:
        query_name = query['name']

        # Checking the sql-query state:
        # - No state: up for execution.
        # - State is a timestamp: executed and up for removal
        #   after the JOB_TTL
        # - State is 'DONE': executed and removed.
        try:
            query_state = state[query_name]
            is_cronjob = query.get('schedule')
            if query_state != 'DONE' and not is_cronjob:
                remove_candidates.append({'name': query_name,
                                          'timestamp': query_state})
            continue
        except KeyError:
            pass

        job_yaml = process_template(query)
        job = yaml.safe_load(job_yaml)
        job_resource = OpenshiftResource(job, QONTRACT_INTEGRATION,
                                         QONTRACT_INTEGRATION_VERSION)
        oc_map = OC_Map(namespaces=[query['namespace']],
                        integration=QONTRACT_INTEGRATION,
                        settings=queries.get_app_interface_settings(),
                        internal=None)

        openshift_base.apply(dry_run=dry_run,
                             oc_map=oc_map,
                             cluster=query['cluster'],
                             namespace=query['namespace']['name'],
                             resource_type=job_resource.kind,
                             resource=job_resource,
                             wait_for_namespace=False)

        if not dry_run:
            state[query_name] = time.time()

    for candidate in remove_candidates:
        if time.time() < candidate['timestamp'] + JOB_TTL:
            continue

        try:
            query = collect_queries(query_name=candidate['name'])[0]
        except IndexError:
            raise RuntimeError(f'sql-query {candidate["name"]} not present'
                               f'in the app-interface while its Job is still '
                               f'not removed from the cluster. Manual clean '
                               f'up is needed.')

        oc_map = OC_Map(namespaces=[query['namespace']],
                        integration=QONTRACT_INTEGRATION,
                        settings=queries.get_app_interface_settings(),
                        internal=None)

        try:
            openshift_base.delete(dry_run=dry_run,
                                  oc_map=oc_map,
                                  cluster=query['cluster'],
                                  namespace=query['namespace']['name'],
                                  resource_type='job',
                                  name=query['name'],
                                  enable_deletion=enable_deletion)
        except StatusCodeError:
            LOG.exception("Error removing ['%s' '%s' 'job' '%s']",
                          query['cluster'], query['namespace']['name'],
                          query['name'])

        if not dry_run:
            state[candidate['name']] = 'DONE'

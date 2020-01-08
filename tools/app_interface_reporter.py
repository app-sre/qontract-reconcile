import json
import logging
import os
import textwrap

from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from functools import lru_cache

import click
import requests
import yaml

import utils.gql as gql
import utils.config as config
import utils.secret_reader as secret_reader
import reconcile.queries as queries
import reconcile.pull_request_gateway as prg
import reconcile.jenkins_plugins as jenkins_base

from reconcile.jenkins_job_builder import init_jjb
from reconcile.cli import (
    config_file,
    log_level,
    dry_run,
    init_log_level,
    gitlab_project_id
)

CONTENT_FORMAT_VERSION = '1.0.0'


def promql(url, query, auth=None):
    """
    Run an instant-query on the prometheus instance.

    The returned structure is documented here:
    https://prometheus.io/docs/prometheus/latest/querying/api/#instant-queries

    :param url: base prometheus url (not the API endpoint).
    :type url: string
    :param query: this is a second value
    :type query: string
    :param auth: auth object
    :type auth: requests.auth
    :return: structure with the metrics
    :rtype: dictionary
    """

    url = os.path.join(url, 'api/v1/query')

    if auth is None:
        auth = {}

    params = {'query': query}

    response = requests.get(url, params=params, auth=auth)

    response.raise_for_status()
    response = response.json()

    # TODO ensure len response == 1
    return response['data']['result']


class Report(object):
    def __init__(self, app, date):
        # standard date format
        if hasattr(date, 'strftime'):
            date = date.strftime('%Y-%m-%d')

        self.app = app
        self.date = date
        self.report_sections = {}

        # valet
        self.add_report_section('valet', self.slo_section())

        # promotions
        self.add_report_section(
            'production_promotions',
            self.get_activity_content(self.app.get('promotions'))
        )

        # merges to master
        self.add_report_section(
            'merges_to_master',
            self.get_activity_content(self.app.get('merge_activity'))
        )

    @property
    def path(self):
        return 'data/reports/{}/{}.yml'.format(
            self.app['name'],
            self.date
        )

    def content(self):
        return {
            '$schema': '/app-sre/report-1.yml',
            'labels': {'app': self.app['name']},
            'name': self.app['name'],
            'app': {'$ref': self.app['path']},
            'date': self.date,
            'contentFormatVersion': CONTENT_FORMAT_VERSION,
            'content': yaml.safe_dump(self.report_sections, sort_keys=False)
        }

    def to_yaml(self):
        return yaml.safe_dump(self.content(), sort_keys=False)

    def to_message(self):
        return {
            'file_path': self.path,
            'content': self.to_yaml()
        }

    def add_report_section(self, header, content):
        if not content:
            content = None

        self.report_sections[header] = content

    def slo_section(self):
        performance_parameters = [
            pp for pp in get_performance_parameters()
            if pp['app']['path'] == self.app['path']
        ]

        metrics_availability = self.get_performance_metrics(
            performance_parameters,
            self.calculate_performance_availability,
            'availability'
        )

        metrics_latency = self.get_performance_metrics(
            performance_parameters,
            self.calculate_performance_latency,
            'latency'
        )

        metrics = [
            *metrics_availability,
            *metrics_latency
        ]

        if not metrics:
            return None

        return metrics

    def get_performance_metrics(self, performance_parameters, method, field):
        return [
            method(pp['component'], ns, metric)
            for pp in performance_parameters
            for ns in pp['namespaces']
            for metric in pp.get(field, [])
            if metric['kind'] == 'SLO'
            if ns['cluster']['prometheus']
        ]

    def calculate_performance_availability(self, component, ns, metric):
        metric_selectors = json.loads(metric['selectors'])
        metric_name = metric['metric']

        settings = queries.get_app_interface_settings()
        prom_info = ns['cluster']['prometheus']
        prom_auth_creds = secret_reader.read(prom_info['auth'], settings)
        prom_auth = requests.auth.HTTPBasicAuth(*prom_auth_creds.split(':'))

        # volume
        vol_selectors = metric_selectors.copy()
        vol_selectors['namespace'] = ns['name']

        prom_vol_selectors = self.promqlify(vol_selectors)
        vol_promql_query = (f"sum(increase({metric_name}"
                            f"{{{prom_vol_selectors}}}[30d]))")

        vol_promql_query_result = promql(
            prom_info['url'],
            vol_promql_query,
            auth=prom_auth,
        )

        if len(vol_promql_query_result) != 1:
            logging.error(("unexpected promql result:\n"
                           f"url: {prom_info['url']}\n"
                           f"query: {vol_promql_query}"))
            return None

        volume = int(float(vol_promql_query_result[0]['value'][1]))

        # availability
        avail_selectors = metric_selectors.copy()
        avail_selectors['namespace'] = ns['name']
        prom_avail_selectors = self.promqlify(avail_selectors)

        avail_promql_query = f"""
        sum(increase(
            {metric_name}{{{prom_avail_selectors}, code!~"5.."}}[30d]
            ))
            /
        sum(increase(
            {metric_name}{{{prom_avail_selectors}}}[30d]
            )) * 100
        """

        avail_promql_query_result = promql(
            prom_info['url'],
            avail_promql_query,
            auth=prom_auth,
        )

        if len(avail_promql_query_result) != 1:
            logging.error(("unexpected promql result:\n"
                           f"url: {prom_info['url']}\n"
                           f"query: {avail_promql_query}"))

            return None

        availability = float(avail_promql_query_result[0]['value'][1])
        target_slo = 100 - float(metric['errorBudget'])

        availability_slo_met = availability >= target_slo

        return {
            'component': component,
            'type': 'availability',
            'selectors': self.promqlify(metric_selectors),
            'total_requests': volume,
            'availability': round(availability, 2),
            'availability_slo_met': availability_slo_met,
        }

    def calculate_performance_latency(self, component, ns, metric):
        metric_selectors = json.loads(metric['selectors'])
        metric_name = metric['metric']

        selectors = metric_selectors.copy()
        selectors['namespace'] = ns['name']

        settings = queries.get_app_interface_settings()
        prom_info = ns['cluster']['prometheus']
        prom_auth_creds = secret_reader.read(prom_info['auth'], settings)
        prom_auth = requests.auth.HTTPBasicAuth(*prom_auth_creds.split(':'))

        percentile = float(metric['percentile']) / 100

        prom_selectors = self.promqlify(selectors)
        promql_query = f"""
            histogram_quantile({percentile},
                sum by (le) (increase(
                    {metric_name}{{
                        {prom_selectors}, code!~"5.."
                    }}[30d]))
            )
        """

        result = promql(
            prom_info['url'],
            promql_query,
            auth=prom_auth,
        )

        if len(result) != 1:
            logging.error(("unexpected promql result:\n"
                           f"url: {prom_info['url']}\n"
                           f"query: {promql_query}"))

            return None

        latency = float(result[0]['value'][1])
        latency_slo_met = latency <= float(metric['threshold'])

        return {
            'component': component,
            'type': 'latency',
            'selectors': self.promqlify(metric_selectors),
            'latency': round(latency, 2),
            'latency_slo_met': latency_slo_met,
        }

    @staticmethod
    def promqlify(selectors):
        return ", ".join([
            f'{k}="{v}"'
            for k, v in selectors.items()
        ])

    @staticmethod
    def get_activity_content(activity):
        if not activity:
            return []

        return [
            {
                "repo": repo,
                "total": int(results[0]),
                "success": int(results[1]),
            }
            for repo, results in activity.items()
        ]


@lru_cache()
def get_performance_parameters():
    query = """
    {
      performance_parameters_v1 {
        path
        name
        component
        namespaces {
          name
          cluster {
            prometheus {
              url
              auth {
                path
                field
              }
            }
          }
        }
        app {
          path
          name
        }
        availability {
          kind
          metric
          errorBudget
          selectors
        }
        latency {
          kind
          metric
          threshold
          percentile
          selectors
        }
      }
    }
    """

    gqlapi = gql.get_api()
    return gqlapi.query(query)['performance_parameters_v1']


def get_apps_data(date, month_delta=1):
    apps = queries.get_apps()
    jjb = init_jjb()
    saas_jobs = jjb.get_all_jobs(job_type='saas-deploy')
    build_master_jobs = jjb.get_all_jobs(job_type='build-master')
    jenkins_map = jenkins_base.get_jenkins_map()
    time_limit = date - relativedelta(months=month_delta)
    timestamp_limit = \
        int(time_limit.replace(tzinfo=timezone.utc).timestamp())
    saas_build_history = \
        get_build_history(jenkins_map, saas_jobs, timestamp_limit)
    build_master_build_history = \
        get_build_history(jenkins_map, build_master_jobs, timestamp_limit)

    for app in apps:
        if not app['codeComponents']:
            continue

        app_name = app['name']
        logging.info(f"collecting promotions for {app_name}")
        app['promotions'] = {}
        saas_repos = [c['url'] for c in app['codeComponents']
                      if c['resource'] == 'saasrepo']
        for sr in saas_repos:
            sr_history = saas_build_history.get(sr)
            if not sr_history:
                continue
            successes = [h for h in sr_history if h == 'SUCCESS']
            app['promotions'][sr] = (len(sr_history), len(successes))

        logging.info(f"collecting merge activity for {app_name}")
        app['merge_activity'] = {}
        code_repos = [c['url'] for c in app['codeComponents']
                      if c['resource'] == 'upstream']
        for cr in code_repos:
            cr_history = build_master_build_history.get(cr)
            if not cr_history:
                continue
            successes = [h for h in cr_history if h == 'SUCCESS']
            app['merge_activity'][cr] = (len(cr_history), len(successes))

    return apps


def get_build_history(jenkins_map, jobs, timestamp_limit):
    history = {}
    for instance, jobs in jobs.items():
        jenkins = jenkins_map[instance]
        for job in jobs:
            logging.info(f"getting build history for {job['name']}")
            build_history = \
                jenkins.get_build_history(job['name'], timestamp_limit)
            repo_url = get_repo_url(job)
            history[repo_url] = build_history

    return history


def get_repo_url(job):
    repo_url_raw = job['properties'][0]['github']['url']
    return repo_url_raw.strip('/').replace('.git', '')


@click.command()
@config_file
@dry_run
@log_level
# TODO: @environ(['gitlab_pr_submitter_queue_url'])
@gitlab_project_id
@click.option('--reports-path', help='path to write reports')
def main(configfile, dry_run, log_level, gitlab_project_id, reports_path):
    config.init_from_toml(configfile)
    init_log_level(log_level)
    config.init_from_toml(configfile)
    gql.init_from_config()

    now = datetime.now()
    apps = get_apps_data(now)

    reports = [Report(app, now).to_message() for app in apps]

    for report in reports:
        logging.info(['create_report', report['file_path']])

        if reports_path:
            report_file = os.path.join(reports_path, report['file_path'])

            try:
                os.makedirs(os.path.dirname(report_file))
            except FileExistsError:
                pass

            with open(report_file, 'w') as f:
                f.write(report['content'])

    if not dry_run:
        email_schema = '/app-interface/app-interface-email-1.yml'
        email_body = """\
            Hello,

            A new report by the App SRE team is now available at:
            https://visual-app-interface.devshift.net/reports

            You can use the Search bar to search by App.

            You can also view reports per service here:
            https://visual-app-interface.devshift.net/services


            Having problems? Ping us on #sd-app-sre on Slack!
            """
        gw = prg.init(gitlab_project_id=gitlab_project_id,
                      override_pr_gateway_type='gitlab')
        mr = gw.create_app_interface_reporter_mr(
            reports, email_schema, textwrap.dedent(email_body), reports_path)
        logging.info(['created_mr', mr.web_url])

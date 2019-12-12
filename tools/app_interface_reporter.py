import json
import logging
import textwrap

from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from functools import lru_cache

import click
import requests
import yaml

import utils.gql as gql
import utils.config as config
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


class Report(object):
    def __init__(self, app, date):
        # standard date format
        if hasattr(date, 'strftime'):
            date = date.strftime('%Y-%m-%d')

        self.app = app
        self.date = date
        self.report_sections = []

        # slo
        self.add_report_section('SLOs', self.slo_section())

        # promotions
        self.add_report_section(
            'Number of Production Promotions',
            self.get_activity_content(self.app.get('promotions'))
        )

        # merges to master
        self.add_report_section(
            'Number of Merges to Master',
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
            'content': "\n\n".join(self.report_sections),
        }

    def to_yaml(self):
        return yaml.safe_dump(self.content())

    def to_message(self):
        return {
            'file_path': self.path,
            'content': self.to_yaml()
        }

    def add_report_section(self, header, content):
        if not content:
            content = 'No data.'
        else:
            content = content.strip()

        self.report_sections.append(f"# {header}\n\n{content}")

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

        return yaml.safe_dump(metrics, sort_keys=False)

    def get_performance_metrics(self, performance_parameters, method, field):
        return [
            method(pp['component'], ns['name'], metric)
            for pp in performance_parameters
            for ns in pp['namespaces']
            for metric in pp.get(field, [])
            if metric['kind'] == 'SLO'
        ]

    def calculate_performance_availability(self, component, ns, metric):
        prom_metric_availability = ("errorbudget:status_code:"
                                    f"{metric['metric']}:increase30d:sum")

        selectors = json.loads(metric['selectors'])
        selectors['component'] = component
        selectors['namespace'] = ns

        prom_selector = self.promqlify(selectors)
        promql_query = f"{prom_metric_availability}{{{prom_selector}}}"

        target_slo = 1 - float(metric['errorBudget'])
        # achieved_slo = 1 - (target_slo * remaining_error_budget)
        achieved_slo = 0

        slo_met = True

        return {
            'Component': component,
            'Type': 'availability',
            'Selectors': selectors,
            'Target SLO': f'{target_slo}%',
            'Achieved': f'{achieved_slo}%',
            'Query': promql_query,
            'SLO met': slo_met,
        }

    def calculate_performance_latency(self, component, ns, metric):
        prom_metric_availability = (f"TODO_LATENCY_{metric['metric']}")

        selectors = json.loads(metric['selectors'])
        selectors['component'] = component
        selectors['namespace'] = ns

        prom_selector = self.promqlify(selectors)
        promql_query = f"{prom_metric_availability}{{{prom_selector}}}"

        target_slo = f'{metric["threshold"]}ms ({metric["percentile"]}%)'
        achieved_slo = '0'
        slo_met = True

        return {
            'Component': component,
            'Type': 'latency',
            'Selectors': selectors,
            'Target Latency': target_slo,
            'Achieved': f'{achieved_slo}%',
            'Query': promql_query,
            'SLO met': slo_met,
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
            return ''

        lines = [f"{repo}: {results[0]} ({int(results[1])}% success)"
                 for repo, results in activity.items()]

        return '\n'.join(lines) if lines else ''


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
            app['promotions'][sr] = \
                (len(sr_history), (len(successes) / len(sr_history) * 100))

        logging.info(f"collecting merge activity for {app_name}")
        app['merge_activity'] = {}
        code_repos = [c['url'] for c in app['codeComponents']
                      if c['resource'] == 'upstream']
        for cr in code_repos:
            cr_history = build_master_build_history.get(cr)
            if not cr_history:
                continue
            successes = [h for h in cr_history if h == 'SUCCESS']
            app['merge_activity'][cr] = \
                (len(cr_history), (len(successes) / len(cr_history) * 100))

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
def main(configfile, dry_run, log_level, gitlab_project_id):
    config.init_from_toml(configfile)
    init_log_level(log_level)
    config.init_from_toml(configfile)
    gql.init_from_config()

    now = datetime.now()
    apps = get_apps_data(now)

    reports = [Report(app, now) for app in apps]

    for report in reports:
        report_msg = report.to_message()
        logging.info(['create_report', report_msg['file_path']])
        print(report_msg)

    if not dry_run:
        gw = prg.init(gitlab_project_id=gitlab_project_id,
                      override_pr_gateway_type='gitlab')
        mr = gw.create_app_interface_reporter_mr([report.to_message()
                                                  for report in reports])
        logging.info(['created_mr', mr.web_url])

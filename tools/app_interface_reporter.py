import logging
import os
import textwrap

from datetime import datetime, timezone

import click
import requests
import yaml

from prometheus_client.parser import text_string_to_metric_families
from dateutil.relativedelta import relativedelta

import reconcile.utils.gql as gql
import reconcile.utils.config as config
from reconcile.utils.secret_reader import SecretReader
import reconcile.queries as queries
import reconcile.jenkins_plugins as jenkins_base

from reconcile.utils.mr import CreateAppInterfaceReporter
from reconcile import mr_client_gateway
from reconcile.jenkins_job_builder import init_jjb
from reconcile.jenkins_job_builder import get_openshift_saas_deploy_job_name
from reconcile.cli import (
    config_file,
    log_level,
    dry_run,
    init_log_level,
    gitlab_project_id
)

CONTENT_FORMAT_VERSION = '1.0.0'
DASHDOTDB_SECRET = os.environ.get('DASHDOTDB_SECRET',
                                  'app-sre/dashdot/auth-proxy-production')


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


class Report:
    def __init__(self, app, date):
        settings = queries.get_app_interface_settings()
        self.secret_reader = SecretReader(settings=settings)
        # standard date format
        if hasattr(date, 'strftime'):
            date = date.strftime('%Y-%m-%d')

        self.app = app
        self.date = date
        self.report_sections = {}

        # promotions
        self.add_report_section(
            'promotions',
            self.app.get('promotions')
        )
        # merge activities
        self.add_report_section(
            'merge_activities',
            self.app.get('merge_activity')
        )
        # Container Vulnerabilities
        self.add_report_section(
            'container_vulnerabilities',
            self.get_vulnerability_content(
                self.app.get('container_vulnerabilities')
            )
        )
        # Post-deploy Jobs
        self.add_report_section(
            'post_deploy_jobs',
            self.get_post_deploy_jobs_content(
                self.app.get('post_deploy_jobs')
            )
        )
        # Deployment Validations
        self.add_report_section(
            'deployment_validations',
            self.get_validations_content(
                self.app.get('deployment_validations')
            )
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
            'name': f"{self.app['name']}-{self.date}",
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

    @staticmethod
    def get_vulnerability_content(container_vulnerabilities):
        parsed_metrics = []
        if not container_vulnerabilities:
            return parsed_metrics

        for cluster, namespaces in container_vulnerabilities.items():
            for namespace, severities in namespaces.items():
                parsed_metrics.append({'cluster': cluster,
                                       'namespace': namespace,
                                       'vulnerabilities': severities})
        return parsed_metrics

    @staticmethod
    def get_post_deploy_jobs_content(post_deploy_jobs):
        results = []
        if not post_deploy_jobs:
            return results

        for cluster, namespaces in post_deploy_jobs.items():
            for namespace, post_deploy_job in namespaces.items():
                results.append({'cluster': cluster,
                                'namespace': namespace,
                                'post_deploy_job': post_deploy_job})
        return results

    @staticmethod
    def get_validations_content(deployment_validations):
        parsed_metrics = []
        if not deployment_validations:
            return parsed_metrics

        for cluster, namespaces in deployment_validations.items():
            for namespace, validations in namespaces.items():
                parsed_metrics.append({'cluster': cluster,
                                       'namespace': namespace,
                                       'validations': validations})
        return parsed_metrics

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


def get_apps_data(date, month_delta=1):
    apps = queries.get_apps()
    saas_files = queries.get_saas_files()
    jjb, _ = init_jjb()
    build_jobs = jjb.get_all_jobs(job_types=['build'])
    jenkins_map = jenkins_base.get_jenkins_map()
    time_limit = date - relativedelta(months=month_delta)
    timestamp_limit = \
        int(time_limit.replace(tzinfo=timezone.utc).timestamp())
    build_jobs_history = \
        get_build_history(jenkins_map, build_jobs, timestamp_limit)

    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)
    secret_content = secret_reader.read_all({'path': DASHDOTDB_SECRET})
    dashdotdb_url = secret_content['url']
    dashdotdb_user = secret_content['username']
    dashdotdb_pass = secret_content['password']
    metrics = requests.get(f'{dashdotdb_url}/api/v1/metrics',
                           auth=(dashdotdb_user, dashdotdb_pass)).text
    namespaces = queries.get_namespaces()

    saas_deploy_history = {}
    for saas_file in saas_files:
        saas_file_name = saas_file['name']
        app_name = saas_file["app"]["name"]
        instance_name = saas_file["instance"]["name"]
        for template in saas_file["resourceTemplates"]:
            for target in template["targets"]:
                env_name = target["namespace"]["environment"]["name"]
                job_name = get_openshift_saas_deploy_job_name(
                    saas_file_name, env_name, settings
                )
                logging.info(f"getting build history for {job_name}")
                try:
                    build_history = \
                        jenkins_map[instance_name].get_build_history(
                            job_name, timestamp_limit
                        )
                    if app_name not in saas_deploy_history:
                        saas_deploy_history[app_name] = {
                            env_name: build_history}
                    else:
                        saas_deploy_history[app_name].update(
                            {env_name: build_history}
                        )
                except requests.exceptions.HTTPError:
                    logging.info(f"getting build history failed \
                        for {job_name}")

    for app in apps:
        if not app['codeComponents']:
            continue

        app_name = app['name']

        logging.info(f"collecting post-deploy jobs "
                     f"information for {app_name}")
        post_deploy_jobs = {}
        for saas_file in saas_files:
            if saas_file['app']['name'] != app_name:
                continue
            resource_types = saas_file['managedResourceTypes']

            # Only jobs of these types are expected to have a
            # further post-deploy job
            if not any(['Deployment' in resource_types,
                        'DeploymentConfig' not in resource_types]):
                continue

            for resource_template in saas_file['resourceTemplates']:
                for target in resource_template['targets']:
                    cluster = target['namespace']['cluster']['name']
                    namespace = target['namespace']['name']
                    post_deploy_jobs[cluster] = {}
                    post_deploy_jobs[cluster][namespace] = False

        for saas_file in saas_files:
            if saas_file['app']['name'] != app_name:
                continue
            resource_types = saas_file['managedResourceTypes']
            if 'Job' not in resource_types:
                continue
            for resource_template in saas_file['resourceTemplates']:
                for target in resource_template['targets']:

                    cluster = target['namespace']['cluster']['name']
                    namespace = target['namespace']['name']

                    # This block skips the check if the cluster/namespace
                    # has no Deployment/DeploymentConfig job associated.
                    if cluster not in post_deploy_jobs:
                        continue
                    if namespace not in post_deploy_jobs[cluster]:
                        continue

                    # Post-deploy job must depend on a openshift-saas-deploy
                    # job
                    if target['upstream'] is None:
                        continue
                    if target['upstream'].startswith('openshift-saas-deploy-'):
                        post_deploy_jobs[cluster][namespace] = True

        app['post_deploy_jobs'] = post_deploy_jobs

        logging.info(f"collecting promotion history for {app_name}")
        app["promotions"] = {}
        if app_name in saas_deploy_history:
            for env, history in saas_deploy_history[app_name].items():
                if history:
                    successes = [h for h in history if h == 'SUCCESS']
                    app["promotions"][env] = {
                        "total": len(history),
                        "success": len(successes),
                    }

        logging.info(f"collecting merge activity for {app_name}")
        app['merge_activity'] = {}
        code_repos = [c['url'] for c in app['codeComponents']
                      if c['resource'] == 'upstream']
        for cr in code_repos:
            cr_history = build_jobs_history.get(cr)
            if not cr_history:
                continue
            for env, history in cr_history.items():
                if not history:
                    continue
                successes = [h for h in history if h == 'SUCCESS']
                if cr not in app["merge_activity"]:
                    app["merge_activity"][cr] = {
                        env: {
                            "total": len(history),
                            "success": len(successes)
                        }
                    }
                else:
                    app["merge_activity"][cr].update({
                        env: {
                            "total": len(history),
                            "success": len(successes)
                        }
                    })

        logging.info(f"collecting dashdotdb information for {app_name}")
        app_namespaces = []
        for namespace in namespaces:
            if namespace['app']['name'] != app['name']:
                continue
            app_namespaces.append(namespace)
        vuln_mx = {}
        validt_mx = {}
        for family in text_string_to_metric_families(metrics):
            for sample in family.samples:
                if sample.name == 'imagemanifestvuln_total':
                    for app_namespace in app_namespaces:
                        cluster = sample.labels['cluster']
                        if app_namespace['cluster']['name'] != cluster:
                            continue
                        namespace = sample.labels['namespace']
                        if app_namespace['name'] != namespace:
                            continue
                        severity = sample.labels['severity']
                        if cluster not in vuln_mx:
                            vuln_mx[cluster] = {}
                        if namespace not in vuln_mx[cluster]:
                            vuln_mx[cluster][namespace] = {}
                        if severity not in vuln_mx[cluster][namespace]:
                            value = int(sample.value)
                            vuln_mx[cluster][namespace][severity] = value
                if sample.name == 'deploymentvalidation_total':
                    for app_namespace in app_namespaces:
                        cluster = sample.labels['cluster']
                        if app_namespace['cluster']['name'] != cluster:
                            continue
                        namespace = sample.labels['namespace']
                        if app_namespace['name'] != namespace:
                            continue
                        validation = sample.labels['validation']
                        # dvo: fail == 1, pass == 0, py: true == 1, false == 0
                        # so: ({false|pass}, {true|fail})
                        status = ('Passed',
                                  'Failed')[int(sample.labels['status'])]
                        if cluster not in validt_mx:
                            validt_mx[cluster] = {}
                        if namespace not in validt_mx[cluster]:
                            validt_mx[cluster][namespace] = {}
                        if validation not in validt_mx[cluster][namespace]:
                            validt_mx[cluster][namespace][validation] = {}
                        if status not in validt_mx[cluster][namespace][validation]:  # noqa: E501
                            validt_mx[cluster][namespace][validation][status] = {}  # noqa: E501
                        value = int(sample.value)
                        validt_mx[cluster][namespace][validation][status] = value  # noqa: E501

        app['container_vulnerabilities'] = vuln_mx
        app['deployment_validations'] = validt_mx

    return apps


def get_build_history(jenkins_map, jobs, timestamp_limit):
    history = {}
    for instance, jobs in jobs.items():
        jenkins = jenkins_map[instance]
        for job in jobs:
            logging.info(f"getting build history for {job['name']}")
            # continue if no repo_url
            if 'properties' not in job:
                continue
            if 'github' not in job['properties'][0]:
                continue

            if 'build_branch' in job:
                job_env = job['build_branch']
            elif 'id' in job:
                job_env = job['id']
            else:
                continue

            try:
                build_history = \
                    jenkins.get_build_history(job['name'], timestamp_limit)
                repo_url = get_repo_url(job)
                if repo_url not in history:
                    history[repo_url] = {job_env: build_history}
                else:
                    history[repo_url].update({job_env: build_history})
            except requests.exceptions.HTTPError:
                logging.info(f"getting build history failed \
                    for {job['name']}")

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
        email_body = """\
            Hello,

            A new report by the App SRE team is now available at:
            https://visual-app-interface.devshift.net/reports

            You can use the Search bar to search by App.

            You can also view reports per service here:
            https://visual-app-interface.devshift.net/services


            Having problems? Ping us on #sd-app-sre on Slack!


            You are receiving this message because you are a member
            of app-interface or subscribed to a mailing list specified
            as owning a service being run by the App SRE team:
            https://gitlab.cee.redhat.com/service/app-interface
            """

        mr_cli = mr_client_gateway.init(gitlab_project_id=gitlab_project_id,
                                        sqs_or_gitlab='gitlab')
        mr = CreateAppInterfaceReporter(reports=reports,
                                        email_body=textwrap.dedent(email_body),
                                        reports_path=reports_path)
        result = mr.submit(cli=mr_cli)
        logging.info(['created_mr', result.web_url])

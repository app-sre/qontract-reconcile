import logging
import os
import textwrap
from datetime import (
    datetime,
    timezone,
)

import click
import requests
import yaml
from dateutil.relativedelta import relativedelta
from prometheus_client.parser import text_string_to_metric_families
from sretoolbox.utils.threaded import run

from reconcile import (
    jenkins_base,
    mr_client_gateway,
    queries,
)
from reconcile.cli import (
    config_file,
    dry_run,
    gitlab_project_id,
    log_level,
    threaded,
)
from reconcile.jenkins_job_builder import init_jjb
from reconcile.utils.jjb_client import JJB
from reconcile.utils.mr import CreateAppInterfaceReporter
from reconcile.utils.runtime.environment import init_env
from reconcile.utils.secret_reader import SecretReader

CONTENT_FORMAT_VERSION = "1.0.0"
DASHDOTDB_SECRET = os.environ.get(
    "DASHDOTDB_SECRET", "app-sre/dashdot/auth-proxy-production"
)


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

    url = os.path.join(url, "api/v1/query")

    if auth is None:
        auth = {}

    params = {"query": query}

    response = requests.get(url, params=params, auth=auth, timeout=60)

    response.raise_for_status()
    response = response.json()

    # TODO ensure len response == 1
    return response["data"]["result"]


class Report:
    def __init__(self, app, date):
        settings = queries.get_app_interface_settings()
        self.secret_reader = SecretReader(settings=settings)
        # standard date format
        if hasattr(date, "strftime"):
            date = date.strftime("%Y-%m-%d")

        self.app = app
        self.date = date
        self.report_sections = {}

        # promotions
        self.add_report_section("promotions", self.app.get("promotions"))
        # merge activities
        self.add_report_section("merge_activities", self.app.get("merge_activity"))
        # Container Vulnerabilities
        self.add_report_section(
            "container_vulnerabilities",
            self.get_vulnerability_content(self.app.get("container_vulnerabilities")),
        )
        # Post-deploy Jobs
        self.add_report_section(
            "post_deploy_jobs",
            self.get_post_deploy_jobs_content(self.app.get("post_deploy_jobs")),
        )
        # Deployment Validations
        self.add_report_section(
            "deployment_validations",
            self.get_validations_content(self.app.get("deployment_validations")),
        )
        # Service SLOs
        self.add_report_section(
            "service_slo", self.get_slo_content(self.app.get("service_slo"))
        )

    @property
    def path(self):
        return "data/reports/{}/{}.yml".format(self.app["name"], self.date)

    def content(self):
        return {
            "$schema": "/app-sre/report-1.yml",
            "labels": {"app": self.app["name"]},
            "name": f"{self.app['name']}-{self.date}",
            "app": {"$ref": self.app["path"]},
            "date": self.date,
            "contentFormatVersion": CONTENT_FORMAT_VERSION,
            "content": yaml.safe_dump(self.report_sections, sort_keys=False),
        }

    def to_yaml(self):
        return yaml.safe_dump(self.content(), sort_keys=False)

    def to_message(self):
        return {"file_path": self.path, "content": self.to_yaml()}

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
                parsed_metrics.append({
                    "cluster": cluster,
                    "namespace": namespace,
                    "vulnerabilities": severities,
                })
        return parsed_metrics

    @staticmethod
    def get_post_deploy_jobs_content(post_deploy_jobs):
        results = []
        if not post_deploy_jobs:
            return results

        for cluster, namespaces in post_deploy_jobs.items():
            for namespace, post_deploy_job in namespaces.items():
                results.append({
                    "cluster": cluster,
                    "namespace": namespace,
                    "post_deploy_job": post_deploy_job,
                })
        return results

    @staticmethod
    def get_validations_content(deployment_validations):
        parsed_metrics = []
        if not deployment_validations:
            return parsed_metrics

        for cluster, namespaces in deployment_validations.items():
            for namespace, validations in namespaces.items():
                parsed_metrics.append({
                    "cluster": cluster,
                    "namespace": namespace,
                    "validations": validations,
                })
        return parsed_metrics

    @staticmethod
    def get_slo_content(service_slo):
        parsed_metrics = []
        if not service_slo:
            return parsed_metrics

        for cluster, namespaces in service_slo.items():
            for namespace, slo_doc_names in namespaces.items():
                for slo_doc_name, slos in slo_doc_names.items():
                    for slo_name, values in slos.items():
                        metric = {
                            "cluster": cluster,
                            "namespace": namespace,
                            "slo_name": slo_name,
                            "slo_doc_name": slo_doc_name,
                            **values,
                        }
                        parsed_metrics.append(metric)
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


def get_apps_data(date, month_delta=1, thread_pool_size=10):
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings)

    apps = queries.get_apps()
    jjb: JJB = init_jjb(secret_reader)
    jenkins_map = jenkins_base.get_jenkins_map()
    time_limit = date - relativedelta(months=month_delta)
    timestamp_limit = int(time_limit.replace(tzinfo=timezone.utc).timestamp())

    secret_content = secret_reader.read_all({"path": DASHDOTDB_SECRET})
    dashdotdb_url = secret_content["url"]
    dashdotdb_user = secret_content["username"]
    dashdotdb_pass = secret_content["password"]
    auth = (dashdotdb_user, dashdotdb_pass)
    vuln_metrics = requests.get(
        f"{dashdotdb_url}/api/v1/imagemanifestvuln/metrics", auth=auth, timeout=60
    ).text
    validt_metrics = requests.get(
        f"{dashdotdb_url}/api/v1/deploymentvalidation/metrics", auth=auth, timeout=60
    ).text
    slo_metrics = requests.get(
        f"{dashdotdb_url}/api/v1/serviceslometrics/metrics", auth=auth, timeout=60
    ).text
    namespaces = queries.get_namespaces()

    build_jobs = jjb.get_all_jobs(job_types=["build"])
    jobs_to_get = build_jobs.copy()

    job_history = get_build_history_pool(
        jenkins_map, jobs_to_get, timestamp_limit, thread_pool_size
    )

    for app in apps:
        if not app["codeComponents"]:
            continue

        app_name = app["name"]

        logging.info(f"collecting post-deploy jobs " f"information for {app_name}")
        # this is now empty as it referred to post_deploy jobs via Jenkins. This section
        # should be removed when we publish a new content format or if we get promotion data
        # differently.
        app["post_deploy_jobs"] = {}

        logging.info(f"collecting promotion history for {app_name}")
        app["promotions"] = {}
        # this is now empty as it referred to saas files promotions via Jenkins. This section
        # should be removed when we publish a new content format or if we get promotion data
        # differently.

        logging.info(f"collecting merge activity for {app_name}")
        app["merge_activity"] = {}
        code_repos = [
            c["url"] for c in app["codeComponents"] if c["resource"] == "upstream"
        ]
        for jobs in build_jobs.values():
            for job in jobs:
                try:
                    repo_url = get_repo_url(job)
                except KeyError:
                    continue
                if repo_url not in code_repos:
                    continue
                if job["name"] not in job_history:
                    continue
                history = job_history[job["name"]]
                if repo_url not in app["merge_activity"]:
                    app["merge_activity"][repo_url] = [
                        {"branch": job["branch"], **history}
                    ]
                else:
                    app["merge_activity"][repo_url].append({
                        "branch": job["branch"],
                        **history,
                    })

        logging.info(f"collecting dashdotdb information for {app_name}")
        app_namespaces = []
        for namespace in namespaces:
            if namespace["app"]["name"] != app["name"]:
                continue
            app_namespaces.append(namespace)
        vuln_mx = {}
        validt_mx = {}
        slo_mx = {}
        for family in text_string_to_metric_families(vuln_metrics):
            for sample in family.samples:
                if sample.name == "imagemanifestvuln_total":
                    for app_namespace in app_namespaces:
                        cluster = sample.labels["cluster"]
                        if app_namespace["cluster"]["name"] != cluster:
                            continue
                        namespace = sample.labels["namespace"]
                        if app_namespace["name"] != namespace:
                            continue
                        severity = sample.labels["severity"]
                        if cluster not in vuln_mx:
                            vuln_mx[cluster] = {}
                        if namespace not in vuln_mx[cluster]:
                            vuln_mx[cluster][namespace] = {}
                        if severity not in vuln_mx[cluster][namespace]:
                            value = int(sample.value)
                            vuln_mx[cluster][namespace][severity] = value
        for family in text_string_to_metric_families(validt_metrics):
            for sample in family.samples:
                if sample.name == "deploymentvalidation_total":
                    for app_namespace in app_namespaces:
                        cluster = sample.labels["cluster"]
                        if app_namespace["cluster"]["name"] != cluster:
                            continue
                        namespace = sample.labels["namespace"]
                        if app_namespace["name"] != namespace:
                            continue
                        validation = sample.labels["validation"]
                        # dvo: fail == 1, pass == 0, py: true == 1, false == 0
                        # so: ({false|pass}, {true|fail})
                        status = ("Passed", "Failed")[int(sample.labels["status"])]
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
        for family in text_string_to_metric_families(slo_metrics):
            for sample in family.samples:
                if sample.name == "serviceslometrics":
                    for app_namespace in app_namespaces:
                        cluster = sample.labels["cluster"]
                        if app_namespace["cluster"]["name"] != cluster:
                            continue
                        namespace = sample.labels["namespace"]
                        if app_namespace["name"] != namespace:
                            continue
                        slo_doc_name = sample.labels["slodoc"]
                        slo_name = sample.labels["name"]
                        if cluster not in slo_mx:
                            slo_mx[cluster] = {}
                        if namespace not in slo_mx[cluster]:
                            slo_mx[cluster][namespace] = {}
                        if slo_doc_name not in slo_mx[cluster][namespace]:  # pylint: disable=line-too-long # noqa: E501
                            slo_mx[cluster][namespace][slo_doc_name] = {}
                        if slo_name not in slo_mx[cluster][namespace][slo_doc_name]:  # noqa: E501
                            slo_mx[cluster][namespace][slo_doc_name][slo_name] = {  # noqa: E501
                                sample.labels["type"]: sample.value
                            }
                        else:
                            slo_mx[cluster][namespace][slo_doc_name][slo_name].update({  # pylint: disable=line-too-long # noqa: E501
                                sample.labels["type"]: sample.value
                            })
        app["container_vulnerabilities"] = vuln_mx
        app["deployment_validations"] = validt_mx
        app["service_slo"] = slo_mx

    return apps


def get_build_history(job):
    try:
        logging.info(f"getting build history for {job['name']}")
        job["build_history"] = job["jenkins"].get_build_history(
            job["name"], job["timestamp_limit"]
        )
    except requests.exceptions.HTTPError:
        logging.debug(f"{job['name']}: get build history failed")
    return job


def get_build_history_pool(jenkins_map, jobs, timestamp_limit, thread_pool_size):
    history_to_get = []
    for instance, _jobs in jobs.items():
        jenkins = jenkins_map[instance]
        for job in _jobs:
            job["jenkins"] = jenkins
            job["timestamp_limit"] = timestamp_limit
            history_to_get.append(job)

    result = run(
        func=get_build_history,
        iterable=history_to_get,
        thread_pool_size=thread_pool_size,
    )

    history = {}
    for job in result:
        build_history = job.get("build_history")
        if not build_history:
            continue
        successes = [_ for _ in build_history if _ == "SUCCESS"]
        history[job["name"]] = {"total": len(build_history), "success": len(successes)}
    return history


def get_repo_url(job):
    repo_url_raw = job["properties"][0]["github"]["url"]
    return repo_url_raw.strip("/").replace(".git", "")


@click.command()
@threaded()
@config_file
@dry_run
@log_level
@gitlab_project_id
@click.option("--reports-path", help="path to write reports")
def main(
    configfile, dry_run, log_level, gitlab_project_id, reports_path, thread_pool_size
):
    init_env(log_level=log_level, config_file=configfile)

    now = datetime.now()
    apps = get_apps_data(now, thread_pool_size=thread_pool_size)

    reports = [Report(app, now).to_message() for app in apps]

    for report in reports:
        logging.info(["create_report", report["file_path"]])

        if reports_path:
            report_file = os.path.join(reports_path, report["file_path"])

            try:
                os.makedirs(os.path.dirname(report_file))
            except FileExistsError:
                pass

            with open(report_file, "w", encoding="locale") as f:
                f.write(report["content"])

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

        mr = CreateAppInterfaceReporter(
            reports=reports,
            email_body=textwrap.dedent(email_body),
            reports_path=reports_path,
        )
        with mr_client_gateway.init(
            gitlab_project_id=gitlab_project_id, sqs_or_gitlab="gitlab"
        ) as mr_cli:
            result = mr.submit(cli=mr_cli)
        logging.info(["created_mr", result.web_url])


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter

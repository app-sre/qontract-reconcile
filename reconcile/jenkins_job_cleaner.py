import logging

from reconcile import queries

from reconcile.jenkins_job_builder import init_jjb
from reconcile.utils.jenkins_api import JenkinsApi
from reconcile.utils.secret_reader import SecretReader

QONTRACT_INTEGRATION = "jenkins-job-cleaner"


def get_managed_job_names(job_names, managed_projects):
    managed_jobs = set()
    for job_name in job_names:
        for managed_project in managed_projects:
            if job_name.startswith(managed_project):
                managed_jobs.add(job_name)

    return list(managed_jobs)


def get_desired_job_names(instance_name: str, secret_reader: SecretReader):
    jjb = init_jjb(secret_reader)
    desired_jobs = jjb.get_all_jobs(instance_name=instance_name, include_test=True)[
        instance_name
    ]
    return [j["name"] for j in desired_jobs]


def run(dry_run):
    jenkins_instances = queries.get_jenkins_instances()
    secret_reader = SecretReader(queries.get_secret_reader_settings())

    for instance in jenkins_instances:
        if instance.get("deleteMethod") != "manual":
            continue
        managed_projects = instance.get("managedProjects")
        if not managed_projects:
            continue

        instance_name = instance["name"]
        jenkins = JenkinsApi.init_jenkins_from_secret(
            secret_reader, instance["token"], ssl_verify=False
        )
        all_job_names = jenkins.get_job_names()
        managed_job_names = get_managed_job_names(all_job_names, managed_projects)
        desired_job_names = get_desired_job_names(instance_name, secret_reader)
        delete_job_names = [j for j in managed_job_names if j not in desired_job_names]

        for job_name in delete_job_names:
            logging.info(["delete_job", instance_name, job_name])
            if not dry_run:
                jenkins.delete_job(job_name)

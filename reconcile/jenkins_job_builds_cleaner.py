import logging
import re
import time

from reconcile import queries

from reconcile.utils.jenkins_api import JenkinsApi

QONTRACT_INTEGRATION = "jenkins-job-builds-cleaner"


def hours_to_ms(hours):
    return hours * 60 * 60 * 1000


def delete_builds(jenkins, builds_todel, dry_run=True):
    delete_builds_count = len(builds_todel)
    for idx, build in enumerate(builds_todel, start=1):
        job_name = build["job_name"]
        build_id = build["build_id"]
        progress_str = f"{idx}/{delete_builds_count}"
        logging.debug(
            [
                progress_str,
                job_name,
                build["rule_name"],
                build["rule_keep_hours"],
                build_id,
            ]
        )
        if not dry_run:
            try:
                jenkins.delete_build(build["job_name"], build["build_id"])
            except Exception:
                msg = f"failed to delete {job_name}/{build_id}"
                logging.exception(msg)


def find_builds(jenkins, job_names, rules):
    # Current time in ms
    time_ms = time.time() * 1000

    builds_found = []
    for job_name in job_names:
        for rule in rules:
            if rule["name_re"].search(job_name):
                builds = jenkins.get_builds(job_name)
                for build in builds:
                    if time_ms - rule["keep_ms"] > build["timestamp"]:
                        builds_found.append(
                            {
                                "job_name": job_name,
                                "rule_name": rule["name"],
                                "rule_keep_hours": rule["keep_hours"],
                                "build_id": build["id"],
                            }
                        )
                # Only act on the first rule matched
                break
    return builds_found


def run(dry_run):
    jenkins_instances = queries.get_jenkins_instances()
    settings = queries.get_app_interface_settings()

    for instance in jenkins_instances:
        instance_cleanup_rules = instance.get("buildsCleanupRules", [])
        if not instance_cleanup_rules:
            # Skip instance if no cleanup rules defined
            continue

        # Process cleanup rules, pre-compile as regexes
        cleanup_rules = []
        for rule in instance_cleanup_rules:
            cleanup_rules.append(
                {
                    "name": rule["name"],
                    "name_re": re.compile(rule["name"]),
                    "keep_hours": rule["keep_hours"],
                    "keep_ms": hours_to_ms(rule["keep_hours"]),
                }
            )

        token = instance["token"]
        jenkins = JenkinsApi(token, ssl_verify=False, settings=settings)
        all_job_names = jenkins.get_job_names()

        builds_todel = find_builds(jenkins, all_job_names, cleanup_rules)

        logging.info(f"{len(builds_todel)} builds will be deleted")
        delete_builds(jenkins, builds_todel, dry_run)
        logging.info("deletion completed")

import sys
import semver

import reconcile.openshift_saas_deploy as osd
import reconcile.utils.threaded as threaded

from reconcile.saas_file_owners import read_diffs_from_file as \
    read_saas_file_owners_diffs

QONTRACT_INTEGRATION = 'openshift-saas-deploy-wrapper'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def osd_run_wrapper(diff, dry_run, available_thread_pool_size,
                    gitlab_project_id):
    saas_file_name = diff['saas_file_name']
    env_name = diff['environment']
    exit_code = 0
    try:
        osd.run(dry_run=dry_run,
                thread_pool_size=available_thread_pool_size,
                saas_file_name=saas_file_name,
                env_name=env_name,
                gitlab_project_id=gitlab_project_id)
    except SystemExit as e:
        exit_code = e.code
    return exit_code


def run(dry_run, thread_pool_size=10, io_dir='throughput/',
        gitlab_project_id=None):
    saas_file_owners_diffs = read_saas_file_owners_diffs(io_dir)
    if len(saas_file_owners_diffs) == 0:
        return

    available_thread_pool_size = \
        threaded.estimate_available_thread_pool_size(
            thread_pool_size,
            len(saas_file_owners_diffs))

    exit_codes = threaded.run(
        osd_run_wrapper, saas_file_owners_diffs, thread_pool_size,
        dry_run=dry_run,
        available_thread_pool_size=available_thread_pool_size,
        gitlab_project_id=gitlab_project_id,
    )

    if [ec for ec in exit_codes if ec]:
        sys.exit(1)

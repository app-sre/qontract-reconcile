import reconcile.pull_request_gateway as prg

QONTRACT_INTEGRATION = 'gitlab-pr-submitter'


def run(dry_run, gitlab_project_id):
    prg.submit_to_gitlab(gitlab_project_id, dry_run)

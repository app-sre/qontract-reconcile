import reconcile.pull_request_gateway as prg


def run(gitlab_project_id, dry_run=False):
    prg.submit_to_gitlab(gitlab_project_id, dry_run)

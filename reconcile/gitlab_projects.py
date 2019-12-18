import logging

import reconcile.queries as queries

from utils.gitlab_api import GitLabApi


def run(dry_run=False):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    gl = GitLabApi(instance, settings=settings)

    project_requests = instance['projectRequests'] or []
    for pr in project_requests:
        group = pr['group']
        group_id, existing_projects = gl.get_group_id_and_projects(group)
        requested_projects = pr['projects']
        projects_to_create = [p for p in requested_projects
                              if p not in existing_projects]
        for p in projects_to_create:
            logging.info(['create_project', group, p])
            if not dry_run:
                gl.create_project(group_id, p)

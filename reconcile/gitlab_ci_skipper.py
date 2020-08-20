import os

import reconcile.queries as queries
import utils.throughput as throughput

from utils.gitlab_api import GitLabApi


QONTRACT_INTEGRATION = 'gitlab-ci-skipper'


def get_output_file_path(io_dir):
    dir_path = os.path.join(io_dir, QONTRACT_INTEGRATION)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    return os.path.join(dir_path, 'output')


def write_output_to_file(io_dir, output):
    file_path = get_output_file_path(io_dir)
    with open(file_path, 'w') as f:
        f.write(output)
    throughput.change_files_ownership(io_dir)


def init_gitlab(gitlab_project_id):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    return GitLabApi(instance, project_id=gitlab_project_id,
                     settings=settings)


def run(dry_run, gitlab_project_id=None, gitlab_merge_request_id=None,
        io_dir='throughput/'):
    gl = init_gitlab(gitlab_project_id)
    labels = gl.get_merge_request_labels(gitlab_merge_request_id)
    output = 'yes' if 'skip-ci' in labels else 'no'
    write_output_to_file(io_dir, output)

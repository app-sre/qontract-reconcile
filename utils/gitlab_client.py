import gitlab
import urllib3
import uuid
from reconcile.config import get_config

_project = None

def init(server, token, project_id):
    global _project
    
    # supress `InsecureRequestWarning: Unverified HTTPS request is being made`
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    gl = gitlab.Gitlab(server, private_token=token, ssl_verify=False)
    _project = gl.projects.get(project_id)

    return _project


def init_from_config():
    if _project is not None:
        return
    
    config = get_config()

    server = config['gitlab']['server']
    token = config['gitlab']['token']
    project_id = config['gitlab']['project_id']

    return init(server, token, project_id)


def create_branch(new_branch, source_branch):
    global _project

    init_from_config()

    data = {
        'branch': new_branch,
        'ref': source_branch
    }
    _project.branches.create(data)


def delete_file(branch_name, file_path, commit_message):
    global _project

    init_from_config()

    data = {
        'branch': branch_name,
        'commit_message': commit_message,
        'actions': [
            {
                'action': 'delete',
                'file_path': file_path
                }
        ]
    }
    _project.commits.create(data)


def create_mr(source_branch, target_branch, title, remove_source_branch=True):
    global _project

    init_from_config()

    data = {
        'source_branch': source_branch,
        'target_branch': target_branch,
        'title': title,
        'remove_source_branch': str(remove_source_branch)
    }
    _project.mergerequests.create(data)


def delete_user_mr_exists(title):
    global _project

    init_from_config()

    mrs = _project.mergerequests.list(state='opened')
    for mr in mrs:
        # since we are using a naming convention for these MRs
        # we can determine if there is already a pending MR based on the title
        if (mr.attributes['title'] != title):
            continue
        
        return True
    
    return False


def create_delete_user_mr(username, path):
    prefix = 'qcontract-reconcile'
    target_branch = 'master'
    branch_name = '{}-delete-{}-{}'.format(prefix, username, str(uuid.uuid4())[0:6])
    title = '[{}] delete user {} ({})'.format(prefix, username, path)

    if (delete_user_mr_exists(title)):
        return

    create_branch(branch_name, target_branch)
    delete_file(branch_name, path, title)
    create_mr(branch_name, target_branch, title)

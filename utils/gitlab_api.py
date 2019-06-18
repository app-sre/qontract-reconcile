import logging

import gitlab
import urllib3
import uuid


# The following line will supress
# `InsecureRequestWarning: Unverified HTTPS request is being made`
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class GitLabApi(object):
    def __init__(self, server, token, project_id=None, ssl_verify=True):
        self.server = server
        self.gl = gitlab.Gitlab(self.server, private_token=token,
                                ssl_verify=ssl_verify)
        self.gl.auth()
        self.user = self.gl.user
        if project_id is not None:
            self.project = self.gl.projects.get(project_id)

    def create_branch(self, new_branch, source_branch):
        data = {
            'branch': new_branch,
            'ref': source_branch
        }
        self.project.branches.create(data)

    def delete_branch(self, branch):
        self.project.branches.delete(branch)

    def delete_file(self, branch_name, file_path, commit_message):
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
        self.project.commits.create(data)

    def create_mr(self, source_branch, target_branch, title,
                  remove_source_branch=True):
        data = {
            'source_branch': source_branch,
            'target_branch': target_branch,
            'title': title,
            'remove_source_branch': str(remove_source_branch)
        }
        self.project.mergerequests.create(data)

    def mr_exists(self, title):
        mrs = self.project.mergerequests.list(state='opened')
        for mr in mrs:
            # since we are using a naming convention for these MRs
            # we can determine if a pending MR exists based on the title
            if mr.attributes.get('title') != title:
                continue

            return True

        return False

    def create_delete_user_mr(self, username, paths):
        prefix = 'qontract-reconcile'
        target_branch = 'master'
        branch_name = '{}-delete-{}-{}'.format(
            prefix,
            username,
            str(uuid.uuid4())[0:6]
        )
        title = '[{}] delete user {}'.format(prefix, username)

        if self.mr_exists(title):
            return

        self.create_branch(branch_name, target_branch)

        for path in paths:
            try:
                self.delete_file(branch_name, path, title)
            except gitlab.exceptions.GitlabCreateError as e:
                self.delete_branch(branch_name)
                if str(e) != "400: A file with this name doesn't exist":
                    raise e
                logging.info(
                    "File {} does not exist, not opening MR".format(path)
                )
                return

        self.create_mr(branch_name, target_branch, title)

    def get_project_maintainers(self, repo_url):
        project = self.get_project(repo_url)
        members = project.members.all(all=True)
        return [m['username'] for m in members if m['access_level'] >= 40]

    def get_app_sre_group_users(self):
        app_sre_group = self.gl.groups.get('app-sre')
        return [m for m in app_sre_group.members.list()]

    def add_project_member(self, repo_url, user):
        project = self.get_project(repo_url)
        try:
            project.members.create({
                'user_id': user.id,
                'access_level': gitlab.MAINTAINER_ACCESS
            })
        except gitlab.exceptions.GitlabCreateError:
            member = project.members.get(user.id)
            member.access_level = gitlab.MAINTAINER_ACCESS

    def get_project(self, repo_url):
        repo = repo_url.replace(self.server + '/', '')
        return self.gl.projects.get(repo)

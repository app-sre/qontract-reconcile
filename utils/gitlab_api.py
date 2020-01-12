import os
import logging
import uuid
import gitlab
import urllib3
import ruamel.yaml as yaml

from datetime import datetime
from ruamel.yaml.scalarstring import PreservedScalarString as pss

import utils.secret_reader as secret_reader


# The following line will supress
# `InsecureRequestWarning: Unverified HTTPS request is being made`
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class GitLabApi(object):
    def __init__(self, instance, project_id=None, ssl_verify=True,
                 settings=None):
        self.server = instance['url']
        token = secret_reader.read(instance['token'], settings=settings)
        ssl_verify = instance['sslVerify']
        if ssl_verify is None:
            ssl_verify = True
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

    def create_commit(self, branch_name, commit_message, actions):
        """
        actions is a list of 'action' dictionaries. The 'action' dict is
        documented here: https://docs.gitlab.com/ee/api/commits.html
                         #create-a-commit-with-multiple-files-and-actions
        """

        self.project.commits.create({
            'branch': branch_name,
            'commit_message': commit_message,
            'actions': actions
        })

    def create_file(self, branch_name, file_path, commit_message, content):
        data = {
            'branch': branch_name,
            'commit_message': commit_message,
            'actions': [
                {
                    'action': 'create',
                    'file_path': file_path,
                    'content': content
                }
            ]
        }
        self.project.commits.create(data)

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

    def update_file(self, branch_name, file_path, commit_message, content):
        data = {
            'branch': branch_name,
            'commit_message': commit_message,
            'actions': [
                {
                    'action': 'update',
                    'file_path': file_path,
                    'content': content
                }
            ]
        }
        self.project.commits.create(data)

    def create_mr(self, source_branch, target_branch, title,
                  remove_source_branch=True, labels=[]):
        data = {
            'source_branch': source_branch,
            'target_branch': target_branch,
            'title': title,
            'remove_source_branch': str(remove_source_branch),
            'labels': labels
        }
        return self.project.mergerequests.create(data)

    def mr_exists(self, title):
        mrs = self.get_merge_requests(state='opened')
        for mr in mrs:
            # since we are using a naming convention for these MRs
            # we can determine if a pending MR exists based on the title
            if mr.attributes.get('title') != title:
                continue

            return True

        return False

    def create_app_interface_reporter_mr(self, reports, email_schema,
                                         email_body, reports_path):
        labels = ['automerge']
        prefix = 'app-interface-reporter'
        target_branch = 'master'

        now = datetime.now()
        ts = now.strftime("%Y%m%d%H%M%S")
        isodate = now.isoformat()
        short_date = now.strftime('%Y-%m-%d')

        branch_name = 'app-interface-reporter-{}'.format(ts)
        commit_message = '[{}] reports for {}'.format(
            prefix, isodate
        )

        self.create_branch(branch_name, target_branch)

        actions = [
            {
                'action': 'create',
                'file_path': report['file_path'],
                'content': report['content'],
            }
            for report in reports
        ]

        self.create_commit(branch_name, commit_message, actions)

        # add a new email to be picked up by email-sender
        msg = 'add email notification'
        email_path = f"data/{reports_path}/emails/{branch_name}.yml"
        email = {
            '$schema': email_schema,
            'labels': {},
            'name': branch_name,
            'subject': f"[{prefix}] reports for {short_date}",
            'to': {
                'aliases': ['all-service-owners']
            },
            'body': pss(email_body)
        }
        content = '---\n' + \
            yaml.dump(email, Dumper=yaml.RoundTripDumper)
        self.create_file(branch_name, email_path, msg, content)

        return self.create_mr(branch_name, target_branch,
                              commit_message, labels=labels)

    def create_delete_user_mr(self, username, paths):
        labels = ['automerge']
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

        return self.create_mr(branch_name, target_branch, title, labels=labels)

    def create_delete_aws_access_key_mr(self, account, path, key):
        labels = ['automerge']
        prefix = 'qontract-reconcile'
        target_branch = 'master'
        branch_name = '{}-delete-aws-access-key-{}-{}-{}'.format(
            prefix,
            account,
            key,
            str(uuid.uuid4())[0:6]
        )
        title = '[{}] delete {} access key {}'.format(prefix, account, key)

        if self.mr_exists(title):
            return

        self.create_branch(branch_name, target_branch)

        # add key to deleteKeys list to be picked up by aws-iam-keys
        msg = 'add key to deleteKeys'
        f = self.project.files.get(file_path=path, ref=target_branch)
        content = yaml.load(f.decode(), Loader=yaml.RoundTripLoader)
        content.setdefault('deleteKeys', [])
        content['deleteKeys'].append(key)
        new_content = '---\n' + \
            yaml.dump(content, Dumper=yaml.RoundTripDumper)
        try:
            self.update_file(branch_name, path, msg, new_content)
        except gitlab.exceptions.GitlabCreateError as e:
            self.delete_branch(branch_name)
            if str(e) != "400: A file with this name doesn't exist":
                raise e
            logging.info(
                "File {} does not exist, not opening MR".format(path)
            )
            return

        # add a new email to be picked up by email-sender
        body = """Hello,

This is an automated notification.

An AWS access key leak was detected and is being mitigatd.
Information:
Account: {}
Access key: {}

Please consult relevant SOPs to verify that the account is secure.
"""
        msg = 'add email notification'
        name = f"{account}-{key}"
        email_path = f"{os.path.dirname(path)}/emails/{name}.yml"
        ref = path[4:] if path.startswith('data') else path
        email = {
            # TODO: extract the schema value from utils
            '$schema': '/app-interface/app-interface-email-1.yml',
            'labels': {},
            'name': name,
            'subject': title,
            'to': {
                'aws_accounts': [{'$ref': ref}]
            },
            'body': pss(body.format(account, key))
        }
        content = '---\n' + \
            yaml.dump(email, Dumper=yaml.RoundTripDumper)
        self.create_file(branch_name, email_path, msg, content)

        return self.create_mr(branch_name, target_branch, title, labels=labels)

    def get_project_maintainers(self, repo_url):
        project = self.get_project(repo_url)
        if project is None:
            return None
        members = project.members.all(all=True)
        return [m.username for m in members if m.access_level >= 40]

    def get_app_sre_group_users(self):
        app_sre_group = self.gl.groups.get('app-sre')
        return [m for m in app_sre_group.members.list()]

    def check_group_exists(self, group_name):
        groups = self.gl.groups.list()
        group_names = list(map(lambda x: x.name, groups))
        if group_name not in group_names:
            return False
        return True

    def get_group_members(self, group_name):
        if not self.check_group_exists(group_name):
            logging.error(group_name + " group not found")
            return []
        group = self.gl.groups.get(group_name)
        return ([{
                "user": m.username,
                "access_level": self.get_access_level_string(m.access_level)}
            for m in group.members.list()])

    def add_project_member(self, repo_url, user, access="maintainer"):
        project = self.get_project(repo_url)
        if project is None:
            return
        access_level = self.get_access_level(access)
        try:
            project.members.create({
                'user_id': user.id,
                'access_level': access_level
            })
        except gitlab.exceptions.GitlabCreateError:
            member = project.members.get(user.id)
            member.access_level = access_level

    def add_group_member(self, group_name, username, access):
        if not self.check_group_exists(group_name):
            logging.error(group_name + " group not found")
        else:
            group = self.gl.groups.get(group_name)
            user = self.get_user(username)
            access_level = self.get_access_level(access)
            if user is not None:
                try:
                    group.members.create({
                        'user_id': user.id,
                        'access_level': access_level
                    })
                except gitlab.exceptions.GitlabCreateError:
                    member = group.members.get(user.id)
                    member.access_level = access_level

    def remove_group_member(self, group_name, username):
        group = self.gl.groups.get(group_name)
        user = self.get_user(username)
        if user is not None:
            group.members.delete(user.id)

    def change_access(self, group, username, access):
        group = self.gl.groups.get(group)
        user = self.get_user(username)
        member = group.members.get(user.id)
        member.access_level = self.get_access_level(access)
        member.save()

    @staticmethod
    def get_access_level_string(access_level):
        if access_level == gitlab.OWNER_ACCESS:
            return "owner"
        elif access_level == gitlab.MAINTAINER_ACCESS:
            return "maintainer"
        elif access_level == gitlab.DEVELOPER_ACCESS:
            return "developer"
        elif access_level == gitlab.REPORTER_ACCESS:
            return "reporter"
        elif access_level == gitlab.GUEST_ACCESS:
            return "guest"

    @staticmethod
    def get_access_level(access):
        access = access.lower()
        if access == "owner":
            return gitlab.OWNER_ACCESS
        elif access == "maintainer":
            return gitlab.MAINTAINER_ACCESS
        elif access == "developer":
            return gitlab.DEVELOPER_ACCESS
        elif access == "reporter":
            return gitlab.REPORTER_ACCESS
        elif access == "guest":
            return gitlab.GUEST_ACCESS

    def get_group_id_and_projects(self, group_name):
        groups = self.gl.groups.list()
        group = [g for g in groups if g.path == group_name]
        if not group:
            logging.error(group_name + " group not found")
            return None, []
        [group] = group
        return group.id, [p.name for p in self.get_items(group.projects.list)]

    def create_project(self, group_id, project):
        self.gl.projects.create({'name': project, 'namespace_id': group_id})

    def get_project_url(self, group, project):
        return f"{self.server}/{group}/{project}"

    def get_project(self, repo_url):
        repo = repo_url.replace(self.server + '/', '')
        try:
            project = self.gl.projects.get(repo)
        except gitlab.exceptions.GitlabGetError:
            logging.warning(f'{repo_url} not found')
            project = None
        return project

    def get_issues(self, state):
        return self.get_items(self.project.issues.list, state=state)

    def get_merge_requests(self, state):
        return self.get_items(self.project.mergerequests.list, state=state)

    @staticmethod
    def get_items(method, **kwargs):
        all_items = []
        page = 1
        while True:
            items = method(page=page, per_page=100, **kwargs)
            all_items.extend(items)
            if len(items) < 100:
                break
            page += 1

        return all_items

    def add_label(self, item, item_type, label):
        note_body = (
            'item has been marked as {0}. '
            'to remove say `/{0} cancel`').format(label)
        labels = item.attributes.get('labels')
        labels.append(label)
        item.notes.create({'body': note_body})
        self.update_labels(item, item_type, labels)

    def remove_label(self, item, item_type, label):
        labels = item.attributes.get('labels')
        labels.remove(label)
        self.update_labels(item, item_type, labels)

    def update_labels(self, item, item_type, labels):
        if item_type == 'issue':
            editable_item = \
                self.project.issues.get(
                    item.attributes.get('iid'), lazy=True)
        elif item_type == 'merge-request':
            editable_item = \
                self.project.mergerequests.get(
                    item.attributes.get('iid'), lazy=True)
        editable_item.labels = labels
        editable_item.save()

    def close(self, item):
        item.state_event = 'close'
        item.save()

    def get_user(self, username):
        user = self.gl.users.list(search=username)
        if len(user) == 0:
            logging.error(username + " user not found")
            return
        return user[0]

    def get_project_hooks(self, repo_url):
        p = self.get_project(repo_url)
        if p is None:
            return []
        return p.hooks.list(per_page=100)

    def create_project_hook(self, repo_url, data):
        p = self.get_project(repo_url)
        if p is None:
            return
        url = data['job_url']
        trigger = data['trigger']
        hook = {
            'url': url,
            'enable_ssl_verification': 1,
            'note_events': int(trigger == 'mr'),
            'push_events': int(trigger == 'push'),
            'merge_requests_events': int(trigger == 'mr'),
        }
        p.hooks.create(hook)

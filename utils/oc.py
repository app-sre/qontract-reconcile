from subprocess import Popen, PIPE
import json

import utils.vault_client as vault_client
from utils.jump_host import JumpHostSSH
from utils.retry import retry


class StatusCodeError(Exception):
    pass


class NoOutputError(Exception):
    pass


class JSONParsingError(Exception):
    pass


class OC(object):
    def __init__(self, server, token, jh=None):
        oc_base_cmd = ['oc', '--server', server, '--token', token]

        if jh is not None:
            self.jump_host = JumpHostSSH(jh)
            oc_base_cmd = self.jump_host.get_ssh_base_cmd() + oc_base_cmd

        self.oc_base_cmd = oc_base_cmd

    def whoami(self):
        return self._run(['whoami'])

    def cleanup(self):
        if hasattr(self, 'jump_host') and \
                isinstance(self.jump_host, JumpHostSSH):
            self.jump_host.cleanup()

    def get_items(self, kind, **kwargs):
        cmd = ['get', kind, '-o', 'json']

        if 'namespace' in kwargs:
            namespace = kwargs['namespace']
            if not self.project_exists(namespace):
                return []
            cmd.extend(['-n', namespace])

        if 'labels' in kwargs:
            labels_list = [
                "{}={}".format(k, v)
                for k, v in kwargs.get('labels').items()
            ]

            cmd.append('-l')
            cmd.append(','.join(labels_list))

        items_list = self._run_json(cmd)

        items = items_list.get('items')
        if items is None:
            raise Exception("Expecting items")

        return items

    def get(self, namespace, kind, name):
        cmd = ['get', '-o', 'json', kind, name]
        if namespace is not None:
            cmd.extend(['-n', namespace])
        return self._run_json(cmd)

    def get_all(self, kind, all_namespaces=False):
        cmd = ['get', '-o', 'json', kind]
        if all_namespaces:
            cmd.append('--all-namespaces')
        return self._run_json(cmd)

    def apply(self, namespace, resource):
        cmd = ['apply', '-n', namespace, '-f', '-']
        self._run(cmd, stdin=resource)

    def delete(self, namespace, kind, name):
        cmd = ['delete', '-n', namespace, kind, name]
        self._run(cmd)

    def project_exists(self, name):
        try:
            self.get(None, 'Project', name)
        except StatusCodeError as e:
            if 'NotFound' in e.message:
                return False
            else:
                raise e
        return True

    def new_project(self, namespace):
        cmd = ['new-project', namespace]
        self._run(cmd)

    def delete_project(self, namespace):
        cmd = ['delete', 'project', namespace]
        self._run(cmd)

    def get_group_if_exists(self, name):
        try:
            return self.get(None, 'Group', name)
        except StatusCodeError as e:
            if 'NotFound' in e.message:
                return None
            else:
                raise e

    def create_group(self, group):
        cmd = ['adm', 'groups', 'new', group]
        self._run(cmd)

    def delete_group(self, group):
        cmd = ['delete', 'group', group]
        self._run(cmd)

    def get_users(self):
        return self.get_all('Users')['items']

    def delete_user(self, user):
        cmd = ['delete', 'user', user]
        self._run(cmd)

    def add_user_to_group(self, group, user):
        cmd = ['adm', 'groups', 'add-users', group, user]
        self._run(cmd)

    def del_user_from_group(self, group, user):
        cmd = ['adm', 'groups', 'remove-users', group, user]
        self._run(cmd)

    def add_role_to_user(self, namespace, role, user, kind):
        if kind == 'ServiceAccount':
            user = self.get_service_account_username(user)
        cmd = ['policy', '-n', namespace, 'add-role-to-user', role, user]
        self._run(cmd)

    def remove_role_from_user(self, namespace, role, user, kind):
        if kind == 'ServiceAccount':
            user = self.get_service_account_username(user)
        cmd = ['policy', '-n', namespace, 'remove-role-from-user', role, user]
        self._run(cmd)

    @staticmethod
    def get_service_account_username(user):
        namespace = user.split('/')[0]
        name = user.split('/')[1]
        return "system:serviceaccount:{}:{}".format(namespace, name)

    @retry(exceptions=(StatusCodeError, NoOutputError))
    def _run(self, cmd, **kwargs):
        if kwargs.get('stdin'):
            stdin = PIPE
            stdin_text = kwargs.get('stdin')
        else:
            stdin = None
            stdin_text = None

        p = Popen(
            self.oc_base_cmd + cmd,
            stdin=stdin,
            stdout=PIPE,
            stderr=PIPE
        )
        out, err = p.communicate(stdin_text)

        code = p.returncode

        if code != 0:
            raise StatusCodeError(err)

        if not out:
            raise NoOutputError(err)

        return out.strip()

    def _run_json(self, cmd):
        out = self._run(cmd)

        try:
            out_json = json.loads(out)
        except ValueError as e:
            raise JSONParsingError(out + "\n" + e.message)

        return out_json


class OC_Map(object):
    """OC_Map gets a GraphQL query results list as input
    and initiates a dictionary of OC clients per cluster.

    The input must contain either 'clusters' or 'namespaces', but not both.

    In case a cluster does not have an automation token
    the OC client will be initiated to False.
    """
    def __init__(self, clusters=None, namespaces=None, managed_only=False):
        self.oc_map = {}
        self.managed_only = managed_only

        if clusters and namespaces:
            raise KeyError('expected only one of clusters or namespaces.')
        elif clusters:
            for cluster_info in clusters:
                self.init_oc_client(cluster_info)
        elif namespaces:
            for namespace_info in namespaces:
                cluster_info = namespace_info['cluster']
                self.init_oc_client(cluster_info)
        else:
            raise KeyError('expected one of clusters or namespaces.')

    def init_oc_client(self, cluster_info):
        cluster = cluster_info['name']
        if self.oc_map.get(cluster):
            return
        if self.managed_only and cluster_info.get('unManaged'):
            return

        automation_token = cluster_info.get('automationToken')
        if automation_token is None:
            self.oc_map[cluster] = False
        else:
            server_url = cluster_info['serverUrl']
            token = vault_client.read(automation_token)
            jump_host = cluster_info.get('jumpHost')
            self.oc_map[cluster] = OC(server_url, token, jump_host)

    def get(self, cluster):
        return self.oc_map[cluster]

    def clusters(self):
        return [k for k, v in self.oc_map.items() if v]

    def cleanup(self):
        for oc in self.oc_map.values():
            if oc:
                oc.cleanup()

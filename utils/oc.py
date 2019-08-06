from subprocess import Popen, PIPE
import json
import time

from utils.jump_host import JumpHostSSH
from retry import retry


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

    def add_user_to_group(self, group, user):
        cmd = ['adm', 'groups', 'add-users', group, user]
        self._run(cmd)

    def del_user_from_group(self, group, user):
        cmd = ['adm', 'groups', 'remove-users', group, user]
        self._run(cmd)

    @retry()
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

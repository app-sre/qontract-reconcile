from subprocess import Popen, PIPE
import json

from utils.jump_host import JumpHostSSH


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
            cmd.append('-n')
            cmd.append(kwargs['namespace'])

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
        cmd = ['get', '-o', 'json', '-n', namespace, kind,
               name]
        if namespace is not None:
            cmd.append(['-n', namespace])
        return self._run_json(cmd)

    def apply(self, namespace, resource):
        cmd = ['apply', '-n', namespace, '-f', '-']
        self._run(cmd, stdin=resource)

    def delete(self, namespace, kind, name):
        cmd = ['delete', '-n', namespace, kind, name]
        self._run(cmd)

    def new_project(self, namespace):
        cmd = ['new-project', namespace]
        self._run(cmd)

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

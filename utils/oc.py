from subprocess import Popen, PIPE
import json
import os


class StatusCodeError(Exception):
    pass


class NoOutputError(Exception):
    pass


class JSONParsingError(Exception):
    pass


class OC(object):
    def __init__(self, server, token, jh_data=None):
        ssh_base_cmd = self.init_ssh_base_cmd(jh_data)
        self.oc_base_cmd = ssh_base_cmd + \
            ['oc', '--server', server, '--token', token]

    def whoami(self):
        return self._run(['whoami'])

    def init_ssh_base_cmd(self, jh_data):
        if jh_data is None:
            return []

        import tempfile
        import base64

        hostname = jh_data['hostname']
        port = jh_data['port']
        identity = base64.b64decode(jh_data['identity'])
        user = jh_data['user']
        self.identity_dir = tempfile.mkdtemp()
        identity_file = self.identity_dir + '/id'
        with open(identity_file, 'w') as f:
            f.write(identity)
        os.chmod(identity_file, 0o600)
        user_host = '{}@{}'.format(user, hostname)
        return ['ssh', '-i', identity_file, '-p', port, user_host]

    def cleanup(self):
        if hasattr(self, 'identity_dir'):
            import shutil

            shutil.rmtree(self.identity_dir)

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
        return self._run_json(cmd)

    def apply(self, namespace, resource):
        cmd = ['apply', '-n', namespace, '-f', '-']
        self._run(cmd, stdin=resource)

    def delete(self, namespace, kind, name):
        cmd = ['delete', '-n', namespace, kind, name]
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

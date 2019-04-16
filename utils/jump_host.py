import tempfile
import base64
import shutil
import os

from sshtunnel import SSHTunnelForwarder

import utils.vault_client as vault_client


class JumpHost(object):
    def __init__(self, jh):
        self.hostname = jh['hostname']
        self.user = jh['user']
        self.port = '22' if jh['port'] is None else jh['port']
        self.identity = self.get_identity_from_vault(jh)

        self.init_ssh_base_cmd()
        self.init_ssh_server()

    def get_identity_from_vault(self, jh):
        jh_identity = jh['identity']
        identity = \
            vault_client.read(jh_identity['path'], jh_identity['field'])
        if jh_identity['format'] == 'base64':
            identity = base64.b64decode(identity)
        return identity

    def init_ssh_base_cmd(self):
        identity_file = self.init_identity_file()
        user_host = '{}@{}'.format(self.user, self.hostname)

        self.set_ssh_base_cmd([
            'ssh', '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null', '-o', 'LogLevel=ERROR',
            '-i', identity_file, '-p', self.port, user_host])

    def init_ssh_server(self):
        identity_file = self.init_identity_file()
        local_host = '127.0.0.1'
        local_port = 5000
        server = SSHTunnelForwarder(
            (self.hostname, self.port),
            ssh_username=self.user,
            ssh_private_key=identity_file,
            remote_bind_address=(local_host, local_port),
            local_bind_address=(local_host, local_port),
        )

        self.set_ssh_server(server)

    def init_identity_file(self):
        self._identity_dir = tempfile.mkdtemp()
        identity_file = self._identity_dir + '/id'
        with open(identity_file, 'w') as f:
            f.write(self.identity)
        os.chmod(identity_file, 0o600)
        return identity_file

    def get_ssh_base_cmd(self):
        return self.ssh_base_cmd

    def set_ssh_base_cmd(self, cmd):
        self.ssh_base_cmd = cmd

    def get_ssh_server(self):
        return self.ssh_server

    def set_ssh_server(self, server):
        self.ssh_server = server

    def cleanup(self):
        shutil.rmtree(self._identity_dir)


class DummySSHServer(object):
    def __init__(self, dummy_resource=None):
        self.dummy_resource = dummy_resource

    def __enter__(self):
        return self.dummy_resource

    def __exit__(self, *args):
        pass

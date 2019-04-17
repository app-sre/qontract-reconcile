import tempfile
import base64
import shutil
import os
import requests
import warnings
import logging

import jumpssh

import utils.gql as gql
import utils.vault_client as vault_client


class FetchResourceError(Exception):
    def __init__(self, msg):
        super(FetchResourceError, self).__init__(
            "error fetching resource: " + str(msg)
        )


class HTTPStatusCodeError(Exception):
    def __init__(self, msg):
        super(HTTPStatusCodeError, self).__init__(
            "HTTP status code error: " + str(msg)
        )


class JumpHostBase(object):
    def __init__(self, jh):
        self.hostname = jh['hostname']
        self.user = jh['user']
        self.port = 22 if jh['port'] is None else jh['port']
        self.identity = self.get_identity_from_vault(jh)

        self.init_identity_file()

    def get_identity_from_vault(self, jh):
        jh_identity = jh['identity']
        identity = \
            vault_client.read(jh_identity['path'], jh_identity['field'])
        if jh_identity['format'] == 'base64':
            identity = base64.b64decode(identity)
        return identity

    def init_identity_file(self):
        self._identity_dir = tempfile.mkdtemp()

        identity_file = self._identity_dir + '/id'
        with open(identity_file, 'w') as f:
            f.write(self.identity)
        os.chmod(identity_file, 0o600)
        self.identity_file = identity_file

    def cleanup(self):
        shutil.rmtree(self._identity_dir)


class JumpHostSSH(JumpHostBase):
    def __init__(self, jh):
        JumpHostBase.__init__(self, jh)

        self.known_hosts = self.get_known_hosts(jh)
        self.init_known_hosts_file()

    def get_known_hosts(self, jh):
        known_hosts_path = jh['knownHosts']
        gqlapi = gql.get_api()

        try:
            known_hosts = gqlapi.get_resource(known_hosts_path)
        except gql.GqlApiError as e:
            raise FetchResourceError(e.message)
        return known_hosts['content']

    def init_known_hosts_file(self):
        known_hosts_file = self._identity_dir + '/known_hosts'
        with open(known_hosts_file, 'w') as f:
            f.write(self.known_hosts)
        os.chmod(known_hosts_file, 0o600)
        self.known_hosts_file = known_hosts_file

    def get_ssh_base_cmd(self):
        user_host = '{}@{}'.format(self.user, self.hostname)

        return [
            'ssh',
            '-o', 'StrictHostKeyChecking=yes',
            '-o', 'UserKnownHostsFile={}'.format(self.known_hosts_file),
            '-i', self.identity_file, '-p', str(self.port), user_host]


# The following line will supress CryptographyDeprecationWarning
warnings.filterwarnings(action='ignore', module='.*paramiko.*')


class JumpHostSSHRestApi(JumpHostBase):
    def __init__(self, jh):
        JumpHostBase.__init__(self, jh)

        self.init_ssh_session()
        self.default_logging = logging.getLogger().level

    def __enter__(self):
        logging.getLogger().setLevel(logging.WARNING)
        gateway_session = self.get_ssh_session().open()
        return jumpssh.RestSshClient(gateway_session, silent=True)

    def __exit__(self, *args):
        self.get_ssh_session().close()
        logging.getLogger().setLevel(self.default_logging)

    def init_ssh_session(self):
        session = jumpssh.SSHSession(
            self.hostname,
            self.user,
            private_key_file=self.identity_file,
            port=self.port,
        )
        self.ssh_session = session

    def get_ssh_session(self):
        return self.ssh_session


class DummySSHServer(object):
    def __init__(self, dummy_resource=None):
        self.dummy_resource = dummy_resource

    def __enter__(self):
        return requests

    def __exit__(self, *args):
        pass

    def cleanup(self):
        pass

    def raise_for_status(self, response):
        response.raise_for_status()

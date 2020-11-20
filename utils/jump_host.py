import tempfile
import shutil
import os

import utils.gql as gql
from utils.secret_reader import SecretReader

from reconcile.exceptions import FetchResourceError


class HTTPStatusCodeError(Exception):
    def __init__(self, msg):
        super(HTTPStatusCodeError, self).__init__(
            "HTTP status code error: " + str(msg)
        )


class JumpHostBase(object):
    def __init__(self, jh, settings=None):
        self.hostname = jh['hostname']
        self.user = jh['user']
        self.port = 22 if jh['port'] is None else jh['port']
        secret_reader = SecretReader(settings=settings)
        self.identity = secret_reader.read(jh['identity'])
        self.init_identity_file()

    def init_identity_file(self):
        self._identity_dir = tempfile.mkdtemp()

        identity_file = self._identity_dir + '/id'
        with open(identity_file, 'w') as f:
            f.write(self.identity.decode('utf-8'))
        os.chmod(identity_file, 0o600)
        self.identity_file = identity_file

    def cleanup(self):
        shutil.rmtree(self._identity_dir)


class JumpHostSSH(JumpHostBase):
    def __init__(self, jh, settings=None):
        JumpHostBase.__init__(self, jh, settings=settings)

        self.known_hosts = self.get_known_hosts(jh)
        self.init_known_hosts_file()

    def get_known_hosts(self, jh):
        known_hosts_path = jh['knownHosts']
        gqlapi = gql.get_api()

        try:
            known_hosts = gqlapi.get_resource(known_hosts_path)
        except gql.GqlGetResourceError as e:
            raise FetchResourceError(str(e))
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
            '-o', 'ControlMaster=auto',
            '-o', 'ControlPath=/tmp/controlmaster-%r@%h:%p',
            '-o', 'ControlPersist=600',
            '-o', 'StrictHostKeyChecking=yes',
            '-o', 'UserKnownHostsFile={}'.format(self.known_hosts_file),
            '-i', self.identity_file, '-p', str(self.port), user_host]

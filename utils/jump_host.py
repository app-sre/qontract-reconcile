import utils.vault_client as vault_client


class JumpHost(object):
    def __init__(self, jh):
        self.hostname = jh['hostname']
        self.user = jh['user']
        self.port = '22' if jh['port'] is None else jh['port']
        self.identity = self.get_identity_from_vault(jh)

        self.init_ssh_base_cmd()

    def get_identity_from_vault(self, jh):
        jh_identity = jh['identity']
        identity = \
            vault_client.read(jh_identity['path'], jh_identity['field'])
        if jh_identity['format'] == 'base64':
            import base64

            identity = base64.b64decode(identity)
        return identity

    def init_ssh_base_cmd(self):
        import tempfile
        import os

        self._identity_dir = tempfile.mkdtemp()
        identity_file = self._identity_dir + '/id'
        with open(identity_file, 'w') as f:
            f.write(self.identity)
        os.chmod(identity_file, 0o600)
        user_host = '{}@{}'.format(self.user, self.hostname)

        self.ssh_base_cmd = \
            ['ssh', '-i', identity_file, '-p', self.port, user_host]

    def cleanup(self):
        import shutil

        shutil.rmtree(self._identity_dir)

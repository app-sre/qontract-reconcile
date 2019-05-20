import toml
import json
import requests

import utils.vault_client as vault_client

class JenkinsApi(object):
    """Wrapper around Jenkins API calls"""

    def __init__(self, token):
        token_path = token['path']
        token_field = token['field']
        token_config = vault_client.read(token_path, token_field)
        config = toml.loads(token_config)

        self.url = config['jenkins']['url']
        self.user = config['jenkins']['user']
        self.password = config['jenkins']['password']

    def get_all_roles(self):
        url = "{}/role-strategy/strategy/getAllRoles".format(self.url)
        res = requests.get(url, verify=False, auth=(self.user, self.password))

        return res.json()

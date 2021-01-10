import toml
import requests
import logging

from utils.secret_reader import SecretReader


class JenkinsApi(object):
    """Wrapper around Jenkins API calls"""

    def __init__(self, token, ssl_verify=True, settings=None):
        secret_reader = SecretReader(settings=settings)
        token_config = secret_reader.read(token)
        config = toml.loads(token_config)

        self.url = config['jenkins']['url']
        self.user = config['jenkins']['user']
        self.password = config['jenkins']['password']
        self.ssl_verify = ssl_verify
        self.should_restart = False
        self.settings = settings

    def get_job_names(self):
        url = f"{self.url}/api/json?tree=jobs[name]"
        res = requests.get(
            url,
            verify=self.ssl_verify,
            auth=(self.user, self.password)
        )

        res.raise_for_status()
        job_names = [r['name'] for r in res.json()['jobs']]
        return job_names

    def delete_job(self, job_name):
        kwargs = self.get_crumb_kwargs()

        url = f"{self.url}/job/{job_name}/doDelete"
        res = requests.post(
            url,
            verify=self.ssl_verify,
            auth=(self.user, self.password),
            **kwargs
        )

        res.raise_for_status()

    def get_all_roles(self):
        url = "{}/role-strategy/strategy/getAllRoles".format(self.url)
        res = requests.get(
            url,
            verify=self.ssl_verify,
            auth=(self.user, self.password)
        )

        res.raise_for_status()
        return res.json()

    def assign_role_to_user(self, role, user):
        url = "{}/role-strategy/strategy/assignRole".format(self.url)
        data = {
            'type': 'globalRoles',
            'roleName': role,
            'sid': user
        }
        res = requests.post(
            url,
            verify=self.ssl_verify,
            data=data,
            auth=(self.user, self.password)
        )

        res.raise_for_status()

    def unassign_role_from_user(self, role, user):
        url = "{}/role-strategy/strategy/unassignRole".format(self.url)
        data = {
            'type': 'globalRoles',
            'roleName': role,
            'sid': user
        }
        res = requests.post(
            url,
            verify=self.ssl_verify,
            data=data,
            auth=(self.user, self.password)
        )

        res.raise_for_status()

    def list_plugins(self):
        url = "{}/pluginManager/api/json?depth=1".format(self.url)

        res = requests.get(
            url,
            verify=self.ssl_verify,
            auth=(self.user, self.password)
        )

        res.raise_for_status()
        return res.json()['plugins']

    def install_plugin(self, name):
        self.should_restart = True
        header = {"Content-Type": "text/xml"}
        url = "{}/pluginManager/installNecessaryPlugins".format(self.url)
        data = \
            '<jenkins><install plugin="{}@current" /></jenkins>'.format(name)
        res = requests.post(
            url,
            verify=self.ssl_verify,
            data=data,
            headers=header,
            auth=(self.user, self.password)
        )

        res.raise_for_status()

    def safe_restart(self, force_restart=False):
        url = "{}/safeRestart".format(self.url)
        if self.should_restart or force_restart:
            logging.debug('performing safe restart. ' +
                          'should_restart={}, ' +
                          'force_restart={}.'.format(self.should_restart,
                                                     force_restart))
            res = requests.post(
                url,
                verify=self.ssl_verify,
                auth=(self.user, self.password)
            )

            res.raise_for_status()

    def get_build_history(self, job_name, time_limit):
        url = f"{self.url}/job/{job_name}/api/json" + \
            f"?tree=builds[timestamp,result]"
        res = requests.get(
            url,
            verify=self.ssl_verify,
            auth=(self.user, self.password)
        )

        res.raise_for_status()
        return [b['result'] for b in res.json()['builds']
                if time_limit < self.timestamp_seconds(b['timestamp'])]

    def is_job_running(self, job_name):
        url = f"{self.url}/job/{job_name}/lastBuild/api/json"
        res = requests.get(
            url,
            verify=self.ssl_verify,
            auth=(self.user, self.password)
        )

        if res.status_code == 404:
            # assuming the job exists due to the nature of our integrations,
            # this means the job was never triggered, which is fine.
            return False

        res.raise_for_status()
        return res.json()['building'] is True

    def get_crumb_kwargs(self):
        try:
            crumb_url = f"{self.url}/crumbIssuer/api/json"
            res = requests.get(
                crumb_url,
                verify=self.ssl_verify,
                auth=(self.user, self.password)
            )
            body = res.json()
            kwargs = {
                'headers': {body['crumbRequestField']: body['crumb']},
                'cookies': res.cookies
            }
        except Exception:
            kwargs = {}

        return kwargs

    def trigger_job(self, job_name):
        kwargs = self.get_crumb_kwargs()

        url = f"{self.url}/job/{job_name}/build"
        res = requests.post(
            url,
            verify=self.ssl_verify,
            auth=(self.user, self.password),
            **kwargs
        )

        res.raise_for_status()

    @staticmethod
    def timestamp_seconds(timestamp):
        return int(timestamp / 1000)

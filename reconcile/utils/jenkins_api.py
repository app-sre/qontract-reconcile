import logging
from typing import Any

import requests
import toml
import yaml
from sretoolbox.utils import retry

from reconcile.utils.secret_reader import SecretReader


class JenkinsApi:
    """Wrapper around Jenkins API calls"""

    @staticmethod
    def init_jenkins_from_secret(
        secret_reader: SecretReader, secret, ssl_verify=True
    ) -> "JenkinsApi":
        token_config = secret_reader.read(secret)
        config = toml.loads(token_config)
        return JenkinsApi(
            config["jenkins"]["url"],
            config["jenkins"]["user"],
            config["jenkins"]["password"],
            ssl_verify=ssl_verify,
        )

    def __init__(self, url: str, user: str, password: str, ssl_verify=True):
        self.url = url
        self.user = user
        self.password = password
        self.ssl_verify = ssl_verify
        self.should_restart = False

    def get_jcasc_config(self) -> dict[str, Any]:
        url = f"{self.url}/manage/configuration-as-code/export"
        res = requests.post(
            url,
            verify=self.ssl_verify,
            auth=(self.user, self.password),
            timeout=60,
        )
        res.raise_for_status()
        return yaml.safe_load(res.text)

    def apply_jcasc_config(self, config: dict[str, Any]):
        url = f"{self.url}/manage/configuration-as-code/apply"
        res = requests.post(
            url,
            verify=self.ssl_verify,
            auth=(self.user, self.password),
            data=yaml.safe_dump(config),
            timeout=60,
        )
        res.raise_for_status()

    def get_job_names(self):
        url = f"{self.url}/api/json?tree=jobs[name]"
        res = requests.get(
            url, verify=self.ssl_verify, auth=(self.user, self.password), timeout=60
        )

        res.raise_for_status()
        job_names = [r["name"] for r in res.json()["jobs"]]
        return job_names

    @retry()
    def get_jobs_state(self):
        url = f"{self.url}/api/json?tree=jobs[name,builds[number,result]]"
        res = requests.get(
            url, verify=self.ssl_verify, auth=(self.user, self.password), timeout=60
        )

        res.raise_for_status()
        jobs_state = {}
        for r in res.json()["jobs"]:
            job_name = r["name"]
            builds = r.get("builds", [])
            jobs_state[job_name] = builds

        return jobs_state

    def delete_build(self, job_name, build_id):
        url = f"{self.url}/job/{job_name}/{build_id}/doDelete"
        res = requests.post(
            url, verify=self.ssl_verify, auth=(self.user, self.password), timeout=60
        )
        res.raise_for_status()

    def delete_job(self, job_name):
        kwargs = self.get_crumb_kwargs()

        url = f"{self.url}/job/{job_name}/doDelete"
        res = requests.post(
            url,
            verify=self.ssl_verify,
            auth=(self.user, self.password),
            timeout=60,
            **kwargs,
        )

        res.raise_for_status()

    def get_all_roles(self):
        url = "{}/role-strategy/strategy/getAllRoles".format(self.url)
        res = requests.get(
            url, verify=self.ssl_verify, auth=(self.user, self.password), timeout=60
        )

        res.raise_for_status()
        return res.json()

    def assign_role_to_user(self, role, user):
        url = "{}/role-strategy/strategy/assignRole".format(self.url)
        data = {"type": "globalRoles", "roleName": role, "sid": user}
        res = requests.post(
            url,
            verify=self.ssl_verify,
            data=data,
            auth=(self.user, self.password),
            timeout=60,
        )

        res.raise_for_status()

    def unassign_role_from_user(self, role, user):
        url = "{}/role-strategy/strategy/unassignRole".format(self.url)
        data = {"type": "globalRoles", "roleName": role, "sid": user}
        res = requests.post(
            url,
            verify=self.ssl_verify,
            data=data,
            auth=(self.user, self.password),
            timeout=60,
        )

        res.raise_for_status()

    def list_plugins(self):
        url = "{}/pluginManager/api/json?depth=1".format(self.url)

        res = requests.get(
            url, verify=self.ssl_verify, auth=(self.user, self.password), timeout=60
        )

        res.raise_for_status()
        return res.json()["plugins"]

    def install_plugin(self, name):
        self.should_restart = True
        header = {"Content-Type": "text/xml"}
        url = "{}/pluginManager/installNecessaryPlugins".format(self.url)
        data = '<jenkins><install plugin="{}@current" /></jenkins>'.format(name)
        res = requests.post(
            url,
            verify=self.ssl_verify,
            data=data,
            headers=header,
            auth=(self.user, self.password),
            timeout=60,
        )

        res.raise_for_status()

    def safe_restart(self, force_restart=False):
        url = "{}/safeRestart".format(self.url)
        if self.should_restart or force_restart:
            logging.debug(
                "performing safe restart. "
                f"should_restart={self.should_restart}, "
                f"force_restart={force_restart}."
            )
            res = requests.post(
                url, verify=self.ssl_verify, auth=(self.user, self.password), timeout=60
            )

            res.raise_for_status()

    def get_builds(self, job_name):
        url = (
            f"{self.url}/job/{job_name}/api/json"
            + "?tree=allBuilds[timestamp,result,id]"
        )
        res = requests.get(
            url, verify=self.ssl_verify, auth=(self.user, self.password), timeout=60
        )
        res.raise_for_status()
        logging.debug(f"Job: {job_name} Builds: {res.json()}")
        try:
            return res.json()["allBuilds"]
        except KeyError:
            return []

    def get_build_history(self, job_name, time_limit):
        return [
            b["result"]
            for b in self.get_builds(job_name)
            if time_limit < self.timestamp_seconds(b["timestamp"])
        ]

    def is_job_running(self, job_name):
        url = f"{self.url}/job/{job_name}/lastBuild/api/json"
        res = requests.get(
            url, verify=self.ssl_verify, auth=(self.user, self.password), timeout=60
        )

        if res.status_code == 404:
            # assuming the job exists due to the nature of our integrations,
            # this means the job was never triggered, which is fine.
            return False

        res.raise_for_status()
        return res.json()["building"] is True

    def get_crumb_kwargs(self):
        try:
            crumb_url = f"{self.url}/crumbIssuer/api/json"
            res = requests.get(
                crumb_url,
                verify=self.ssl_verify,
                auth=(self.user, self.password),
                timeout=60,
            )
            body = res.json()
            kwargs = {
                "headers": {body["crumbRequestField"]: body["crumb"]},
                "cookies": res.cookies,
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
            timeout=60,
            **kwargs,
        )

        res.raise_for_status()

    @staticmethod
    def timestamp_seconds(timestamp):
        return int(timestamp / 1000)

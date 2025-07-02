import logging
from collections.abc import Mapping
from typing import Any, NotRequired, Self, TypedDict

import requests
import toml
import yaml
from sretoolbox.utils import retry

from reconcile.utils.secret_reader import SecretReaderBase


class JobBuildState(TypedDict):
    _class: NotRequired[str]
    number: int
    result: NotRequired[str | None]
    actions: NotRequired[list]
    commit_sha: NotRequired[str]


class JenkinsApi:
    """Wrapper around Jenkins API calls"""

    @classmethod
    def init_jenkins_from_secret(
        cls,
        secret_reader: SecretReaderBase,
        secret: Mapping[str, Any],
        ssl_verify: bool = True,
    ) -> Self:
        token_config = secret_reader.read(secret)
        config = toml.loads(token_config)
        return cls(
            config["jenkins"]["url"],
            config["jenkins"]["user"],
            config["jenkins"]["password"],
            ssl_verify=ssl_verify,
        )

    def __init__(
        self,
        url: str,
        user: str,
        password: str,
        ssl_verify: bool = True,
    ):
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

    def apply_jcasc_config(self, config: dict[str, Any]) -> None:
        url = f"{self.url}/manage/configuration-as-code/apply"
        res = requests.post(
            url,
            verify=self.ssl_verify,
            auth=(self.user, self.password),
            data=yaml.safe_dump(config),
            timeout=60,
        )
        res.raise_for_status()

    def get_job_names(self) -> list[str]:
        url = f"{self.url}/api/json?tree=jobs[name]"
        res = requests.get(
            url, verify=self.ssl_verify, auth=(self.user, self.password), timeout=60
        )

        res.raise_for_status()
        job_names = [r["name"] for r in res.json()["jobs"]]
        return job_names

    @staticmethod
    def _get_commit_sha_from_build(build: Mapping[str, Any]) -> str | None:
        for action in reversed(build.get("actions", [])):
            if revision := action.get("lastBuiltRevision"):
                return revision["SHA1"]
        return None

    def _build_job_build_state(self, build: Mapping) -> JobBuildState:
        job_build_state = JobBuildState(number=build["number"])
        if "_class" in build:
            job_build_state["_class"] = build["_class"]
        if "actions" in build:
            job_build_state["actions"] = build["actions"]
        if "result" in build:
            job_build_state["result"] = build["result"]
        if commit_sha := self._get_commit_sha_from_build(build):
            job_build_state["commit_sha"] = commit_sha
        return job_build_state

    @retry()
    def get_jobs_state(self) -> dict[str, list[JobBuildState]]:
        url = f"{self.url}/api/json?tree=jobs[name,builds[number,result,actions[lastBuiltRevision[SHA1]]]]"
        res = requests.get(
            url, verify=self.ssl_verify, auth=(self.user, self.password), timeout=60
        )

        res.raise_for_status()
        jobs = res.json().get("jobs") or []
        return {
            job["name"]: list(
                map(
                    self._build_job_build_state,
                    job.get("builds", []),
                )
            )
            for job in jobs
        }

    def delete_build(self, job_name: str, build_id: str) -> None:
        url = f"{self.url}/job/{job_name}/{build_id}/doDelete"
        res = requests.post(
            url, verify=self.ssl_verify, auth=(self.user, self.password), timeout=60
        )
        res.raise_for_status()

    def get_all_roles(self) -> dict[str, Any]:
        url = f"{self.url}/role-strategy/strategy/getAllRoles"
        res = requests.get(
            url, verify=self.ssl_verify, auth=(self.user, self.password), timeout=60
        )

        res.raise_for_status()
        return res.json()

    def assign_role_to_user(self, role: str, user: str) -> None:
        url = f"{self.url}/role-strategy/strategy/assignRole"
        data = {"type": "globalRoles", "roleName": role, "sid": user}
        res = requests.post(
            url,
            verify=self.ssl_verify,
            data=data,
            auth=(self.user, self.password),
            timeout=60,
        )

        res.raise_for_status()

    def unassign_role_from_user(self, role: str, user: str) -> None:
        url = f"{self.url}/role-strategy/strategy/unassignRole"
        data = {"type": "globalRoles", "roleName": role, "sid": user}
        res = requests.post(
            url,
            verify=self.ssl_verify,
            data=data,
            auth=(self.user, self.password),
            timeout=60,
        )

        res.raise_for_status()

    def safe_restart(self, force_restart: bool = False) -> None:
        url = f"{self.url}/safeRestart"
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

    def get_builds(self, job_name: str) -> list[dict[str, Any]]:
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

    def get_build_history(self, job_name: str, time_limit: int) -> list[str]:
        return [
            b["result"]
            for b in self.get_builds(job_name)
            if time_limit < self.timestamp_seconds(b["timestamp"])
        ]

    def is_job_running(self, job_name: str) -> bool:
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

    def get_crumb_kwargs(self) -> dict[str, Any]:
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

    def trigger_job(self, job_name: str) -> None:
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
    def timestamp_seconds(timestamp: float) -> int:
        return int(timestamp / 1000)

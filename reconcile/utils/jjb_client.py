import difflib
import filecmp
import logging
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from os import path
from pathlib import Path
from subprocess import (
    PIPE,
    STDOUT,
    CalledProcessError,
)
from typing import Any

import yaml
from jenkins_jobs.errors import JenkinsJobsException
from jenkins_jobs.loader import load_files
from jenkins_jobs.roots import Roots
from sretoolbox.utils import retry

from reconcile.utils import throughput
from reconcile.utils.helpers import toggle_logger
from reconcile.utils.json import json_dumps
from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.state import State
from reconcile.utils.vcs import GITHUB_BASE_URL

JJB_INI = "[jenkins]\nurl = https://JENKINS_URL"


class JJB:
    """Wrapper around Jenkins Jobs"""

    def __init__(
        self,
        configs: list[dict[str, Any]],
        ssl_verify: bool = True,
        secret_reader: SecretReaderBase | None = None,
        print_only: bool = False,
    ) -> None:
        self.print_only = print_only
        self.secret_reader = secret_reader
        if not self.print_only and self.secret_reader is None:
            raise ValueError("secret_reader must be provided if print_only is False")
        self.collect_configs(configs)
        self.modify_logger()
        self.python_https_verify = str(int(ssl_verify))

    def collect_configs(self, configs: list[dict[str, Any]]) -> None:
        instances = {
            c["instance"]["name"]: {
                "serverUrl": c["instance"]["serverUrl"],
                "token": c["instance"]["token"],
                "delete_method": c["instance"]["deleteMethod"],
            }
            for c in configs
        }

        working_dirs = {}
        instance_urls = {}
        for name, data in instances.items():
            token = data["token"]
            server_url = data["serverUrl"]
            wd = tempfile.mkdtemp()
            ini = JJB_INI
            if not self.print_only and self.secret_reader:
                ini = self.secret_reader.read(token)
                ini = ini.replace('"', "")
                ini = ini.replace("false", "False")
            ini_file_path = f"{wd}/{name}.ini"
            with open(ini_file_path, "w", encoding="locale") as f:
                f.write(ini)
                f.write("\n")
            working_dirs[name] = wd
            instance_urls[name] = server_url

        self.sort(configs)

        for c in configs:
            instance_name = c["instance"]["name"]
            config = c["config"]
            config_file_path = f"{working_dirs[instance_name]}/config.yaml"
            if config:
                content = yaml.load(config, Loader=yaml.FullLoader)
                if c["type"] == "jobs":
                    for item in content:
                        item["project"]["app_name"] = c["app"]["name"]
                with open(config_file_path, "a", encoding="locale") as f:
                    yaml.dump(content, f)
                    f.write("\n")
            else:
                config = c["config_path"]["content"]
                with open(config_file_path, "a", encoding="locale") as f:
                    f.write(config)
                    f.write("\n")

        self.instances = instances
        self.instance_urls = instance_urls
        self.working_dirs = working_dirs

    def overwrite_configs(self, configs: Mapping[str, str] | State) -> None:
        """This function will override the existing
        config files in the working directories with
        the supplied configs"""
        for name, wd in self.working_dirs.items():
            config_path = f"{wd}/config.yaml"
            with open(config_path, "w", encoding="locale") as f:
                f.write(configs[name])

    def sort(self, configs: list[dict[str, Any]]) -> None:
        configs.sort(key=self.sort_by_name)
        configs.sort(key=lambda x: self.sort_by_type(x) or 0)

    @staticmethod
    def sort_by_type(config: Mapping[str, Any]) -> int:
        if config["type"] == "defaults":
            return 0
        if config["type"] == "global-defaults":
            return 5
        if config["type"] == "views":
            return 10
        if config["type"] == "secrets":
            return 20
        if config["type"] == "base-templates":
            return 30
        if config["type"] == "global-base-templates":
            return 35
        if config["type"] == "job-templates":
            return 40
        if config["type"] == "jobs":
            return 50
        return 100

    @staticmethod
    def sort_by_name(config: Mapping[str, Any]) -> str:
        return config["name"]

    def get_configs(self) -> dict[str, str]:
        """This function gets the configs from the
        working directories"""
        configs = {}
        for name, wd in self.working_dirs.items():
            config_path = f"{wd}/config.yaml"
            with open(config_path, encoding="locale") as f:
                configs[name] = f.read()

        return configs

    def generate(self, io_dir: str, fetch_state: str) -> None:
        """
        Generates job definitions from JJB configs

        :param io_dir: Input/output directory
        :param fetch_state: subdirectory to use ('desired' or 'current')
        """
        for name, wd in self.working_dirs.items():
            ini_path = f"{wd}/{name}.ini"
            config_path = f"{wd}/config.yaml"

            output_dir = path.join(io_dir, "jjb", fetch_state, name)
            args = [
                "--conf",
                ini_path,
                "test",
                config_path,
                "-o",
                output_dir,
                "--config-xml",
            ]
            self.execute(args)
            throughput.change_files_ownership(io_dir)

    def print_diffs(self, io_dir: str, instance_name: str | None = None) -> None:
        """Print the diffs between the current and
        the desired job definitions"""
        current_path = path.join(io_dir, "jjb", "current")
        current_files = self.get_files(current_path, instance_name)
        desired_path = path.join(io_dir, "jjb", "desired")
        desired_files = self.get_files(desired_path, instance_name)

        create = self.compare_files(desired_files, current_files)
        delete = self.compare_files(current_files, desired_files)
        common = self.compare_files(desired_files, current_files, in_op=True)

        self.print_diff(create, desired_path, "create")
        self.print_diff(delete, current_path, "delete")
        self.print_diff(common, desired_path, "update")

    def print_diff(self, files: Iterable[str], replace_path: str, action: str) -> None:
        for f in files:
            if action == "update":
                ft = self.toggle_cd(f)
                equal = filecmp.cmp(f, ft)
                if equal:
                    continue

            instance, *items, _ = f.replace(replace_path + "/", "").split("/")
            if len(items) != 1:
                name = "/".join(items)
                raise ValueError(f"Invalid job name contains '/' in {instance}: {name}")
            item = items[0]
            item_type = ET.parse(f).getroot().tag
            item_type = item_type.replace("hudson.model.ListView", "view")
            item_type = item_type.replace("project", "job")
            logging.info([action, item_type, instance, item])

            if action == "update":
                with open(ft, encoding="locale") as c, open(f, encoding="locale") as d:
                    clines = c.readlines()
                    dlines = d.readlines()

                    differ = difflib.Differ()
                    diff = [
                        ln
                        for ln in differ.compare(clines, dlines)
                        if ln.startswith(("-", "+"))
                    ]
                    logging.debug("DIFF:\n" + "".join(diff))

    def compare_files(
        self,
        from_files: Iterable[str],
        subtract_files: Iterable[str],
        in_op: bool = False,
    ) -> list[str]:
        return [f for f in from_files if (self.toggle_cd(f) in subtract_files) is in_op]

    @staticmethod
    def get_files(search_path: str, instance_name: str | None = None) -> list[str]:
        if instance_name is not None:
            search_path = path.join(search_path, instance_name)
        return [
            path.join(root, f) for root, _, files in os.walk(search_path) for f in files
        ]

    @staticmethod
    def toggle_cd(file_name: str) -> str:
        if "desired" in file_name:
            return file_name.replace("desired", "current")
        return file_name.replace("current", "desired")

    def update(self) -> None:
        for name, wd in self.working_dirs.items():
            ini_path = f"{wd}/{name}.ini"
            config_path = f"{wd}/config.yaml"

            os.environ["PYTHONHTTPSVERIFY"] = self.python_https_verify
            cmd = ["jenkins-jobs", "--conf", ini_path, "update", config_path]
            delete_method = self.instances[name]["delete_method"]
            if delete_method != "manual":
                cmd.append("--delete-old")
            try:
                result = subprocess.run(
                    cmd, check=True, stdout=PIPE, stderr=STDOUT, encoding="utf-8"
                )
                if re.search(r"updated: [1-9]", result.stdout):
                    logging.info(result.stdout)
            except CalledProcessError as ex:
                logging.error(ex.stdout)
                raise

    @staticmethod
    def get_jjb(args: Iterable[str]) -> Any:
        from jenkins_jobs.cli.entry import JenkinsJobs  # noqa: PLC0415

        return JenkinsJobs(args)

    def execute(self, args: Iterable[str]) -> None:
        jjb = self.get_jjb(args)
        with toggle_logger():
            jjb.execute()

    def modify_logger(self) -> None:
        yaml.warnings({"YAMLLoadWarning": False})
        formatter = logging.Formatter("%(levelname)s: %(message)s")
        logger = logging.getLogger()
        logger.handlers[0].setFormatter(formatter)

    def cleanup(self) -> None:
        for wd in self.working_dirs.values():
            shutil.rmtree(wd)

    @retry(exceptions=(JenkinsJobsException))
    def get_jobs(self, wd: str, name: str) -> list[dict[str, Any]]:
        ini_path = f"{wd}/{name}.ini"
        config_path = f"{wd}/config.yaml"

        args = ["--conf", ini_path, "test", config_path]
        jjb = self.get_jjb(args)
        roots = Roots(jjb.jjb_config)
        load_files(jjb.jjb_config, roots, [Path(config_path)])
        job_view_data_list = roots.generate_jobs()
        return [job.data for job in job_view_data_list]

    def get_job_webhooks_data(self) -> dict[str, list[dict[str, Any]]]:
        job_webhooks_data: dict[str, list[dict[str, Any]]] = {}
        for name, wd in self.working_dirs.items():
            jobs = self.get_jobs(wd, name)

            for job in jobs:
                try:
                    project_url_raw = job["properties"][0]["github"]["url"]
                    if project_url_raw.startswith(GITHUB_BASE_URL):
                        continue
                    if str(job.get("disabled")).lower() == "true":
                        continue
                    job_url = "{}/project/{}".format(
                        self.instance_urls[name], job["name"]
                    )
                    project_url = project_url_raw.strip("/").replace(".git", "")
                    trigger = self.get_gitlab_webhook_trigger(job)
                    if not trigger:
                        continue
                    hook = {
                        "job_url": job_url,
                        "trigger": trigger,
                    }
                    job_webhooks_data.setdefault(project_url, [])
                    job_webhooks_data[project_url].append(hook)
                except KeyError:
                    continue

        return job_webhooks_data

    def get_repos(self) -> set[str]:
        repos = set()
        for name, wd in self.working_dirs.items():
            jobs = self.get_jobs(wd, name)
            for job in jobs:
                job_name = job["name"]
                try:
                    repos.add(self.get_repo_url(job))
                except KeyError:
                    logging.debug(f"missing github url: {job_name}")
        return repos

    def get_admins(self) -> set[str]:
        admins = set()
        for name, wd in self.working_dirs.items():
            jobs = self.get_jobs(wd, name)
            for j in jobs:
                try:
                    admins_list = j["triggers"][0]["github-pull-request"]["admin-list"]
                    admins.update(admins_list)
                except (KeyError, TypeError):
                    # no admins, that's fine
                    pass

        return admins

    @staticmethod
    def get_repo_url(job: Mapping[str, Any]) -> str:
        repo_url_raw = job["properties"][0]["github"]["url"]
        return repo_url_raw.strip("/").replace(".git", "")

    @staticmethod
    def get_ref(job: Mapping[str, Any]) -> str:
        return job["scm"][0]["git"]["branches"][0]

    def get_all_jobs(
        self, job_types: Iterable[str] | None = None, instance_name: str | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        if job_types is None:
            job_types = []
        all_jobs: dict[str, list[dict]] = {}
        for name, wd in self.working_dirs.items():
            if instance_name and name != instance_name:
                continue
            logging.debug(f"getting jobs from {name}")
            all_jobs[name] = []
            jobs = self.get_jobs(wd, name)
            for job in jobs:
                job_name = job["name"]
                if not any(job_type in job_name for job_type in job_types):
                    continue
                all_jobs[name].append(job)

        return all_jobs

    def print_jobs(self, job_name: str | None = None) -> None:
        all_jobs: dict[str, list[dict[str, Any]]] = {}
        found = False
        for name, wd in self.working_dirs.items():
            logging.debug(f"getting jobs from {name}")
            all_jobs[name] = []
            jobs = self.get_jobs(wd, name)
            for job in jobs:
                if job_name is not None and job_name not in job["name"]:
                    continue
                all_jobs[name].append(job)
                found = True
        if not found:
            raise ValueError(f"job name {job_name} is not found")
        print(json_dumps(all_jobs, indent=2))

    def get_job_by_repo_url(self, repo_url: str, job_type: str) -> dict[str, Any]:
        for jobs in self.get_all_jobs(job_types=[job_type]).values():
            for job in jobs:
                try:
                    if self.get_repo_url(job).lower() == repo_url.rstrip("/").lower():
                        return job
                except KeyError:
                    # something wrong here. ignore this job
                    pass
        raise ValueError(f"job with {job_type=} and {repo_url=} not found")

    @staticmethod
    def get_trigger_phrases_regex(job: Mapping[str, Any]) -> str | None:
        for trigger in job["triggers"]:
            if "gitlab" in trigger:
                return trigger["gitlab"].get("note-regex")
            if "github-pull-request" in trigger:
                return trigger["github-pull-request"].get("trigger-phrase")
        return None

    @staticmethod
    def get_gitlab_webhook_trigger(job: Mapping[str, Any]) -> list[str]:
        gitlab_triggers = job["triggers"][0]["gitlab"]
        # pr-check job should be triggered by merge request events
        # and certain comments: [test]|/retest|/lgtm|/lgtm cancel|/hold|/hold cancel
        if gitlab_triggers.get("trigger-merge-request"):
            return ["mr", "note"]
        # build main/master job should be triggered by push events
        elif gitlab_triggers.get("trigger-push"):
            return ["push"]
        # On-demand test job should be triggered by special comment
        elif gitlab_triggers.get("trigger-note"):
            return ["note"]
        else:
            return []

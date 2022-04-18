import difflib
import logging
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as et
import json
import re

from os import path
from contextlib import contextmanager
from subprocess import PIPE, STDOUT, CalledProcessError

import filecmp
import yaml

from jenkins_jobs.builder import JenkinsManager
from jenkins_jobs.parser import YamlParser
from jenkins_jobs.registry import ModuleRegistry
from jenkins_jobs.errors import JenkinsJobsException
from sretoolbox.utils import retry

from reconcile.utils import gql
from reconcile.utils import throughput


from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.exceptions import FetchResourceError

JJB_INI = "[jenkins]\nurl = https://JENKINS_URL"


class JJB:  # pylint: disable=too-many-public-methods
    """Wrapper around Jenkins Jobs"""

    def __init__(self, configs, ssl_verify=True, settings=None, print_only=False):
        self.settings = settings
        self.print_only = print_only
        if not print_only:
            self.secret_reader = SecretReader(settings=settings)
        self.collect_configs(configs)
        self.modify_logger()
        self.python_https_verify = str(int(ssl_verify))

    def collect_configs(self, configs):
        gqlapi = gql.get_api()
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
            if not self.print_only:
                ini = self.secret_reader.read(token)
                ini = ini.replace('"', "")
                ini = ini.replace("false", "False")
            ini_file_path = "{}/{}.ini".format(wd, name)
            with open(ini_file_path, "w") as f:
                f.write(ini)
                f.write("\n")
            working_dirs[name] = wd
            instance_urls[name] = server_url

        self.sort(configs)

        for c in configs:
            instance_name = c["instance"]["name"]
            config = c["config"]
            config_file_path = "{}/config.yaml".format(working_dirs[instance_name])
            if config:
                with open(config_file_path, "a") as f:
                    yaml.dump(yaml.load(config, Loader=yaml.FullLoader), f)
                    f.write("\n")
            else:
                config_path = c["config_path"]
                # get config data
                try:
                    config_resource = gqlapi.get_resource(config_path)
                    config = config_resource["content"]
                except gql.GqlGetResourceError as e:
                    raise FetchResourceError(str(e))
                with open(config_file_path, "a") as f:
                    f.write(config)
                    f.write("\n")

        self.instances = instances
        self.instance_urls = instance_urls
        self.working_dirs = working_dirs

    def overwrite_configs(self, configs):
        """This function will override the existing
        config files in the working directories with
        the supplied configs"""
        for name, wd in self.working_dirs.items():
            config_path = "{}/config.yaml".format(wd)
            with open(config_path, "w") as f:
                f.write(configs[name])

    def sort(self, configs):
        configs.sort(key=self.sort_by_name)
        configs.sort(key=self.sort_by_type)

    @staticmethod
    def sort_by_type(config):
        if config["type"] == "defaults":
            return 0
        elif config["type"] == "global-defaults":
            return 5
        elif config["type"] == "views":
            return 10
        elif config["type"] == "secrets":
            return 20
        elif config["type"] == "base-templates":
            return 30
        elif config["type"] == "global-base-templates":
            return 35
        elif config["type"] == "job-templates":
            return 40
        elif config["type"] == "jobs":
            return 50

    @staticmethod
    def sort_by_name(config):
        return config["name"]

    def get_configs(self):
        """This function gets the configs from the
        working directories"""
        configs = {}
        for name, wd in self.working_dirs.items():
            config_path = "{}/config.yaml".format(wd)
            with open(config_path, "r") as f:
                configs[name] = f.read()

        return configs

    def generate(self, io_dir, fetch_state):
        """
        Generates job definitions from JJB configs

        :param io_dir: Input/output directory
        :param fetch_state: subdirectory to use ('desired' or 'current')
        """
        for name, wd in self.working_dirs.items():
            ini_path = "{}/{}.ini".format(wd, name)
            config_path = "{}/config.yaml".format(wd)

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

    def print_diffs(self, io_dir, instance_name=None):
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

    def print_diff(self, files, replace_path, action):
        for f in files:
            if action == "update":
                ft = self.toggle_cd(f)
                equal = filecmp.cmp(f, ft)
                if equal:
                    continue

            instance, item, _ = f.replace(replace_path + "/", "").split("/")
            item_type = et.parse(f).getroot().tag
            item_type = item_type.replace("hudson.model.ListView", "view")
            item_type = item_type.replace("project", "job")
            logging.info([action, item_type, instance, item])

            if action == "update":
                with open(ft) as c, open(f) as d:
                    clines = c.readlines()
                    dlines = d.readlines()

                    differ = difflib.Differ()
                    diff = [
                        ln
                        for ln in differ.compare(clines, dlines)
                        if ln.startswith(("-", "+"))
                    ]
                    logging.debug("DIFF:\n" + "".join(diff))

    def compare_files(self, from_files, subtract_files, in_op=False):
        return [f for f in from_files if (self.toggle_cd(f) in subtract_files) is in_op]

    @staticmethod
    def get_files(search_path, instance_name=None):
        if instance_name is not None:
            search_path = path.join(search_path, instance_name)
        return [
            path.join(root, f) for root, _, files in os.walk(search_path) for f in files
        ]

    @staticmethod
    def toggle_cd(file_name):
        if "desired" in file_name:
            return file_name.replace("desired", "current")
        else:
            return file_name.replace("current", "desired")

    def update(self) -> None:
        for name, wd in self.working_dirs.items():
            ini_path = "{}/{}.ini".format(wd, name)
            config_path = "{}/config.yaml".format(wd)

            os.environ["PYTHONHTTPSVERIFY"] = self.python_https_verify
            cmd = ["jenkins-jobs", "--conf", ini_path, "update", config_path]
            delete_method = self.instances[name]["delete_method"]
            if delete_method != "manual":
                cmd.append("--delete-old")
            try:
                result = subprocess.run(
                    cmd, check=True, stdout=PIPE, stderr=STDOUT, encoding="utf-8"
                )
                if re.search("updated: [1-9]", result.stdout):
                    logging.info(result.stdout)
            except CalledProcessError as ex:
                logging.error(ex.stdout)
                raise

    @staticmethod
    def get_jjb(args):
        from jenkins_jobs.cli.entry import JenkinsJobs

        return JenkinsJobs(args)

    def execute(self, args):
        jjb = self.get_jjb(args)
        with self.toggle_logger():
            jjb.execute()

    def modify_logger(self):
        yaml.warnings({"YAMLLoadWarning": False})
        formatter = logging.Formatter("%(levelname)s: %(message)s")
        logger = logging.getLogger()
        logger.handlers[0].setFormatter(formatter)
        self.default_logging = logger.level

    @contextmanager
    def toggle_logger(self):
        logger = logging.getLogger()
        try:
            yield logger.setLevel(logging.ERROR)
        finally:
            logger.setLevel(self.default_logging)

    def cleanup(self):
        for wd in self.working_dirs.values():
            shutil.rmtree(wd)

    @retry(exceptions=(JenkinsJobsException))
    def get_jobs(self, wd, name):
        ini_path = "{}/{}.ini".format(wd, name)
        config_path = "{}/config.yaml".format(wd)

        args = ["--conf", ini_path, "test", config_path]
        jjb = self.get_jjb(args)
        builder = JenkinsManager(jjb.jjb_config)
        registry = ModuleRegistry(jjb.jjb_config, builder.plugins_list)
        parser = YamlParser(jjb.jjb_config)
        parser.load_files(jjb.options.path)
        jobs, _ = parser.expandYaml(registry, jjb.options.names)

        return jobs

    def get_job_webhooks_data(self):
        job_webhooks_data = {}
        for name, wd in self.working_dirs.items():
            jobs = self.get_jobs(wd, name)

            for job in jobs:
                try:
                    project_url_raw = job["properties"][0]["github"]["url"]
                    if "https://github.com" in project_url_raw:
                        continue
                    job_url = "{}/project/{}".format(
                        self.instance_urls[name], job["name"]
                    )
                    project_url = project_url_raw.strip("/").replace(".git", "")
                    gitlab_triggers = job["triggers"][0]["gitlab"]
                    mr_trigger = gitlab_triggers["trigger-merge-request"]
                    trigger = "mr" if mr_trigger else "push"
                    hook = {
                        "job_url": job_url,
                        "trigger": trigger,
                    }
                    job_webhooks_data.setdefault(project_url, [])
                    job_webhooks_data[project_url].append(hook)
                except KeyError:
                    continue

        return job_webhooks_data

    def get_repos(self):
        repos = set()
        for name, wd in self.working_dirs.items():
            jobs = self.get_jobs(wd, name)
            for job in jobs:
                job_name = job["name"]
                try:
                    repos.add(self.get_repo_url(job))
                except KeyError:
                    logging.debug("missing github url: {}".format(job_name))
        return repos

    def get_admins(self):
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
    def get_repo_url(job):
        repo_url_raw = job["properties"][0]["github"]["url"]
        return repo_url_raw.strip("/").replace(".git", "")

    @staticmethod
    def get_ref(job: dict) -> str:
        return job["scm"][0]["git"]["branches"][0]

    def get_all_jobs(self, job_types=None, instance_name=None, include_test=False):
        if job_types is None:
            job_types = []
        all_jobs = {}
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
                if not include_test and "test" in job_name:
                    continue
                # temporarily ignore openshift-saas-deploy jobs
                if job_name.startswith("openshift-saas-deploy"):
                    continue
                all_jobs[name].append(job)

        return all_jobs

    def print_jobs(self, job_name=None):
        all_jobs = {}
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
        print(json.dumps(all_jobs, indent=2))

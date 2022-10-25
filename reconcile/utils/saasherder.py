import base64
from dataclasses import dataclass
import json
import logging
import os
import itertools
import hashlib
import re
from collections import ChainMap
from typing import (
    Dict,
    Iterable,
    Mapping,
    Any,
    MutableMapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
    cast,
)

from contextlib import suppress
import yaml

from gitlab.exceptions import GitlabError
from github import Github, GithubException
from requests import exceptions as rqexc
from sretoolbox.container import Image
from sretoolbox.utils import retry
from sretoolbox.utils import threaded

from reconcile.github_org import get_default_config
from reconcile.status import RunningState
from reconcile.utils.mr.auto_promoter import AutoPromoter
from reconcile.utils.oc import OCLocal, StatusCodeError
from reconcile.utils.openshift_resource import (
    OpenshiftResource as OR,
    ResourceInventory,
    fully_qualified_kind,
    ResourceKeyExistsError,
)
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.state import State
from reconcile.utils.jjb_client import JJB

TARGET_CONFIG_HASH = "target_config_hash"


class Providers:
    TEKTON = "tekton"


class TriggerTypes:
    CONFIGS = 0
    MOVING_COMMITS = 1
    UPSTREAM_JOBS = 2
    CONTAINER_IMAGES = 3


@dataclass
class UpstreamJob:
    instance: str
    job: str

    def __str__(self):
        return f"{self.instance}/{self.job}"

    def __repr__(self):
        return self.__str__()


@dataclass
class TriggerSpecBase:
    saas_file_name: str
    env_name: str
    timeout: Optional[str]
    pipelines_provider: Optional[dict[str, Any]]
    resource_template_name: str
    cluster_name: str
    namespace_name: str
    state_content: Any

    @property
    def state_key(self):
        raise NotImplementedError("implement this function in inheriting classes")


@dataclass
class TriggerSpecConfig(TriggerSpecBase):
    target_name: Optional[str] = None
    reason: Optional[str] = None

    @property
    def state_key(self):
        key = (
            f"{self.saas_file_name}/{self.resource_template_name}/{self.cluster_name}/"
            f"{self.namespace_name}/{self.env_name}"
        )
        if self.target_name:
            key += f"/{self.target_name}"
        return key


@dataclass
class TriggerSpecMovingCommit(TriggerSpecBase):
    ref: str
    reason: Optional[str] = None

    @property
    def state_key(self):
        key = (
            f"{self.saas_file_name}/{self.resource_template_name}/{self.cluster_name}/"
            f"{self.namespace_name}/{self.env_name}/{self.ref}"
        )
        return key


@dataclass
class TriggerSpecUpstreamJob(TriggerSpecBase):
    instance_name: str
    job_name: str
    reason: Optional[str] = None

    @property
    def state_key(self):
        key = (
            f"{self.saas_file_name}/{self.resource_template_name}/{self.cluster_name}/"
            f"{self.namespace_name}/{self.env_name}/{self.instance_name}/{self.job_name}"
        )
        return key


@dataclass
class TriggerSpecContainerImage(TriggerSpecBase):
    image: str
    reason: Optional[str] = None

    @property
    def state_key(self):
        key = (
            f"{self.saas_file_name}/{self.resource_template_name}/{self.cluster_name}/"
            f"{self.namespace_name}/{self.env_name}/{self.image}"
        )
        return key


TriggerSpecUnion = Union[
    TriggerSpecConfig,
    TriggerSpecMovingCommit,
    TriggerSpecUpstreamJob,
    TriggerSpecContainerImage,
]

UNIQUE_SAAS_FILE_ENV_COMBO_LEN = 50


class SaasHerder:
    """Wrapper around SaaS deployment actions."""

    def __init__(
        self,
        saas_files,
        thread_pool_size,
        gitlab,
        integration,
        integration_version,
        settings,
        jenkins_map=None,
        accounts=None,
        validate=False,
        include_trigger_trace=False,
    ):
        self.saas_files = saas_files
        self.repo_urls = self._collect_repo_urls()
        if validate:
            self._validate_saas_files()
            if not self.valid:
                return
        self.thread_pool_size = thread_pool_size
        self.gitlab = gitlab
        self.integration = integration
        self.integration_version = integration_version
        self.settings = settings
        self.secret_reader = SecretReader(settings=settings)
        self.namespaces = self._collect_namespaces()
        self.jenkins_map = jenkins_map
        self.include_trigger_trace = include_trigger_trace
        # each namespace is in fact a target,
        # so we can use it to calculate.
        divisor = len(self.namespaces) or 1
        self.available_thread_pool_size = threaded.estimate_available_thread_pool_size(
            self.thread_pool_size, divisor
        )
        # if called by a single saas file,it may
        # specify that it manages resources exclusively.
        self.take_over = self._get_saas_file_feature_enabled("takeover")
        self.compare = self._get_saas_file_feature_enabled("compare", default=True)
        self.publish_job_logs = self._get_saas_file_feature_enabled("publishJobLogs")
        self.cluster_admin = self._get_saas_file_feature_enabled("clusterAdmin")
        if accounts:
            self._initiate_state(accounts)

    def __iter__(self):
        for saas_file in self.saas_files:
            for resource_template in saas_file["resourceTemplates"]:
                for target in resource_template["targets"]:
                    yield (saas_file, resource_template, target)

    def _get_saas_file_feature_enabled(self, name, default=None):
        """Returns a bool indicating if a feature is enabled in a saas file,
        or a supplied default. Returns False if there are multiple
        saas files in the process.
        All features using this method should assume a single saas file.
        """
        sf_attribute = len(self.saas_files) == 1 and self.saas_files[0].get(name)
        if sf_attribute is None and default is not None:
            return default
        return sf_attribute

    def _validate_allowed_secret_parameter_paths(
        self,
        saas_file_name: str,
        secret_parameters: Sequence[Mapping[str, Any]],
        allowed_secret_parameter_paths: Sequence[str],
    ) -> None:
        if not secret_parameters:
            return
        if not allowed_secret_parameter_paths:
            self.valid = False
            logging.error(
                f"[{saas_file_name}] " f"missing allowedSecretParameterPaths section"
            )
            return
        for sp in secret_parameters:
            path = sp["secret"]["path"]
            match = [a for a in allowed_secret_parameter_paths if path.startswith(a)]
            if not match:
                self.valid = False
                logging.error(
                    f"[{saas_file_name}] "
                    f"secret parameter path '{path}' does not match any of allowedSecretParameterPaths"
                )

    def _validate_saas_files(self):
        self.valid = True
        saas_file_name_path_map = {}
        self.tkn_unique_pipelineruns = {}

        publications = {}
        subscriptions = {}

        for saas_file in self.saas_files:
            saas_file_name = saas_file["name"]
            saas_file_path = saas_file["path"]
            saas_file_name_path_map.setdefault(saas_file_name, [])
            saas_file_name_path_map[saas_file_name].append(saas_file_path)

            saas_file_owners = [
                u["org_username"]
                for r in saas_file["selfServiceRoles"]
                for u in r["users"]
            ]
            if not saas_file_owners:
                msg = "saas file {} has no owners: {}"
                logging.error(msg.format(saas_file_name, saas_file_path))
                self.valid = False

            allowed_secret_parameter_paths = (
                saas_file.get("allowedSecretParameterPaths") or []
            )
            self._validate_allowed_secret_parameter_paths(
                saas_file_name,
                saas_file.get("secretParameters"),
                allowed_secret_parameter_paths,
            )

            for resource_template in saas_file["resourceTemplates"]:
                resource_template_name = resource_template["name"]
                resource_template_url = resource_template["url"]
                self._validate_allowed_secret_parameter_paths(
                    saas_file_name,
                    resource_template.get("secretParameters"),
                    allowed_secret_parameter_paths,
                )
                for target in resource_template["targets"]:
                    target_namespace = target["namespace"]
                    namespace_name = target_namespace["name"]
                    cluster_name = target_namespace["cluster"]["name"]
                    environment = target_namespace["environment"]
                    environment_name = environment["name"]
                    # unique saas file and env name combination
                    self._check_saas_file_env_combo_unique(
                        saas_file_name, environment_name
                    )
                    self._validate_auto_promotion_used_with_commit_sha(
                        saas_file_name,
                        resource_template_name,
                        target,
                    )
                    self._validate_upstream_not_used_with_commit_sha(
                        saas_file_name,
                        resource_template_name,
                        target,
                    )
                    self._validate_upstream_not_used_with_image(
                        saas_file_name,
                        resource_template_name,
                        target,
                    )
                    self._validate_image_not_used_with_commit_sha(
                        saas_file_name,
                        resource_template_name,
                        target,
                    )
                    self._validate_allowed_secret_parameter_paths(
                        saas_file_name,
                        target.get("secretParameters"),
                        allowed_secret_parameter_paths,
                    )
                    self._validate_allowed_secret_parameter_paths(
                        saas_file_name,
                        environment.get("secretParameters"),
                        allowed_secret_parameter_paths,
                    )

                    promotion = target.get("promotion")
                    if promotion:
                        rt_ref = (
                            saas_file_path,
                            resource_template_name,
                            resource_template_url,
                        )

                        # Get publications and subscriptions for the target
                        self._get_promotion_pubs_and_subs(
                            rt_ref, promotion, publications, subscriptions
                        )
                    # validate target parameters
                    target_parameters = target["parameters"]
                    if not target_parameters:
                        continue
                    target_parameters = json.loads(target_parameters)
                    self._validate_image_tag_not_equals_ref(
                        saas_file_name,
                        resource_template_name,
                        target["ref"],
                        target_parameters,
                    )
                    environment_parameters = environment["parameters"]
                    if not environment_parameters:
                        continue
                    environment_parameters = json.loads(environment_parameters)
                    msg = (
                        f"[{saas_file_name}/{resource_template_name}] "
                        + "parameter found in target "
                        + f"{cluster_name}/{namespace_name} "
                        + f"should be reused from env {environment_name}"
                    )
                    for t_key, t_value in target_parameters.items():
                        if not isinstance(t_value, str):
                            continue
                        # Check for recursivity. Ex: PARAM: "foo.${PARAM}"
                        replace_pattern = "${" + t_key + "}"
                        if replace_pattern in t_value:
                            logging.error(
                                f"[{saas_file_name}/{resource_template_name}] "
                                f"recursivity in parameter name and value "
                                f'found: {t_key}: "{t_value}" - this will '
                                f"likely not work as expected. Please consider"
                                f" changing the parameter name"
                            )
                            self.valid = False
                        for e_key, e_value in environment_parameters.items():
                            if not isinstance(e_value, str):
                                continue
                            if "." not in e_value:
                                continue
                            if e_value not in t_value:
                                continue
                            if t_key == e_key and t_value == e_value:
                                details = f"consider removing {t_key}"
                            else:
                                replacement = t_value.replace(
                                    e_value, "${" + e_key + "}"
                                )
                                details = (
                                    f'target: "{t_key}: {t_value}". '
                                    + f'env: "{e_key}: {e_value}". '
                                    + f'consider "{t_key}: {replacement}"'
                                )
                            logging.error(f"{msg}: {details}")
                            self.valid = False

        # saas file name duplicates
        duplicates = {
            saas_file_name: saas_file_paths
            for saas_file_name, saas_file_paths in saas_file_name_path_map.items()
            if len(saas_file_paths) > 1
        }
        if duplicates:
            self.valid = False
            msg = "saas file name {} is not unique: {}"
            for saas_file_name, saas_file_paths in duplicates.items():
                logging.error(msg.format(saas_file_name, saas_file_paths))

        self._check_promotions_have_same_source(subscriptions, publications)

    def _get_promotion_pubs_and_subs(
        self,
        rt_ref: Tuple,
        promotion: dict[str, Any],
        publications: MutableMapping[str, Tuple],
        subscriptions: MutableMapping[str, list[Tuple]],
    ):
        """
        Function to gather promotion publish and subcribe configurations
        It validates a publish channel is unique across all publis targets.
        """
        publish = promotion.get("publish") or []
        for channel in publish:
            if channel in publications:
                self.valid = False
                logging.error(
                    "saas file promotion publish channel"
                    "is not unique: {}".format(channel)
                )
                continue
            publications[channel] = rt_ref

        subscribe = promotion.get("subscribe") or []
        for channel in subscribe:
            subscriptions.setdefault(channel, [])
            subscriptions[channel].append(rt_ref)

    def _check_promotions_have_same_source(
        self,
        subscriptions: Mapping[str, list[Tuple]],
        publications: Mapping[str, Tuple],
    ) -> None:
        """
        Function to check that a promotion has the same repository
        in both publisher and subscriber targets.
        """

        for sub_channel, sub_targets in subscriptions.items():
            pub_channel_ref = publications.get(sub_channel)
            if not pub_channel_ref:
                self.valid = False
            else:
                (pub_saas, pub_rt_name, pub_rt_url) = pub_channel_ref

            for (sub_saas, sub_rt_name, sub_rt_url) in sub_targets:
                if not pub_channel_ref:
                    logging.error(
                        "Channel is not published by any target\n"
                        "subscriber_saas: {}\n"
                        "subscriber_rt: {}\n"
                        "channel: {}".format(sub_saas, sub_rt_name, sub_channel)
                    )
                else:
                    if sub_rt_url != pub_rt_url:
                        self.valid = False
                        logging.error(
                            "Subscriber and Publisher targets have diferent "
                            "source repositories\n"
                            "publisher_saas: {}\n"
                            "publisher_rt: {}\n"
                            "publisher_repo: {}\n"
                            "subscriber_saas: {}\n"
                            "subscriber_rt: {}\n"
                            "subscriber_repo: {}\n".format(
                                pub_saas,
                                pub_rt_name,
                                pub_rt_url,
                                sub_saas,
                                sub_rt_name,
                                sub_rt_url,
                            )
                        )

    def _check_saas_file_env_combo_unique(self, saas_file_name, env_name):
        # max tekton pipelinerun name length can be 63.
        # leaving 12 for the timestamp leaves us with 51
        # to create a unique pipelinerun name
        tkn_long_name = f"{saas_file_name}-{env_name}"
        tkn_name = tkn_long_name[:UNIQUE_SAAS_FILE_ENV_COMBO_LEN]
        if (
            tkn_name in self.tkn_unique_pipelineruns
            and self.tkn_unique_pipelineruns[tkn_name] != tkn_long_name
        ):
            logging.error(
                f"[{saas_file_name}/{env_name}] "
                "saas file and env name combination must be "
                f"unique in first {UNIQUE_SAAS_FILE_ENV_COMBO_LEN} chars. "
                f"found not unique value: {tkn_name} "
                f"from this long name: {tkn_long_name}"
            )
            self.valid = False
        else:
            self.tkn_unique_pipelineruns[tkn_name] = tkn_long_name

    def _validate_auto_promotion_used_with_commit_sha(
        self,
        saas_file_name: str,
        resource_template_name: str,
        target: dict,
    ):
        target_promotion = target.get("promotion") or {}
        if not target_promotion:
            return

        target_auto = target_promotion.get("auto")
        if not target_auto:
            return

        pattern = r"^[0-9a-f]{40}$"
        ref = target["ref"]
        if re.search(pattern, ref):
            return

        self.valid = False
        logging.error(
            f"[{saas_file_name}/{resource_template_name}] "
            f"auto promotion should be used with commit sha instead of: {ref}"
        )

    def _validate_upstream_not_used_with_commit_sha(
        self,
        saas_file_name: str,
        resource_template_name: str,
        target: dict,
    ):
        upstream = target.get("upstream")
        if upstream:
            pattern = r"^[0-9a-f]{40}$"
            ref = target["ref"]
            if re.search(pattern, ref):
                logging.error(
                    f"[{saas_file_name}/{resource_template_name}] "
                    f"upstream used with commit sha: {ref}"
                )
                self.valid = False

    def _validate_upstream_not_used_with_image(
        self,
        saas_file_name: str,
        resource_template_name: str,
        target: dict,
    ):
        upstream = target.get("upstream")
        image = target.get("image")
        if image and upstream:
            logging.error(
                f"[{saas_file_name}/{resource_template_name}] "
                f"image used with upstream"
            )
            self.valid = False

    def _validate_image_not_used_with_commit_sha(
        self,
        saas_file_name: str,
        resource_template_name: str,
        target: dict,
    ):
        image = target.get("image")
        if image:
            pattern = r"^[0-9a-f]{40}$"
            ref = target["ref"]
            if re.search(pattern, ref):
                logging.error(
                    f"[{saas_file_name}/{resource_template_name}] "
                    f"image used with commit sha: {ref}"
                )
                self.valid = False

    def _validate_image_tag_not_equals_ref(
        self,
        saas_file_name: str,
        resource_template_name: str,
        ref: str,
        parameters: dict,
    ):
        image_tag = parameters.get("IMAGE_TAG")
        if image_tag and str(ref).startswith(str(image_tag)):
            logging.error(
                f"[{saas_file_name}/{resource_template_name}] "
                f"IMAGE_TAG {image_tag} is the same as ref {ref}. "
                "please remove the IMAGE_TAG parameter, it is automatically generated."
            )
            self.valid = False

    @staticmethod
    def _get_upstream_jobs(
        jjb: JJB,
        all_jobs: dict[str, list[dict]],
        url: str,
        ref: str,
    ) -> Iterable[UpstreamJob]:
        results = []
        for instance, jobs in all_jobs.items():
            for job in jobs:
                job_repo_url = jjb.get_repo_url(job)
                if url != job_repo_url:
                    continue
                job_ref = jjb.get_ref(job)
                if ref != job_ref:
                    continue
                results.append(UpstreamJob(instance, job["name"]))
        return results

    def validate_upstream_jobs(
        self,
        jjb: JJB,
    ):
        all_jobs = jjb.get_all_jobs(job_types=["build"])
        pattern = r"^[0-9a-f]{40}$"
        for sf, rt, t in self:
            sf_name = sf["name"]
            rt_name = rt["name"]
            url = rt["url"]
            ref = t["ref"]
            if re.search(pattern, ref):
                continue
            upstream = t.get("upstream")
            if upstream:
                if isinstance(upstream, str):
                    # skip v1 saas files
                    continue
                upstream_job = UpstreamJob(
                    upstream["instance"]["name"], upstream["name"]
                )
                possible_upstream_jobs = self._get_upstream_jobs(
                    jjb, all_jobs, url, ref
                )
                found_jobs = [
                    j
                    for j in all_jobs[upstream_job.instance]
                    if j["name"] == upstream_job.job
                ]
                if found_jobs:
                    if upstream_job not in possible_upstream_jobs:
                        logging.error(
                            f"[{sf_name}/{rt_name}] upstream job "
                            f"incorrect: {upstream_job}. "
                            f"should be one of: {possible_upstream_jobs}"
                        )
                        self.valid = False
                else:
                    logging.error(
                        f"[{sf_name}/{rt_name}] upstream job "
                        f"not found: {upstream_job}. "
                        f"should be one of: {possible_upstream_jobs}"
                    )
                    self.valid = False

    def _collect_namespaces(self):
        # namespaces may appear more then once in the result
        namespaces = []
        for saas_file in self.saas_files:
            managed_resource_types = saas_file["managedResourceTypes"]
            resource_templates = saas_file["resourceTemplates"]
            for rt in resource_templates:
                targets = rt["targets"]
                for target in targets:
                    namespace = target["namespace"]
                    if target.get("disable"):
                        logging.debug(
                            f"[{saas_file['name']}/{rt['name']}] target "
                            + f"{namespace['cluster']['name']}/"
                            + f"{namespace['name']} is disabled."
                        )
                        continue
                    # managedResourceTypes is defined per saas_file
                    # add it to each namespace in the current saas_file
                    namespace["managedResourceTypes"] = managed_resource_types
                    namespaces.append(namespace)
        return namespaces

    def _collect_repo_urls(self):
        repo_urls = set()
        for saas_file in self.saas_files:
            resource_templates = saas_file["resourceTemplates"]
            for rt in resource_templates:
                repo_urls.add(rt["url"])
        return repo_urls

    def _initiate_state(self, accounts):
        self.state = State(
            integration=self.integration, accounts=accounts, settings=self.settings
        )

    @staticmethod
    def _collect_parameters(container):
        parameters = container.get("parameters") or {}
        if isinstance(parameters, str):
            parameters = json.loads(parameters)
        # adjust Python's True/False
        for k, v in parameters.items():
            if v is True:
                parameters[k] = "true"
            elif v is False:
                parameters[k] = "false"
            elif any(isinstance(v, t) for t in [dict, list, tuple]):
                parameters[k] = json.dumps(v)
        return parameters

    def _collect_secret_parameters(self, container):
        parameters = {}
        secret_parameters = container.get("secretParameters") or []
        for sp in secret_parameters:
            name = sp["name"]
            secret = sp["secret"]
            value = self.secret_reader.read(secret)
            parameters[name] = value

        return parameters

    @staticmethod
    def _get_file_contents_github(repo, path, commit_sha):
        f = repo.get_contents(path, commit_sha)
        if f.size < 1024**2:  # 1 MB
            return f.decoded_content
        else:
            tree = repo.get_git_tree(commit_sha, recursive="/" in path).tree
            for x in tree:
                if x.path != path.lstrip("/"):
                    continue
                blob = repo.get_git_blob(x.sha)
                return base64.b64decode(blob.content).decode("utf8")

    @retry(max_attempts=20)
    def _get_file_contents(self, options):
        url = options["url"]
        path = options["path"]
        ref = options["ref"]
        github = options["github"]
        html_url = f"{url}/blob/{ref}{path}"
        commit_sha = self._get_commit_sha(options)
        content = None
        if "github" in url:
            repo_name = url.rstrip("/").replace("https://github.com/", "")
            repo = github.get_repo(repo_name)
            content = self._get_file_contents_github(repo, path, commit_sha)
        elif "gitlab" in url:
            if not self.gitlab:
                raise Exception("gitlab is not initialized")
            project = self.gitlab.get_project(url)
            f = project.files.get(file_path=path.lstrip("/"), ref=commit_sha)
            content = f.decode()

        return yaml.safe_load(content), html_url, commit_sha

    @retry()
    def _get_directory_contents(self, options):
        url = options["url"]
        path = options["path"]
        ref = options["ref"]
        github = options["github"]
        html_url = f"{url}/tree/{ref}{path}"
        commit_sha = self._get_commit_sha(options)
        resources = []
        if "github" in url:
            repo_name = url.rstrip("/").replace("https://github.com/", "")
            repo = github.get_repo(repo_name)
            for f in repo.get_contents(path, commit_sha):
                file_path = os.path.join(path, f.name)
                file_contents_decoded = self._get_file_contents_github(
                    repo, file_path, commit_sha
                )
                resource = yaml.safe_load(file_contents_decoded)
                resources.append(resource)
        elif "gitlab" in url:
            if not self.gitlab:
                raise Exception("gitlab is not initialized")
            project = self.gitlab.get_project(url)
            for f in self.gitlab.get_items(
                project.repository_tree, path=path.lstrip("/"), ref=commit_sha
            ):
                file_contents = project.files.get(file_path=f["path"], ref=commit_sha)
                resource = yaml.safe_load(file_contents.decode())
                resources.append(resource)

        return resources, html_url, commit_sha

    @retry()
    def _get_commit_sha(self, options):
        url = options["url"]
        ref = options["ref"]
        github = options["github"]
        hash_length = options.get("hash_length")
        commit_sha = ""
        if "github" in url:
            repo_name = url.rstrip("/").replace("https://github.com/", "")
            repo = github.get_repo(repo_name)
            commit = repo.get_commit(sha=ref)
            commit_sha = commit.sha
        elif "gitlab" in url:
            if not self.gitlab:
                raise Exception("gitlab is not initialized")
            project = self.gitlab.get_project(url)
            commits = project.commits.list(ref_name=ref)
            commit_sha = commits[0].id

        if hash_length:
            return commit_sha[:hash_length]

        return commit_sha

    @staticmethod
    def _get_cluster_and_namespace(target):
        cluster = target["namespace"]["cluster"]["name"]
        namespace = target["namespace"]["name"]
        return cluster, namespace

    @staticmethod
    def _additional_resource_process(resources, html_url):
        for resource in resources:
            # add a definition annotation to each PrometheusRule rule
            if resource["kind"] == "PrometheusRule":
                try:
                    groups = resource["spec"]["groups"]
                    for group in groups:
                        rules = group["rules"]
                        for rule in rules:
                            annotations = rule.get("annotations")
                            if not annotations:
                                continue
                            rule["annotations"]["html_url"] = html_url
                except Exception:
                    logging.warning(
                        "could not add html_url annotation to" + resource["name"]
                    )

    @staticmethod
    def _parameter_value_needed(parameter_name, consolidated_parameters, template):
        """Is a parameter named in the template but unspecified?

        NOTE: This is currently "parameter *named* and absent" -- i.e. we
        don't care about `required: true`. This is for backward compatibility.

        :param parameter_name: The name (key) of the parameter.
        :param consolidated_parameters: Dict of parameters already specified/
                calculated.
        :param template: The template file in dict form.
        :return bool: True if the named parameter is named in the template,
                but not already present in consolidated_parameters.
        """
        if parameter_name in consolidated_parameters:
            return False
        for template_parameter in template.get("parameters", {}):
            if template_parameter["name"] == parameter_name:
                return True
        return False

    def _process_template(self, options):
        saas_file_name = options["saas_file_name"]
        resource_template_name = options["resource_template_name"]
        image_auth = options["image_auth"]
        url = options["url"]
        path = options["path"]
        provider = options["provider"]
        target = options["target"]
        github = options["github"]
        target_ref = target["ref"]
        target_promotion = target.get("promotion") or {}

        resources = None
        html_url = None
        commit_sha = None

        if provider == "openshift-template":
            hash_length = options["hash_length"]
            parameters = options["parameters"]
            environment = target["namespace"]["environment"]
            environment_parameters = self._collect_parameters(environment)
            environment_secret_parameters = self._collect_secret_parameters(environment)
            target_parameters = self._collect_parameters(target)
            target_secret_parameters = self._collect_secret_parameters(target)

            consolidated_parameters = {}
            consolidated_parameters.update(environment_parameters)
            consolidated_parameters.update(environment_secret_parameters)
            consolidated_parameters.update(parameters)
            consolidated_parameters.update(target_parameters)
            consolidated_parameters.update(target_secret_parameters)

            for replace_key, replace_value in consolidated_parameters.items():
                if not isinstance(replace_value, str):
                    continue
                replace_pattern = "${" + replace_key + "}"
                for k, v in consolidated_parameters.items():
                    if not isinstance(v, str):
                        continue
                    if replace_pattern in v:
                        consolidated_parameters[k] = v.replace(
                            replace_pattern, replace_value
                        )

            get_file_contents_options = {
                "url": url,
                "path": path,
                "ref": target_ref,
                "github": github,
            }

            try:
                template, html_url, commit_sha = self._get_file_contents(
                    get_file_contents_options
                )
            except Exception as e:
                logging.error(
                    f"[{url}/blob/{target_ref}{path}] "
                    + f"error fetching template: {str(e)}"
                )
                return None, None, None

            # add IMAGE_TAG only if it is unspecified
            image_tag = consolidated_parameters.get("IMAGE_TAG")
            if not image_tag:
                sha_substring = commit_sha[:hash_length]
                # IMAGE_TAG takes one of two forms:
                # - If saas file attribute 'use_channel_in_image_tag' is true,
                #   it is {CHANNEL}-{SHA}
                # - Otherwise it is just {SHA}
                if self._get_saas_file_feature_enabled("use_channel_in_image_tag"):
                    try:
                        channel = consolidated_parameters["CHANNEL"]
                    except KeyError:
                        logging.error(
                            f"[{saas_file_name}/{resource_template_name}] "
                            + f"{html_url}: CHANNEL is required when "
                            + "'use_channel_in_image_tag' is true."
                        )
                        return None, None, None
                    image_tag = f"{channel}-{sha_substring}"
                else:
                    image_tag = sha_substring
                consolidated_parameters["IMAGE_TAG"] = image_tag

            # This relies on IMAGE_TAG already being calculated.
            need_repo_digest = self._parameter_value_needed(
                "REPO_DIGEST", consolidated_parameters, template
            )
            need_image_digest = self._parameter_value_needed(
                "IMAGE_DIGEST", consolidated_parameters, template
            )
            if need_repo_digest or need_image_digest:
                try:
                    logging.debug("Generating REPO_DIGEST.")
                    registry_image = consolidated_parameters["REGISTRY_IMG"]
                except KeyError as e:
                    logging.error(
                        f"[{saas_file_name}/{resource_template_name}] "
                        + f"{html_url}: error generating REPO_DIGEST. "
                        + "Is REGISTRY_IMG missing? "
                        + f"{str(e)}"
                    )
                    return None, None, None
                try:
                    image_uri = f"{registry_image}:{image_tag}"
                    img = Image(image_uri, **image_auth)
                    if need_repo_digest:
                        consolidated_parameters["REPO_DIGEST"] = img.url_digest
                    if need_image_digest:
                        consolidated_parameters["IMAGE_DIGEST"] = img.digest
                except (rqexc.ConnectionError, rqexc.HTTPError) as e:
                    logging.error(
                        f"[{saas_file_name}/{resource_template_name}] "
                        + f"{html_url}: error generating REPO_DIGEST for "
                        + f"{image_uri}: {str(e)}"
                    )
                    return None, None, None

            oc = OCLocal("cluster", None, None, local=True)
            try:
                resources = oc.process(template, consolidated_parameters)
            except StatusCodeError as e:
                logging.error(
                    f"[{saas_file_name}/{resource_template_name}] "
                    + f"{html_url}: error processing template: {str(e)}"
                )

        elif provider == "directory":
            get_directory_contents_options = {
                "url": url,
                "path": path,
                "ref": target_ref,
                "github": github,
            }
            try:
                resources, html_url, commit_sha = self._get_directory_contents(
                    get_directory_contents_options
                )
            except Exception as e:
                logging.error(
                    f"[{url}/tree/{target_ref}{path}] "
                    + f"error fetching directory: {str(e)}"
                )
                return None, None, None

        else:
            logging.error(
                f"[{saas_file_name}/{resource_template_name}] "
                + f"unknown provider: {provider}"
            )

        target_promotion["commit_sha"] = commit_sha
        # This target_promotion data is used in publish_promotions
        if target_promotion.get("publish"):
            target_promotion["saas_file"] = saas_file_name
            target_promotion[TARGET_CONFIG_HASH] = options[TARGET_CONFIG_HASH]

        return resources, html_url, target_promotion

    @staticmethod
    def _collect_images(resource):
        images = set()
        # resources with pod templates
        with suppress(KeyError):
            template = resource["spec"]["template"]
            for c in template["spec"]["containers"]:
                images.add(c["image"])
        # init containers
        with suppress(KeyError):
            template = resource["spec"]["template"]
            for c in template["spec"]["initContainers"]:
                images.add(c["image"])
        # CronJob
        with suppress(KeyError):
            template = resource["spec"]["jobTemplate"]["spec"]["template"]
            for c in template["spec"]["containers"]:
                images.add(c["image"])
        # CatalogSource templates
        with suppress(KeyError):
            images.add(resource["spec"]["image"])
        # ClowdApp deployments
        with suppress(KeyError):
            deployments = resource["spec"]["deployments"]
            for d in deployments:
                images.add(d["podSpec"]["image"])
        # ClowdApp jobs
        with suppress(KeyError, TypeError):
            jobs = resource["spec"]["jobs"]
            for j in jobs:
                images.add(j["podSpec"]["image"])

        return images

    @staticmethod
    def _check_image(image, image_patterns, image_auth, error_prefix):
        error = False
        if not image_patterns:
            error = True
            logging.error(
                f"{error_prefix} imagePatterns is empty (does not contain {image})"
            )
        if image_patterns and not any(image.startswith(p) for p in image_patterns):
            error = True
            logging.error(f"{error_prefix} Image is not in imagePatterns: {image}")
        try:
            valid = Image(image, **image_auth)
            if not valid:
                error = True
                logging.error(f"{error_prefix} Image does not exist: {image}")
        except Exception as e:
            error = True
            logging.error(
                f"{error_prefix} Image is invalid: {image}. " + f"details: {str(e)}"
            )

        return error

    def _check_images(self, options):
        saas_file_name = options["saas_file_name"]
        resource_template_name = options["resource_template_name"]
        html_url = options["html_url"]
        resources = options["resources"]
        image_auth = options["image_auth"]
        image_patterns = options["image_patterns"]
        error_prefix = f"[{saas_file_name}/{resource_template_name}] {html_url}:"

        images_list = threaded.run(
            self._collect_images, resources, self.available_thread_pool_size
        )
        images = set(itertools.chain.from_iterable(images_list))
        if not images:
            return False  # no errors
        errors = threaded.run(
            self._check_image,
            images,
            self.available_thread_pool_size,
            image_patterns=image_patterns,
            image_auth=image_auth,
            error_prefix=error_prefix,
        )
        return any(errors)

    def _initiate_github(self, saas_file):
        auth = saas_file.get("authentication") or {}
        auth_code = auth.get("code") or {}
        if auth_code:
            token = self.secret_reader.read(auth_code)
        else:
            token = get_default_config()["token"]

        base_url = os.environ.get("GITHUB_API", "https://api.github.com")
        # This is a threaded world. Let's define a big
        # connections pool to live in that world
        # (this avoids the warning "Connection pool is
        # full, discarding connection: api.github.com")
        pool_size = 100
        return Github(token, base_url=base_url, pool_size=pool_size)

    def _initiate_image_auth(self, saas_file):
        """
        This function initiates a dict required for image authentication.
        This dict will be used as kwargs for sretoolbox's Image.
        The image authentication secret specified in the saas file must
        contain the 'user' and 'token' keys, and may optionally contain
        a 'url' key specifying the image registry url to be passed to check
        if an image should be checked using these credentials.
        The function returns the keys extracted from the secret in the
        structure expected by sretoolbox's Image:
        'user' --> 'username'
        'token' --> 'password'
        'url' --> 'auth_server' (optional)
        """
        auth = saas_file.get("authentication")
        if not auth:
            return {}

        auth_image_secret = auth.get("image")
        if not auth_image_secret:
            return {}

        creds = self.secret_reader.read_all(auth_image_secret)
        required_keys = ["user", "token"]
        ok = all(k in creds.keys() for k in required_keys)
        if not ok:
            logging.warning(
                "the specified image authentication secret "
                + f"found in path {auth_image_secret['path']} "
                + f"does not contain all required keys: {required_keys}"
            )
            return {}

        image_auth = {"username": creds["user"], "password": creds["token"]}
        url = creds.get("url")
        if url:
            image_auth["auth_server"] = url

        return image_auth

    def populate_desired_state(self, ri):
        results = threaded.run(
            self.init_populate_desired_state_specs,
            self.saas_files,
            self.thread_pool_size,
        )
        desired_state_specs = list(itertools.chain.from_iterable(results))
        promotions = threaded.run(
            self.populate_desired_state_saas_file,
            desired_state_specs,
            self.thread_pool_size,
            ri=ri,
        )
        self.promotions = promotions

    def init_populate_desired_state_specs(self, saas_file):
        specs = []
        saas_file_name = saas_file["name"]
        github = self._initiate_github(saas_file)
        image_auth = self._initiate_image_auth(saas_file)
        managed_resource_types = saas_file["managedResourceTypes"]
        image_patterns = saas_file["imagePatterns"]
        resource_templates = saas_file["resourceTemplates"]
        saas_file_parameters = self._collect_parameters(saas_file)
        saas_file_secret_parameters = self._collect_secret_parameters(saas_file)

        all_trigger_specs = self.get_saas_targets_config_trigger_specs(saas_file)
        # iterate over resource templates (multiple per saas_file)
        for rt in resource_templates:
            rt_name = rt["name"]
            url = rt["url"]
            path = rt["path"]
            provider = rt.get("provider") or "openshift-template"
            hash_length = rt.get("hash_length") or self.settings["hashLength"]
            resource_template_parameters = self._collect_parameters(rt)
            resource_template_secret_parameters = self._collect_secret_parameters(rt)

            consolidated_parameters = {}
            consolidated_parameters.update(saas_file_parameters)
            consolidated_parameters.update(saas_file_secret_parameters)
            consolidated_parameters.update(resource_template_parameters)
            consolidated_parameters.update(resource_template_secret_parameters)

            # Iterate over targets (each target is a namespace).
            for target in rt["targets"]:
                if target.get("disable"):
                    # Warning is logged during SaasHerder initiation.
                    continue

                cluster = target["namespace"]["cluster"]["name"]
                namespace = target["namespace"]["name"]
                env_name = target["namespace"]["environment"]["name"]

                state_key = TriggerSpecConfig(
                    saas_file_name=saas_file_name,
                    env_name=env_name,
                    timeout=None,
                    pipelines_provider=None,
                    resource_template_name=rt_name,
                    cluster_name=cluster,
                    namespace_name=namespace,
                    target_name=target.get("name"),
                    state_content=None,
                ).state_key
                digest = SaasHerder.get_target_config_hash(
                    all_trigger_specs[state_key].state_content
                )

                process_template_options = {
                    "saas_file_name": saas_file_name,
                    "resource_template_name": rt_name,
                    "image_auth": image_auth,
                    "url": url,
                    "path": path,
                    "provider": provider,
                    "hash_length": hash_length,
                    "target": target,
                    "parameters": consolidated_parameters,
                    "github": github,
                    TARGET_CONFIG_HASH: digest,
                }
                check_images_options_base = {
                    "saas_file_name": saas_file_name,
                    "resource_template_name": rt_name,
                    "image_auth": image_auth,
                    "image_patterns": image_patterns,
                }
                spec = {
                    "saas_file_name": saas_file_name,
                    "cluster": cluster,
                    "namespace": namespace,
                    "managed_resource_types": managed_resource_types,
                    "process_template_options": process_template_options,
                    "check_images_options_base": check_images_options_base,
                    "delete": target.get("delete"),
                    "privileged": saas_file.get("clusterAdmin", False) is True,
                }
                specs.append(spec)

        return specs

    def populate_desired_state_saas_file(self, spec, ri: ResourceInventory):
        if spec["delete"]:
            # to delete resources, we avoid adding them to the desired state
            return

        saas_file_name = spec["saas_file_name"]
        cluster = spec["cluster"]
        namespace = spec["namespace"]
        managed_resource_types = set(spec["managed_resource_types"])
        process_template_options = spec["process_template_options"]
        check_images_options_base = spec["check_images_options_base"]

        resources, html_url, promotion = self._process_template(
            process_template_options
        )
        if resources is None:
            ri.register_error()
            return
        # filter resources
        rs = []
        for r in resources:
            if isinstance(r, dict) and "kind" in r and "apiVersion" in r:
                kind = cast(str, r.get("kind"))
                kind_and_group = fully_qualified_kind(
                    kind, cast(str, r.get("apiVersion"))
                )
                if (
                    kind in managed_resource_types
                    or kind_and_group in managed_resource_types
                ):
                    rs.append(r)
                else:
                    logging.info(
                        f"Skipping resource of kind {kind} on " f"{cluster}/{namespace}"
                    )
            else:
                logging.info(
                    "Skipping non-dictionary resource on " f"{cluster}/{namespace}"
                )
        # additional processing of resources
        resources = rs
        self._additional_resource_process(resources, html_url)
        # check images
        check_images_options = {"html_url": html_url, "resources": resources}
        check_images_options.update(check_images_options_base)
        image_error = self._check_images(check_images_options)
        if image_error:
            ri.register_error()
            return
        # add desired resources
        for resource in resources:
            resource_kind = resource["kind"]
            resource_name = resource["metadata"]["name"]
            oc_resource = OR(
                resource,
                self.integration,
                self.integration_version,
                caller_name=saas_file_name,
                error_details=html_url,
            )
            try:
                ri.add_desired_resource(
                    cluster,
                    namespace,
                    oc_resource,
                    privileged=spec["privileged"],
                )
            except ResourceKeyExistsError:
                ri.register_error()
                msg = (
                    f"[{cluster}/{namespace}] desired item "
                    + f"already exists: {resource_kind}/{resource_name}. "
                    + f"saas file name: {saas_file_name}, "
                    + "resource template name: "
                    + f"{process_template_options['resource_template_name']}."
                )
                logging.error(msg)

        return promotion

    def get_diff(self, trigger_type, dry_run):
        if trigger_type == TriggerTypes.MOVING_COMMITS:
            # TODO: replace error with actual error handling when needed
            error = False
            return self.get_moving_commits_diff(dry_run), error
        elif trigger_type == TriggerTypes.UPSTREAM_JOBS:
            # error is being returned from the called function
            return self.get_upstream_jobs_diff(dry_run)
        elif trigger_type == TriggerTypes.CONFIGS:
            # TODO: replace error with actual error handling when needed
            error = False
            return self.get_configs_diff(), error
        elif trigger_type == TriggerTypes.CONTAINER_IMAGES:
            # TODO: replace error with actual error handling when needed
            error = False
            return self.get_container_images_diff(dry_run), error
        else:
            raise NotImplementedError(
                f"saasherder get_diff for trigger type: {trigger_type}"
            )

    def update_state(self, trigger_spec: TriggerSpecUnion):
        self.state.add(
            trigger_spec.state_key, value=trigger_spec.state_content, force=True
        )

    def get_moving_commits_diff(self, dry_run: bool) -> list[TriggerSpecMovingCommit]:
        results = threaded.run(
            self.get_moving_commits_diff_saas_file,
            self.saas_files,
            self.thread_pool_size,
            dry_run=dry_run,
        )
        return list(itertools.chain.from_iterable(results))

    def get_moving_commits_diff_saas_file(
        self, saas_file: dict[str, Any], dry_run: bool
    ) -> list[TriggerSpecMovingCommit]:
        saas_file_name = saas_file["name"]
        timeout = saas_file.get("timeout") or None
        pipelines_provider = self._get_pipelines_provider(saas_file)
        github = self._initiate_github(saas_file)
        trigger_specs: list[TriggerSpecMovingCommit] = []
        for rt in saas_file["resourceTemplates"]:
            rt_name = rt["name"]
            url = rt["url"]
            for target in rt["targets"]:
                try:
                    # don't trigger if there is a linked upstream job or container image
                    if target.get("upstream") or target.get("image"):
                        continue
                    ref = target["ref"]
                    get_commit_sha_options = {"url": url, "ref": ref, "github": github}
                    desired_commit_sha = self._get_commit_sha(get_commit_sha_options)
                    # don't trigger on refs which are commit shas
                    if ref == desired_commit_sha:
                        continue
                    namespace = target["namespace"]
                    cluster_name = namespace["cluster"]["name"]
                    namespace_name = namespace["name"]
                    env_name = namespace["environment"]["name"]
                    trigger_spec = TriggerSpecMovingCommit(
                        saas_file_name=saas_file_name,
                        env_name=env_name,
                        timeout=timeout,
                        pipelines_provider=pipelines_provider,
                        resource_template_name=rt_name,
                        cluster_name=cluster_name,
                        namespace_name=namespace_name,
                        ref=ref,
                        state_content=desired_commit_sha,
                    )
                    if self.include_trigger_trace:
                        trigger_spec.reason = f"{url}/commit/{desired_commit_sha}"
                    current_commit_sha = self.state.get(trigger_spec.state_key, None)
                    # skip if there is no change in commit sha
                    if current_commit_sha == desired_commit_sha:
                        continue
                    # don't trigger if this is the first time
                    # this target is being deployed.
                    # that will be taken care of by
                    # openshift-saas-deploy-trigger-configs
                    if current_commit_sha is None:
                        # store the value to take over from now on
                        if not dry_run:
                            self.update_state(trigger_spec)
                        continue
                    # we finally found something we want to trigger on!
                    trigger_specs.append(trigger_spec)
                except (GithubException, GitlabError):
                    logging.exception(
                        f"Skipping target {saas_file_name}:{rt_name}"
                        f" - repo: {url} - ref: {ref}"
                    )

        return trigger_specs

    def get_upstream_jobs_diff(
        self, dry_run: bool
    ) -> tuple[list[TriggerSpecUpstreamJob], bool]:
        current_state, error = self._get_upstream_jobs_current_state()
        results = threaded.run(
            self.get_upstream_jobs_diff_saas_file,
            self.saas_files,
            self.thread_pool_size,
            dry_run=dry_run,
            current_state=current_state,
        )
        return list(itertools.chain.from_iterable(results)), error

    def _get_upstream_jobs_current_state(self) -> tuple[dict[str, Any], bool]:
        current_state: dict[str, Any] = {}
        error = False
        for instance_name, jenkins in self.jenkins_map.items():
            try:
                current_state[instance_name] = jenkins.get_jobs_state()
            except (rqexc.ConnectionError, rqexc.HTTPError):
                error = True
                logging.error(f"instance unreachable: {instance_name}")
                current_state[instance_name] = {}

        return current_state, error

    def get_upstream_jobs_diff_saas_file(
        self, saas_file: dict[str, Any], dry_run: bool, current_state: dict[str, Any]
    ) -> list[TriggerSpecUpstreamJob]:
        saas_file_name = saas_file["name"]
        timeout = saas_file.get("timeout") or None
        pipelines_provider = self._get_pipelines_provider(saas_file)
        trigger_specs = []
        for rt in saas_file["resourceTemplates"]:
            rt_name = rt["name"]
            for target in rt["targets"]:
                upstream = target.get("upstream")
                if not upstream:
                    continue
                instance_name = upstream["instance"]["name"]
                job_name = upstream["name"]
                job_history = current_state[instance_name].get(job_name, [])
                if not job_history:
                    continue
                last_build_result = job_history[0]
                namespace = target["namespace"]
                cluster_name = namespace["cluster"]["name"]
                namespace_name = namespace["name"]
                env_name = namespace["environment"]["name"]
                trigger_spec = TriggerSpecUpstreamJob(
                    saas_file_name=saas_file_name,
                    env_name=env_name,
                    timeout=timeout,
                    pipelines_provider=pipelines_provider,
                    resource_template_name=rt_name,
                    cluster_name=cluster_name,
                    namespace_name=namespace_name,
                    instance_name=instance_name,
                    job_name=job_name,
                    state_content=last_build_result,
                )
                last_build_result_number = last_build_result["number"]
                if self.include_trigger_trace:
                    trigger_spec.reason = f"{upstream['instance']['serverUrl']}/job/{job_name}/{last_build_result_number}"
                state_build_result = self.state.get(trigger_spec.state_key, None)
                # skip if last_build_result is incomplete or
                # there is no change in job state
                if (
                    last_build_result["result"] is None
                    or last_build_result == state_build_result
                ):
                    continue
                # don't trigger if this is the first time
                # this target is being deployed.
                # that will be taken care of by
                # openshift-saas-deploy-trigger-configs
                if state_build_result is None:
                    # store the value to take over from now on
                    if not dry_run:
                        self.update_state(trigger_spec)
                    continue

                state_build_result_number = state_build_result["number"]
                # this is the most important condition
                # if there is a successful newer build -
                # trigger the deployment.
                # we only check the last build result. even
                # if there are newer ones, but the last one
                # is not successful, triggering the deployment
                # will end up in a failure.
                # in case job history was cleared and a new build
                # was successful, the number is likely lower from
                # what is stored in the state.
                # the only case we want to do nothing is if the last
                # build result matches what is stored in the state.
                if (
                    last_build_result_number != state_build_result_number
                    and last_build_result["result"] == "SUCCESS"
                ):
                    # we finally found something we want to trigger on!
                    trigger_specs.append(trigger_spec)

        return trigger_specs

    def get_container_images_diff(
        self, dry_run: bool
    ) -> list[TriggerSpecContainerImage]:
        results = threaded.run(
            self.get_container_images_diff_saas_file,
            self.saas_files,
            self.thread_pool_size,
            dry_run=dry_run,
        )
        return list(itertools.chain.from_iterable(results))

    def get_container_images_diff_saas_file(
        self, saas_file: dict[str, Any], dry_run: bool
    ) -> list[TriggerSpecContainerImage]:
        """
        Get a list of trigger specs based on the diff between the
        desired state (git commit) and the current state for a single saas file.
        """
        saas_file_name = saas_file["name"]
        timeout = saas_file.get("timeout") or None
        pipelines_provider = self._get_pipelines_provider(saas_file)
        github = self._initiate_github(saas_file)
        trigger_specs: list[TriggerSpecContainerImage] = []
        for rt in saas_file["resourceTemplates"]:
            rt_name = rt["name"]
            url = rt["url"]
            for target in rt["targets"]:
                try:
                    image = target.get("image")
                    if not image:
                        continue
                    ref = target["ref"]
                    hash_length = rt.get("hash_length") or self.settings["hashLength"]
                    get_commit_sha_options = {
                        "url": url,
                        "ref": ref,
                        "github": github,
                        "hash_length": hash_length,
                    }
                    desired_image_tag = self._get_commit_sha(get_commit_sha_options)
                    # don't trigger if image doesn't exist
                    image_registry = f"{image['org']['instance']['url']}/{image['org']['name']}/{image['name']}"
                    image_uri = f"{image_registry}:{desired_image_tag}"
                    image_patterns = saas_file["imagePatterns"]
                    image_auth = self._initiate_image_auth(saas_file)
                    error_prefix = f"[{saas_file_name}/{rt_name}] {ref}:"
                    error = self._check_image(
                        image_uri, image_patterns, image_auth, error_prefix
                    )
                    if error:
                        continue
                    namespace = target["namespace"]
                    cluster_name = namespace["cluster"]["name"]
                    namespace_name = namespace["name"]
                    env_name = namespace["environment"]["name"]
                    trigger_spec = TriggerSpecContainerImage(
                        saas_file_name=saas_file_name,
                        env_name=env_name,
                        timeout=timeout,
                        pipelines_provider=pipelines_provider,
                        resource_template_name=rt_name,
                        cluster_name=cluster_name,
                        namespace_name=namespace_name,
                        image=image_registry,
                        state_content=desired_image_tag,
                    )
                    if self.include_trigger_trace:
                        trigger_spec.reason = image_uri
                    current_image_tag = self.state.get(trigger_spec.state_key, None)
                    # skip if there is no change in image tag
                    if current_image_tag == desired_image_tag:
                        continue
                    # don't trigger if this is the first time
                    # this target is being deployed.
                    # that will be taken care of by
                    # openshift-saas-deploy-trigger-configs
                    if current_image_tag is None:
                        # store the value to take over from now on
                        if not dry_run:
                            self.update_state(trigger_spec)
                        continue
                    # we finally found something we want to trigger on!
                    trigger_specs.append(trigger_spec)
                except (GithubException, GitlabError):
                    logging.exception(
                        f"Skipping target {saas_file_name}:{rt_name}"
                        f" - repo: {url} - ref: {ref}"
                    )

        return trigger_specs

    def get_configs_diff(self) -> list[TriggerSpecConfig]:
        results = threaded.run(
            self.get_configs_diff_saas_file, self.saas_files, self.thread_pool_size
        )
        return list(itertools.chain.from_iterable(results))

    @staticmethod
    def remove_none_values(d):
        if d is None:
            return {}
        new = {}
        for k, v in d.items():
            if v is not None:
                if isinstance(v, dict):
                    v = SaasHerder.remove_none_values(v)
                new[k] = v
        return new

    def get_configs_diff_saas_file(
        self, saas_file: dict[str, Any]
    ) -> list[TriggerSpecConfig]:
        all_trigger_specs = self.get_saas_targets_config_trigger_specs(saas_file)
        trigger_specs = []

        for key, trigger_spec in all_trigger_specs.items():
            current_target_config = self.state.get(key, None)
            # Continue if there are no diffs between configs.
            # Compare existent values only, gql queries return None
            # values for non set attributes so any change in the saas
            # schema will trigger a job even though the saas file does
            # not have the new parameters set.
            ctc = SaasHerder.remove_none_values(current_target_config)
            dtc = SaasHerder.remove_none_values(trigger_spec.state_content)
            if ctc == dtc:
                continue

            if self.include_trigger_trace:
                trigger_spec.reason = (
                    f"{self.settings['repoUrl']}/commit/{RunningState().commit}"
                )
            trigger_specs.append(trigger_spec)
        return trigger_specs

    @staticmethod
    def get_target_config_hash(target_config):
        m = hashlib.sha256()
        m.update(json.dumps(target_config, sort_keys=True).encode("utf-8"))
        digest = m.hexdigest()[:16]
        return digest

    def get_saas_targets_config_trigger_specs(
        self, saas_file: dict[str, Any]
    ) -> dict[str, TriggerSpecConfig]:
        configs = {}
        saas_file_name = saas_file["name"]
        saas_file_parameters = saas_file.get("parameters")
        saas_file_managed_resource_types = saas_file["managedResourceTypes"]
        for rt in saas_file["resourceTemplates"]:
            rt_name = rt["name"]
            url = rt["url"]
            path = rt["path"]
            rt_parameters = rt.get("parameters")
            for v in rt["targets"]:
                # ChainMap will store modifications avoiding a deep copy
                desired_target_config = ChainMap({}, v)
                namespace = desired_target_config["namespace"]

                cluster_name = namespace["cluster"]["name"]
                namespace_name = namespace["name"]
                env_name = namespace["environment"]["name"]

                # This will add the namespace key/value to the chainMap, but
                # the target will remain with the original value
                # When the namespace key is looked up, the chainmap will
                # return the modified attribute ( set in the first mapping)
                desired_target_config["namespace"] = self.sanitize_namespace(namespace)
                # add parent parameters to target config
                desired_target_config["saas_file_parameters"] = saas_file_parameters
                # add managed resource types to target config
                desired_target_config[
                    "saas_file_managed_resource_types"
                ] = saas_file_managed_resource_types
                desired_target_config["url"] = url
                desired_target_config["path"] = path
                desired_target_config["rt_parameters"] = rt_parameters
                # Convert to dict, ChainMap is not JSON serializable
                # desired_target_config needs to be serialized to generate
                # its config hash and to be stored in S3
                serializable_target_config = dict(desired_target_config)
                trigger_spec = TriggerSpecConfig(
                    saas_file_name=saas_file_name,
                    env_name=env_name,
                    timeout=saas_file.get("timeout") or None,
                    pipelines_provider=self._get_pipelines_provider(saas_file),
                    resource_template_name=rt_name,
                    cluster_name=cluster_name,
                    namespace_name=namespace_name,
                    target_name=desired_target_config.get("name"),
                    state_content=serializable_target_config,
                )
                configs[trigger_spec.state_key] = trigger_spec

        return configs

    @staticmethod
    def _get_pipelines_provider(saas_file: Mapping[str, Any]) -> dict[str, Any]:
        return saas_file["pipelinesProvider"]

    @staticmethod
    def sanitize_namespace(namespace):
        """Only keep fields that should trigger a new job."""
        new_job_fields = {
            "namespace": ["name", "cluster", "app"],
            "cluster": ["name", "serverUrl"],
            "app": ["name"],
        }
        namespace = {
            k: v for k, v in namespace.items() if k in new_job_fields["namespace"]
        }
        cluster = namespace["cluster"]
        namespace["cluster"] = {
            k: v for k, v in cluster.items() if k in new_job_fields["cluster"]
        }
        app = namespace["app"]
        namespace["app"] = {k: v for k, v in app.items() if k in new_job_fields["app"]}
        return namespace

    def validate_promotions(self):
        """
        If there were promotion sections in the participating saas files
        validate that the conditions are met."""
        for item in self.promotions:
            if item is None:
                continue
            # validate that the commit sha being promoted
            # was succesfully published to the subscribed channel(s)
            subscribe = item.get("subscribe")
            if subscribe:
                commit_sha = item["commit_sha"]
                for channel in subscribe:
                    state_key = f"promotions/{channel}/{commit_sha}"
                    stateobj = self.state.get(state_key, {})
                    success = stateobj.get("success")
                    if not success:
                        logging.error(
                            f"Commit {commit_sha} was not "
                            + f"published with success to channel {channel}"
                        )
                        return False

                    state_config_hash = stateobj.get(TARGET_CONFIG_HASH)
                    promotion_data = item.get("promotion_data", None)

                    # This code supports current saas targets that does
                    # not have promotion_data yet
                    if not state_config_hash or not promotion_data:
                        logging.info(
                            "Promotion data is missing; rely on the success "
                            "state only"
                        )
                        return True

                    # Validate the promotion_data section.
                    # Just validate parent_saas_config hash
                    # promotion_data type by now.
                    parent_saas_config = None
                    for pd in promotion_data:
                        pd_channel = pd.get("channel")
                        if pd_channel == channel:
                            channel_data = pd.get("data")
                            for data in channel_data:
                                t = data.get("type")
                                if t == "parent_saas_config":
                                    parent_saas_config = data

                    # This section might not exist due to a manual MR.
                    # Promotion shall continue if this data is missing.
                    # The parent at the same ref has succeed if this code
                    # is reached though.
                    if not parent_saas_config:
                        logging.info(
                            "Parent Saas config missing on target "
                            "rely on the success state only"
                        )
                        return True

                    # Validate that the state config_hash set by the parent
                    # matches with the hash set in promotion_data
                    promotion_target_config_hash = parent_saas_config.get(
                        TARGET_CONFIG_HASH
                    )

                    if promotion_target_config_hash == state_config_hash:
                        return True
                    else:
                        logging.error(
                            "Parent saas target has run with a newer "
                            "configuration and the same commit (ref). "
                            "Check if other MR exists for this target"
                        )
                        return False
        return True

    def publish_promotions(self, success, all_saas_files, mr_cli, auto_promote=False):
        """
        If there were promotion sections in the participating saas file
        publish the results for future promotion validations."""
        (
            subscribe_saas_file_path_map,
            subscribe_target_path_map,
        ) = self._get_subscribe_path_map(all_saas_files, auto_only=True)
        trigger_promotion = False

        if self.promotions and not auto_promote:
            logging.info(
                "Auto-promotions to next stages are disabled. This could"
                "happen if the current stage does not make any change"
            )

        for item in self.promotions:
            if item is None:
                continue
            commit_sha = item["commit_sha"]
            publish = item.get("publish")
            if publish:
                value = {
                    "success": success,
                    "saas_file": item["saas_file"],
                    TARGET_CONFIG_HASH: item.get(TARGET_CONFIG_HASH),
                }
                all_subscribed_saas_file_paths = set()
                all_subscribed_target_paths = set()
                for channel in publish:
                    # publish to state to pass promotion gate
                    state_key = f"promotions/{channel}/{commit_sha}"
                    self.state.add(state_key, value, force=True)
                    logging.info(
                        f"Commit {commit_sha} was published "
                        + f"with success {success} to channel {channel}"
                    )
                    # collect data to trigger promotion
                    subscribed_saas_file_paths = subscribe_saas_file_path_map.get(
                        channel
                    )

                    if subscribed_saas_file_paths:
                        all_subscribed_saas_file_paths.update(
                            subscribed_saas_file_paths
                        )

                    subscribed_target_paths = subscribe_target_path_map.get(channel)
                    if subscribed_target_paths:
                        all_subscribed_target_paths.update(subscribed_target_paths)

                item["saas_file_paths"] = list(all_subscribed_saas_file_paths)
                item["target_paths"] = list(all_subscribed_target_paths)

                if auto_promote and (
                    all_subscribed_saas_file_paths or all_subscribed_target_paths
                ):
                    trigger_promotion = True

        if success and trigger_promotion:
            mr = AutoPromoter(self.promotions)
            mr.submit(cli=mr_cli)

    @staticmethod
    def _get_subscribe_path_map(
        saas_files: Iterable[Mapping[str, Any]], auto_only: bool = False
    ) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
        """
        Returns dicts with subscribe channels as keys and a
        list of paths of saas files or targets containing these channels.
        """
        subscribe_saas_file_path_map: Dict[str, Set[str]] = {}
        subscribe_target_path_map: Dict[str, Set[str]] = {}
        for saas_file in saas_files:
            saas_file_path = "data" + saas_file["path"]
            for rt in saas_file["resourceTemplates"]:
                for target in rt["targets"]:
                    target_promotion = target.get("promotion")
                    if not target_promotion:
                        continue
                    target_auto = target_promotion.get("auto")
                    if auto_only and not target_auto:
                        continue
                    subscribe = target_promotion.get("subscribe")
                    if not subscribe:
                        continue
                    # targets with a path are referenced and not inlined
                    target_path = target.get("path")
                    if target_path:
                        target_path = "data" + target_path
                    for channel in subscribe:
                        subscribe_saas_file_path_map.setdefault(channel, set())
                        subscribe_saas_file_path_map[channel].add(saas_file_path)
                        if target_path:
                            subscribe_target_path_map.setdefault(channel, set())
                            subscribe_target_path_map[channel].add(target_path)

        return subscribe_saas_file_path_map, subscribe_target_path_map

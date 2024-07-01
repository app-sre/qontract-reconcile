import base64
import hashlib
import itertools
import json
import logging
import os
import re
from collections import (
    ChainMap,
    defaultdict,
)
from collections.abc import (
    Generator,
    Iterable,
    Mapping,
    MutableMapping,
    Sequence,
)
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any
from urllib.parse import urlparse

import yaml
from github import (
    Github,
    GithubException,
)
from github.ContentFile import ContentFile
from github.Repository import Repository
from gitlab.exceptions import GitlabError
from requests import exceptions as rqexc
from sretoolbox.container import Image
from sretoolbox.utils import (
    retry,
    threaded,
)

from reconcile.github_org import get_default_config
from reconcile.status import RunningState
from reconcile.utils import helm
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.jenkins_api import JenkinsApi
from reconcile.utils.jjb_client import JJB
from reconcile.utils.oc import (
    OCLocal,
    StatusCodeError,
)
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import (
    ResourceInventory,
    ResourceKeyExistsError,
    ResourceNotManagedError,
    fully_qualified_kind,
)
from reconcile.utils.promotion_state import (
    PromotionData,
    PromotionState,
)
from reconcile.utils.saasherder.interfaces import (
    SaasFile,
    SaasParentSaasPromotion,
    SaasResourceTemplate,
    SaasResourceTemplateTarget,
    SaasResourceTemplateTargetNamespace,
    SaasResourceTemplateTargetPromotion,
    SaasSecretParameters,
)
from reconcile.utils.saasherder.models import (
    Channel,
    ImageAuth,
    Namespace,
    Promotion,
    TargetSpec,
    TriggerSpecConfig,
    TriggerSpecContainerImage,
    TriggerSpecMovingCommit,
    TriggerSpecUnion,
    TriggerSpecUpstreamJob,
    TriggerTypes,
    UpstreamJob,
)
from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.state import State

TARGET_CONFIG_HASH = "target_config_hash"


UNIQUE_SAAS_FILE_ENV_COMBO_LEN = 56
REQUEST_TIMEOUT = 60


def is_commit_sha(ref: str) -> bool:
    """Check if the given ref is a commit sha."""
    return bool(re.search(r"^[0-9a-f]{40}$", ref))


# saas_name, resource_template_name, resource_template_url, target_uid
RtRef = tuple[str, str, str, str]
Resource = dict[str, Any]
Resources = list[Resource]


class SaasHerder:  # pylint: disable=too-many-public-methods
    """Wrapper around SaaS deployment actions."""

    def __init__(
        self,
        saas_files: Sequence[SaasFile],
        thread_pool_size: int,
        integration: str,
        integration_version: str,
        secret_reader: SecretReaderBase,
        hash_length: int,
        repo_url: str,
        gitlab: GitLabApi | None = None,
        jenkins_map: dict[str, JenkinsApi] | None = None,
        state: State | None = None,
        validate: bool = False,
        include_trigger_trace: bool = False,
        all_saas_files: Iterable[SaasFile] | None = None,
    ):
        self.error_registered = False
        self.saas_files = saas_files
        self.repo_urls = self._collect_repo_urls()
        self.resolve_templated_parameters(self.saas_files)
        if validate:
            self._validate_saas_files()
            if not self.valid:
                return
        self.thread_pool_size = thread_pool_size
        self.gitlab = gitlab
        self.integration = integration
        self.integration_version = integration_version
        self.hash_length = hash_length
        self.repo_url = repo_url
        self.secret_reader = secret_reader
        self.namespaces = self._collect_namespaces()
        self.jenkins_map = jenkins_map
        self.include_trigger_trace = include_trigger_trace
        self.state = state
        self._promotion_state = PromotionState(state=state) if state else None
        self._channel_map = self._assemble_channels(saas_files=all_saas_files)
        self.images: set[str] = set()
        self.blocked_versions = self._collect_blocked_versions()
        self.hotfix_versions = self._collect_hotfix_versions()

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
        self.publish_job_logs = self._get_saas_file_feature_enabled("publish_job_logs")
        self.cluster_admin = self._get_saas_file_feature_enabled("cluster_admin")

    def __enter__(self) -> "SaasHerder":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        if hasattr(self, "state") and self.state is not None:
            self.state.cleanup()
        if hasattr(self, "gitlab") and self.gitlab is not None:
            self.gitlab.cleanup()

    def _register_error(self) -> None:
        self.error_registered = True

    @property
    def has_error_registered(self) -> bool:
        return self.error_registered

    def __iter__(
        self,
    ) -> Generator[
        tuple[SaasFile, SaasResourceTemplate, SaasResourceTemplateTarget],
        None,
        None,
    ]:
        for saas_file in self.saas_files:
            for resource_template in saas_file.resource_templates:
                for target in resource_template.targets:
                    yield (saas_file, resource_template, target)

    def _get_saas_file_feature_enabled(
        self, name: str, default: bool | None = None
    ) -> bool | None:
        """Returns a bool indicating if a feature is enabled in a saas file,
        or a supplied default. Returns False if there are multiple
        saas files in the process.
        All features using this method should assume a single saas file.
        """
        if len(self.saas_files) > 1:
            return False

        sf_attribute = getattr(self.saas_files[0], name, None)
        if sf_attribute is None and default is not None:
            return default
        return sf_attribute

    def _validate_allowed_secret_parameter_paths(
        self,
        saas_file_name: str,
        secret_parameters: SaasSecretParameters,
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
            match = [
                a
                for a in allowed_secret_parameter_paths
                if (os.path.commonpath([sp.secret.path, a]) == a)
            ]
            if not match:
                self.valid = False
                logging.error(
                    f"[{saas_file_name}] "
                    f"secret parameter path '{sp.secret.path}' does not match any of allowedSecretParameterPaths"
                )

    def _validate_target_in_app(
        self, saas_file: SaasFile, target: SaasResourceTemplateTarget
    ) -> None:
        if saas_file.validate_targets_in_app:
            valid_app_names = {saas_file.app.name}
            if saas_file.app.parent_app:
                valid_app_names.add(saas_file.app.parent_app.name)
            if target.namespace.app.name not in valid_app_names:
                logging.error(
                    f"[{saas_file.name}] targets must be within app(s) {valid_app_names}"
                )
                self.valid = False

    def _validate_saas_files(self) -> None:
        self.valid = True
        saas_file_name_path_map: dict[str, list[str]] = {}
        tkn_unique_pipelineruns: dict[str, str] = {}

        publications: dict[str, set[RtRef]] = defaultdict(set)
        subscriptions: dict[str, list[RtRef]] = defaultdict(list)

        for saas_file in self.saas_files:
            saas_file_name_path_map.setdefault(saas_file.name, [])
            saas_file_name_path_map[saas_file.name].append(saas_file.path)

            if not saas_file.app.self_service_roles:
                logging.error(
                    f"app {saas_file.app.name} has no self-service roles (saas file {saas_file.name})"
                )
                self.valid = False

            self._validate_allowed_secret_parameter_paths(
                saas_file.name,
                saas_file.secret_parameters or [],
                saas_file.allowed_secret_parameter_paths or [],
            )

            for resource_template in saas_file.resource_templates:
                self._validate_allowed_secret_parameter_paths(
                    saas_file.name,
                    resource_template.secret_parameters or [],
                    saas_file.allowed_secret_parameter_paths or [],
                )
                for target in resource_template.targets:
                    # unique saas file and env name combination
                    tkn_name, tkn_long_name = self._check_saas_file_env_combo_unique(
                        saas_file.name,
                        target.namespace.environment.name,
                        tkn_unique_pipelineruns,
                    )
                    tkn_unique_pipelineruns[tkn_name] = tkn_long_name
                    self._validate_auto_promotion_used_with_commit_sha(
                        saas_file.name,
                        resource_template.name,
                        target,
                    )
                    self._validate_upstream_not_used_with_commit_sha(
                        saas_file.name,
                        resource_template.name,
                        target,
                    )
                    self._validate_upstream_not_used_with_image(
                        saas_file.name,
                        resource_template.name,
                        target,
                    )
                    self._validate_image_not_used_with_commit_sha(
                        saas_file.name,
                        resource_template.name,
                        target,
                    )
                    self._validate_dangling_target_config_hashes(
                        saas_file.name,
                        resource_template.name,
                        target,
                    )
                    self._validate_allowed_secret_parameter_paths(
                        saas_file.name,
                        target.secret_parameters or [],
                        saas_file.allowed_secret_parameter_paths or [],
                    )
                    self._validate_allowed_secret_parameter_paths(
                        saas_file.name,
                        target.namespace.environment.secret_parameters or [],
                        saas_file.allowed_secret_parameter_paths or [],
                    )
                    self._validate_target_in_app(saas_file, target)

                    if target.promotion:
                        rt_ref = (
                            saas_file.path,
                            resource_template.name,
                            resource_template.url,
                            target.uid(
                                parent_saas_file_name=saas_file.name,
                                parent_resource_template_name=resource_template.name,
                            ),
                        )

                        # Get publications and subscriptions for the target
                        self._get_promotion_pubs_and_subs(
                            rt_ref, target.promotion, publications, subscriptions
                        )
                    # validate target parameters
                    if not target.parameters:
                        continue
                    self._validate_image_tag_not_equals_ref(
                        saas_file.name,
                        resource_template.name,
                        target.ref,
                        target.parameters,
                    )

                    if not target.namespace.environment.parameters:
                        continue
                    msg = (
                        f"[{saas_file.name}/{resource_template.name}] "
                        + "parameter found in target "
                        + f"{target.namespace.cluster.name}/{target.namespace.name} "
                        + f"should be reused from env {target.namespace.environment.name}"
                    )
                    for t_key, t_value in target.parameters.items():
                        if not isinstance(t_value, str):
                            continue
                        # Check for recursivity. Ex: PARAM: "foo.${PARAM}"
                        replace_pattern = "${" + t_key + "}"
                        if replace_pattern in t_value:
                            logging.error(
                                f"[{saas_file.name}/{resource_template.name}] "
                                f"recursivity in parameter name and value "
                                f'found: {t_key}: "{t_value}" - this will '
                                f"likely not work as expected. Please consider"
                                f" changing the parameter name"
                            )
                            self.valid = False
                        for (
                            e_key,
                            e_value,
                        ) in target.namespace.environment.parameters.items():
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
        rt_ref: RtRef,
        promotion: SaasResourceTemplateTargetPromotion,
        publications: MutableMapping[str, set[RtRef]],
        subscriptions: MutableMapping[str, list[RtRef]],
    ) -> None:
        """
        Function to gather promotion publish and subscribe configurations
        It validates a publish channel is unique across all publish targets.
        """
        for channel in promotion.publish or []:
            if rt_ref in publications[channel]:
                self.valid = False
                # This should never be possible theoretically ...
                logging.error(
                    f"Non-unique resource template reference {rt_ref} in "
                    f"channel {channel}"
                )
                continue
            publications[channel].add(rt_ref)

        for channel in promotion.subscribe or []:
            subscriptions[channel].append(rt_ref)

    def _check_promotions_have_same_source(
        self,
        subscriptions: Mapping[str, list[RtRef]],
        publications: Mapping[str, set[RtRef]],
    ) -> None:
        """
        Function to check that a promotion has the same repository
        in both publisher and subscriber targets.
        """

        for sub_channel, sub_targets in subscriptions.items():
            pub_channel_refs = publications.get(sub_channel, set())
            for sub_saas, sub_rt_name, sub_rt_url, _ in sub_targets:
                if not pub_channel_refs:
                    self.valid = False
                    logging.error(
                        "Channel is not published by any target\n"
                        f"subscriber_saas: {sub_saas}\n"
                        f"subscriber_rt: {sub_rt_name}\n"
                        f"channel: {sub_channel}"
                    )
                for pub_ref in pub_channel_refs:
                    (pub_saas, pub_rt_name, pub_rt_url, _) = pub_ref
                    if sub_rt_url != pub_rt_url:
                        self.valid = False
                        logging.error(
                            "Subscriber and Publisher targets have different "
                            "source repositories\n"
                            f"publisher_saas: {pub_saas}\n"
                            f"publisher_rt: {pub_rt_name}\n"
                            f"publisher_repo: {pub_rt_url}\n"
                            f"subscriber_saas: {sub_saas}\n"
                            f"subscriber_rt: {sub_rt_name}\n"
                            f"subscriber_repo: {sub_rt_url}\n"
                        )

    @staticmethod
    def build_saas_file_env_combo(
        saas_file_name: str,
        env_name: str,
    ) -> tuple[str, str]:
        """
        Build a tuple of short and long names for a saas file and environment combo,
        max tekton pipelinerun name length can be 63,
        leaving 7 for the rerun leaves us with 56 to create a unique pipelinerun name.

        :param saas_file_name: name of the saas file
        :param env_name: name of the environment
        :return: (tkn_name, tkn_long_name)
        """
        tkn_long_name = f"{saas_file_name}-{env_name}"
        tkn_name = tkn_long_name[:UNIQUE_SAAS_FILE_ENV_COMBO_LEN].rstrip("-")
        return tkn_name, tkn_long_name

    def _check_saas_file_env_combo_unique(
        self,
        saas_file_name: str,
        env_name: str,
        tkn_unique_pipelineruns: Mapping[str, str],
    ) -> tuple[str, str]:
        tkn_name, tkn_long_name = self.build_saas_file_env_combo(
            saas_file_name, env_name
        )
        if (
            tkn_name in tkn_unique_pipelineruns
            and tkn_unique_pipelineruns[tkn_name] != tkn_long_name
        ):
            logging.error(
                f"[{saas_file_name}/{env_name}] "
                "saas file and env name combination must be "
                f"unique in first {UNIQUE_SAAS_FILE_ENV_COMBO_LEN} chars. "
                f"found not unique value: {tkn_name} "
                f"from this long name: {tkn_long_name}"
            )
            self.valid = False

        return tkn_name, tkn_long_name

    def _validate_auto_promotion_used_with_commit_sha(
        self,
        saas_file_name: str,
        resource_template_name: str,
        target: SaasResourceTemplateTarget,
    ) -> None:
        if not target.promotion:
            return

        if not target.promotion.auto:
            return

        if not is_commit_sha(target.ref):
            self.valid = False
            logging.error(
                f"[{saas_file_name}/{resource_template_name}] "
                f"auto promotion should be used with commit sha instead of: {target.ref}"
            )

    def _validate_upstream_not_used_with_commit_sha(
        self,
        saas_file_name: str,
        resource_template_name: str,
        target: SaasResourceTemplateTarget,
    ) -> None:
        if target.upstream and is_commit_sha(target.ref):
            logging.error(
                f"[{saas_file_name}/{resource_template_name}] "
                f"upstream used with commit sha: {target.ref}"
            )
            self.valid = False

    def _validate_upstream_not_used_with_image(
        self,
        saas_file_name: str,
        resource_template_name: str,
        target: SaasResourceTemplateTarget,
    ) -> None:
        if target.image and target.upstream:
            logging.error(
                f"[{saas_file_name}/{resource_template_name}] "
                f"image used with upstream"
            )
            self.valid = False

    def _validate_image_not_used_with_commit_sha(
        self,
        saas_file_name: str,
        resource_template_name: str,
        target: SaasResourceTemplateTarget,
    ) -> None:
        if target.image and is_commit_sha(target.ref):
            logging.error(
                f"[{saas_file_name}/{resource_template_name}] "
                f"image used with commit sha: {target.ref}"
            )
            self.valid = False

    def _validate_image_tag_not_equals_ref(
        self,
        saas_file_name: str,
        resource_template_name: str,
        ref: str,
        parameters: dict,
    ) -> None:
        image_tag = parameters.get("IMAGE_TAG")
        if image_tag and str(ref).startswith(str(image_tag)):
            logging.error(
                f"[{saas_file_name}/{resource_template_name}] "
                f"IMAGE_TAG {image_tag} is the same as ref {ref}. "
                "please remove the IMAGE_TAG parameter, it is automatically generated."
            )
            self.valid = False

    def _validate_dangling_target_config_hashes(
        self,
        saas_file_name: str,
        resource_template_name: str,
        target: SaasResourceTemplateTarget,
    ) -> None:
        if not target.promotion:
            return

        if not target.promotion.auto:
            return

        if not target.promotion.subscribe:
            return

        sub_channels = set(target.promotion.subscribe)
        for prom_data in target.promotion.promotion_data or []:
            if prom_data.channel not in sub_channels:
                self.valid = False
                logging.error(
                    f"[{saas_file_name}/{resource_template_name}] "
                    "Promotion data detected for unsubscribed channel. "
                    "Maybe a subscribed channel was removed and you forgot "
                    "to remove its corresponding promotion_data block? "
                    f"Please remove promotion_data for channel {prom_data.channel}."
                )

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
    ) -> None:
        all_jobs = jjb.get_all_jobs(job_types=["build"])
        for sf, rt, t in self:
            if is_commit_sha(t.ref):
                continue

            if t.upstream:
                upstream_job = UpstreamJob(t.upstream.instance.name, t.upstream.name)
                possible_upstream_jobs = self._get_upstream_jobs(
                    jjb, all_jobs, rt.url, t.ref
                )
                found_jobs = [
                    j
                    for j in all_jobs[upstream_job.instance]
                    if j["name"] == upstream_job.job
                ]
                if found_jobs:
                    if upstream_job not in possible_upstream_jobs:
                        logging.error(
                            f"[{sf.name}/{rt.name}] upstream job "
                            f"incorrect: {upstream_job}. "
                            f"should be one of: {possible_upstream_jobs}"
                        )
                        self.valid = False
                else:
                    logging.error(
                        f"[{sf.name}/{rt.name}] upstream job "
                        f"not found: {upstream_job}. "
                        f"should be one of: {possible_upstream_jobs}"
                    )
                    self.valid = False

    def _collect_namespaces(self) -> list[Namespace]:
        # namespaces may appear more then once in the result
        namespaces = []
        for saas_file in self.saas_files:
            for rt in saas_file.resource_templates:
                for target in rt.targets:
                    if target.disable:
                        logging.debug(
                            f"[{saas_file.name}/{rt.name}] target "
                            + f"{target.namespace.cluster.name} /"
                            + f"{target.namespace.name} is disabled."
                        )
                        continue

                    namespaces.append(
                        Namespace(
                            name=target.namespace.name,
                            environment=target.namespace.environment,
                            app=target.namespace.app,
                            cluster=target.namespace.cluster,
                            # managedResourceTypes and managedResourceNames are defined per saas_file
                            # add them to each namespace in the current saas_file
                            managed_resource_types=saas_file.managed_resource_types,
                            managed_resource_names=saas_file.managed_resource_names,
                        )
                    )
        return namespaces

    def _collect_repo_urls(self) -> set[str]:
        return set(
            rt.url
            for saas_file in self.saas_files
            for rt in saas_file.resource_templates
        )

    @staticmethod
    def _get_file_contents_github(repo: Repository, path: str, commit_sha: str) -> str:
        f = repo.get_contents(path, commit_sha)
        if isinstance(f, list):
            raise Exception(f"Path {path} and sha {commit_sha} is a directory!")

        if f.size < 1024**2:  # 1 MB
            return f.decoded_content.decode("utf8")

        tree = repo.get_git_tree(commit_sha, recursive="/" in path).tree
        for x in tree:
            if x.path != path.lstrip("/"):
                continue
            blob = repo.get_git_blob(x.sha)
            return base64.b64decode(blob.content).decode("utf8")

        return ""

    @retry(max_attempts=20)
    def get_archive_info(
        self,
        saas_file: SaasFile,
        trigger_reason: str,
    ) -> tuple[str, str]:
        [url, sha] = trigger_reason.split(" ")[0].split("/commit/")
        repo_name = urlparse(url).path.strip("/")
        file_name = f"{repo_name.replace('/', '-')}-{sha}.tar.gz"
        if "github" in url:
            github = self._initiate_github(saas_file, base_url="https://api.github.com")
            repo = github.get_repo(repo_name)
            # get_archive_link get redirect url form header, it does not work with github-mirror
            archive_url = repo.get_archive_link("tarball", ref=sha)
        elif "gitlab" in url:
            archive_url = f"{url}/-/archive/{sha}/{file_name}"
        else:
            raise Exception(f"Only GitHub and GitLab are supported: {url}")

        return file_name, archive_url

    @retry(max_attempts=20)
    def _get_file_contents(
        self, url: str, path: str, ref: str, github: Github
    ) -> tuple[Any, str]:
        commit_sha = self._get_commit_sha(url, ref, github)

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
        else:
            raise Exception(f"Only GitHub and GitLab are supported: {url}")

        return yaml.safe_load(content), commit_sha

    @retry()
    def _get_directory_contents(
        self, url: str, path: str, ref: str, github: Github
    ) -> tuple[list[Any], str]:
        commit_sha = self._get_commit_sha(url, ref, github)
        resources: list[Any] = []
        if "github" in url:
            repo_name = url.rstrip("/").replace("https://github.com/", "")
            repo = github.get_repo(repo_name)
            directory = repo.get_contents(path, commit_sha)
            if isinstance(directory, ContentFile):
                raise Exception(f"Path {path} and sha {commit_sha} is a file!")
            for f in directory:
                file_path = os.path.join(path, f.name)
                file_contents_decoded = self._get_file_contents_github(
                    repo, file_path, commit_sha
                )
                result_resources = yaml.safe_load_all(file_contents_decoded)
                resources.extend(result_resources)
        elif "gitlab" in url:
            if not self.gitlab:
                raise Exception("gitlab is not initialized")
            project = self.gitlab.get_project(url)
            for item in self.gitlab.get_items(
                project.repository_tree, path=path.lstrip("/"), ref=commit_sha
            ):
                file_contents = project.files.get(
                    file_path=item["path"], ref=commit_sha
                )
                resource = yaml.safe_load(file_contents.decode())
                resources.append(resource)
        else:
            raise Exception(f"Only GitHub and GitLab are supported: {url}")

        return resources, commit_sha

    @retry()
    def _get_commit_sha(self, url: str, ref: str, github: Github) -> str:
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
            commits = project.commits.list(ref_name=ref, per_page=1, page=1)
            commit_sha = commits[0].id

        return commit_sha

    @staticmethod
    def _additional_resource_process(resources: Resources, html_url: str) -> None:
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
    def _parameter_value_needed(
        parameter_name: str,
        consolidated_parameters: Mapping[str, str],
        template: Mapping[str, Any],
    ) -> bool:
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

    def _process_template(self, spec: TargetSpec) -> tuple[list[Any], Promotion | None]:
        saas_file_name = spec.saas_file_name
        resource_template_name = spec.resource_template_name
        url = spec.url
        path = spec.path
        ref = spec.ref
        provider = spec.provider
        hash_length = spec.hash_length
        target = spec.target
        github = spec.github
        target_config_hash = spec.target_config_hash
        error_prefix = spec.error_prefix

        if provider == "openshift-template":
            consolidated_parameters = spec.parameters()
            try:
                template, commit_sha = self._get_file_contents(
                    url=url, path=path, ref=ref, github=github
                )
            except Exception as e:
                logging.error(f"{error_prefix} error fetching template: {str(e)}")
                raise

            # add COMMIT_SHA only if it is unspecified
            consolidated_parameters.setdefault("COMMIT_SHA", commit_sha)

            # add IMAGE_TAG only if it is unspecified
            if not (image_tag := consolidated_parameters.get("IMAGE_TAG", "")):
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
                            f"{error_prefix} CHANNEL is required when "
                            + "'use_channel_in_image_tag' is true."
                        )
                        raise
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
                        f"{error_prefix} error generating REPO_DIGEST. "
                        + "Is REGISTRY_IMG missing? "
                        + f"{str(e)}"
                    )
                    raise

                image_uri = f"{registry_image}:{image_tag}"
                img = self._get_image(
                    image=image_uri,
                    image_patterns=spec.image_patterns,
                    image_auth=spec.image_auth,
                    error_prefix=error_prefix,
                )
                if not img:
                    msg = f"{error_prefix} error get image for {image_uri}"
                    logging.error(msg)
                    raise Exception(msg)

                if need_repo_digest:
                    consolidated_parameters["REPO_DIGEST"] = img.url_digest
                if need_image_digest:
                    consolidated_parameters["IMAGE_DIGEST"] = img.digest

            oc = OCLocal("cluster", None, None, local=True)
            try:
                resources = oc.process(template, consolidated_parameters)
            except StatusCodeError as e:
                logging.error(f"{error_prefix} error processing template: {str(e)}")

        elif provider == "directory":
            try:
                resources, commit_sha = self._get_directory_contents(
                    url=url, path=path, ref=ref, github=github
                )
            except Exception as e:
                logging.error(
                    f"{error_prefix} error fetching directory: {str(e)} "
                    + "(We do not support nested directories. Do you by chance have subdirectories?)"
                )
                raise

        elif provider == "helm":
            ssl_verify = (
                self.gitlab.ssl_verify
                if self.gitlab and url.startswith(self.gitlab.server)
                else True
            )
            consolidated_parameters = spec.parameters(adjust=False)
            image = consolidated_parameters.get("image", {})
            if isinstance(image, dict) and not image.get("tag"):
                commit_sha = self._get_commit_sha(url, ref, github)
                image_tag = commit_sha[:hash_length]
                consolidated_parameters.setdefault("image", {})["tag"] = image_tag
            resources = helm.template_all(
                url=url,
                path=path,
                name=resource_template_name,
                values=consolidated_parameters,
                ssl_verify=ssl_verify,
            )

        else:
            logging.error(f"{error_prefix} unknown provider: {provider}")

        target_promotion = None
        if target.promotion:
            channels = [
                self._channel_map[sub] for sub in target.promotion.subscribe or []
            ]
            target_promotion = Promotion(
                url=url,
                auto=target.promotion.auto,
                publish=target.promotion.publish,
                subscribe=channels,
                promotion_data=target.promotion.promotion_data,
                commit_sha=commit_sha,
                saas_file=saas_file_name,
                target_config_hash=target_config_hash,
                saas_target_uid=target.uid(
                    parent_resource_template_name=resource_template_name,
                    parent_saas_file_name=saas_file_name,
                ),
                soak_days=target.promotion.soak_days or 0,
            )
        return resources, target_promotion

    def _assemble_channels(
        self, saas_files: Iterable[SaasFile] | None
    ) -> dict[str, Channel]:
        """
        We need to assemble all publisher_uids that are publishing to a channel.
        These uids are required to validate correctness of promotions.
        """
        channel_map: dict[str, Channel] = {}
        for saas_file in saas_files or []:
            for tmpl in saas_file.resource_templates:
                for target in tmpl.targets:
                    if not target.promotion:
                        continue
                    for publish in target.promotion.publish or []:
                        publisher_uid = target.uid(
                            parent_saas_file_name=saas_file.name,
                            parent_resource_template_name=tmpl.name,
                        )
                        if publish not in channel_map:
                            channel_map[publish] = Channel(
                                name=publish,
                                publisher_uids=[],
                            )
                        channel_map[publish].publisher_uids.append(publisher_uid)
        return channel_map

    def _collect_blocked_versions(self) -> dict[str, set[str]]:
        blocked_versions: dict[str, set[str]] = {}
        for saas_file in self.saas_files:
            for cc in saas_file.app.code_components or []:
                for v in cc.blocked_versions or []:
                    blocked_versions.setdefault(cc.url, set()).add(v)
        return blocked_versions

    def _collect_hotfix_versions(self) -> dict[str, set[str]]:
        hotfix_versions: dict[str, set[str]] = {}
        for saas_file in self.saas_files:
            for cc in saas_file.app.code_components or []:
                for v in cc.hotfix_versions or []:
                    hotfix_versions.setdefault(cc.url, set()).add(v)
        return hotfix_versions

    @staticmethod
    def _collect_images(resource: Resource) -> set[str]:
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
    def _get_image(
        image: str,
        image_patterns: Iterable[str],
        image_auth: ImageAuth,
        error_prefix: str,
    ) -> Image | None:
        if not image_patterns:
            logging.error(
                f"{error_prefix} imagePatterns is empty (does not contain {image})"
            )
            return None
        if image_patterns and not any(image.startswith(p) for p in image_patterns):
            logging.error(f"{error_prefix} Image is not in imagePatterns: {image}")
            return None

        # .dockerconfigjson
        if image_auth.docker_config:
            # we rely on the secret in vault being ordered
            # https://peps.python.org/pep-0468/
            for registry, auth in image_auth.docker_config["auths"].items():
                if not image.startswith(registry):
                    continue
                username, password = (
                    base64.b64decode(auth["auth"]).decode("utf-8").split(":")
                )
                with suppress(Exception):
                    return Image(
                        image,
                        username=username,
                        password=password,
                        auth_server=image_auth.auth_server,
                        timeout=REQUEST_TIMEOUT,
                    )

        # basic auth fallback for backwards compatibility
        try:
            return Image(
                image,
                username=image_auth.username,
                password=image_auth.password,
                auth_server=image_auth.auth_server,
                timeout=REQUEST_TIMEOUT,
            )
        except Exception as e:
            logging.error(
                f"{error_prefix} Image is invalid: {image}. " + f"details: {str(e)}"
            )

        return None

    def _check_images(
        self,
        spec: TargetSpec,
        resources: Resources,
    ) -> bool:
        images_list = threaded.run(
            self._collect_images, resources, self.available_thread_pool_size
        )
        images = set(itertools.chain.from_iterable(images_list))
        self.images.update(images)
        if not images:
            return False  # no errors
        images = threaded.run(
            self._get_image,
            images,
            self.available_thread_pool_size,
            image_patterns=spec.image_patterns,
            image_auth=spec.image_auth,
            error_prefix=spec.error_prefix,
        )
        return None in images

    def _initiate_github(
        self, saas_file: SaasFile, base_url: str | None = None
    ) -> Github:
        token = (
            self.secret_reader.read_secret(saas_file.authentication.code)
            if saas_file.authentication and saas_file.authentication.code
            else get_default_config()["token"]
        )
        if not base_url:
            base_url = os.environ.get("GITHUB_API", "https://api.github.com")
        return Github(token, base_url=base_url)

    def _initiate_image_auth(self, saas_file: SaasFile) -> ImageAuth:
        """
        This function initiates an ImageAuth class required for image authentication.
        This class will be used as parameters for sretoolbox's Image.
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
        if not saas_file.authentication or not saas_file.authentication.image:
            return ImageAuth()

        creds = self.secret_reader.read_all_secret(saas_file.authentication.image)
        required_docker_config_keys = [".dockerconfigjson"]
        required_keys_basic_auth = ["user", "token"]
        ok = all(k in creds.keys() for k in required_keys_basic_auth) or all(
            k in creds.keys() for k in required_docker_config_keys
        )
        if not ok:
            logging.warning(
                "the specified image authentication secret "
                + f"found in path {saas_file.authentication.image.path} "
                + f"does not contain all required keys: {required_docker_config_keys} or {required_keys_basic_auth}"
            )
            return ImageAuth()

        return ImageAuth(
            username=creds.get("user"),
            password=creds.get("token"),
            auth_server=creds.get("url"),
            docker_config=json.loads(creds.get(".dockerconfigjson") or "{}"),
        )

    def populate_desired_state(self, ri: ResourceInventory) -> None:
        results = threaded.run(
            self._init_populate_desired_state_specs,
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
        self.promotions: list[Promotion | None] = promotions

    def _init_populate_desired_state_specs(
        self, saas_file: SaasFile
    ) -> list[TargetSpec]:
        specs = []
        github = self._initiate_github(saas_file)
        image_auth = self._initiate_image_auth(saas_file)
        all_trigger_specs = self.get_saas_targets_config_trigger_specs(saas_file)
        # iterate over resource templates (multiple per saas_file)
        for rt in saas_file.resource_templates:
            hash_length = rt.hash_length or self.hash_length
            # Iterate over targets (each target is a namespace).
            for target in rt.targets:
                if target.disable:
                    # Warning is logged during SaasHerder initiation.
                    continue

                state_key = TriggerSpecConfig(
                    saas_file_name=saas_file.name,
                    env_name=target.namespace.environment.name,
                    timeout=None,
                    pipelines_provider=saas_file.pipelines_provider,
                    resource_template_name=rt.name,
                    cluster_name=target.namespace.cluster.name,
                    namespace_name=target.namespace.name,
                    target_name=target.name,
                    state_content=None,
                ).state_key
                digest = SaasHerder.get_target_config_hash(
                    all_trigger_specs[state_key].state_content
                )

                specs.append(
                    TargetSpec(
                        saas_file=saas_file,
                        resource_template=rt,
                        target=target,
                        # process_template options
                        image_auth=image_auth,
                        hash_length=hash_length,
                        github=github,
                        target_config_hash=digest,
                        secret_reader=self.secret_reader,
                    )
                )

        return specs

    def populate_desired_state_saas_file(
        self, spec: TargetSpec, ri: ResourceInventory
    ) -> Promotion | None:
        if spec.delete:
            # to delete resources, we avoid adding them to the desired state
            return None

        html_url = spec.html_url
        try:
            resources, promotion = self._process_template(spec)
        except Exception as e:
            # error log message send in _process_template. We cannot just
            # register an error without logging as inventory errors don't have details.
            logging.error(f"Error in populate_desired_state_saas_file: {e}")
            ri.register_error()
            return None

        # filter resources
        rs: Resources = []
        for r in resources:
            if isinstance(r, dict) and "kind" in r and "apiVersion" in r:
                kind: str = r["kind"]
                kind_and_group = fully_qualified_kind(kind, r["apiVersion"])
                if (
                    kind in spec.managed_resource_types
                    or kind_and_group in spec.managed_resource_types
                ):
                    rs.append(r)
                else:
                    logging.info(
                        f"Skipping resource of kind {kind} on "
                        f"{spec.cluster}/{spec.namespace}"
                    )
            else:
                logging.info(
                    "Skipping non-dictionary resource on "
                    f"{spec.cluster}/{spec.namespace}"
                )
        # additional processing of resources
        resources = rs
        self._additional_resource_process(resources, html_url)
        # check images
        image_error = self._check_images(
            spec=spec,
            resources=resources,
        )
        if image_error:
            ri.register_error()
            return None
        # add desired resources
        for resource in resources:
            oc_resource = OR(
                resource,
                self.integration,
                self.integration_version,
                caller_name=spec.saas_file_name,
                error_details=html_url,
            )
            try:
                ri.add_desired_resource(
                    spec.cluster,
                    spec.namespace,
                    oc_resource,
                    privileged=spec.privileged,
                )
            except ResourceKeyExistsError:
                ri.register_error()
                msg = (
                    f"[{spec.cluster}/{spec.namespace}] desired item "
                    + f"already exists: {resource['kind']}/{resource['metadata']['name']}. "
                    + f"saas file name: {spec.saas_file_name}, "
                    + "resource template name: "
                    + f"{spec.resource_template_name}."
                )
                logging.error(msg)
            except ResourceNotManagedError:
                msg = (
                    f"[{spec.cluster}/{spec.namespace}] desired item "
                    + f"not managed, skipping: {oc_resource.kind}/{oc_resource.name}. "
                    + f"saas file name: {spec.saas_file_name}, "
                    + "resource template name: "
                    + f"{spec.resource_template_name}."
                )
                logging.info(msg)

        return promotion

    def get_diff(
        self, trigger_type: TriggerTypes, dry_run: bool
    ) -> tuple[
        list[TriggerSpecConfig]
        | list[TriggerSpecMovingCommit]
        | list[TriggerSpecUpstreamJob]
        | list[TriggerSpecContainerImage],
        bool,
    ]:
        if trigger_type == TriggerTypes.MOVING_COMMITS:
            # TODO: replace error with actual error handling when needed
            error = False
            return self.get_moving_commits_diff(dry_run), error
        if trigger_type == TriggerTypes.UPSTREAM_JOBS:
            # error is being returned from the called function
            return self.get_upstream_jobs_diff(dry_run)
        if trigger_type == TriggerTypes.CONFIGS:
            # TODO: replace error with actual error handling when needed
            error = False
            return self.get_configs_diff(), error
        if trigger_type == TriggerTypes.CONTAINER_IMAGES:
            # TODO: replace error with actual error handling when needed
            error = False
            return self.get_container_images_diff(dry_run), error
        raise NotImplementedError(
            f"saasherder get_diff for trigger type: {trigger_type}"
        )

    def update_state(self, trigger_spec: TriggerSpecUnion) -> None:
        if not self.state:
            raise Exception("state is not initialized")

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
        self, saas_file: SaasFile, dry_run: bool
    ) -> list[TriggerSpecMovingCommit]:
        github = self._initiate_github(saas_file)
        trigger_specs: list[TriggerSpecMovingCommit] = []
        for rt in saas_file.resource_templates:
            for target in rt.targets:
                try:
                    # don't trigger if there is a linked upstream job or container image
                    if target.upstream or target.image:
                        continue

                    desired_commit_sha = self._get_commit_sha(
                        url=rt.url, ref=target.ref, github=github
                    )
                    # don't trigger on refs which are commit shas
                    if target.ref == desired_commit_sha:
                        continue

                    trigger_spec = TriggerSpecMovingCommit(
                        saas_file_name=saas_file.name,
                        env_name=target.namespace.environment.name,
                        timeout=saas_file.timeout,
                        pipelines_provider=saas_file.pipelines_provider,
                        resource_template_name=rt.name,
                        cluster_name=target.namespace.cluster.name,
                        namespace_name=target.namespace.name,
                        ref=target.ref,
                        state_content=desired_commit_sha,
                    )
                    if self.include_trigger_trace:
                        trigger_spec.reason = f"{rt.url}/commit/{desired_commit_sha}"

                    if not self.state:
                        raise Exception("state is not initialized")
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
                        f"Skipping target {saas_file.name}:{rt.name}"
                        f" - repo: {rt.url} - ref: {target.ref}"
                    )
                    self._register_error()
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
        if not self.jenkins_map:
            raise Exception("jenkins_map is not initialized")

        for instance_name, jenkins in self.jenkins_map.items():
            try:
                current_state[instance_name] = jenkins.get_jobs_state()
            except (rqexc.ConnectionError, rqexc.HTTPError):
                error = True
                logging.error(f"instance unreachable: {instance_name}")
                current_state[instance_name] = {}

        return current_state, error

    def get_upstream_jobs_diff_saas_file(
        self, saas_file: SaasFile, dry_run: bool, current_state: dict[str, Any]
    ) -> list[TriggerSpecUpstreamJob]:
        trigger_specs = []
        for rt in saas_file.resource_templates:
            for target in rt.targets:
                if not target.upstream:
                    continue
                job_name = target.upstream.name
                job_history = current_state[target.upstream.instance.name].get(
                    job_name, []
                )
                if not job_history:
                    continue
                last_build_result = job_history[0]

                trigger_spec = TriggerSpecUpstreamJob(
                    saas_file_name=saas_file.name,
                    env_name=target.namespace.environment.name,
                    timeout=saas_file.timeout,
                    pipelines_provider=saas_file.pipelines_provider,
                    resource_template_name=rt.name,
                    cluster_name=target.namespace.cluster.name,
                    namespace_name=target.namespace.name,
                    instance_name=target.upstream.instance.name,
                    job_name=job_name,
                    state_content=last_build_result,
                )
                last_build_result_number = last_build_result["number"]
                if self.include_trigger_trace:
                    trigger_spec.reason = f"{target.upstream.instance.server_url}/job/{job_name}/{last_build_result_number}"
                    last_build_result_commit_sha = last_build_result.get("commit_sha")
                    if last_build_result_commit_sha:
                        trigger_spec.reason = (
                            f"{rt.url}/commit/{last_build_result_commit_sha} via "
                            + trigger_spec.reason
                        )
                if not self.state:
                    raise Exception("state is not initialized")
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
        self, saas_file: SaasFile, dry_run: bool
    ) -> list[TriggerSpecContainerImage]:
        """
        Get a list of trigger specs based on the diff between the
        desired state (git commit) and the current state for a single saas file.
        """
        github = self._initiate_github(saas_file)
        trigger_specs: list[TriggerSpecContainerImage] = []
        for rt in saas_file.resource_templates:
            for target in rt.targets:
                try:
                    if not target.image:
                        continue
                    commit_sha = self._get_commit_sha(
                        url=rt.url,
                        ref=target.ref,
                        github=github,
                    )
                    desired_image_tag = commit_sha[: rt.hash_length or self.hash_length]
                    # don't trigger if image doesn't exist
                    image_registry = f"{target.image.org.instance.url}/{target.image.org.name}/{target.image.name}"
                    image_uri = f"{image_registry}:{desired_image_tag}"
                    image_auth = self._initiate_image_auth(saas_file)
                    error_prefix = f"[{saas_file.name}/{rt.name}] {target.ref}:"
                    image = self._get_image(
                        image_uri, saas_file.image_patterns, image_auth, error_prefix
                    )
                    if not image:
                        continue

                    trigger_spec = TriggerSpecContainerImage(
                        saas_file_name=saas_file.name,
                        env_name=target.namespace.environment.name,
                        timeout=saas_file.timeout,
                        pipelines_provider=saas_file.pipelines_provider,
                        resource_template_name=rt.name,
                        cluster_name=target.namespace.cluster.name,
                        namespace_name=target.namespace.name,
                        image=image_registry,
                        state_content=desired_image_tag,
                    )
                    if self.include_trigger_trace:
                        trigger_spec.reason = (
                            f"{rt.url}/commit/{commit_sha} build {image_uri}"
                        )
                    if not self.state:
                        raise Exception("state is not initialized")
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
                        f"Skipping target {saas_file.name}:{rt.name}"
                        f" - repo: {rt.url} - ref: {target.ref}"
                    )

        return trigger_specs

    def get_configs_diff(self) -> list[TriggerSpecConfig]:
        results = threaded.run(
            self.get_configs_diff_saas_file, self.saas_files, self.thread_pool_size
        )
        return list(itertools.chain.from_iterable(results))

    @staticmethod
    def remove_none_values(d: dict[Any, Any] | None) -> dict[Any, Any]:
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
        self, saas_file: SaasFile
    ) -> list[TriggerSpecConfig]:
        all_trigger_specs = self.get_saas_targets_config_trigger_specs(saas_file)
        trigger_specs = []

        if not self.state:
            raise Exception("state is not initialized")

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
                trigger_spec.reason = f"{self.repo_url}/commit/{RunningState().commit}"
                # For now we count every saas config change as an auto-promotion
                # if the auto promotion field is enabled in the saas target.
                # Ideally, we check if there was an actual ref change in order
                # to reduce false-positives.
                promotion = trigger_spec.state_content.get("promotion")
                if promotion and promotion.get("auto", False):
                    trigger_spec.reason += " [auto-promotion]"
            trigger_specs.append(trigger_spec)
        return trigger_specs

    @staticmethod
    def get_target_config_hash(target_config: Any) -> str:
        m = hashlib.sha256()
        m.update(json.dumps(target_config, sort_keys=True).encode("utf-8"))
        digest = m.hexdigest()[:16]
        return digest

    def get_saas_targets_config_trigger_specs(
        self, saas_file: SaasFile
    ) -> dict[str, TriggerSpecConfig]:
        configs = {}
        for rt in saas_file.resource_templates:
            for target in rt.targets:
                # ChainMap will store modifications avoiding a deep copy
                desired_target_config = ChainMap(target.dict(by_alias=True))
                # This will add the namespace key/value to the chainMap, but
                # the target will remain with the original value
                # When the namespace key is looked up, the chainmap will
                # return the modified attribute (set in the first mapping)
                desired_target_config["namespace"] = self.sanitize_namespace(
                    target.namespace
                )
                # add parent parameters to target config
                # before the GQL classes are introduced, the parameters attribute
                # was a json string. Keep it that way to be backwards compatible.
                desired_target_config["saas_file_parameters"] = (
                    json.dumps(saas_file.parameters, separators=(",", ":"))
                    if saas_file.parameters is not None
                    else None
                )

                # before the GQL classes are introduced, the parameters attribute
                # was a json string. Keep it that way to be backwards compatible.
                desired_target_config["parameters"] = (
                    json.dumps(target.parameters, separators=(",", ":"))
                    if target.parameters is not None
                    else None
                )

                # add managed resource types to target config
                desired_target_config["saas_file_managed_resource_types"] = (
                    saas_file.managed_resource_types
                )
                desired_target_config["url"] = rt.url
                desired_target_config["path"] = rt.path
                # before the GQL classes are introduced, the parameters attribute
                # was a json string. Keep it that way to be backwards compatible.
                desired_target_config["rt_parameters"] = (
                    json.dumps(rt.parameters, separators=(",", ":"))
                    if rt.parameters is not None
                    else None
                )

                # include secret parameters from resource template and saas file
                if rt.secret_parameters:
                    desired_target_config["rt_secretparameters"] = [
                        p.dict() for p in rt.secret_parameters
                    ]
                if saas_file.secret_parameters:
                    desired_target_config["saas_file_secretparameters"] = [
                        p.dict() for p in saas_file.secret_parameters
                    ]

                # Convert to dict, ChainMap is not JSON serializable
                # desired_target_config needs to be serialized to generate
                # its config hash and to be stored in S3
                serializable_target_config = dict(desired_target_config)
                trigger_spec = TriggerSpecConfig(
                    saas_file_name=saas_file.name,
                    env_name=target.namespace.environment.name,
                    timeout=saas_file.timeout,
                    pipelines_provider=saas_file.pipelines_provider,
                    resource_template_name=rt.name,
                    cluster_name=target.namespace.cluster.name,
                    namespace_name=target.namespace.name,
                    target_name=target.name,
                    state_content=serializable_target_config,
                )
                configs[trigger_spec.state_key] = trigger_spec

        return configs

    @staticmethod
    def sanitize_namespace(
        namespace: SaasResourceTemplateTargetNamespace,
    ) -> dict[str, dict[str, str]]:
        """Only keep fields that should trigger a new job."""
        return namespace.dict(
            by_alias=True,
            include={
                "name": True,
                "cluster": {"name": True, "server_url": True},
                "app": {"name": True},
            },
            # TODO: add environment.parameters to the include list!?!?
        )

    def _validate_promotion(self, promotion: Promotion) -> bool:
        # Placing this check here to make mypy happy
        if not (self.state and self._promotion_state):
            raise Exception("state is not initialized")

        if not promotion.subscribe:
            return True

        if promotion.commit_sha in self.blocked_versions.get(promotion.url, set()):
            logging.error(f"Commit {promotion.commit_sha} is blocked!")
            return False

        # hotfix must run before further gates are evaluated to override them
        if promotion.commit_sha in self.hotfix_versions.get(promotion.url, set()):
            return True

        now = datetime.now(UTC)
        passed_soak_days = timedelta(days=0)

        for channel in promotion.subscribe:
            config_hashes: set[str] = set()
            for target_uid in channel.publisher_uids:
                deployment = self._promotion_state.get_promotion_data(
                    sha=promotion.commit_sha,
                    channel=channel.name,
                    target_uid=target_uid,
                    pre_check_sha_exists=False,
                )
                if not (
                    deployment and (deployment.success or deployment.has_succeeded_once)
                ):
                    logging.error(
                        f"Commit {promotion.commit_sha} was not "
                        + f"published with success to channel {channel.name}"
                    )
                    return False
                if check_in := deployment.check_in:
                    passed_soak_days += now - datetime.fromisoformat(check_in)
                if deployment.target_config_hash:
                    config_hashes.add(deployment.target_config_hash)

            # This code supports current saas targets that does
            # not have promotion_data yet
            if not config_hashes or not promotion.promotion_data:
                logging.info(
                    "Promotion data is missing; rely on the success " "state only"
                )
                continue

            # Validate the promotion_data section.
            # Just validate parent_saas_config hash
            # promotion_data type by now.
            parent_saas_config = None
            for pd in promotion.promotion_data:
                if pd.channel == channel.name:
                    for data in pd.data or []:
                        if isinstance(data, SaasParentSaasPromotion):
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
                continue

            # Validate that the state config_hash set by the parent
            # matches with the hash set in promotion_data
            if parent_saas_config.target_config_hash in config_hashes:
                continue

            logging.error(
                "Parent saas target has run with a newer "
                "configuration and the same commit (ref). "
                "Check if other MR exists for this target, "
                f"or update {parent_saas_config.target_config_hash} "
                f"to any in {config_hashes} for channel {channel.name}"
            )
            return False

        if passed_soak_days < timedelta(days=promotion.soak_days):
            logging.error(
                f"SoakDays in publishers did not pass. So far accumulated soakDays is {passed_soak_days},"
                f"but we have a soakDays setting of {promotion.soak_days}. We cannot proceed with this promotion."
            )
            return False
        return True

    def validate_promotions(self) -> bool:
        """
        If there were promotion sections in the participating saas files
        validate that the conditions are met."""
        return all(
            self._validate_promotion(promotion)
            for promotion in self.promotions
            if promotion is not None
        )

    def publish_promotions(
        self,
        success: bool,
        all_saas_files: Iterable[SaasFile],
    ) -> None:
        """
        If there were promotion sections in the participating saas file
        publish the results for future promotion validations."""
        (
            subscribe_saas_file_path_map,
            subscribe_target_path_map,
        ) = self._get_subscribe_path_map(all_saas_files, auto_only=True)

        if not (self.state and self._promotion_state):
            raise Exception("state is not initialized")

        now = datetime.now(UTC)
        for promotion in self.promotions:
            if promotion is None:
                continue

            if promotion.publish:
                all_subscribed_saas_file_paths = set()
                all_subscribed_target_paths = set()
                for channel in promotion.publish:
                    # make sure we keep some attributes on re-deployments of same ref
                    has_succeeded_once = success
                    current_state = self._promotion_state.get_promotion_data(
                        sha=promotion.commit_sha,
                        channel=channel,
                        target_uid=promotion.saas_target_uid,
                        use_cache=True,
                    )
                    if current_state and current_state.has_succeeded_once:
                        has_succeeded_once = True

                    # publish to state to pass promotion gate
                    self._promotion_state.publish_promotion_data(
                        sha=promotion.commit_sha,
                        channel=channel,
                        target_uid=promotion.saas_target_uid,
                        data=PromotionData(
                            saas_file=promotion.saas_file,
                            success=success,
                            target_config_hash=promotion.target_config_hash,
                            has_succeeded_once=has_succeeded_once,
                            # TODO: do not override - check if timestamp already exists
                            check_in=str(now),
                        ),
                    )
                    logging.info(
                        f"Commit {promotion.commit_sha} was published "
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

                promotion.saas_file_paths = list(all_subscribed_saas_file_paths)
                promotion.target_paths = list(all_subscribed_target_paths)

    @staticmethod
    def _get_subscribe_path_map(
        saas_files: Iterable[SaasFile], auto_only: bool = False
    ) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        """
        Returns dicts with subscribe channels as keys and a
        list of paths of saas files or targets containing these channels.
        """
        subscribe_saas_file_path_map: dict[str, set[str]] = {}
        subscribe_target_path_map: dict[str, set[str]] = {}
        for saas_file in saas_files:
            saas_file_path = "data" + saas_file.path
            for rt in saas_file.resource_templates:
                for target in rt.targets:
                    if not target.promotion:
                        continue
                    if auto_only and not target.promotion.auto:
                        continue
                    if not target.promotion.subscribe:
                        continue
                    # targets with a path are referenced and not inlined
                    if target.path:
                        target.path = "data" + target.path
                    for channel in target.promotion.subscribe:
                        subscribe_saas_file_path_map.setdefault(channel, set())
                        subscribe_saas_file_path_map[channel].add(saas_file_path)
                        if target.path:
                            subscribe_target_path_map.setdefault(channel, set())
                            subscribe_target_path_map[channel].add(target.path)

        return subscribe_saas_file_path_map, subscribe_target_path_map

    @staticmethod
    def resolve_templated_parameters(saas_files: Iterable[SaasFile]) -> None:
        """Resolve templated target parameters in saas files."""
        from reconcile.utils.jinja2.utils import (  # noqa: PLC0415 - # avoid circular import
            compile_jinja2_template,
        )

        for saas_file in saas_files:
            for rt in saas_file.resource_templates:
                for target in rt.targets:
                    template_vars = {
                        "resource": {"namespace": target.namespace.dict(by_alias=True)}
                    }
                    if target.parameters:
                        for param in target.parameters:
                            if not isinstance(target.parameters[param], str):
                                continue
                            target.parameters[param] = compile_jinja2_template(
                                target.parameters[param], extra_curly=True
                            ).render(template_vars)
                    if target.secret_parameters:
                        for secret_param in target.secret_parameters:
                            secret_param.secret.field = compile_jinja2_template(
                                secret_param.secret.field, extra_curly=True
                            ).render(template_vars)
                            secret_param.secret.path = compile_jinja2_template(
                                secret_param.secret.path, extra_curly=True
                            ).render(template_vars)

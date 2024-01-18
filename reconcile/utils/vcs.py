from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from enum import Enum
from typing import Optional

from gitlab.v4.objects import ProjectMergeRequest

from reconcile.typed_queries.github_orgs import GithubOrgV1
from reconcile.typed_queries.gitlab_instances import GitlabInstanceV1
from reconcile.utils.github_api import GithubRepositoryApi
from reconcile.utils.gitlab_api import (
    GitLabApi,
    MRState,
)
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.secret_reader import (
    HasSecret,
    SecretReaderBase,
)


class MRCheckStatus(Enum):
    NONE = 0
    SUCCESS = 1
    FAILED = 2
    RUNNING = 3


class VCS:
    """
    Abstraction layer for aggregating different Version Control Systems.
    The idea is to abstract away the differences between
    Gitlab and Github for fetching publisher state.
    Further this acts as a wrapper around our gitlab client
    for interactions with the app-interface repo. That makes
    setting up tests easier.
    """

    def __init__(
        self,
        secret_reader: SecretReaderBase,
        github_orgs: Iterable[GithubOrgV1],
        gitlab_instances: Iterable[GitlabInstanceV1],
        app_interface_repo_url: str,
        dry_run: bool,
        allow_deleting_mrs: bool,
        allow_opening_mrs: bool,
        gitlab_instance: Optional[GitLabApi] = None,
        default_gh_token: Optional[str] = None,
        app_interface_api: Optional[GitLabApi] = None,
    ):
        self._dry_run = dry_run
        self._allow_deleting_mrs = allow_deleting_mrs
        self._allow_opening_mrs = allow_opening_mrs
        self._secret_reader = secret_reader
        self._gh_per_repo_url: dict[str, GithubRepositoryApi] = {}
        self._default_gh_token = (
            default_gh_token
            if default_gh_token
            else self._get_default_gh_token(github_orgs=github_orgs)
        )
        self._gitlab_instance = (
            gitlab_instance
            if gitlab_instance
            else self._gitlab_api(gitlab_instances=gitlab_instances)
        )
        self._app_interface_api = (
            app_interface_api
            if app_interface_api
            else self._init_app_interface_api(
                gitlab_instances=gitlab_instances,
                app_interface_repo_url=app_interface_repo_url,
            )
        )
        self._is_commit_sha_regex = re.compile(r"^[0-9a-f]{40}$")

    def _get_default_gh_token(
        self,
        github_orgs: Iterable[GithubOrgV1],
    ) -> str:
        defaults: list[str] = []
        for org in github_orgs:
            if not org.default:
                continue
            token = self._secret_reader.read_secret(org.token)
            defaults.append(token)
        if len(defaults) == 0:
            raise RuntimeError("No default GitHub token found.")
        if len(defaults) > 1:
            raise RuntimeError("More than 1 default token for GitHub found.")
        return defaults[0]

    def _init_github(
        self, repo_url: str, auth_code: Optional[HasSecret]
    ) -> GithubRepositoryApi:
        if repo_url not in self._gh_per_repo_url:
            if auth_code:
                token = self._secret_reader.read_secret(auth_code)
            else:
                token = self._default_gh_token
            self._gh_per_repo_url[repo_url] = self._github_api(
                token=token, repo_url=repo_url
            )
        return self._gh_per_repo_url[repo_url]

    def _github_api(self, token: str, repo_url: str) -> GithubRepositoryApi:
        return GithubRepositoryApi(repo_url=repo_url, token=token)

    def _gitlab_api(
        self,
        gitlab_instances: Iterable[GitlabInstanceV1],
    ) -> GitLabApi:
        return GitLabApi(
            list(gitlab_instances)[0].dict(by_alias=True),
            secret_reader=self._secret_reader,
        )

    def _init_app_interface_api(
        self,
        gitlab_instances: Iterable[GitlabInstanceV1],
        app_interface_repo_url: str,
    ) -> GitLabApi:
        return GitLabApi(
            list(gitlab_instances)[0].dict(by_alias=True),
            secret_reader=self._secret_reader,
            project_url=app_interface_repo_url,
        )

    def get_gitlab_mr_check_status(self, mr: ProjectMergeRequest) -> MRCheckStatus:
        pipelines = self._gitlab_instance.get_merge_request_pipelines(mr)
        if not pipelines:
            return MRCheckStatus.NONE
        # available status codes https://docs.gitlab.com/ee/api/pipelines.html
        last_pipeline_result = pipelines[0]["status"]
        match last_pipeline_result:
            case "success":
                return MRCheckStatus.SUCCESS
            case "running":
                return MRCheckStatus.RUNNING
            case "failed":
                return MRCheckStatus.FAILED
            case _:
                # Lets assume all other states as non-present
                return MRCheckStatus.NONE

    def get_commit_sha(
        self, repo_url: str, ref: str, auth_code: Optional[HasSecret]
    ) -> str:
        if bool(self._is_commit_sha_regex.search(ref)):
            return ref
        if "github.com" in repo_url:
            github = self._init_github(repo_url=repo_url, auth_code=auth_code)
            return github.get_commit_sha(ref=ref)
        # assume gitlab by default
        return self._gitlab_instance.get_commit_sha(ref=ref, repo_url=repo_url)

    def close_app_interface_mr(self, mr: ProjectMergeRequest, comment: str) -> None:
        if not self._allow_deleting_mrs:
            logging.info("Deleting MRs is disabled. Skipping.")
        if not self._dry_run and self._allow_deleting_mrs:
            self._app_interface_api.add_comment_to_merge_request(
                merge_request=mr,
                body=comment,
            )
            self._app_interface_api.close(mr)

    def get_file_content_from_app_interface_master(self, file_path: str) -> str:
        return self._app_interface_api.project.files.get(
            file_path=f"data{file_path}", ref="master"
        ).decode()

    def get_open_app_interface_merge_requests(self) -> list[ProjectMergeRequest]:
        return self._app_interface_api.get_merge_requests(state=MRState.OPENED)

    def open_app_interface_merge_request(self, mr: MergeRequestBase) -> None:
        if not self._allow_opening_mrs:
            logging.info("Creating MRs is disabled. Skipping.")
        if not self._dry_run and self._allow_opening_mrs:
            mr.submit_to_gitlab(gitlab_cli=self._app_interface_api)

    def cleanup(self) -> None:
        for gh_client in self._gh_per_repo_url.values():
            gh_client.cleanup()
        self._gitlab_instance.cleanup()
        self._app_interface_api.cleanup()

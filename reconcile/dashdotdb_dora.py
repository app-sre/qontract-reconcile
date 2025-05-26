import functools
import os
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from typing import (
    Any,
    Self,
)

import requests
import yaml
from github import GithubException
from psycopg2 import (
    connect,
    sql,
)
from sretoolbox.utils import threaded

from reconcile import queries
from reconcile.dashdotdb_base import (
    LOG,
    DashdotdbBase,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.saas_files import get_saas_files
from reconcile.utils.github_api import GithubRepositoryApi
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.vcs import VCS

QONTRACT_INTEGRATION = "dashdotdb-dora"


@dataclass
class DeploymentDBSecret:
    path: str
    field: str
    q_format: str | None
    version: int | None


@dataclass(eq=True, frozen=True)
class AppEnv:
    app_name: str
    env_name: str


@dataclass
class Deployment:
    trigger_reason: str
    deployment_time: datetime


@dataclass(eq=True, frozen=True)
class SaasTarget:
    app_name: str
    env_name: str
    path: str
    resource_template: str
    namespace: str
    pipeline: str

    @property
    def app_env(self) -> AppEnv:
        return AppEnv(self.app_name, self.env_name)


@dataclass(eq=True, frozen=True)
class RepoChanges:
    repo_url: str | None
    ref_from: str | None
    ref_to: str | None


@dataclass(eq=True, frozen=True)
class SummaryKey:
    rt_name: str
    target_ns: str


@dataclass(eq=True, frozen=True)
class SummaryEntry:
    repo_url: str
    target_ref: str


class DeploymentDB:
    def __init__(
        self,
        host: str,
        port: str,
        name: str,
        user: str,
        password: str,
    ):
        self.conn = connect(
            host=host, port=port, dbname=name, user=user, password=password
        )
        LOG.info("Connected to DeploymentDB")

    def deployments(
        self,
        trigger_reason_pattern: str,
        app_env_since_list: Iterable[tuple[AppEnv, datetime]],
    ) -> list[tuple[AppEnv, Deployment]]:
        deployments: list[tuple[AppEnv, Deployment]] = []
        with self.conn.cursor() as cur:
            subq = [
                sql.SQL(
                    "(app_name = {} AND env_name = {} AND deployment_time > {})"
                ).format(
                    sql.Literal(app_env.app_name),
                    sql.Literal(app_env.env_name),
                    sql.Literal(since),
                )
                for (app_env, since) in app_env_since_list
            ]

            query = sql.SQL(
                """
                    SELECT app_name, env_name, trigger_reason, deployment_time
                    FROM deployments
                    WHERE
                        succeeded = True
                        AND trigger_reason LIKE {}
                        AND ({})
                    ORDER BY deployment_time ASC;
                """
            ).format(sql.Literal(trigger_reason_pattern), sql.SQL(" OR ").join(subq))

            cur.execute(query)

            deployments.extend(
                (
                    AppEnv(record[0], record[1]),
                    Deployment(record[2], record[3]),
                )
                for record in cur
            )

        if not deployments:
            LOG.info("No deployments found")

        return deployments


@dataclass
class Commit:
    repo: str
    sha: str
    date: datetime

    def lttc(self, finish_timestamp: datetime) -> int:
        commit_date_tzaware = self.date
        finish_timestamp_tzaware = finish_timestamp

        if commit_date_tzaware.tzinfo is None:
            commit_date_tzaware = commit_date_tzaware.replace(tzinfo=UTC)

        if finish_timestamp_tzaware.tzinfo is None:
            finish_timestamp_tzaware = finish_timestamp_tzaware.replace(tzinfo=UTC)

        return int((finish_timestamp_tzaware - commit_date_tzaware).total_seconds())


class DashdotdbDORA(DashdotdbBase):
    """DashdotDB DORA collector.

    Definitions:

    * `app_name` is the value of `.name` in the saas-file.
    * `env_name` is the value of a given
      `.resourceTemplates.targets.namespace.$ref -> ns file -> environment file
      -> .name`.
    * `trigger_reason` is one of the fields registered in DeploymentDB that
      identifies the promotion event. It looks like:
      https://gitlab.../service/app-interface/commit/<sha>.
    * `promotion_sha` is the sha contained in the trigger_reason.

    This collector performs the followig tasks:

    * Get a list of saasfiles that contain the dora field in its labels. The
      value is a comma-separated list of target env_names. Relevant MR.
    * Query DashdotDB (over API) to obtain latest registered entry for that
      app_name and env_name pair.
    * Query DeploymentDB (over SQL) to obtain the deployments associated to each
      app_name and env_name pair from the latest registered entry in DashdotDB
      or from the last 90 days if there are none.
    * From the DeploymentDB entry trigger_reason, extract the changes: url of
      the repository, previous commit, promotion commit. This is done by
      fetching the saas-file from GitLab's API at at the promotion_sha commit,
      and comparing it with the promotion_sha^ commit (note the ^).
    * Using GitHub or GitLab's API, obtain the list of commits between
      promotion_sha^ and promotion_sha.
    * Build the payload for DashdotDB and submit it as a POST.

    Caveats:

    * This class has been designed to run as a cronjob, so the cleanup code
      should be reviewed if this changes its execution pattern to a service.
    """

    def __init__(
        self, dry_run: bool, gitlab_project_id: str, thread_pool_size: int = 5
    ) -> None:
        self.gitlab_project_id = gitlab_project_id
        self.settings = queries.get_app_interface_settings()
        vault_settings = get_app_interface_vault_settings()
        secret_reader = create_secret_reader(use_vault=vault_settings.vault)

        # init dashdotdb
        super().__init__(
            dry_run=dry_run,
            thread_pool_size=thread_pool_size,
            marker="DDDB_DORA:",
            scope="dora",
            secret_reader=secret_reader,
        )

        # init dep db
        depdb_secret = secret_reader.read_all_secret(
            DeploymentDBSecret(
                field="",
                path=os.environ["DEPLOYMENT_DB_SECRET"],
                q_format=None,
                version=None,
            )
        )

        self.dep_db = DeploymentDB(
            depdb_secret["db.host"],
            depdb_secret["db.port"],
            depdb_secret["db.name"],
            depdb_secret["db.user"],
            depdb_secret["db.password"],
        )

        # init GitLab API
        gl_instance = queries.get_gitlab_instance()
        self.gl = GitLabApi(
            gl_instance, project_id=self.gitlab_project_id, settings=self.settings
        )
        self.gl_app_interface_get_file = functools.cache(self.gl.get_file)

        # init GitHub API
        gh_instance = queries.get_github_instance()
        self.gh_token = secret_reader.read(gh_instance["token"])
        self._gh_apis: dict[str, GithubRepositoryApi] = {}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.gl.cleanup()
        for gh in self._gh_apis.values():
            gh.cleanup()

    def gh_api(self, repo: str) -> GithubRepositoryApi:
        if repo not in self._gh_apis:
            self._gh_apis[repo] = GithubRepositoryApi(repo, self.gh_token)
        return self._gh_apis[repo]

    def run(self) -> None:
        saastargets = self.get_saastargets()

        # Build unique combination of app_name and env_names
        # so we can fetch the deployments associated with each one.
        # We are doing this so we don't fetch the deployments
        # from the DB for a unique (app_name, env_name) multiple times.
        app_envs = {s.app_env for s in saastargets}

        since_default = datetime.now() - timedelta(days=90)
        app_env_since_list: list[tuple[AppEnv, datetime]] = threaded.run(
            func=functools.partial(self.get_latest_with_default, since_default),
            iterable=app_envs,
            thread_pool_size=self.thread_pool_size,
        )

        trigger_reason_pattern = f"{self.gl.server}/service/app-interface/commit/%"
        app_env_deployments_list = self.dep_db.deployments(
            trigger_reason_pattern, app_env_since_list
        )

        self.app_env_deployments = defaultdict(list)
        for app_env, deployment in app_env_deployments_list:
            self.app_env_deployments[app_env].append(deployment)

        repo_changes_iterable = [
            (saastarget, deployment)
            for saastarget in saastargets
            for deployment in self.app_env_deployments[saastarget.app_env]
        ]

        saastarget_dep_repo_changes: list[
            tuple[SaasTarget, Deployment, RepoChanges]
        ] = threaded.run(
            func=self.get_repo_changes,
            iterable=repo_changes_iterable,
            thread_pool_size=self.thread_pool_size,
        )

        # filter out invalid entries:
        # - one of the fields (repo, ref_from, ref_to) is null
        # - ref_from is equal to ref_to. This can happen when there was a happen
        #   to the saasfile that didn't change the ref, only a parameter for
        #   example
        saastarget_dep_repo_changes = [
            (st, dep, rc)
            for (st, dep, rc) in saastarget_dep_repo_changes
            if rc.repo_url and rc.ref_from and rc.ref_to and rc.ref_from != rc.ref_to
        ]

        unique_repo_changes = {rc for (_, _, rc) in saastarget_dep_repo_changes}

        rc_commits_list = threaded.run(
            func=self.compare,
            iterable=unique_repo_changes,
            thread_pool_size=self.thread_pool_size,
        )

        rc_commits = dict(rc_commits_list)

        # we want to sort by oldest first, so that if the process crashes
        # the call to latest_deployment from Dash.DB will return the appropriate
        # value so that it is possible to continue
        def sortkey(item: tuple[SaasTarget, Deployment, RepoChanges]) -> datetime:
            (_, dep, _) = item
            return dep.deployment_time

        deployments = [
            self.build_deployment_post(st, dep, rc_commits[rc])
            for st, dep, rc in sorted(saastarget_dep_repo_changes, key=sortkey)
        ]

        if deployments:
            self.post({"deployments": deployments})

    def get_saastargets(self) -> list[SaasTarget]:
        targets = []
        for saas_file in get_saas_files():
            if not saas_file.labels:
                continue

            if "dora" not in saas_file.labels:
                continue

            dora_target_env_names = saas_file.labels["dora"].split(",")

            # filter out empty fields, in case there are leading, trailing or doubled commas
            dora_target_env_names = [e for e in dora_target_env_names if e]

            for rt in saas_file.resource_templates:
                for target in rt.targets:
                    ns = target.namespace
                    target_env_name = ns.environment.name
                    if target_env_name not in dora_target_env_names:
                        continue

                    pipeline = f"{rt.name}-{ns.cluster.name}-{ns.name}"
                    saas_file_path = "data/" + saas_file.path.lstrip("/")
                    saastarget = SaasTarget(
                        app_name=saas_file.name,
                        env_name=target_env_name,
                        path=saas_file_path,
                        resource_template=rt.name,
                        namespace=ns.path,
                        pipeline=pipeline,
                    )

                    targets.append(saastarget)

                    LOG.info("marking SaaS file for processing: %s", saastarget)
        return targets

    def get_repo_changes(
        self, saastarget_deployment: tuple[SaasTarget, Deployment]
    ) -> tuple[SaasTarget, Deployment, RepoChanges]:
        saastarget, deployment = saastarget_deployment
        LOG.info("Fetching repo changes for %s - %s", saastarget, deployment)
        # sometimes the trigger_reason ends with '[auto-promotion]', so we keeep
        # only the first 40 chars.
        promotion_sha = deployment.trigger_reason.split("/")[-1][:40]

        repo_url, ref_from = self.get_repo_ref_for_sha(saastarget, promotion_sha + "^")
        _, ref_to = self.get_repo_ref_for_sha(saastarget, promotion_sha)

        return (saastarget, deployment, RepoChanges(repo_url, ref_from, ref_to))

    def get_repo_ref_for_sha(
        self, saastarget: SaasTarget, sha: str
    ) -> tuple[str | None, str | None]:
        try:
            saas_file_yaml = self.gl_app_interface_get_file(saastarget.path, ref=sha)
            if not saas_file_yaml:
                LOG.info(f"failed to fetch saas file {saastarget.path} at {sha}")
                return (None, None)
            saas_file = yaml.safe_load(saas_file_yaml.decode())
        except Exception as e:
            LOG.info(f"failed to decode saas file {saastarget.path} with error: {e}")
            return (None, None)

        for rt in saas_file["resourceTemplates"]:
            if saastarget.resource_template != rt["name"]:
                continue

            for target in rt["targets"]:
                if saastarget.namespace == target["namespace"]["$ref"]:
                    return (rt["url"], target["ref"])

        return (None, None)

    def compare(self, rc: RepoChanges) -> tuple[RepoChanges, list[Commit]]:
        if not rc.repo_url:
            return rc, []

        LOG.info("Fetching commits %s", rc)
        repo_info = VCS.parse_repo_url(rc.repo_url)
        match repo_info.platform:
            case "github":
                try:
                    commits = self._github_compare_commits(rc, repo_info.name)
                except GithubException as e:
                    if e.status == 404:
                        LOG.info(
                            f"Ignoring RepoChanges for {rc} because could not calculate them: {e.data['message']}"
                        )
                        return rc, []
            case "gitlab":
                commits = self._gitlab_compare_commits(rc, repo_info.name)
            case _:
                raise Exception(f"Unknown git hosting {rc.repo_url}")

        return rc, commits

    def get_latest_with_default(
        self, since_default: datetime, app_env: AppEnv
    ) -> tuple[AppEnv, datetime]:
        endpoint = f"{self.dashdotdb_url}/api/v1/dora/latest"
        response = self._do_get(
            endpoint,
            {
                "app_name": app_env.app_name,
                "env_name": app_env.env_name,
            },
        )

        if response.status_code == 404:
            return app_env, since_default

        return app_env, datetime.fromisoformat(response.json()["finish_timestamp"])

    def _gitlab_compare_commits(self, rc: RepoChanges, repo: str) -> list[Commit]:
        if not rc.repo_url or not rc.ref_from or not rc.ref_to:
            return []

        commits = self.gl.repository_compare(repo, rc.ref_from, rc.ref_to)

        return [
            Commit(
                rc.repo_url,
                commit["id"],
                datetime.fromisoformat(commit["committed_date"]),
            )
            for commit in commits
        ]

    def _github_compare_commits(self, rc: RepoChanges, repo: str) -> list[Commit]:
        if not rc.repo_url:
            return []

        return [
            Commit(rc.repo_url, commit.sha, commit.commit.committer.date)
            for commit in self.gh_api(repo).compare(rc.ref_from, rc.ref_to)
        ]

    def post(self, data: Mapping[str, Any]) -> None:
        endpoint = f"{self.dashdotdb_url}/api/v1/dora"
        response = self._do_post(endpoint, data)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as details:
            LOG.error(
                "%s error posting DORA - %s - %s",
                self.logmarker,
                details,
                response.text,
            )
        else:
            LOG.info(
                "Successfully posted to DashdotDB %s deployments.",
                len(data["deployments"]),
            )

    @staticmethod
    def build_deployment_post(
        saastarget: SaasTarget, deployment: Deployment, commits: list[Commit]
    ) -> dict[str, Any]:
        return {
            "app_name": saastarget.app_name,
            "env_name": saastarget.env_name,
            "pipeline": saastarget.pipeline,
            "trigger_reason": deployment.trigger_reason,
            "finish_timestamp": deployment.deployment_time.isoformat(),
            "commits": [
                {
                    "repo": c.repo,
                    "revision": c.sha,
                    "timestamp": c.date.isoformat(),
                    "lttc": c.lttc(deployment.deployment_time),
                }
                for c in commits
            ],
        }


def run(dry_run: bool, gitlab_project_id: str, thread_pool_size: int = 5) -> None:
    with DashdotdbDORA(
        dry_run=dry_run,
        gitlab_project_id=gitlab_project_id,
        thread_pool_size=thread_pool_size,
    ) as dashdotdb_dora:
        dashdotdb_dora.run()

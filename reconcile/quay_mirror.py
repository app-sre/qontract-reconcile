import logging
import os
import sys
import tempfile
import time
from collections import (
    defaultdict,
    namedtuple,
)
from collections.abc import Iterable
from typing import (
    Any,
    Self,
)

import requests
from requests import Response
from sretoolbox.container.image import (
    ImageComparisonError,
    ImageContainsError,
)
from sretoolbox.container.skopeo import SkopeoCmdError

from reconcile import queries
from reconcile.status import ExitCodes
from reconcile.utils import (
    gql,
    metrics,
    sharding,
)
from reconcile.utils.helpers import match_patterns
from reconcile.utils.instrumented_wrappers import InstrumentedImage as Image
from reconcile.utils.instrumented_wrappers import InstrumentedSkopeo as Skopeo
from reconcile.utils.secret_reader import SecretReader

_LOG = logging.getLogger(__name__)

QONTRACT_INTEGRATION = "quay-mirror"
CONTROL_FILE_NAME = "qontract-reconcile-quay-mirror.timestamp"
REQUEST_TIMEOUT = 60

OrgKey = namedtuple("OrgKey", ["instance", "org_name"])


class QuayMirror:
    QUAY_ORG_CATALOG_QUERY = """
    {
      quay_orgs: quay_orgs_v1 {
        name
        pushCredentials {
          path
          field
          version
          format
        }
        instance {
          name
          url
        }
      }
    }
    """

    response_cache: dict[tuple[str, str], Response] = {}

    def __init__(
        self,
        dry_run: bool = False,
        control_file_dir: str | None = None,
        compare_tags: bool | None = None,
        compare_tags_interval: int = 86400,
        repository_urls: Iterable[str] | None = None,
        exclude_repository_urls: Iterable[str] | None = None,
    ) -> None:
        self.dry_run = dry_run
        self.gqlapi = gql.get_api()
        settings = queries.get_app_interface_settings()
        self.secret_reader = SecretReader(settings=settings)
        self.skopeo_cli = Skopeo(dry_run)
        self.push_creds = self._get_push_creds()
        self.compare_tags = compare_tags
        self.compare_tags_interval = compare_tags_interval
        self.repository_urls = repository_urls
        self.exclude_repository_urls = exclude_repository_urls

        self.response_cache_hits = metrics.cache_hits.labels(
            integration=QONTRACT_INTEGRATION,
            shards=sharding.SHARDS,
            shard_id=sharding.SHARD_ID,
        )
        self.response_cache_misses = metrics.cache_misses.labels(
            integration=QONTRACT_INTEGRATION,
            shards=sharding.SHARDS,
            shard_id=sharding.SHARD_ID,
        )
        self.response_cache_size = metrics.cache_size.labels(
            integration=QONTRACT_INTEGRATION,
            shards=sharding.SHARDS,
            shard_id=sharding.SHARD_ID,
        )
        self.response_cache_size.set_function(lambda: len(self.response_cache))

        if control_file_dir:
            if not os.path.isdir(control_file_dir):
                raise FileNotFoundError(
                    f"'{control_file_dir}' does not exist or it is not a directory"
                )

            self.control_file_path = os.path.join(control_file_dir, CONTROL_FILE_NAME)
        else:
            self.control_file_path = os.path.join(
                tempfile.gettempdir(), CONTROL_FILE_NAME
            )

        self._has_enough_time_passed_since_last_compare_tags: bool | None = None
        self.session = requests.Session()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.session.close()

    def run(self) -> None:
        sync_tasks = self.process_sync_tasks()
        for org, data in sync_tasks.items():
            for item in data:
                try:
                    self.skopeo_cli.copy(
                        src_image=item["mirror_url"],
                        src_creds=item["mirror_creds"],
                        dst_image=item["image_url"],
                        dest_creds=self.push_creds[org],
                    )
                except SkopeoCmdError as details:
                    _LOG.error("skopeo command error message: '%s'", details)

        if self.is_compare_tags and not self.dry_run:
            self.record_timestamp(self.control_file_path)

    @classmethod
    def process_repos_query(
        cls,
        repository_urls: Iterable[str] | None = None,
        exclude_repository_urls: Iterable[str] | None = None,
        session: requests.Session | None = None,
        timeout: int = REQUEST_TIMEOUT,
    ) -> defaultdict[OrgKey, list[dict[str, Any]]]:
        apps = queries.get_quay_repos()

        if repository_urls:
            repository_urls = set(repository_urls)

        if exclude_repository_urls:
            exclude_repository_urls = set(exclude_repository_urls)

        summary = defaultdict(list)

        for app in apps:
            quay_repos = app.get("quayRepos")

            if quay_repos is None:
                continue

            for quay_repo in quay_repos:
                org = quay_repo["org"]["name"]
                instance = quay_repo["org"]["instance"]["name"]
                server_url = quay_repo["org"]["instance"]["url"]

                for item in quay_repo["items"]:
                    if item["mirror"] is None:
                        continue

                    mirror_url = item["mirror"]["url"]

                    if repository_urls and mirror_url not in repository_urls:
                        continue

                    if (
                        exclude_repository_urls
                        and mirror_url in exclude_repository_urls
                    ):
                        continue

                    mirror_image = Image(
                        mirror_url,
                        response_cache=cls.response_cache,
                        session=session,
                        timeout=timeout,
                    )
                    if mirror_image.registry == "docker.io" and item["public"]:
                        _LOG.error(
                            "Image %s can't be mirrored to a public "
                            "quay repository.",
                            mirror_image,
                        )
                        sys.exit(ExitCodes.ERROR)

                    org_key = OrgKey(instance, org)
                    summary[org_key].append({
                        "name": item["name"],
                        "mirror": item["mirror"],
                        "server_url": server_url,
                    })
        return summary

    @staticmethod
    def sync_tag(
        tags: Iterable[str] | None,
        tags_exclude: Iterable[str] | None,
        candidate: str,
    ) -> bool:
        """
        Determine if the candidate tag should sync, tags_exclude check take precedence.
        :param tags: regex patterns to filter, match means to sync, None means no filter
        :param tags_exclude: regex patterns to filter, match means not to sync, None means no filter
        :param candidate: tag to check
        :return: bool, True means to sync, False means not to sync
        """
        if not tags and not tags_exclude:
            return True

        if not tags:
            # only tags_exclude provided
            assert tags_exclude  # mypy can't infer not None
            return not match_patterns(tags_exclude, candidate)

        if not tags_exclude:
            # only tags provided
            return match_patterns(tags, candidate)

        # both tags and tags_exclude provided
        return not match_patterns(
            tags_exclude,
            candidate,
        ) and match_patterns(
            tags,
            candidate,
        )

    def process_sync_tasks(self):
        if self.is_compare_tags:
            _LOG.warning("Making a compare-tags run. This is a slow operation.")
        summary = self.process_repos_query(
            self.repository_urls, self.exclude_repository_urls
        )
        sync_tasks = defaultdict(list)
        for org_key, data in summary.items():
            org = org_key.org_name
            for item in data:
                push_creds = self.push_creds[org_key].split(":")
                image = Image(
                    f'{item["server_url"]}/{org}/{item["name"]}',
                    username=push_creds[0],
                    password=push_creds[1],
                    response_cache=self.response_cache,
                    session=self.session,
                    timeout=REQUEST_TIMEOUT,
                )

                mirror_url = item["mirror"]["url"]

                username = None
                password = None
                mirror_creds = None
                if item["mirror"]["pullCredentials"] is not None:
                    pull_credentials = item["mirror"]["pullCredentials"]
                    raw_data = self.secret_reader.read_all(pull_credentials)
                    username = raw_data["user"]
                    password = raw_data["token"]
                    mirror_creds = f"{username}:{password}"

                image_mirror = Image(
                    mirror_url,
                    username=username,
                    password=password,
                    response_cache=self.response_cache,
                    session=self.session,
                    timeout=REQUEST_TIMEOUT,
                )

                tags = item["mirror"].get("tags")
                tags_exclude = item["mirror"].get("tagsExclude")

                for tag in image_mirror:
                    if not self.sync_tag(
                        tags=tags, tags_exclude=tags_exclude, candidate=tag
                    ):
                        continue

                    upstream = image_mirror[tag]
                    downstream = image[tag]
                    if tag not in image:
                        _LOG.debug(
                            "Image %s does not exist. Syncing it from %s",
                            downstream,
                            upstream,
                        )
                        task = {
                            "mirror_url": str(upstream),
                            "mirror_creds": mirror_creds,
                            "image_url": str(downstream),
                        }
                        sync_tasks[org_key].append(task)
                        continue

                    # Compare tags (slow) only from time to time.
                    if not self.is_compare_tags:
                        _LOG.debug(
                            "Running in non compare-tags mode. We won't check if %s "
                            "and %s are actually in sync",
                            downstream,
                            upstream,
                        )
                        continue

                    try:
                        if downstream == upstream:
                            _LOG.debug(
                                "Image %s and mirror %s are in sync",
                                downstream,
                                upstream,
                            )
                            continue
                        if downstream.is_part_of(upstream):
                            _LOG.debug(
                                "Image %s is part of mirror multi-arch image %s",
                                downstream,
                                upstream,
                            )
                            continue
                    except ImageComparisonError as details:
                        _LOG.error(
                            "Error comparing image %s and %s - %s",
                            downstream,
                            upstream,
                            details,
                        )
                        continue
                    except ImageContainsError:
                        # Upstream and downstream images are different and not part
                        # of each other. We will mirror them.
                        pass
                    finally:
                        self.response_cache_hits.inc(
                            upstream.response_cache_hits
                            + downstream.response_cache_hits
                        )
                        self.response_cache_misses.inc(
                            upstream.response_cache_misses
                            + downstream.response_cache_misses
                        )

                    _LOG.debug(
                        "Image %s and mirror %s are out of sync", downstream, upstream
                    )
                    sync_tasks[org_key].append({
                        "mirror_url": str(upstream),
                        "mirror_creds": mirror_creds,
                        "image_url": str(downstream),
                    })

        return sync_tasks

    @property
    def is_compare_tags(self) -> bool:
        if self.compare_tags is not None:
            return self.compare_tags

        return self.has_enough_time_passed_since_last_compare_tags

    @property
    def has_enough_time_passed_since_last_compare_tags(self) -> bool:
        if self._has_enough_time_passed_since_last_compare_tags is None:
            self._has_enough_time_passed_since_last_compare_tags = (
                self.check_compare_tags_elapsed_time(
                    self.control_file_path, self.compare_tags_interval
                )
            )

        return self._has_enough_time_passed_since_last_compare_tags

    @staticmethod
    def check_compare_tags_elapsed_time(path, interval) -> bool:
        try:
            with open(path, encoding="locale") as file_obj:
                last_compare_tags = float(file_obj.read())
        except FileNotFoundError:
            return True

        next_compare_tags = last_compare_tags + interval
        return time.time() >= next_compare_tags

    @staticmethod
    def record_timestamp(path) -> None:
        with open(path, "w", encoding="locale") as file_object:
            file_object.write(str(time.time()))

    def _get_push_creds(self):
        result = self.gqlapi.query(self.QUAY_ORG_CATALOG_QUERY)

        creds = {}
        for org_data in result["quay_orgs"]:
            push_secret = org_data["pushCredentials"]
            if push_secret is None:
                continue

            raw_data = self.secret_reader.read_all(push_secret)
            org = org_data["name"]
            instance = org_data["instance"]["name"]
            org_key = OrgKey(instance, org)
            creds[org_key] = f'{raw_data["user"]}:{raw_data["token"]}'

        return creds


def run(
    dry_run,
    control_file_dir: str | None,
    compare_tags: bool | None,
    compare_tags_interval: int,
    repository_urls: Iterable[str] | None,
    exclude_repository_urls: Iterable[str] | None,
):
    with QuayMirror(
        dry_run,
        control_file_dir,
        compare_tags,
        compare_tags_interval,
        repository_urls,
        exclude_repository_urls,
    ) as quay_mirror:
        quay_mirror.run()


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    with QuayMirror(dry_run=True) as quay_mirror:
        return {
            "repos": quay_mirror.process_repos_query(session=quay_mirror.session),
            "orgs": quay_mirror.push_creds,
        }

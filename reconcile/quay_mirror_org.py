import logging
import os
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from typing import Optional

from sretoolbox.container import (
    Image,
    Skopeo,
)
from sretoolbox.container.image import (
    ImageComparisonError,
    ImageContainsError,
)
from sretoolbox.container.skopeo import SkopeoCmdError

from reconcile.quay_base import get_quay_api_store
from reconcile.quay_mirror import QuayMirror

_LOG = logging.getLogger(__name__)

QONTRACT_INTEGRATION = "quay-mirror-org"
CONTROL_FILE_NAME = "qontract-reconcile-quay-mirror-org.timestamp"


class QuayMirrorOrg:
    def __init__(
        self,
        dry_run: bool = False,
        control_file_dir: Optional[str] = None,
        compare_tags: Optional[bool] = None,
        compare_tags_interval: int = 28800,  # 8 hours
        orgs: Optional[Iterable[str]] = None,
        repositories: Optional[Iterable[str]] = None,
    ) -> None:
        self.dry_run = dry_run
        self.skopeo_cli = Skopeo(dry_run)
        self.quay_api_store = get_quay_api_store()
        self.compare_tags = compare_tags
        self.compare_tags_interval = compare_tags_interval
        self.orgs = orgs
        self.repositories = repositories

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

        self._has_enough_time_passed_since_last_compare_tags: Optional[bool] = None

    def run(self):
        sync_tasks = self.process_sync_tasks()
        for org, data in sync_tasks.items():
            for item in data:
                try:
                    self.skopeo_cli.copy(
                        src_image=item["mirror_url"],
                        src_creds=item["mirror_creds"],
                        dst_image=item["image_url"],
                        dest_creds=self.get_push_creds(org),
                    )
                except SkopeoCmdError as details:
                    _LOG.error("skopeo command error message: '%s'", details)

        if self.is_compare_tags and not self.dry_run:
            QuayMirror.record_timestamp(self.control_file_path)

    def process_org_mirrors(self, summary):
        """adds new keys to the summary dict with information about mirrored
        orgs

        It collects the list of repositories in the upstream org from an API
        call and not from App-Interface.

        :param summary: summary
        :type summary: dict
        :return: summary
        :rtype: dict
        """

        for org_key, org_info in self.quay_api_store.items():
            if not org_info.get("mirror"):
                continue

            if self.orgs and org_key.org_name not in self.orgs:
                continue

            quay_api = org_info["api"]
            upstream_org_key = org_info["mirror"]
            upstream_org = self.quay_api_store[upstream_org_key]
            upstream_quay_api = upstream_org["api"]

            username = upstream_org["push_token"]["user"]
            token = upstream_org["push_token"]["token"]

            org_repos = [item["name"] for item in quay_api.list_images()]
            for repo in upstream_quay_api.list_images():
                if repo["name"] not in org_repos:
                    continue

                if self.repositories and repo["name"] not in self.repositories:
                    continue

                server_url = upstream_org["url"]
                url = f"{server_url}/{org_key.org_name}/{repo['name']}"
                data = {
                    "name": repo["name"],
                    "mirror": {
                        "url": url,
                        "username": username,
                        "token": token,
                    },
                    "mirror_filters": org_info.get("mirror_filters").get(
                        repo["name"], {}
                    ),
                }
                summary[org_key].append(data)

        return summary

    def process_sync_tasks(self):
        summary = defaultdict(list)
        self.process_org_mirrors(summary)

        sync_tasks = defaultdict(list)
        for org_key, data in summary.items():
            org = self.quay_api_store[org_key]
            org_name = org_key.org_name

            server_url = org["url"]
            username = org["push_token"]["user"]
            password = org["push_token"]["token"]

            for item in data:
                image = Image(
                    f'{server_url}/{org_name}/{item["name"]}',
                    username=username,
                    password=password,
                )

                mirror_url = item["mirror"]["url"]

                mirror_username = None
                mirror_password = None
                mirror_creds = None

                if item["mirror"].get("username") and item["mirror"].get("token"):
                    mirror_username = item["mirror"]["username"]
                    mirror_password = item["mirror"]["token"]
                    mirror_creds = f"{mirror_username}:{mirror_password}"

                image_mirror = Image(
                    mirror_url, username=mirror_username, password=mirror_password
                )

                tags = item["mirror_filters"].get("tags")
                tags_exclude = item["mirror_filters"].get("tags_exclude")

                for tag in image_mirror:
                    upstream = image_mirror[tag]
                    downstream = image[tag]

                    if not QuayMirror.sync_tag(
                        tags=tags, tags_exclude=tags_exclude, candidate=tag
                    ):
                        _LOG.debug(
                            "Image %s excluded through a mirror filter",
                            upstream,
                        )
                        continue

                    if tag not in image:
                        _LOG.debug(
                            "Image %s and mirror %s are out of sync",
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

                    _LOG.debug(
                        "Image %s and mirror %s are out of sync", downstream, upstream
                    )
                    sync_tasks[org_key].append(
                        {
                            "mirror_url": str(upstream),
                            "mirror_creds": mirror_creds,
                            "image_url": str(downstream),
                        }
                    )

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
                QuayMirror.check_compare_tags_elapsed_time(
                    self.control_file_path, self.compare_tags_interval
                )
            )

        return self._has_enough_time_passed_since_last_compare_tags

    def get_push_creds(self, org_key):
        """returns username and password for the given org

        :param org_key: org_key
        :type org_key: tuple(instance, org_name)
        :return: tuple containing username and password
        :rtype: tuple(str, str)
        """

        push_token = self.quay_api_store[org_key]["push_token"]
        username = push_token["user"]
        password = push_token["token"]
        return f"{username}:{password}"


def run(
    dry_run,
    control_file_dir: Optional[str],
    compare_tags: Optional[bool],
    compare_tags_interval: int,
    orgs: Optional[Iterable[str]],
    repositories: Optional[Iterable[str]],
):
    quay_mirror = QuayMirrorOrg(
        dry_run,
        control_file_dir,
        compare_tags,
        compare_tags_interval,
        orgs,
        repositories,
    )
    quay_mirror.run()

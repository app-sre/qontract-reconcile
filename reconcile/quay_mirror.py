import logging
import os
import re
import sys
import tempfile
import time

from collections import defaultdict, namedtuple

from sretoolbox.container.image import ImageComparisonError
from sretoolbox.container.skopeo import SkopeoCmdError

from reconcile import queries
from reconcile.status import ExitCodes
from reconcile.utils import gql, sharding
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.instrumented_wrappers import (
    InstrumentedImage as Image,
    InstrumentedSkopeo as Skopeo,
    InstrumentedCache,
)

_LOG = logging.getLogger(__name__)

QONTRACT_INTEGRATION = "quay-mirror"

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

    response_cache = InstrumentedCache(
        integration_name=QONTRACT_INTEGRATION,
        shards=sharding.SHARDS,
        shard_id=sharding.SHARD_ID,
    )

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.gqlapi = gql.get_api()
        settings = queries.get_app_interface_settings()
        self.secret_reader = SecretReader(settings=settings)
        self.skopeo_cli = Skopeo(dry_run)
        self.push_creds = self._get_push_creds()

    def run(self):
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
                    _LOG.error("[%s]", details)

    @classmethod
    def process_repos_query(cls):
        apps = queries.get_quay_repos()

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

                    mirror_image = Image(
                        item["mirror"]["url"], response_cache=cls.response_cache
                    )
                    if (
                        mirror_image.registry == "docker.io"
                        and mirror_image.repository == "library"
                        and item["public"]
                    ):
                        _LOG.error(
                            "Image %s can't be mirrored to a public "
                            "quay repository.",
                            mirror_image,
                        )
                        sys.exit(ExitCodes.ERROR)

                    org_key = OrgKey(instance, org)
                    summary[org_key].append(
                        {
                            "name": item["name"],
                            "mirror": item["mirror"],
                            "server_url": server_url,
                        }
                    )

        return summary

    @staticmethod
    def sync_tag(tags, tags_exclude, candidate):
        if tags is not None:
            for tag in tags:
                if re.match(tag, candidate):
                    return True
            # When tags is defined, we don't look at
            # tags_exclude
            return False

        if tags_exclude is not None:
            for tag_exclude in tags_exclude:
                if re.match(tag_exclude, candidate):
                    return False
            return True

        # Both tags and tags_exclude are None, so
        # tag must be synced
        return True

    def process_sync_tasks(self):
        twenty_four_hours = 86400  # 60 * 60 * 24
        is_deep_sync = self._is_deep_sync(interval=twenty_four_hours)

        summary = self.process_repos_query()
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
                            "Image %s and mirror %s are out off sync",
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

                    # Deep (slow) check only in non dry-run mode
                    if self.dry_run:
                        _LOG.debug(
                            "Image %s and mirror %s are in sync", downstream, upstream
                        )
                        continue

                    # Deep (slow) check only from time to time
                    if not is_deep_sync:
                        _LOG.debug(
                            "Image %s and mirror %s are in sync", downstream, upstream
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
                    except ImageComparisonError as details:
                        _LOG.error("[%s]", details)
                        continue

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

    def _is_deep_sync(self, interval):
        control_file_name = "qontract-reconcile-quay-mirror.timestamp"
        control_file_path = os.path.join(tempfile.gettempdir(), control_file_name)
        try:
            with open(control_file_path, "r") as file_obj:
                last_deep_sync = float(file_obj.read())
        except FileNotFoundError:
            self._record_timestamp(control_file_path)
            return True

        next_deep_sync = last_deep_sync + interval
        if time.time() >= next_deep_sync:
            self._record_timestamp(control_file_path)
            return True

        return False

    @staticmethod
    def _record_timestamp(path):
        with open(path, "w") as file_object:
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


def run(dry_run):
    quay_mirror = QuayMirror(dry_run)
    quay_mirror.run()

import logging
import os
import tempfile
import time

from collections import defaultdict

from sretoolbox.container import Image
from sretoolbox.container.image import ImageComparisonError
from sretoolbox.container import Skopeo
from sretoolbox.container.skopeo import SkopeoCmdError

from reconcile.quay_base import get_quay_api_store


_LOG = logging.getLogger(__name__)

QONTRACT_INTEGRATION = "quay-mirror-org"


class QuayMirrorOrg:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.skopeo_cli = Skopeo(dry_run)
        self.quay_api_store = get_quay_api_store()

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
                    _LOG.error("[%s]", details)

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

            quay_api = org_info["api"]
            upstream_org_key = org_info["mirror"]
            upstream_org = self.quay_api_store[upstream_org_key]
            upstream_quay_api = upstream_org["api"]

            username = upstream_org["push_token"]["user"]
            token = upstream_org["push_token"]["token"]

            repos = [item["name"] for item in quay_api.list_images()]
            for repo in upstream_quay_api.list_images():
                if repo["name"] not in repos:
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
                }
                summary[org_key].append(data)

        return summary

    def process_sync_tasks(self):
        eight_hours = 28800  # 60 * 60 * 8
        is_deep_sync = self._is_deep_sync(interval=eight_hours)

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

                for tag in image_mirror:
                    upstream = image_mirror[tag]
                    downstream = image[tag]
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
        control_file_name = "qontract-reconcile-quay-mirror-org.timestamp"
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


def run(dry_run):
    quay_mirror = QuayMirrorOrg(dry_run)
    quay_mirror.run()

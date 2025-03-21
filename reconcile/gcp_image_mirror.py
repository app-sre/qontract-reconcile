import base64
import logging
import os
import re
import tempfile
import time
from typing import Any, Self

import requests
from pydantic import BaseModel
from sretoolbox.container import (
    Image,
    Skopeo,
)
from sretoolbox.container.image import ImageComparisonError
from sretoolbox.container.skopeo import SkopeoCmdError

import reconcile.gql_definitions.gcr_mirror.gcp_projects as gql_gcp_projects
import reconcile.gql_definitions.gcr_mirror.gcr_repos as gql_gcr_repos
from reconcile import queries
from reconcile.utils import gql
from reconcile.utils.secret_reader import SecretReader

QONTRACT_INTEGRATION = "gcp-image-mirror"
REQUEST_TIMEOUT = 60


class GcrSyncItem(BaseModel):
    name: str
    mirror: gql_gcr_repos.ContainerImageMirrorV1
    server_url: str
    org_name: str


class SyncTask(BaseModel):
    mirror_creds: str
    mirror_url: str
    image_url: str
    org_name: str


class QuayMirror:
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self.gqlapi = gql.get_api()
        settings = queries.get_app_interface_settings()
        self.secret_reader = SecretReader(settings=settings)
        self.skopeo_cli = Skopeo(dry_run)
        self.push_creds = self._get_push_creds()
        self.session = requests.Session()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.session.close()

    def run(self) -> None:
        sync_tasks = self.process_sync_tasks()
        for task in sync_tasks:
            try:
                self.skopeo_cli.copy(
                    src_image=task.mirror_url,
                    src_creds=task.mirror_creds,
                    dst_image=task.image_url,
                    dest_creds=self.push_creds[task.org_name],
                )
            except SkopeoCmdError as details:
                logging.error("[%s]", details)

    def process_repos_query(self) -> list[GcrSyncItem]:
        result = gql_gcr_repos.query(self.gqlapi.query())
        summary = list[GcrSyncItem]()

        if result.apps:
            for app in result.apps:
                if app.gcr_repos:
                    for project in app.gcr_repos:
                        for gcr_repo in project.items:
                            if gcr_repo.mirror:
                                project_name = project.project.name
                                server_url = "gcr.io"
                                artifact_registry = gcr_repo.artifact_registry
                                if artifact_registry and artifact_registry.enabled:
                                    server_url = (
                                        f"{artifact_registry.location}-docker.pkg.dev"
                                    )

                                summary.append(
                                    GcrSyncItem(
                                        name=gcr_repo.name,
                                        mirror=gcr_repo.mirror,
                                        server_url=server_url,
                                        org_name=project_name,
                                    )
                                )

        return summary

    @staticmethod
    def sync_tag(
        tags: list[str] | None, tags_exclude: list[str] | None, candidate: str
    ) -> bool:
        if tags is not None:
            # When tags is defined, we don't look at tags_exclude
            return any(re.match(tag, candidate) for tag in tags)

        if tags_exclude is not None:
            for tag_exclude in tags_exclude:
                if re.match(tag_exclude, candidate):
                    return False
            return True

        # Both tags and tags_exclude are None, so
        # tag must be synced
        return True

    def process_sync_tasks(self) -> list[SyncTask]:
        eight_hours = 28800  # 60 * 60 * 8
        is_deep_sync = self._is_deep_sync(interval=eight_hours)

        summary = self.process_repos_query()

        sync_tasks = list[SyncTask]()
        for item in summary:
            image = Image(
                f"{item.server_url}/{item.org_name}/{item.name}",
                session=self.session,
                timeout=REQUEST_TIMEOUT,
            )

            mirror_url = item.mirror.url

            username = None
            password = None
            mirror_creds = None
            pull_credentials = item.mirror.pull_credentials
            if pull_credentials:
                raw_data = self.secret_reader.read_all(pull_credentials.dict())
                username = raw_data["user"]
                password = raw_data["token"]
                mirror_creds = f"{username}:{password}"

            image_mirror = Image(
                mirror_url,
                username=username,
                password=password,
                session=self.session,
                timeout=REQUEST_TIMEOUT,
            )

            if item.mirror.tags:
                for tag in item.mirror.tags:
                    if not self.sync_tag(
                        tags=item.mirror.tags,
                        tags_exclude=item.mirror.tags_exclude,
                        candidate=tag,
                    ):
                        continue

                    upstream = image_mirror.tag
                    downstream = image.tag
                    if tag not in image:
                        logging.debug(
                            "Image %s and mirror %s are out off sync",
                            downstream,
                            upstream,
                        )
                        sync_tasks.append(
                            SyncTask(
                                mirror_url=str(upstream),
                                mirror_creds=mirror_creds,
                                image_url=str(downstream),
                                org_name=item.org_name,
                            )
                        )
                        continue

                    # Deep (slow) check only in non dry-run mode
                    if self.dry_run:
                        logging.debug(
                            "Image %s and mirror %s are in sync", downstream, upstream
                        )
                        continue

                    # Deep (slow) check only from time to time
                    if not is_deep_sync:
                        logging.debug(
                            "Image %s and mirror %s are in sync", downstream, upstream
                        )
                        continue

                    try:
                        if downstream == upstream:
                            logging.debug(
                                "Image %s and mirror %s are in sync",
                                downstream,
                                upstream,
                            )
                            continue
                    except ImageComparisonError as details:
                        logging.error("[%s]", details)
                        continue

                    logging.debug(
                        "Image %s and mirror %s are out of sync", downstream, upstream
                    )
                    sync_tasks.append(
                        SyncTask(
                            mirror_url=str(upstream),
                            mirror_creds=mirror_creds,
                            image_url=str(downstream),
                            org_name=item.org_name,
                        )
                    )

        return sync_tasks

    def _is_deep_sync(self, interval: int) -> bool:
        control_file_name = "qontract-reconcile-gcr-mirror.timestamp"
        control_file_path = os.path.join(tempfile.gettempdir(), control_file_name)
        try:
            with open(control_file_path, encoding="locale") as file_obj:
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
    def _record_timestamp(path: str) -> None:
        with open(path, "w", encoding="locale") as file_object:
            file_object.write(str(time.time()))

    def _get_push_creds(self) -> dict[str, str]:
        result = gql_gcp_projects.query(self.gqlapi.query())

        creds = dict[str, str]()
        if result.projects:
            for project_data in result.projects:
                push_secret = project_data.push_credentials
                if push_secret:
                    raw_data = self.secret_reader.read_all(push_secret.dict())
                    project_name = project_data.name
                    token = base64.b64decode(raw_data["token"]).decode()
                    creds[project_name] = f"{raw_data['user']}:{token}"
        return creds


def run(dry_run: bool) -> None:
    with QuayMirror(dry_run) as gcp_image_mirror:
        gcp_image_mirror.run()

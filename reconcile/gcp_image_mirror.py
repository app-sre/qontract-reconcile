import base64
import logging
import os
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

import reconcile.gql_definitions.gcp.gcp_docker_repos as gql_gcp_repos
import reconcile.gql_definitions.gcp.gcp_projects as gql_gcp_projects
from reconcile import queries
from reconcile.gql_definitions.fragments.container_image_mirror import (
    ContainerImageMirror,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils import gql
from reconcile.utils.quay_mirror import record_timestamp, sync_tag
from reconcile.utils.secret_reader import SecretReader

QONTRACT_INTEGRATION = "gcp-image-mirror"
REQUEST_TIMEOUT = 60
GCR_SECRET_PREFIX = "gcr_"
AR_SECRET_PREFIX = "ar_"


class ImageSyncItem(BaseModel):
    mirror: ContainerImageMirror
    destination_url: str
    org_name: str


class SyncTask(BaseModel):
    mirror_creds: str | None = None
    source_url: str
    dest_url: str
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
        gql_result = gql_gcp_repos.query(query_func=self.gqlapi.query)
        processed_repos = self.process_repos_to_sync(gql_result)
        sync_tasks = self.process_sync_tasks(processed_repos)

        for task in sync_tasks:
            try:
                dest_creds = self.push_creds[f"{GCR_SECRET_PREFIX}{task.org_name}"]
                if "pkg.dev" in task.dest_url:
                    dest_creds = self.push_creds[f"{AR_SECRET_PREFIX}{task.org_name}"]

                self.skopeo_cli.copy(
                    src_image=task.source_url,
                    src_creds=task.mirror_creds,
                    dst_image=task.dest_url,
                    dest_creds=dest_creds,
                )
            except SkopeoCmdError as details:
                logging.error("[%s]", details)

    # processes the GQL repos to come up with a list of items that need to be synced
    def process_repos_to_sync(
        self, repos: gql_gcp_repos.GcpDockerReposQueryData
    ) -> list[ImageSyncItem]:
        summary = list[ImageSyncItem]()
        if repos.apps:
            for app in repos.apps:
                if app.gcr_repos:
                    for gcr_project in app.gcr_repos:
                        for gcr_repo in gcr_project.items:
                            if gcr_repo.mirror:
                                project_name = gcr_project.project.name
                                summary.append(
                                    ImageSyncItem(
                                        mirror=gcr_repo.mirror,
                                        destination_url=f"gcr.io/{project_name}/{gcr_repo.name}",
                                        org_name=project_name,
                                    )
                                )
                if app.artifact_registry_mirrors:
                    for ar_project in app.artifact_registry_mirrors:
                        for ar_repo in ar_project.items:
                            summary.append(
                                ImageSyncItem(
                                    mirror=ar_repo.mirror,
                                    destination_url=ar_repo.image_url,
                                    org_name=ar_project.project.name,
                                )
                            )

        return summary

    # second layer of processing that matches up pull/push creds with each repo and determines what tags need to be synced
    def process_sync_tasks(self, repos_to_sync: list[ImageSyncItem]) -> list[SyncTask]:
        eight_hours = 28800  # 60 * 60 * 8
        is_deep_sync = self._is_deep_sync(interval=eight_hours)

        sync_tasks = list[SyncTask]()
        for item in repos_to_sync:
            image = Image(
                f"{item.destination_url}",
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

            for tag in image_mirror:
                if not sync_tag(
                    tags=item.mirror.tags,
                    tags_exclude=item.mirror.tags_exclude,
                    candidate=tag,
                ):
                    continue

                # the Image class allows you to fetch Image information at a specific tag with a get operator
                upstream = image_mirror[tag]
                downstream = image[tag]
                if tag not in image:
                    logging.debug(
                        f"Image {image.image}: {downstream} and mirror {upstream} are out of sync"
                    )
                    sync_tasks.append(
                        SyncTask(
                            source_url=str(upstream),
                            mirror_creds=mirror_creds,
                            dest_url=str(downstream),
                            org_name=item.org_name,
                        )
                    )
                    continue

                # Deep (slow) check only in non dry-run mode
                if self.dry_run:
                    logging.debug(
                        f"Image {image.image}: {downstream} and mirror {upstream} are in sync"
                    )
                    continue

                # Deep (slow) check only from time to time
                if not is_deep_sync:
                    logging.debug(
                        f"Image {image.image}: {downstream} and mirror {upstream} are in sync"
                    )
                    continue

                try:
                    if downstream == upstream:
                        logging.debug(
                            f"Image {image.image}: {downstream} and mirror {upstream} are in sync",
                        )
                        continue
                except ImageComparisonError as details:
                    logging.error("[%s]", details)
                    continue

                logging.debug(
                    f"Image {image.image}: {downstream} and mirror {upstream} are out of sync"
                )
                sync_tasks.append(
                    SyncTask(
                        source_url=str(upstream),
                        mirror_creds=mirror_creds,
                        dest_url=str(downstream),
                        org_name=item.org_name,
                    )
                )

        return sync_tasks

    def _is_deep_sync(self, interval: int) -> bool:
        control_file_name = "qontract-reconcile-gcp-image-mirror.timestamp"
        control_file_path = os.path.join(tempfile.gettempdir(), control_file_name)
        try:
            with open(control_file_path, encoding="locale") as file_obj:
                last_deep_sync = float(file_obj.read())
        except FileNotFoundError:
            record_timestamp(control_file_path)
            return True

        next_deep_sync = last_deep_sync + interval
        if time.time() >= next_deep_sync:
            record_timestamp(control_file_path)
            return True

        return False

    def _decode_push_secret(self, secret: VaultSecret) -> str:
        raw_data = self.secret_reader.read_all(secret.dict())
        token = base64.b64decode(raw_data["token"]).decode()
        return f"{raw_data['user']}:{token}"

    def _get_push_creds(self) -> dict[str, str]:
        result = gql_gcp_projects.query(query_func=self.gqlapi.query)

        creds = dict[str, str]()
        if result.gcp_projects:
            for project_data in result.gcp_projects:
                # support old pull secret for backwards compatibility (although they are both using artifact registry on the backend)
                if project_data.gcr_push_credentials:
                    creds[f"{GCR_SECRET_PREFIX}{project_data.name}"] = (
                        self._decode_push_secret(project_data.gcr_push_credentials)
                    )
                creds[f"{AR_SECRET_PREFIX}{project_data.name}"] = (
                    self._decode_push_secret(project_data.artifact_push_credentials)
                )
        return creds


def run(dry_run: bool) -> None:
    with QuayMirror(dry_run) as gcp_image_mirror:
        gcp_image_mirror.run()

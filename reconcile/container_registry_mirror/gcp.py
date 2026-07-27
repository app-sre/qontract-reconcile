from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING, Any

import reconcile.gql_definitions.gcp.gcp_docker_repos as gql_gcp_repos
import reconcile.gql_definitions.gcp.gcp_projects as gql_gcp_projects
from reconcile import queries
from reconcile.container_registry_mirror import register
from reconcile.container_registry_mirror.deep_sync_timer import DeepSyncTimer
from reconcile.container_registry_mirror.engine import MirrorEngine
from reconcile.container_registry_mirror.mirror_spec import MirrorSpec
from reconcile.utils import gql
from reconcile.utils.instrumented_wrappers import InstrumentedSkopeo as Skopeo
from reconcile.utils.secret_reader import SecretReader

if TYPE_CHECKING:
    from reconcile.gql_definitions.fragments.vault_secret import VaultSecret

_LOG = logging.getLogger(__name__)

# Credential key prefixes distinguish GCR from Artifact Registry
# because both can exist for the same GCP project but use different
# push credentials.
GCR_SECRET_PREFIX = "gcr_"
AR_SECRET_PREFIX = "ar_"


class GcpMirror:
    """Mirrors images from any source registry into GCR or Artifact
    Registry. Satisfies the ContainerRegistryMirror protocol by
    implementing the four required methods."""

    def __init__(self) -> None:
        self.gqlapi = gql.get_api()
        settings = queries.get_app_interface_settings()
        self.secret_reader = SecretReader(settings=settings)
        # Credentials are fetched eagerly so that misconfiguration
        # (missing Vault secret, wrong path) fails immediately.
        self.push_creds = self._get_push_creds()

    def resolve_source_credentials(
        self,
        secret_ref: dict[str, Any] | None,
    ) -> str | None:
        """Read pull credentials from Vault and return in skopeo's
        "user:password" format. Returns None for public sources."""
        if secret_ref is None:
            return None
        raw_data = self.secret_reader.read_all(secret_ref)
        return f"{raw_data['user']}:{raw_data['token']}"

    def resolve_destination_credentials(self, destination_url: str) -> str:
        """Look up pre-fetched push credentials by destination URL.
        Uses the ar_ prefix for Artifact Registry (pkg.dev URLs) and
        the gcr_ prefix for GCR. Raises KeyError if the project has
        no push credentials configured."""
        # Extract the project name from the destination URL.
        # GCR: gcr.io/{project}/{image} -> project is path segment 1
        # AR: {region}-docker.pkg.dev/{project}/{repo}/{image} -> same
        parts = destination_url.split("/")
        # The project name is always the second path segment after the
        # registry hostname.
        if len(parts) < 2:
            raise KeyError(f"Cannot extract project from URL: {destination_url}")
        project_name = parts[1]

        if "pkg.dev" in destination_url:
            key = f"{AR_SECRET_PREFIX}{project_name}"
        else:
            key = f"{GCR_SECRET_PREFIX}{project_name}"

        return self.push_creds[key]

    def should_skip_mirror(
        self,
        source_registry: str,
        source_url: str,
        destination_url: str,
        destination_public: bool | None,
    ) -> bool:
        """GCP schema has no public/private flag for repositories.
        No mirrors are skipped."""
        return False

    def discover_mirrors(self) -> list[MirrorSpec]:
        """Query gcp_docker_repos from app-interface and transform
        each mirror definition into a MirrorSpec."""
        gql_result = gql_gcp_repos.query(query_func=self.gqlapi.query)

        specs: list[MirrorSpec] = []
        if not gql_result.apps:
            return specs

        for app in gql_result.apps:
            # GCR repositories: destination URL is constructed from
            # the project name and repo name.
            if app.gcr_repos:
                for gcr_project in app.gcr_repos:
                    for gcr_repo in gcr_project.items:
                        if gcr_repo.mirror is None:
                            continue

                        pull_creds_ref = None
                        if gcr_repo.mirror.pull_credentials:
                            pull_creds_ref = (
                                gcr_repo.mirror.pull_credentials.model_dump()
                            )

                        source_creds = self.resolve_source_credentials(pull_creds_ref)
                        dest_url = f"gcr.io/{gcr_project.project.name}/{gcr_repo.name}"
                        dest_creds = self.resolve_destination_credentials(dest_url)

                        specs.append(
                            MirrorSpec(
                                source_url=gcr_repo.mirror.url,
                                source_creds=source_creds,
                                destination_url=dest_url,
                                destination_creds=dest_creds,
                                tag_include=gcr_repo.mirror.tags,
                                tag_exclude=gcr_repo.mirror.tags_exclude,
                            )
                        )

            # Artifact Registry repositories: destination URL comes
            # directly from the schema's image_url field.
            if app.artifact_registry_mirrors:
                for ar_project in app.artifact_registry_mirrors:
                    for ar_repo in ar_project.items:
                        pull_creds_ref = None
                        if ar_repo.mirror.pull_credentials:
                            pull_creds_ref = (
                                ar_repo.mirror.pull_credentials.model_dump()
                            )

                        source_creds = self.resolve_source_credentials(pull_creds_ref)
                        dest_creds = self.resolve_destination_credentials(
                            ar_repo.image_url
                        )

                        specs.append(
                            MirrorSpec(
                                source_url=ar_repo.mirror.url,
                                source_creds=source_creds,
                                destination_url=ar_repo.image_url,
                                destination_creds=dest_creds,
                                tag_include=ar_repo.mirror.tags,
                                tag_exclude=ar_repo.mirror.tags_exclude,
                            )
                        )

        return specs

    def _decode_push_secret(self, secret: VaultSecret) -> str:
        """GCP service account keys are stored base64-encoded in Vault.
        Decode the token and return in skopeo's "user:password" format."""
        raw_data = self.secret_reader.read_all(secret.model_dump())
        token = base64.b64decode(raw_data["token"]).decode()
        return f"{raw_data['user']}:{token}"

    def _get_push_creds(self) -> dict[str, str]:
        """Fetch push credentials for all GCP projects from Vault.
        Both GCR and AR credentials are stored, keyed by prefix +
        project name."""
        result = gql_gcp_projects.query(query_func=self.gqlapi.query)

        creds: dict[str, str] = {}
        if not result.gcp_projects:
            return creds

        for project_data in result.gcp_projects:
            # GCR push credentials are optional (backwards compat
            # for projects that have migrated fully to AR).
            if project_data.gcr_push_credentials:
                creds[f"{GCR_SECRET_PREFIX}{project_data.name}"] = (
                    self._decode_push_secret(project_data.gcr_push_credentials)
                )
            creds[f"{AR_SECRET_PREFIX}{project_data.name}"] = self._decode_push_secret(
                project_data.artifact_push_credentials
            )

        return creds


# Equivalent of Go's init() in add_pod.go.
register("gcp-image-mirror", GcpMirror)

# Used by the integration framework for metric labels, log context,
# and early-exit cache keys.
QONTRACT_INTEGRATION = "gcp-image-mirror"
# The original gcp_image_mirror.py ran deep sync every 8 hours
# to detect mutable tag drift at the GCP fallback registry.
CONTROL_FILE_NAME = "qontract-reconcile-gcp-image-mirror.timestamp"
DEEP_SYNC_INTERVAL = 28800  # 8 hours


def run(dry_run: bool) -> None:
    """Module-level entry point called by the integration framework."""
    impl = GcpMirror()
    timer = DeepSyncTimer.from_dir(
        control_file_dir=None,
        control_file_name=CONTROL_FILE_NAME,
        interval=DEEP_SYNC_INTERVAL,
    )
    specs = impl.discover_mirrors()
    engine = MirrorEngine(
        skopeo=Skopeo(dry_run),
        dry_run=dry_run,
        deep_sync_timer=timer,
    )
    engine.sync(specs)
